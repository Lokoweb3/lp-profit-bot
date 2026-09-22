"""Create a local X1 wallet; secret export requires an explicit CLI flag."""

import argparse
import json
import os
import stat
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .transaction_audit import base58

ROOT = Path(__file__).resolve().parent.parent
KEYPAIR_FILE = ROOT / ".secrets" / "bot-wallet.json"


class WalletError(Exception):
    pass


def public_bytes(key):
    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def check_directory():
    directory = KEYPAIR_FILE.parent
    if directory.is_symlink():
        raise WalletError("Wallet directory must not be a symbolic link.")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.stat().st_uid != os.getuid():
        raise WalletError("Wallet directory must belong to your user.")
    directory.chmod(0o700)


def load_wallet() -> Ed25519PrivateKey:
    if KEYPAIR_FILE.parent.is_symlink():
        raise WalletError("Wallet directory must not be a symbolic link.")
    try:
        fd = os.open(KEYPAIR_FILE, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise WalletError("Wallet key file must be a regular file owned by your user with permissions 600.")
            data = json.loads(stream.read(4096))
        if not isinstance(data, list) or len(data) != 64 or any(type(x) is not int or not 0 <= x <= 255 for x in data):
            raise WalletError("Wallet key file is invalid; it was not replaced.")
        key = Ed25519PrivateKey.from_private_bytes(bytes(data[:32]))
        if public_bytes(key) != bytes(data[32:]):
            raise WalletError("Wallet public key does not match its secret; file was not replaced.")
        return key
    except (OSError, ValueError, UnicodeError):
        raise WalletError("Cannot load wallet key file; check that setup completed and permissions are 600.") from None


def create_wallet() -> tuple[str, bool]:
    check_directory()
    if os.path.lexists(KEYPAIR_FILE):
        return base58(public_bytes(load_wallet())), False
    key = Ed25519PrivateKey.generate()
    seed = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                             serialization.NoEncryption())
    public = public_bytes(key)
    # Standard Solana keypair format: 32-byte seed followed by 32-byte public key.
    try:
        fd = os.open(KEYPAIR_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        return base58(public_bytes(load_wallet())), False
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(list(seed + public), stream)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    return base58(public_bytes(load_wallet())), True


def main() -> int:
    parser = argparse.ArgumentParser(description="Local bot wallet setup; never signs or sends trades.")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--create", action="store_true", help="Create once; preserve any existing keypair")
    action.add_argument("--export-private-key", action="store_true", help="Print the private key in Base58 for local wallet import; do not share")
    args = parser.parse_args()
    try:
        if args.export_private_key:
            key = load_wallet()
            seed = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                                     serialization.NoEncryption())
            print(base58(seed + public_bytes(key)))
            return 0
        if args.create:
            address, created = create_wallet()
            print("Created a separate bot wallet." if created else "Using existing bot wallet; key unchanged.")
            metadata = {"network": "x1-mainnet", "public_address": address,
                        "keypair_file": ".secrets/bot-wallet.json", "execution_enabled": False}
            (ROOT / "state").mkdir(exist_ok=True)
            (ROOT / "state" / "bot-wallet.json").write_text(json.dumps(metadata, indent=2) + "\n")
        else:
            address = base58(public_bytes(load_wallet()))
        print(f"Public X1 address: {address}")
        print("No funds moved. Wallet setup does not enable trading.")
        return 0
    except (WalletError, OSError) as exc:
        print(str(exc) if isinstance(exc, WalletError) else "Wallet setup failed; check local file permissions.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
