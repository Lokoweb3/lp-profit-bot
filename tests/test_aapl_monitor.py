import time
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from lp_profit_bot import aapl_monitor as aapl, dashboard, seller


class AaplMonitorTests(unittest.TestCase):
    def test_snapshot_validates_route_and_reports_balance(self):
        now=time.time()
        pool={'address':aapl.POOL,
              'baseToken':{'address':aapl.MINT,'symbol':'AAPL.X','decimals':8},
              'quoteToken':{'address':seller.WXNT,'symbol':'XNT'},
              'priceUsd':350,'liquidity':500,
              'lastSyncedAt':datetime.now(timezone.utc).isoformat()}
        reference={aapl.REFERENCE:{'usd':340,'last_updated_at':now}}
        with patch.object(aapl,'load_key',return_value='test'), \
             patch.object(aapl,'NinjaClient') as client, \
             patch.object(aapl,'fetch_reference',return_value=reference) as fetch, \
             patch.object(seller,'rpc',return_value={'value':[]}):
            client.return_value.pool.return_value={'pool':pool}
            value=aapl.snapshot()
            self.assertEqual(value['balance'],'0')
            self.assertTrue(value['fresh'])
            self.assertAlmostEqual(float(value['gap_percent']),2.94117647)
            fetch.assert_called_once_with('apple-xstock')
            pool['baseToken']['address']=seller.GOOGL_MINT
            with self.assertRaises(seller.SellerError):
                aapl.snapshot()

    def test_stale_data_suppresses_aapl_premium(self):
        cache=dashboard.DashboardData();now=time.time()
        cache.aapl={'fetched_at':now,'pool_updated_at':now-301,
                    'reference_updated_at':now,'fresh':True,'gap_percent':'3'}
        with patch.object(seller,'read_journal',return_value={'halted':False,'entries':[]}), \
             patch.object(dashboard,'seller_running',return_value=False), \
             patch.object(dashboard,'read_public_file',return_value=(None,None)):
            result=cache.status()
        self.assertFalse(result['aapl']['fresh'])
        self.assertIsNone(result['aapl']['gap_percent'])
        self.assertEqual(cache.aapl['gap_percent'],'3')
