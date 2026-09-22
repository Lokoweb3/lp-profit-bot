import unittest
from contextlib import nullcontext
from unittest.mock import patch
from lp_profit_bot import meta_seller as m

class MetaRetryTests(unittest.TestCase):
    def test_watch_recovers_from_reference_failure(self):
        with patch.object(m.sys,'argv',['meta','--live','--watch']), patch.object(m,'process_lock',return_value=nullcontext()), patch.object(m,'runtime_status') as status, patch.object(m,'cycle',side_effect=[m.ReferenceUnavailable('rate limit'),{'status':'HOLD'}]) as cycle, patch.object(m.time,'sleep',side_effect=[None,KeyboardInterrupt]), patch('builtins.print'):
            self.assertEqual(m.main(),0)
            self.assertEqual(cycle.call_count,2)
            self.assertIn(((True,'WAITING_FOR_REFERENCE'),),status.call_args_list)
            self.assertIn(((True,'HOLD'),),status.call_args_list)

    def test_transaction_errors_still_stop_without_retry(self):
        with patch.object(m.sys,'argv',['meta','--live','--watch']), patch.object(m,'process_lock',return_value=nullcontext()), patch.object(m,'runtime_status') as status, patch.object(m,'cycle',side_effect=m.SellerError('RPC sendTransaction unavailable')) as cycle, patch.object(m.time,'sleep') as sleep, patch('builtins.print'):
            self.assertEqual(m.main(),1)
            cycle.assert_called_once_with(True)
            sleep.assert_not_called()
            status.assert_called_with(True,'STOPPED_ERROR')

    def test_reference_fetch_errors_are_classified_before_signing(self):
        with patch.object(m,'fetch_reference',side_effect=m.NinjaError('rate limit')), patch.object(m,'load_wallet') as signing:
            with self.assertRaises(m.ReferenceUnavailable):m.reference_price()
            signing.assert_not_called()
