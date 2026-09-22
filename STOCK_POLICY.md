# Stock selling policy

Approved for the locally configured bot wallet. The public address is derived
from the keypair in `.secrets/bot-wallet.json` and is not stored in this policy.

| Token | Approved mint |
|---|---|
| SPY.X | `5Z7K1BaM36ubfNHkXbiDm5GW3KGzVSt3DFxD2b7p4VtJ` |
| SPCX.X | `CCqoyVud4QNCccV9EJtWEFPaC6jBaGJsaFTnyD8Ss47m` |
| TSLA.X | `47wNUaHJyuiknQswU5qsfYKjaZ9ijueRB63ZrsxuRb4F` |
| META.X | `36fxZScbKNXxAfJoiqk76egFGm5b7wWFutjJfXTU5nhT` |
| COIN.X | `44QsUuVsKVGk5A1X5Vx7MnevsNe7UTVnijfkbSi3rtpY` |
| PLTR.X | `2EPkJGy9C4CwdXFc7zpa4VxeansMRcRVdPnR52nBVZbW` |
| AMD.X | `7Y5bai9oWEjZMYMkHxVBUzpUXJqAcwaHi8MptdcDhKk2` |
| NVDA.X | `4JfDXUw8N7b1VJ1og1K3Nc4Z6nwtWxWJUSQKYBcdsiJz` |

- Sell current and future deposited inventory. No lifetime or per-trade quantity cap.
- Sell only when the reference value is exceeded after the transaction cost allowance and a 5% conservative XNT valuation buffer. Size the trade so the ending marginal price also meets that buffered reference.
- Protect at least 99.5% of estimated output (0.5% slippage); use the higher of that amount and the reference-based minimum. Retain the 0.01 XNT transaction cost allowance and a native fee/rent reserve.
- Immediately before signing, reload the on-chain pool and recheck the reference timestamp. Require a positive pool/reference delta, the 5% buffer, sufficient proceeds after costs, and a qualifying ending pool price for the planned quantity. If the delta disappears, hold without signing. Record the successful delta check with the sale.
- Reject stale or invalid reference data. Validate on-chain mints, pool accounts, token programs, balances, fees, and transaction simulation before signing.
- Receive native XNT. Automatically convert only finalized, verified proceeds from the approved assets into USDC.X. Include completed sales, deduct prior conversions and costs, and preserve the XNT balance preceding the earliest included stock sale. Previously converted proceeds cannot be reused.
- Automatic conversions use at most 25 XNT per batch, a 0.5% slippage bound, and retain the 0.01 XNT cost allowance. Small remainders accumulate.
- Keep separate journals and worker locks per seller. Reserve transactions durably before broadcast. Wait for unresolved transactions; stop after a failed sale rather than resubmitting it.
- Start/Stop controls and the terminal show each script separately. Stop cannot undo a transaction already sent to the chain.

GOOGL.X retains its separate 0.005 batch limit. Its former 0.07 lifetime cap has been removed; it may sell current or future deposits while live watch mode runs and all price and cost checks pass. This policy does not authorize additional mints or converting unrelated XNT.

The approved asset registry and shared pricing factors are in `lp_profit_bot/stock_policy.py`. Price protections do not guarantee profit relative to purchase cost.
