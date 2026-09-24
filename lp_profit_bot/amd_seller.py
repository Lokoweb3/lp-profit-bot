"""AMD.X premium seller: available inventory, native XNT proceeds; no sale amount caps."""
import argparse
import fcntl
import json
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING
from solders.keypair import Keypair
from solders.signature import Signature
from solders.transaction import VersionedTransaction
from cryptography.hazmat.primitives import serialization
from . import seller as base
from .seller import (ROOT, WALLET, COST_CEILING, SellerError, require, rpc, atomic_write,
                     load_wallet, WalletError, encoded)
from .ninja import NinjaError
from .stock_references import fetch_reference
from .spy_quotes import snapshot as stock_snapshot, quote
from .stock_policy import STOCKS
ASSET = STOCKS['amd']
def snapshot():
    return stock_snapshot(ASSET.mint, ASSET.pool)
from .stock_policy import VALUATION_FACTOR, MINIMUM_QUOTE_FACTOR
from .native_swaps import prepare, simulate

LEGACY_CAP_RAW = 5_000_000
LEGACY_CHUNK_RAW = 500_000
STATE = ROOT / 'state' / 'amd-seller-journal.json'


from .spy_seller import native_lock, NativeSwapBusy


def reference_price():
    value = fetch_reference('amd-xstock')['amd-xstock']
    price = Decimal(str(value['usd']))
    updated = Decimal(str(value['last_updated_at']))
    require(price.is_finite() and price>0 and updated.is_finite(), 'Invalid AMD.X reference')
    require(0 <= Decimal(str(time.time()))-updated <= 300, 'AMD.X reference stale or future-dated')
    return price, float(updated)


def minimum_output(qty, price, xnt_usd):
    # 5% valuation headroom on the XNT price, plus the full network cost allowance.
    value = Decimal(qty)/10**8*price/(xnt_usd*VALUATION_FACTOR)*10**9 + COST_CEILING
    return int(value.to_integral_value(rounding=ROUND_CEILING))+1


def plan(s, price):
    require(s['native_balance'] >= COST_CEILING+s['rent']+1_000_000, 'Insufficient XNT fee reserve')
    maximum = s['balance_in']
    low, high = 0, maximum
    while low < high:
        middle = (low+high+1)//2
        if Decimal(quote(s,middle)['ending_pool_price_usd'])*VALUATION_FACTOR >= price:
            low=middle
        else:
            high=middle-1
    if low<=0:
        return None
    p=quote(s,low)
    p['minimum_output_raw']=max(minimum_output(low,price,s['xnt_usd']),int(Decimal(p['estimated_output_raw'])*MINIMUM_QUOTE_FACTOR))
    return p if p['estimated_output_raw']>=p['minimum_output_raw'] else None


def read_journal(path=None):
    path = STATE if path is None else path
    if not path.exists() and not path.is_symlink():
        return {"wallet": WALLET, "mint": ASSET.mint, "cap_raw": None, "entries": [], "halted": False}
    journal = base.read_state_json(path)
    require(journal["wallet"] == WALLET and journal.get("mint") == ASSET.mint and journal["cap_raw"] is None,
            "Journal belongs to another wallet or has an unsupported policy")
    require(isinstance(journal["entries"], list) and type(journal["halted"]) is bool, "Invalid journal")
    for entry in journal["entries"]:
        require(type(entry["amount_raw"]) is int and 0 < entry["amount_raw"] <= 2**64-1,
                "Invalid journal amount")
        require(entry["status"] in ("pending", "finalized", "failed"), "Unknown journal state")
        Signature.from_string(entry["signature"])
    if journal['cap_raw'] is not None:
        require(all(e['amount_raw'] <= LEGACY_CHUNK_RAW for e in journal['entries'])
                and sum(e['amount_raw'] for e in journal['entries']) <= LEGACY_CAP_RAW,
                'Legacy journal exceeds its original limits')
    journal['cap_raw'] = None
    journal['amount_policy'] = 'available_inventory'

    require(len({e["signature"] for e in journal["entries"]}) == len(journal["entries"]), "Duplicate journal signature")
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
    try:
        with native_lock():
            return locked_cycle(live)
    except NativeSwapBusy:
        return {'status':'WAITING_FOR_NATIVE_SWAP'}


def locked_cycle(live=False):
    from .xnt_conversion import ready, stock_sales_ready
    if not ready():
        return {'status':'WAITING_FOR_XNT_CONVERSION'}
    if not stock_sales_ready():
        return {'status':'WAITING_FOR_FINALITY'}
    journal=read_journal()
    require(not journal['halted'], 'AMD.X seller halted; review journal')
    if not reconcile(journal):
        return {'status':'WAITING_FOR_FINALITY'}
    require(not journal['halted'], 'AMD.X seller halted after failed transaction')
    price, updated=reference_price()
    snap=prepare(snapshot())
    p=plan(snap,price)
    if not p:
        return {'status':'HOLD','reason':'No premium after costs, or no available AMD.X',
                'wallet_amd':str(Decimal(snap['balance_in'])/10**8),'reference_usd':str(price)}
    unsigned, block, slot, received=simulate(snap,p['amount_raw'],p['minimum_output_raw'],sell_spy=True)
    require(0<=time.time()-updated<=300,'Reference expired during simulation')
    report={'status':'SIMULATION_PASSED','amount_amd':str(Decimal(p['amount_raw'])/10**8),
            'minimum_xnt':str(Decimal(p['minimum_output_raw'])/10**9),
            'simulated_net_xnt':str(Decimal(received)/10**9),
            'reference_usd':str(price),'transaction_submitted':False}
    if not live:
        atomic_write(ROOT/'state'/'amd-seller-last-simulation.json',report)
        return report
    current_price,current_updated=reference_price()
    current= snapshot()
    from .sale_checks import pre_sign_delta
    delta=pre_sign_delta(current,p,current_price,current_updated)
    if not delta['qualifies']:
        return {'status':'HOLD','reason':'Pool/reference delta no longer meets buffer and costs.',
                'delta_check':delta,'transaction_submitted':False}
    report['delta_check']=delta
    require(p['minimum_output_raw']>=minimum_output(p['amount_raw'],current_price,current['xnt_usd']),
            'Reference or XNT valuation changed beyond protected proceeds')
    require(time.monotonic()-snap['received']<=30,'Pre-sign snapshot expired')
    local=load_wallet()
    seed=local.private_bytes(serialization.Encoding.Raw,serialization.PrivateFormat.Raw,serialization.NoEncryption())
    signer=Keypair.from_seed(seed)
    require(str(signer.pubkey())==WALLET,'Signing wallet mismatch')
    signed=VersionedTransaction(unsigned.message,[signer])
    signature=str(signed.signatures[0])
    journal['entries'].append({'signature':signature,'amount_raw':p['amount_raw'],
        'minimum_output_raw':p['minimum_output_raw'],'status':'pending',
        'last_valid_block_height':block['lastValidBlockHeight'],
        'created_at':datetime.now(timezone.utc).isoformat(),'delta_check':delta})
    atomic_write(STATE,journal)
    returned=rpc('sendTransaction',[encoded(signed),{'encoding':'base64','skipPreflight':False,
        'preflightCommitment':'confirmed','minContextSlot':slot,'maxRetries':0}])
    require(returned==signature,'RPC signature mismatch; reservation remains pending')
    report.update(status='SUBMITTED_PENDING_FINALITY',transaction_submitted=True,signature=signature)
    return report


@contextmanager
def process_lock():
    path=ROOT/'state'/'amd-seller.lock'
    base.ensure_private_state_dir(path.parent)
    with base.open_state_lock(path) as stream:
        try:
            fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            raise SellerError('Another AMD.X seller is running') from None
        yield


def runtime_status(live,status):
    import os
    try:
        atomic_write(ROOT/'state'/'amd-seller-runtime.json',{'pid':os.getpid(),
            'mode':'live' if live else 'simulation','status':status,'updated_at':time.time()})
    except OSError:
        pass


def main():
    parser=argparse.ArgumentParser(description='AMD.X inventory seller; defaults to simulation')
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--watch',action='store_true')
    args=parser.parse_args()
    from . import execution_barrier
    execution_barrier.arm()
    print('AMD.X: no total or per-trade amount cap; available inventory only; native XNT proceeds; '+('LIVE' if args.live else 'SIMULATION'),flush=True)
    try:
        with process_lock():
            while True:
                runtime_status(args.live,'CHECKING')
                report=cycle(args.live)
                runtime_status(args.live,report['status'])
                print(json.dumps(report),flush=True)
                if not args.watch:
                    return 0
                time.sleep(60)
    except KeyboardInterrupt:
        return 0
    except Exception as error:
        runtime_status(args.live,'STOPPED_ERROR')
        message=str(error) if isinstance(error,(SellerError,NinjaError,WalletError)) else 'Invalid data or local I/O failure'
        print('AMD.X seller stopped: '+message+'. Pending reservations remain.',file=sys.stderr,flush=True)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
