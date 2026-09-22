"""Read-only actual proceeds, verified from finalized transaction receipts."""
from . import meta_seller, coin_seller, pltr_seller, amd_seller, nvda_seller
import json
import threading
import time
from decimal import Decimal
from . import seller,spy_seller,spcx_seller,tsla_seller,xnt_conversion
from .stock_policy import STOCKS


def units(raw,decimals):
    return str(Decimal(raw)/10**decimals)


def decode(tx,row,asset,mint):
    seller.require(tx and tx.get('meta') is not None,'Receipt unavailable')
    seller.require(tx['transaction']['signatures'][0]==row['signature'],'Receipt signature mismatch')
    message=tx['transaction']['message'];meta=tx['meta']
    seller.require(message['accountKeys'][0]==seller.WALLET,'Unexpected transaction payer')
    fee=meta['fee'];before=meta['preBalances'][0];after=meta['postBalances'][0]
    seller.require(all(type(v) is int and v>=0 for v in (fee,before,after)),'Invalid receipt balances')
    def balance(field,token,decimals):
        values=[r for r in meta.get(field,[]) if r.get('owner')==seller.WALLET and r['mint']==token]
        seller.require(all(r['uiTokenAmount']['decimals']==decimals for r in values),'Unexpected token decimals')
        return sum(int(r['uiTokenAmount']['amount']) for r in values)
    usdc=balance('postTokenBalances',seller.USDC_MINT,6)-balance('preTokenBalances',seller.USDC_MINT,6)
    failed=meta['err'] is not None
    is_conversion=asset=='XNT'
    input_raw=row['amount_raw'] if is_conversion else balance('preTokenBalances',mint,8)-balance('postTokenBalances',mint,8)
    if failed:
        seller.require(usdc==0 and (is_conversion or input_raw==0),'Unexpected failed transaction changes')
        input_raw=0;net_xnt=0;usdc=0;other_cost=before-after-fee
    elif is_conversion:
        seller.require(usdc>=row['minimum_output_raw'],'Conversion output below protected minimum')
        net_xnt=0;other_cost=before-after-input_raw-fee
    elif asset=='GOOGL.X':
        seller.require(input_raw==row['amount_raw'] and usdc>=row['minimum_output_raw'],'Stock sale receipt mismatch')
        net_xnt=0;other_cost=before-after-fee
    else:
        net_xnt=after-before
        seller.require(input_raw==row['amount_raw'] and net_xnt+fee>=row['minimum_output_raw'] and usdc==0,
                       'Stock sale receipt mismatch')
        other_cost=0
    seller.require(other_cost>=0,'Unexpected native balance change')
    return {'signature':row['signature'],'asset':asset,'status':'failed' if failed else 'finalized',
            'at':tx.get('blockTime') or row.get('created_at'),'actual_input':units(input_raw,9 if is_conversion else 8),
            'net_xnt_received':units(net_xnt,9),'usdc_received':units(usdc,6),
            'network_fee_xnt':units(fee,9),'other_cost_xnt':units(other_cost,9),
            'kind':'conversion' if is_conversion else 'sale',
            'source':'automatic' if row.get('source') in ('spy_proceeds_auto','stock_proceeds_auto') else 'manual' if is_conversion else 'stock seller'}


class ProceedsHistory:
    def __init__(self):
        self.lock=threading.Lock();self.cache={};self.rows=[];self.updated_at=None;self.errors=[]
        self.path=seller.ROOT/'state'/'proceeds-history.json'
        try:
            data=seller.read_state_json(self.path)
            if data.get('wallet')==seller.WALLET and data.get('version')==1:
                self.cache=data['receipts']
        except (OSError,ValueError,TypeError,KeyError):
            pass

    def snapshot(self):
        with self.lock:
            return {'rows':list(self.rows),'updated_at':self.updated_at,'errors':list(self.errors)}

    def poll(self,stop):
        while not stop.is_set():
            try:self.refresh()
            except Exception:
                with self.lock:self.errors=['Proceeds refresh unavailable; previous receipts remain visible.']
            stop.wait(30)

    def refresh(self):
        rows=[];errors=[];changed=False
        sources=[('GOOGL.X',seller.GOOGL_MINT,seller.read_journal),
                 ('SPY.X',STOCKS['spy'].mint,spy_seller.read_journal),
                 ('SPCX.X',STOCKS['spcx'].mint,spcx_seller.read_journal),
                 ('TSLA.X',STOCKS['tsla'].mint,tsla_seller.read_journal),
                 ('META.X',STOCKS['meta'].mint,meta_seller.read_journal),
                 ('COIN.X',STOCKS['coin'].mint,coin_seller.read_journal),
                 ('PLTR.X',STOCKS['pltr'].mint,pltr_seller.read_journal),
                 ('AMD.X',STOCKS['amd'].mint,amd_seller.read_journal),
                 ('NVDA.X',STOCKS['nvda'].mint,nvda_seller.read_journal),
                 ('XNT',seller.WXNT,xnt_conversion.read_journal)]
        for asset,mint,reader in sources:
            try:entries=reader()['entries']
            except Exception:
                errors.append(asset+' journal unavailable.');continue
            for row in entries:
                signature=row['signature']
                result=self.cache.get(signature)
                if result and (result.get('signature')!=signature or result.get('asset')!=asset):
                    result=None
                if result is None:
                    try:
                        tx=seller.rpc('getTransaction',[signature,{'encoding':'json','commitment':'finalized','maxSupportedTransactionVersion':0}])
                        if tx:
                            result=decode(tx,row,asset,mint);self.cache[signature]=result;changed=True
                    except Exception:
                        errors.append(asset+' receipt could not be verified.')
                if result is None:
                    result={'signature':signature,'asset':asset,'status':'pending' if row['status']=='pending' else 'receipt unavailable',
                            'at':row.get('created_at'),'kind':'conversion' if asset=='XNT' else 'sale',
                            'source':'automatic' if row.get('source') in ('spy_proceeds_auto','stock_proceeds_auto') else 'manual' if asset=='XNT' else 'stock seller'}
                rows.append(result)
        if changed:seller.atomic_write(self.path,{'version':1,'wallet':seller.WALLET,'receipts':self.cache})
        with self.lock:
            self.rows=rows;self.updated_at=time.time();self.errors=list(dict.fromkeys(errors))
