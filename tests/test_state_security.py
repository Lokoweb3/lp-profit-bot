import json
import stat
import tempfile
import unittest
from pathlib import Path

from lp_profit_bot import seller


class StateSecurityTests(unittest.TestCase):
    def test_state_directory_and_written_journal_are_private(self):
        with tempfile.TemporaryDirectory() as root:
            state = Path(root) / "state"
            state.mkdir(mode=0o755)
            path = state / "journal.json"
            seller.atomic_write(path, {"entries": []})
            self.assertEqual(stat.S_IMODE(state.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(seller.read_state_json(path), {"entries": []})

    def test_symlinked_state_file_and_directory_are_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            private = Path(root) / "state"
            private.mkdir(mode=0o700)
            target = Path(root) / "target.json"
            target.write_text(json.dumps({"entries": []}))
            (private / "journal.json").symlink_to(target)
            with self.assertRaises(OSError):
                seller.read_state_json(private / "journal.json")
            (Path(root) / "linked-state").symlink_to(private, target_is_directory=True)
            with self.assertRaises(seller.SellerError):
                seller.ensure_private_state_dir(Path(root) / "linked-state")

    def test_symlinked_lock_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            state = Path(root) / "state"
            state.mkdir(mode=0o700)
            target = Path(root) / "target"
            target.write_text("keep")
            (state / "seller.lock").symlink_to(target)
            with self.assertRaises(OSError):
                seller.open_state_lock(state / "seller.lock")
            self.assertEqual(target.read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
