const $ = id => document.getElementById(id);
const fmt = (n, digits=4) => n == null ? '—' : Number(n).toLocaleString(undefined,{maximumFractionDigits:digits});
const money = n => n == null ? '—' : '$'+Number(n).toFixed(2);
function balanceEstimate(balance,price,fresh){
  if(!fresh||balance==null||price==null)return null;
  const amount=Number(balance),spot=Number(price);
  return Number.isFinite(amount)&&amount>=0&&Number.isFinite(spot)&&spot>0?amount*spot:null;
}
function showBalanceEstimate(id,balance,price,fresh,symbol,basis='X1 spot'){
  const estimate=balanceEstimate(balance,price,fresh),el=$(id);
  el.textContent=estimate==null?'Estimated value: —':'Estimated value: '+money(estimate);
  el.title=estimate==null?'Requires a current balance and X1 spot price':`${balance} ${symbol} × ${price} USD at ${basis}; estimate only, not an executable quote`;
}
const age = (stamp, now) => stamp == null ? 'unknown' : Math.max(0,Math.floor(now-stamp))+'s ago';
const short = value => value.slice(0,7)+'…'+value.slice(-6);
let wallet = '';
const stockStarting=new Set();
let sessionReady = false, starting = false, spyStarting = false, stopBusy = false, autoStarting = false;
function badge(id,text,tone='') { $(id).textContent=text; $(id).className='badge '+tone; }
function liveValue(id,value){const el=$(id),previous=el.textContent;if(previous!==value){el.textContent=value;if(previous!=='—'&&previous!==''){el.classList.remove('value-updated');void el.offsetWidth;el.classList.add('value-updated');}}}
let chartRange='3600', lastHistory=[];
function draw(history) {
  lastHistory=history||[];
  const valid=lastHistory.filter(p=>Number.isFinite(p.at)&&Number.isFinite(p.pool)&&Number.isFinite(p.reference)).sort((a,b)=>a.at-b.at);
  const latest=valid.at(-1)?.at;
  const points=chartRange==='all'?valid:valid.filter(p=>p.at>=latest-Number(chartRange));
  $('chart-from').textContent=points.length?new Date(points[0].at*1000).toLocaleTimeString():'—';
  $('chart-to').textContent=points.length?new Date(points.at(-1).at*1000).toLocaleTimeString():'—';
  $('chart-empty').hidden=points.length>1;
  $('chart-empty').textContent=valid.length?'Only one recorded observation in this range.':'Waiting for recorded spot prices…';
  if(points.length<2){for(const id of ['pool-line','reference-line'])$(id).setAttribute('points','');return;}
  const all=points.flatMap(p=>[p.pool,p.reference]);
  const lo=Math.min(...all), hi=Math.max(...all), pad=Math.max((hi-lo)*.2,.1), span=hi-lo+2*pad;
  const start=points[0].at, duration=points.at(-1).at-start || 1;
  for(const [id,key] of [['pool-line','pool'],['reference-line','reference']]) {
    $(id).setAttribute('points',points.map(p=>`${(p.at-start)/duration*700},${135-(p[key]-lo+pad)/span*120}`).join(' '));
  }
}
for(const button of document.querySelectorAll('.range-button'))button.addEventListener('click',()=>{chartRange=button.dataset.range;for(const b of document.querySelectorAll('.range-button'))b.setAttribute('aria-pressed',String(b===button));draw(lastHistory);});
function render(data) {
  renderTerminal(data.activity, data.now);
  renderTimeline(data.activity,data.now,data.auto_bridge);
  renderProceeds(data.proceeds,data.now);
  renderBridge(data.auto_bridge);
  renderStockPurchase(data.stock_purchase);
  renderOverview(data);
  renderRecent(data);
  renderPreview(data);
  const workers=data.workers || {};
  const saleKeys=['googl','spy','spcx','tsla','meta','coin','pltr','amd','nvda'];
  const active=saleKeys.filter(key=>workers[key]?.running===true&&workers[key]?.mode==='live').length;
  liveValue('active-strategies',String(active));
  $('strategy-count-note').textContent=active+' of '+saleKeys.length+' sale scripts live'+(saleKeys.some(key=>workers[key]?.running===true&&workers[key]?.mode==='simulation')?' · simulation also running':'')+(saleKeys.some(key=>workers[key]?.running==null)?' · some status unknown':'');
  badge('rail-automation-status',active+' live sale strateg'+(active===1?'y':'ies'),active?'good':'warn');
  const descriptions={WAITING_FOR_REFERENCE:'Reference provider unavailable; retrying in 60 seconds',HOLD:'Waiting for a sale above the reference after costs',CHECKING:'Checking prices and balances',WAITING_FOR_PROCEEDS:'Waiting for eligible stock sale proceeds',KEEPING_XNT_RESERVE:'Waiting to preserve the XNT fee reserve',WAITING_FOR_FINALITY:'Waiting for transaction confirmation',WAITING_FOR_CONVERSION_FINALITY:'Waiting for conversion confirmation',WAITING_FOR_BRIDGE_FINALITY:'Waiting for X1 and Solana bridge confirmation',RETRYING_BRIDGE_API:'Bridge API unavailable; retrying in 30 seconds',WAITING_FOR_SPY_FINALITY:'Waiting for SPY.X sale confirmation',SUBMITTED_PENDING_FINALITY:'Transaction submitted; awaiting confirmation',WAITING_FOR_NATIVE_SWAP:'Waiting for another swap',WAITING_FOR_XNT_CONVERSION:'Waiting for XNT conversion'};
  for(const key of ['googl','spy','spcx','tsla','conversion','bridge','meta','coin','pltr','amd','nvda']){
    const worker=workers[key];const running=worker?.running;
    badge('worker-'+key+'-badge',running===true?'Running':running===false?'Stopped':'Unknown',running===true?'good':running===false?'':'warn');
    const stoppedReason='No script running';
    $('worker-'+key+'-detail').textContent=running===true?(worker.mode==='live'?'Live · ':worker.mode==='simulation'?'Simulation · ':'')+(descriptions[worker.activity] || 'Script active; waiting for activity update'):running===false?stoppedReason:'Cannot determine process status';
    $('stop-'+key).disabled=stopBusy || !sessionReady || running===false;
  }
  $('stop-all').disabled=stopBusy || !sessionReady || ['googl','spy','spcx','tsla','conversion','bridge','meta','coin','pltr','amd','nvda'].every(key=>workers[key]?.running===false);

  const auto=data.auto_conversion;
  $('start-auto-convert').disabled=autoStarting || !sessionReady || !auto || auto.running!==false;
  $('start-auto-convert').textContent=autoStarting?'Starting conversion…':auto?.running?'Automatic conversion running':'Start automatic conversion';
  const autoLive=auto?.running && auto.mode==='live';
  badge('auto-convert-badge',autoLive?'Auto conversion active':auto?.running?'Simulation only':'Auto conversion stopped',autoLive?'good':'warn');
  $('auto-convert-detail').textContent=auto ? (auto.status?.replaceAll('_',' ').toLowerCase() || 'Waiting for status')+(auto.reserve_raw!=null?' · protected reserve '+fmt(auto.reserve_raw/1e9,9)+' XNT':'')+(auto.available_raw!=null?' · unconverted proceeds '+fmt(auto.available_raw/1e9,9)+' XNT':'')+(auto.message?' · '+auto.message:'') : 'Automatic conversion status unavailable';
  const conversions=data.xnt_conversions;
  $('xnt-history').replaceChildren();
  if(conversions?.length){
    const latest=conversions[0];$('xnt-history').textContent='Latest conversion: '+fmt(latest.amount_raw/1e9,9)+' XNT · '+latest.status+' · ';
    const a=document.createElement('a');a.href='https://explorer.mainnet.x1.xyz/tx/'+encodeURIComponent(latest.signature);a.target='_blank';a.rel='noopener noreferrer';a.textContent='View transaction';$('xnt-history').append(a);
  }else if(conversions===null){$('xnt-history').textContent='Conversion history unavailable.';}
  const ss=data.spy_seller;
  $('start-spy-seller').disabled=spyStarting || !sessionReady || !ss || ss.running!==false || ss.halted;
  $('start-spy-seller').textContent=spyStarting?'Starting SPY.X seller…':ss?.running?'SPY.X → XNT · Running':ss?.halted?'SPY.X seller halted':'Sell SPY.X → XNT';
  $('spy-seller-state').textContent=ss ? 'SPY.X seller '+(ss.halted?'halted':ss.running?'running':'stopped')+' · confirmed sold '+fmt(ss.confirmed,8)+' · no sale amount caps'+(ss.status?' · '+ss.status.replaceAll('_',' ').toLowerCase():'') : 'SPY.X seller status unavailable';
  for(const [key,symbol] of [['spcx','SPCX.X'],['tsla','TSLA.X'],['meta','META.X'],['coin','COIN.X'],['pltr','PLTR.X'],['amd','AMD.X'],['nvda','NVDA.X']]){
    const worker=data[key+'_seller'];
    $('start-'+key+'-seller').disabled=stockStarting.has(key)||!sessionReady||!worker||worker.running!==false||worker.halted;
    $('start-'+key+'-seller').textContent=stockStarting.has(key)?'Starting…':worker?.running?symbol+' → XNT · Running':worker?.halted?symbol+' seller halted':'Sell '+symbol+' → XNT';
    $(key+'-seller-state').textContent=worker?(worker.running?'Running':'Stopped')+' · confirmed sold '+fmt(worker.confirmed,8)+' · no amount caps'+(worker.status?' · '+worker.status.replaceAll('_',' ').toLowerCase():''):'Seller status unavailable';
  }
  const spcx=data.spcx;
  $('spcx-price').textContent=money(spcx?.price_usd);
  $('spcx-reference').textContent=money(spcx?.reference_price);
  $('spcx-balance').textContent=fmt(spcx?.balance,8);
  $('spcx-gap').textContent=spcx?.gap_percent==null?'—':(Number(spcx.gap_percent)>=0?'+':'')+Number(spcx.gap_percent).toFixed(2)+'%';
  badge('spcx-status',spcx?.fresh?'Fresh data':data.spcx_error?'Unavailable / stale':'Waiting / stale',spcx?.fresh?'good':'warn');
  $('spcx-detail').textContent=data.spcx_error || (spcx?'Pool liquidity '+money(spcx.liquidity_usd)+' · checked '+age(spcx.fetched_at,data.now):'Loading SPCX.X market and wallet data…');
  const tsla=data.tsla;
  $('tsla-price').textContent=money(tsla?.price_usd);
  $('tsla-reference').textContent=money(tsla?.reference_price);
  $('tsla-balance').textContent=fmt(tsla?.balance,8);
  $('tsla-gap').textContent=tsla?.gap_percent==null?'—':(Number(tsla.gap_percent)>=0?'+':'')+Number(tsla.gap_percent).toFixed(2)+'%';
  badge('tsla-status',tsla?.fresh?'Fresh data':data.tsla_error?'Unavailable / stale':'Waiting / stale',tsla?.fresh?'good':'warn');
  $('tsla-detail').textContent=data.tsla_error || (tsla?'Pool liquidity '+money(tsla.liquidity_usd)+' · checked '+age(tsla.fetched_at,data.now):'Loading TSLA.X market and wallet data…');
  const meta=data.meta;
  $('meta-price').textContent=money(meta?.price_usd);
  $('meta-reference').textContent=money(meta?.reference_price);
  $('meta-balance').textContent=fmt(meta?.balance,8);
  $('meta-gap').textContent=meta?.gap_percent==null?'—':(Number(meta.gap_percent)>=0?'+':'')+Number(meta.gap_percent).toFixed(2)+'%';
  badge('meta-status',meta?.fresh?'Fresh data':data.meta_error?'Unavailable / stale':'Waiting / stale',meta?.fresh?'good':'warn');
  $('meta-detail').textContent=data.meta_error || (meta?'Pool liquidity '+money(meta.liquidity_usd)+' · checked '+age(meta.fetched_at,data.now):'Loading META.X market and wallet data…');
  const coin=data.coin;
  $('coin-price').textContent=money(coin?.price_usd);
  $('coin-reference').textContent=money(coin?.reference_price);
  $('coin-balance').textContent=fmt(coin?.balance,8);
  $('coin-gap').textContent=coin?.gap_percent==null?'—':(Number(coin.gap_percent)>=0?'+':'')+Number(coin.gap_percent).toFixed(2)+'%';
  badge('coin-status',coin?.fresh?'Fresh data':data.coin_error?'Unavailable / stale':'Waiting / stale',coin?.fresh?'good':'warn');
  $('coin-detail').textContent=data.coin_error || (coin?'Pool liquidity '+money(coin.liquidity_usd)+' · checked '+age(coin.fetched_at,data.now):'Loading COIN.X market and wallet data…');
  const pltr=data.pltr;
  $('pltr-price').textContent=money(pltr?.price_usd);
  $('pltr-reference').textContent=money(pltr?.reference_price);
  $('pltr-balance').textContent=fmt(pltr?.balance,8);
  $('pltr-gap').textContent=pltr?.gap_percent==null?'—':(Number(pltr.gap_percent)>=0?'+':'')+Number(pltr.gap_percent).toFixed(2)+'%';
  badge('pltr-status',pltr?.fresh?'Fresh data':data.pltr_error?'Unavailable / stale':'Waiting / stale',pltr?.fresh?'good':'warn');
  $('pltr-detail').textContent=data.pltr_error || (pltr?'Pool liquidity '+money(pltr.liquidity_usd)+' · checked '+age(pltr.fetched_at,data.now):'Loading PLTR.X market and wallet data…');
  const amd=data.amd;
  $('amd-price').textContent=money(amd?.price_usd);
  $('amd-reference').textContent=money(amd?.reference_price);
  $('amd-balance').textContent=fmt(amd?.balance,8);
  $('amd-gap').textContent=amd?.gap_percent==null?'—':(Number(amd.gap_percent)>=0?'+':'')+Number(amd.gap_percent).toFixed(2)+'%';
  badge('amd-status',amd?.fresh?'Fresh data':data.amd_error?'Unavailable / stale':'Waiting / stale',amd?.fresh?'good':'warn');
  $('amd-detail').textContent=data.amd_error || (amd?'Pool liquidity '+money(amd.liquidity_usd)+' · checked '+age(amd.fetched_at,data.now):'Loading AMD.X market and wallet data…');
  const nvda=data.nvda;
  $('nvda-price').textContent=money(nvda?.price_usd);
  $('nvda-reference').textContent=money(nvda?.reference_price);
  $('nvda-balance').textContent=fmt(nvda?.balance,8);
  $('nvda-gap').textContent=nvda?.gap_percent==null?'—':(Number(nvda.gap_percent)>=0?'+':'')+Number(nvda.gap_percent).toFixed(2)+'%';
  badge('nvda-status',nvda?.fresh?'Fresh data':data.nvda_error?'Unavailable / stale':'Waiting / stale',nvda?.fresh?'good':'warn');
  $('nvda-detail').textContent=data.nvda_error || (nvda?'Pool liquidity '+money(nvda.liquidity_usd)+' · checked '+age(nvda.fetched_at,data.now):'Loading NVDA.X market and wallet data…');
  const spy=data.spy;
  $('spy-price').textContent=money(spy?.price_usd);
  $('spy-reference').textContent=money(spy?.reference_price);
  $('spy-balance').textContent=fmt(spy?.balance,8);
  $('spy-gap').textContent=spy?.gap_percent==null?'—':(Number(spy.gap_percent)>=0?'+':'')+Number(spy.gap_percent).toFixed(2)+'%';
  badge('spy-status',spy?.fresh?'Fresh data':data.spy_error?'Unavailable / stale':'Waiting / stale',spy?.fresh?'good':'warn');
  $('spy-detail').textContent=data.spy_error || (spy?'Pool liquidity '+money(spy.liquidity_usd)+' · checked '+age(spy.fetched_at,data.now):'Loading SPY.X market and wallet data…');
  for(const key of ['spy','spcx','tsla','meta','coin','pltr','amd','nvda']){
    const market=data[key];showBalanceEstimate(key+'-value',market?.balance,market?.price_usd,market?.fresh===true,key.toUpperCase()+'.X');
  }
  wallet=data.wallet;
  const blocked=!data.journal || data.journal.halted;
  $('start-seller').disabled=starting || !sessionReady || data.seller_running!==false || blocked;
  $('start-seller').textContent=starting?'Starting…':data.seller_running?'Seller running':data.journal?.halted?'Seller halted':'Start selling';
  const googlBalance=data.chain?.googl;
  $('googl-strategy-balance').textContent=googlBalance==null?'—':fmt(googlBalance,8)+' GOOGL.X';
  const googlFresh=data.market_fresh===true;
  for(const id of ['googl-strategy-value','googl-wallet-value','remaining-value'])
    showBalanceEstimate(id,googlBalance,data.chain?.pool_price,googlFresh,'GOOGL.X','X1 USDC.X spot (USDC.X valued at $1)');
  const googlSpot=googlFresh?fmt(data.chain.pool_price,2)+' USDC.X':'—';
  const googlReference=googlFresh?money(data.reference.price):'—';
  const googlGap=googlFresh&&data.gap_percent!=null?(Number(data.gap_percent)>=0?'+':'')+Number(data.gap_percent).toFixed(2)+'%':'—';
  liveValue('googl-strategy-price',googlSpot);
  liveValue('googl-strategy-reference',googlReference);
  liveValue('googl-strategy-gap',googlGap);
  $('googl-strategy-price').title=googlFresh?data.chain.pool_price+' USDC.X per GOOGL.X':'Spot price unavailable or stale';
  $('googl-strategy-reference').title=googlFresh?data.reference.price+' USD per GOOGL xStock':'Reference price unavailable or stale';
  $('googl-strategy-gap').className=googlFresh&&Number(data.gap_percent)>0?'mint':'';
  const spotTime=data.chain?.fetched_at?new Date(data.chain.fetched_at*1000).toLocaleString():'unknown';
  const referenceTime=data.reference?.updated_at?new Date(data.reference.updated_at*1000).toLocaleString():'unknown';
  $('googl-strategy-market-detail').textContent=(googlFresh?'Market data current':'Market data stale or unavailable')+' · X1 spot checked '+spotTime+' · xStock reference updated '+referenceTime;
  badge('googl-strategy-status',data.seller_running?'Running':data.journal?.halted?'Halted':data.journal?'Stopped':'Unknown',data.seller_running?'good':data.journal?'':'warn');
  $('wallet').textContent=short(wallet); $('wallet').title=wallet;
  $('wallet').href='https://explorer.mainnet.x1.xyz/address/'+encodeURIComponent(wallet);
  const running=data.seller_running, j=data.journal, runtime=data.runtime;
  const runningCount=Object.values(workers).filter(w=>w.running===true).length;
  const unknownWorkers=['googl','spy','spcx','tsla','conversion','bridge','meta','coin','pltr','amd','nvda'].some(key=>workers[key]?.running==null);
  badge('engine-badge',runningCount?runningCount+' script'+(runningCount===1?'':'s')+' running':unknownWorkers?'Script status unknown':'All scripts stopped',runningCount?'good':unknownWorkers?'warn':'');
  $('engine-detail').textContent='Individual status and Stop controls below';
  const visibleErrors=data.errors.filter(message=>message!=='Reference price unavailable or stale.');
  $('errors').hidden=!visibleErrors.length;
  $('errors').textContent=visibleErrors.join(' ');
  $('googl').textContent=fmt(data.chain?.googl,8); liveValue('usdc',fmt(data.chain?.usdc,6)); $('xnt').textContent=fmt(data.chain?.xnt,6);
  $('usdc').title=data.chain?.usdc==null?'Unavailable':String(data.chain.usdc)+' USDC.X';
  $('usdc-note').textContent=data.chain?age(data.chain.fetched_at,data.now)+' · pending transfers may reduce spendable funds':'Wallet balance unavailable';
  const usdcCurrent=data.chain?.fetched_at!=null&&data.now-data.chain.fetched_at<=120;
  const usdcValue=balanceEstimate(data.chain?.usdc,1,usdcCurrent);
  $('usdc-value').textContent=usdcValue==null?'Estimated value: —':'Estimated value: '+money(usdcValue);
  $('usdc-value').title='USDC.X valued at $1; pending transfers may reduce spendable funds';
  $('updated').textContent=data.chain ? 'Chain checked '+age(data.chain.fetched_at,data.now)+' · slot '+data.chain.slot.toLocaleString() : 'Loading chain data…';
  $('sold').textContent=fmt(j?.confirmed,8); $('remaining').textContent=fmt(data.chain?.googl,8); $('reserved').textContent=j?fmt(j.reserved,8)+' GOOGL.X':'Unknown';
  $('pool-price').textContent=money(data.chain?.pool_price); $('reference').textContent=money(data.reference?.price);
  $('gap').textContent=data.gap_percent==null?'—':(Number(data.gap_percent)>=0?'+':'')+Number(data.gap_percent).toFixed(2)+'%';
  badge('freshness',data.market_fresh?'Fresh data':'Waiting / stale',data.market_fresh?'good':'warn');
  $('reference-age').textContent='Reference updated '+age(data.reference?.updated_at,data.now);
  draw(data.history);
  const rows=j?.entries||[];
  $('count').textContent=rows.length+' TRANSACTIONS'; $('empty').hidden=rows.length>0;
  $('empty').textContent=j?'No transactions recorded yet. Monitoring does not submit trades.':'Journal unavailable; transaction history is unknown.';
  $('transactions').replaceChildren();
  for(const row of rows) {
    const tr=document.createElement('tr');
    const time=document.createElement('td'); time.textContent=row.created_at?new Date(row.created_at).toLocaleString():'—'; tr.append(time);
    const status=document.createElement('td'),tag=document.createElement('span'); tag.className='badge '+(row.status==='finalized'?'good':row.status==='failed'?'bad':'warn'); tag.textContent=row.status; status.append(tag);tr.append(status);
    for(const text of [fmt(row.amount_raw/1e8,8), row.minimum_output_raw==null?'—':fmt(row.minimum_output_raw/1e6,6)+' USDC.X']) {const td=document.createElement('td');td.textContent=text;tr.append(td);}
    const td=document.createElement('td'),a=document.createElement('a');a.textContent=short(row.signature);a.href='https://explorer.mainnet.x1.xyz/tx/'+encodeURIComponent(row.signature);a.target='_blank';a.rel='noopener noreferrer';td.append(a);tr.append(td);$('transactions').append(tr);
  }
  if(data.simulation) {
    $('simulation').textContent=fmt(data.simulation.amount_googl,8)+' GOOGL.X → '+fmt(data.simulation.simulated_usdc,6)+' USDC.X';
    $('simulation-detail').textContent='Protected minimum '+fmt(data.simulation.minimum_usdc,6)+' USDC.X · historical simulation, not a live quote';
    $('simulation-age').textContent=data.simulation_updated_at?new Date(data.simulation_updated_at*1000).toLocaleString():'Time unknown';
  }
  $('connection').textContent='Connected to local dashboard · '+new Date(data.now*1000).toLocaleTimeString();
}
async function refresh(schedule=true){
  try {const response=await fetch('/api/status',{cache:'no-store',signal:AbortSignal.timeout(8000)});if(!response.ok)throw Error('status');const data=await response.json();sessionReady=true;render(data);}
  catch { for(const id of ['spy-value','spcx-value','tsla-value','meta-value','coin-value','pltr-value','amd-value','nvda-value','googl-strategy-value','googl-wallet-value','remaining-value','usdc-value'])$(id).textContent='Estimated value: —';previewFingerprint='';$('overview-cards').replaceChildren(); for(const key of ['meta','coin','pltr','amd','nvda']){badge(key+'-status','Disconnected','bad');$(key+'-gap').textContent='—';} badge('proceeds-status','Disconnected','bad'); badge('bridge-status','Disconnected','bad'); badge('settlement-status','Disconnected','bad'); badge('googl-strategy-status','Disconnected','bad'); badge('timeline-status','Disconnected','bad'); badge('rail-automation-status','Disconnected','bad'); $('proceeds-metric-note').textContent='Last known receipts · dashboard disconnected';$('strategy-count-note').textContent='Last known script count · dashboard disconnected';$('usdc-note').textContent='Last known wallet balance · dashboard disconnected';$('recent-empty').textContent='Dashboard disconnected; recent activity may be stale.'; for(const key of ['spcx','tsla','meta','coin','pltr','amd','nvda'])$('start-'+key+'-seller').disabled=true; badge('tsla-status','Disconnected','bad'); $('tsla-gap').textContent='—'; badge('spcx-status','Disconnected','bad'); $('spcx-gap').textContent='—'; $('start-auto-convert').disabled=true; badge('terminal-status','Disconnected','bad'); for(const key of ['googl','spy','spcx','tsla','conversion','bridge','meta','coin','pltr','amd','nvda']){$('stop-'+key).disabled=true;badge('worker-'+key+'-badge','Unknown','warn');} $('stop-all').disabled=true; badge('auto-convert-badge','Disconnected','bad'); $('start-spy-seller').disabled=true; badge('spy-status','Disconnected','bad'); $('spy-gap').textContent='—'; $('start-seller').disabled=true; sessionReady=false; $('connection').textContent='Dashboard disconnected'; $('errors').hidden=false; $('errors').textContent='Connection lost. Displayed values may be out of date.';badge('freshness','Disconnected','bad');badge('engine-badge','Status unknown','warn'); }
  if(!sessionReady)$('stock-purchase-confirm').disabled=true;
  if(schedule)setTimeout(refresh,5000);
}
$('start-seller').addEventListener('click',async()=>{
  if(starting || !sessionReady) return;
  starting=true; $('start-seller').disabled=true; $('start-seller').textContent='Starting…';
  $('start-result').textContent='Starting live seller…';
  try {
    const response=await fetch('/api/seller/start',{method:'POST',signal:AbortSignal.timeout(15000)});
    const result=await response.json();
    $('start-result').textContent=result.message;
  } catch { $('start-result').textContent='Start response unavailable. Wait for seller status before retrying.'; }
  finally { starting=false; }
});
$('copy').addEventListener('click',async()=>{try{await navigator.clipboard.writeText(wallet);$('copy').textContent='Copied';setTimeout(()=>$('copy').textContent='Copy address',1500);}catch{$('copy').textContent='Select address to copy';$('wallet').textContent=wallet;}});
refresh();

let conversionQuote=null, conversionBusy=false, quoteTimer;
function clearConversionQuote(){conversionQuote=null;clearTimeout(quoteTimer);$('xnt-quote').hidden=true;}
async function conversionPost(path, body){
  if(!sessionReady) throw Error('Dashboard disconnected. Wait for reconnection.');
  const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal:AbortSignal.timeout(90000)});
  const result=await response.json();if(!response.ok)throw Error(result.message || 'Conversion unavailable');return result;
}
$('xnt-amount').addEventListener('input',clearConversionQuote);
$('xnt-cancel').addEventListener('click',clearConversionQuote);
$('xnt-form').addEventListener('submit',async event=>{
  event.preventDefault();if(conversionBusy)return;clearConversionQuote();conversionBusy=true;$('xnt-preview').disabled=true;
  $('xnt-result').textContent='Fetching a live quote…';
  try {
    const q=await conversionPost('/api/xnt/quote',{amount:$('xnt-amount').value});conversionQuote=q;
    $('xnt-quote-detail').textContent='Sell '+q.amount_xnt+' XNT · estimated '+q.estimated_usdc+' USDC.X · minimum '+q.minimum_usdc+' USDC.X. Network costs up to '+q.cost_allowance_xnt+' XNT.';
    $('xnt-quote').hidden=false;$('xnt-confirm').disabled=false;$('xnt-result').textContent='Review and confirm within 30 seconds.';
    quoteTimer=setTimeout(()=>{clearConversionQuote();$('xnt-result').textContent='Quote expired. Preview again.';},Math.max(0,q.expires_at*1000-Date.now()));
  }catch(e){$('xnt-result').textContent=e.message;}finally{conversionBusy=false;$('xnt-preview').disabled=false;}
});
$('xnt-confirm').addEventListener('click',async()=>{
  if(conversionBusy||!conversionQuote)return;
  const id=conversionQuote.quote_id;clearConversionQuote();conversionBusy=true;$('xnt-preview').disabled=true;
  $('xnt-result').textContent='Simulating and submitting your confirmed conversion…';
  try{
    const r=await conversionPost('/api/xnt/confirm',{quote_id:id});$('xnt-result').textContent=r.message+' ';
    const a=document.createElement('a');a.href='https://explorer.mainnet.x1.xyz/tx/'+encodeURIComponent(r.signature);a.target='_blank';a.rel='noopener noreferrer';a.textContent='View transaction';$('xnt-result').append(a);
  }catch(e){$('xnt-result').textContent=e.message+' If submission status is unknown, check transaction history before retrying.';}
  finally{conversionBusy=false;$('xnt-preview').disabled=false;}
});

$('start-spy-seller').addEventListener('click',async()=>{
  if(spyStarting || !sessionReady || $('start-spy-seller').disabled)return;
  spyStarting=true;$('start-spy-seller').disabled=true;$('start-spy-seller').textContent='Starting SPY.X seller…';
  $('spy-start-result').textContent='Starting live SPY.X sales from available inventory…';
  try{
    const response=await fetch('/api/spy/seller/start',{method:'POST',signal:AbortSignal.timeout(15000)});
    const result=await response.json();$('spy-start-result').textContent=result.message;
  }catch{$('spy-start-result').textContent='Start response unavailable. Wait for seller status before retrying.';}
  finally{spyStarting=false;}
});

async function stopScript(key){
  if(stopBusy || !sessionReady)return;
  stopBusy=true;
  for(const name of ['googl','spy','spcx','tsla','conversion','bridge','meta','coin','pltr','amd','nvda','all'])$('stop-'+name).disabled=true;
  $('script-stop-result').textContent=key==='all'?'Stopping all trading scripts…':'Stopping selected script…';
  try{
    const path=key==='all'?'/api/scripts/stop-all':'/api/scripts/'+key+'/stop';
    const response=await fetch(path,{method:'POST',signal:AbortSignal.timeout(15000)});
    const result=await response.json();$('script-stop-result').textContent=result.message;
    const status=await fetch('/api/status',{cache:'no-store',signal:AbortSignal.timeout(8000)});
    if(status.ok)render(await status.json());
  }catch{$('script-stop-result').textContent='Stop response unavailable. Check script status; stopping has not been confirmed.';}
  finally{stopBusy=false;}
}
for(const key of ['googl','spy','spcx','tsla','conversion','bridge','meta','coin','pltr','amd','nvda','all'])$('stop-'+key).addEventListener('click',()=>stopScript(key));

let terminalEvents=[], terminalFilter='all', terminalIds=new Set(), terminalCheckedAt=null;
function renderTerminal(activity, now){
  if(!activity){badge('terminal-status','Unavailable','warn');return;}
  terminalEvents=activity.events || []; terminalCheckedAt=activity.checked_at;
  badge('terminal-status',activity.checked_at && now-activity.checked_at<20?'Live · 5s refresh':'Waiting for activity',activity.checked_at && now-activity.checked_at<20?'good':'warn');
  const output=$('terminal-output');
  const visible=terminalEvents.filter(e=>terminalFilter==='all'||e.source===terminalFilter);
  if(!terminalIds.size)output.replaceChildren();
  for(const event of visible){
    if(terminalIds.has(event.id))continue;
    const row=document.createElement('div');row.className='terminal-line '+event.level;row.dataset.eventId=event.id;
    const time=document.createElement('time');time.dateTime=new Date(event.at*1000).toISOString();time.textContent=new Date(event.at*1000).toLocaleString();
    const source=document.createElement('span');source.className='terminal-source';source.textContent=({spy:'SPY.X',spcx:'SPCX.X',tsla:'TSLA.X',meta:'META.X',coin:'COIN.X',pltr:'PLTR.X',amd:'AMD.X',nvda:'NVDA.X',googl:'GOOGL.X',conversion:'XNT → USDC.X',bridge:'USDC.X → SOL',system:'SYSTEM'})[event.source]||'SYSTEM';
    const message=document.createElement('span');message.textContent=event.message;
    row.append(time,source,message);
    if(event.signature){const link=document.createElement('a');link.href='https://explorer.mainnet.x1.xyz/tx/'+encodeURIComponent(event.signature);link.target='_blank';link.rel='noopener noreferrer';link.textContent='View transaction ↗';message.append(' ',link);}
    output.append(row);terminalIds.add(event.id);
  }
  const retained=new Set(visible.map(e=>e.id));
  for(const row of [...output.children])if(row.dataset.eventId && !retained.has(Number(row.dataset.eventId))){terminalIds.delete(Number(row.dataset.eventId));row.remove();}
  if(!visible.length){output.textContent='No activity recorded for this script yet.';}
  if($('terminal-follow').checked)output.scrollTop=output.scrollHeight;
}
$('terminal-filter').addEventListener('change',()=>{terminalFilter=$('terminal-filter').value;terminalIds.clear();renderTerminal({events:terminalEvents,checked_at:terminalCheckedAt},Date.now()/1000);});
$('terminal-follow').addEventListener('change',()=>{if($('terminal-follow').checked)$('terminal-output').scrollTop=$('terminal-output').scrollHeight;});

function renderBridge(bridge){
  const rows=bridge?.entries || [];
  badge('bridge-status',bridge?.running?'Bridge worker running':bridge?'Bridge worker stopped':'Bridge status unavailable',bridge?.running?'good':'warn');
  $('bridge-empty').hidden=rows.length>0;
  $('bridge-empty').textContent=bridge?'No bridge transfers recorded yet.':'Bridge journal unavailable.';
  $('bridge-rows').replaceChildren();
  for(const row of rows){
    const tr=document.createElement('tr');
    const time=document.createElement('td');time.textContent=row.created_at?new Date(row.created_at*1000).toLocaleString():'—';tr.append(time);
    const status=document.createElement('td'),tag=document.createElement('span');tag.className='badge '+(row.status==='completed'?'good':row.status==='failed'?'bad':'warn');tag.textContent=({pending_x1:'Pending on X1',pending_solana:'Awaiting Solana',completed:'Completed',failed:'Failed'})[row.status]||'Unknown';status.append(tag);tr.append(status);
    for(const value of [fmt(row.amount_raw/1e6,6),fmt((row.amount_raw-(row.fee_raw??1e6))/1e6,6)]){const td=document.createElement('td');td.textContent=value;tr.append(td);}
    for(const [signature,base] of [[row.signature,'https://explorer.mainnet.x1.xyz/tx/'],[row.destination_signature,'https://solscan.io/tx/']]){
      const td=document.createElement('td');
      if(signature){const a=document.createElement('a');a.href=base+encodeURIComponent(signature);a.target='_blank';a.rel='noopener noreferrer';a.textContent=short(signature);td.append(a);}else td.textContent='—';
      tr.append(td);
    }
    $('bridge-rows').append(tr);
  }
}

let bridgeQuote=null,bridgeBusy=false,bridgeTimer;
function clearBridgeQuote(){bridgeQuote=null;clearTimeout(bridgeTimer);$('bridge-quote').hidden=true;}
async function bridgePost(path,body){
  if(!sessionReady)throw Error('Dashboard disconnected. Wait for reconnection.');
  const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal:AbortSignal.timeout(90000)});
  const result=await response.json();if(!response.ok)throw Error(result.message||'Bridge unavailable');return result;
}
$('bridge-amount').addEventListener('input',clearBridgeQuote);
$('bridge-cancel').addEventListener('click',()=>{clearBridgeQuote();$('bridge-result').textContent='Bridge preview cancelled.';});
$('bridge-form').addEventListener('submit',async event=>{
  event.preventDefault();if(bridgeBusy)return;bridgeBusy=true;clearBridgeQuote();$('bridge-preview').disabled=true;$('bridge-result').textContent='Checking bridge route and wallet balance…';
  try{
    const quote=await bridgePost('/api/bridge/preview',{amount:$('bridge-amount').value});
    bridgeQuote=quote;$('bridge-quote').hidden=false;
    $('bridge-quote-detail').textContent='Send '+quote.amount_usdc+' USDC.X · bridge fee '+quote.fee_usdc+' USDC.X · expected '+quote.expected_usdc+' USDC on Solana · destination '+short(quote.destination)+' · expires in 30 seconds';
    $('bridge-result').textContent='Review the amount and confirm to submit the bridge transfer.';
    bridgeTimer=setTimeout(()=>{clearBridgeQuote();$('bridge-result').textContent='Bridge preview expired. Preview again.';},Math.max(0,(quote.expires_at-Date.now()/1000)*1000));
  }catch(error){$('bridge-result').textContent=error.message;}
  finally{bridgeBusy=false;$('bridge-preview').disabled=false;}
});
$('bridge-confirm').addEventListener('click',async()=>{
  if(bridgeBusy||!bridgeQuote)return;bridgeBusy=true;$('bridge-confirm').disabled=true;
  const quote=bridgeQuote;clearBridgeQuote();$('bridge-result').textContent='Submitting bridge transfer; wait for transaction status…';
  try{const result=await bridgePost('/api/bridge/confirm',{quote_id:quote.quote_id});$('bridge-result').textContent='Bridge submitted on X1: '+short(result.signature)+'. Follow the bridge log for Solana completion.';}
  catch(error){$('bridge-result').textContent=error.message+' Check the bridge log before retrying.';}
  finally{bridgeBusy=false;$('bridge-confirm').disabled=false;}
});

let stockPurchaseData=null,stockPurchaseQuote=null,stockPurchaseBusy=false,stockPurchaseTimer;
function clearStockPurchaseQuote(){stockPurchaseQuote=null;clearTimeout(stockPurchaseTimer);$('stock-purchase-quote').hidden=true;$('stock-purchase-confirm').disabled=true;}
function renderStockPurchase(data){
  stockPurchaseData=data;
  const key=$('stock-purchase-stock').value, row=data?.[key],stage=row?.stage;
  const labels={new:'Not started',swap_pending:'Solana purchase pending',swap_finalized:'Purchase finalized · bridge ready',bridge_pending:'Solana bridge pending',completed:'Received on X1',failed:'Failed · review journal',unavailable:'Journal unavailable'};
  badge('stock-purchase-badge',labels[stage]||'Status unavailable',stage==='completed'?'good':stage==='new'?'':stage==='failed'||stage==='unavailable'?'bad':'warn');
  $('stock-purchase-status').textContent=row?`${row.asset} · ${labels[stage]||'Unknown status'}`+(row.attempt_count?` · ${row.attempt_count} recorded purchase${row.attempt_count===1?'':'s'}`:'')+(data?.running===true?' · background tracker running':'')+(row.bought_raw!=null?` · purchased ${fmt(row.bought_raw/1e8,8)} ${row.asset}`:'')+(row.created_at?` · started ${new Date(row.created_at*1000).toLocaleString()}`:''):'Stock bridge status unavailable.';
  $('stock-purchase-stock').disabled=stockPurchaseBusy;
  $('stock-purchase-amount').disabled=stockPurchaseBusy;
  $('stock-purchase-preview').disabled=stockPurchaseBusy||!row||data?.running!==false||stage==='failed'||stage==='unavailable';
  $('stock-purchase-preview').textContent=data?.running===true?'Bridge tracker running':stage==='completed'?'Preview another purchase':stage==='new'?'Preview purchase & bridge':'Check bridge status';
  const links=$('stock-purchase-links');links.replaceChildren();
  for(const [index,attempt] of (row?.history||[]).entries()){
    for(const [signature,label,base] of [[attempt.swap_signature,'Solana purchase','https://solscan.io/tx/'],[attempt.bridge_signature,'Solana bridge','https://solscan.io/tx/'],[attempt.destination_signature,'X1 receipt','https://explorer.mainnet.x1.xyz/tx/']]){
      if(!signature)continue;
      const a=document.createElement('a');a.href=base+encodeURIComponent(signature);a.textContent=`#${index+1} ${label} ↗`;a.target='_blank';a.rel='noopener noreferrer';links.append(a);
    }
  }
}
async function stockPurchasePost(path,body){
  if(!sessionReady)throw Error('Dashboard disconnected. Wait for reconnection.');
  const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal:AbortSignal.timeout(90000)});
  const result=await response.json();if(!response.ok)throw Error(result.message||'Stock purchase or bridge unavailable');return result;
}
$('stock-purchase-stock').addEventListener('change',()=>{clearStockPurchaseQuote();$('stock-purchase-result').textContent='';renderStockPurchase(stockPurchaseData);});
$('stock-purchase-amount').addEventListener('input',()=>{clearStockPurchaseQuote();$('stock-purchase-result').textContent='';});
$('stock-purchase-cancel').addEventListener('click',()=>{clearStockPurchaseQuote();$('stock-purchase-result').textContent='Preview cancelled.';});
$('stock-purchase-form').addEventListener('submit',async event=>{
  event.preventDefault();if(stockPurchaseBusy)return;
  if(!sessionReady){$('stock-purchase-result').textContent='Dashboard disconnected. Wait for reconnection.';return;}
  clearStockPurchaseQuote();stockPurchaseBusy=true;$('stock-purchase-preview').disabled=true;$('stock-purchase-stock').disabled=true;$('stock-purchase-amount').disabled=true;
  $('stock-purchase-result').textContent='Checking current Solana quote and X1 bridge route…';
  try{
    const result=await stockPurchasePost('/api/stock-purchase/preview',{stock:$('stock-purchase-stock').value,amount:$('stock-purchase-amount').value});
    if(result.quote_id){
      stockPurchaseQuote=result;
      const detail=result.status==='SWAP_READY'?`Spend ${result.spend_usdc} USDC for ${result.asset}. Quoted ${result.quoted_stock} ${result.asset}; protected minimum ${result.minimum_stock}; bridge minimum ${result.bridge_minimum_stock}. Destination: same wallet on X1.`:result.status==='BRIDGE_READY'?`Purchase finalized. Bridge ${fmt(result.stock_raw/1e8,8)} ${$('stock-purchase-stock').selectedOptions[0].textContent} to X1.`:`${result.status.replaceAll('_',' ').toLowerCase()}. No new purchase is needed; continue checking the recorded transaction.`;
      $('stock-purchase-quote-detail').textContent=detail;
      $('stock-purchase-confirm').textContent=result.status==='SWAP_READY'?`Confirm ${result.spend_usdc} USDC purchase & bridge`:result.status==='BRIDGE_READY'?'Confirm bridge to X1':'Continue tracking';
      $('stock-purchase-confirm').disabled=false;$('stock-purchase-quote').hidden=false;
      $('stock-purchase-result').textContent='Review and confirm within 30 seconds.';
      stockPurchaseTimer=setTimeout(()=>{clearStockPurchaseQuote();$('stock-purchase-result').textContent='Preview expired. Preview again.';},Math.max(0,(result.expires_at-Date.now()/1000)*1000));
    }else{$('stock-purchase-result').textContent='This stock purchase and bridge is complete.';}
    await refresh(false);
  }catch(error){$('stock-purchase-result').textContent=error.message;}
  finally{stockPurchaseBusy=false;renderStockPurchase(stockPurchaseData);}
});
$('stock-purchase-confirm').addEventListener('click',async()=>{
  if(stockPurchaseBusy||!stockPurchaseQuote)return;
  const quote=stockPurchaseQuote;clearStockPurchaseQuote();stockPurchaseBusy=true;$('stock-purchase-preview').disabled=true;$('stock-purchase-stock').disabled=true;$('stock-purchase-amount').disabled=true;
  $('stock-purchase-result').textContent=quote.status==='SWAP_READY'?'Submitting confirmed Solana purchase; do not retry until its status is known.':'Checking and continuing the confirmed bridge.';
  try{
    const result=await stockPurchasePost('/api/stock-purchase/confirm',{quote_id:quote.quote_id});
    $('stock-purchase-result').textContent=`${result.status.replaceAll('_',' ').toLowerCase()}. `+(result.tracking_started===false?'Automatic tracking could not start. Check the journal before retrying.':result.tracking_started?'Finality and X1 bridge tracking started.':'Check transaction status below.');
    await refresh(false);
  }catch(error){
    $('stock-purchase-result').textContent=error.message.includes('Current protected output is below the confirmed preview')
      ? 'The quote moved below your confirmed minimum. No purchase was sent. Preview again for a fresh quote.'
      : error.message+' Check the recorded transaction status before previewing again.';
    await refresh(false);
  }
  finally{stockPurchaseBusy=false;renderStockPurchase(stockPurchaseData);}
});

$('start-auto-convert').addEventListener('click',async()=>{
  if(autoStarting || !sessionReady || $('start-auto-convert').disabled)return;
  autoStarting=true;$('start-auto-convert').disabled=true;$('start-auto-convert').textContent='Starting conversion…';
  $('auto-start-result').textContent='Starting automatic conversion of approved stock proceeds…';
  try{
    const response=await fetch('/api/conversion/start',{method:'POST',signal:AbortSignal.timeout(15000)});
    const result=await response.json();$('auto-start-result').textContent=result.message;
  }catch{$('auto-start-result').textContent='Start response unavailable. Check converter status before retrying.';}
  finally{autoStarting=false;}
});

for(const key of ['spcx','tsla','meta','coin','pltr','amd','nvda'])$('start-'+key+'-seller').addEventListener('click',async()=>{
  if(stockStarting.has(key)||!sessionReady||$('start-'+key+'-seller').disabled)return;
  stockStarting.add(key);$('start-'+key+'-seller').disabled=true;$(key+'-start-result').textContent='Starting live stock seller…';
  try{const r=await fetch('/api/'+key+'/seller/start',{method:'POST',signal:AbortSignal.timeout(15000)});const result=await r.json();$(key+'-start-result').textContent=result.message;}
  catch{$(key+'-start-result').textContent='Start response unavailable. Check worker status before retrying.';}
  finally{stockStarting.delete(key);}
});

let proceedsData=null;
function renderProceeds(data,now){
  proceedsData=data;
  if(!data){badge('proceeds-status','Unavailable','warn');return;}
  badge('proceeds-status',data.updated_at && now-data.updated_at<90?'Receipts checked':'Loading / stale',data.updated_at && now-data.updated_at<90?'good':'warn');
  $('proceeds-errors').textContent=(data.errors||[]).join(' ');
  const rows=[...(data.rows||[])].sort((a,b)=>receiptTime(b.at)-receiptTime(a.at));
  const selected=$('proceeds-filter').value;
  const visible=rows.filter(r=>selected==='all'||r.kind===selected||r.asset===selected);
  const finalized=rows.filter(r=>r.status==='finalized');
  const sum=key=>finalized.reduce((n,r)=>n+Number(r[key]||0),0);
  $('proceeds-summary').textContent=finalized.length+' finalized transactions · stock sales received '+fmt(sum('net_xnt_received'),9)+' net XNT · direct stock sales '+fmt(finalized.filter(r=>r.kind==='sale').reduce((n,r)=>n+Number(r.usdc_received||0),0),6)+' USDC.X · conversions received '+fmt(finalized.filter(r=>r.kind==='conversion').reduce((n,r)=>n+Number(r.usdc_received||0),0),6)+' USDC.X';
  $('proceeds-rows').replaceChildren();
  for(const row of visible){
    const tr=document.createElement('tr');
    const text=value=>{const td=document.createElement('td');td.textContent=value;tr.append(td);};
    text(row.at?new Date(receiptTime(row.at)).toLocaleString():'—');
    text(row.kind==='conversion'?'XNT → USDC.X · '+row.source:row.asset+' → '+(row.asset==='GOOGL.X'?'USDC.X':'XNT'));
    const status=document.createElement('td'),tag=document.createElement('span');tag.className='badge '+(row.status==='finalized'?'good':row.status==='failed'?'bad':'warn');tag.textContent=row.status;status.append(tag);tr.append(status);
    text(row.actual_input==null?'—':fmt(row.actual_input,9)+' '+row.asset);
    for(const key of ['net_xnt_received','usdc_received','network_fee_xnt','other_cost_xnt'])text(row[key]==null?'—':fmt(row[key],key==='usdc_received'?6:9));
    const td=document.createElement('td'),link=document.createElement('a');link.href='https://explorer.mainnet.x1.xyz/tx/'+encodeURIComponent(row.signature);link.target='_blank';link.rel='noopener noreferrer';link.textContent=short(row.signature);td.append(link);tr.append(td);$('proceeds-rows').append(tr);
  }
  $('proceeds-empty').hidden=visible.length>0;$('proceeds-empty').textContent=data.updated_at?'No recorded transactions match this filter.':'Loading finalized receipts…';
}
function receiptTime(value){return typeof value==='number'?value*1000:Date.parse(value)||0;}
$('proceeds-filter').addEventListener('change',()=>renderProceeds(proceedsData,Date.now()/1000));

function exactSum(rows,key,places){
  const scale=10n**BigInt(places);
  const units=rows.reduce((sum,row)=>{const value=String(row[key]??'0');const match=/^(-?)(\d+)(?:\.(\d+))?$/.exec(value);if(!match)return sum;const fraction=(match[3]||'').padEnd(places,'0').slice(0,places);return sum+(match[1]? -1n:1n)*(BigInt(match[2])*scale+BigInt(fraction||'0'));},0n);
  const absolute=units<0n?-units:units;
  return (units<0n?'-':'')+(absolute/scale).toString()+'.'+(absolute%scale).toString().padStart(places,'0');
}

let proceedsPeriod='604800', latestOverviewData=null;
for(const button of document.querySelectorAll('[data-proceeds-period]'))button.addEventListener('click',()=>{proceedsPeriod=button.dataset.proceedsPeriod;for(const peer of document.querySelectorAll('[data-proceeds-period]'))peer.setAttribute('aria-pressed',String(peer===button));if(latestOverviewData)renderOverview(latestOverviewData);});
function eligibleProceeds(rows){return rows.filter(row=>row.status==='finalized'&&((row.kind==='sale'&&row.asset==='GOOGL.X')||(row.kind==='conversion'&&row.source==='automatic')));}
function drawProceeds(rows,now,verified){
  const periodStart=proceedsPeriod==='all'?0:now-Number(proceedsPeriod);
  const points=eligibleProceeds(rows).filter(row=>receiptTime(row.at)/1000>=periodStart).sort((a,b)=>receiptTime(a.at)-receiptTime(b.at));
  const svg=$('proceeds-chart'),line=$('proceeds-line'),area=$('proceeds-area');
  const total=exactSum(points,'usdc_received',6);
  const label=({'86400':'Last 24 hours','604800':'Last 7 days','2592000':'Last 30 days',all:'All recorded time'})[proceedsPeriod];
  svg.setAttribute('aria-label',`${label}: ${total} verified USDC.X from ${points.length} finalized eligible receipts`);
  $('proceeds-axis-start').textContent=points.length?new Date(receiptTime(points[0].at)).toLocaleDateString():'—';
  $('proceeds-axis-end').textContent=points.length?new Date(receiptTime(points.at(-1).at)).toLocaleDateString():'—';
  $('proceeds-chart-empty').hidden=points.length>1;
  $('proceeds-chart-empty').textContent=!verified?'Waiting for verified receipts…':points.length===1?'One finalized receipt in this period.':`No finalized proceeds receipts in ${label.toLowerCase()}.`;
  if(points.length<2){line.setAttribute('d','');area.setAttribute('d','');return {total,count:points.length,label};}
  const first=receiptTime(points[0].at),last=receiptTime(points.at(-1).at),duration=last-first||1;
  let running=0;
  const values=points.map(row=>{running+=Number(row.usdc_received||0);return {at:receiptTime(row.at),value:running};});
  const max=values.at(-1).value||1;
  const coordinates=values.map(p=>[(p.at-first)/duration*640,170-p.value/max*145]);
  const path='M'+coordinates.map(p=>p.join(',')).join(' L');
  line.setAttribute('d',path);area.setAttribute('d',path+' L640,185 L0,185 Z');
  return {total,count:points.length,label};
}

function renderOverview(data){
  latestOverviewData=data;
  const receipts=data.proceeds;
  const rows=receipts?.rows||[];
  const final=rows.filter(row=>row.status==='finalized');
  const direct=final.filter(row=>row.kind==='sale'&&row.asset==='GOOGL.X');
  const automatic=final.filter(row=>row.kind==='conversion'&&row.source==='automatic');
  const stock=final.filter(row=>row.kind==='sale'&&row.asset!=='GOOGL.X');
  const directUsdc=exactSum(direct,'usdc_received',6), automaticUsdc=exactSum(automatic,'usdc_received',6), netXnt=exactSum(stock,'net_xnt_received',9);
  const totalUsdc=exactSum([...direct,...automatic],'usdc_received',6);
  const checked=receipts?.updated_at;
  const fresh=checked && data.now-checked<90;
  const period=drawProceeds(rows,data.now,Boolean(checked));
  liveValue('verified-proceeds',checked?fmt(period.total,6):'—');
  $('verified-proceeds').title=checked?period.total+' USDC.X from '+period.count+' finalized eligible receipts, '+period.label.toLowerCase():'Receipts unavailable';
  $('proceeds-metric-note').textContent=checked?`${period.label} · ${period.count} eligible receipts · checked ${age(checked,data.now)}${receipts.errors?.length?' · some receipts unavailable':''}`:'Waiting for finalized receipts';
  $('settlement-sales').textContent=checked?fmt(netXnt,9)+' XNT':'—';
  $('settlement-converted').textContent=checked?fmt(automaticUsdc,6)+' USDC.X':'—';
  $('settlement-direct').textContent=checked?fmt(totalUsdc,6)+' USDC.X':'—';
  $('settlement-sales').title=netXnt+' XNT';
  $('settlement-converted').title=automaticUsdc+' USDC.X';
  $('settlement-direct').title=totalUsdc+' USDC.X total; '+directUsdc+' direct GOOGL.X sales';
  const pending=rows.filter(row=>row.status!=='finalized'&&row.status!=='failed').length;
  const failed=rows.filter(row=>row.status==='failed').length;
  const stages=[{complete:stock.length>0,pending:rows.some(row=>row.kind==='sale'&&row.asset!=='GOOGL.X'&&row.status==='pending')},{complete:automatic.length>0,pending:rows.some(row=>row.kind==='conversion'&&row.source==='automatic'&&row.status==='pending')},{complete:direct.length+automatic.length>0,pending:pending>0}];
  document.querySelectorAll('.settlement-step').forEach((step,index)=>{const stage=stages[index],icon=step.querySelector('.step-number');step.classList.toggle('completed',stage.complete);step.classList.toggle('pending',!stage.complete&&stage.pending);icon.textContent=stage.complete?'✓':stage.pending?'◷':String(index+1).padStart(2,'0');});
  badge('settlement-status',!checked?'Loading':fresh&&!receipts.errors?.length?'Receipts current':'Receipts stale / partial',fresh&&!receipts.errors?.length?'good':'warn');
  $('settlement-detail').textContent=checked?`${pending} pending or unverified · ${failed} failed · checked ${new Date(checked*1000).toLocaleString()}. Direct GOOGL.X sales: ${fmt(directUsdc,6)} USDC.X. XNT and USDC.X are separate units; automatic conversions are not assigned to individual sales.`:'Receipt history unavailable. Amounts will appear after verification.';
}

let recentData=null;
function renderRecent(data){
  recentData=data;
  const items=[];
  for(const row of data.proceeds?.rows||[]){
    items.push({time:receiptTime(row.at),kind:row.kind,label:row.kind==='sale'?`${row.asset} → ${row.asset==='GOOGL.X'?'USDC.X':'XNT'}`:`XNT → USDC.X · ${row.source}`,amount:row.status==='finalized'?(row.kind==='conversion'||row.asset==='GOOGL.X'?fmt(row.usdc_received,6)+' USDC.X':fmt(row.net_xnt_received,9)+' XNT'):'Pending receipt',status:row.status,signature:row.signature,url:'https://explorer.mainnet.x1.xyz/tx/'});
  }
  for(const row of data.auto_bridge?.entries||[]){
    items.push({time:receiptTime(row.created_at),kind:'bridge',label:'USDC.X → Solana USDC',amount:row.status==='completed'?fmt((row.amount_raw-(row.fee_raw??1e6))/1e6,6)+' USDC':'Pending Solana receipt',status:row.status,signature:row.destination_signature||row.signature,url:row.destination_signature?'https://solscan.io/tx/':'https://explorer.mainnet.x1.xyz/tx/'});
  }
  const filter=$('recent-filter').value;
  const visible=items.filter(item=>filter==='all'||item.kind===filter).sort((a,b)=>b.time-a.time).slice(0,8);
  $('recent-rows').replaceChildren();
  for(const item of visible){
    const tr=document.createElement('tr');
    for(const value of [item.time?new Date(item.time).toLocaleString():'—',item.label,item.amount]){const td=document.createElement('td');td.textContent=value;tr.append(td);}
    const status=document.createElement('td'),tag=document.createElement('span');tag.className='badge '+(['finalized','completed'].includes(item.status)?'good':item.status==='failed'?'bad':'warn');tag.textContent=item.status.replaceAll('_',' ');status.append(tag);tr.append(status);
    const receipt=document.createElement('td');if(item.signature){const link=document.createElement('a');link.href=item.url+encodeURIComponent(item.signature);link.target='_blank';link.rel='noopener noreferrer';link.textContent=short(item.signature);receipt.append(link);}else receipt.textContent='—';tr.append(receipt);$('recent-rows').append(tr);
  }
  $('recent-empty').hidden=visible.length>0;
  $('recent-empty').textContent=data.proceeds?.updated_at?'No recorded transactions match this filter.':'Loading transaction history…';
}
$('recent-filter').addEventListener('change',()=>{if(recentData)renderRecent(recentData);});

function renderTimeline(activity,now,bridge){
  const list=$('activity-timeline');
  const events=(activity?.events||[]).filter(event=>event.level==='good'&&/^(FINALIZED|COMPLETED) · /.test(event.message||'')).slice(-5).reverse();
  badge('timeline-status',activity?.checked_at&&now-activity.checked_at<20?'Finalized only':'Waiting / stale',activity?.checked_at&&now-activity.checked_at<20?'good':'warn');
  const fingerprint=JSON.stringify([Boolean(activity),...events.map(e=>[e.id,e.level,e.message,e.at,e.source==='bridge'?(bridge?.entries||[]).find(row=>row.signature===e.signature)?.destination_signature:null])]);
  if(list.dataset.fingerprint===fingerprint)return;
  list.dataset.fingerprint=fingerprint;list.replaceChildren();
  if(!events.length){const item=document.createElement('li');item.className='muted';item.textContent=activity?'No finalized activity recorded yet.':'Activity feed unavailable.';list.append(item);return;}
  const labels={spy:'SPY.X',spcx:'SPCX.X',tsla:'TSLA.X',meta:'META.X',coin:'COIN.X',pltr:'PLTR.X',amd:'AMD.X',nvda:'NVDA.X',googl:'GOOGL.X',conversion:'XNT → USDC.X',bridge:'USDC.X → Solana',system:'System'};
  for(const event of events){
    const item=document.createElement('li');item.className='timeline-event '+(event.level||'');
    const marker=document.createElement('span');marker.className='timeline-marker';marker.setAttribute('aria-hidden','true');marker.textContent=event.level==='good'?'✓':event.level==='bad'?'!':'◷';
    const body=document.createElement('div');body.className='timeline-body';
    const heading=document.createElement('div');heading.className='timeline-heading';
    const title=document.createElement('strong');title.textContent=labels[event.source]||'System';
    const time=document.createElement('time');if(Number.isFinite(event.at)){time.dateTime=new Date(event.at*1000).toISOString();time.textContent=new Date(event.at*1000).toLocaleTimeString();time.title=new Date(event.at*1000).toLocaleString();}else time.textContent='Time unavailable';
    heading.append(title,time);const message=document.createElement('p');message.textContent=event.message||'Status update';body.append(heading,message);
    if(event.signature){const destination=event.source==='bridge'?(bridge?.entries||[]).find(row=>row.signature===event.signature)?.destination_signature:null;const link=document.createElement('a');link.href=(destination?'https://solscan.io/tx/':'https://explorer.mainnet.x1.xyz/tx/')+encodeURIComponent(destination||event.signature);link.target='_blank';link.rel='noopener noreferrer';link.textContent=destination?'View Solana receipt ↗':'View X1 transaction ↗';body.append(link);}
    item.append(marker,body);list.append(item);
  }
}

let previewFingerprint='';
function renderPreview(data){
  const specs=[['googl','GOOGL.X','GOOGL.X / USDC.X','googl'],['tsla','TSLA.X','TSLA.X / XNT','tsla'],['meta','META.X','META.X / XNT','meta']];
  const values=specs.map(([key,symbol,name])=>{const market=key==='googl'?data.chain:data[key];return {key,symbol,name,balance:key==='googl'?market?.googl:market?.balance,price:key==='googl'?market?.pool_price:market?.price_usd,gap:key==='googl'?data.gap_percent:market?.gap_percent,running:data.workers?.[key]?.running,mode:data.workers?.[key]?.mode,fresh:key==='googl'?data.market_fresh:market?.fresh};});
  const fingerprint=JSON.stringify(values);if(fingerprint===previewFingerprint)return;previewFingerprint=fingerprint;
  const container=$('overview-cards');container.replaceChildren();
  for(const value of values){
    const card=document.createElement('article');card.className='panel preview-card';
    const top=document.createElement('div');top.className='preview-top';
    const icon=document.createElement('span');icon.className='asset-icon '+value.key;icon.textContent=value.symbol[0];icon.setAttribute('aria-hidden','true');
    const name=document.createElement('div');const title=document.createElement('h3');title.textContent=value.symbol;const subtitle=document.createElement('small');subtitle.textContent=value.name;name.append(title,subtitle);
    const tag=document.createElement('span');tag.className='badge '+(value.running===true&&value.mode==='live'?'good':value.running==null||value.running===true?'warn':'');tag.textContent=value.running===true?(value.mode==='live'?'Live':value.mode==='simulation'?'Simulation':'Running'):value.running===false?'Stopped':'Unknown';top.append(icon,name,tag);
    const metrics=document.createElement('div');metrics.className='preview-metrics';
    for(const [label,textValue] of [['Balance',value.balance==null?'—':fmt(value.balance,8)+' '+value.symbol],['Spot premium',value.gap==null?'—':(Number(value.gap)>=0?'+':'')+Number(value.gap).toFixed(2)+'%']]){const block=document.createElement('div');const small=document.createElement('small');small.textContent=label;const strong=document.createElement('strong');strong.textContent=textValue;if(label==='Spot premium'&&value.gap!=null&&Number(value.gap)>0)strong.className='mint';strong.title=textValue;block.append(small,strong);if(label==='Balance'){const estimate=balanceEstimate(value.balance,value.price,value.fresh===true),caption=document.createElement('small');caption.className='balance-value';caption.textContent=estimate==null?'Estimated value: —':'Estimated value: '+money(estimate);caption.title=estimate==null?'Current X1 spot price unavailable':`${value.balance} ${value.symbol} × ${value.price} at X1 spot; estimate only`;block.append(caption);}metrics.append(block);}
    const footer=document.createElement('div');footer.className='preview-footer';const freshness=document.createElement('small');freshness.textContent=value.fresh?'Market data current':'Market data stale or unavailable';const link=document.createElement('a');link.href=value.key==='googl'?'#googl-controls':'#strategies';link.textContent='Manage →';footer.append(freshness,link);
    card.append(top,metrics,footer);container.append(card);
  }
}

function updateNavigation(){const hash=location.hash;const active=hash==='#stock-purchase'?'stock-purchase':hash==='#strategies'||hash==='#automation'||hash==='#googl-controls'?'strategies':hash==='#transaction-section'||hash==='#history'?'transactions':'overview';for(const link of document.querySelectorAll('.site-header nav a')){if(link.dataset.nav===active)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');}}
window.addEventListener('hashchange',updateNavigation);updateNavigation();
$('open-logs').addEventListener('click',()=>{$('detailed-logs').open=true;});
