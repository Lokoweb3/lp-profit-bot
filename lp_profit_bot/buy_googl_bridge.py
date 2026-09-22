"""One bounded Solana USDC -> stock purchase and stock -> X1 bridge.

No spend occurs without --live. Persistent stages prevent blind resend after
RPC failures. The bridge's destination is the same public wallet on X1.
"""
import argparse
import base64
import fcntl
import json
import re
import struct
import time
import urllib.parse
import urllib.error
import urllib.request
from decimal import Decimal
from contextlib import contextmanager

from cryptography.hazmat.primitives import serialization
from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.message import MessageV0
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.transaction import VersionedTransaction

from . import seller as s, auto_bridge as bridge
from .stock_policy import STOCKS

LOCK = s.ROOT/'state'/'googlx-buy-bridge.lock'
USDC = bridge.SOL_USDC
GOOGL = 'XsCPL9dNWBMvFtTmwcCA5v3xWPSMEBCszbQdiLLq6aN'
X1_GOOGL = s.GOOGL_MINT
SOLANA_STOCK_MINTS = {
    'googl': GOOGL,
    'spy': 'XsoCS1TfEyfFhfvj8EtZ528L3CaKBDBRqRapnBbDF2W',
    'spcx': 'Xs3oZwbHvqis4NYcf4YKWmEia2eC84wSiVrcYcTqpH8',
    'tsla': 'XsDoVfqeBukxuZHWhdvWHBhgEHjGNst4MLodqsJHzoB',
    'meta': 'Xsa62P5mvPszXL1krVUnU5ar38bBSVcWAB6fmPCo5Zu',
    'coin': 'Xs7ZdzSHLU9ftNJsii5fCeJhoRWSC32SQGzGQtePxNu',
    'pltr': 'XsoBhf2ufR8fTyNSjqfU71DYGaE6Z3SUGAidpzriAA4',
    'amd': 'XsXcJ6GZ9kVnjqGsjBnktRcuwMBmvKWh8S93RefZ1rF',
    'nvda': 'Xsc9qvGR1efVDFGLrVsmkzv3qi45LTBjeUKSPmx9qEh',
}
ASSETS = {'googl': {'key': 'googl', 'symbol': 'GOOGL', 'sol_mint': GOOGL,
                    'x1_mint': X1_GOOGL}}
ASSETS.update({key: {'key': key, 'symbol': stock.symbol.removesuffix('.X'),
                     'sol_mint': SOLANA_STOCK_MINTS[key], 'x1_mint': stock.mint}
               for key, stock in STOCKS.items()})
TOKEN_2022 = s.TOKEN
TOKEN_CLASSIC = 'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'
WSOL = 'So11111111111111111111111111111111111111112'
JUPITER = 'JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4'
COMPUTE = 'ComputeBudget111111111111111111111111111111'
DEFAULT_USDC_RAW = 11_000_000
MIN_BRIDGE_RAW = 2_900_000
MAX_SLIPPAGE_BPS = 50
MAX_PRIORITY_LAMPORTS = 100_000
MAX_SOL_COST_LAMPORTS = 20_000_000


def request_json(url, body=None):
    headers = {'Accept':'application/json'}
    if body is not None:
        headers['Content-Type'] = 'application/json'
    request = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                     headers=headers, method='POST' if body is not None else 'GET')
    with urllib.request.urlopen(request, timeout=25) as response:
        s.require(response.url == url, 'Unexpected Jupiter redirect')
        return json.load(response)


def journal_path(asset):
    return s.ROOT/'state'/('googlx-buy-bridge-journal.json' if asset['key'] == 'googl'
                           else f"{asset['key']}-buy-bridge-journal.json")


def parse_usdc_amount(value):
    s.require(type(value) is str and re.fullmatch(r'(?:0|[1-9][0-9]*)(?:\.[0-9]{1,6})?', value) is not None,
              'Enter a USDC amount with at most 6 decimal places')
    raw = int(Decimal(value) * 10**6)
    s.require(0 < raw < 2**64, 'USDC amount is outside the supported range')
    return raw


def quote(amount_raw=DEFAULT_USDC_RAW, asset=None, minimum_raw=MIN_BRIDGE_RAW):
    asset = ASSETS['googl'] if asset is None else asset
    s.require(type(amount_raw) is int and 0 < amount_raw < 2**64, 'Invalid USDC amount')
    params = urllib.parse.urlencode({'inputMint':USDC, 'outputMint':asset['sol_mint'],
             'amount':amount_raw, 'slippageBps':MAX_SLIPPAGE_BPS, 'instructionVersion':'V2'})
    result = request_json('https://api.jup.ag/swap/v1/quote?' + params)
    s.require(result['inputMint'] == USDC and result['outputMint'] == asset['sol_mint'] and
              result['inAmount'] == str(amount_raw) and result['swapMode'] == 'ExactIn' and
              result['slippageBps'] == MAX_SLIPPAGE_BPS, 'Jupiter quote changed route')
    s.require(int(result['otherAmountThreshold']) >= minimum_raw,
              f"{asset['symbol']} quote minimum "
              f"{Decimal(result['otherAmountThreshold'])/10**8} is below bridge minimum "
              f"{Decimal(minimum_raw)/10**8}; no purchase will be sent")
    s.require(int(result['outAmount']) >= int(result['otherAmountThreshold']) > 0,
              'Invalid stock quote amount')
    s.require(Decimal(result['priceImpactPct']) <= Decimal('0.01'), 'Swap price impact exceeds 1%')
    return result


def bridge_token(asset=None):
    asset = ASSETS['googl'] if asset is None else asset
    data = bridge.api('/config')
    source, dest = data['solana'], data['x1']
    s.require(source['config']['programId'] == dest['config']['programId'] == bridge.PROGRAM and
              not source['config']['paused'] and not dest['config']['paused'], 'Bridge route unavailable')
    source_matches = [t for t in source['tokens'] if t['symbol'] == asset['symbol']]
    dest_matches = [t for t in dest['tokens'] if t['symbol'] == asset['symbol']]
    s.require(len(source_matches) == len(dest_matches) == 1, 'Stock bridge route unavailable')
    a, b = source_matches[0], dest_matches[0]
    s.require(a['mint'] == asset['sol_mint'] and b['mint'] == asset['x1_mint'] and a['decimals'] == b['decimals'] == 8
              and a['isNative'] is True and b['isNative'] is False and
              not a['paused'] and not b['paused'], 'Stock bridge mint or route changed')
    s.require(int(a['minAmount']) > 0 and int(a['percentageFeeBps']) <= 25 and
              int(a['flatFeeAmount']) == 0, 'Stock bridge limits or fee changed')
    return source, a


def new_attempt(asset, spend_raw):
    return {'version':1, 'wallet':s.WALLET, 'stage':'new', 'spend_raw':spend_raw,
            'asset':asset['key'], 'sol_mint':asset['sol_mint'], 'x1_mint':asset['x1_mint']}


def read_history(asset=None):
    asset = ASSETS['googl'] if asset is None else asset
    path = journal_path(asset)
    if not path.exists() and not path.is_symlink():
        return []
    data = s.read_state_json(path)
    rows = data['attempts'] if data.get('version') == 2 else [data]
    s.require(type(rows) is list and len(rows) > 0, 'Invalid stock purchase history')
    for row in rows:
        s.require(type(row) is dict and row.get('version') == 1 and row.get('wallet') == s.WALLET and
              type(row.get('spend_raw')) is int and 0 < row['spend_raw'] < 2**64 and row.get('stage') in
              ('new','swap_pending','swap_finalized','bridge_pending','completed','failed'),
              'Invalid stock purchase journal')
        if asset['key'] != 'googl' or 'asset' in row:
            s.require(row.get('asset') == asset['key'] and row.get('sol_mint') == asset['sol_mint']
                  and row.get('x1_mint') == asset['x1_mint'], 'Journal belongs to another stock')
        for key in ('swap_signature','bridge_signature'):
            if key in row:
                Signature.from_string(row[key])
    s.require(all(row['stage'] == 'completed' for row in rows[:-1]),
              'Earlier stock purchase is not completed')
    return rows


def read_journal(asset=None):
    asset = ASSETS['googl'] if asset is None else asset
    rows = read_history(asset)
    return rows[-1] if rows else new_attempt(asset, DEFAULT_USDC_RAW)


def write_attempt(asset, row, append=False):
    rows = read_history(asset)
    if append:
        s.require(not rows or rows[-1]['stage'] == 'completed',
                  'Previous stock purchase is not completed')
        rows.append(row)
    elif rows:
        rows[-1] = row
    else:
        rows = [row]
    s.atomic_write(journal_path(asset), {'version':2, 'attempts':rows})


def signer():
    key = s.load_wallet()
    seed = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                             serialization.NoEncryption())
    result = Keypair.from_seed(seed)
    s.require(str(result.pubkey()) == s.WALLET, 'Bot signing wallet mismatch')
    return result


def owner_balance(mint):
    result = bridge.solana_rpc('getTokenAccountsByOwner', [s.WALLET, {'mint':mint},
                                 {'encoding':'jsonParsed','commitment':'confirmed'}])['value']
    return sum(int(a['account']['data']['parsed']['info']['tokenAmount']['amount']) for a in result)


def associated(mint, program):
    pub = Pubkey.from_string
    return str(Pubkey.find_program_address([bytes(pub(s.WALLET)),bytes(pub(program)),
                bytes(pub(mint))],pub(s.ATA))[0])


def transaction_receipt(signature, mint):
    tx = bridge.solana_rpc('getTransaction', [signature, {'encoding':'json',
                           'commitment':'finalized','maxSupportedTransactionVersion':0}])
    if tx is None:
        return None
    s.require(tx['transaction']['signatures'][0] == signature and tx['meta']['err'] is None,
              'Solana transaction failed; manual review required')
    def balance(field):
        return sum(int(a['uiTokenAmount']['amount']) for a in tx['meta'].get(field, [])
                   if a.get('owner') == s.WALLET and a.get('mint') == mint)
    return balance('postTokenBalances') - balance('preTokenBalances')


def validate_swap_programs(message):
    keys = [str(key) for key in message.account_keys]
    programs = [keys[ix.program_id_index] for ix in message.instructions]
    allowed = {COMPUTE, s.ATA, JUPITER, TOKEN_CLASSIC}
    s.require(set(programs) <= allowed and JUPITER in programs,
              'Unexpected Jupiter top-level program')
    cleanup = [(position, ix) for position, ix in enumerate(message.instructions)
               if programs[position] == TOKEN_CLASSIC]
    if not cleanup:
        return False
    wsol_ata = associated(WSOL, TOKEN_CLASSIC)
    s.require(len(cleanup) == 1, 'Unexpected Jupiter token cleanup')
    position, ix = cleanup[0]
    s.require(bytes(ix.data) == b'\x09' and len(ix.accounts) == 3 and
              all(index < len(keys) for index in ix.accounts) and
              [keys[index] for index in ix.accounts] == [wsol_ata, s.WALLET, s.WALLET],
              'Unexpected Jupiter token cleanup')
    creates = [entry for prior, entry in enumerate(message.instructions) if prior < position and
               programs[prior] == s.ATA and bytes(entry.data) == b'\x01' and
               len(entry.accounts) == 6 and all(index < len(keys) for index in
               (entry.accounts[0], entry.accounts[1], entry.accounts[2],
                entry.accounts[4], entry.accounts[5])) and
               [keys[entry.accounts[index]] for index in (0, 1, 2, 4, 5)] ==
               [s.WALLET, wsol_ata, s.WALLET, bridge.SYSTEM, TOKEN_CLASSIC]]
    s.require(len(creates) == 1, 'Unexpected Jupiter wrapped SOL setup')
    return True


def prepare_swap(q, asset=None, spend_raw=None):
    asset = ASSETS['googl'] if asset is None else asset
    spend_raw = int(q['inAmount']) if spend_raw is None else spend_raw
    data = request_json('https://api.jup.ag/swap/v1/swap', {
        'quoteResponse':q, 'userPublicKey':s.WALLET, 'dynamicComputeUnitLimit':True,
        'prioritizationFeeLamports':{'priorityLevelWithMaxLamports':
            {'priorityLevel':'medium','maxLamports':MAX_PRIORITY_LAMPORTS}}})
    s.require(data.get('simulationError') is None, 'Jupiter build simulation failed')
    unsigned = VersionedTransaction.from_bytes(base64.b64decode(data['swapTransaction'], validate=True))
    message = unsigned.message
    s.require(str(message.account_keys[0]) == s.WALLET and message.header.num_required_signatures == 1,
              'Jupiter transaction payer/signers changed')
    if validate_swap_programs(message):
        wsol_ata = associated(WSOL, TOKEN_CLASSIC)
        account = bridge.solana_rpc('getAccountInfo',
            [wsol_ata, {'encoding':'base64','commitment':'confirmed'}])['value']
        s.require(account is None, 'Existing wrapped SOL account cannot be closed by this swap')
    s.require(str(message.account_keys[0]) == s.WALLET, 'Unexpected Jupiter fee payer')
    before_usdc, before_stock = owner_balance(USDC), owner_balance(asset['sol_mint'])
    native = bridge.solana_rpc('getBalance',[s.WALLET, {'commitment':'confirmed'}])['value']
    s.require(before_usdc >= spend_raw and native >= MAX_SOL_COST_LAMPORTS,
              'Insufficient Solana USDC or SOL reserve')
    # The output ATA does not exist yet; simulation must return its new balance.
    pub = Pubkey.from_string
    output_ata = associated(asset['sol_mint'],TOKEN_2022)
    sim = bridge.solana_rpc('simulateTransaction', [base64.b64encode(bytes(unsigned)).decode(),
          {'encoding':'base64','sigVerify':False,'commitment':'confirmed',
           'accounts':{'encoding':'base64','addresses':[associated(USDC,TOKEN_CLASSIC),output_ata,s.WALLET]}}])['value']
    s.require(sim['err'] is None and len(sim['accounts']) == 3, 'Swap simulation failed')
    usdc_after = s.token_balance(sim['accounts'][0], USDC, s.WALLET, program=TOKEN_CLASSIC)
    stock_after = s.token_balance(sim['accounts'][1], asset['sol_mint'], s.WALLET)
    s.require(before_usdc - usdc_after == spend_raw and
              stock_after - before_stock >= int(q['otherAmountThreshold']),
              'Swap simulation amount or minimum output mismatch')
    s.require(0 <= native - sim['accounts'][2]['lamports'] <= MAX_SOL_COST_LAMPORTS,
              'Swap SOL cost exceeds allowance')
    return unsigned


def build_bridge(amount_raw, source, token, asset=None):
    asset = ASSETS['googl'] if asset is None else asset
    mint = asset['sol_mint']
    pub = Pubkey.from_string
    slot = bridge.solana_rpc('getSlot',[{'commitment':'confirmed'}])
    seq = (1 << 56) | (slot*1000)
    s.require(0 < seq < 2**64, 'Bridge sequence out of range')
    pda = lambda *parts: str(Pubkey.find_program_address(list(parts),pub(bridge.PROGRAM))[0])
    vault = pda(b'vault', bytes(pub(mint)))
    vault_ata = str(Pubkey.find_program_address([bytes(pub(vault)),bytes(pub(TOKEN_2022)),bytes(pub(mint))],pub(s.ATA))[0])
    keys = [pda(b'config'),pda(b'token_registry',bytes(pub(mint))),
            pda(b'evt_out',struct.pack('<Q',seq)),s.WALLET,
            associated(mint,TOKEN_2022),
            mint,vault,vault_ata,source['config']['feeCollector'],token['feeCollectorAta'],
            TOKEN_2022,bridge.SYSTEM]
    metas = [AccountMeta(pub(k),i==3,i in (0,1,2,3,4,5,6,7,8,9)) for i,k in enumerate(keys)]
    ix = Instruction(pub(bridge.PROGRAM),bytes([27,194,57,119,215,165,247,150])+
                     struct.pack('<QQ',seq,amount_raw),metas)
    block = bridge.solana_rpc('getLatestBlockhash',[{'commitment':'confirmed'}])['value']
    message = MessageV0.try_compile(pub(s.WALLET),[ix],[],Hash.from_string(block['blockhash']))
    return VersionedTransaction.populate(message,[Signature.default()])


def cycle(live=False, asset_key='googl', approved_minimum_raw=None,
          spend_raw=None, repeat=False):
    s.require(asset_key in ASSETS, 'Unsupported stock')
    asset = ASSETS[asset_key]
    row = read_journal(asset)
    new_round = False
    if row['stage'] == 'completed':
        if not repeat:
            return {'status':'COMPLETED', 'swap_signature':row['swap_signature'],
                    'bridge_signature':row['bridge_signature'],
                    'destination_signature':row['destination_signature']}
        spend_raw = DEFAULT_USDC_RAW if spend_raw is None else spend_raw
        s.require(type(spend_raw) is int and 0 < spend_raw < 2**64, 'Invalid USDC amount')
        row = new_attempt(asset, spend_raw)
        new_round = True
    if row['stage'] == 'failed':
        raise s.SellerError('Prior transaction failed; review journal before any retry')
    if row['stage'] == 'new':
        spend_raw = row['spend_raw'] if spend_raw is None else spend_raw
        s.require(type(spend_raw) is int and 0 < spend_raw < 2**64, 'Invalid USDC amount')
        if live and row['spend_raw'] != spend_raw:
            row['spend_raw'] = spend_raw
        source, token = bridge_token(asset)
        q = quote(amount_raw=spend_raw, asset=asset, minimum_raw=int(token['minAmount']))
        s.require(int(q['outAmount']) <= int(token['maxAmount']) and
                  int(q['outAmount']) <= int(token['dailyCapRemaining']),
                  'Quoted stock amount exceeds bridge limits; no purchase will be sent')
        report = {'status':'SWAP_READY', 'spend_usdc':str(Decimal(spend_raw)/10**6),
                  'asset':asset['symbol'], 'solana_mint':asset['sol_mint'],
                  'x1_mint':asset['x1_mint'],
                  'quoted_stock':str(Decimal(q['outAmount'])/10**8),
                  'minimum_stock':str(Decimal(q['otherAmountThreshold'])/10**8),
                  'bridge_minimum_stock':str(Decimal(token['minAmount'])/10**8)}
        if not live:
            return report
        if approved_minimum_raw is not None:
            s.require(type(approved_minimum_raw) is int and approved_minimum_raw > 0 and
                      int(q['otherAmountThreshold']) >= approved_minimum_raw,
                      'Current protected output is below the confirmed preview; preview again')
        unsigned = prepare_swap(q,asset,spend_raw)
        signed = VersionedTransaction(unsigned.message,[signer()])
        row.update(stage='swap_pending',spend_raw=spend_raw,swap_signature=str(signed.signatures[0]),
                   quote_minimum_raw=int(q['otherAmountThreshold']),created_at=time.time())
        write_attempt(asset,row,append=new_round)
        returned = bridge.solana_rpc('sendTransaction',[base64.b64encode(bytes(signed)).decode(),
                    {'encoding':'base64','skipPreflight':False,'preflightCommitment':'confirmed','maxRetries':0}])
        s.require(returned == row['swap_signature'],'Swap send signature mismatch; reservation retained')
        return dict(report,status='SWAP_PENDING',signature=returned)
    if row['stage'] == 'swap_pending':
        status = bridge.solana_rpc('getSignatureStatuses',[[row['swap_signature']],
                                   {'searchTransactionHistory':True}])['value'][0]
        if status is None or status.get('confirmationStatus') != 'finalized':
            return {'status':'SWAP_PENDING','signature':row['swap_signature']}
        if status['err'] is not None:
            row['stage']='failed';write_attempt(asset,row)
            raise s.SellerError('Swap failed; journal preserved')
        amount = transaction_receipt(row['swap_signature'],asset['sol_mint'])
        spent = transaction_receipt(row['swap_signature'],USDC)
        source, token = bridge_token(asset)
        s.require(amount is not None and amount >= int(token['minAmount']) and
                  spent == -row['spend_raw'], 'Swap receipt failed amount verification')
        row.update(stage='swap_finalized',bought_raw=amount)
        write_attempt(asset,row)
    if row['stage'] == 'swap_finalized':
        source, token = bridge_token(asset)
        amount = row['bought_raw']
        s.require(amount >= int(token['minAmount']) and
                  amount <= int(token['maxAmount']) and amount <= int(token['dailyCapRemaining']),
                  'Purchased stock no longer satisfies bridge limits')
        s.require(owner_balance(asset['sol_mint']) >= amount, 'Purchased stock balance unavailable')
        if not live:
            return {'status':'BRIDGE_READY','asset':asset['symbol'],'stock_raw':amount}
        unsigned = build_bridge(amount,source,token,asset)
        source_ata = associated(asset['sol_mint'],TOKEN_2022)
        native = bridge.solana_rpc('getBalance',[s.WALLET,{'commitment':'confirmed'}])['value']
        balance = owner_balance(asset['sol_mint'])
        sim = bridge.solana_rpc('simulateTransaction',[base64.b64encode(bytes(unsigned)).decode(),
             {'encoding':'base64','sigVerify':False,'commitment':'confirmed',
              'accounts':{'encoding':'base64','addresses':[source_ata,s.WALLET]}}])['value']
        s.require(sim['err'] is None, 'Stock bridge simulation failed')
        after = s.token_balance(sim['accounts'][0],asset['sol_mint'],s.WALLET)
        s.require(balance-after == amount and 0 <= native-sim['accounts'][1]['lamports'] <= MAX_SOL_COST_LAMPORTS,
                  'Stock bridge simulation debit or cost mismatch')
        signed = VersionedTransaction(unsigned.message,[signer()])
        row.update(stage='bridge_pending',bridge_signature=str(signed.signatures[0]),
                   bridge_amount_raw=amount)
        write_attempt(asset,row)
        returned = bridge.solana_rpc('sendTransaction',[base64.b64encode(bytes(signed)).decode(),
                    {'encoding':'base64','skipPreflight':False,'preflightCommitment':'confirmed','maxRetries':0}])
        s.require(returned == row['bridge_signature'],'Bridge send signature mismatch; reservation retained')
        return {'status':'BRIDGE_PENDING','signature':returned}
    if row['stage'] == 'bridge_pending':
        status = bridge.solana_rpc('getSignatureStatuses',[[row['bridge_signature']],
                                   {'searchTransactionHistory':True}])['value'][0]
        if status is None or status.get('confirmationStatus') != 'finalized':
            return {'status':'BRIDGE_PENDING','signature':row['bridge_signature']}
        if status['err'] is not None:
            row['stage']='failed';write_attempt(asset,row)
            raise s.SellerError('Bridge source failed; journal preserved')
        try:
            result = bridge.api('/transactions/'+row['bridge_signature'])
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return {'status':'WAITING_FOR_X1_RECEIPT','signature':row['bridge_signature']}
            raise
        tx = result.get('transaction',result)
        if tx.get('status') not in ('executed','completed') or not tx.get('destTxSig'):
            return {'status':'WAITING_FOR_X1_RECEIPT','signature':row['bridge_signature']}
        receipt = s.rpc('getTransaction',[tx['destTxSig'],{'encoding':'json','commitment':'finalized',
                           'maxSupportedTransactionVersion':0}])
        if receipt is None:
            return {'status':'WAITING_FOR_X1_RECEIPT','signature':row['bridge_signature']}
        s.require(receipt['meta']['err'] is None and receipt['transaction']['signatures'][0]==tx['destTxSig'],
                  'X1 bridge receipt failed')
        def token_balance(field):
            return sum(int(a['uiTokenAmount']['amount']) for a in receipt['meta'].get(field,[])
                       if a.get('owner')==s.WALLET and a.get('mint')==asset['x1_mint'])
        minimum = row['bridge_amount_raw']*9975//10000
        s.require(token_balance('postTokenBalances')-token_balance('preTokenBalances')>=minimum,
                  'X1 stock receipt below bridge fee minimum')
        row.update(stage='completed',destination_signature=tx['destTxSig'])
        write_attempt(asset,row)
        return {'status':'COMPLETED','swap_signature':row['swap_signature'],
                'bridge_signature':row['bridge_signature'],'destination_signature':tx['destTxSig']}


@contextmanager
def process_lock():
    s.ensure_private_state_dir(LOCK.parent)
    with s.open_state_lock(LOCK) as stream:
        try:
            fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            raise s.SellerError('Another stock purchase/bridge command is running') from None
        yield


def main():
    parser=argparse.ArgumentParser(description='Buy a selected Solana stock and bridge it to X1')
    parser.add_argument('--stock',choices=tuple(ASSETS),default='googl',
                        help='Stock to purchase; default is googl.')
    parser.add_argument('--amount',default='11',help='USDC to spend, up to 6 decimal places; default 11')
    parser.add_argument('--new-purchase',action='store_true',
                        help='Start another purchase after the previous bridge completed')
    parser.add_argument('--live',action='store_true',help='Sign and send the bounded purchase and bridge')
    parser.add_argument('--watch',action='store_true',help='After a live submission, track finality and complete the bridge')
    args=parser.parse_args()
    if args.watch and not args.live:
        parser.error('--watch requires --live')
    amount_raw = parse_usdc_amount(args.amount)
    try:
        with process_lock():
            repeat = args.new_purchase
            while True:
                result = cycle(args.live,args.stock,spend_raw=amount_raw,repeat=repeat)
                repeat = False
                print(json.dumps(result,indent=2),flush=True)
                if not args.watch or result['status'] == 'COMPLETED':
                    return
                time.sleep(15)
    except s.SellerError as error:
        parser.exit(1, f'{error}\n')


if __name__=='__main__':
    main()
