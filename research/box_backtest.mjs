// Big-move box breakout backtest — same rules as BiasDesk_BigMoveBox_Strategy.pine
// Data: Deriv 15m candles (public API). Run: node research/box_backtest.mjs frxXAUUSD 900 3
const [SYM='frxXAUUSD', G='900', YEARS='3'] = process.argv.slice(2); const g=+G;
const DERIV='wss://api.derivws.com/trading/v1/options/ws/public';
async function fetchAll(){ const ws=new WebSocket(DERIV); await new Promise((r,j)=>{ ws.onopen=r; ws.onerror=j; });
  let id=0; const pend=new Map(); ws.onmessage=e=>{ const m=JSON.parse(e.data); const p=pend.get(m.req_id); if(p){ pend.delete(m.req_id); p(m); } };
  const ask=q=>new Promise(r=>{ const k=++id; pend.set(k,r); ws.send(JSON.stringify({...q,req_id:k})); setTimeout(()=>{ if(pend.has(k)){ pend.delete(k); r({error:{message:'timeout'}}); } },20000); });
  const stop=Math.floor(Date.now()/1000)-(+YEARS)*365*86400; let end='latest', all=new Map(), guard=0, lastOldest=Infinity;
  while(guard++<400){ const m=await ask({ticks_history:SYM,adjust_start_time:1,count:1000,end,style:'candles',granularity:g});
    if(m.error){ console.error('deriv error', m.error.message); break; } const cs=(m.candles||[]).map(c=>({t:+c.epoch,o:+c.open,h:+c.high,l:+c.low,c:+c.close}));
    if(!cs.length) break; cs.forEach(c=>all.set(c.t,c)); const oldest=Math.min(...cs.map(c=>c.t)); if(oldest>=lastOldest) break; lastOldest=oldest; if(oldest<=stop) break; end=oldest-1; }
  ws.close(); return [...all.values()].sort((a,b)=>a.t-b.t).filter(c=>c.t>=stop); }
// time zone helpers
const fmt=new Intl.DateTimeFormat('en-US',{timeZone:'America/New_York',hourCycle:'h23',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',weekday:'short'});
function ny(t){ const p={}; fmt.formatToParts(new Date(t*1000)).forEach(x=>p[x.type]=x.value); return {d:`${p.year}-${p.month}-${p.day}`,mins:+p.hour*60+ +p.minute,wd:p.weekday}; }
function run(B,o){ const W0=o.w0??500, W1=o.w1??570, cutoff=(o.cutoffH??3)*3600, rr=o.rr??2, partR=o.partR??1, partPct=o.part??.5, beR=o.beR??1, lock=o.lock??0.02, cost=o.cost??0;
  // daily ATR (NY 17:00 sessions), RMA 14, previous day
  const days=[]; let cur=null; for(const b of B){ const n=ny(b.t+7*3600); /* shift so the day starts 17:00 NY */ if(!cur||cur.d!==n.d){ cur={d:n.d,h:b.h,l:b.l,c:b.c,o:b.o}; days.push(cur); } else { cur.h=Math.max(cur.h,b.h); cur.l=Math.min(cur.l,b.l); cur.c=b.c; } }
  const atr={}; let a=null; for(let i=1;i<days.length;i++){ const d=days[i], pc=days[i-1].c, tr=Math.max(d.h,pc)-Math.min(d.l,pc); a=a==null?tr:(a*13+tr)/14; if(i+1<days.length) atr[days[i+1].d]=a; }
  let ema=null; const k=2/201; const trades=[]; let box=null, pos=null;
  for(let i=0;i<B.length;i++){ const b=B[i], n=ny(b.t); ema=ema==null?b.c:ema+(b.c-ema)*k; const dayKey=ny(b.t+7*3600).d;
    const weekday=!['Sat','Sun'].includes(n.wd); const inW=weekday&&n.mins>=W0&&n.mins<W1;
    // manage open position on this bar (orders placed at previous close)
    if(pos){ const s=pos.side, R=pos.risk; const stopNow=pos.be?pos.e+s*lock:pos.stop; const hitStop=s>0?b.l<=stopNow:b.h>=stopNow;
      const t1=pos.e+s*partR*R, t2=pos.e+s*rr*R; const hit1=!pos.p1&&(s>0?b.h>=t1:b.l<=t1), hit2=s>0?b.h>=t2:b.l<=t2;
      if(hitStop){ pos.res+=(pos.p1?(1-partPct):1)*((stopNow-pos.e)*s/R); pos.done=true; }       // conservative: stop first
      else { if(hit1){ pos.p1=true; pos.res+=partPct*partR; } if(hit2){ pos.res+=(pos.p1?(1-partPct):1)*rr; pos.done=true; } }
      if(!pos.done&&o.be!==false&&!pos.be&&(s>0?b.h>=pos.e+beR*R:b.l<=pos.e-beR*R)) pos.be=true;
      if(!pos.done&&n.mins>=16*60+55&&n.mins<17*60+10){ pos.res+=(pos.p1?(1-partPct):1)*((b.c-pos.e)*s/R); pos.done=true; }
      if(pos.done){ pos.res-=cost/R; trades.push(pos); pos=null; } }
    if(inW){ if(!box||box.d!==n.d||box.closed){ box={d:n.d,hi:b.h,lo:b.l,closed:false,end:null,done:false}; } else { box.hi=Math.max(box.hi,b.h); box.lo=Math.min(box.lo,b.l); } continue; }
    if(box&&!box.closed&&box.d===n.d){ box.closed=true; box.end=b.t; }
    if(box&&box.closed&&!box.done){ if(b.t-box.end>cutoff){ box.done=true; continue; }
      const up=b.c>box.hi, dn=b.c<box.lo; if(!up&&!dn) continue; box.done=true;
      const size=box.hi-box.lo, dA=atr[dayKey]; if(dA&&(size<(o.minD??.05)*dA||size>(o.maxD??.6)*dA)) continue;
      const side=up?1:-1; if(o.dir&&o.dir!==side) continue; if(o.ema&&(side>0?b.c<ema:b.c>ema)) continue; if(pos) continue;
      const stop=o.mid?(box.hi+box.lo)/2:(side>0?box.lo:box.hi); const risk=(b.c-stop)*side; if(risk<=0) continue;
      pos={t:b.t,side,e:b.c,stop,risk,res:0,p1:false,be:false,done:false,year:n.d.slice(0,4)}; } }
  return trades; }
function stats(tr){ const n=tr.length; if(!n) return {n:0}; const r=tr.map(x=>x.res); const sum=r.reduce((a,b)=>a+b,0), avg=sum/n; const w=r.filter(x=>x>0), l=r.filter(x=>x<0);
  const gp=w.reduce((a,b)=>a+b,0), gl=-l.reduce((a,b)=>a+b,0); const sd=Math.sqrt(r.reduce((a,b)=>a+(b-avg)**2,0)/Math.max(1,n-1));
  let eq=0,pk=0,dd=0; for(const x of r){ eq+=x; pk=Math.max(pk,eq); dd=Math.max(dd,pk-eq); }
  return {n,win:Math.round(w.length/n*100),pf:gl?+(gp/gl).toFixed(2):null,avgR:+avg.toFixed(3),totalR:+sum.toFixed(1),t:+(avg/(sd/Math.sqrt(n))).toFixed(2),maxDD:+dd.toFixed(1)}; }
const B=await fetchAll(); console.log(`data: ${SYM} ${g/60}m candles: ${B.length}, from ${new Date(B[0].t*1000).toISOString().slice(0,10)} to ${new Date(B.at(-1).t*1000).toISOString().slice(0,10)}`);
const row=(name,o)=>{ const tr=run(B,o); const s=stats(tr); console.log(name.padEnd(46),JSON.stringify(s)); return tr; };
console.log('\n=== Variants (results in R; 1R = the box-side stop distance) ===');
const base=row('Both directions (as in TradingView)',{});
row('Sell breaks only',{dir:-1}); row('Buy breaks only',{dir:1});
row('Both + 200-EMA filter',{ema:true}); row('Sell only + 200-EMA filter',{dir:-1,ema:true});
row('Both, stop at middle of box',{mid:true}); row('Both, no partial / no BE, 2R',{part:0,be:false});
for(const rr of [1,1.5,3]) row(`Both, target ${rr}R`,{rr});
console.log('\n=== Costs (spread+slippage per round trip, in $ of gold price) ===');
for(const cost of [0.2,0.4,0.6]) { row(`Both, cost $${cost}`,{cost}); row(`Sell only, cost $${cost}`,{dir:-1,cost}); }
console.log('\n=== By year (Both, cost $0.4) ===');
const all=run(B,{cost:0.4}); const yrs=[...new Set(all.map(t=>t.year))]; for(const y of yrs) console.log(y.padEnd(46),JSON.stringify(stats(all.filter(t=>t.year===y))));
console.log('\n=== By year (Sell only, cost $0.4) ===');
const so=run(B,{dir:-1,cost:0.4}); for(const y of yrs) console.log(y.padEnd(46),JSON.stringify(stats(so.filter(t=>t.year===y))));
const half=Math.floor(B.length/2), A1=B.slice(0,half), A2=B.slice(half);
console.log('\n=== First half vs second half (Both, cost $0.4) ===');
console.log('first half'.padEnd(46),JSON.stringify(stats(run(A1,{cost:0.4})))); console.log('second half'.padEnd(46),JSON.stringify(stats(run(A2,{cost:0.4}))));
