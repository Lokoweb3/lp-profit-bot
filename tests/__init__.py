"""Use a public fixture address so tests never need the live bot wallet."""

import os

# Deterministic test-only pubkey (32 bytes of 0x2a); never use a real wallet here.
os.environ.setdefault("X1_BOT_WALLET_ADDRESS", "3qbR1eZRqXUWroWKKYhbDmR3FfqTHfqSU8zZSxtANzYh")
