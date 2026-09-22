import copy
import time
import unittest
from unittest.mock import patch
from lp_profit_bot import auto_convert as a, seller as s, spy_seller as spy
from lp_profit_bot.spy_monitor import MINT


class AutoConvertTests(unittest.TestCase):
    def setUp(self):
        from lp_profit_bot import spcx_seller,tsla_seller
        for module in (spcx_seller,tsla_seller):
            p=patch.object(module,'read_journal',return_value={'entries':[]});p.start();self.addCleanup(p.stop)

    def sale(self,signature='sale',status='finalized'):
        return {'signature':signature,'amount_raw':500000,'minimum_output_raw':14000000000,'status':status}

    def sale_receipt(self):
        return {'kind':'sale','amount_raw':500000,'net_raw':15000000000,'cost_raw':0,
                'native_before':10000000000,'slot':100}

    def test_prior_manual_conversions_and_fees_are_deducted(self):
        sales={'entries':[self.sale()]}
        conversions={'entries':[{'signature':'manual','amount_raw':10000000000,'status':'finalized'}]}
        cache={'receipts':{'sale':self.sale_receipt(),'manual':{'kind':'conversion','amount_raw':10000000000,
                'cost_raw':2507000,'net_raw':0,'native_before':25000000000,'slot':101}}}
        with patch.object(a,'receipt') as rpc:
            result=a.accounting(sales,conversions,cache)
            again=a.accounting(sales,conversions,cache)
        self.assertEqual(result,again)
        self.assertEqual(result['available_raw'],4997493000)
        self.assertEqual(result['reserve_raw'],10000000000)
        rpc.assert_not_called()

    def test_pending_and_failed_conversions_remain_reserved(self):
        for status in ('pending','failed'):
            result=a.accounting({'entries':[self.sale()]},{'entries':[{'signature':'x','amount_raw':10000000000,'status':status}]},
                                {'receipts':{'sale':self.sale_receipt()}})
            self.assertEqual(result['available_raw'],4990000000)

    def test_pending_sales_never_authorize_conversion(self):
        result=a.accounting({'entries':[self.sale(status='pending')]},{'entries':[]},{'receipts':{}})
        self.assertEqual(result['available_raw'],0)
        self.assertIsNone(result['reserve_raw'])

    def test_conversion_cannot_spend_existing_or_external_xnt(self):
        ledger={'reserve_raw':10000000000,'available_raw':5000000000}
        snapshot={'native_balance':100000000000,'rent':2039280}
        self.assertEqual(a.planned_amount(ledger,snapshot),4990000000)
        snapshot['native_balance']=12000000000
        self.assertEqual(a.planned_amount(ledger,snapshot),1990000000)
        snapshot['native_balance']=10000000000
        self.assertEqual(a.planned_amount(ledger,snapshot),0)

    def test_batch_limit_and_dust(self):
        snap={'native_balance':100000000000,'rent':2039280}
        self.assertEqual(a.planned_amount({'reserve_raw':10000000000,'available_raw':50000000000},snap),a.MAX_BATCH)
        self.assertEqual(a.planned_amount({'reserve_raw':10000000000,'available_raw':59999999},snap),0)

    def test_receipt_must_match_spy_debit_and_signature(self):
        def tokens(amount):
            return [{'owner':s.WALLET,'mint':MINT,'uiTokenAmount':{'decimals':8,'amount':str(amount)}}]
        tx={'slot':100,'transaction':{'signatures':['sale'],'message':{'accountKeys':[s.WALLET]}},
            'meta':{'err':None,'fee':2507000,'preBalances':[10000000000],'postBalances':[25000000000],
                    'preTokenBalances':tokens(1000000),'postTokenBalances':tokens(500000)}}
        with patch.object(s,'rpc',return_value=tx):
            self.assertEqual(a.receipt(self.sale(),'sale')['net_raw'],15000000000)
            for change in ('signature','amount','failed'):
                bad=copy.deepcopy(tx)
                if change=='signature':bad['transaction']['signatures']=['wrong']
                elif change=='amount':bad['meta']['postTokenBalances']=tokens(499999)
                else:bad['meta']['err']={'failure':1}
                with patch.object(s,'rpc',return_value=bad),self.assertRaises(s.SellerError):
                    a.receipt(self.sale(),'sale')

    def test_failed_auto_conversion_halts(self):
        with patch.object(a.conversion,'ready',return_value=True),patch.object(spy,'read_journal',return_value={'entries':[]}), \
             patch.object(spy,'reconcile',return_value=True),patch.object(a.conversion,'read_journal',return_value={'entries':[{'status':'failed','source':'spy_proceeds_auto'}]}), \
             patch.object(a.conversion,'execute_locked') as send:
            with self.assertRaises(s.SellerError):a.locked_cycle(True)
            send.assert_not_called()

    def test_pending_conversion_blocks_receipt_loading_and_submission(self):
        with patch.object(a.conversion,'ready',return_value=False),patch.object(a,'accounting') as account,patch.object(a.conversion,'execute_locked') as send:
            self.assertEqual(a.locked_cycle(True)['status'],'WAITING_FOR_CONVERSION_FINALITY')
            account.assert_not_called();send.assert_not_called()

    def test_busy_lock_waits_instead_of_stopping_sellers(self):
        with patch.object(spy,'native_lock',side_effect=spy.NativeSwapBusy('busy')):
            self.assertEqual(a.cycle(True)['status'],'WAITING_FOR_NATIVE_SWAP')
            self.assertEqual(spy.cycle(True)['status'],'WAITING_FOR_NATIVE_SWAP')

    def test_automatic_conversion_simulation_does_not_send(self):
        ledger={'available_raw':5000000000,'reserve_raw':10000000000}
        with patch.object(a.conversion,'ready',return_value=True),patch.object(spy,'read_journal',return_value={'entries':[]}), \
             patch.object(spy,'reconcile',return_value=True),patch.object(a.conversion,'read_journal',return_value={'entries':[]}), \
             patch.object(a,'load_cache',return_value={}),patch.object(a,'accounting',return_value=ledger), \
             patch.object(a.native_swaps,'xnt_snapshot',return_value={'native_balance':15000000000,'rent':2039280}), \
             patch.object(a.native_swaps,'xnt_quote',return_value=(1000000,995000)), \
             patch.object(a.native_swaps,'simulate',return_value=(None,None,None,1000000)), \
             patch.object(a.conversion,'execute_locked') as send:
            self.assertEqual(a.locked_cycle(False)['status'],'SIMULATION_PASSED')
            send.assert_not_called()
            self.assertEqual(a.locked_cycle(True)['status'],'SUBMITTED_PENDING_FINALITY')
            self.assertEqual(send.call_args.kwargs,{'source':'stock_proceeds_auto','native_floor':10000000000})

    def test_reserve_rechecked_before_conversion_signing(self):
        with patch.object(a.conversion,'ready',return_value=True),patch.object(a.conversion,'spy_journal',return_value={}), \
             patch.object(a.conversion,'reconcile_spy',return_value=True), \
             patch.object(a.native_swaps,'xnt_snapshot',return_value={'native_balance':11000000000}), \
             patch.object(s,'load_wallet') as signer:
            with self.assertRaises(s.SellerError):
                a.conversion.execute_locked({'amount_raw':2000000000,'expires_at':time.time()+30},native_floor=10000000000)
            signer.assert_not_called()
