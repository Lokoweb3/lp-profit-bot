import unittest
from unittest.mock import patch
from lp_profit_bot import activity as a

class ActivityTests(unittest.TestCase):
    def setUp(self):
        for module in (a.spcx_seller,a.tsla_seller,a.meta_seller,a.coin_seller,a.pltr_seller,a.amd_seller,a.nvda_seller):
            p=patch.object(module,'read_journal',return_value={'entries':[]});p.start();self.addCleanup(p.stop)
        p=patch.object(a.auto_bridge,'read_journal',return_value={'entries':[]});p.start();self.addCleanup(p.stop)

    def test_bridge_completion_appears_once_without_private_fields(self):
        f=a.ActivityFeed()
        row={'signature':'source','amount_raw':100_000_000,'status':'completed',
             'destination_signature':'destination','private_key':'SECRET'}
        with patch.object(a.seller,'read_journal',return_value={'entries':[]}), \
             patch.object(a.spy_seller,'read_journal',return_value={'entries':[]}), \
             patch.object(a.xnt_conversion,'read_journal',return_value={'entries':[]}), \
             patch.object(a.auto_bridge,'read_journal',return_value={'entries':[row]}), \
             patch.object(a.worker_control,'status',return_value={}):
            f.refresh();f.refresh()
        events=f.snapshot()['events']
        self.assertEqual(len(events),1)
        self.assertEqual(events[0]['source'],'bridge')
        self.assertIn('COMPLETED',events[0]['message'])
        self.assertNotIn('SECRET',str(events))

    def test_pending_to_finalized_and_no_secret_fields(self):
        row={'signature':'example','amount_raw':500000,'minimum_output_raw':12000000000,
             'status':'pending','created_at':'2026-09-19T03:00:00+00:00','private_key':'SECRET'}
        f=a.ActivityFeed()
        with patch.object(a.seller,'read_journal',return_value={'entries':[]}), \
             patch.object(a.spy_seller,'read_journal',return_value={'entries':[row]}), \
             patch.object(a.xnt_conversion,'read_journal',return_value={'entries':[]}), \
             patch.object(a.worker_control,'status',return_value={}), \
             patch.object(a.seller,'rpc',side_effect=[{'value':[None]},{'value':[{'confirmationStatus':'finalized','err':None}]}]):
            f.refresh();f.refresh();f.refresh()
        events=f.snapshot()['events']
        self.assertEqual(len(events),2)
        self.assertIn('PENDING',events[0]['message']);self.assertIn('FINALIZED',events[1]['message'])
        self.assertEqual(events[1]['signature'],'example')
        self.assertNotIn('SECRET',str(events));self.assertNotIn('private_key',str(events))

    def test_rpc_failure_is_not_transaction_failure(self):
        row={'signature':'example','amount_raw':1,'status':'pending'}
        f=a.ActivityFeed()
        with patch.object(a.seller,'read_journal',return_value={'entries':[]}), \
             patch.object(a.spy_seller,'read_journal',return_value={'entries':[row]}), \
             patch.object(a.xnt_conversion,'read_journal',return_value={'entries':[]}), \
             patch.object(a.worker_control,'status',return_value={}), \
             patch.object(a.seller,'rpc',side_effect=ValueError('SECRET')):
            f.refresh()
        events=f.snapshot()['events']
        self.assertNotIn('FAILED',str(events));self.assertNotIn('SECRET',str(events))
        self.assertIn('PENDING',str(events))

    def test_feed_is_bounded(self):
        f=a.ActivityFeed()
        for i in range(300):f.add('spy',str(i))
        self.assertEqual(len(f.snapshot()['events']),250)
        self.assertEqual(f.snapshot()['events'][0]['id'],51)
