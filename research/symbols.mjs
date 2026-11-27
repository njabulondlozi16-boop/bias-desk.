const ws=new WebSocket('wss://api.derivws.com/trading/v1/options/ws/public'); await new Promise(r=>ws.onopen=r);
const ask=q=>new Promise(r=>{ ws.onmessage=e=>r(JSON.parse(e.data)); ws.send(JSON.stringify(q)); });
const m=await ask({active_symbols:'brief'}); const L=m.active_symbols||[]; console.log('error',m.error&&m.error.message,'count',L.length);
for(const s of L) if(/usd|dollar|dxy|basket|index/i.test((s.display_name||'')+' '+(s.symbol||''))&&!/volatility|boom|crash|jump|step|range|drift|dex/i.test(s.display_name||'')) console.log(s.symbol,'|',s.display_name,'|',s.market,'|',s.submarket,'| open:',s.exchange_is_open);
for(const sym of ['WLDUSD','frxUSDSEK','frxUSDJPY','frxUSDCAD','frxUSDCHF']){ const h=await ask({ticks_history:sym,count:3,end:'latest',style:'candles',granularity:900}); console.log(sym, h.error?('ERR '+h.error.message):(h.candles||[]).map(c=>c.close).join(',')); }
ws.close();
