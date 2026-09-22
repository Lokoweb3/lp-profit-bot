import time
import unittest
from datetime import datetime,timezone
from unittest.mock import patch
from lp_profit_bot import spcx_monitor as m,seller,dashboard

class SpcxTests(unittest.TestCase):
    def test_valid_market_and_wrong_mint(self):
        pool={'address':m.POOL,'baseToken':{'address':m.MINT,'symbol':'SPCX.X','decimals':8},
              'quoteToken':{'address':seller.WXNT,'symbol':'XNT'},'priceUsd':180,'liquidity':460,
              'lastSyncedAt':datetime.now(timezone.utc).isoformat()}
        with patch.object(m,'load_key',return_value='test'),patch.object(m,'NinjaClient') as client, \
             patch.object(m,'fetch_reference',return_value={'spacex-xstocks':{'usd':150,'last_updated_at':time.time()}}) as ref, \
             patch.object(seller,'rpc',return_value={'value':[]}):
            client.return_value.pool.return_value={'pool':pool}
            value=m.snapshot();self.assertEqual(value['balance'],'0');self.assertEqual(value['gap_percent'],'20.0')
            ref.assert_called_once_with('spacex-xstocks')
            pool['baseToken']['address']=seller.GOOGL_MINT
            with self.assertRaises(seller.SellerError):m.snapshot()

    def test_stale_spcx_does_not_change_spy_or_cached_values(self):
        data=dashboard.DashboardData();now=time.time()
        data.spcx={'fetched_at':now,'pool_updated_at':now-301,'reference_updated_at':now,'fresh':True,'gap_percent':'20'}
        with patch.object(seller,'read_journal',return_value={'halted':False,'entries':[]}), \
             patch.object(dashboard,'seller_running',return_value=False),patch.object(dashboard,'read_public_file',return_value=(None,None)):
            result=data.status()
        self.assertFalse(result['spcx']['fresh']);self.assertIsNone(result['spcx']['gap_percent'])
        self.assertEqual(data.spcx['gap_percent'],'20');self.assertIsNone(result['spy'])
