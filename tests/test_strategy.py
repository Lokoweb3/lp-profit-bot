import unittest
from decimal import Decimal

from lp_profit_bot.strategy import Position, evaluate


class StrategyTests(unittest.TestCase):
    def position(self, **updates):
        values = dict(position_id="test", contributed_usd="1000",
                      principal_value_usd="1080", unclaimed_fees_usd="35",
                      withdrawn_usd="0", estimated_exit_cost_usd="5")
        values.update(updates)
        return Position.from_dict(values)

    def test_target_boundary(self):
        result = evaluate(self.position(), Decimal("11"))
        self.assertEqual(result["decision"], "TARGET_REACHED")
        self.assertEqual(Decimal(result["net_profit_usd"]), Decimal("110"))
        self.assertFalse(result["transaction_submitted"])

    def test_exit_cost_can_prevent_trigger(self):
        result = evaluate(self.position(estimated_exit_cost_usd="6"), Decimal("11"))
        self.assertEqual(result["decision"], "HOLD")

    def test_collected_fees_are_not_counted_twice(self):
        before = evaluate(self.position(), Decimal("11"))
        after = evaluate(self.position(unclaimed_fees_usd="0", withdrawn_usd="35"), Decimal("11"))
        self.assertEqual(before["net_profit_usd"], after["net_profit_usd"])

    def test_fees_do_not_hide_principal_loss(self):
        result = evaluate(self.position(principal_value_usd="900"), Decimal("1"))
        self.assertEqual(result["decision"], "HOLD")
        self.assertEqual(Decimal(result["net_profit_usd"]), Decimal("-70"))

    def test_invalid_amounts_rejected(self):
        for value in ["NaN", "Infinity", "-1", "abc", None]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.position(unclaimed_fees_usd=value)
        with self.assertRaises(ValueError):
            self.position(contributed_usd="0")


if __name__ == "__main__":
    unittest.main()
