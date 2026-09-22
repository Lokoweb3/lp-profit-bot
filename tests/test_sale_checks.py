import importlib
import time
import unittest
from decimal import Decimal
from unittest.mock import patch
from lp_profit_bot import seller,xnt_conversion,stock_policy
from lp_profit_bot.sale_checks import pre_sign_delta

class DeltaTests(unittest.TestCase):
    def snapshot(self):
        return {'reserve_in':100000000,'reserve_out':1500000000000,'xnt_usd':Decimal('.3'),
                'balance_in':10000000,'trade_fee':2800,'protocol_fee':250000,'fund_fee':50000,
                'received':time.monotonic()}

    def test_positive_buffered_delta_and_costs(self):
        s=self.snapshot();p={'amount_raw':1000000,'minimum_output_raw':1}
        self.assertTrue(pre_sign_delta(s,p,Decimal('350'),time.time())['qualifies'])
        for price in ['450','451','430']:
            self.assertFalse(pre_sign_delta(s,p,Decimal(price),time.time())['qualifies'])
        p['amount_raw']=1
        self.assertFalse(pre_sign_delta(s,p,Decimal('350'),time.time())['qualifies'])

    def test_stale_data_never_qualifies(self):
        s=self.snapshot();p={'amount_raw':1000000,'minimum_output_raw':1}
        with self.assertRaises(seller.SellerError):pre_sign_delta(s,p,Decimal('350'),time.time()-301)
        s['received']-=31
        with self.assertRaises(seller.SellerError):pre_sign_delta(s,p,Decimal('350'),time.time())

    def test_googl_requires_positive_delta_and_costs(self):
        s=self.snapshot();s['reserve_out']=450000000
        p={'amount_raw':500000,'minimum_output_raw':1}
        self.assertTrue(pre_sign_delta(s,p,Decimal('350'),time.time(),native=False)['qualifies'])
        self.assertFalse(pre_sign_delta(s,p,Decimal('450'),time.time(),native=False)['qualifies'])

    def test_all_stock_sellers_hold_without_signing_when_delta_disappears(self):
        for key in stock_policy.STOCKS:
            m=importlib.import_module('lp_profit_bot.'+key+'_seller')
            first=self.snapshot();last=self.snapshot();last['reserve_out']=1000000000000
            with patch.object(xnt_conversion,'ready',return_value=True),patch.object(xnt_conversion,'stock_sales_ready',return_value=True),patch.object(m,'read_journal',return_value={'entries':[],'halted':False}),patch.object(m,'reference_price',return_value=(Decimal('350'),time.time())),patch.object(m,'snapshot',side_effect=[first,last]),patch.object(m,'prepare',side_effect=lambda s:s),patch.object(m,'plan',return_value={'amount_raw':1000000,'minimum_output_raw':1}),patch.object(m,'simulate',return_value=(None,{},1,1)),patch.object(m,'load_wallet') as signing,patch.object(m,'rpc') as rpc:
                report=m.locked_cycle(True)
                self.assertEqual(report['status'],'HOLD',key)
                self.assertFalse(report['delta_check']['qualifies'])
                signing.assert_not_called();rpc.assert_not_called()
