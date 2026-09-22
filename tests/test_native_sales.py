import base64
import struct
import tempfile
import time
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from solders.hash import Hash
from solders.pubkey import Pubkey
from solders.signature import Signature
from lp_profit_bot import seller as s, spy_seller as spy, native_swaps as native, xnt_conversion as convert
from lp_profit_bot.spy_monitor import MINT, POOL
from lp_profit_bot.spy_quotes import LEGACY_TOKEN


def token(mint,qty):
    raw=bytearray(170); raw[:32]=bytes(Pubkey.from_string(mint));raw[32:64]=bytes(Pubkey.from_string(s.WALLET))
    struct.pack_into('<Q',raw,64,qty);raw[108]=1
    return {'owner':s.TOKEN,'executable':False,'data':[base64.b64encode(raw).decode(),'base64']}


def snapshot(spy_mode=True):
    return {'reserve_in':100_000_000,'reserve_out':3_500_000_000_000,'trade_fee':2800,
        'protocol_fee':250000,'fund_fee':50000,'balance_in':5_000_000,'balance_out':0,
        'native_balance':10_000_000_000,'xnt_usd':Decimal('.3'),'rent':2039280,
        'slot':1,'received':time.monotonic(),'pool':{'mints':[MINT if spy_mode else s.WXNT,s.WXNT if spy_mode else s.USDC_MINT],
        'vaults':[str(Pubkey.new_unique()),str(Pubkey.new_unique())],'observation':str(Pubkey.new_unique())}}


class NativeSalesTests(unittest.TestCase):
    def setUp(self):
        self.ready_patch=patch.object(convert,'stock_sales_ready',return_value=True)
        self.ready_patch.start();self.addCleanup(self.ready_patch.stop)

    def test_spy_plan_uses_inventory_without_old_batch_limit(self):
        snap=snapshot()
        p=spy.plan(snap,Decimal('750'))
        self.assertEqual(p['amount_raw'],snap['balance_in'])
        self.assertGreater(p['amount_raw'],500000)
        self.assertGreaterEqual(p['minimum_output_raw'],spy.minimum_output(p['amount_raw'],Decimal('750'),Decimal('.3')))
        snap['balance_in']=200000
        self.assertEqual(spy.plan(snap,Decimal('750'))['amount_raw'],200000)
        self.assertIsNone(spy.plan(snap,Decimal('1100')))
        snap['balance_in']=1
        self.assertIsNone(spy.plan(snap,Decimal('750')))

    def test_transaction_closes_only_temporary_account_and_uses_correct_programs(self):
        for spy_mode in (True,False):
            snap=snapshot(spy_mode)
            tx=native.build(snap,500000,100000,str(Hash.default()),sell_spy=spy_mode)
            keys=tx.message.account_keys
            self.assertEqual(tx.signatures,[Signature.default()])
            swap=tx.message.instructions[-2];close=tx.message.instructions[-1]
            self.assertEqual(str(keys[swap.program_id_index]),s.XDEX_PROGRAM)
            self.assertEqual(struct.unpack('<QQ',swap.data[8:]),(500000,100000))
            self.assertEqual(str(keys[swap.accounts[3]]),POOL if spy_mode else s.XNT_POOL)
            self.assertEqual(str(keys[swap.accounts[8]]),s.TOKEN if spy_mode else LEGACY_TOKEN)
            self.assertEqual(str(keys[swap.accounts[9]]),LEGACY_TOKEN if spy_mode else s.TOKEN)
            self.assertEqual(close.data,b'\x09')
            self.assertEqual(str(keys[close.accounts[0]]),native.temporary_account())
            self.assertEqual(str(keys[close.accounts[1]]),s.WALLET)

    def test_simulation_validates_spy_debit_native_proceeds_and_closure(self):
        snap=snapshot(); amount=500000; minimum=10000000
        def run(debit=amount,credit=minimum-5000,closed=None):
            replies=[{'value':{'blockhash':str(Hash.default()),'lastValidBlockHeight':1}}, {'value':5000},
                {'context':{'slot':2},'value':{'err':None,'accounts':[token(MINT,snap['balance_in']-debit),
                {'owner':'11111111111111111111111111111111','lamports':snap['native_balance']+credit},closed]}}]
            with patch.object(s,'rpc',side_effect=replies),patch.object(s,'load_wallet') as signer:
                result=native.simulate(snap,amount,minimum,sell_spy=True)
                signer.assert_not_called()
                return result
        run()
        run(closed={'lamports':0,'owner':'11111111111111111111111111111111','data':['','base64']})
        for kwargs in ({'debit':amount+1},{'credit':minimum-5001},{'closed':{'lamports':1}}):
            with self.assertRaises(s.SellerError): run(**kwargs)

    def test_conversion_amount_and_reserve(self):
        self.assertEqual(convert.amount_raw('1.000000001'),1000000001)
        for value in ('0','-1','NaN','Infinity','0.0000000001'):
            with self.assertRaises(s.SellerError):convert.amount_raw(value)
        snap=snapshot(False)
        output,minimum=native.xnt_quote(snap,1000000000)
        self.assertEqual(minimum,output*995//1000)
        with self.assertRaises(s.SellerError):native.xnt_quote(snap,snap['native_balance'])

    def test_spy_pending_blocks_next_trade_and_failed_halts(self):
        j={'wallet':s.WALLET,'cap_raw':None,'halted':False,
           'entries':[{'signature':str(Signature.default()),'amount_raw':500000,'status':'pending'}]}
        with patch.object(spy,'rpc',return_value={'value':[None]}):self.assertFalse(spy.reconcile(j))
        with patch.object(spy,'rpc',return_value={'value':[{'confirmationStatus':'finalized','err':{'error':1}}]}),patch.object(spy,'atomic_write'):
            self.assertTrue(spy.reconcile(j))
        self.assertTrue(j['halted']);self.assertEqual(j['entries'][0]['amount_raw'],500000)

    def test_spy_journal_separate_cap_and_corruption(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'spy.json';j=spy.read_journal(path)
            self.assertIsNone(j['cap_raw'])
            j['cap_raw']=s.LEGACY_CAP_RAW;path.write_text(__import__('json').dumps(j))
            with self.assertRaises(s.SellerError):spy.read_journal(path)

    def test_expired_conversion_never_loads_signer(self):
        with patch.object(convert,'native_lock'),patch.object(s,'load_wallet') as signer:
            with self.assertRaises(s.SellerError):convert.execute({'expires_at':time.time()-1})
            signer.assert_not_called()

    def test_previous_total_does_not_prevent_new_sales(self):
        j={'halted':False,'entries':[{'status':'finalized','amount_raw':5000000}]}
        snap=snapshot();snap['balance_in']=0
        with patch.object(convert,'ready',return_value=True),patch.object(spy,'read_journal',return_value=j), \
             patch.object(spy,'reference_price',return_value=(Decimal('750'),time.time())) as ref, \
             patch.object(spy,'snapshot',return_value=snap),patch.object(spy,'prepare',side_effect=lambda x:x):
            self.assertEqual(spy.locked_cycle(True)['status'],'HOLD')
            ref.assert_called_once()

    def test_spy_dry_run_never_signs_and_live_reserves_before_send(self):
        import json
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from lp_profit_bot.wallet import base58, public_bytes
        key=Ed25519PrivateKey.generate();wallet=base58(public_bytes(key))
        snap=snapshot();p=spy.plan(snap,Decimal('750'))
        with patch.object(s,'WALLET',wallet),patch.object(spy,'WALLET',wallet):
            unsigned=native.build(snap,p['amount_raw'],p['minimum_output_raw'],str(Hash.default()),sell_spy=True)
            for live in (False,True):
                j={'wallet':wallet,'cap_raw':None,'halted':False,'entries':[]};saved=[]
                def broadcast(method,params):
                    self.assertEqual(method,'sendTransaction')
                    self.assertEqual(saved[-1]['entries'][0]['status'],'pending')
                    self.assertEqual(saved[-1]['entries'][0]['amount_raw'],p['amount_raw'])
                    self.assertFalse(params[1]['skipPreflight'])
                    raise s.SellerError('Unknown submission result')
                with patch.object(convert,'ready',return_value=True),patch.object(spy,'read_journal',return_value=j), \
                     patch.object(spy,'reference_price',return_value=(Decimal('750'),time.time())), \
                     patch.object(spy,'snapshot',return_value=snap),patch.object(spy,'prepare',side_effect=lambda x:x), \
                     patch.object(spy,'simulate',return_value=(unsigned,{'lastValidBlockHeight':5},2,p['minimum_output_raw'])), \
                     patch.object(spy,'load_wallet',return_value=key) as signer, \
                     patch.object(spy,'atomic_write',side_effect=lambda path,data:saved.append(json.loads(json.dumps(data)))), \
                     patch.object(spy,'rpc',side_effect=broadcast) as rpc:
                    if live:
                        with self.assertRaises(s.SellerError):spy.locked_cycle(True)
                        self.assertEqual(j['entries'][0]['status'],'pending');rpc.assert_called_once()
                    else:
                        self.assertEqual(spy.locked_cycle(False)['status'],'SIMULATION_PASSED')
                        signer.assert_not_called();rpc.assert_not_called()


    def test_legacy_spy_history_migrates_without_losing_entries(self):
        import json
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'spy.json'
            row={'signature':str(Signature.default()),'amount_raw':500000,'status':'finalized'}
            journal={'wallet':s.WALLET,'cap_raw':5000000,'halted':False,'entries':[row]}
            path.write_text(json.dumps(journal))
            migrated=spy.read_journal(path)
            self.assertIsNone(migrated['cap_raw'])
            self.assertEqual(migrated['entries'],[row])
            migrated['entries'][0]['amount_raw']=6000000
            path.write_text(json.dumps(migrated))
            self.assertEqual(spy.read_journal(path)['entries'][0]['amount_raw'],6000000)

    def test_large_inventory_still_respects_reference_buffer(self):
        snap=snapshot();snap['balance_in']=100000000
        p=spy.plan(snap,Decimal('750'))
        self.assertIsNotNone(p)
        self.assertGreater(p['amount_raw'],500000)
        self.assertLess(p['amount_raw'],snap['balance_in'])
        self.assertGreaterEqual(Decimal(p['ending_pool_price_usd'])*Decimal('.95'),Decimal('750'))
        self.assertGreaterEqual(p['estimated_output_raw'],p['minimum_output_raw'])
