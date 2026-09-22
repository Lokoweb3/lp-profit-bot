import unittest
from datetime import datetime, timezone

from lp_profit_bot.monitor import observation
from lp_profit_bot.ninja import NinjaError


class MonitorTests(unittest.TestCase):
    def payload(self, timestamp):
        return {"pool": {"address": "test-pool", "baseToken": {"symbol": "GOOGL.X"},
                         "quoteToken": {"symbol": "USDC.X"}, "priceUsd": "375.03",
                         "liquidity": "1237.39", "lastSyncedAt": timestamp}}

    def test_freshness_uses_pool_timestamp(self):
        now = datetime(2026, 9, 18, 23, 0, tzinfo=timezone.utc)
        cases = [("2026-09-18T22:59:00Z", "FRESH"),
                 ("2026-09-18T22:35:32.878Z", "STALE"),
                 ("2026-09-18T23:01:00Z", "FUTURE_TIMESTAMP"),
                 (None, "UNKNOWN_FRESHNESS"),
                 ("2026-09-18T23:00:00", "UNKNOWN_FRESHNESS")]
        for timestamp, status in cases:
            with self.subTest(status=status):
                payload = self.payload(timestamp)
                payload["lastUpdated"] = int(now.timestamp() * 1000)
                result = observation(payload, "test-pool", 300, now)
                self.assertEqual(result["data_status"], status)
                self.assertFalse(result["transaction_submitted"])
                self.assertNotIn("net_profit_usd", result)

    def test_wrong_pool_rejected(self):
        with self.assertRaises(NinjaError):
            observation(self.payload(None), "different-pool", 300)

    def test_invalid_market_data_rejected(self):
        payload = self.payload(None)
        payload["pool"]["priceUsd"] = float("nan")
        with self.assertRaises(NinjaError):
            observation(payload, "test-pool", 300)
