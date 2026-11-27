import fs from 'node:fs';
const load=f=>{ const s=fs.readFileSync(f,'utf8'); const a=s.indexOf('function pivotHi('), b=s.indexOf('// closed candles only'); return new Function(s.slice(a,b)+'; return msRun;')(); };
const NEW=load('research/new_index.html'), OLD=load('research/old_index.html');
const ws=new WebSocket('wss://api.derivws.com/trading/v1/options/ws/public'); await new Promise(r=>ws.onopen=r);
let id=0; const pend=new Map(); ws.onmessage=e=>{ const m=JSON.parse(e.data); const p=pend.get(m.req_id); if(p){ pend.delete(m.req_id); p(m); } };
const ask=q=>new Promise(r=>{ const k=++id; pend.set(k,r); ws.send(JSON.stringify({...q,req_id:k})); });
const base={len1:3,len2:4,len3:5,len4:5,fast:3,leg:true,internal:false,rearm:true,lock:true,maxEvents:30,bos:true,mss:true,sweep:true,riser:true};
for(const [g,len] of [[900,5],[3600,5],[14400,4]]){ const h=await ask({ticks_history:'frxXAUUSD',count:500,end:'latest',style:'candles',granularity:g}); const bars=(h.candles||[]).map(c=>({time:+c.epoch,open:+c.open,high:+c.high,low:+c.low,close:+c.close})).slice(0,-1);
  const last200=bars[bars.length-200].time;
  for(const [name,fn,o] of [['OLD (before fix)',OLD,{...base,disp:true}],['NEW 50% rule',NEW,{...base,disp:false,conf:'half'}],['NEW pivot mode',NEW,{...base,disp:false,conf:'pivot'}]]){
    const r=fn(bars,len,o); const ev=r.events.filter(e=>e.t2>=last200); const c={}; ev.forEach(e=>c[e.k]=(c[e.k]||0)+1);
    console.log(`gold ${g/60}m`.padEnd(10),name.padEnd(18),'trend',r.trend,'| range high',r.rHi==null?'NONE':r.rHi,'| range low',r.rLo==null?'NONE':r.rLo,'| marks in last 200 candles',JSON.stringify(c)); } }
ws.close();
