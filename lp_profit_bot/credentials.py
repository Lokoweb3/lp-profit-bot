"""Local API credential storage, excluded from version control."""

import os
import tempfile
from pathlib import Path

from .ninja import NinjaError


KEY_FILE = Path(__file__).resolve().parent.parent / ".secrets" / "ninja-api-key"


def load_key() -> str:
    key = os.environ.get("X1_API_KEY", "").strip()
    if key:
        return key
    try:
        return KEY_FILE.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""
    except (OSError, UnicodeError):
        raise NinjaError("Cannot read saved API key; run --setup-key to replace it.") from None


def save_key(key: str) -> None:
    key = key.strip()
    if not key or any(ord(char) < 33 or ord(char) > 126 for char in key):
        raise NinjaError("Enter a non-empty API key without spaces or control characters.")
    temporary = None
    try:
        directory = KEY_FILE.parent
        if directory.is_symlink():
            raise NinjaError("Credential directory must not be a symbolic link.")
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory.chmod(0o700)
        # A new private file plus atomic replacement also safely updates old keys.
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory,
                                         delete=False) as stream:
            temporary = Path(stream.name)
            os.fchmod(stream.fileno(), 0o600)
            stream.write(key + "\n")
        os.replace(temporary, KEY_FILE)
    except OSError:
        raise NinjaError("Cannot save API key; check project directory permissions.") from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
