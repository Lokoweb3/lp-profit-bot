import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lp_profit_bot.credentials import load_key, save_key
from lp_profit_bot.ninja import NinjaError


class CredentialTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / ".secrets" / "ninja-api-key"
        key_patch = patch("lp_profit_bot.credentials.KEY_FILE", self.path)
        key_patch.start()
        self.addCleanup(key_patch.stop)
        env_patch = patch.dict(os.environ, {}, clear=True)
        env_patch.start()
        self.addCleanup(env_patch.stop)

    def test_save_load_replace_and_permissions(self):
        self.assertEqual(load_key(), "")
        save_key("test-first")
        self.assertEqual(load_key(), "test-first")
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.path.parent.stat().st_mode & 0o777, 0o700)
        save_key("test-second")
        self.assertEqual(load_key(), "test-second")
        self.assertEqual(len(list(self.path.parent.iterdir())), 1)

    def test_environment_takes_precedence(self):
        save_key("test-saved")
        with patch.dict(os.environ, {"X1_API_KEY": "test-env"}):
            self.assertEqual(load_key(), "test-env")

    def test_invalid_key_preserves_existing_key(self):
        save_key("test-saved")
        for key in ["", "has spaces", "has\nnewline"]:
            with self.assertRaises(NinjaError):
                save_key(key)
        self.assertEqual(load_key(), "test-saved")
