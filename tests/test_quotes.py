import unittest
from decimal import Decimal

from lp_profit_bot.quotes import TOKENS, QuoteError, quote_route, validate_quote


class QuoteTests(unittest.TestCase):
    def payload(self):
        return {"inputMint": TOKENS["XNT"][0], "outputMint": TOKENS["GOOGL.X"][0],
                "inputAmount": "1", "outputAmount": "0.000689699", "priceImpactPct": "0.05"}

    def test_rounds_output_down_to_token_precision(self):
        result = validate_quote(self.payload(), "XNT", "GOOGL.X", Decimal("1"))
        self.assertEqual(result["output_amount"], "0.00068969")

    def test_wrong_mint_and_amount_rejected(self):
        for key, value in [("inputMint", "wrong"), ("inputAmount", "2"),
                           ("outputAmount", "NaN"), ("outputAmount", "0")]:
            data = self.payload()
            data[key] = value
            with self.assertRaises(QuoteError):
                validate_quote(data, "XNT", "GOOGL.X", Decimal("1"))

    def test_outputs_feed_next_leg(self):
        seen = []
        outputs = iter(["0.001", "0.4", "0.99"])
        def fetch(source, destination, amount):
            seen.append(amount)
            return {"output_amount": next(outputs)}
        result = quote_route(("XNT", "GOOGL.X", "USDC.X", "XNT"), fetch)
        self.assertEqual(seen, [Decimal("1"), Decimal("0.001"), Decimal("0.4")])
        self.assertEqual(result["quoted_difference_xnt"], "-0.01")
        self.assertFalse(result["transaction_submitted"])
