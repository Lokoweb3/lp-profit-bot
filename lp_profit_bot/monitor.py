"""Read-only pool observations; these are not personal profit estimates."""

from datetime import datetime, timezone

from .ninja import NinjaError
from .strategy import amount


def observation(payload: dict, address: str, max_age: int, now=None) -> dict:
    now = now or datetime.now(timezone.utc)
    try:
        pool = payload["pool"]
        if pool["address"] != address:
            raise ValueError("Pool address mismatch")
        price = amount(pool["priceUsd"], "priceUsd")
        liquidity = amount(pool["liquidity"], "liquidity")
        pair = f'{pool["baseToken"]["symbol"]}/{pool["quoteToken"]["symbol"]}'
    except (KeyError, TypeError, ValueError):
        raise NinjaError("Pool response has missing or invalid market data.") from None

    synced_at = pool.get("lastSyncedAt")
    age = None
    status = "UNKNOWN_FRESHNESS"
    try:
        synced = datetime.fromisoformat(synced_at.replace("Z", "+00:00"))
        if synced.tzinfo is None:
            raise ValueError("Timestamp must include timezone")
        age = (now - synced).total_seconds()
        status = "FUTURE_TIMESTAMP" if age < 0 else "STALE" if age > max_age else "FRESH"
    except (AttributeError, TypeError, ValueError):
        pass
    return {
        "observed_at": now.isoformat(),
        "pool_address": address,
        "pair": pair,
        "price_usd": str(price),
        "liquidity_usd": str(liquidity),
        "last_synced_at": synced_at,
        "data_age_seconds": round(age, 1) if age is not None else None,
        "data_status": status,
        "mode": "read_only",
        "transaction_submitted": False,
    }
