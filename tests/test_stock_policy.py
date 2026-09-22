import json
import tempfile
import time
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from solders.hash import Hash
from solders.pubkey import Pubkey
from lp_profit_bot import meta_seller,coin_seller,pltr_seller,amd_seller,nvda_seller
from lp_profit_bot import stock_policy as p,spcx_seller,tsla_seller,spy_seller,native_swaps as n,seller as s,xnt_conversion as x,auto_convert as auto

class StockPolicyTests(unittest.TestCase):
    def snapshot(self,key):
        stock=p.STOCKS[key]
        return {'sell_mint':stock.mint,'sell_pool':stock.pool,'balance_in':10000000,'native_balance':10000000000,
                'reserve_in':100000000,'reserve_out':5000000000000,'xnt_usd':Decimal('.3'),
                'trade_fee':2800,'protocol_fee':250000,'fund_fee':50000,'rent':2039280,
                'pool':{'mints':[stock.mint,s.WXNT],'vaults':[str(Pubkey.new_unique()),str(Pubkey.new_unique())],
                        'observation':str(Pubkey.new_unique())}}

    def test_approved_mints_and_buffers_are_explicit(self):
        self.assertEqual(set(p.STOCKS),{'spy','spcx','tsla','meta','coin','pltr','amd','nvda'})
        self.assertEqual(p.VALUATION_FACTOR,Decimal('.95'))
        self.assertIsNone(p.public_policy()['total_cap'])
        self.assertIsNone(p.public_policy()['per_trade_cap'])

    def test_new_sellers_use_own_mint_and_pool_without_amount_caps(self):
        for key,module in [('spcx',spcx_seller),('tsla',tsla_seller),('meta',meta_seller),('coin',coin_seller),('pltr',pltr_seller),('amd',amd_seller),('nvda',nvda_seller)]:
            snap=self.snapshot(key);plan=module.plan(snap,Decimal('350'))
            self.assertEqual(plan['amount_raw'],snap['balance_in'])
            self.assertGreaterEqual(plan['minimum_output_raw'],module.minimum_output(plan['amount_raw'],Decimal('350'),snap['xnt_usd']))
            tx=n.build(snap,plan['amount_raw'],plan['minimum_output_raw'],str(Hash.default()),sell_spy=True)
            swap=tx.message.instructions[-2];keys=tx.message.account_keys
            self.assertEqual(str(keys[swap.accounts[3]]),p.STOCKS[key].pool)
            self.assertEqual(str(keys[swap.accounts[10]]),p.STOCKS[key].mint)
            self.assertEqual(str(keys[swap.accounts[4]]),s.associated(p.STOCKS[key].mint))
            self.assertIsNone(module.plan(snap,Decimal('2000')))

    def test_unknown_stock_route_rejected(self):
        snap=self.snapshot('tsla');snap['sell_mint']=s.GOOGL_MINT
        with self.assertRaises(s.SellerError):n.build(snap,100,100,str(Hash.default()),sell_spy=True)

    def test_journals_are_separate_and_mint_bound(self):
        self.assertNotEqual(spcx_seller.STATE,tsla_seller.STATE)
        for key,module in [('spcx',spcx_seller),('tsla',tsla_seller),('meta',meta_seller),('coin',coin_seller),('pltr',pltr_seller),('amd',amd_seller),('nvda',nvda_seller)]:
            with tempfile.TemporaryDirectory() as tmp:
                file=Path(tmp)/'journal.json';j=module.read_journal(file)
                self.assertEqual(j['mint'],p.STOCKS[key].mint)
                j['mint']=p.STOCKS['spy'].mint;file.write_text(json.dumps(j))
                with self.assertRaises(s.SellerError):module.read_journal(file)

    def test_pending_stock_blocks_other_native_trades(self):
        with patch.object(x,'spy_journal',return_value={}),patch.object(x,'reconcile_spy',return_value=True), \
             patch.object(spcx_seller,'read_journal',return_value={}),patch.object(spcx_seller,'reconcile',return_value=False), \
             patch.object(tsla_seller,'read_journal') as tsla:
            self.assertFalse(x.stock_sales_ready());tsla.assert_not_called()

    def test_combined_stock_proceeds_preserve_original_reserve(self):
        sales={'entries':[]};cache={'receipts':{}}
        for i,key in enumerate(('spy','spcx','tsla')):
            sales['entries'].append({'signature':key,'amount_raw':100,'status':'finalized','asset_mint':p.STOCKS[key].mint})
            cache['receipts'][key]={'kind':'sale','amount_raw':100,'net_raw':1000000000,'cost_raw':0,
                                   'native_before':10000000000+i*1000000000,'slot':100+i,'asset_mint':p.STOCKS[key].mint}
        ledger=auto.accounting(sales,{'entries':[]},cache)
        self.assertEqual(ledger['proceeds_raw'],3000000000)
        self.assertEqual(ledger['reserve_raw'],10000000000)
        cache['receipts']['tsla']['asset_mint']=p.STOCKS['spy'].mint
        with self.assertRaises(s.SellerError):auto.accounting(sales,{'entries':[]},cache)

    def test_new_worker_does_not_sign_when_no_inventory(self):
        for key,module in [('spcx',spcx_seller),('tsla',tsla_seller),('meta',meta_seller),('coin',coin_seller),('pltr',pltr_seller),('amd',amd_seller),('nvda',nvda_seller)]:
            snap=self.snapshot(key);snap['balance_in']=0
            with patch.object(x,'ready',return_value=True),patch.object(x,'stock_sales_ready',return_value=True), \
                 patch.object(module,'read_journal',return_value={'entries':[],'halted':False}), \
                 patch.object(module,'reference_price',return_value=(Decimal('350'),time.time())), \
                 patch.object(module,'snapshot',return_value=snap),patch.object(module,'prepare',side_effect=lambda s:s), \
                 patch.object(module,'load_wallet') as sign:
                self.assertEqual(module.locked_cycle(True)['status'],'HOLD');sign.assert_not_called()

    def test_snapshot_retains_requested_stock_mint(self):
        import hashlib,struct
        from lp_profit_bot import spy_quotes
        for key in ('spcx','tsla','meta','coin','pltr','amd','nvda'):
            stock=p.STOCKS[key]
            pool={'config':s.CONFIG,'vaults':['a','b'],'mints':[s.WXNT,stock.mint],
                  'programs':[spy_quotes.LEGACY_TOKEN,s.TOKEN],'decimals':[9,8],
                  'protocol_fees':[0,0],'fund_fees':[0,0]}
            valuation={'config':s.CONFIG,'vaults':['c','d'],'mints':[s.WXNT,s.USDC_MINT],
                       'programs':[spy_quotes.LEGACY_TOKEN,s.TOKEN],'decimals':[9,6],
                       'protocol_fees':[0,0],'fund_fees':[0,0]}
            raw=bytearray(236);raw[:8]=hashlib.sha256(b'account:AmmConfig').digest()[:8]
            struct.pack_into('<3Q',raw,12,2800,250000,50000)
            a=[{} for _ in range(10)];a[9]={'owner':'11111111111111111111111111111111','lamports':10000000000}
            with patch.object(s,'accounts',side_effect=[{'value':[{},{}],'context':{'slot':1}},{'value':a,'context':{'slot':2}}]), \
                 patch.object(s,'decode_pool',side_effect=[pool,valuation,pool,valuation]), \
                 patch.object(s,'check_mint'),patch.object(s,'raw_account',return_value=bytes(raw)), \
                 patch.object(s,'token_balance',side_effect=[1000000000000,100000000,1000000000000,300000000,123456]) as balances:
                result=spy_quotes.snapshot(stock.mint,stock.pool)
            self.assertEqual(result['sell_mint'],stock.mint)
            self.assertEqual(result['input_index'],1)
            self.assertEqual(result['balance_in'],123456)
            self.assertEqual(balances.call_args.args[1],stock.mint)
