"""GOOGL.X market-price comparison, without trade execution."""

import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

from .monitor import observation
from .ninja import NinjaError, NoRedirect
from .strategy import amount

GOOGL_POOL = "8MFEMQNdgES25bfhNuo2xAmbES6kiPHhKD27cZwkT2dj"
GOOGL_MINT = "E3v5m81RLR3ZAjNuCeMjbniCmwBUd1j2iWsvtpXiBVe5"
USDC_MINT = "B69chRzqzDCmdB5WYB8NRu5Yv5ZA95ABiZcdzCgGm9Tq"
REFERENCE_URL = ("https://api.coingecko.com/api/v3/simple/price"
                 "?ids=alphabet-xstock&vs_currencies=usd&include_last_updated_at=true")


def fetch_reference(coin_id="alphabet-xstock") -> dict:
    return fetch_reference_batch((coin_id,))


def fetch_reference_batch(coin_ids) -> dict:
    for coin_id in coin_ids:
        if coin_id not in ("alphabet-xstock", "sp500-xstock", "spacex-xstocks", "tesla-xstock", 'meta-xstock', 'coinbase-xstock', 'palantir-xstock', 'amd-xstock', 'nvidia-xstock'):
            raise ValueError("Unsupported reference asset")
    url = REFERENCE_URL.replace("alphabet-xstock", ','.join(coin_ids))
    headers = {"Accept": "application/json", "User-Agent": "lp-profit-bot/0.1"}
    key = os.environ.get("COINGECKO_DEMO_API_KEY", "").strip()
    if key:
        if any(ord(char) < 33 or ord(char) > 126 for char in key):
            raise NinjaError("CoinGecko API key contains invalid characters.")
        headers["x-cg-demo-api-key"] = key
    try:
        with build_opener(NoRedirect()).open(Request(url, headers=headers), timeout=20) as response:
            payload = json.load(response, parse_float=Decimal)
        if not isinstance(payload, dict):
            raise ValueError("Expected object")
        return payload
    except HTTPError as exc:
        if exc.code == 429:
            raise NinjaError("CoinGecko rate limit reached; wait before restarting.") from None
        if exc.code in (401, 403):
            raise NinjaError("CoinGecko denied access; configure COINGECKO_DEMO_API_KEY if required.") from None
        raise NinjaError(f"CoinGecko returned HTTP {exc.code}.") from None
    except (URLError, OSError):
        raise NinjaError("Unable to reach CoinGecko within the request timeout.") from None
    except (ValueError, UnicodeError):
        raise NinjaError("CoinGecko returned invalid price data.") from None


def compare(pool_payload: dict, reference_payload: dict, max_age: int = 300, now=None) -> dict:
    now = now or datetime.now(timezone.utc)
    try:
        pool = pool_payload["pool"]
        if (pool["baseToken"]["address"] != GOOGL_MINT
                or pool["quoteToken"]["address"] != USDC_MINT):
            raise ValueError("Token mismatch")
        reference = reference_payload["alphabet-xstock"]
        reference_price = amount(reference["usd"], "reference price")
        if reference_price == 0:
            raise ValueError("Zero reference price")
    except (KeyError, TypeError, ValueError):
        raise NinjaError("Comparison rejected: wrong tokens or missing/invalid reference price.") from None
    result = observation(pool_payload, GOOGL_POOL, max_age, now)
    pool_price = Decimal(result["price_usd"])
    if pool_price == 0:
        raise NinjaError("Comparison rejected: pool price is zero.")
    reference_age = None
    reference_status = "UNKNOWN_FRESHNESS"
    try:
        timestamp = amount(reference["last_updated_at"], "reference timestamp")
        reference_age = float(Decimal(str(now.timestamp())) - timestamp)
        reference_status = ("FUTURE_TIMESTAMP" if reference_age < 0 else
                            "STALE" if reference_age > max_age else "FRESH")
    except (KeyError, TypeError, ValueError, OverflowError):
        pass
    fresh = result["data_status"] == "FRESH" and reference_status == "FRESH"
    gap = (pool_price / reference_price - 1) * 100 if fresh else None
    result.update({
        "reference_source": "CoinGecko alphabet-xstock",
        "reference_price_usd": str(reference_price),
        "reference_data_age_seconds": round(reference_age, 1) if reference_age is not None else None,
        "reference_data_status": reference_status,
        "max_age_seconds": max_age,
        "gap_percent": str(gap) if gap is not None else None,
        "comparison_status": ("DATA_NOT_FRESH" if not fresh else
                              "X1_PREMIUM" if gap > 0 else
                              "X1_DISCOUNT" if gap < 0 else "AT_REFERENCE"),
    })
    return result


def format_comparison(result: dict) -> str:
    gap = result["gap_percent"]
    gap_text = f'{Decimal(gap):+.2f}%' if gap is not None else "unavailable"
    def age_text(age):
        if age is None:
            return "age unknown"
        if age < 0:
            return f'{abs(age):.0f}s ahead'
        return f'{age:.0f}s old'

    return (f'{result["observed_at"]} | GOOGL.X ${Decimal(result["price_usd"]):.4f}'
            f' | reference ${Decimal(result["reference_price_usd"]):.4f}'
            f' | gap {gap_text} | {result["comparison_status"]}'
            f' | pool {result["data_status"]} ({age_text(result["data_age_seconds"])})'
            f', reference {result["reference_data_status"]} ({age_text(result["reference_data_age_seconds"])})'
            f' | freshness limit {result["max_age_seconds"]}s')
