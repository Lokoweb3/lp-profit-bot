"""Local XDEX transactions with a temporary wrapped-native account."""
import base64
import hashlib
import struct
import time
from decimal import Decimal
from solders.pubkey import Pubkey
from solders.hash import Hash
from solders.signature import Signature
from solders.instruction import Instruction, AccountMeta
from solders.message import MessageV0, to_bytes_versioned
from solders.transaction import VersionedTransaction
from solders.compute_budget import set_compute_unit_limit, set_compute_unit_price
from solders.system_program import create_account_with_seed
from . import seller as s
from .spy_quotes import LEGACY_TOKEN

SEED = 'x1-native-swap-v1'


def temporary_account():
    return str(Pubkey.create_with_seed(Pubkey.from_string(s.WALLET), SEED, Pubkey.from_string(LEGACY_TOKEN)))


def build(snapshot, amount, minimum, blockhash, *, sell_spy=False):
    from .spy_monitor import MINT, POOL
    MINT = snapshot.get('sell_mint', MINT)
    POOL = snapshot.get('sell_pool', POOL)
    if sell_spy:
        from .stock_policy import STOCKS
        s.require(any(stock.mint == MINT and stock.pool == POOL for stock in STOCKS.values()), 'Stock route is not authorized')
    pub = Pubkey.from_string
    pool = snapshot['pool']
    mint_in, mint_out = (MINT, s.WXNT) if sell_spy else (s.WXNT, s.USDC_MINT)
    program_in, program_out = (s.TOKEN, LEGACY_TOKEN) if sell_spy else (LEGACY_TOKEN, s.TOKEN)
    j = pool['mints'].index(mint_in)
    temp = temporary_account()
    source = s.associated(MINT) if sell_spy else temp
    target = temp if sell_spy else s.associated(s.USDC_MINT)
    s.require(type(amount) is int and amount > 0 and type(minimum) is int and minimum > 0, 'Invalid swap bounds')
    rent = snapshot['rent']
    instructions = [set_compute_unit_limit(250_000), set_compute_unit_price(10_000),
        create_account_with_seed({'from_pubkey': pub(s.WALLET), 'to_pubkey': pub(temp),
          'base': pub(s.WALLET), 'seed': SEED, 'lamports': rent + (0 if sell_spy else amount),
          'space': 165, 'owner': pub(LEGACY_TOKEN)}),
        Instruction(pub(LEGACY_TOKEN), b'\x12'+bytes(pub(s.WALLET)),
                    [AccountMeta(pub(temp), False, True), AccountMeta(pub(s.WXNT), False, False)])]
    if not sell_spy:
        instructions.append(Instruction(pub(s.ATA), b'\x01', [
            AccountMeta(pub(s.WALLET), True, True), AccountMeta(pub(target), False, True),
            AccountMeta(pub(s.WALLET), False, False), AccountMeta(pub(s.USDC_MINT), False, False),
            AccountMeta(pub('11111111111111111111111111111111'), False, False),
            AccountMeta(pub(s.TOKEN), False, False)]))
    keys = [s.WALLET, s.AUTHORITY, s.CONFIG, POOL if sell_spy else s.XNT_POOL, source, target,
            pool['vaults'][j], pool['vaults'][1-j], program_in, program_out, mint_in, mint_out, pool['observation']]
    instructions.append(Instruction(pub(s.XDEX_PROGRAM), s.SWAP_BASE_INPUT+struct.pack('<QQ', amount, minimum),
        [AccountMeta(pub(key), i == 0, i in (0,3,4,5,6,7,12)) for i,key in enumerate(keys)]))
    # Close only our temporary account; proceeds and rent return to the same wallet.
    instructions.append(Instruction(pub(LEGACY_TOKEN), b'\x09', [
        AccountMeta(pub(temp), False, True), AccountMeta(pub(s.WALLET), False, True),
        AccountMeta(pub(s.WALLET), True, False)]))
    message = MessageV0.try_compile(pub(s.WALLET), instructions, [], Hash.from_string(blockhash))
    return VersionedTransaction.populate(message, [Signature.default()])


def prepare(snapshot):
    a = s.accounts([temporary_account()], snapshot['slot'])['value'][0]
    s.require(a is None, 'Temporary native account already exists; inspect before retrying')
    snapshot['rent'] = s.rpc('getMinimumBalanceForRentExemption', [165])
    s.require(type(snapshot['rent']) is int and 0 < snapshot['rent'] <= s.COST_CEILING, 'Unexpected native account rent')
    return snapshot


def simulate(snapshot, amount, minimum, *, sell_spy=False):
    from .spy_monitor import MINT
    MINT = snapshot.get('sell_mint', MINT)
    block = s.rpc('getLatestBlockhash', [{'commitment':'confirmed', 'minContextSlot':snapshot['slot']}])['value']
    unsigned = build(snapshot, amount, minimum, block['blockhash'], sell_spy=sell_spy)
    fee = s.rpc('getFeeForMessage', [base64.b64encode(to_bytes_versioned(unsigned.message)).decode(), {'commitment':'confirmed'}])['value']
    s.require(type(fee) is int and 0 <= fee <= s.COST_CEILING, 'Invalid/excessive transaction fee')
    token = s.associated(MINT if sell_spy else s.USDC_MINT)
    sim = s.rpc('simulateTransaction', [s.encoded(unsigned), {'encoding':'base64', 'sigVerify':False,
        'commitment':'confirmed', 'minContextSlot':snapshot['slot'],
        'accounts':{'encoding':'base64', 'addresses':[token, s.WALLET, temporary_account()]}}])
    result = sim['value']
    s.require(result.get('err') is None, 'Native swap simulation failed')
    a = result.get('accounts')
    s.require(isinstance(a,list) and len(a)==3 and a[1] is not None
              and (a[2] is None or (a[2].get('lamports')==0
                   and a[2].get('owner')=='11111111111111111111111111111111'
                   and a[2].get('data', [''])[0]=='')),
              'Simulation account or native account closure mismatch')
    s.require(a[1]['owner']=='11111111111111111111111111111111', 'Payer owner changed')
    if sell_spy:
        after = s.token_balance(a[0], MINT, s.WALLET)
        s.require(snapshot['balance_in']-after == amount, 'SPY.X debit mismatch')
        received = a[1]['lamports']-snapshot['native_balance']
        s.require(received >= minimum-fee, 'Native proceeds below protected minimum after fee')
    else:
        after = s.token_balance(a[0], s.USDC_MINT, s.WALLET)
        received = after-snapshot['balance_out']
        debit = snapshot['native_balance']-a[1]['lamports']
        s.require(received >= minimum, 'USDC.X proceeds below protected minimum')
        s.require(amount <= debit <= amount+s.COST_CEILING and debit-amount+fee <= s.COST_CEILING,
                  'Native debit or fees exceed bounds')
    s.require(time.monotonic()-snapshot['received'] <= 30, 'Swap snapshot expired')
    return unsigned, block, sim['context']['slot'], received


def xnt_snapshot():
    first = s.accounts([s.XNT_POOL])
    old = s.decode_pool(first['value'][0])
    response = s.accounts([s.XNT_POOL, s.CONFIG, *old['vaults'], s.WALLET,
                           s.associated(s.USDC_MINT), s.USDC_MINT], first['context']['slot'])
    a = response['value']; pool = s.decode_pool(a[0])
    s.require(pool['vaults']==old['vaults'] and pool['config']==s.CONFIG
              and set(pool['mints'])=={s.WXNT,s.USDC_MINT}, 'Unexpected XNT pool')
    j = pool['mints'].index(s.WXNT)
    s.require(pool['programs'][j]==LEGACY_TOKEN and pool['programs'][1-j]==s.TOKEN
              and pool['decimals'][j]==9 and pool['decimals'][1-j]==6, 'Unexpected token programs/decimals')
    s.check_mint(a[6],6)
    raw = s.raw_account(a[1],s.XDEX_PROGRAM)
    s.require(len(raw)==236 and raw[:8]==hashlib.sha256(b'account:AmmConfig').digest()[:8], 'Invalid fee configuration')
    trade = struct.unpack_from('<Q',raw,12)[0]
    s.require(trade<1_000_000,'Invalid pool fee')
    reserves = [s.token_balance(a[2+i],pool['mints'][i],s.AUTHORITY,pool['programs'][i])
                -pool['protocol_fees'][i]-pool['fund_fees'][i] for i in range(2)]
    s.require(all(v>0 for v in reserves), 'Invalid pool reserves')
    s.require(a[4] and a[4]['owner']=='11111111111111111111111111111111','Invalid payer')
    return prepare({'pool':pool,'reserve_in':reserves[j],'reserve_out':reserves[1-j], 'trade_fee':trade,
                    'native_balance':a[4]['lamports'], 'balance_out':s.token_balance(a[5],s.USDC_MINT,s.WALLET),
                    'slot':response['context']['slot'],'received':time.monotonic()})


def xnt_quote(snapshot, amount):
    s.require(type(amount) is int and amount>0 and amount+snapshot['rent']+s.COST_CEILING+1_000_000 <= snapshot['native_balance'],
              'Amount exceeds spendable XNT; keep a fee and rent reserve')
    net = amount-(amount*snapshot['trade_fee']+999_999)//1_000_000
    output = net*snapshot['reserve_out']//(snapshot['reserve_in']+net)
    minimum = output*995//1000
    s.require(minimum>0,'Amount is too small')
    return output, minimum
