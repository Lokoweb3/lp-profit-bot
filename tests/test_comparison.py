import io
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch

from lp_profit_bot.comparison import GOOGL_POOL, GOOGL_MINT, USDC_MINT, compare, fetch_reference
from lp_profit_bot.ninja import NinjaError


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 18, 23, 0, tzinfo=timezone.utc)
        self.pool = {"pool": {"address": GOOGL_POOL,
                    "baseToken": {"address": GOOGL_MINT, "symbol": "GOOGL.X"},
                    "quoteToken": {"address": USDC_MINT, "symbol": "USDC.X"},
                    "priceUsd": "105", "liquidity": "1000",
                    "lastSyncedAt": self.now.isoformat()}}
        self.ref = {"alphabet-xstock": {"usd": "100", "last_updated_at": self.now.timestamp()}}

    def test_premium_and_discount(self):
        for price, expected in [("105", "5"), ("95", "-5"), ("100", "0")]:
            self.pool["pool"]["priceUsd"] = price
            result = compare(self.pool, self.ref, now=self.now)
            self.assertEqual(Decimal(result["gap_percent"]), Decimal(expected))
            self.assertFalse(result["transaction_submitted"])

    def test_stale_pool_suppresses_gap(self):
        self.pool["pool"]["lastSyncedAt"] = "2026-09-18T22:00:00Z"
        self.assertIsNone(compare(self.pool, self.ref, now=self.now)["gap_percent"])

    def test_untrusted_reference_timestamps_suppress_gap(self):
        for timestamp in [None, "bad", self.now.timestamp() - 301, self.now.timestamp() + 1]:
            self.ref["alphabet-xstock"]["last_updated_at"] = timestamp
            result = compare(self.pool, self.ref, now=self.now)
            self.assertIsNone(result["gap_percent"])
            self.assertEqual(result["comparison_status"], "DATA_NOT_FRESH")

    def test_zero_and_invalid_reference_prices_rejected(self):
        for price in ["0", "NaN", "-1", None]:
            self.ref["alphabet-xstock"]["usd"] = price
            with self.assertRaises(NinjaError):
                compare(self.pool, self.ref, now=self.now)

    def test_matching_symbol_wrong_mint_rejected(self):
        self.pool["pool"]["baseToken"]["address"] = "wrong-mint"
        with self.assertRaises(NinjaError):
            compare(self.pool, self.ref, now=self.now)

    def test_reference_request_never_uses_ninja_key(self):
        with patch.dict("os.environ", {"X1_API_KEY": "private-ninja-key"}, clear=True), \
             patch("lp_profit_bot.comparison.build_opener") as opener:
            opener.return_value.open.return_value = io.BytesIO(b'{"alphabet-xstock":{"usd":350.88}}')
            self.assertEqual(fetch_reference()["alphabet-xstock"]["usd"], Decimal("350.88"))
            request = opener.return_value.open.call_args.args[0]
            self.assertIsNone(request.get_header("Authorization"))
            self.assertNotIn("private-ninja-key", str(request.headers))
