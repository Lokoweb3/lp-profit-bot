import io
import unittest
from unittest.mock import patch

from lp_profit_bot.__main__ import main


class PromptTests(unittest.TestCase):
    def test_interactive_key_prompt(self):
        with patch.dict("os.environ", {}, clear=True), \
             patch("lp_profit_bot.__main__.load_key", return_value=""), \
             patch("sys.argv", ["lp-profit-bot", "--pools"]), \
             patch("sys.stdin.isatty", return_value=True), \
             patch("lp_profit_bot.__main__.getpass.getpass", return_value="test-key") as prompt, \
             patch("lp_profit_bot.__main__.NinjaClient") as client, \
             patch("sys.stdout", new_callable=io.StringIO):
            client.return_value.pools.return_value = {"pools": []}
            self.assertEqual(main(), 0)
            prompt.assert_called_once()
            client.assert_called_once_with("test-key")

    def test_unattended_missing_key_fails_without_prompt(self):
        with patch.dict("os.environ", {}, clear=True), \
             patch("lp_profit_bot.__main__.load_key", return_value=""), \
             patch("sys.argv", ["lp-profit-bot", "--pools"]), \
             patch("sys.stdin.isatty", return_value=False), \
             patch("lp_profit_bot.__main__.getpass.getpass") as prompt, \
             patch("sys.stderr", new_callable=io.StringIO):
            self.assertEqual(main(), 1)
            prompt.assert_not_called()

    def test_saved_key_skips_prompt(self):
        with patch("lp_profit_bot.__main__.load_key", return_value="saved-key"), \
             patch("sys.argv", ["lp-profit-bot", "--pools"]), \
             patch("lp_profit_bot.__main__.getpass.getpass") as prompt, \
             patch("lp_profit_bot.__main__.NinjaClient") as client, \
             patch("sys.stdout", new_callable=io.StringIO):
            client.return_value.pools.return_value = {"pools": []}
            self.assertEqual(main(), 0)
            client.assert_called_once_with("saved-key")
            prompt.assert_not_called()
