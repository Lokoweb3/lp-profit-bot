"""Read-only SPCX.X market and wallet observation. No transaction construction."""
from datetime import datetime
from decimal import Decimal
import time

from . import seller
from .stock_references import fetch_reference
from .credentials import load_key
from .monitor import observation
from .ninja import NinjaClient

MINT = "CCqoyVud4QNCccV9EJtWEFPaC6jBaGJsaFTnyD8Ss47m"
POOL = "7jDUExC8K6WLr2kk8mw7vZN6JwZFCHmcr7qtzFRJ25LX"


def snapshot():
    payload = NinjaClient(load_key()).pool(POOL)
    pool = payload["pool"]
    seller.require(pool["baseToken"]["address"] == MINT
                   and pool["quoteToken"]["address"] == seller.WXNT
                   and pool["baseToken"]["decimals"] == 8, "Unexpected SPCX.X market")
    market = observation(payload, POOL, 300)
    from .stock_market import fresh_pool_market
    market = fresh_pool_market(market, MINT, POOL)
    price = Decimal(market["price_usd"])
    ref = fetch_reference("spacex-xstocks")["spacex-xstocks"]
    reference = Decimal(str(ref["usd"]))
    updated = float(ref["last_updated_at"])
    seller.require(price.is_finite() and price > 0 and reference.is_finite() and reference > 0,
                   "Invalid SPCX.X price")
    accounts = seller.rpc("getTokenAccountsByOwner", [seller.WALLET, {"mint": MINT},
                          {"encoding": "base64", "commitment": "confirmed"}])
    balance = sum(seller.token_balance(row["account"], MINT, seller.WALLET)
                  for row in accounts["value"])
    now = time.time()
    synced = datetime.fromisoformat(market["last_synced_at"].replace("Z", "+00:00"))
    seller.require(synced.tzinfo is not None, "SPCX.X timestamp lacks timezone")
    fresh = market["data_status"] == "FRESH" and 0 <= now-updated <= 300
    return {"mint": MINT, "pool": POOL, "balance": str(Decimal(balance)/10**8),
            "price_usd": str(price), "reference_price": str(reference),
            "liquidity_usd": market["liquidity_usd"], "fetched_at": now,
            "pool_updated_at": synced.timestamp(), "reference_updated_at": updated,
            "fresh": fresh, "gap_percent": str((price/reference-1)*100) if fresh else None}
