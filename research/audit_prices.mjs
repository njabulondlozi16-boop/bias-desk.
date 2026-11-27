// Accuracy audit 1: Bias Desk's own symbol matching on the live Deriv feed, prices vs independent sources, candle anchors, tick density.
import fs from 'node:fs';
const src=fs.readFileSync('index.html','utf8'); const grab=(a,b)=>{ const i=src.indexOf(a), j=src.indexOf(b,i); return src.slice(i,j); };
const code=grab('const DEFAULT_INSTRUMENTS=[','const SYNTH_DEFAULTS')+'\nconst mapping=new Map();\nfunction isBinance(i){ return i.type==="Crypto"; }\n'+grab('function norm(s)','// Normalise active_symbols')+grab('function normActive(','\n')+'\nreturn {DEFAULT_INSTRUMENTS,matchSymbols,normActive,mapping};';
const L=new Function('getInstruments','lsGet',code).call(null,()=>L2.DEFAULT_INSTRUMENTS,()=>null);
var L2=L; // getInstruments closure reads L2
const ws=new WebSocket('wss://api.derivws.com/trading/v1/options/ws/public'); await new Promise(r=>ws.onopen=r);
let id=0; const pend=new Map(); ws.onmessage=e=>{ const m=JSON.parse(e.data); const p=pend.get(m.req_id); if(p){ pend.delete(m.req_id); p(m); } };
const ask=q=>new Promise(r=>{ const k=++id; pend.set(k,r); ws.send(JSON.stringify({...q,req_id:k})); setTimeout(()=>{ if(pend.has(k)){ pend.delete(k); r({error:{message:'timeout'}}); } },20000); });
const act=L.normActive((await ask({active_symbols:'brief'})).active_symbols); L.matchSymbols(act);
const STOOQ={XAUUSD:'xauusd',XAGUSD:'xagusd',EURUSD:'eurusd',GBPUSD:'gbpusd',AUDUSD:'audusd',NZDUSD:'nzdusd',USDCHF:'usdchf',US30:'^dji',US100:'^ndx',GER30:'^dax',USDX:'dx.f'};
async function stooq(s){ try{ const r=await fetch(`https://stooq.com/q/l/?s=${encodeURIComponent(s)}&f=sd2t2ohlc&h&e=csv`); const t=await r.text(); const row=t.trim().split('\n')[1].split(','); return {date:row[1],time:row[2],close:+row[6]}; }catch(e){ return {err:String(e.message||e)}; } }
console.log('\n=== 1. Symbol matching + live price vs independent source ===');
for(const inst of L.DEFAULT_INSTRUMENTS){ if(inst.type==='Synthetic') continue; let feed='', px=null;
  if(inst.type==='Crypto'){ feed='Binance BTCUSDT'; const r=await (await fetch('https://data-api.binance.vision/api/v3/ticker/price?symbol=BTCUSDT')).json(); px=+r.price; }
  else { const m=L.mapping.get(inst.symbol)||{}; const a=act.find(x=>x.symbol===m.deriv); feed=`${m.deriv||'NOT FOUND'} (${a?a.display_name:'-'})`; if(m.deriv){ const h=await ask({ticks_history:m.deriv,count:1,end:'latest',style:'ticks'}); px=h.history?+h.history.prices[0]:null; } }
  let ref='', diff=''; if(STOOQ[inst.symbol]){ const q=await stooq(STOOQ[inst.symbol]); if(q.close){ ref=`stooq ${STOOQ[inst.symbol]} ${q.close} (${q.date} ${q.time})`; if(px) diff=((px/q.close-1)*100).toFixed(3)+'%'; } else ref='stooq: '+(q.err||'n/a'); }
  if(inst.type==='Crypto'){ try{ const cg=await (await fetch('https://api.coinbase.com/v2/prices/BTC-USD/spot')).json(); const c=+cg.data.amount; ref=`coinbase ${c}`; diff=((px/c-1)*100).toFixed(3)+'%'; }catch(e){} }
  console.log(`${inst.symbol.padEnd(7)} feed=${feed.padEnd(40)} price=${px}  | ${ref}  diff=${diff}`); }
console.log('\n=== 2. Candle anchors on the feed (UTC hour of each candle open) ===');
for(const [sym,g] of [['frxXAUUSD',14400],['frxXAUUSD',86400],['frxEURUSD',14400],['OTC_DJI',14400],['OTC_DJI',86400]]){ const h=await ask({ticks_history:sym,count:8,end:'latest',style:'candles',granularity:g}); console.log(sym,g===86400?'1D':'4H', (h.candles||[]).map(c=>new Date(c.epoch*1000).toISOString().slice(5,16).replace('T',' ')).join(' | ')); }
console.log('\n=== 3. Tick density (ticks in the last hour) ===');
for(const sym of ['frxXAUUSD','frxEURUSD','OTC_DJI','frxXAGUSD','WLDUSD']){ const end=Math.floor(Date.now()/1000), st=end-3600; let n=0,lo=st,hi=end,guard=0; while(guard++<40){ const h=await ask({ticks_history:sym,start:lo,end:hi,count:5000,style:'ticks'}); const T=(h.history&&h.history.times)||[]; n+=T.filter(t=>t>=lo&&t<=hi).length; if(T.length<1000) break; hi=+T[0]-1; if(hi<=lo) break; } console.log(sym.padEnd(10),'ticks/hour ≈',n); }
console.log('\n=== 4. Deriv vs stooq daily candles (last 5 days close, gold and Dow) ===');
for(const [sym,sq] of [['frxXAUUSD','xauusd'],['OTC_DJI','^dji']]){ const h=await ask({ticks_history:sym,count:6,end:'latest',style:'candles',granularity:86400}); const d=(h.candles||[]).map(c=>`${new Date(c.epoch*1000).toISOString().slice(5,10)}:${(+c.close).toFixed(1)}`).join(' ');
  let s=''; try{ const t=await (await fetch(`https://stooq.com/q/d/l/?s=${encodeURIComponent(sq)}&i=d`)).text(); s=t.trim().split('\n').slice(-6).map(r=>{ const x=r.split(','); return x[0].slice(5)+':'+(+x[4]).toFixed(1); }).join(' '); }catch(e){ s='err '+e.message; }
  console.log(sym,'deriv',d,'\n'+' '.repeat(sym.length),'stooq',s); }
ws.close();
