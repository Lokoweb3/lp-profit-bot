"""Bridge verified USDC.X proceeds to the same wallet on Solana.

Dry run is the default. A live run must be explicitly requested with --live.
The journal reserves an amount before broadcast and never retries an unknown send.
"""
import argparse
import base64
import fcntl
import json
import os
import struct
import subprocess
import time
import urllib.error
import urllib.request
from contextlib import contextmanager, nullcontext
from decimal import Decimal

from cryptography.hazmat.primitives import serialization
from solders.compute_budget import set_compute_unit_limit, set_compute_unit_price
from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.message import MessageV0, to_bytes_versioned
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.transaction import VersionedTransaction

from . import seller as s
from . import xnt_conversion
from .proceeds import ProceedsHistory, decode

API = 'https://api.bridge.mainnet.x1.xyz'
PROGRAM = '6JbPTuxVuoTgyQeXFb9MH8C8nUY8NBbLP1Lu4B13JfMD'
SOL_USDC = 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v'
SYSTEM = '11111111111111111111111111111111'
STATE = s.ROOT/'state'/'auto-bridge-journal.json'
LOCK = s.ROOT/'state'/'auto-bridge.lock'
TX_LOCK = s.ROOT/'state'/'auto-bridge-transaction.lock'
RUNTIME = s.ROOT/'state'/'auto-bridge-runtime.json'
LOG = s.ROOT/'state'/'auto-bridge.log'
MIN_BATCH = 10_000_000
MAX_BATCH = 100_000_000
MAX_FEE = 1_000_000
MAX_NATIVE_COST = s.COST_CEILING
SOL_RPC = 'https://api.mainnet-beta.solana.com'


def api(path):
    request = urllib.request.Request(API + path, headers={'Accept': 'application/json'})
    with urllib.request.urlopen(request, timeout=12) as response:
        s.require(response.url == API + path, 'Unexpected bridge API redirect')
        return json.load(response)


def bridge_config():
    data = api('/config')
    source, dest = data['x1'], data['solana']
    s.require(source['config']['programId'] == dest['config']['programId'] == PROGRAM,
              'Bridge program changed')
    s.require(not source['config']['paused'] and not dest['config']['paused'], 'Bridge paused')
    tokens = []
    for chain, mint, native in ((source, s.USDC_MINT, False), (dest, SOL_USDC, True)):
        matches = [t for t in chain['tokens'] if t['symbol'] == 'USDC']
        s.require(len(matches) == 1, 'USDC bridge route unavailable')
        token = matches[0]
        s.require(token['mint'] == mint and token['decimals'] == 6 and token['isNative'] == native
                  and not token['paused'], 'USDC bridge route changed or paused')
        tokens.append(token)
    token = tokens[0]
    s.require(int(token['flatFeeAmount']) <= MAX_FEE and int(token['percentageFeeBps']) == 0,
              'Bridge token fee exceeds policy')
    s.require(int(source['config']['flatFeeLamports']) == 0 and
              int(source['config']['percentageFeeBps']) == 0, 'Bridge native fee exceeds policy')
    s.require(token['feeCollectorAta'] != SYSTEM, 'Bridge token fee account unavailable')
    guardians = api('/guardians')['guardians']
    healthy = sum(g.get('status') == 'healthy' and g.get('watches') == 'x1' and
                  g.get('pubkey') in dest['config']['guardians'] for g in guardians)
    s.require(healthy >= int(dest['config']['threshold']), 'Bridge guardian threshold unavailable')
    return source, token


def solana_rpc(method, params):
    request = json.dumps({'jsonrpc':'2.0', 'id':1, 'method':method, 'params':params})
    result = subprocess.run(['curl', '--fail', '--silent', '--show-error', '--max-time', '20',
                             SOL_RPC, '-H', 'Content-Type: application/json', '--data-binary', '@-'],
                            input=request, text=True, capture_output=True, timeout=25, check=True)
    payload = json.loads(result.stdout)
    s.require('result' in payload and not payload.get('error'), 'Solana RPC unavailable')
    return payload['result']


def destination_receipt(signature, minimum):
    tx = solana_rpc('getTransaction', [signature, {'encoding':'json', 'commitment':'finalized',
                     'maxSupportedTransactionVersion':0}])
    if tx is None:
        return False
    s.require(tx['transaction']['signatures'][0] == signature and tx['meta']['err'] is None,
              'Destination transaction failed or mismatched')
    def balance(field):
        rows = [row for row in tx['meta'].get(field, []) if
                row.get('owner') == s.WALLET and row.get('mint') == SOL_USDC]
        s.require(all(row['uiTokenAmount']['decimals'] == 6 for row in rows),
                  'Destination USDC decimals changed')
        return sum(int(row['uiTokenAmount']['amount']) for row in rows)
    s.require(balance('postTokenBalances') - balance('preTokenBalances') >= minimum,
              'Destination USDC receipt below bridge minimum')
    return True


def read_journal():
    if not STATE.exists() and not STATE.is_symlink():
        return {'version': 1, 'wallet': s.WALLET, 'destination': s.WALLET, 'entries': []}
    journal = s.read_state_json(STATE)
    s.require(journal['version'] == 1 and journal['wallet'] == s.WALLET and
              journal['destination'] == s.WALLET and isinstance(journal['entries'], list),
              'Invalid bridge journal')
    for row in journal['entries']:
        s.require(type(row['amount_raw']) is int and MIN_BATCH <= row['amount_raw'] <= MAX_BATCH and
                  row['status'] in ('pending_x1', 'pending_solana', 'completed', 'failed'),
                  'Invalid bridge journal entry')
        Signature.from_string(row['signature'])
    s.require(len({r['signature'] for r in journal['entries']}) == len(journal['entries']),
              'Duplicate bridge signature')
    return journal


def proceeds():
    """Count finalized automatic conversions and direct GOOGL sales only."""
    history = ProceedsHistory()
    total = 0
    sources = [('XNT', s.WXNT, xnt_conversion.read_journal),
               ('GOOGL.X', s.GOOGL_MINT, s.read_journal)]
    for asset, mint, reader in sources:
        for row in reader()['entries']:
            if row['status'] != 'finalized':
                continue
            if asset == 'XNT' and row.get('source') not in ('spy_proceeds_auto', 'stock_proceeds_auto'):
                continue
            result = history.cache.get(row['signature'])
            if result is None:
                tx = s.rpc('getTransaction', [row['signature'], {'encoding':'json',
                           'commitment':'finalized', 'maxSupportedTransactionVersion':0}])
                result = decode(tx, row, asset, mint)
            s.require(result['signature'] == row['signature'] and result['asset'] == asset and
                      result['status'] == 'finalized', 'Unverified proceeds receipt')
            total += int(Decimal(result['usdc_received']) * 10**6)
    return total


def reconcile(journal):
    """A pending/unknown bridge blocks new sends until destination receipt is known."""
    for row in journal['entries']:
        if row['status'] == 'pending_x1':
            value = s.rpc('getSignatureStatuses', [[row['signature']],
                           {'searchTransactionHistory': True}])['value'][0]
            if value is None or value.get('confirmationStatus') != 'finalized':
                return False
            row['status'] = 'failed' if value['err'] is not None else 'pending_solana'
            s.atomic_write(STATE, journal)
        if row['status'] == 'pending_solana':
            try:
                result = api('/transactions/' + row['signature'])
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    return False
                raise
            tx = result.get('transaction', result)
            if tx.get('status') not in ('executed', 'completed') or not tx.get('destTxSig'):
                return False
            # Fee was fixed by policy when this worker submitted the transfer.
            if not destination_receipt(tx['destTxSig'], row['amount_raw'] - MAX_FEE):
                return False
            row['destination_signature'] = tx['destTxSig']
            row['status'] = 'completed'
            s.atomic_write(STATE, journal)
        if row['status'] == 'failed':
            # Even a failed source transaction stays reserved until manual review.
            return False
    return True


def pda(*seeds):
    return str(Pubkey.find_program_address(list(seeds), Pubkey.from_string(PROGRAM))[0])


def build(amount, slot, blockhash, fee_account, fee_collector):
    # Bridge client sequence: top nibble = source chain 1, next = destination 0.
    seq = (1 << 60) | (slot * 1000)
    s.require(0 < seq < 2**64, 'Bridge sequence out of range')
    pub = Pubkey.from_string
    outgoing = pda(b'evt_out', struct.pack('<Q', seq))
    keys = [pda(b'config'), pda(b'token_registry', bytes(pub(s.USDC_MINT))), outgoing,
            s.WALLET, s.associated(s.USDC_MINT), s.USDC_MINT, PROGRAM, PROGRAM,
            fee_collector, fee_account, s.TOKEN, SYSTEM]
    metas = [AccountMeta(pub(key), i == 3, i in (0, 1, 2, 3, 4, 5, 8, 9))
             for i, key in enumerate(keys)]
    ix = Instruction(pub(PROGRAM), bytes([27,194,57,119,215,165,247,150]) +
                     struct.pack('<QQ', seq, amount), metas)
    message = MessageV0.try_compile(pub(s.WALLET),
                [set_compute_unit_limit(250_000), set_compute_unit_price(10_000), ix],
                [], Hash.from_string(blockhash))
    return VersionedTransaction.populate(message, [Signature.default()]), outgoing


@contextmanager
def transaction_lock():
    s.ensure_private_state_dir(TX_LOCK.parent)
    with s.open_state_lock(TX_LOCK) as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def wallet_balance():
    account = s.rpc('getAccountInfo', [s.associated(s.USDC_MINT),
                    {'encoding':'base64', 'commitment':'confirmed'}])['value']
    return s.token_balance(account, s.USDC_MINT, s.WALLET)


def amount_raw(text):
    try:
        amount = Decimal(str(text)) * 10**6
    except Exception:
        raise s.SellerError('Enter a valid USDC.X amount') from None
    s.require(amount.is_finite() and amount == amount.to_integral_value() and
              MIN_BATCH <= amount <= MAX_BATCH, 'Enter 10 to 100 USDC.X with at most 6 decimals')
    return int(amount)


def preview(text):
    from . import execution_barrier
    barrier_generation=execution_barrier.arm()
    amount = amount_raw(text)
    _, token = bridge_config()
    s.require(amount >= int(token['minAmount']) and amount <= int(token['maxAmount']) and
              amount <= int(token['dailyCapRemaining']), 'Amount exceeds current bridge limits')
    s.require(wallet_balance() >= amount, 'Insufficient USDC.X wallet balance')
    fee = int(token['flatFeeAmount'])
    s.require(amount > fee, 'Amount must exceed the bridge fee')
    return {'amount_raw':amount, 'amount_usdc':str(Decimal(amount)/10**6),
            'fee_usdc':str(Decimal(fee)/10**6),
            'expected_usdc':str(Decimal(amount-fee)/10**6),
            'destination':s.WALLET, 'expires_at':time.time()+30,
            'barrier_generation':barrier_generation}


def execute_manual(quote):
    with transaction_lock():
        s.require(time.time() <= quote['expires_at'], 'Bridge preview expired; preview again')
        journal = read_journal()
        s.require(reconcile(journal), 'Previous bridge is pending; no duplicate transfer sent')
        s.require(xnt_conversion.ready(), 'Conversion pending; bridge deferred')
        source, token = bridge_config()
        amount = quote['amount_raw']
        s.require(type(amount) is int and MIN_BATCH <= amount <= MAX_BATCH and
                  amount <= int(token['maxAmount']) and amount <= int(token['dailyCapRemaining']) and
                  amount >= int(token['minAmount']), 'Bridge amount exceeds current limits')
        s.require(str(Decimal(token['flatFeeAmount'])/10**6) == quote['fee_usdc'],
                  'Bridge fee changed; preview again')
        balance = wallet_balance()
        s.require(balance >= amount, 'Insufficient USDC.X wallet balance')
        return submit(journal, source, token, amount, balance, True, 'manual',
                      quote.get('barrier_generation'))


def cycle(live=False):
    with transaction_lock():
        return locked_cycle(live)


def locked_cycle(live=False):
    journal = read_journal()
    if not reconcile(journal):
        return {'status':'WAITING_FOR_BRIDGE_FINALITY'}
    s.require(xnt_conversion.ready(), 'Conversion pending; bridge deferred')
    source, token = bridge_config()
    earned = proceeds()
    reserved = sum(row['amount_raw'] for row in journal['entries'])
    available = max(0, earned - reserved)
    balance = wallet_balance()
    amount = min(available, balance, MAX_BATCH, int(token['maxAmount']),
                 int(token['dailyCapRemaining']))
    minimum = max(MIN_BATCH, int(token['minAmount']))
    if amount < minimum:
        return {'status':'WAITING_FOR_PROCEEDS', 'earned_raw':earned,
                'reserved_raw':reserved, 'available_raw':available, 'wallet_usdc_raw':balance,
                'minimum_raw':minimum}
    return submit(journal, source, token, amount, balance, live, 'automatic')


def submit(journal, source, token, amount, balance, live, kind, barrier_generation=None):
    native = s.rpc('getBalance', [s.WALLET, {'commitment':'confirmed'}])['value']
    s.require(native >= MAX_NATIVE_COST + 1_000_000, 'Insufficient XNT fee reserve')
    slot = s.rpc('getSlot', [{'commitment':'confirmed'}])
    block = s.rpc('getLatestBlockhash', [{'commitment':'confirmed'}])['value']
    s.require(source['config']['feeCollector'] != SYSTEM, 'Bridge fee collector unavailable')
    unsigned, outgoing = build(amount, slot, block['blockhash'], token['feeCollectorAta'],
                               source['config']['feeCollector'])
    fee = s.rpc('getFeeForMessage', [base64.b64encode(to_bytes_versioned(unsigned.message)).decode(),
                {'commitment':'confirmed'}])['value']
    s.require(type(fee) is int and fee <= MAX_NATIVE_COST, 'Bridge network fee exceeds policy')
    simulation = s.rpc('simulateTransaction', [s.encoded(unsigned), {'encoding':'base64',
                       'sigVerify':False, 'commitment':'confirmed',
                       'accounts':{'encoding':'base64',
                       'addresses':[s.associated(s.USDC_MINT), s.WALLET]}}])
    value = simulation['value']
    s.require(value['err'] is None, 'Bridge simulation rejected transaction')
    after = s.token_balance(value['accounts'][0], s.USDC_MINT, s.WALLET)
    # The bridge takes its flat fee from the amount, as its client preview shows.
    s.require(balance - after == amount,
              'Bridge simulation token debit mismatch')
    native_cost = native - value['accounts'][1]['lamports']
    s.require(0 <= native_cost <= MAX_NATIVE_COST, 'Bridge simulation native cost exceeds policy')
    report = {'status':'SIMULATION_PASSED', 'amount_raw':amount,
              'amount_usdc':str(Decimal(amount)/10**6), 'fee_usdc':str(Decimal(token['flatFeeAmount'])/10**6),
              'destination':s.WALLET, 'outgoing_message':outgoing}
    if not live:
        return report
    local = s.load_wallet()
    seed = local.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                               serialization.NoEncryption())
    signer = Keypair.from_seed(seed)
    s.require(str(signer.pubkey()) == s.WALLET, 'Signing wallet mismatch')
    signed = VersionedTransaction(unsigned.message, [signer])
    signature = str(signed.signatures[0])
    journal['entries'].append({'signature':signature, 'amount_raw':amount,
                               'status':'pending_x1', 'created_at':time.time(),
                               'outgoing_message':outgoing, 'source':kind,
                               'fee_raw':int(token['flatFeeAmount'])})
    s.atomic_write(STATE, journal)
    from . import execution_barrier
    context = (execution_barrier.authorize(barrier_generation)
               if barrier_generation is not None else nullcontext())
    with context:
        returned = s.rpc('sendTransaction', [s.encoded(signed), {'encoding':'base64',
                           'skipPreflight':False, 'preflightCommitment':'confirmed',
                           'minContextSlot':simulation['context']['slot'], 'maxRetries':0}])
    s.require(returned == signature, 'Bridge RPC signature mismatch; reservation retained')
    return dict(report, status='SUBMITTED_PENDING_FINALITY', signature=signature)


@contextmanager
def process_lock():
    s.ensure_private_state_dir(LOCK.parent)
    with s.open_state_lock(LOCK) as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise s.SellerError('Another automatic bridge worker is running') from None
        yield


def main():
    parser = argparse.ArgumentParser(description='Bridge verified USDC.X proceeds to the same Solana wallet')
    parser.add_argument('--live', action='store_true', help='Sign and send bridge transactions')
    parser.add_argument('--watch', action='store_true', help='Repeat every 30 seconds')
    args = parser.parse_args()
    from . import execution_barrier
    execution_barrier.arm()
    with process_lock():
        while True:
            try:
                report = cycle(args.live)
                record = {'at':time.time(), 'mode':'live' if args.live else 'simulation', **report}
                s.atomic_write(RUNTIME, {'updated_at':record['at'], 'pid':os.getpid(),
                              'mode':record['mode'], 'status':report['status']})
                with LOG.open('a') as stream:
                    stream.write(json.dumps(record) + '\n')
                print(json.dumps(report), flush=True)
            except OSError:
                # Public bridge API timeouts are transient. The journal still blocks
                # any new send until a pending source/destination is reconciled.
                record = {'at':time.time(), 'mode':'live' if args.live else 'simulation',
                          'status':'RETRYING_BRIDGE_API', 'message':'Bridge API unavailable; retrying.'}
                s.atomic_write(RUNTIME, {'updated_at':record['at'], 'pid':os.getpid(),
                              'mode':record['mode'], 'status':record['status']})
                with LOG.open('a') as stream:
                    stream.write(json.dumps(record) + '\n')
                print(json.dumps(record), flush=True)
                if not args.watch:
                    parser.exit(1, 'Bridge API unavailable; retry later.\n')
            except (s.SellerError, ValueError, KeyError, TypeError) as exc:
                s.atomic_write(RUNTIME, {'updated_at':time.time(), 'pid':os.getpid(),
                              'mode':'live' if args.live else 'simulation', 'status':'STOPPED_ERROR'})
                with LOG.open('a') as stream:
                    stream.write(json.dumps({'at':time.time(), 'status':'STOPPED_ERROR',
                                             'message':str(exc)}) + '\n')
                parser.exit(1, f'Automatic bridge stopped: {exc}\n')
            if not args.watch:
                break
            time.sleep(30)


if __name__ == '__main__':
    main()
