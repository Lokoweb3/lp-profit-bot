import time
import unittest
from unittest.mock import patch
from lp_profit_bot import spy_monitor as spy, dashboard, seller


class SpyTests(unittest.TestCase):
    def test_snapshot_and_wrong_mint(self):
        from datetime import datetime, timezone
        now = time.time()
        pool = {"address": spy.POOL, "baseToken": {"address": spy.MINT, "decimals": 8, "symbol": "SPY.X"},
                "quoteToken": {"address": seller.WXNT, "symbol": "XNT"},
                "priceUsd": 800, "liquidity": 500, "lastSyncedAt": datetime.now(timezone.utc).isoformat()}
        with patch.object(spy, "load_key", return_value="test"), patch.object(spy, "NinjaClient") as client, \
             patch.object(spy, "fetch_reference", return_value={"sp500-xstock": {"usd": 750, "last_updated_at": now}}), \
             patch.object(seller, "rpc", return_value={"value": []}):
            client.return_value.pool.return_value = {"pool": pool}
            value = spy.snapshot()
            self.assertEqual(value["balance"], "0")
            self.assertTrue(value["fresh"])
            self.assertAlmostEqual(float(value["gap_percent"]), 6.6666667)
            pool["baseToken"]["address"] = seller.GOOGL_MINT
            with self.assertRaises(seller.SellerError):
                spy.snapshot()

    def test_stale_snapshot_suppresses_premium_without_mutating_cache(self):
        cache = dashboard.DashboardData()
        now = time.time()
        cache.spy = {"fetched_at": now, "pool_updated_at": now-301,
                     "reference_updated_at": now, "fresh": True, "gap_percent": "10"}
        with patch.object(seller, "read_journal", return_value={"halted": False, "entries": []}), \
             patch.object(dashboard, "seller_running", return_value=False), \
             patch.object(dashboard, "read_public_file", return_value=(None, None)):
            result = cache.status()
        self.assertFalse(result["spy"]["fresh"])
        self.assertIsNone(result["spy"]["gap_percent"])
        self.assertEqual(cache.spy["gap_percent"], "10")
        self.assertEqual(result["errors"], [])

    def test_refresh_failure_retains_previous_values_and_hides_internal_error(self):
        cache = dashboard.DashboardData()
        cache.spy = {"balance": "1"}
        with patch.object(dashboard, "spy_snapshot", side_effect=ValueError("private response")):
            cache.refresh_spy()
        self.assertEqual(cache.spy["balance"], "1")
        self.assertNotIn("private", cache.spy_error)
        self.assertEqual(cache.errors, {})
