"""Read-only XDEX token-route quotes. Never prepares or submits transactions."""

import json
import subprocess
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from urllib.parse import urlencode

from .strategy import amount

TOKENS = {
    "XNT": ("So11111111111111111111111111111111111111112", 9),
    "GOOGL.X": ("E3v5m81RLR3ZAjNuCeMjbniCmwBUd1j2iWsvtpXiBVe5", 8),
    "USDC.X": ("B69chRzqzDCmdB5WYB8NRu5Yv5ZA95ABiZcdzCgGm9Tq", 6),
    "JACK": ("54uAdhRHZmbGnD1tATH7F7Qp5us7xsXJQTf6MpMEdFbg", 9),
    "SPCX.X": ("CCqoyVud4QNCccV9EJtWEFPaC6jBaGJsaFTnyD8Ss47m", 8),
}
ROUTES = [
    ("XNT", "GOOGL.X", "USDC.X", "XNT"),
    ("XNT", "GOOGL.X", "JACK", "XNT"),
    ("XNT", "GOOGL.X", "SPCX.X", "XNT"),
]


class QuoteError(Exception):
    pass


def validate_quote(data: dict, token_in: str, token_out: str, input_amount: Decimal) -> dict:
    try:
        if data["inputMint"] != TOKENS[token_in][0] or data["outputMint"] != TOKENS[token_out][0]:
            raise ValueError("Mismatched token mints")
        actual_input = amount(data["inputAmount"], "inputAmount")
        if actual_input != input_amount:
            raise ValueError("Mismatched input amount")
        output = amount(data["outputAmount"], "outputAmount").quantize(
            Decimal(1).scaleb(-TOKENS[token_out][1]), rounding=ROUND_DOWN)
        if output <= 0:
            raise ValueError("Non-positive output")
        impact = amount(data["priceImpactPct"], "priceImpactPct")
        return {"token_in": token_in, "token_out": token_out,
                "input_amount": str(actual_input), "output_amount": str(output),
                "price_impact_percent": str(impact),
                "amm_config_address": data.get("amm_config_address"),
                "received_at": datetime.now(timezone.utc).isoformat()}
    except (KeyError, TypeError, ValueError):
        raise QuoteError("XDEX quote failed token, amount, or price-impact validation.") from None


def fetch_quote(token_in: str, token_out: str, input_amount: Decimal) -> dict:
    params = {"network": "X1 Mainnet", "token_in": TOKENS[token_in][0],
              "token_out": TOKENS[token_out][0], "token_in_amount": str(input_amount),
              "is_exact_amount_in": "true", "slippage": "0.5"}
    url = "https://api.xdex.xyz/api/xdex/swap/quote?" + urlencode(params)
    # XDEX rejected Python urllib during discovery; curl successfully reaches its public API.
    try:
        response = subprocess.run(["curl", "--fail", "--silent", "--show-error",
                                   "--max-time", "25", url],
                                  capture_output=True, text=True, timeout=30, check=True)
        payload = json.loads(response.stdout, parse_float=Decimal)
        if not isinstance(payload, dict) or payload.get("success") is not True:
            raise QuoteError("XDEX could not quote this token pair.")
        return validate_quote(payload.get("data"), token_in, token_out, input_amount)
    except (OSError, subprocess.SubprocessError):
        raise QuoteError("XDEX quote request failed; curl and network access are required.") from None
    except (ValueError, TypeError):
        raise QuoteError("XDEX returned malformed quote data.") from None


def quote_route(route, fetch=fetch_quote) -> dict:
    started = datetime.now(timezone.utc)
    current = Decimal("1")
    legs = []
    for source, destination in zip(route, route[1:]):
        leg = fetch(source, destination, current)
        legs.append(leg)
        current = Decimal(leg["output_amount"])
    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    return {"route": list(route), "input_xnt": "1", "quoted_output_xnt": str(current),
            "quoted_difference_xnt": str(current - 1), "elapsed_seconds": elapsed,
            "status": "QUOTES_TOO_FAR_APART" if elapsed > 30 else "INDICATIVE_ONLY",
            "legs": legs, "transaction_submitted": False,
            "network_costs_included": False, "pool_addresses_verified": False,
            "fee_breakdown_verified": False}


def main() -> int:
    print("Read-only 1 XNT route check. Quotes are sequential, not a transaction simulation.", flush=True)
    results = []
    for forward in ROUTES:
        for route in (forward, tuple(reversed(forward))):
            label = " -> ".join(route)
            print(f"Checking {label} ...", flush=True)
            try:
                result = quote_route(route)
                print(f'  1 XNT -> {result["quoted_output_xnt"]} XNT; '
                      f'difference {Decimal(result["quoted_difference_xnt"]):+.9f} XNT '
                      f'before network costs [{result["status"]}]', flush=True)
            except QuoteError as exc:
                result = {"route": list(route), "status": "QUOTE_FAILED", "error": str(exc)}
                print(f"  {exc}", flush=True)
            results.append(result)
    output = Path(__file__).resolve().parent.parent / "state" / "latest-route-quotes.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps({"checked_at": datetime.now(timezone.utc).isoformat(),
                                 "results": results}, indent=2) + "\n")
    print(f"Details saved to {output}")
    return 1 if any(row["status"] == "QUOTE_FAILED" for row in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
