"""Batch stock reference prices across workers without changing source timestamps."""
import fcntl
import json
import time
from pathlib import Path
from . import comparison
from .ninja import NinjaError

CACHE = Path(__file__).resolve().parents[1]/'state'/'stock-reference-cache.json'
IDS = ('sp500-xstock', 'spacex-xstocks', 'tesla-xstock', 'meta-xstock', 'coinbase-xstock', 'palantir-xstock', 'amd-xstock', 'nvidia-xstock')


def fetch_reference(coin_id):
    from . import seller
    if coin_id not in IDS:
        raise ValueError('Unsupported reference asset')
    seller.ensure_private_state_dir(CACHE.parent)
    with seller.open_state_lock(CACHE.with_suffix('.lock')) as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        now = time.time()
        try:
            cached = seller.read_state_json(CACHE)
        except (OSError, ValueError):
            cached = {}
        age = now-cached.get('fetched_at', 0)
        if not 0 <= age < 60 or cached.get('ids') != list(IDS):
            if 0 <= now-cached.get('failed_at', 0) < 60:
                raise NinjaError('Reference provider temporarily unavailable; retrying after cooldown.')
            try:
                payload = comparison.fetch_reference_batch(IDS)
            except NinjaError:
                seller.atomic_write(CACHE, {'failed_at':now})
                raise
            cached = {'fetched_at':now, 'ids':list(IDS), 'data':payload}
            seller.atomic_write(CACHE, json.loads(json.dumps(cached, default=str)))
        value = cached.get('data', {}).get(coin_id)
        if not isinstance(value, dict) or 'usd' not in value or 'last_updated_at' not in value:
            raise NinjaError('Reference asset is missing from the provider response.')
        return {coin_id:value}
