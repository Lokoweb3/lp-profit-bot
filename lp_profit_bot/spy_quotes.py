"""Validated, read-only SPY.X/XNT pool quotes. Never signs or broadcasts."""
import hashlib
import struct
import time
from decimal import Decimal

from . import seller as s
from .spy_monitor import MINT, POOL

LEGACY_TOKEN = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"


def snapshot(mint=MINT, pool_address=POOL):
    first = s.accounts([pool_address, s.XNT_POOL])
    initial = [s.decode_pool(a) for a in first["value"]]
    addresses = [pool_address, s.XNT_POOL, s.CONFIG, *initial[0]["vaults"],
                 *initial[1]["vaults"], s.associated(mint), mint, s.WALLET]
    response = s.accounts(addresses, first["context"]["slot"])
    a = response["value"]
    pools = [s.decode_pool(a[0]), s.decode_pool(a[1])]
    for old, pool in zip(initial, pools):
        s.require(old["vaults"] == pool["vaults"], "Pool vaults changed while loading")
        s.require(pool["config"] == s.CONFIG, "Unexpected pool fee configuration")
    pool, valuation = pools
    for current, expected in ((pool, {mint: (s.TOKEN, 8), s.WXNT: (LEGACY_TOKEN, 9)}),
                              (valuation, {s.USDC_MINT: (s.TOKEN, 6), s.WXNT: (LEGACY_TOKEN, 9)})):
        s.require(set(current["mints"]) == set(expected), "Unexpected pool mints")
        for i, pool_mint in enumerate(current["mints"]):
            s.require((current["programs"][i], current["decimals"][i]) == expected[pool_mint],
                      "Unexpected token program or decimals")
    s.check_mint(a[8], 8)
    raw = s.raw_account(a[2], s.XDEX_PROGRAM)
    s.require(len(raw) == 236 and raw[:8] == hashlib.sha256(b"account:AmmConfig").digest()[:8],
              "Unsupported fee configuration")
    trade, protocol, fund = struct.unpack_from("<3Q", raw, 12)
    s.require(0 <= trade < 1_000_000 and protocol+fund <= 1_000_000, "Invalid fee rates")
    reserves = []
    for current, offset in ((pool, 3), (valuation, 5)):
        reserves.append([s.token_balance(a[offset+i], current["mints"][i], s.AUTHORITY,
                                         current["programs"][i])
                         - current["protocol_fees"][i] - current["fund_fees"][i] for i in range(2)])
    s.require(all(v > 0 for pair in reserves for v in pair), "Empty or invalid reserves")
    j = pool["mints"].index(mint)
    xj = valuation["mints"].index(s.WXNT)
    xnt_usd = Decimal(reserves[1][1-xj])/Decimal(reserves[1][xj])*1000
    s.require(0 < xnt_usd < 1000, "Invalid XNT valuation")
    s.require(a[9] and a[9]["owner"] == "11111111111111111111111111111111", "Invalid payer")
    return {"sell_mint": mint, "sell_pool": pool_address, "pool": pool, "input_index": j, "reserve_in": reserves[0][j],
            "reserve_out": reserves[0][1-j], "trade_fee": trade,
            "protocol_fee": protocol, "fund_fee": fund,
            "balance_in": s.token_balance(a[7], mint, s.WALLET),
            "native_balance": a[9]["lamports"], "xnt_usd": xnt_usd,
            "slot": response["context"]["slot"], "received": time.monotonic()}


def quote(snapshot, amount_raw):
    s.require(type(amount_raw) is int and 0 < amount_raw <= snapshot["balance_in"],
              "SPY.X amount exceeds available balance or is invalid")
    fee = (amount_raw*snapshot["trade_fee"] + 999_999)//1_000_000
    net = amount_raw-fee
    output = net*snapshot["reserve_out"]//(snapshot["reserve_in"]+net) if net > 0 else 0
    excluded = fee*snapshot["protocol_fee"]//1_000_000 + fee*snapshot["fund_fee"]//1_000_000
    end_usd = (Decimal(snapshot["reserve_out"]-output)
               / Decimal(snapshot["reserve_in"]+amount_raw-excluded)
               / 10 * snapshot["xnt_usd"])
    return {"amount_raw": amount_raw, "estimated_output_raw": output,
            "estimated_xnt": str(Decimal(output)/10**9),
            "estimated_usd": str(Decimal(output)/10**9*snapshot["xnt_usd"]),
            "ending_pool_price_usd": str(end_usd), "transaction_submitted": False}
