"""Convert only verified approved-stock proceeds; preserve the pre-sale native reserve."""
import argparse
import fcntl
import json
import os
import time
from contextlib import contextmanager
from decimal import Decimal

from . import seller as s, spy_seller as spy, xnt_conversion as conversion
from . import native_swaps
from .spy_monitor import MINT
from .stock_policy import STOCKS

CACHE = s.ROOT/'state'/'auto-convert-receipts.json'
RUNTIME = s.ROOT/'state'/'auto-convert-runtime.json'
MAX_BATCH = 25_000_000_000
MIN_BATCH = 50_000_000


def receipt(row, kind):
    tx=s.rpc('getTransaction',[row['signature'],{'encoding':'json','commitment':'finalized',
                                               'maxSupportedTransactionVersion':0}])
    s.require(tx is not None and tx.get('meta') is not None,'Finalized receipt unavailable; conversion deferred')
    s.require(tx['transaction']['signatures'][0]==row['signature'],'Receipt signature mismatch')
    meta=tx['meta'];s.require(meta['err'] is None,'Receipt reports failed transaction')
    keys=tx['transaction']['message']['accountKeys']
    s.require(keys[0]==s.WALLET,'Unexpected receipt payer')
    before,after=meta['preBalances'][0],meta['postBalances'][0]
    s.require(type(before) is int and type(after) is int and before>=0 and after>=0,'Invalid native balances')
    mint=row.get('asset_mint',MINT) if kind=='sale' else s.USDC_MINT
    if kind=='sale':
        s.require(mint in {stock.mint for stock in STOCKS.values()},'Unauthorized stock receipt')
    def balance(field):
        rows=[r for r in meta[field] if r['owner']==s.WALLET and r['mint']==mint]
        s.require(all(r['uiTokenAmount']['decimals']==(8 if kind=='sale' else 6) for r in rows),
                  'Receipt token decimals mismatch')
        return sum(int(r['uiTokenAmount']['amount']) for r in rows)
    change=balance('postTokenBalances')-balance('preTokenBalances')
    if kind=='sale':
        s.require(change==-row['amount_raw'] and after>before,'Stock receipt debit or proceeds mismatch')
        net=after-before
        s.require(net+meta['fee']>=row['minimum_output_raw'],'Stock receipt below protected output')
        cost=0
    else:
        s.require(change>=row['minimum_output_raw'],'USDC.X receipt below protected output')
        cost=before-after-row['amount_raw']
        s.require(0<=cost<=s.COST_CEILING,'Conversion native debit exceeds allowance')
        net=0
    return {'kind':kind,'amount_raw':row['amount_raw'],'net_raw':net,'cost_raw':cost,
            'native_before':before,'slot':tx['slot'],'asset_mint':mint}


def load_cache():
    if not CACHE.exists():
        return {'wallet':s.WALLET,'receipts':{}}
    data=json.loads(CACHE.read_text())
    s.require(data['wallet']==s.WALLET and isinstance(data['receipts'],dict),'Invalid proceeds cache')
    return data


def accounting(sales, conversions, cache):
    receipts=cache['receipts']; changed=False
    for kind,rows in (('sale',sales['entries']),('conversion',conversions['entries'])):
        for row in rows:
            if row['status']!='finalized':
                continue
            key=row['signature']
            if key not in receipts:
                receipts[key]=receipt(row,kind);changed=True
            r=receipts[key]
            s.require(r['kind']==kind and r['amount_raw']==row['amount_raw']
                      and (kind!='sale' or r.get('asset_mint',MINT)==row.get('asset_mint',MINT)),'Receipt cache identity mismatch')
            s.require(all(type(r[k]) is int and r[k]>=0 for k in ('amount_raw','net_raw','cost_raw','native_before','slot')),
                      'Invalid receipt cache values')
    if changed:
        s.atomic_write(CACHE,cache)
    verified=[receipts[e['signature']] for e in sales['entries'] if e['status']=='finalized']
    proceeds=sum(r['net_raw'] for r in verified)
    # Pending and failed conversions remain reserved, including manual conversions.
    reserved=sum(e['amount_raw'] for e in conversions['entries'])
    costs=sum(receipts[e['signature']]['cost_raw'] if e['status']=='finalized' else s.COST_CEILING
              for e in conversions['entries'])
    floor=min(verified,key=lambda r:r['slot'])['native_before'] if verified else None
    return {'proceeds_raw':proceeds,'converted_reserved_raw':reserved,'conversion_cost_raw':costs,
            'available_raw':max(0,proceeds-reserved-costs),'reserve_raw':floor}


def planned_amount(ledger,snapshot):
    if ledger['reserve_raw'] is None:
        return 0
    amount=min(MAX_BATCH,ledger['available_raw']-s.COST_CEILING,
               snapshot['native_balance']-ledger['reserve_raw']-s.COST_CEILING,
               snapshot['native_balance']-snapshot['rent']-s.COST_CEILING-1_000_000)
    return amount if amount>=MIN_BATCH else 0


def cycle(live=False):
    try:
        with spy.native_lock():
            return locked_cycle(live)
    except spy.NativeSwapBusy:
        return {'status':'WAITING_FOR_NATIVE_SWAP'}


def locked_cycle(live=False):
    if not conversion.ready():
        return {'status':'WAITING_FOR_CONVERSION_FINALITY'}
    from . import spcx_seller, tsla_seller, meta_seller, coin_seller, pltr_seller, amd_seller, nvda_seller
    sales={'entries':[]}
    for key,module in (('spy',spy),('spcx',spcx_seller),('tsla',tsla_seller),('meta',meta_seller),('coin',coin_seller),('pltr',pltr_seller),('amd',amd_seller),('nvda',nvda_seller)):
        journal=module.read_journal()
        if not module.reconcile(journal):
            return {'status':'WAITING_FOR_STOCK_FINALITY'}
        sales['entries'].extend(dict(row,asset_mint=STOCKS[key].mint) for row in journal['entries'])
    conversions=conversion.read_journal()
    s.require(not any(e['status']=='failed' and e.get('source') in ('spy_proceeds_auto','stock_proceeds_auto')
                      for e in conversions['entries']),'Automatic conversion failed; review before restarting')
    ledger=accounting(sales,conversions,load_cache())
    report={'status':'WAITING_FOR_PROCEEDS',**ledger}
    if ledger['available_raw']<MIN_BATCH+s.COST_CEILING:
        return report
    snap=native_swaps.xnt_snapshot()
    amount=planned_amount(ledger,snap)
    if not amount:
        return dict(report,status='KEEPING_XNT_RESERVE')
    output,minimum=native_swaps.xnt_quote(snap,amount)
    q={'amount_raw':amount,'minimum_raw':minimum,'expires_at':time.time()+30}
    report.update(amount_xnt=str(Decimal(amount)/10**9),minimum_usdc=str(Decimal(minimum)/10**6))
    if not live:
        _,_,_,received=native_swaps.simulate(snap,amount,minimum)
        return dict(report,status='SIMULATION_PASSED',simulated_usdc=str(Decimal(received)/10**6))
    result=conversion.execute_locked(q,source='stock_proceeds_auto',native_floor=ledger['reserve_raw'])
    return dict(report,status='SUBMITTED_PENDING_FINALITY',signature=result['signature'])


@contextmanager
def process_lock():
    path=s.ROOT/'state'/'auto-convert.lock';s.ensure_private_state_dir(path.parent)
    with s.open_state_lock(path) as stream:
        try:
            fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            raise s.SellerError('Automatic conversion is already running') from None
        yield


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true');parser.add_argument('--watch',action='store_true')
    args=parser.parse_args()
    try:
        with process_lock():
            while True:
                report=cycle(args.live)
                s.atomic_write(RUNTIME,dict(report,pid=os.getpid(),mode='live' if args.live else 'simulation',updated_at=time.time()))
                print(json.dumps(report),flush=True)
                if not args.watch:return 0
                time.sleep(15)
    except KeyboardInterrupt:
        return 0
    except Exception as error:
        message=str(error) if isinstance(error,s.SellerError) else 'Data or network error; no automatic retry'
        s.atomic_write(RUNTIME,{'status':'STOPPED_ERROR','message':message,'pid':os.getpid(),
                               'mode':'live' if args.live else 'simulation','updated_at':time.time()})
        print(message,flush=True)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
