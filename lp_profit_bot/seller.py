"""Bounded GOOGL.X -> USDC.X seller. Default mode only simulates.

USDC.X is treated as $1 for the reference comparison. This is not a guarantee
of redemption value, original-cost profit, or future oracle correctness.
"""

import argparse
import base64
import fcntl
import hashlib
import json
import os
import stat
import struct
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING
from pathlib import Path

from solders.compute_budget import set_compute_unit_limit, set_compute_unit_price
from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.message import MessageV0, to_bytes_versioned
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.transaction import VersionedTransaction
from cryptography.hazmat.primitives import serialization

from .comparison import GOOGL_POOL, GOOGL_MINT, USDC_MINT, fetch_reference
from .ninja import NinjaError
from .transaction_audit import XDEX_PROGRAM, SWAP_BASE_INPUT
from .wallet import load_wallet, WalletError, public_bytes
from .transaction_audit import base58

ROOT = Path(__file__).resolve().parent.parent
def local_wallet_address():
    """Read the bot address locally; never publish a wallet address in source."""
    try:
        return base58(public_bytes(load_wallet()))
    except WalletError:
        configured = os.environ.get("X1_BOT_WALLET_ADDRESS")
        if not configured:
            raise
        try:
            return str(Pubkey.from_string(configured))
        except ValueError:
            raise WalletError("X1_BOT_WALLET_ADDRESS is invalid.") from None


WALLET = local_wallet_address()
TOKEN = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
ATA = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
CONFIG = "2eFPWosizV6nSAGeSvi5tRgXLoqhjnSesra23ALA248c"
XNT_POOL = "CAJeVEoSm1QQZccnCqYu9cnNF7TTD2fcUA3E5HQoxRvR"
WXNT = "So11111111111111111111111111111111111111112"
RPC_URL = "https://rpc.mainnet.x1.xyz"
STATE = ROOT / "state" / "seller-journal.json"
LEGACY_CAP_RAW = 7_000_000  # Validate journals written under the former lifetime cap.
CHUNK_RAW = 500_000  # At most 0.005 GOOGL.X per attempt.
COST_CEILING = 10_000_000  # Includes network fees and any output account rent: 0.01 XNT.


class SellerError(Exception):
    pass


def require(condition, message):
    if not condition:
        raise SellerError(message)


def rpc(method, params):
    request = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    try:
        if method == 'sendTransaction':
            from . import execution_barrier
            guard = execution_barrier.submission(None)
        else:
            guard = nullcontext()
        with guard:
            result = subprocess.run(["curl", "--fail", "--silent", "--show-error", "--max-time", "20",
                                     RPC_URL, "-H", "Content-Type: application/json", "--data-binary", "@-"],
                                    input=request, text=True, capture_output=True, timeout=25, check=True)
        payload = json.loads(result.stdout)
        require(isinstance(payload, dict) and "result" in payload and not payload.get("error"),
                f"RPC {method} rejected the request")
        return payload["result"]
    except (subprocess.SubprocessError, OSError, ValueError):
        raise SellerError(f"RPC {method} unavailable; no automatic resend") from None


def accounts(addresses, slot=0):
    return rpc("getMultipleAccounts", [addresses, {"encoding": "base64", "commitment": "confirmed",
                                                  "minContextSlot": slot}])


def raw_account(account, owner):
    require(account is not None and account["owner"] == owner and not account["executable"],
            "Unexpected on-chain account owner/type")
    return base64.b64decode(account["data"][0], validate=True)


def decode_pool(account):
    raw = raw_account(account, XDEX_PROGRAM)
    require(len(raw) == 637 and raw[:8] == hashlib.sha256(b"account:PoolState").digest()[:8],
            "Unsupported pool layout")
    keys = [str(Pubkey.from_bytes(raw[8 + i*32:40 + i*32])) for i in range(10)]
    require(not raw[329] & 4, "Pool swaps are paused")
    nums = struct.unpack_from("<7Q", raw, 333)
    require(nums[5] <= time.time(), "Pool is not open")
    return {"config": keys[0], "vaults": keys[2:4], "mints": keys[5:7],
            "programs": keys[7:9], "observation": keys[9], "decimals": list(raw[331:333]),
            "protocol_fees": [nums[1], nums[2]], "fund_fees": [nums[3], nums[4]]}


def token_balance(account, mint, owner, program=TOKEN):
    if account is None:
        return 0
    raw = raw_account(account, program)
    require(len(raw) >= 165 and str(Pubkey.from_bytes(raw[:32])) == mint
            and str(Pubkey.from_bytes(raw[32:64])) == owner and raw[108] == 1,
            "Token account mint, owner, or state mismatch")
    require(struct.unpack_from("<I", raw, 72)[0] == 0, "Delegated token account is not supported")
    return struct.unpack_from("<Q", raw, 64)[0]


def associated(mint):
    return str(Pubkey.find_program_address([bytes(Pubkey.from_string(WALLET)),
                bytes(Pubkey.from_string(TOKEN)), bytes(Pubkey.from_string(mint))], Pubkey.from_string(ATA))[0])


def check_mint(account, decimals):
    raw = raw_account(account, TOKEN)
    require(len(raw) >= 82 and raw[44] == decimals and raw[45] == 1, "Unexpected mint decimals/state")
    # Only metadata extensions are supported; reject transfer fees/hooks and other behavior changes.
    if len(raw) > 82:
        require(len(raw) >= 166 and raw[165] == 1, "Invalid Token-2022 mint")
        offset = 166
        while offset + 4 <= len(raw):
            kind, size = struct.unpack_from("<HH", raw, offset)
            if kind == 0:
                require(not any(raw[offset:]), "Invalid mint padding")
                break
            require(kind in (18, 19) and offset + 4 + size <= len(raw), "Unsupported mint extension")
            offset += 4 + size


AUTHORITY = str(Pubkey.find_program_address([b"vault_and_lp_mint_auth_seed"],
                                          Pubkey.from_string(XDEX_PROGRAM))[0])


def snapshot():
    first = accounts([GOOGL_POOL, XNT_POOL])
    pool, xp = [decode_pool(a) for a in first["value"]]
    addresses = [GOOGL_POOL, CONFIG, *pool["vaults"], associated(GOOGL_MINT), associated(USDC_MINT),
                 WALLET, GOOGL_MINT, USDC_MINT, XNT_POOL, *xp["vaults"]]
    response = accounts(addresses, first["context"]["slot"])
    a = response["value"]
    fresh_pool, fresh_xp = decode_pool(a[0]), decode_pool(a[9])
    require(pool["vaults"] == fresh_pool["vaults"] and xp["vaults"] == fresh_xp["vaults"],
            "Pool vaults changed while loading")
    pool, xp = fresh_pool, fresh_xp
    require(pool["config"] == CONFIG and set(pool["mints"]) == {GOOGL_MINT, USDC_MINT}
            and pool["programs"] == [TOKEN, TOKEN], "Unexpected selected pool configuration")
    require(set(xp["mints"]) == {WXNT, USDC_MINT}, "Unexpected XNT valuation pool")
    config = raw_account(a[1], XDEX_PROGRAM)
    require(len(config) == 236 and config[:8] == hashlib.sha256(b"account:AmmConfig").digest()[:8],
            "Unsupported fee configuration")
    trade, protocol, fund = struct.unpack_from("<3Q", config, 12)
    require(0 <= trade < 1_000_000 and 0 <= protocol + fund <= 1_000_000, "Invalid fee rates")
    check_mint(a[7], 8)
    check_mint(a[8], 6)
    reserves = [token_balance(a[2+i], pool["mints"][i], AUTHORITY) - pool["protocol_fees"][i]
                - pool["fund_fees"][i] for i in range(2)]
    xr = [token_balance(a[10+i], xp["mints"][i], AUTHORITY, xp["programs"][i])
          - xp["protocol_fees"][i] - xp["fund_fees"][i] for i in range(2)]
    require(all(r > 0 for r in reserves + xr), "Empty or invalid pool reserves")
    j = pool["mints"].index(GOOGL_MINT)
    xj = xp["mints"].index(WXNT)
    xnt_usd = Decimal(xr[1-xj]) / Decimal(xr[xj]) * 1000
    require(Decimal("0") < xnt_usd < Decimal("1000"), "Invalid XNT valuation")
    require(a[6] is not None and a[6]["owner"] == "11111111111111111111111111111111",
            "Wallet is not a system account")
    return {"pool": pool, "input_index": j, "reserve_in": reserves[j], "reserve_out": reserves[1-j],
            "trade_fee": trade, "protocol_fee": protocol, "fund_fee": fund,
            "balance_in": token_balance(a[4], GOOGL_MINT, WALLET),
            "balance_out": token_balance(a[5], USDC_MINT, WALLET),
            "native_balance": a[6]["lamports"], "output_exists": a[5] is not None,
            "slot": response["context"]["slot"], "xnt_usd": xnt_usd,
            "received": time.monotonic()}


def reference_price():
    value = fetch_reference()["alphabet-xstock"]
    price = Decimal(str(value["usd"]))
    updated = Decimal(str(value["last_updated_at"]))
    require(price.is_finite() and price > 0 and updated.is_finite(), "Invalid reference data")
    age = Decimal(str(time.time())) - updated
    require(0 <= age <= 300, "Reference price is stale or future-dated")
    return price, float(updated)


def output_for(s, qty):
    fee = (qty*s["trade_fee"] + 999_999)//1_000_000
    net = qty - fee
    if net <= 0:
        return 0, Decimal(0)
    output = net*s["reserve_out"]//(s["reserve_in"] + net)
    excluded = fee*s["protocol_fee"]//1_000_000 + fee*s["fund_fee"]//1_000_000
    end_price = Decimal(s["reserve_out"]-output)/Decimal(s["reserve_in"]+qty-excluded)*100
    return output, end_price


def minimum_output(qty, price, xnt_usd):
    # Charge the full 0.01 XNT ceiling, with 5% valuation headroom, even if actual fees are lower.
    cost = Decimal(COST_CEILING)/10**9 * xnt_usd * Decimal("1.05")
    value = (Decimal(qty)/10**8 * price + cost)*10**6
    return int(value.to_integral_value(rounding=ROUND_CEILING)) + 1


def plan(s, price):
    require(s["native_balance"] >= COST_CEILING + 1_000_000, "Insufficient XNT fee reserve")
    maximum = min(CHUNK_RAW, s["balance_in"])
    if maximum <= 0:
        return None
    # Find a batch that does not push the pool's marginal price below the reference.
    low, high = 0, maximum
    while low < high:
        middle = (low+high+1)//2
        _, end = output_for(s, middle)
        if end >= price:
            low = middle
        else:
            high = middle-1
    if low == 0:
        return None
    out, end = output_for(s, low)
    minimum = max(minimum_output(low, price, s["xnt_usd"]), out*995//1000)
    if out < minimum:
        return None
    return {"amount_raw": low, "estimated_output_raw": out, "minimum_output_raw": minimum,
            "reference_usd": str(price), "ending_pool_price_usd": str(end)}


def build_transaction(s, p, blockhash):
    pub = Pubkey.from_string
    input_ata, output_ata = associated(GOOGL_MINT), associated(USDC_MINT)
    instructions = [set_compute_unit_limit(200_000), set_compute_unit_price(10_000)]
    # Idempotent output account creation. Never transfer/close native funds or change authorities.
    instructions.append(Instruction(pub(ATA), b"\x01", [
        AccountMeta(pub(WALLET), True, True), AccountMeta(pub(output_ata), False, True),
        AccountMeta(pub(WALLET), False, False), AccountMeta(pub(USDC_MINT), False, False),
        AccountMeta(pub("11111111111111111111111111111111"), False, False),
        AccountMeta(pub(TOKEN), False, False)]))
    pool, j = s["pool"], s["input_index"]
    keys = [WALLET, AUTHORITY, CONFIG, GOOGL_POOL, input_ata, output_ata,
            pool["vaults"][j], pool["vaults"][1-j], TOKEN, TOKEN, GOOGL_MINT, USDC_MINT,
            pool["observation"]]
    require(0 < p["amount_raw"] <= CHUNK_RAW and p["minimum_output_raw"] > 0, "Invalid swap bounds")
    data = SWAP_BASE_INPUT + struct.pack("<QQ", p["amount_raw"], p["minimum_output_raw"])
    metas = [AccountMeta(pub(key), i == 0, i in (0, 3, 4, 5, 6, 7, 12)) for i, key in enumerate(keys)]
    instructions.append(Instruction(pub(XDEX_PROGRAM), data, metas))
    message = MessageV0.try_compile(pub(WALLET), instructions, [], Hash.from_string(blockhash))
    return VersionedTransaction.populate(message, [Signature.default()])


def encoded(tx):
    return base64.b64encode(bytes(tx)).decode()


def verify_simulation(s, p, value, fee):
    require(value.get("err") is None, f'Simulation rejected swap: {value.get("err")}')
    a = value.get("accounts")
    require(isinstance(a, list) and len(a) == 3, "Simulation did not return expected accounts")
    input_after = token_balance(a[0], GOOGL_MINT, WALLET)
    output_after = token_balance(a[1], USDC_MINT, WALLET)
    require(s["balance_in"] - input_after == p["amount_raw"], "Simulation input debit mismatch")
    require(output_after - s["balance_out"] >= p["minimum_output_raw"], "Simulation output below minimum")
    require(a[2] is not None, "Simulation omitted payer")
    native_debit = s["native_balance"] - a[2]["lamports"]
    require(0 <= native_debit <= COST_CEILING and 0 <= fee <= COST_CEILING,
            "Simulation fees/rent exceed cost ceiling")
    # Some RPC versions omit fee deduction in simulated accounts; charge it conservatively again.
    require(native_debit + fee <= COST_CEILING, "Combined simulated rent/fee exceeds ceiling")
    return {"output_raw": output_after-s["balance_out"], "native_debit_lamports": native_debit,
            "message_fee_lamports": fee, "units": value.get("unitsConsumed")}


def atomic_write(path, data):
    ensure_private_state_dir(path.parent)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
            name = stream.name
            os.fchmod(stream.fileno(), 0o600)
            json.dump(data, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def ensure_private_state_dir(path=ROOT / "state"):
    path = Path(path)
    if not path.exists() and not path.is_symlink():
        path.mkdir(mode=0o700)
    info = path.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid(), "Unsafe state directory")
    if stat.S_IMODE(info.st_mode) != 0o700:
        path.chmod(0o700)


def read_state_json(path):
    path = Path(path)
    ensure_private_state_dir(path.parent)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid(), "Unsafe state file")
        with os.fdopen(fd, "r") as stream:
            fd = -1
            return json.load(stream)
    finally:
        if fd >= 0:
            os.close(fd)


def open_state_lock(path):
    path = Path(path)
    ensure_private_state_dir(path.parent)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid(), "Unsafe state lock")
        if stat.S_IMODE(info.st_mode) != 0o600:
            os.fchmod(fd, 0o600)
        stream = os.fdopen(fd, "w")
        fd = -1
        return stream
    finally:
        if fd >= 0:
            os.close(fd)


def read_journal(path=STATE):
    if not path.exists() and not path.is_symlink():
        return {"wallet": WALLET, "cap_raw": None, "entries": [], "halted": False}
    journal = read_state_json(path)
    require(journal["wallet"] == WALLET and journal.get("cap_raw") in (None, LEGACY_CAP_RAW),
            "Journal belongs to another wallet or has an unsupported policy")
    require(isinstance(journal["entries"], list) and type(journal["halted"]) is bool, "Invalid journal")
    for entry in journal["entries"]:
        require(type(entry["amount_raw"]) is int and 0 < entry["amount_raw"] <= CHUNK_RAW,
                "Invalid journal amount")
        require(entry["status"] in ("pending", "finalized", "failed"), "Unknown journal state")
        Signature.from_string(entry["signature"])
    if journal.get("cap_raw") is not None:
        require(sum(e["amount_raw"] for e in journal["entries"]) <= LEGACY_CAP_RAW,
                "Legacy journal exceeds its original cap")
    require(len({e["signature"] for e in journal["entries"]}) == len(journal["entries"]), "Duplicate journal signature")
    journal["cap_raw"] = None
    return journal


def reconcile(journal):
    for entry in journal["entries"]:
        if entry["status"] != "pending":
            continue
        result = rpc("getSignatureStatuses", [[entry["signature"]], {"searchTransactionHistory": True}])["value"][0]
        if result is None or result.get("confirmationStatus") != "finalized":
            return False
        if result["err"] is not None:
            entry["status"] = "failed"
            journal["halted"] = True
        else:
            entry["status"] = "finalized"
        atomic_write(STATE, journal)
    return True


def cycle(live=False):
    journal = read_journal()
    require(not journal["halted"], "Seller halted after an on-chain failure; review the journal")
    if not reconcile(journal):
        return {"status": "WAITING_FOR_FINALITY", "detail": "No replacement or duplicate sale will be sent"}
    require(not journal["halted"], "Seller halted after an on-chain failure")
    price, updated = reference_price()
    s = snapshot()
    p = plan(s, price)
    if not p:
        return {"status": "HOLD", "reason": "No premium after costs, or no available GOOGL.X",
                "reference_usd": str(price), "wallet_googl": str(Decimal(s["balance_in"])/10**8)}
    block = rpc("getLatestBlockhash", [{"commitment": "confirmed", "minContextSlot": s["slot"]}])["value"]
    unsigned = build_transaction(s, p, block["blockhash"])
    fee = rpc("getFeeForMessage", [base64.b64encode(to_bytes_versioned(unsigned.message)).decode(),
                                  {"commitment": "confirmed"}])["value"]
    require(type(fee) is int and 0 <= fee <= COST_CEILING, "Invalid/excessive message fee")
    sim = rpc("simulateTransaction", [encoded(unsigned), {"encoding": "base64", "sigVerify": False,
              "commitment": "confirmed", "minContextSlot": s["slot"],
              "accounts": {"encoding": "base64", "addresses": [associated(GOOGL_MINT), associated(USDC_MINT), WALLET]}}])
    checked = verify_simulation(s, p, sim["value"], fee)
    require(time.monotonic()-s["received"] <= 30 and 0 <= time.time()-updated <= 300,
            "Simulation/reference became stale; retry next cycle")
    report = {"status": "SIMULATION_PASSED", "amount_googl": str(Decimal(p["amount_raw"])/10**8),
              "minimum_usdc": str(Decimal(p["minimum_output_raw"])/10**6),
              "simulated_usdc": str(Decimal(checked["output_raw"])/10**6),
              "reference_usd": str(price), "simulation": checked, "transaction_submitted": False}
    if not live:
        atomic_write(ROOT/"state"/"seller-last-simulation.json", report)
        return report
    # Revalidate the reference after simulation, then sign only locally generated instructions.
    current_price, current_updated = reference_price()
    current = snapshot()
    from .sale_checks import pre_sign_delta
    delta = pre_sign_delta(current,p,current_price,current_updated,native=False)
    if not delta['qualifies']:
        return {'status':'HOLD','reason':'Pool/reference delta no longer meets costs.',
                'delta_check':delta,'transaction_submitted':False}
    report['delta_check'] = delta
    require(p["minimum_output_raw"] >= minimum_output(p["amount_raw"], current_price, current["xnt_usd"]),
            "Reference increased beyond protected proceeds; retry")
    require(time.monotonic()-s["received"] <= 30, "Pre-sign snapshot expired")
    local = load_wallet()
    seed = local.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    signer = Keypair.from_seed(seed)
    require(str(signer.pubkey()) == WALLET, "Signing wallet does not match fixed bot wallet")
    signed = VersionedTransaction(unsigned.message, [signer])
    signature = str(signed.signatures[0])
    # Reserve the full quantity durably BEFORE any broadcast. Failed/unknown transactions never release it automatically.
    journal["entries"].append({"signature": signature, "amount_raw": p["amount_raw"],
                               "minimum_output_raw": p["minimum_output_raw"], "status": "pending",
                               "last_valid_block_height": block["lastValidBlockHeight"],
                               "created_at": datetime.now(timezone.utc).isoformat(), "delta_check": delta})
    atomic_write(STATE, journal)
    returned = rpc("sendTransaction", [encoded(signed), {"encoding": "base64", "skipPreflight": False,
                   "preflightCommitment": "confirmed", "minContextSlot": sim["context"]["slot"], "maxRetries": 0}])
    require(returned == signature, "RPC signature mismatch; journal remains pending")
    report.update(status="SUBMITTED_PENDING_FINALITY", transaction_submitted=True, signature=signature)
    return report


@contextmanager
def process_lock():
    path = ROOT/"state"/"seller.lock"
    ensure_private_state_dir(path.parent)
    with open_state_lock(path) as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SellerError("Another seller process is already running") from None
        yield


def main():
    parser = argparse.ArgumentParser(description="GOOGL.X premium seller; simulates unless --live is supplied")
    parser.add_argument("--live", action="store_true", help="Sign and submit protected sales without per-trade prompts")
    parser.add_argument("--watch", action="store_true", help="Repeat until stopped or halted")
    parser.add_argument("--interval", type=int, default=60)
    args = parser.parse_args()
    from . import execution_barrier
    execution_barrier.arm()
    if args.interval < 60:
        parser.error("--interval must be at least 60 seconds")
    print("LIVE seller enabled" if args.live else "SIMULATION ONLY: no signatures or broadcasts", flush=True)
    print("No lifetime sale cap; batches up to 0.005 GOOGL.X; receive USDC.X; USDC.X valued at $1.", flush=True)
    try:
        with process_lock():
            while True:
                runtime_status(args.live, "CHECKING")
                report = cycle(args.live)
                runtime_status(args.live, report["status"])
                print(json.dumps(report), flush=True)
                if not args.watch:
                    return 0
                time.sleep(args.interval)
    except KeyboardInterrupt:
        return 0
    except (SellerError, NinjaError, WalletError, OSError, ValueError, KeyError, TypeError, struct.error):
        # Do not leak RPC bodies, keys, or signed transaction data on malformed responses.
        error = sys.exc_info()[1]
        message = str(error) if isinstance(error, (SellerError, NinjaError, WalletError)) else "Invalid data or local I/O failure"
        print(f"Seller stopped: {message}. No automatic resend; pending entries remain reserved.", file=sys.stderr)
        return 1


def runtime_status(live, status):
    """Best-effort dashboard telemetry; cannot interrupt or authorize a sale."""
    try:
        atomic_write(ROOT/"state"/"seller-runtime.json", {
            "pid": os.getpid(), "mode": "live" if live else "simulation",
            "status": status, "updated_at": time.time()})
    except OSError:
        pass


if __name__ == "__main__":
    raise SystemExit(main())
