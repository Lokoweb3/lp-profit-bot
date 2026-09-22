"""Use a public fixture address so tests never need the live bot wallet."""

import os

os.environ.setdefault("X1_BOT_WALLET_ADDRESS", "11111111111111111111111111111111")
