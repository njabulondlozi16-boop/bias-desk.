// Trade-quality score research: do regime features separate winning from losing Bias Desk signals?
// Signals: S/B step-in (spAnalyse), ⚡ scalp (scAnalyse), big-move box breakout. Data: Deriv 15m, ~1 year.
import fs from 'node:fs';
const SYMS=(process.argv[2]||'frxXAUUSD,OTC_DJI,OTC_NDX,cryBTCUSD').split(','); const g=900;
const src=fs.readFileSync('index.html','utf8'); const a=src.indexOf('const SP_DEF='), b=src.indexOf('function scStats(');
const lib=new Function('lsGet', src.slice(a,b)+'; return {spAnalyse,scAnalyse,swingTrend,scTrendAt};')(()=>({}));
const DERIV='wss://api.derivws.com/trading/v1/options/ws/public';
async function fetchAll(SYM,gran,years){ if(process.env.SYNTH){ let p=2000,t=Math.floor(Date.now()/1000/900)*900-20000*900,o=[]; for(let k=0;k<20000;k++){ const c=p*(1+(Math.random()-.5)*0.004); o.push({time:t+k*900,open:p,high:Math.max(p,c)*(1+Math.random()*.001),low:Math.min(p,c)*(1-Math.random()*.001),close:c}); p=c; } return o; } const ws=new WebSocket(DERIV); await new Promise((r,j)=>{ ws.onopen=r; ws.onerror=j; });
  let id=0; const pend=new Map(); ws.onmessage=e=>{ const m=JSON.parse(e.data); const p=pend.get(m.req_id); if(p){ pend.delete(m.req_id); p(m); } };
  const ask=q=>new Promise(r=>{ const k=++id; pend.set(k,r); ws.send(JSON.stringify({...q,req_id:k})); setTimeout(()=>{ if(pend.has(k)){ pend.delete(k); r({error:{message:'timeout'}}); } },20000); });
  const stop=Math.floor(Date.now()/1000)-years*365*86400; let end='latest', all=new Map(), guard=0, lastOldest=Infinity;
  while(guard++<400){ const m=await ask({ticks_history:SYM,adjust_start_time:1,count:1000,end,style:'candles',granularity:gran});
    if(m.error){ console.error(SYM,'deriv error',m.error.message); break; } const cs=(m.candles||[]).map(c=>({time:+c.epoch,open:+c.open,high:+c.high,low:+c.low,close:+c.close}));
    if(!cs.length) break; cs.forEach(c=>all.set(c.time,c)); const oldest=Math.min(...cs.map(c=>c.time)); if(oldest>=lastOldest) break; lastOldest=oldest; if(oldest<=stop) break; end=oldest-1; }
  ws.close(); let out=[...all.values()].sort((x,y)=>x.time-y.time).filter(c=>c.time>=stop); if(/^OTC_/i.test(SYM)) out=out.filter(x=>x.high>x.low); return out; }
function resample(B,G){ const m=new Map(); for(const x of B){ const k=Math.floor(x.time/G)*G; const c=m.get(k); if(!c) m.set(k,{time:k,open:x.open,high:x.high,low:x.low,close:x.close}); else { c.high=Math.max(c.high,x.high); c.low=Math.min(c.low,x.low); c.close=x.close; } } return [...m.values()]; }
// ---- features (only data up to and including bar i) ----
function features(B){ const n=B.length, tr=B.map((x,i)=>{ const pc=i?B[i-1].close:x.open; return Math.max(x.high,pc)-Math.min(x.low,pc); });
  const er=new Array(n).fill(null), atr=new Array(n).fill(null), hu=new Array(n).fill(null);
  let a=null; for(let i=0;i<n;i++){ a=a==null?tr[i]:(a*13+tr[i])/14; atr[i]=a;
    if(i>=20){ let s=0; for(let j=i-19;j<=i;j++) s+=Math.abs(B[j].close-B[j-1].close); er[i]=s?Math.abs(B[i].close-B[i-20].close)/s:0; }
    if(i>=129&&i%1===0) hu[i]=hurst(B,i); }
  const pct=(arr,i,L)=>{ const v=arr[i]; if(v==null) return null; let c=0,t=0; for(let j=Math.max(0,i-L);j<i;j++){ if(arr[j]!=null){ t++; if(arr[j]<v) c++; } } return t>50?c/t:null; };
  return {er,atr,hu,erP:i=>pct(er,i,300),atrP:i=>pct(atr,i,500)}; }
function hurst(B,i){ const r=[]; for(let j=i-127;j<=i;j++) r.push(Math.log(B[j].close/B[j-1].close)); const xs=[],ys=[];
  for(const w of [8,16,32,64,128]){ let acc=0,cnt=0; for(let s=0;s+w<=128;s+=w){ const seg=r.slice(s,s+w), m=seg.reduce((p,q)=>p+q,0)/w; let cum=0,mx=-Infinity,mn=Infinity,v=0; for(const x of seg){ cum+=x-m; mx=Math.max(mx,cum); mn=Math.min(mn,cum); v+=(x-m)**2; } const sd=Math.sqrt(v/w); if(sd>0){ acc+=(mx-mn)/sd; cnt++; } }
    if(cnt){ xs.push(Math.log(w)); ys.push(Math.log(acc/cnt)); } }
  const mx=xs.reduce((p,q)=>p+q,0)/xs.length, my=ys.reduce((p,q)=>p+q,0)/ys.length; let num=0,den=0; xs.forEach((x,k)=>{ num+=(x-mx)*(ys[k]-my); den+=(x-mx)**2; }); return den?num/den:null; }
// ---- box breakout signals ----
const fmt=new Intl.DateTimeFormat('en-US',{timeZone:'America/New_York',hourCycle:'h23',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',weekday:'short'});
function ny(t){ const p={}; fmt.formatToParts(new Date(t*1000)).forEach(x=>p[x.type]=x.value); return {d:`${p.year}-${p.month}-${p.day}`,mins:+p.hour*60+ +p.minute,wd:p.weekday}; }
function boxSignals(B,W0,W1){ const out=[]; let box=null, pos=null;
  for(let i=0;i<B.length;i++){ const b=B[i], n=ny(b.time); const wk=!['Sat','Sun'].includes(n.wd), inW=wk&&n.mins>=W0&&n.mins<W1;
    if(pos){ const s=pos.side,R=pos.risk, st=pos.be?pos.e+s*0.02*0:pos.stop; const hs=s>0?b.low<=st:b.high>=st, t1=pos.e+s*R, t2=pos.e+s*2*R;
      if(hs){ pos.res+=(pos.p1?.5:1)*((st-pos.e)*s/R); pos.done=1; } else { if(!pos.p1&&(s>0?b.high>=t1:b.low<=t1)){ pos.p1=1; pos.be=1; pos.res+=.5; } if(s>0?b.high>=t2:b.low<=t2){ pos.res+=(pos.p1?.5:1)*2; pos.done=1; } }
      if(!pos.done&&n.mins>=1015&&n.mins<1030){ pos.res+=(pos.p1?.5:1)*((b.close-pos.e)*s/R); pos.done=1; }
      if(pos.done){ out.push({fam:'box',i:pos.i,side:pos.side,R:pos.res}); pos=null; } }
    if(inW){ if(!box||box.d!==n.d||box.closed) box={d:n.d,hi:b.high,lo:b.low,closed:0,end:0,done:0}; else { box.hi=Math.max(box.hi,b.high); box.lo=Math.min(box.lo,b.low); } continue; }
    if(box&&!box.closed&&box.d===n.d){ box.closed=1; box.end=b.time; }
    if(box&&box.closed&&!box.done){ if(b.time-box.end>3*3600){ box.done=1; continue; } const up=b.close>box.hi, dn=b.close<box.lo; if(!up&&!dn) continue; box.done=1; if(pos) continue;
      const side=up?1:-1, stop=up?box.lo:box.hi, risk=(b.close-stop)*side; if(risk>0) pos={i,side,e:b.close,stop,risk,res:0,p1:0,be:0,done:0}; } }
  return out; }
function stats(r){ const n=r.length; if(!n) return {n:0}; const s=r.reduce((p,q)=>p+q,0), m=s/n, sd=Math.sqrt(r.reduce((p,q)=>p+(q-m)**2,0)/Math.max(1,n-1)); const gp=r.filter(x=>x>0).reduce((p,q)=>p+q,0), gl=-r.filter(x=>x<0).reduce((p,q)=>p+q,0);
  return {n,win:Math.round(r.filter(x=>x>0).length/n*100),avgR:+m.toFixed(3),totR:+s.toFixed(1),pf:gl?+(gp/gl).toFixed(2):null,t:sd?+(m/(sd/Math.sqrt(n))).toFixed(2):0}; }
// ---- collect ----
const T=[];
for(const SYM of SYMS){ const B=await fetchAll(SYM,g,2); if(B.length<500){ console.log(SYM,'too little data',B.length); continue; }
  console.log(`data ${SYM}: ${B.length} bars ${new Date(B[0].time*1000).toISOString().slice(0,10)} → ${new Date(B.at(-1).time*1000).toISOString().slice(0,10)}`);
  const F=features(B); const H4=resample(B,14400), tr4=lib.swingTrend(H4); const H1=resample(B,3600), H={bars:H1,trend:lib.swingTrend(H1)};
  const b4=t=>{ let lo=0,hi=H4.length-1,ans=-1; while(lo<=hi){ const m=(lo+hi)>>1; if(H4[m].time+14400<=t){ ans=m; lo=m+1; } else hi=m-1; } return ans<0?0:tr4[ans]; };
  const sigs=[];
  for(const r of lib.spAnalyse(B,null)){ if((r.kind==='S'||r.kind==='B')&&r.state==='ok'&&r.r1!=null) sigs.push({fam:'S/B',i:r.i+1,side:r.kind==='S'?-1:1,R:r.r1===1?1:-1}); }
  for(const s of lib.scAnalyse(B,null,H,3600,g)){ if(s.r1!=null) sigs.push({fam:'scalp',i:s.i,side:s.side,R:s.r1===0?-1:.5+(s.r2===1?1:0)}); }
  const W=SYM==='frxXAUUSD'?[500,570]:[570,630]; sigs.push(...boxSignals(B,W[0],W[1]));
  for(const s of sigs){ const i=s.i; if(i>=B.length) continue; const erP=F.erP(i), atP=F.atrP(i), h=F.hu[i]; if(erP==null||atP==null||h==null) continue;
    const bias=b4(B[i].time+g)*s.side; T.push({sym:SYM,...s,t:B[i].time,erP,atP,h,bias}); } }
// a-priori score (fixed before looking at results): 4H bias 30, efficiency 25, Hurst 20, volatility (mid best) 25
const score=x=>Math.round(30*(x.bias>0?1:x.bias===0?.5:0)+25*x.erP+20*Math.min(1,Math.max(0,(x.h-.4)/.25))+25*Math.max(0,1-Math.abs(x.atP-.55)/.55));
T.forEach(x=>x.q=score(x)); const line=(l,r)=>console.log(l.padEnd(40),JSON.stringify(stats(r)));
console.log(`\nsignals with features: ${T.length}`);
console.log('\n=== All signals, baseline ==='); line('all',T.map(x=>x.R)); for(const f of ['S/B','scalp','box']) line(f,T.filter(x=>x.fam===f).map(x=>x.R)); for(const s of SYMS) line(s,T.filter(x=>x.sym===s).map(x=>x.R));
const terc=(key,lab)=>{ const v=T.map(x=>x[key]).sort((p,q)=>p-q), c1=v[Math.floor(v.length/3)], c2=v[Math.floor(v.length*2/3)]; console.log(`\n--- ${lab} (cuts ${c1.toFixed(2)} / ${c2.toFixed(2)}) ---`);
  line(' low third',T.filter(x=>x[key]<c1).map(x=>x.R)); line(' mid third',T.filter(x=>x[key]>=c1&&x[key]<c2).map(x=>x.R)); line(' high third',T.filter(x=>x[key]>=c2).map(x=>x.R)); };
console.log('\n=== Each feature alone ==='); terc('erP','Efficiency ratio percentile'); terc('atP','ATR percentile'); terc('h','Hurst exponent');
console.log('\n--- 4H bias agreement ---'); line(' with 4H trend',T.filter(x=>x.bias>0).map(x=>x.R)); line(' 4H neutral',T.filter(x=>x.bias===0).map(x=>x.R)); line(' against 4H trend',T.filter(x=>x.bias<0).map(x=>x.R));
console.log('\n--- ATR extremes ---'); line(' ATR pct < 0.15 (dead)',T.filter(x=>x.atP<.15).map(x=>x.R)); line(' ATR pct 0.15–0.85',T.filter(x=>x.atP>=.15&&x.atP<=.85).map(x=>x.R)); line(' ATR pct > 0.85 (wild)',T.filter(x=>x.atP>.85).map(x=>x.R));
const buck=(arr,l)=>{ console.log(`\n=== Quality score buckets: ${l} ===`); line(' red   (<45)',arr.filter(x=>x.q<45).map(x=>x.R)); line(' amber (45–64)',arr.filter(x=>x.q>=45&&x.q<65).map(x=>x.R)); line(' green (65+)',arr.filter(x=>x.q>=65).map(x=>x.R)); line(' skip red only',arr.filter(x=>x.q>=45).map(x=>x.R)); };
buck(T,'all'); for(const f of ['S/B','scalp','box']) buck(T.filter(x=>x.fam===f),f); for(const s of SYMS) buck(T.filter(x=>x.sym===s),s);
const ts=T.map(x=>x.t).sort((p,q)=>p-q), mid=ts[Math.floor(ts.length/2)]; buck(T.filter(x=>x.t<mid),'first half of the year'); buck(T.filter(x=>x.t>=mid),'second half of the year');
