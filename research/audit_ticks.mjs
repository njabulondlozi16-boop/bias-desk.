const ws=new WebSocket('wss://api.derivws.com/trading/v1/options/ws/public'); await new Promise(r=>ws.onopen=r);
let id=0; const pend=new Map(); ws.onmessage=e=>{ const m=JSON.parse(e.data); const p=pend.get(m.req_id); if(p){ pend.delete(m.req_id); p(m); } };
const ask=q=>new Promise(r=>{ const k=++id; pend.set(k,r); ws.send(JSON.stringify({...q,req_id:k})); setTimeout(()=>{ if(pend.has(k)){ pend.delete(k); r({error:{message:'timeout'}}); } },25000); });
async function ticks(sym,st,en){ const out=new Map(); let lo=st,hi=en,g=0; while(g++<200){ const h=await ask({ticks_history:sym,start:lo,end:hi,count:5000,style:'ticks'}); const T=(h.history&&h.history.times)||[], P=(h.history&&h.history.prices)||[]; for(let i=0;i<T.length;i++){ const t=+T[i]; if(t>=lo&&t<=hi) out.set(t,+P[i]); } if(T.length<1000) break; const f=+T[0]; if(f<=lo) break; hi=f-1; } return [...out.entries()].sort((a,b)=>a[0]-b[0]); }
console.log('=== Tick activity by hour (last 24h, UTC hour): all ticks · price-changed ticks · sum of moves ===');
for(const sym of ['frxXAUUSD','frxEURUSD','OTC_DJI']){ const en=Math.floor(Date.now()/1000), st=en-24*3600; const tk=await ticks(sym,st,en); const H={};
  for(let i=1;i<tk.length;i++){ const h=new Date(tk[i][0]*1000).getUTCHours(); const x=H[h]||(H[h]={n:0,ch:0,mv:0}); x.n++; const d=Math.abs(tk[i][1]-tk[i-1][1]); if(d>0){ x.ch++; x.mv+=d; } }
  console.log(sym,'total ticks',tk.length); console.log(Object.keys(H).sort((a,b)=>a-b).map(h=>`${String(h).padStart(2,'0')}h ${H[h].n}/${H[h].ch}/${H[h].mv.toFixed(sym==='frxEURUSD'?4:1)}`).join('  ')); }
console.log('\n=== Independent price check (Yahoo Finance) ===');
const Y={frxXAUUSD:'GC=F',frxXAGUSD:'SI=F',frxEURUSD:'EURUSD=X',frxGBPUSD:'GBPUSD=X',frxAUDUSD:'AUDUSD=X',frxNZDUSD:'NZDUSD=X',frxUSDCHF:'USDCHF=X',OTC_DJI:'^DJI',OTC_NDX:'^NDX',OTC_GDAXI:'^GDAXI',WLDUSD:'DX-Y.NYB'};
for(const [d,y] of Object.entries(Y)){ const h=await ask({ticks_history:d,count:1,end:'latest',style:'ticks'}); const px=h.history?+h.history.prices[0]:null; let ref='',diff='';
  try{ const r=await fetch(`https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(y)}?interval=1m&range=1d`,{headers:{'User-Agent':'Mozilla/5.0'}}); const j=await r.json(); const m=j.chart.result[0].meta; ref=`${y} ${m.regularMarketPrice} (${new Date(m.regularMarketTime*1000).toISOString().slice(11,16)}Z)`; if(px) diff=((px/m.regularMarketPrice-1)*100).toFixed(3)+'%'; }catch(e){ ref='yahoo err '+String(e.message||e).slice(0,60); }
  console.log(d.padEnd(10),'deriv',px,'|',ref,'diff',diff); }
try{ const r=await (await fetch('https://api.frankfurter.app/latest?from=USD&to=ZAR')).json(); console.log('\nUSDZAR (ECB via frankfurter):',r.rates&&r.rates.ZAR,r.date); }catch(e){ console.log('frankfurter err',e.message); }
try{ const r=await (await fetch('https://open.er-api.com/v6/latest/USD')).json(); console.log('USDZAR (open.er-api):',r.rates&&r.rates.ZAR,r.time_last_update_utc); }catch(e){ console.log('er-api err',e.message); }
ws.close();
