import base64
import json
import struct
import tempfile
import time
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from solders.hash import Hash
from solders.pubkey import Pubkey
from solders.signature import Signature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from lp_profit_bot.wallet import base58, public_bytes

from lp_profit_bot import seller as s


def token_account(mint, qty):
    data = bytearray(170)
    data[:32] = bytes(Pubkey.from_string(mint))
    data[32:64] = bytes(Pubkey.from_string(s.WALLET))
    struct.pack_into("<Q", data, 64, qty)
    data[108] = 1
    return {"owner": s.TOKEN, "executable": False, "data": [base64.b64encode(data).decode(), "base64"]}


class SellerTests(unittest.TestCase):
    def test_wallet_address_comes_from_local_keypair(self):
        local = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
        with patch.object(s, 'load_wallet', return_value=local), \
             patch.dict(s.os.environ, {'X1_BOT_WALLET_ADDRESS': '11111111111111111111111111111111'}):
            self.assertEqual(s.local_wallet_address(), base58(public_bytes(local)))

    def snapshot(self):
        return {"reserve_in": 100_000_000, "reserve_out": 400_000_000,
                "trade_fee": 2800, "protocol_fee": 250000, "fund_fee": 50000,
                "balance_in": 7_488_777, "balance_out": 0, "native_balance": 10_000_000_000,
                "xnt_usd": Decimal("0.3"), "received": time.monotonic(), "slot": 1,
                "input_index": 0, "pool": {"vaults": [str(Pubkey.new_unique()), str(Pubkey.new_unique())],
                "observation": str(Pubkey.new_unique())}}

    def test_plan_limits_inventory_and_chunk_without_lifetime_cap(self):
        snap = self.snapshot()
        for balance, expected in [(7_488_777, s.CHUNK_RAW), (200_000, 200_000)]:
            snap["balance_in"] = balance
            p = s.plan(snap, Decimal("350"))
            self.assertEqual(p["amount_raw"], expected)
            self.assertGreater(p["minimum_output_raw"], 0)
            self.assertGreaterEqual(p["estimated_output_raw"], p["minimum_output_raw"])

    def test_no_sale_when_pool_below_reference(self):
        self.assertIsNone(s.plan(self.snapshot(), Decimal("401")))

    def test_costs_can_eliminate_premium(self):
        snap = self.snapshot()
        self.assertIsNone(s.plan(snap, Decimal("399.99")))

    def test_final_pool_price_not_below_reference(self):
        snap = self.snapshot()
        p = s.plan(snap, Decimal("390"))
        self.assertGreaterEqual(Decimal(p["ending_pool_price_usd"]), Decimal("390"))

    def test_minimum_includes_cost_ceiling_and_rounds_up(self):
        result = s.minimum_output(500_000, Decimal("350"), Decimal("0.3"))
        self.assertEqual(result, 1_753_151)

    def test_transaction_has_only_fixed_programs_and_protected_swap(self):
        snap = self.snapshot()
        p = s.plan(snap, Decimal("350"))
        tx = s.build_transaction(snap, p, str(Hash.default()))
        self.assertEqual(str(tx.message.account_keys[0]), s.WALLET)
        self.assertEqual(tx.signatures, [Signature.default()])
        programs = [str(tx.message.account_keys[ix.program_id_index]) for ix in tx.message.instructions]
        self.assertEqual(programs, ["ComputeBudget111111111111111111111111111111"]*2 + [s.ATA, s.XDEX_PROGRAM])
        swap = tx.message.instructions[-1]
        self.assertEqual(struct.unpack("<QQ", swap.data[8:]), (p["amount_raw"], p["minimum_output_raw"]))
        self.assertEqual(str(tx.message.account_keys[swap.accounts[5]]), s.associated(s.USDC_MINT))

    def test_simulation_rejects_wrong_debit_low_output_and_excess_cost(self):
        snap = self.snapshot()
        p = s.plan(snap, Decimal("350"))
        def response(debit=p["amount_raw"], output=p["minimum_output_raw"], native_cost=10000):
            return {"err": None, "accounts": [token_account(s.GOOGL_MINT, snap["balance_in"]-debit),
                    token_account(s.USDC_MINT, output), {"lamports": snap["native_balance"]-native_cost}]}
        s.verify_simulation(snap, p, response(), 5000)
        for value in [response(debit=p["amount_raw"]+1), response(output=p["minimum_output_raw"]-1),
                      response(native_cost=s.COST_CEILING+1), {"err": "failed"}]:
            with self.assertRaises(s.SellerError):
                s.verify_simulation(snap, p, value, 5000)

    def test_journal_corruption_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"journal.json"
            path.write_text("broken")
            with self.assertRaises(ValueError):
                s.read_journal(path)

    def test_pending_signature_blocks_new_sale(self):
        journal = {"wallet": s.WALLET, "cap_raw": s.LEGACY_CAP_RAW, "halted": False,
                   "entries": [{"signature": str(Signature.default()), "amount_raw": 100, "status": "pending"}]}
        with patch.object(s, "read_journal", return_value=journal), \
             patch.object(s, "rpc", return_value={"value": [None]}) as rpc, \
             patch.object(s, "load_wallet") as signer:
            self.assertEqual(s.cycle(True)["status"], "WAITING_FOR_FINALITY")
            rpc.assert_called_once()
            signer.assert_not_called()

    def test_failed_transaction_halts_and_keeps_reservation(self):
        journal = {"wallet": s.WALLET, "cap_raw": s.LEGACY_CAP_RAW, "halted": False,
                   "entries": [{"signature": str(Signature.default()), "amount_raw": 100, "status": "pending"}]}
        with patch.object(s, "rpc", return_value={"value": [{"err": {"failure": 1}, "confirmationStatus": "finalized"}]}), \
             patch.object(s, "atomic_write"):
            self.assertTrue(s.reconcile(journal))
        self.assertTrue(journal["halted"])
        self.assertEqual(journal["entries"][0]["amount_raw"], 100)
        self.assertEqual(journal["entries"][0]["status"], "failed")

    def test_legacy_cap_exhaustion_does_not_block_future_inventory(self):
        journal = {"halted": False, "entries": [{"status": "finalized", "amount_raw": s.CHUNK_RAW}] * 14}
        snap = self.snapshot()
        snap["balance_in"] = 0
        with patch.object(s, "read_journal", return_value=journal), \
             patch.object(s, "reference_price", return_value=(Decimal("350"), time.time())) as ref, \
             patch.object(s, "snapshot", return_value=snap), \
             patch.object(s, "load_wallet") as signer:
            self.assertEqual(s.cycle(False)["status"], "HOLD")
            ref.assert_called_once()
            signer.assert_not_called()

    def test_legacy_journal_migrates_without_resetting_history(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"journal.json"
            entries = [{"signature": str(Signature.from_bytes(bytes([i+1])*64)),
                        "amount_raw": s.CHUNK_RAW, "status": "finalized"} for i in range(14)]
            s.atomic_write(path, {"wallet": s.WALLET, "cap_raw": s.LEGACY_CAP_RAW,
                                  "halted": False, "entries": entries})
            migrated = s.read_journal(path)
            self.assertIsNone(migrated["cap_raw"])
            self.assertEqual(migrated["entries"], entries)
            s.atomic_write(path, migrated)
            self.assertIsNone(s.read_journal(path)["cap_raw"])
            migrated["entries"].append({"signature": str(Signature.from_bytes(bytes([15])*64)),
                                        "amount_raw": s.CHUNK_RAW, "status": "finalized"})
            s.atomic_write(path, migrated)
            self.assertEqual(len(s.read_journal(path)["entries"]), 15)
            migrated["cap_raw"] = s.LEGACY_CAP_RAW
            s.atomic_write(path, migrated)
            with self.assertRaises(s.SellerError):
                s.read_journal(path)

    def test_dry_run_does_not_load_key_or_broadcast(self):
        snap = self.snapshot()
        p = s.plan(snap, Decimal("350"))
        result = {"value": {"err": None, "accounts": [
            token_account(s.GOOGL_MINT, snap["balance_in"]-p["amount_raw"]),
            token_account(s.USDC_MINT, p["minimum_output_raw"]),
            {"lamports": snap["native_balance"]-5000}]}}
        replies = [{"value": {"blockhash": str(Hash.default()), "lastValidBlockHeight": 5}},
                   {"value": 5000}, result]
        journal = {"wallet": s.WALLET, "cap_raw": s.LEGACY_CAP_RAW, "entries": [], "halted": False}
        with patch.object(s, "read_journal", return_value=journal), \
             patch.object(s, "snapshot", return_value=snap), \
             patch.object(s, "reference_price", return_value=(Decimal("350"), time.time())), \
             patch.object(s, "rpc", side_effect=replies) as rpc, \
             patch.object(s, "atomic_write"), patch.object(s, "load_wallet") as signer:
            report = s.cycle(False)
            self.assertEqual(report["status"], "SIMULATION_PASSED")
            signer.assert_not_called()
            self.assertNotIn("sendTransaction", [call.args[0] for call in rpc.call_args_list])

    def test_atomic_journal_write_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"journal.json"
            data = {"wallet": s.WALLET, "cap_raw": None, "halted": False, "entries": []}
            s.atomic_write(path, data)
            self.assertEqual(s.read_journal(path), data)

    def test_live_reserves_before_broadcast_and_preserves_unknown_result(self):
        local = Ed25519PrivateKey.generate()
        journal = {"wallet": s.WALLET, "cap_raw": s.LEGACY_CAP_RAW, "halted": False, "entries": []}
        saved = []
        calls = []
        with patch.object(s, "WALLET", base58(public_bytes(local))):
            snap = self.snapshot()
            p = s.plan(snap, Decimal("350"))
            def rpc(method, params):
                calls.append(method)
                if method == "getLatestBlockhash":
                    return {"value": {"blockhash": str(Hash.default()), "lastValidBlockHeight": 5}}
                if method == "getFeeForMessage":
                    return {"value": 5000}
                if method == "simulateTransaction":
                    return {"context": {"slot": 2}, "value": {"err": None, "accounts": [
                        token_account(s.GOOGL_MINT, snap["balance_in"]-p["amount_raw"]),
                        token_account(s.USDC_MINT, p["minimum_output_raw"]),
                        {"lamports": snap["native_balance"]-5000}]}}
                if method == "sendTransaction":
                    self.assertEqual(len(saved), 1)
                    self.assertEqual(saved[0]["entries"][0]["status"], "pending")
                    self.assertEqual(saved[0]["entries"][0]["amount_raw"], p["amount_raw"])
                    self.assertFalse(params[1]["skipPreflight"])
                    raise s.SellerError("transport timeout after possible submission")
                self.fail("Unexpected RPC method")
            with patch.object(s, "read_journal", return_value=journal), \
                 patch.object(s, "snapshot", return_value=snap), \
                 patch.object(s, "reference_price", return_value=(Decimal("350"), time.time())), \
                 patch.object(s, "rpc", side_effect=rpc), patch.object(s, "load_wallet", return_value=local), \
                 patch.object(s, "atomic_write", side_effect=lambda path, value: saved.append(json.loads(json.dumps(value)))):
                with self.assertRaises(s.SellerError):
                    s.cycle(True)
        self.assertEqual(calls.count("sendTransaction"), 1)
        self.assertEqual(journal["entries"][0]["status"], "pending")

    def test_stale_future_and_nonfinite_reference_rejected(self):
        for timestamp in [time.time()-301, time.time()+60, "NaN"]:
            with patch.object(s, "fetch_reference", return_value={"alphabet-xstock": {"usd": "350", "last_updated_at": timestamp}}):
                with self.assertRaises(s.SellerError):
                    s.reference_price()

    def test_zero_bound_never_builds(self):
        with self.assertRaises(s.SellerError):
            s.build_transaction(self.snapshot(), {"amount_raw": 100, "minimum_output_raw": 0}, str(Hash.default()))
