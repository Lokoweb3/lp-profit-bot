import argparse
import getpass
import json
import sys
import time
from decimal import Decimal
from pathlib import Path

from .strategy import Position, amount, evaluate
from .ninja import NinjaClient, NinjaError
from .monitor import observation
from .credentials import load_key, save_key
from .comparison import GOOGL_POOL, compare, fetch_reference, format_comparison


def read_decisions(path: Path) -> list[dict]:
    data = json.loads(path.read_text(), parse_float=Decimal)
    target = amount(data["target_percent"], "target_percent")
    rows = data["positions"]
    if not isinstance(rows, list):
        raise ValueError("positions must be a list")
    positions = [Position.from_dict(row) for row in rows]
    if len({p.position_id for p in positions}) != len(positions):
        raise ValueError("position_id values must be unique")
    return [evaluate(position, target) for position in positions]


def main() -> int:
    parser = argparse.ArgumentParser(description="Monitor X1 pool data or simulate LP profit targets.")
    parser.add_argument("--snapshot", type=Path, default=Path("examples/positions.json"))
    parser.add_argument("--watch", action="store_true", help="Monitor one live pool or reload local snapshots")
    parser.add_argument("--interval", type=int, help="Seconds between checks (comparison: 60; other modes: 30)")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--pools", action="store_true", help="Fetch one page of live X1.Ninja pools")
    source.add_argument("--pool", help="Fetch live X1.Ninja data for one pool address")
    source.add_argument("--setup-key", action="store_true", help="Save or replace your API key locally")
    source.add_argument("--compare-googl", action="store_true", help="Compare GOOGL.X with the Alphabet xStock reference price")
    parser.add_argument("--limit", type=int, default=10, help="Pool list page size (1–100)")
    parser.add_argument("--max-age", type=int, default=300, help="Flag pool data older than this many seconds")
    args = parser.parse_args()
    if args.interval is None:
        args.interval = 60 if args.compare_googl else 30
    if args.setup_key:
        if args.watch:
            parser.error("--setup-key cannot be combined with --watch")
        try:
            save_key(getpass.getpass("Paste your X1.Ninja API key to save (hidden): "))
            print("API key saved locally. Future runs will load it automatically.")
            return 0
        except NinjaError as exc:
            print(f"X1.Ninja: {exc}", file=sys.stderr)
            return 1
        except (EOFError, KeyboardInterrupt):
            print("\nAPI key setup cancelled.", file=sys.stderr)
            return 1
    if args.interval < 1:
        parser.error("--interval must be at least 1")
    if args.max_age < 1:
        parser.error("--max-age must be at least 1")
    if args.watch and args.pools:
        parser.error("Use --pool ADDRESS to watch a single pool")
    if args.watch and args.pool and args.interval < 5:
        parser.error("Live pool polling requires --interval of at least 5 seconds")
    if args.compare_googl and args.watch and args.interval < 60:
        parser.error("Comparison polling requires --interval of at least 60 seconds")
    if args.pools or args.pool or args.compare_googl:
        try:
            api_key = load_key()
            if not api_key and sys.stdin.isatty():
                api_key = getpass.getpass("Paste your X1.Ninja API key and press Enter (hidden): ")
            client = NinjaClient(api_key)
            if args.compare_googl:
                print("Read-only price comparison. Gaps exclude costs and are not executable profit.", flush=True)
                try:
                    while True:
                        pool = client.pool(GOOGL_POOL)
                        reference = fetch_reference()
                        result = compare(pool, reference, args.max_age)
                        print(format_comparison(result), flush=True)
                        if not args.watch:
                            return 0
                        time.sleep(args.interval)
                except KeyboardInterrupt:
                    return 0
            if args.watch:
                try:
                    while True:
                        result = observation(client.pool(args.pool), args.pool, args.max_age)
                        print(json.dumps(result), flush=True)
                        time.sleep(args.interval)
                except KeyboardInterrupt:
                    return 0
            result = client.pool(args.pool) if args.pool else client.pools(args.limit)
            print(json.dumps(result, indent=2))
            return 0
        except NinjaError as exc:
            print(f"Monitor: {exc}", file=sys.stderr)
            return 1
        except (EOFError, KeyboardInterrupt):
            print("\nAPI key entry cancelled.", file=sys.stderr)
            return 1
    previous = {}
    try:
        while True:
            decisions = read_decisions(args.snapshot)
            current = {}
            for decision in decisions:
                key = decision["position_id"]
                current[key] = decision["decision"]
                if not args.watch or previous.get(key) != decision["decision"]:
                    print(json.dumps(decision), flush=True)
            previous = current
            if not args.watch:
                return 0
            time.sleep(args.interval)
    except KeyboardInterrupt:
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Snapshot rejected: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
