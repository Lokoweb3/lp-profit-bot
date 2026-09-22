"""Use validated on-chain reserves when the indexed stock pool is stale."""
from datetime import datetime, timezone
from decimal import Decimal


def fresh_pool_market(market, mint, pool):
    if market['data_status']=='FRESH':
        return market
    from .spy_quotes import snapshot
    current=snapshot(mint,pool)
    price=Decimal(current['reserve_out'])/Decimal(current['reserve_in'])/10*current['xnt_usd']
    liquidity=Decimal(current['reserve_out'])*2/10**9*current['xnt_usd']
    return {**market,'price_usd':str(price),'liquidity_usd':str(liquidity),
            'last_synced_at':datetime.now(timezone.utc).isoformat(),
            'data_status':'FRESH','source':'X1 on-chain reserves'}
