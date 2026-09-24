"""Local seller dashboard. Explicit routes only; never serves project files."""
from .meta_monitor import snapshot as meta_snapshot
from .coin_monitor import snapshot as coin_snapshot
from .pltr_monitor import snapshot as pltr_snapshot
from .amd_monitor import snapshot as amd_snapshot
from .nvda_monitor import snapshot as nvda_snapshot
from .aapl_monitor import snapshot as aapl_snapshot

import argparse
import fcntl
import json
import secrets
import subprocess
import sys
import threading
import time
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlsplit

from . import seller, worker_control, execution_barrier
from .spy_monitor import snapshot as spy_snapshot
from .spcx_monitor import snapshot as spcx_snapshot
from .tsla_monitor import snapshot as tsla_snapshot
from .activity import ActivityFeed
from .proceeds import ProceedsHistory

ASSETS = Path(__file__).resolve().parent / "dashboard_assets"
START_LOCK = threading.Lock()


def start_seller():
    """Serialize launches across dashboard instances; seller also holds its own lock."""
    state = seller.ROOT / "state"
    seller.ensure_private_state_dir(state)
    with START_LOCK, seller.open_state_lock(state / "dashboard-start.lock") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if seller_running():
            return "Seller already running; no additional process started."
        journal = seller.read_journal()
        if journal["halted"]:
            raise seller.SellerError("Seller halted. Review its journal before restarting.")
        with (state / "seller-dashboard.log").open("ab") as log:
            process = subprocess.Popen(
                [sys.executable, "-m", "lp_profit_bot.seller", "--live", "--watch"],
                cwd=seller.ROOT, stdin=subprocess.DEVNULL, stdout=log,
                stderr=subprocess.STDOUT, start_new_session=True,
            )
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise seller.SellerError("Seller exited. Check state/seller-dashboard.log.")
            if seller_running():
                threading.Thread(target=process.wait, daemon=True).start()
                return "Live seller started: GOOGL.X → USDC.X. It waits for qualifying prices."
            time.sleep(0.05)
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        raise seller.SellerError("Seller startup timed out. Check state/seller-dashboard.log.")


def start_spy_seller():
    from . import spy_seller
    """Serialize launches across dashboard instances; seller also holds its own lock."""
    state = seller.ROOT / "state"
    seller.ensure_private_state_dir(state)
    with START_LOCK, seller.open_state_lock(state / "spy-dashboard-start.lock") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if seller_running('spy-seller.lock'):
            return "Seller already running; no additional process started."
        journal = spy_seller.read_journal()
        if journal["halted"]:
            raise seller.SellerError("Seller halted. Review its journal before restarting.")
        with (state / "spy-seller-dashboard.log").open("ab") as log:
            process = subprocess.Popen(
                [sys.executable, "-m", "lp_profit_bot.spy_seller", "--live", "--watch"],
                cwd=seller.ROOT, stdin=subprocess.DEVNULL, stdout=log,
                stderr=subprocess.STDOUT, start_new_session=True,
            )
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise seller.SellerError("Seller exited. Check state/spy-seller-dashboard.log.")
            if seller_running('spy-seller.lock'):
                threading.Thread(target=process.wait, daemon=True).start()
                return "Live seller started: SPY.X → XNT. It waits for qualifying prices."
            time.sleep(0.05)
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        raise seller.SellerError("Seller startup timed out. Check state/spy-seller-dashboard.log.")


def start_spcx_seller():
    from . import spcx_seller
    """Serialize launches across dashboard instances; seller also holds its own lock."""
    state = seller.ROOT / "state"
    seller.ensure_private_state_dir(state)
    with START_LOCK, seller.open_state_lock(state / "spcx-dashboard-start.lock") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if seller_running('spcx-seller.lock'):
            return "Seller already running; no additional process started."
        journal = spcx_seller.read_journal()
        if journal["halted"]:
            raise seller.SellerError("Seller halted. Review its journal before restarting.")
        with (state / "spcx-seller-dashboard.log").open("ab") as log:
            process = subprocess.Popen(
                [sys.executable, "-m", "lp_profit_bot.spcx_seller", "--live", "--watch"],
                cwd=seller.ROOT, stdin=subprocess.DEVNULL, stdout=log,
                stderr=subprocess.STDOUT, start_new_session=True,
            )
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise seller.SellerError("Seller exited. Check state/spcx-seller-dashboard.log.")
            if seller_running('spcx-seller.lock'):
                threading.Thread(target=process.wait, daemon=True).start()
                return "Live seller started: SPCX.X → XNT. It waits for qualifying prices."
            time.sleep(0.05)
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        raise seller.SellerError("Seller startup timed out. Check state/spcx-seller-dashboard.log.")


def start_tsla_seller():
    from . import tsla_seller
    """Serialize launches across dashboard instances; seller also holds its own lock."""
    state = seller.ROOT / "state"
    seller.ensure_private_state_dir(state)
    with START_LOCK, seller.open_state_lock(state / "tsla-dashboard-start.lock") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if seller_running('tsla-seller.lock'):
            return "Seller already running; no additional process started."
        journal = tsla_seller.read_journal()
        if journal["halted"]:
            raise seller.SellerError("Seller halted. Review its journal before restarting.")
        with (state / "tsla-seller-dashboard.log").open("ab") as log:
            process = subprocess.Popen(
                [sys.executable, "-m", "lp_profit_bot.tsla_seller", "--live", "--watch"],
                cwd=seller.ROOT, stdin=subprocess.DEVNULL, stdout=log,
                stderr=subprocess.STDOUT, start_new_session=True,
            )
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise seller.SellerError("Seller exited. Check state/tsla-seller-dashboard.log.")
            if seller_running('tsla-seller.lock'):
                threading.Thread(target=process.wait, daemon=True).start()
                return "Live seller started: TSLA.X → XNT. It waits for qualifying prices."
            time.sleep(0.05)
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        raise seller.SellerError("Seller startup timed out. Check state/tsla-seller-dashboard.log.")


def start_meta_seller():
    from . import meta_seller
    """Serialize launches across dashboard instances; seller also holds its own lock."""
    state = seller.ROOT / "state"
    seller.ensure_private_state_dir(state)
    with START_LOCK, seller.open_state_lock(state / "meta-dashboard-start.lock") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if seller_running('meta-seller.lock'):
            return "Seller already running; no additional process started."
        journal = meta_seller.read_journal()
        if journal["halted"]:
            raise seller.SellerError("Seller halted. Review its journal before restarting.")
        with (state / "meta-seller-dashboard.log").open("ab") as log:
            process = subprocess.Popen(
                [sys.executable, "-m", "lp_profit_bot.meta_seller", "--live", "--watch"],
                cwd=seller.ROOT, stdin=subprocess.DEVNULL, stdout=log,
                stderr=subprocess.STDOUT, start_new_session=True,
            )
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise seller.SellerError("Seller exited. Check state/meta-seller-dashboard.log.")
            if seller_running('meta-seller.lock'):
                threading.Thread(target=process.wait, daemon=True).start()
                return "Live seller started: META.X → XNT. It waits for qualifying prices."
            time.sleep(0.05)
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        raise seller.SellerError("Seller startup timed out. Check state/meta-seller-dashboard.log.")


def start_coin_seller():
    from . import coin_seller
    """Serialize launches across dashboard instances; seller also holds its own lock."""
    state = seller.ROOT / "state"
    seller.ensure_private_state_dir(state)
    with START_LOCK, seller.open_state_lock(state / "coin-dashboard-start.lock") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if seller_running('coin-seller.lock'):
            return "Seller already running; no additional process started."
        journal = coin_seller.read_journal()
        if journal["halted"]:
            raise seller.SellerError("Seller halted. Review its journal before restarting.")
        with (state / "coin-seller-dashboard.log").open("ab") as log:
            process = subprocess.Popen(
                [sys.executable, "-m", "lp_profit_bot.coin_seller", "--live", "--watch"],
                cwd=seller.ROOT, stdin=subprocess.DEVNULL, stdout=log,
                stderr=subprocess.STDOUT, start_new_session=True,
            )
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise seller.SellerError("Seller exited. Check state/coin-seller-dashboard.log.")
            if seller_running('coin-seller.lock'):
                threading.Thread(target=process.wait, daemon=True).start()
                return "Live seller started: COIN.X → XNT. It waits for qualifying prices."
            time.sleep(0.05)
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        raise seller.SellerError("Seller startup timed out. Check state/coin-seller-dashboard.log.")


def start_pltr_seller():
    from . import pltr_seller
    """Serialize launches across dashboard instances; seller also holds its own lock."""
    state = seller.ROOT / "state"
    seller.ensure_private_state_dir(state)
    with START_LOCK, seller.open_state_lock(state / "pltr-dashboard-start.lock") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if seller_running('pltr-seller.lock'):
            return "Seller already running; no additional process started."
        journal = pltr_seller.read_journal()
        if journal["halted"]:
            raise seller.SellerError("Seller halted. Review its journal before restarting.")
        with (state / "pltr-seller-dashboard.log").open("ab") as log:
            process = subprocess.Popen(
                [sys.executable, "-m", "lp_profit_bot.pltr_seller", "--live", "--watch"],
                cwd=seller.ROOT, stdin=subprocess.DEVNULL, stdout=log,
                stderr=subprocess.STDOUT, start_new_session=True,
            )
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise seller.SellerError("Seller exited. Check state/pltr-seller-dashboard.log.")
            if seller_running('pltr-seller.lock'):
                threading.Thread(target=process.wait, daemon=True).start()
                return "Live seller started: PLTR.X → XNT. It waits for qualifying prices."
            time.sleep(0.05)
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        raise seller.SellerError("Seller startup timed out. Check state/pltr-seller-dashboard.log.")


def start_amd_seller():
    from . import amd_seller
    """Serialize launches across dashboard instances; seller also holds its own lock."""
    state = seller.ROOT / "state"
    seller.ensure_private_state_dir(state)
    with START_LOCK, seller.open_state_lock(state / "amd-dashboard-start.lock") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if seller_running('amd-seller.lock'):
            return "Seller already running; no additional process started."
        journal = amd_seller.read_journal()
        if journal["halted"]:
            raise seller.SellerError("Seller halted. Review its journal before restarting.")
        with (state / "amd-seller-dashboard.log").open("ab") as log:
            process = subprocess.Popen(
                [sys.executable, "-m", "lp_profit_bot.amd_seller", "--live", "--watch"],
                cwd=seller.ROOT, stdin=subprocess.DEVNULL, stdout=log,
                stderr=subprocess.STDOUT, start_new_session=True,
            )
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise seller.SellerError("Seller exited. Check state/amd-seller-dashboard.log.")
            if seller_running('amd-seller.lock'):
                threading.Thread(target=process.wait, daemon=True).start()
                return "Live seller started: AMD.X → XNT. It waits for qualifying prices."
            time.sleep(0.05)
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        raise seller.SellerError("Seller startup timed out. Check state/amd-seller-dashboard.log.")

def start_nvda_seller():
    from . import nvda_seller
    """Serialize launches across dashboard instances; seller also holds its own lock."""
    state = seller.ROOT / "state"
    seller.ensure_private_state_dir(state)
    with START_LOCK, seller.open_state_lock(state / "nvda-dashboard-start.lock") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if seller_running('nvda-seller.lock'):
            return "Seller already running; no additional process started."
        journal = nvda_seller.read_journal()
        if journal["halted"]:
            raise seller.SellerError("Seller halted. Review its journal before restarting.")
        with (state / "nvda-seller-dashboard.log").open("ab") as log:
            process = subprocess.Popen(
                [sys.executable, "-m", "lp_profit_bot.nvda_seller", "--live", "--watch"],
                cwd=seller.ROOT, stdin=subprocess.DEVNULL, stdout=log,
                stderr=subprocess.STDOUT, start_new_session=True,
            )
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise seller.SellerError("Seller exited. Check state/nvda-seller-dashboard.log.")
            if seller_running('nvda-seller.lock'):
                threading.Thread(target=process.wait, daemon=True).start()
                return "Live seller started: NVDA.X → XNT. It waits for qualifying prices."
            time.sleep(0.05)
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        raise seller.SellerError("Seller startup timed out. Check state/nvda-seller-dashboard.log.")

def start_aapl_seller():
    from . import aapl_seller
    """Serialize launches across dashboard instances; seller also holds its own lock."""
    state = seller.ROOT / "state"
    seller.ensure_private_state_dir(state)
    with START_LOCK, seller.open_state_lock(state / "aapl-dashboard-start.lock") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if seller_running('aapl-seller.lock'):
            return "Seller already running; no additional process started."
        journal = aapl_seller.read_journal()
        if journal["halted"]:
            raise seller.SellerError("Seller halted. Review its journal before restarting.")
        with (state / "aapl-seller-dashboard.log").open("ab") as log:
            process = subprocess.Popen(
                [sys.executable, "-m", "lp_profit_bot.aapl_seller", "--live", "--watch"],
                cwd=seller.ROOT, stdin=subprocess.DEVNULL, stdout=log,
                stderr=subprocess.STDOUT, start_new_session=True,
            )
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise seller.SellerError("Seller exited. Check state/aapl-seller-dashboard.log.")
            if seller_running('aapl-seller.lock'):
                threading.Thread(target=process.wait, daemon=True).start()
                return "Live seller started: AAPL.X → XNT. It waits for qualifying prices."
            time.sleep(0.05)
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        raise seller.SellerError("Seller startup timed out. Check state/aapl-seller-dashboard.log.")



def start_auto_conversion():
    from . import xnt_conversion
    """Serialize launches across dashboard instances; seller also holds its own lock."""
    state = seller.ROOT / "state"
    seller.ensure_private_state_dir(state)
    with START_LOCK, seller.open_state_lock(state / "auto-convert-start.lock") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if seller_running('auto-convert.lock'):
            return "Automatic conversion already running; no additional process started."
        journal = xnt_conversion.read_journal()
        if any(row['status']=='failed' and row.get('source') in ('spy_proceeds_auto','stock_proceeds_auto') for row in journal['entries']):
            raise seller.SellerError('Automatic conversion failed previously. Review its journal before restarting.')
        with (state / "auto-convert-dashboard.log").open("ab") as log:
            process = subprocess.Popen(
                [sys.executable, "-m", "lp_profit_bot.auto_convert", "--live", "--watch"],
                cwd=seller.ROOT, stdin=subprocess.DEVNULL, stdout=log,
                stderr=subprocess.STDOUT, start_new_session=True,
            )
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise seller.SellerError("Seller exited. Check state/auto-convert-dashboard.log.")
            if seller_running('auto-convert.lock'):
                threading.Thread(target=process.wait, daemon=True).start()
                return "Automatic conversion started: Stock proceeds → USDC.X; existing XNT reserve protected."
            time.sleep(0.05)
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        raise seller.SellerError("Seller startup timed out. Check state/auto-convert-dashboard.log.")


def read_public_file(name):
    try:
        path = seller.ROOT / "state" / name
        return seller.read_state_json(path), path.stat().st_mtime
    except FileNotFoundError:
        return None, None


def start_stock_purchase_watcher(asset_key, barrier_generation):
    """Continue a confirmed, journaled Solana purchase and bridge in the background."""
    from . import buy_googl_bridge as flow
    seller.require(asset_key in flow.ASSETS, "Unsupported stock")
    state = seller.ROOT / "state"
    seller.ensure_private_state_dir(state)
    with (state / f"{asset_key}-buy-bridge-dashboard.log").open("ab") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "lp_profit_bot.buy_stock_bridge", "--stock", asset_key,
             "--live", "--watch", "--barrier-generation", str(barrier_generation)],
            cwd=seller.ROOT, stdin=subprocess.DEVNULL,
            stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    threading.Thread(target=process.wait, daemon=True).start()
    return process.poll() is None


def seller_running(name="seller.lock"):
    path = seller.ROOT / "state" / name
    if not path.exists():
        return False
    with path.open("r") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(stream, fcntl.LOCK_UN)
        return False


class DashboardData:
    def __init__(self):
        self.activity = ActivityFeed()
        self.proceeds = ProceedsHistory()
        self.lock = threading.Lock()
        self.meta = None
        self.meta_error = None
        self.coin = None
        self.coin_error = None
        self.pltr = None
        self.pltr_error = None
        self.amd = None
        self.amd_error = None
        self.nvda = None
        self.nvda_error = None
        self.aapl = None
        self.aapl_error = None
        self.tsla = None
        self.tsla_error = None
        self.spcx = None
        self.spcx_error = None
        self.spy = None
        self.spy_error = None
        self.chain = None
        self.reference = None
        self.errors = {}
        self.history = []
        self.stop = threading.Event()

    def poll(self):
        while not self.stop.is_set():
            self.refresh()
            self.stop.wait(30)

    def refresh(self):
        try:
            snap = seller.snapshot()
            now = time.time()
            chain = {"fetched_at": now, "slot": snap["slot"],
                     "xnt": str(Decimal(snap["native_balance"])/10**9),
                     "googl": str(Decimal(snap["balance_in"])/10**8),
                     "usdc": str(Decimal(snap["balance_out"])/10**6),
                     "pool_price": str(Decimal(snap["reserve_out"])/Decimal(snap["reserve_in"])*100)}
            with self.lock:
                self.chain = chain
                self.errors.pop("chain", None)
        except Exception:
            with self.lock:
                self.errors["chain"] = "Chain refresh failed. Previous balances may be stale."
        try:
            price, updated = seller.reference_price()
            with self.lock:
                self.reference = {"price": str(price), "updated_at": updated, "fetched_at": time.time()}
                self.errors.pop("reference", None)
        except Exception:
            with self.lock:
                self.errors["reference"] = "Reference price unavailable or stale."
        with self.lock:
            if self.chain and self.reference and not self.errors:
                self.history.append({"at": self.chain["fetched_at"], "pool": float(self.chain["pool_price"]),
                                     "reference": float(self.reference["price"])})
                self.history = self.history[-120:]

    def refresh_spy(self):
        try:
            value = spy_snapshot()
            with self.lock:
                self.spy = value
                self.spy_error = None
        except Exception:
            with self.lock:
                self.spy_error = "SPY.X refresh failed. Previous values may be stale."

    def poll_spcx(self):
        while not self.stop.is_set():
            try:
                value = spcx_snapshot()
                with self.lock:
                    self.spcx = value
                    self.spcx_error = None
            except Exception:
                with self.lock:
                    self.spcx_error = 'SPCX.X refresh failed. Previous values may be stale.'
            self.stop.wait(60)

    def poll_tsla(self):
        while not self.stop.is_set():
            try:
                value = tsla_snapshot()
                with self.lock:
                    self.tsla = value
                    self.tsla_error = None
            except Exception:
                with self.lock:
                    self.tsla_error = 'TSLA.X refresh failed. Previous values may be stale.'
            self.stop.wait(60)

    def poll_meta(self):
        while not self.stop.is_set():
            try:
                value = meta_snapshot()
                with self.lock:
                    self.meta = value
                    self.meta_error = None
            except Exception:
                with self.lock:
                    self.meta_error = 'META.X refresh failed. Previous values may be stale.'
            self.stop.wait(60)

    def poll_coin(self):
        while not self.stop.is_set():
            try:
                value = coin_snapshot()
                with self.lock:
                    self.coin = value
                    self.coin_error = None
            except Exception:
                with self.lock:
                    self.coin_error = 'COIN.X refresh failed. Previous values may be stale.'
            self.stop.wait(60)

    def poll_pltr(self):
        while not self.stop.is_set():
            try:
                value = pltr_snapshot()
                with self.lock:
                    self.pltr = value
                    self.pltr_error = None
            except Exception:
                with self.lock:
                    self.pltr_error = 'PLTR.X refresh failed. Previous values may be stale.'
            self.stop.wait(60)

    def poll_amd(self):
        while not self.stop.is_set():
            try:
                value = amd_snapshot()
                with self.lock:
                    self.amd = value
                    self.amd_error = None
            except Exception:
                with self.lock:
                    self.amd_error = 'AMD.X refresh failed. Previous values may be stale.'
            self.stop.wait(60)

    def poll_nvda(self):
        while not self.stop.is_set():
            try:
                value = nvda_snapshot()
                with self.lock:
                    self.nvda = value
                    self.nvda_error = None
            except Exception:
                with self.lock:
                    self.nvda_error = 'NVDA.X refresh failed. Previous values may be stale.'
            self.stop.wait(60)

    def poll_aapl(self):
        while not self.stop.is_set():
            try:
                value = aapl_snapshot()
                with self.lock:
                    self.aapl = value
                    self.aapl_error = None
            except Exception:
                with self.lock:
                    self.aapl_error = 'AAPL.X refresh failed. Previous values may be stale.'
            self.stop.wait(60)

    def poll_spy(self):
        while not self.stop.is_set():
            self.refresh_spy()
            try:
                from .xnt_conversion import ready
                from .spy_seller import native_lock
                with native_lock():
                    ready()
            except Exception:
                pass
            self.stop.wait(60)

    def status(self):
        with self.lock:
            data = {"chain": self.chain, "reference": self.reference,
                    "errors": list(self.errors.values()), "history": list(self.history),
                    "spy": dict(self.spy) if self.spy else None, "spy_error": self.spy_error,
                    "spcx": dict(self.spcx) if self.spcx else None, "spcx_error": self.spcx_error,
                    "tsla": dict(self.tsla) if self.tsla else None, "tsla_error": self.tsla_error}
        data["meta"] = dict(self.meta) if self.meta else None
        data["meta_error"] = self.meta_error
        data["coin"] = dict(self.coin) if self.coin else None
        data["coin_error"] = self.coin_error
        data["pltr"] = dict(self.pltr) if self.pltr else None
        data["pltr_error"] = self.pltr_error
        data["amd"] = dict(self.amd) if self.amd else None
        data["amd_error"] = self.amd_error
        data["nvda"] = dict(self.nvda) if self.nvda else None
        data["nvda_error"] = self.nvda_error
        data["aapl"] = dict(self.aapl) if self.aapl else None
        data["aapl_error"] = self.aapl_error
        now = time.time()
        for key in ('spy', 'spcx', 'tsla', 'meta', 'coin', 'pltr', 'amd', 'nvda', 'aapl'):
            market = data[key]
            if market:
                market['fresh'] = bool(not data[key+'_error'] and 0 <= now-market['fetched_at'] <= 120
                                       and 0 <= now-market['pool_updated_at'] <= 300
                                       and 0 <= now-market['reference_updated_at'] <= 300)
                if not market['fresh']:
                    market['gap_percent'] = None
        data.update(now=now, wallet=seller.WALLET, pool=seller.GOOGL_POOL,
                    policy={"cap": None, "amount_policy": "available_inventory",
                            "batch": str(Decimal(seller.CHUNK_RAW)/10**8),
                            "cost_allowance_xnt": str(Decimal(seller.COST_CEILING)/10**9)})
        data["market_fresh"] = bool(data["chain"] and data["reference"] and not data["errors"]
                                    and 0 <= now-data["chain"]["fetched_at"] <= 90
                                    and 0 <= now-data["reference"]["updated_at"] <= 300)
        data["gap_percent"] = (str((Decimal(data["chain"]["pool_price"])/Decimal(data["reference"]["price"])-1)*100)
                               if data["market_fresh"] else None)
        try:
            journal = seller.read_journal()
            rows = [{key: row.get(key) for key in ("signature", "amount_raw", "minimum_output_raw", "status", "created_at")}
                    for row in journal["entries"]]
            reserved = sum(row["amount_raw"] for row in rows)
            confirmed = sum(row["amount_raw"] for row in rows if row["status"] == "finalized")
            data["journal"] = {"entries": list(reversed(rows)), "reserved": str(Decimal(reserved)/10**8),
                               "confirmed": str(Decimal(confirmed)/10**8),
                               "remaining": None,
                               "halted": journal["halted"]}
        except Exception:
            data["journal"] = None
            data["errors"].append("Seller journal could not be validated. Sale history is unknown.")
        try:
            data["seller_running"] = seller_running()
        except OSError:
            data["seller_running"] = None
        try:
            runtime, stamp = read_public_file("seller-runtime.json")
            if not isinstance(runtime, dict) or not isinstance(runtime.get("updated_at"), (int, float)) or now-runtime["updated_at"] > 120:
                runtime = None
            data["runtime"] = ({key: runtime.get(key) for key in ("mode", "status", "updated_at", "pid")}
                               if isinstance(runtime, dict) else None)
            simulation, stamp = read_public_file("seller-last-simulation.json")
            data["simulation"] = ({key: simulation.get(key) for key in
                                   ("status", "amount_googl", "minimum_usdc", "simulated_usdc", "reference_usd")}
                                  if isinstance(simulation, dict) else None)
            data["simulation_updated_at"] = stamp
        except (OSError, ValueError, TypeError):
            data["runtime"] = None
            data["simulation"] = None
        try:
            from . import spy_seller
            journal = spy_seller.read_journal()
            reserved = sum(row['amount_raw'] for row in journal['entries'])
            confirmed = sum(row['amount_raw'] for row in journal['entries'] if row['status']=='finalized')
            runtime, _ = read_public_file('spy-seller-runtime.json')
            data['spy_seller'] = {'running': seller_running('spy-seller.lock'),
                'reserved': str(Decimal(reserved)/10**8), 'confirmed': str(Decimal(confirmed)/10**8),
                'remaining': None, 'amount_policy': 'available_inventory',
                'halted':journal['halted'], 'status': runtime.get('status') if isinstance(runtime,dict) else None}
        except Exception:
            data['spy_seller'] = None
        try:
            from . import spcx_seller
            journal = spcx_seller.read_journal()
            reserved = sum(row['amount_raw'] for row in journal['entries'])
            confirmed = sum(row['amount_raw'] for row in journal['entries'] if row['status']=='finalized')
            runtime, _ = read_public_file('spcx-seller-runtime.json')
            data['spcx_seller'] = {'running': seller_running('spcx-seller.lock'),
                'reserved': str(Decimal(reserved)/10**8), 'confirmed': str(Decimal(confirmed)/10**8),
                'remaining': None, 'amount_policy': 'available_inventory',
                'halted':journal['halted'], 'status': runtime.get('status') if isinstance(runtime,dict) else None}
        except Exception:
            data['spcx_seller'] = None
        try:
            from . import tsla_seller
            journal = tsla_seller.read_journal()
            reserved = sum(row['amount_raw'] for row in journal['entries'])
            confirmed = sum(row['amount_raw'] for row in journal['entries'] if row['status']=='finalized')
            runtime, _ = read_public_file('tsla-seller-runtime.json')
            data['tsla_seller'] = {'running': seller_running('tsla-seller.lock'),
                'reserved': str(Decimal(reserved)/10**8), 'confirmed': str(Decimal(confirmed)/10**8),
                'remaining': None, 'amount_policy': 'available_inventory',
                'halted':journal['halted'], 'status': runtime.get('status') if isinstance(runtime,dict) else None}
        except Exception:
            data['tsla_seller'] = None
        try:
            from . import meta_seller
            journal = meta_seller.read_journal()
            reserved = sum(row['amount_raw'] for row in journal['entries'])
            confirmed = sum(row['amount_raw'] for row in journal['entries'] if row['status']=='finalized')
            runtime, _ = read_public_file('meta-seller-runtime.json')
            data['meta_seller'] = {'running': seller_running('meta-seller.lock'),
                'reserved': str(Decimal(reserved)/10**8), 'confirmed': str(Decimal(confirmed)/10**8),
                'remaining': None, 'amount_policy': 'available_inventory',
                'halted':journal['halted'], 'status': runtime.get('status') if isinstance(runtime,dict) else None}
        except Exception:
            data['meta_seller'] = None
        try:
            from . import coin_seller
            journal = coin_seller.read_journal()
            reserved = sum(row['amount_raw'] for row in journal['entries'])
            confirmed = sum(row['amount_raw'] for row in journal['entries'] if row['status']=='finalized')
            runtime, _ = read_public_file('coin-seller-runtime.json')
            data['coin_seller'] = {'running': seller_running('coin-seller.lock'),
                'reserved': str(Decimal(reserved)/10**8), 'confirmed': str(Decimal(confirmed)/10**8),
                'remaining': None, 'amount_policy': 'available_inventory',
                'halted':journal['halted'], 'status': runtime.get('status') if isinstance(runtime,dict) else None}
        except Exception:
            data['coin_seller'] = None
        try:
            from . import pltr_seller
            journal = pltr_seller.read_journal()
            reserved = sum(row['amount_raw'] for row in journal['entries'])
            confirmed = sum(row['amount_raw'] for row in journal['entries'] if row['status']=='finalized')
            runtime, _ = read_public_file('pltr-seller-runtime.json')
            data['pltr_seller'] = {'running': seller_running('pltr-seller.lock'),
                'reserved': str(Decimal(reserved)/10**8), 'confirmed': str(Decimal(confirmed)/10**8),
                'remaining': None, 'amount_policy': 'available_inventory',
                'halted':journal['halted'], 'status': runtime.get('status') if isinstance(runtime,dict) else None}
        except Exception:
            data['pltr_seller'] = None
        try:
            from . import amd_seller
            journal = amd_seller.read_journal()
            reserved = sum(row['amount_raw'] for row in journal['entries'])
            confirmed = sum(row['amount_raw'] for row in journal['entries'] if row['status']=='finalized')
            runtime, _ = read_public_file('amd-seller-runtime.json')
            data['amd_seller'] = {'running': seller_running('amd-seller.lock'),
                'reserved': str(Decimal(reserved)/10**8), 'confirmed': str(Decimal(confirmed)/10**8),
                'remaining': None, 'amount_policy': 'available_inventory',
                'halted':journal['halted'], 'status': runtime.get('status') if isinstance(runtime,dict) else None}
        except Exception:
            data['amd_seller'] = None
        try:
            from . import nvda_seller
            journal = nvda_seller.read_journal()
            reserved = sum(row['amount_raw'] for row in journal['entries'])
            confirmed = sum(row['amount_raw'] for row in journal['entries'] if row['status']=='finalized')
            runtime, _ = read_public_file('nvda-seller-runtime.json')
            data['nvda_seller'] = {'running': seller_running('nvda-seller.lock'),
                'reserved': str(Decimal(reserved)/10**8), 'confirmed': str(Decimal(confirmed)/10**8),
                'remaining': None, 'amount_policy': 'available_inventory',
                'halted':journal['halted'], 'status': runtime.get('status') if isinstance(runtime,dict) else None}
        except Exception:
            data['nvda_seller'] = None
        try:
            from . import aapl_seller
            journal = aapl_seller.read_journal()
            reserved = sum(row['amount_raw'] for row in journal['entries'])
            confirmed = sum(row['amount_raw'] for row in journal['entries'] if row['status']=='finalized')
            runtime, _ = read_public_file('aapl-seller-runtime.json')
            data['aapl_seller'] = {'running': seller_running('aapl-seller.lock'),
                'reserved': str(Decimal(reserved)/10**8), 'confirmed': str(Decimal(confirmed)/10**8),
                'remaining': None, 'amount_policy': 'available_inventory',
                'halted':journal['halted'], 'status': runtime.get('status') if isinstance(runtime,dict) else None}
        except Exception:
            data['aapl_seller'] = None
        try:
            from . import xnt_conversion
            rows = xnt_conversion.read_journal()['entries']
            data['xnt_conversions'] = [{key: row.get(key) for key in
                ('signature','amount_raw','minimum_output_raw','status','created_at')} for row in rows[-10:]][::-1]
        except Exception:
            data['xnt_conversions'] = None
        try:
            runtime, _ = read_public_file('auto-convert-runtime.json')
            data['auto_conversion'] = {'running': seller_running('auto-convert.lock'),
                'scope': 'Approved stock sale proceeds only', **({key: runtime.get(key) for key in
                ('status','mode','updated_at','reserve_raw','proceeds_raw','converted_reserved_raw',
                 'conversion_cost_raw','available_raw','amount_xnt','minimum_usdc','signature','message')}
                if isinstance(runtime, dict) else {})}
        except Exception:
            data['auto_conversion'] = None
        try:
            from . import auto_bridge
            rows = auto_bridge.read_journal()['entries'][-20:]
            data['auto_bridge'] = {'running': seller_running('auto-bridge.lock'),
                'entries': [{key: row.get(key) for key in
                    ('signature', 'destination_signature', 'amount_raw', 'fee_raw', 'status', 'created_at')}
                    for row in reversed(rows)]}
        except Exception:
            data['auto_bridge'] = None
        from . import buy_googl_bridge as stock_purchase
        try:
            purchase_running = seller_running('googlx-buy-bridge.lock')
        except OSError:
            purchase_running = None
        data['stock_purchase'] = {'running': purchase_running}
        for key, asset in stock_purchase.ASSETS.items():
            try:
                row = stock_purchase.read_journal(asset)
                attempts = stock_purchase.read_history(asset)
                data['stock_purchase'][key] = {'asset': asset['symbol'], 'stage': row['stage'],
                    'attempt_count': sum(bool(attempt.get('swap_signature')) for attempt in attempts),
                    'spend_raw': row.get('spend_raw'),
                    'swap_signature': row.get('swap_signature'),
                    'bridge_signature': row.get('bridge_signature'),
                    'destination_signature': row.get('destination_signature'),
                    'bought_raw': row.get('bought_raw'),
                    'bridge_amount_raw': row.get('bridge_amount_raw'),
                    'created_at': row.get('created_at'),
                    'swap_finalized_at': row.get('swap_finalized_at'),
                    'bridge_submitted_at': row.get('bridge_submitted_at'),
                    'bridge_finalized_at': row.get('bridge_finalized_at'),
                    'completed_at': row.get('completed_at'),
                    'failed_at': row.get('failed_at'),
                    'history': [{field: attempt.get(field) for field in
                        ('stage', 'spend_raw', 'swap_signature', 'bridge_signature',
                         'destination_signature', 'created_at', 'swap_finalized_at',
                         'bridge_submitted_at', 'bridge_finalized_at', 'completed_at',
                         'failed_at')} for attempt in attempts]}
            except Exception:
                data['stock_purchase'][key] = {'asset': asset['symbol'], 'stage': 'unavailable'}
        data['workers'] = worker_control.status()
        data['activity'] = self.activity.snapshot()
        data['proceeds'] = self.proceeds.snapshot()
        from .stock_policy import public_policy
        data['stock_policy'] = public_policy()
        return data


def handler_for(data, port):
    token = secrets.token_urlsafe(32)
    conversion_quotes = {}
    bridge_quotes = {}
    stock_purchase_quotes = {}
    quote_lock = threading.Lock()
    class Handler(BaseHTTPRequestHandler):
        control_token = token

        def has_session(self):
            cookie = SimpleCookie()
            try:
                cookie.load(self.headers.get('Cookie', ''))
            except Exception:
                return False
            value = cookie.get('dashboard_session')
            return bool(value and secrets.compare_digest(value.value, token))

        def log_message(self, format, *args):
            pass

        def do_POST(self):
            host = self.headers.get("Host")
            if (host not in (f"127.0.0.1:{port}", f"localhost:{port}")
                    or self.headers.get("Origin") != f"http://{host}"
                    or not (self.has_session() or secrets.compare_digest(
                        self.headers.get("X-Dashboard-Token", ""), token))):
                self.send_error(403)
                return
            stop_routes = {'/api/scripts/googl/stop': 'googl', '/api/scripts/spy/stop': 'spy',
                           '/api/scripts/conversion/stop': 'conversion', '/api/scripts/bridge/stop': 'bridge', '/api/scripts/spcx/stop': 'spcx', '/api/scripts/tsla/stop': 'tsla', '/api/scripts/meta/stop': 'meta', '/api/scripts/coin/stop': 'coin', '/api/scripts/pltr/stop': 'pltr', '/api/scripts/amd/stop': 'amd', '/api/scripts/nvda/stop': 'nvda', '/api/scripts/aapl/stop': 'aapl', '/api/scripts/stop-all': 'all'}
            if self.path in stop_routes:
                try:
                    with START_LOCK:
                        key = stop_routes[self.path]
                        message = worker_control.stop_all() if key == 'all' else worker_control.stop(key)
                    self.respond(json.dumps({'message': message}).encode(), 'application/json')
                except (seller.SellerError, OSError):
                    self.respond(json.dumps({'message': 'Stop was not confirmed for every selected script. Check script status before retrying.'}).encode(), 'application/json', 409)
                return
            if self.path in ('/api/xnt/quote', '/api/xnt/confirm'):
                from . import xnt_conversion
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length <= 1024:
                        raise ValueError('Invalid body length')
                    body = json.loads(self.rfile.read(length))
                    if not isinstance(body, dict):
                        raise ValueError('Invalid body')
                    if self.path == '/api/xnt/quote':
                        result = xnt_conversion.preview(body.get('amount'))
                        quote_id = secrets.token_urlsafe(24)
                        with quote_lock:
                            for key in list(conversion_quotes):
                                if conversion_quotes[key]['expires_at'] < time.time():
                                    del conversion_quotes[key]
                            seller.require(len(conversion_quotes)<100,'Too many pending previews')
                            conversion_quotes[quote_id] = result
                        result = dict(result, quote_id=quote_id)
                    else:
                        with quote_lock:
                            quote = conversion_quotes.pop(str(body.get('quote_id')), None)
                        seller.require(quote is not None, 'Quote already used or unavailable; preview again')
                        result = xnt_conversion.execute(quote)
                    self.respond(json.dumps(result).encode(), 'application/json')
                except seller.SellerError as error:
                    self.respond(json.dumps({'message':str(error)}).encode(), 'application/json', 409)
                except Exception:
                    self.respond(json.dumps({'message':'Conversion unavailable. Check the amount or transaction status before retrying.'}).encode(), 'application/json', 400)
                return
            if self.path in ('/api/bridge/preview', '/api/bridge/confirm'):
                from . import auto_bridge
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length <= 1024:
                        raise ValueError('Invalid body length')
                    body = json.loads(self.rfile.read(length))
                    if not isinstance(body, dict):
                        raise ValueError('Invalid body')
                    if self.path == '/api/bridge/preview':
                        result = auto_bridge.preview(body.get('amount'))
                        quote_id = secrets.token_urlsafe(24)
                        with quote_lock:
                            for key in list(bridge_quotes):
                                if bridge_quotes[key]['expires_at'] < time.time():
                                    del bridge_quotes[key]
                            seller.require(len(bridge_quotes) < 100, 'Too many pending bridge previews')
                            bridge_quotes[quote_id] = result
                        result = dict(result, quote_id=quote_id)
                    else:
                        with quote_lock:
                            quote = bridge_quotes.pop(str(body.get('quote_id')), None)
                        seller.require(quote is not None, 'Preview already used or unavailable; preview again')
                        result = auto_bridge.execute_manual(quote)
                    self.respond(json.dumps(result).encode(), 'application/json')
                except seller.SellerError as error:
                    self.respond(json.dumps({'message':str(error)}).encode(), 'application/json', 409)
                except Exception:
                    self.respond(json.dumps({'message':'Bridge unavailable. Check the amount and transaction status before retrying.'}).encode(), 'application/json', 400)
                return
            if self.path in ('/api/stock-purchase/preview', '/api/stock-purchase/confirm'):
                from . import buy_googl_bridge as flow
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length <= 1024:
                        raise ValueError('Invalid body length')
                    body = json.loads(self.rfile.read(length))
                    if not isinstance(body, dict):
                        raise ValueError('Invalid body')
                    if self.path == '/api/stock-purchase/preview':
                        asset_key = body.get('stock')
                        seller.require(type(asset_key) is str and asset_key in flow.ASSETS,
                                       'Choose a supported stock')
                        spend_raw = flow.parse_usdc_amount(body.get('amount'))
                        with flow.process_lock():
                            before = flow.read_journal(flow.ASSETS[asset_key])['stage']
                            result = flow.cycle(False, asset_key, spend_raw=spend_raw,
                                                repeat=before == 'completed')
                            stage = flow.read_journal(flow.ASSETS[asset_key])['stage']
                            attempt_count = len(flow.read_history(flow.ASSETS[asset_key]))
                        action = ('new_purchase' if result['status'] == 'SWAP_READY' and
                                  stage in ('new', 'completed') else
                                  'resume_bridge' if result['status'] == 'BRIDGE_READY' and
                                  stage == 'swap_finalized' else 'check_status')
                        preview = {'asset': asset_key, 'stage': stage, 'spend_raw': spend_raw,
                                   'attempt_count': attempt_count, 'action': action,
                                   'barrier_generation': execution_barrier.snapshot(),
                                   'minimum_output_raw': int(Decimal(result['minimum_stock'])*10**8)
                                   if action == 'new_purchase' else None,
                                   'expires_at': time.time()+30}
                        quote_id = secrets.token_urlsafe(24)
                        if stage != 'failed':
                            with quote_lock:
                                for key in list(stock_purchase_quotes):
                                    if stock_purchase_quotes[key]['expires_at'] < time.time():
                                        del stock_purchase_quotes[key]
                                seller.require(len(stock_purchase_quotes) < 100,
                                               'Too many pending stock previews')
                                stock_purchase_quotes[quote_id] = preview
                        result = dict(result, stock=asset_key, action=action,
                                      expires_at=preview['expires_at'],
                                      quote_id=quote_id if stage != 'failed' else None)
                    else:
                        with quote_lock:
                            preview = stock_purchase_quotes.pop(str(body.get('quote_id')), None)
                        seller.require(preview is not None and preview['expires_at'] >= time.time(),
                                       'Preview expired or already used; preview again')
                        asset_key = preview['asset']
                        with START_LOCK, flow.process_lock():
                            current = flow.read_journal(flow.ASSETS[asset_key])
                            seller.require(current['stage'] == preview['stage'] and
                                           len(flow.read_history(flow.ASSETS[asset_key])) == preview['attempt_count'],
                                           'Stock bridge state changed; preview again')
                            action = preview['action']
                            if action == 'new_purchase':
                                seller.require(preview['minimum_output_raw'] is not None and
                                               current['stage'] in ('new', 'completed'),
                                               'Fresh purchase preview required')
                                result = flow.cycle(True, asset_key, preview['minimum_output_raw'],
                                    spend_raw=preview['spend_raw'], repeat=current['stage']=='completed',
                                    barrier_generation=preview['barrier_generation'])
                            elif action == 'resume_bridge':
                                seller.require(current['stage'] == 'swap_finalized',
                                               'Bridge state changed; preview again')
                                result = flow.cycle(True, asset_key, repeat=False,
                                    barrier_generation=preview['barrier_generation'])
                            else:
                                result = flow.cycle(False, asset_key, repeat=False)
                        result = dict(result, stock=asset_key)
                        if action in ('new_purchase', 'resume_bridge') and result['status'] in ('SWAP_PENDING', 'BRIDGE_PENDING',
                                                'WAITING_FOR_X1_RECEIPT'):
                            try:
                                result['tracking_started'] = start_stock_purchase_watcher(
                                    asset_key, preview['barrier_generation'])
                            except OSError:
                                result['tracking_started'] = False
                    self.respond(json.dumps(result).encode(), 'application/json')
                except seller.SellerError as error:
                    self.respond(json.dumps({'message': str(error)}).encode(), 'application/json', 409)
                except Exception:
                    self.respond(json.dumps({'message': 'Stock purchase or bridge unavailable. Check the journal and transaction status before retrying.'}).encode(), 'application/json', 500)
                return
            if self.path not in ("/api/seller/start", "/api/spy/seller/start", "/api/conversion/start", "/api/spcx/seller/start", "/api/tsla/seller/start", "/api/meta/seller/start", "/api/coin/seller/start", "/api/pltr/seller/start", "/api/amd/seller/start", "/api/nvda/seller/start", "/api/aapl/seller/start"):
                self.send_error(404)
                return
            try:
                message = (start_aapl_seller() if self.path == "/api/aapl/seller/start" else
                           start_nvda_seller() if self.path == "/api/nvda/seller/start" else
                           start_meta_seller() if self.path == "/api/meta/seller/start" else
                           start_coin_seller() if self.path == "/api/coin/seller/start" else
                           start_pltr_seller() if self.path == "/api/pltr/seller/start" else
                           start_amd_seller() if self.path == "/api/amd/seller/start" else
                           start_spcx_seller() if self.path == "/api/spcx/seller/start" else
                           start_tsla_seller() if self.path == "/api/tsla/seller/start" else
                           start_auto_conversion() if self.path == "/api/conversion/start" else
                           start_spy_seller() if self.path == "/api/spy/seller/start" else start_seller())
                status = 200
            except seller.SellerError as error:
                message, status = str(error), 409
            except Exception:
                message, status = "Unable to start seller. Check local configuration and journal.", 500
            self.respond(json.dumps({"message": message}).encode(), "application/json", status)

        def do_GET(self):
            # Exact Host allowlist prevents DNS rebinding from exposing the local dashboard.
            if self.headers.get("Host") not in (f"127.0.0.1:{port}", f"localhost:{port}"):
                self.send_error(403)
                return
            path = urlsplit(self.path).path
            routes = {"/": ("index.html", "text/html; charset=utf-8"),
                      "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                      "/styles.css": ("styles.css", "text/css; charset=utf-8")}
            if path == "/api/status":
                content = json.dumps(dict(data.status(), controls_unlocked=True)).encode()
                mime = "application/json"
            elif path in routes:
                filename, mime = routes[path]
                content = (ASSETS / filename).read_bytes()
            else:
                self.send_error(404)
                return
            self.respond(content, mime, session=path in ('/', '/api/status'))

        def respond(self, content, mime, status=200, session=False):
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            if session:
                self.send_header('Set-Cookie', f'dashboard_session={token}; HttpOnly; SameSite=Strict; Path=/')
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(content)
    return Handler


def main():
    parser = argparse.ArgumentParser(description="Local seller dashboard with live start control")
    parser.add_argument("--port", type=int, default=8795)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Choose a port between 1024 and 65535")
    seller.ensure_private_state_dir()
    data = DashboardData()
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(data, args.port))
    except OSError:
        parser.exit(1, f"Cannot bind localhost:{args.port}. Choose another port with --port.\n")
    worker = threading.Thread(target=data.poll, daemon=True)
    worker.start()
    threading.Thread(target=data.proceeds.poll, args=(data.stop,), daemon=True).start()
    threading.Thread(target=data.activity.poll, args=(data.stop,), daemon=True).start()
    threading.Thread(target=data.poll_spy, daemon=True).start()
    threading.Thread(target=data.poll_spcx, daemon=True).start()
    threading.Thread(target=data.poll_tsla, daemon=True).start()
    threading.Thread(target=data.poll_meta, daemon=True).start()
    threading.Thread(target=data.poll_coin, daemon=True).start()
    threading.Thread(target=data.poll_pltr, daemon=True).start()
    threading.Thread(target=data.poll_amd, daemon=True).start()
    threading.Thread(target=data.poll_nvda, daemon=True).start()
    threading.Thread(target=data.poll_aapl, daemon=True).start()
    print(f"Dashboard: http://localhost:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        data.stop.set()
        server.server_close()


if __name__ == "__main__":
    main()
