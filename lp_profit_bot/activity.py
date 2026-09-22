"""Bounded public activity feed from worker status and transaction journals."""
from . import meta_seller, coin_seller, pltr_seller, amd_seller, nvda_seller
from collections import deque
from datetime import datetime, timezone
from decimal import Decimal
import threading
import time
from . import seller, spy_seller, spcx_seller, tsla_seller, xnt_conversion, worker_control
from . import auto_bridge

MESSAGES = {
    'CHECKING': 'Checking prices, balances, and sale requirements.',
    'HOLD': 'Holding: no qualifying sale after costs and price protection, or no inventory.',
    'WAITING_FOR_PROCEEDS': 'Waiting: no eligible stock sale proceeds to convert.',
    'WAITING_FOR_REFERENCE': 'Reference provider unavailable; retrying in 60 seconds.',
    'KEEPING_XNT_RESERVE': 'Waiting: preserving the XNT reserve.',
    'WAITING_FOR_NATIVE_SWAP': 'Waiting for another swap to finish.',
    'WAITING_FOR_XNT_CONVERSION': 'Waiting for XNT conversion finality.',
    'WAITING_FOR_CONVERSION_FINALITY': 'Waiting for conversion finality.',
    'WAITING_FOR_STOCK_FINALITY': 'Waiting for stock sale finality.',
    'WAITING_FOR_BRIDGE_FINALITY': 'Waiting for X1 and Solana bridge finality.',
    'RETRYING_BRIDGE_API': 'Bridge API unavailable; retrying in 30 seconds.',
    'WAITING_FOR_SPY_FINALITY': 'Waiting for SPY.X sale finality.',
    'WAITING_FOR_FINALITY': 'Waiting for transaction finality; no duplicate submission.',
    'SUBMITTED_PENDING_FINALITY': 'Transaction submitted; awaiting chain confirmation.',
    'SIMULATION_PASSED': 'Unsigned simulation passed. This is not a completed trade.',
    'STOPPED_ERROR': 'Worker stopped after an error. Check its status before restarting.',
    'CAP_REACHED': 'Previous seller version reached its lifetime cap.',
}


class ActivityFeed:
    def __init__(self):
        self.lock=threading.Lock()
        self.events=deque(maxlen=250)
        self.sequence=0
        self.seen={}
        self.checked_at=None

    def add(self,source,message,level='info',signature=None,stamp=None):
        with self.lock:
            self.sequence+=1
            self.events.append({'id':self.sequence,'at':stamp if stamp is not None else time.time(),
                                'source':source,'message':message,'level':level,'signature':signature})

    def snapshot(self):
        with self.lock:
            return {'events':list(self.events),'checked_at':self.checked_at}

    def poll(self,stop):
        while not stop.is_set():
            try:
                self.refresh()
            except Exception:
                # Never expose raw exceptions, RPC bodies, or credentials.
                if not self.seen.get('feed_error'):
                    self.add('system','Activity refresh unavailable; displayed entries may be stale.','warn')
                self.seen['feed_error']=True
            stop.wait(5)

    def refresh(self):
        collected=[]
        for source,reader,scale,unit,out_scale,out_unit in (
            ('googl',seller.read_journal,10**8,'GOOGL.X',10**6,'USDC.X'),
            ('spy',spy_seller.read_journal,10**8,'SPY.X',10**9,'XNT'),
            ('spcx',spcx_seller.read_journal,10**8,'SPCX.X',10**9,'XNT'),
            ('tsla',tsla_seller.read_journal,10**8,'TSLA.X',10**9,'XNT'),
            ('meta',meta_seller.read_journal,10**8,'META.X',10**9,'XNT'),
            ('coin',coin_seller.read_journal,10**8,'COIN.X',10**9,'XNT'),
            ('pltr',pltr_seller.read_journal,10**8,'PLTR.X',10**9,'XNT'),
            ('amd',amd_seller.read_journal,10**8,'AMD.X',10**9,'XNT'),
            ('nvda',nvda_seller.read_journal,10**8,'NVDA.X',10**9,'XNT'),
            ('conversion',xnt_conversion.read_journal,10**9,'XNT',10**6,'USDC.X')):
            try:
                rows=reader()['entries'][-100:]
            except Exception:
                if not self.seen.get(source+'_error'):
                    self.add(source,'Transaction journal unavailable; confirmation status unknown.','warn')
                self.seen[source+'_error']=True
                continue
            self.seen[source+'_error']=False
            pending=[r for r in rows if r['status']=='pending' and self.seen.get(('tx',r['signature'])) not in ('finalized','failed')]
            chain={}
            if pending:
                try:
                    values=seller.rpc('getSignatureStatuses',[[r['signature'] for r in pending],{'searchTransactionHistory':True}])['value']
                    chain=dict(zip((r['signature'] for r in pending),values))
                    self.seen[source+'_rpc_error']=False
                except Exception:
                    if not self.seen.get(source+'_rpc_error'):
                        self.add(source,'Chain confirmation check unavailable; pending transactions remain unconfirmed.','warn')
                    self.seen[source+'_rpc_error']=True
            for row in rows:
                signature=row['signature'];key=('tx',signature);previous=self.seen.get(key)
                status=row['status']
                if previous in ('finalized','failed'):
                    continue
                chain_status=chain.get(signature)
                if chain_status and chain_status.get('confirmationStatus')=='finalized':
                    status='failed' if chain_status.get('err') is not None else 'finalized'
                elif chain_status and chain_status.get('confirmationStatus')=='confirmed':
                    status='confirmed' if chain_status.get('err') is None else 'pending'
                if previous==status:
                    continue
                self.seen[key]=status
                amount=str(Decimal(row['amount_raw'])/scale)
                if status=='finalized':
                    message=f'FINALIZED · {amount} {unit} → {out_unit}. Transaction completed on-chain.'
                elif status=='failed':
                    message=f'FAILED · {amount} {unit} transaction failed on-chain. Reservation preserved.'
                elif status=='confirmed':
                    message=f'CONFIRMED · {amount} {unit} → {out_unit}. Waiting for finality.'
                else:
                    message=f'PENDING · {amount} {unit} → {out_unit}. Not finalized; no duplicate will be sent.'
                if row.get('minimum_output_raw') is not None:
                    message+=f" Protected minimum {Decimal(row['minimum_output_raw'])/out_scale} {out_unit} (not actual proceeds)."
                stamp=time.time()
                if previous is None:
                    try:
                        created=row['created_at']
                        stamp=float(created) if isinstance(created,(int,float)) else datetime.fromisoformat(created).timestamp()
                    except (KeyError,TypeError,ValueError):
                        pass
                collected.append((stamp,source,message,'good' if status=='finalized' else 'bad' if status=='failed' else 'warn',signature))
        for stamp,source,message,level,signature in sorted(collected):
            self.add(source,message,level,signature,stamp)
        try:
            bridge_rows = auto_bridge.read_journal()['entries'][-100:]
            for row in bridge_rows:
                key = ('bridge', row['signature'])
                status = row['status']
                if self.seen.get(key) == status:
                    continue
                self.seen[key] = status
                amount = Decimal(row['amount_raw']) / 10**6
                message = {
                    'pending_x1': f'PENDING · {amount} USDC.X sent to Warp Bridge; awaiting X1 finality.',
                    'pending_solana': f'X1 FINALIZED · {amount} USDC.X; awaiting Solana USDC receipt.',
                    'completed': f'COMPLETED · {amount} USDC.X bridged to Solana. See bridge history for the destination transaction.',
                    'failed': f'FAILED · {amount} USDC.X bridge source transaction failed; reservation preserved.',
                }[status]
                stamp = row.get('created_at') if status == 'pending_x1' else None
                self.add('bridge', message, 'good' if status == 'completed' else
                         'bad' if status == 'failed' else 'warn', row['signature'], stamp)
        except Exception:
            if not self.seen.get('bridge_error'):
                self.add('bridge', 'Bridge journal unavailable; transfer status unknown.', 'warn')
            self.seen['bridge_error'] = True
        else:
            self.seen['bridge_error'] = False
        for source,worker in worker_control.status().items():
            key=('worker',source)
            state=(worker['running'],worker.get('activity'),worker.get('updated_at'))
            if self.seen.get(key)==state:
                continue
            self.seen[key]=state
            if worker['running'] is False:
                message='STOPPED · No worker running.'
            elif worker['running'] is None:
                message='UNKNOWN · Cannot determine worker status.'
            else:
                message=('LIVE · ' if worker['mode']=='live' else 'SIMULATION · ' if worker['mode']=='simulation' else 'RUNNING · ')
                message+=MESSAGES.get(worker['activity'],'Worker active; waiting for an activity update.')
            self.add(source,message,'warn' if worker['running'] is None else 'info')
        if self.seen.pop('feed_error',False):
            self.add('system','Activity updates restored.')
        with self.lock:
            self.checked_at=time.time()
