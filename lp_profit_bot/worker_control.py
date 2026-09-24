"""Inspect and stop only this project's allowlisted trading workers."""
import fcntl
import json
import os
from pathlib import Path
import signal
import time
from . import seller, execution_barrier

WORKERS = {
    'googl': ('GOOGL.X → USDC.X', 'lp_profit_bot.seller', 'seller.lock', 'seller-runtime.json'),
    'spy': ('SPY.X → XNT', 'lp_profit_bot.spy_seller', 'spy-seller.lock', 'spy-seller-runtime.json'),
    'spcx': ('SPCX.X → XNT', 'lp_profit_bot.spcx_seller', 'spcx-seller.lock', 'spcx-seller-runtime.json'),
    'tsla': ('TSLA.X → XNT', 'lp_profit_bot.tsla_seller', 'tsla-seller.lock', 'tsla-seller-runtime.json'),
    'meta': ('META.X → XNT', 'lp_profit_bot.meta_seller', 'meta-seller.lock', 'meta-seller-runtime.json'),
    'coin': ('COIN.X → XNT', 'lp_profit_bot.coin_seller', 'coin-seller.lock', 'coin-seller-runtime.json'),
    'pltr': ('PLTR.X → XNT', 'lp_profit_bot.pltr_seller', 'pltr-seller.lock', 'pltr-seller-runtime.json'),
    'amd': ('AMD.X → XNT', 'lp_profit_bot.amd_seller', 'amd-seller.lock', 'amd-seller-runtime.json'),
    'nvda': ('NVDA.X → XNT', 'lp_profit_bot.nvda_seller', 'nvda-seller.lock', 'nvda-seller-runtime.json'),
    'aapl': ('AAPL.X → XNT', 'lp_profit_bot.aapl_seller', 'aapl-seller.lock', 'aapl-seller-runtime.json'),
    'conversion': ('Stock proceeds → USDC.X', 'lp_profit_bot.auto_convert', 'auto-convert.lock', 'auto-convert-runtime.json'),
    'bridge': ('USDC.X → Solana USDC', 'lp_profit_bot.auto_bridge', 'auto-bridge.lock', 'auto-bridge-runtime.json'),
    'buy_stock_bridge': ('Stock purchase/bridge watcher', 'lp_profit_bot.buy_stock_bridge', 'googlx-buy-bridge.lock', None),
    'buy_googl_bridge': ('Legacy stock purchase/bridge watcher', 'lp_profit_bot.buy_googl_bridge', 'googlx-buy-bridge.lock', None),
}


def running(key):
    path = seller.ROOT/'state'/WORKERS[key][2]
    if not path.exists() and not path.is_symlink():
        return False
    with seller.open_state_lock(path) as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(stream, fcntl.LOCK_UN)
        return False


def status():
    result = {}
    for key, (label, module, lock, filename) in WORKERS.items():
        try:
            active = running(key)
        except OSError:
            active = None
        try:
            runtime = seller.read_state_json(seller.ROOT/'state'/filename) if filename else {}
            fresh = isinstance(runtime,dict) and 0 <= time.time()-runtime.get('updated_at',0) <= 120
        except (OSError, ValueError, TypeError):
            runtime, fresh = {}, False
        result[key] = {'label':label,'running':active,
                       'mode':runtime.get('mode') if fresh and active else None,
                       'activity':runtime.get('status') if fresh and active else None,
                       'updated_at':runtime.get('updated_at') if fresh and active else None,
                       'activity_fresh':bool(fresh and active)}
    return result


def matches(pid, module):
    """Neither a client-supplied PID nor a stale runtime PID authorizes a signal."""
    try:
        path = Path('/proc')/str(pid)
        if path.stat().st_uid != os.getuid() or (path/'cwd').resolve() != seller.ROOT.resolve():
            return False
        argv = (path/'cmdline').read_bytes().split(b'\0')
        return (len(argv)>=3 and argv[1]==b'-m' and argv[2]==module.encode()
                and Path(os.fsdecode(argv[0])).name.startswith('python'))
    except (OSError, ValueError):
        return False


def stop(key):
    if key not in WORKERS:
        raise seller.SellerError('Unknown script')
    label,module,_,_=WORKERS[key]
    # Inspect exact command + project directory, then pin process identity with pidfd.
    # This also works if a worker has not written its first telemetry record yet.
    signaled = 0
    for entry in Path('/proc').iterdir():
        if not entry.name.isdecimal():
            continue
        pid=int(entry.name)
        if not matches(pid,module):
            continue
        try:
            fd=os.pidfd_open(pid)
        except ProcessLookupError:
            continue
        try:
            if matches(pid,module):
                signal.pidfd_send_signal(fd,signal.SIGTERM)
                signaled += 1
        except ProcessLookupError:
            pass
        finally:
            os.close(fd)
    deadline=time.monotonic()+3
    while running(key) and time.monotonic()<deadline:
        time.sleep(.05)
    if running(key):
        raise seller.SellerError(label+' has not stopped; check its process. Stop was not confirmed.')
    return label+(' stopped.' if signaled else ' is already stopped.')


def stop_all():
    execution_barrier.stop()
    messages=[]; failures=[]
    for key in WORKERS:
        try:
            messages.append(stop(key))
        except (seller.SellerError,OSError) as error:
            failures.append(WORKERS[key][0]+': '+str(error))
    if failures:
        raise seller.SellerError(' '.join(messages+failures))
    return 'All trading scripts stopped. Dashboard monitoring remains active.'
