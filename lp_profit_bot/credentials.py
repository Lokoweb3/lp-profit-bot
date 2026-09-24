"""Local API credential storage, excluded from version control."""

import os
import stat
import tempfile
from pathlib import Path

from .ninja import NinjaError


KEY_FILE = Path(__file__).resolve().parent.parent / ".secrets" / "ninja-api-key"


def load_key() -> str:
    key = os.environ.get("X1_API_KEY", "").strip()
    if key:
        return key
    try:
        if KEY_FILE.parent.is_symlink():
            raise NinjaError("Credential directory must not be a symbolic link.")
        fd = os.open(KEY_FILE, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
                    stat.S_IMODE(info.st_mode) != 0o600):
                raise NinjaError("API key file must be a regular file owned by your user with permissions 600.")
            return stream.read(8192).strip()
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
        if directory.stat().st_uid != os.getuid():
            raise NinjaError("Credential directory must belong to your user.")
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
