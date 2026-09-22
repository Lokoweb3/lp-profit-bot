import unittest
from decimal import Decimal
from lp_profit_bot.spy_quotes import quote
from lp_profit_bot.seller import SellerError


class SpyQuoteTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = {"balance_in": 100_000_000, "reserve_in": 100_000_000,
                         "reserve_out": 1_000_000_000_000, "trade_fee": 0,
                         "protocol_fee": 0, "fund_fee": 0, "xnt_usd": Decimal("0.3")}

    def test_full_reserve_input_halves_output_reserve(self):
        result = quote(self.snapshot, 100_000_000)
        self.assertEqual(result["estimated_output_raw"], 500_000_000_000)
        self.assertEqual(Decimal(result["estimated_usd"]), 150)
        self.assertEqual(Decimal(result["ending_pool_price_usd"]), 75)
        self.assertFalse(result["transaction_submitted"])

    def test_fee_reduces_output(self):
        before = quote(self.snapshot, 500_000)
        self.snapshot["trade_fee"] = 3000
        after = quote(self.snapshot, 500_000)
        self.assertLess(after["estimated_output_raw"], before["estimated_output_raw"])

    def test_invalid_or_unfunded_amounts_rejected(self):
        for amount in (0, -1, 100_000_001, True, 0.5):
            with self.assertRaises(SellerError):
                quote(self.snapshot, amount)
