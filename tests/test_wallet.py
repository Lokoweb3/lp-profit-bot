import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lp_profit_bot.wallet import WalletError, base58, create_wallet, load_wallet, public_bytes


class WalletTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / ".secrets" / "bot-wallet.json"
        mock = patch("lp_profit_bot.wallet.KEYPAIR_FILE", self.path)
        mock.start()
        self.addCleanup(mock.stop)

    def test_create_permissions_sign_verify_and_reuse(self):
        address, created = create_wallet()
        self.assertTrue(created)
        original = self.path.read_bytes()
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.path.parent.stat().st_mode & 0o777, 0o700)
        key = load_wallet()
        self.assertEqual(address, base58(public_bytes(key)))
        message = b"local wallet self-test; not a blockchain transaction"
        key.public_key().verify(key.sign(message), message)
        self.assertEqual(create_wallet(), (address, False))
        self.assertEqual(self.path.read_bytes(), original)

    def test_corrupt_wallet_not_overwritten(self):
        create_wallet()
        self.path.write_text("invalid")
        with self.assertRaises(WalletError):
            create_wallet()
        self.assertEqual(self.path.read_text(), "invalid")

    def test_mismatched_public_key_rejected(self):
        create_wallet()
        data = json.loads(self.path.read_text())
        data[-1] ^= 1
        self.path.write_text(json.dumps(data))
        with self.assertRaises(WalletError):
            load_wallet()

    def test_open_permissions_rejected(self):
        create_wallet()
        self.path.chmod(0o644)
        with self.assertRaises(WalletError):
            load_wallet()

    def test_symlink_rejected(self):
        create_wallet()
        target = self.path.with_name("original.json")
        self.path.rename(target)
        self.path.symlink_to(target)
        with self.assertRaises(WalletError):
            create_wallet()
