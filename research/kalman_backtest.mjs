// "Kalman trend pullback" — generic BUY/SELL indicator research. Rules fixed before testing.
// Direction: 2-state Kalman filter (level + velocity). Gate: efficiency-ratio percentile, Hurst, ATR percentile, higher-TF Kalman agreement.
// Entry: pullback to the Kalman line then a close back in the trend direction. Stop: pullback extreme ± 0.25 ATR (0.75–2.5 ATR). Target 2R. Max hold 64 bars.
// P(win): online logistic regression, updated only with trades that have already finished (walk-forward).
const SYMS=(process.argv[2]||'frxXAUUSD,OTC_DJI,OTC_NDX,frxEURUSD,frxGBPUSD,frxAUDUSD').split(',');
const COST={frxXAUUSD:0.35,OTC_DJI:3,OTC_NDX:1.5,frxEURUSD:0.0001,frxGBPUSD:0.00015,frxAUDUSD:0.00012};
const DERIV='wss://api.derivws.com/trading/v1/options/ws/public';
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function fetchAll(SYM,gran,years){ if(process.env.SYNTH){ let p=2000,t=Math.floor(Date.now()/1000/900)*900-24000*900,o=[]; for(let k=0;k<24000;k++){ const c=p*(1+(Math.random()-.5)*0.003); o.push({time:t+k*900,open:p,high:Math.max(p,c)*(1+Math.random()*.0008),low:Math.min(p,c)*(1-Math.random()*.0008),close:c}); p=c; } return o; } const ws=new WebSocket(DERIV); await new Promise((r,j)=>{ ws.onopen=r; ws.onerror=j; });
  let id=0; const pend=new Map(); ws.onmessage=e=>{ const m=JSON.parse(e.data); const p=pend.get(m.req_id); if(p){ pend.delete(m.req_id); p(m); } };
  const ask=q=>new Promise(r=>{ const k=++id; pend.set(k,r); ws.send(JSON.stringify({...q,req_id:k})); setTimeout(()=>{ if(pend.has(k)){ pend.delete(k); r({error:{message:'timeout'}}); } },20000); });
  const stop=Math.floor(Date.now()/1000)-years*365*86400; let end='latest', all=new Map(), guard=0, lastOldest=Infinity;
  while(guard++<400){ let m=await ask({ticks_history:SYM,adjust_start_time:1,count:1000,end,style:'candles',granularity:gran});
    if(m.error&&/rate limit/i.test(m.error.message)){ await sleep(15000); m=await ask({ticks_history:SYM,adjust_start_time:1,count:1000,end,style:'candles',granularity:gran}); }
    if(m.error){ console.error(SYM,'deriv error',m.error.message); break; } const cs=(m.candles||[]).map(c=>({time:+c.epoch,open:+c.open,high:+c.high,low:+c.low,close:+c.close}));
    if(!cs.length) break; cs.forEach(c=>all.set(c.time,c)); const oldest=Math.min(...cs.map(c=>c.time)); if(oldest>=lastOldest) break; lastOldest=oldest; if(oldest<=stop) break; end=oldest-1; await sleep(700); }
  ws.close(); let out=[...all.values()].sort((x,y)=>x.time-y.time).filter(c=>c.time>=stop); if(/^OTC_/i.test(SYM)) out=out.filter(x=>x.high>x.low); return out; }
function resample(B,G){ const m=new Map(); for(const x of B){ const k=Math.floor(x.time/G)*G; const c=m.get(k); if(!c) m.set(k,{time:k,open:x.open,high:x.high,low:x.low,close:x.close}); else { c.high=Math.max(c.high,x.high); c.low=Math.min(c.low,x.low); c.close=x.close; } } return [...m.values()]; }
// ---- core maths (mirrored in the Pine script) ----
function atrArr(B,n=14){ const out=[]; let a=null; for(let i=0;i<B.length;i++){ const b=B[i], pc=i?B[i-1].close:b.open, tr=Math.max(b.high,pc)-Math.min(b.low,pc); a=a==null?tr:(a*(n-1)+tr)/n; out.push(a); } return out; }
function kalman(B,atr){ let L=B[0].close,V=0,p00=1,p01=0,p11=1; const lv=[],vv=[];
  for(let i=0;i<B.length;i++){ const R=Math.max(atr[i]*atr[i],1e-12), q0=0.02*R, q1=0.0008*R;
    const Lp=L+V, Vp=V; const a00=p00+2*p01+p11+q0, a01=p01+p11, a11=p11+q1; const S=a00+R, K0=a00/S, K1=a01/S, y=B[i].close-Lp;
    L=Lp+K0*y; V=Vp+K1*y; p00=(1-K0)*a00; p01=(1-K0)*a01; p11=a11-K1*a01; lv.push(L); vv.push(V); } return {L:lv,V:vv}; }
function erArr(B,n=20){ return B.map((b,i)=>{ if(i<n) return null; let s=0; for(let j=i-n+1;j<=i;j++) s+=Math.abs(B[j].close-B[j-1].close); return s?Math.abs(b.close-B[i-n].close)/s:0; }); }
function pctRank(arr,i,L){ const v=arr[i]; if(v==null) return null; let c=0,t=0; for(let j=Math.max(0,i-L);j<i;j++){ const x=arr[j]; if(x!=null){ t++; if(x<=v) c++; } } return t>=50?c/t:null; }
function hurst(B,i){ if(i<129) return null; const r=[]; for(let j=i-127;j<=i;j++) r.push(Math.log(B[j].close/B[j-1].close)); const xs=[],ys=[];
  for(const w of [8,16,32,64,128]){ let acc=0,cnt=0; for(let s=0;s+w<=128;s+=w){ let m=0; for(let k=s;k<s+w;k++) m+=r[k]; m/=w; let cum=0,mx=-1e9,mn=1e9,v=0; for(let k=s;k<s+w;k++){ const x=r[k]-m; cum+=x; mx=Math.max(mx,cum); mn=Math.min(mn,cum); v+=x*x; } const sd=Math.sqrt(v/w); if(sd>0){ acc+=(mx-mn)/sd; cnt++; } } if(cnt){ xs.push(Math.log(w)); ys.push(Math.log(acc/cnt)); } }
  const mx=xs.reduce((p,q)=>p+q,0)/xs.length, my=ys.reduce((p,q)=>p+q,0)/ys.length; let nu=0,de=0; xs.forEach((x,k)=>{ nu+=(x-mx)*(ys[k]-my); de+=(x-mx)**2; }); return de?nu/de:null; }
function run(B,g,htfMult,cost,useGate=true){ const n=B.length, atr=atrArr(B), K=kalman(B,atr), er=erArr(B);
  const H=resample(B,g*htfMult), hatr=atrArr(H), HK=kalman(H,hatr); let hi=-1; // higher TF: last COMPLETED bar only
  const w=new Array(8).fill(0), lr=0.05, l2=0.001; const sig=x=>1/(1+Math.exp(-x)); const pending=[], trades=[]; let pos=null, armed={1:true,'-1':true};
  for(let i=0;i<n;i++){ const b=B[i];
    while(hi+1<H.length&&H[hi+1].time+g*htfMult<=b.time+g) hi++;
    // resolve finished trades → train the model
    for(let k=pending.length-1;k>=0;k--){ const t=pending[k]; if(t.done&&t.doneI<=i){ const p=sig(t.x.reduce((s,xv,j)=>s+xv*w[j],0)), y=t.R>0?1:0; for(let j=0;j<w.length;j++) w[j]+=lr*((y-p)*t.x[j]-l2*w[j]); pending.splice(k,1); } }
    if(pos){ const s=pos.side; const hs=s>0?b.low<=pos.sl:b.high>=pos.sl, ht=s>0?b.high>=pos.tp:b.low<=pos.tp;
      if(hs){ pos.R=-1; } else if(ht){ pos.R=2; } else if(i-pos.i>=64){ pos.R=(b.close-pos.e)*s/pos.risk; }
      if(pos.R!=null){ pos.R-=cost/pos.risk; pos.done=true; pos.doneI=i; trades.push(pos); pos=null; } }
    if(i<300||hi<60) continue; const a=atr[i], V=K.V[i], L=K.L[i], ts=V/a, dir=Math.sign(V);
    // re-arm after price has moved away from the line by 1 ATR
    for(const d of [1,-1]) if(!armed[d]&&(d>0?b.close>L+a:b.close<L-a)) armed[d]=true;
    if(!dir||pos) continue; const hd=Math.sign(HK.V[hi]); if(useGate&&hd!==dir) continue;
    const erP=pctRank(er,i,300), atP=pctRank(atr,i,500), h=hurst(B,i); if(erP==null||atP==null||h==null) continue;
    if(useGate&&(erP<0.4||atP<0.1||atP>0.95||Math.abs(ts)<0.03)) continue;
    // pullback: one of the last 3 bars touched the Kalman line (within 0.2 ATR); this bar closes back with the trend beyond the previous bar
    let touched=false, ext=dir>0?Infinity:-Infinity; for(let j=i-3;j<i;j++){ const x=B[j]; if(dir>0?x.low<=K.L[j]+0.2*atr[j]:x.high>=K.L[j]-0.2*atr[j]) touched=true; ext=dir>0?Math.min(ext,x.low):Math.max(ext,x.high); }
    ext=dir>0?Math.min(ext,b.low):Math.max(ext,b.high); const p=B[i-1];
    const trig=dir>0?(b.close>b.open&&b.close>p.high&&b.close>L):(b.close<b.open&&b.close<p.low&&b.close<L);
    if(!touched||!trig||!armed[dir]) continue;
    let risk=Math.abs(b.close-ext)+0.25*a; risk=Math.min(Math.max(risk,0.75*a),2.5*a);
    const hr=new Date(b.time*1000).getUTCHours()+new Date(b.time*1000).getUTCMinutes()/60;
    const x=[1,Math.min(3,Math.abs(ts)/0.1),erP,(h-0.5)*4,atP,Math.sin(2*Math.PI*hr/24),Math.cos(2*Math.PI*hr/24),Math.abs(b.close-L)/a];
    const prob=sig(x.reduce((s,xv,j)=>s+xv*w[j],0));
    pos={i,t:b.time,side:dir,e:b.close,sl:b.close-dir*risk,tp:b.close+dir*2*risk,risk,R:null,x,prob,trained:trades.length}; pending.push(pos); armed[dir]=false; }
  return trades; }
function stats(r){ const n=r.length; if(!n) return {n:0}; const s=r.reduce((p,q)=>p+q,0), m=s/n, sd=Math.sqrt(r.reduce((p,q)=>p+(q-m)**2,0)/Math.max(1,n-1)); const gp=r.filter(x=>x>0).reduce((p,q)=>p+q,0), gl=-r.filter(x=>x<0).reduce((p,q)=>p+q,0);
  return {n,win:Math.round(r.filter(x=>x>0).length/n*100),avgR:+m.toFixed(3),totR:+s.toFixed(1),pf:gl?+(gp/gl).toFixed(2):null,t:sd?+(m/(sd/Math.sqrt(n))).toFixed(2):0}; }
const line=(l,r)=>console.log(l.padEnd(44),JSON.stringify(stats(r)));
const ALL={'15m':[],'1h':[]}, NOG={'15m':[],'1h':[]};
for(const SYM of SYMS){ const B=await fetchAll(SYM,900,1); if(B.length<2000){ console.log(SYM,'too little data',B.length); continue; }
  console.log(`\n##### ${SYM}: ${B.length} 15m bars ${new Date(B[0].time*1000).toISOString().slice(0,10)} → ${new Date(B.at(-1).time*1000).toISOString().slice(0,10)}`);
  const c=COST[SYM]||0; const H1=resample(B,3600);
  for(const [tf,BB,g,m] of [['15m',B,900,4],['1h',H1,3600,4]]){ const T=run(BB,g,m,c), U=run(BB,g,m,c,false); T.forEach(t=>t.sym=SYM); ALL[tf].push(...T); NOG[tf].push(...U);
    line(` ${tf} with filters`,T.map(t=>t.R)); line(` ${tf} no filters (baseline)`,U.map(t=>t.R)); line(` ${tf} P(win) >= 0.40 only`,T.filter(t=>t.prob>=0.4).map(t=>t.R)); } await sleep(process.env.SYNTH?0:3000); }
for(const tf of ['15m','1h']){ const T=ALL[tf]; console.log(`\n===== ALL PAIRS ${tf} (costs included, R = risk units, target 2R) =====`);
  line('with filters',T.map(t=>t.R)); line('no filters (baseline)',NOG[tf].map(t=>t.R)); line('buys',T.filter(t=>t.side>0).map(t=>t.R)); line('sells',T.filter(t=>t.side<0).map(t=>t.R));
  console.log('-- calibration of P(win) (model trained only on earlier trades; first 30 trades per pair excluded) --'); const U=T.filter(t=>t.trained>=30);
  for(const [a,b2] of [[0,.3],[.3,.35],[.35,.4],[.4,.45],[.45,1]]) line(` P ${a}–${b2}`,U.filter(t=>t.prob>=a&&t.prob<b2).map(t=>t.R));
  const ts=T.map(t=>t.t).sort((p,q)=>p-q), mid=ts[Math.floor(ts.length/2)]; line('first half of year',T.filter(t=>t.t<mid).map(t=>t.R)); line('second half of year',T.filter(t=>t.t>=mid).map(t=>t.R)); }
