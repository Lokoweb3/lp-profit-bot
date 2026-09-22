import struct
import unittest

from lp_profit_bot.transaction_audit import SWAP_BASE_INPUT, AuditError, swap_bounds, audit_prepared


class AuditTests(unittest.TestCase):
    def test_zero_minimum_output_is_unprotected(self):
        result = swap_bounds(SWAP_BASE_INPUT + struct.pack("<QQ", 7000000, 0))
        self.assertFalse(result["output_protected"])

    def test_nonzero_minimum_output(self):
        result = swap_bounds(SWAP_BASE_INPUT + struct.pack("<QQ", 7000000, 25000000))
        self.assertEqual(result["minimum_out_raw"], 25000000)
        self.assertTrue(result["output_protected"])

    def test_unknown_layout_rejected(self):
        with self.assertRaises(AuditError):
            swap_bounds(bytes(24))

    def test_truncated_transaction_rejected(self):
        with self.assertRaises(AuditError):
            audit_prepared("AA==", "wallet")
