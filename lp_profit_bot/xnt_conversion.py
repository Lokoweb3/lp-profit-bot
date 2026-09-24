"""Explicitly confirmed XNT -> USDC.X conversions with durable send reservation."""
import json
import fcntl
import time
from contextlib import contextmanager, nullcontext
from decimal import Decimal
from solders.keypair import Keypair
from solders.signature import Signature
from solders.transaction import VersionedTransaction
from cryptography.hazmat.primitives import serialization
from . import seller as s, native_swaps as swaps
from .spy_seller import native_lock, read_journal as spy_journal, reconcile as reconcile_spy

STATE = s.ROOT/'state'/'xnt-conversion-journal.json'
JOURNAL_LOCK = s.ROOT/'state'/'xnt-conversion-journal.lock'


@contextmanager
def journal_lock():
    with s.open_state_lock(JOURNAL_LOCK) as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def _read_journal():
    if not STATE.exists() and not STATE.is_symlink():
        return {'wallet':s.WALLET,'entries':[]}
    j=s.read_state_json(STATE)
    s.require(j['wallet']==s.WALLET and isinstance(j['entries'],list),'Invalid conversion journal')
    for row in j['entries']:
        s.require(type(row['amount_raw']) is int and row['amount_raw']>0
                  and row['status'] in ('pending','finalized','failed'),'Invalid conversion entry')
        Signature.from_string(row['signature'])
    s.require(len({r['signature'] for r in j['entries']})==len(j['entries']),'Duplicate conversion signature')
    return j


def read_journal():
    with journal_lock():
        return _read_journal()


def ready():
    with journal_lock():
        journal=_read_journal()
        changed=False
        for row in journal['entries']:
            if row['status']!='pending':
                continue
            value=s.rpc('getSignatureStatuses',[[row['signature']],{'searchTransactionHistory':True}])['value'][0]
            if value is None or value.get('confirmationStatus')!='finalized':
                return False
            row['status']='failed' if value['err'] is not None else 'finalized'
            changed=True
        if changed:
            s.atomic_write(STATE,journal)
        return True


def stock_sales_ready():
    from . import spcx_seller, tsla_seller, meta_seller, coin_seller, pltr_seller, amd_seller, nvda_seller, aapl_seller
    if not reconcile_spy(spy_journal()):
        return False
    for module in (spcx_seller,tsla_seller,meta_seller,coin_seller,pltr_seller,amd_seller,nvda_seller,aapl_seller):
        if not module.reconcile(module.read_journal()):
            return False
    return True


def amount_raw(text):
    value=Decimal(str(text))
    s.require(value.is_finite() and value>0 and value*10**9==(value*10**9).to_integral_value(),
              'Enter a positive XNT amount with at most 9 decimal places')
    s.require(value<10**9,'XNT amount is too large')
    return int(value*10**9)


def preview(text):
    from . import execution_barrier
    barrier_generation=execution_barrier.arm()
    amount=amount_raw(text)
    snap=swaps.xnt_snapshot()
    output,minimum=swaps.xnt_quote(snap,amount)
    return {'amount_raw':amount,'minimum_raw':minimum,'amount_xnt':str(Decimal(amount)/10**9),
            'estimated_usdc':str(Decimal(output)/10**6),'minimum_usdc':str(Decimal(minimum)/10**6),
            'expires_at':time.time()+30,'cost_allowance_xnt':'0.01',
            'barrier_generation':barrier_generation}


def execute(quote):
    with native_lock():
        return execute_locked(quote)


def execute_locked(quote, *, source="manual", native_floor=0):
    s.require(time.time()<=quote['expires_at'],'Quote expired; request a new preview')
    s.require(ready(),'Previous XNT conversion is pending; no duplicate will be sent')
    s.require(stock_sales_ready(),'Stock sale is pending; wait for finality')
    snap=swaps.xnt_snapshot()
    s.require(snap['native_balance']-quote['amount_raw']-s.COST_CEILING >= native_floor,
              'Conversion would use the protected XNT reserve')
    output,_=swaps.xnt_quote(snap,quote['amount_raw'])
    s.require(output>=quote['minimum_raw'],'Market moved below your minimum; request a new quote')
    unsigned,block,slot,received=swaps.simulate(snap,quote['amount_raw'],quote['minimum_raw'])
    s.require(time.time()<=quote['expires_at'],'Quote expired during simulation')
    local=s.load_wallet()
    seed=local.private_bytes(serialization.Encoding.Raw,serialization.PrivateFormat.Raw,serialization.NoEncryption())
    signer=Keypair.from_seed(seed)
    s.require(str(signer.pubkey())==s.WALLET,'Signing wallet mismatch')
    signed=VersionedTransaction(unsigned.message,[signer]); signature=str(signed.signatures[0])
    with journal_lock():
        journal=_read_journal()
        s.require(not any(row['status']=='pending' for row in journal['entries']),
                  'Previous XNT conversion is pending; no duplicate will be sent')
        journal['entries'].append({'signature':signature,'amount_raw':quote['amount_raw'],
             'minimum_output_raw':quote['minimum_raw'],'status':'pending','created_at':time.time(),
             'last_valid_block_height':block['lastValidBlockHeight'],'source':source})
        s.atomic_write(STATE,journal)
    from . import execution_barrier
    context = (execution_barrier.authorize(quote['barrier_generation'])
               if 'barrier_generation' in quote else nullcontext())
    with context:
        returned=s.rpc('sendTransaction',[s.encoded(signed),{'encoding':'base64','skipPreflight':False,
             'preflightCommitment':'confirmed','minContextSlot':slot,'maxRetries':0}])
    s.require(returned==signature,'RPC signature mismatch; reservation remains pending')
    return {'signature':signature,'message':'Conversion submitted. Awaiting finality.'}
