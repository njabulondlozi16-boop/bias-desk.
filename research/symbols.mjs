const ws=new WebSocket('wss://api.derivws.com/trading/v1/options/ws/public'); await new Promise(r=>ws.onopen=r);
const ask=q=>new Promise(r=>{ ws.onmessage=e=>r(JSON.parse(e.data)); ws.send(JSON.stringify(q)); });
for(const sym of ['frxXAGUSD','frxXAUUSD']){ const h=await ask({ticks_history:sym,count:3,end:'latest',style:'candles',granularity:900}); console.log('SYM',sym, h.error?('ERR '+h.error.message):(h.candles||[]).map(c=>c.close).join(',')); }
ws.close();
