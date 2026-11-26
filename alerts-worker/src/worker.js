// Bias Desk always-on alert server (Cloudflare Worker, free plan).
// Every minute: checks your zone boxes against Deriv 1-minute candles (high/low, so a quick spike is not missed)
// and sends candle-close messages for the pairs/timeframes you ticked. Works when your PC is off.
// Config comes from Bias Desk (POST /config). Secrets (set by the deploy workflow, never in this file):
//   NTFY_TOPIC – your ntfy topic · ALERTS_KEY – passphrase Bias Desk uses to talk to this server · NTFY_TOKEN – optional ntfy access token
const DERIV = 'wss://api.derivws.com/trading/v1/options/ws/public';
const TF = { '15m': { s: 900, base: 900, n: 3, label: '15M' }, '1h': { s: 3600, base: 3600, n: 3, label: '1H' }, '4h': { s: 14400, base: 3600, n: 6, label: '4H' }, '1d': { s: 86400, base: 3600, n: 26, label: 'Daily' } };
const SITE = 'https://njabulondlozi16-boop.github.io/bias-desk./';
const hm = ms => new Date(ms).toLocaleTimeString('en-GB', { timeZone: 'Africa/Johannesburg', hour: '2-digit', minute: '2-digit' });
const fmt = (v, dp) => Number(v).toFixed(dp ?? 5);

function nyAnchorH(ts) { let off = -5; try { const tz = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', timeZoneName: 'shortOffset' }).formatToParts(new Date(ts * 1000)).find(x => x.type === 'timeZoneName').value; off = parseInt(tz.replace('GMT', '')) || -5; } catch (e) { } return (17 - off + 24) % 24; }
export function boundary(tf, now, anchor) { const T = TF[tf]; if (T.s <= 3600) return Math.floor(now / T.s) * T.s; const a = anchor === 'utc' ? 0 : nyAnchorH(now), h = Math.floor(now / 3600) * 3600; for (let k = 0; k <= 25; k++) { const b = h - k * 3600, uh = new Date(b * 1000).getUTCHours(); if (tf === '4h' ? ((uh - a + 24) % 4 === 0) : (uh === a)) return b; } return h; }
function hmMin(x) { const [h, m] = String(x || '0:0').split(':').map(Number); return (h || 0) * 60 + (m || 0); }
function inHours(cc, ms) { const m = hmMin(hm(ms)), a = hmMin(cc.from || '00:00'), b = hmMin(cc.to || '23:59'); return a <= b ? (m >= a && m <= b) : (m >= a || m <= b); }

// ---- session-open alarms (London 08:00 London time, New York 08:00 and NYSE 09:30 New York time) ----
function tzOff(tz, ms) { try { const v = new Intl.DateTimeFormat('en-US', { timeZone: tz, timeZoneName: 'shortOffset' }).formatToParts(new Date(ms)).find(x => x.type === 'timeZoneName').value; const m = v.match(/GMT([+-]\d+)(?::(\d+))?/); return m ? (+m[1]) * 60 + (m[1].startsWith('-') ? -1 : 1) * (+(m[2] || 0)) : 0; } catch (e) { return 0; } }
function tzEpoch(tz, y, mo, d, mins) { const g = Date.UTC(y, mo, d, 0, 0) + mins * 60e3; let e = g - tzOff(tz, g) * 60e3; e = g - tzOff(tz, e) * 60e3; return Math.floor(e / 1000); }
function tzYMD(tz, ms) { const p = new Intl.DateTimeFormat('en-CA', { timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit', weekday: 'short' }).formatToParts(new Date(ms)); const g = t => p.find(x => x.type === t).value; return { y: +g('year'), m: +g('month') - 1, d: +g('day'), wd: g('weekday') }; }
const SESS = [{ k: 'london', name: 'London', tz: 'Europe/London', mins: 480, label: 'London session' }, { k: 'ny', name: 'New York', tz: 'America/New_York', mins: 480, label: 'New York session' }, { k: 'nyse', name: 'NYSE', tz: 'America/New_York', mins: 570, label: 'New York stock market (US30, US100)' }];
export async function sessionAlarms(env, sess, now, log) {
  if (!sess) return; const lead = Math.max(1, Math.min(120, +sess.lead || 15));
  for (const x of SESS) { if (!sess[x.k]) continue; const D = tzYMD(x.tz, now * 1000); if (D.wd === 'Sat' || D.wd === 'Sun') continue; const open = tzEpoch(x.tz, D.y, D.m, D.d, x.mins);
    for (const [at, pre] of [[open - lead * 60, true], [open, false]]) { if (!pre && !sess.atOpen) continue; if (now - at < 0 || now - at >= 60) continue;
      const r = await push(env, { title: pre ? `⏰ ${x.label} opens in ${lead} min` : `🔔 ${x.label} is open`, message: `${x.name} opens at ${hm(open * 1000)} SAST · check your bias and zones`, priority: 4, tags: ['alarm_clock'] });
      if (r.ok) log.sent++; else log.errors.push(r.err || r.skip); } } }

// one WebSocket to Deriv, many requests, answers matched by req_id
export async function derivBatch(reqs, timeoutMs = 12000, WS = globalThis.WebSocket) {
  if (!reqs.length) return [];
  return await new Promise(resolve => {
    const out = new Array(reqs.length).fill(null); let left = reqs.length, done = false; let ws;
    const finish = () => { if (done) return; done = true; try { ws && ws.close(); } catch (e) { } resolve(out); };
    const timer = setTimeout(finish, timeoutMs);
    try { ws = new WS(DERIV); } catch (e) { clearTimeout(timer); return resolve(out); }
    ws.addEventListener('open', () => reqs.forEach((r, i) => ws.send(JSON.stringify({ ...r, req_id: i + 1 }))));
    ws.addEventListener('message', ev => { let m; try { m = JSON.parse(typeof ev.data === 'string' ? ev.data : new TextDecoder().decode(ev.data)); } catch (e) { return; } const i = (m.req_id || 0) - 1; if (i < 0 || i >= reqs.length || out[i]) return; out[i] = m; if (--left === 0) { clearTimeout(timer); finish(); } });
    ws.addEventListener('error', () => { clearTimeout(timer); finish(); });
    ws.addEventListener('close', () => { clearTimeout(timer); finish(); });
  });
}
const candles = m => ((m && m.candles) || []).map(c => ({ time: +c.epoch, open: +c.open, high: +c.high, low: +c.low, close: +c.close })).filter(c => isFinite(c.close)).sort((a, b) => a.time - b.time);
async function binance(sym, interval, limit) { try { const r = await fetch(`https://data-api.binance.vision/api/v3/klines?symbol=${sym}&interval=${interval}&limit=${limit}`); if (!r.ok) return []; return (await r.json()).map(k => ({ time: k[0] / 1000, open: +k[1], high: +k[2], low: +k[3], close: +k[4] })); } catch (e) { return []; } }
// fetch candles for many (symbol, granularity) pairs at once
async function getCandles(items, WS) {
  const der = items.filter(x => x.deriv && !x.binance), bn = items.filter(x => x.binance);
  const res = await derivBatch(der.map(x => ({ ticks_history: x.deriv, adjust_start_time: 1, count: x.n, end: 'latest', style: 'candles', granularity: x.g })), 12000, WS);
  const map = {}; der.forEach((x, i) => { map[x.key] = candles(res[i]); });
  await Promise.all(bn.map(async x => { map[x.key] = await binance(x.binance, x.g === 60 ? '1m' : x.g === 900 ? '15m' : '1h', x.n); }));
  return map;
}
function agg(cs, B, s) { const w = (cs || []).filter(c => c.time >= B - s && c.time < B); if (!w.length) return null; return { o: w[0].open, h: Math.max(...w.map(c => c.high)), l: Math.min(...w.map(c => c.low)), c: w[w.length - 1].close }; }

export async function push(env, msg) {
  if (!env.NTFY_TOPIC) return { skip: 'no topic' };
  const headers = env.NTFY_TOKEN ? { Authorization: 'Bearer ' + env.NTFY_TOKEN } : {};
  const body = JSON.stringify({ topic: env.NTFY_TOPIC, click: SITE, ...msg });
  if (env.DRY_RUN) { (env.SENT ||= []).push(JSON.parse(body)); return { ok: true }; }
  for (let i = 0; i < 3; i++) { try { const r = await fetch('https://ntfy.sh/', { method: 'POST', body, headers }); if (r.ok) return { ok: true }; if (r.status === 429) return { err: 'ntfy limit' }; } catch (e) { } await new Promise(r => setTimeout(r, 800 * (i + 1))); }
  return { err: 'ntfy unreachable' };
}

// ---- the every-minute job ----
export async function run(env, nowMs = Date.now(), WS) {
  const now = Math.floor(nowMs / 1000);
  const cfg = (await env.KV.get('cfg', 'json')) || { cc: null, zones: [] };
  const st = (await env.KV.get('state', 'json')) || { side: {}, zones: {}, lastZone: 0 };
  let stDirty = false; const log = { at: nowMs, zones: 0, cc: [], sent: 0, errors: [] };
  const cc = cfg.cc || { on: false, sel: {} };
  await sessionAlarms(env, cfg.sess, now, log);
  // what is due this minute
  const due = []; let B = 0;
  if (cc.on) for (const tf of Object.keys(TF)) { const b = boundary(tf, now, cc.anchor); if (now - b < 60 && (cc.sel[tf] || []).length) { due.push(tf); B = Math.max(B, b); } }
  const zones = (cfg.zones || []).filter(z => z.on && !(st.zones[z.id] && st.zones[z.id].off && st.zones[z.id].armedAt === z.armedAt));
  const closeTfs = new Set(); for (const tf of Object.keys(TF)) { const b = boundary(tf, now, cc.anchor || 'ny'); if (now - b < 60) closeTfs.add(tf); }
  // requests: 1-minute candles for zone pairs, base candles for due closes and close-inside zones
  const items = new Map(); const want = (p, g, n) => { const key = p.sym + '|' + g; const cur = items.get(key); if (!cur || cur.n < n) items.set(key, { key, deriv: p.deriv, binance: p.binance, g, n }); };
  for (const z of zones) { if (z.mode === 'close') { if (closeTfs.has(z.tf)) want(z, TF[z.tf].base, TF[z.tf].n); } else want(z, 60, 3); }
  for (const tf of due) for (const p of cc.sel[tf]) want(p, TF[tf].base, TF[tf].n);
  const saveLast = async force => { if (force || now % 900 < 60) await env.KV.put('last', JSON.stringify(log), { expirationTtl: 86400 }).catch(() => { }); }; // free plan: 1,000 writes/day → only every 15 min or when something happened
  if (!items.size) { await saveLast(false); return log; }
  if (due.length) await new Promise(r => setTimeout(r, 2500)); // let the closed candle settle at Deriv
  const data = await getCandles([...items.values()], WS);
  // zones
  for (const z of zones) {
    log.zones++;
    if (z.mode === 'close') {
      if (!closeTfs.has(z.tf)) continue; const bz = boundary(z.tf, now, cc.anchor || 'ny'); const c = agg(data[z.sym + '|' + TF[z.tf].base], bz, TF[z.tf].s);
      if (c && c.c >= z.lo && c.c <= z.hi) { await fire(z, `${TF[z.tf].label} candle closed inside your zone`, c.c); }
      continue;
    }
    const cs = (data[z.sym + '|60'] || []).filter(c => c.time >= now - 120);
    if (!cs.length) continue; const hi = Math.max(...cs.map(c => c.high)), lo = Math.min(...cs.map(c => c.low)), last = cs[cs.length - 1].close;
    const side = last > z.hi ? 'above' : last < z.lo ? 'below' : 'in'; const prev = st.side[z.id];
    const touched = hi >= z.lo && lo <= z.hi;
    if (prev === undefined) { st.side[z.id] = side; stDirty = true; continue; } // first look: just remember where price is
    if (prev !== 'in' && touched) { await fire(z, z.kind === 'level' ? `reached ${fmt(z.lo, z.dp)}` : 'price is in your zone', Math.min(Math.max(last, z.lo), z.hi), prev); }
    if (st.side[z.id] !== side) { st.side[z.id] = side; stDirty = true; }
  }
  async function fire(z, what, px, from) {
    const zs = st.zones[z.id] || {}; if (zs.lastHit && nowMs - zs.lastHit < (z.repeat ? 10 * 60e3 : 36e5 * 24 * 365) && zs.armedAt === z.armedAt) return; // browser or an earlier run already alerted
    const r = await push(env, { title: `${z.name} · ${what}`, message: `${z.kind === 'level' ? 'Price alert' : fmt(z.lo, z.dp) + ' – ' + fmt(z.hi, z.dp)} · price ${fmt(px, z.dp)}${from ? (from === 'above' ? ' · came down into it' : ' · came up into it') : ''} · ${hm(nowMs)} SAST`, priority: 5, tags: ['rotating_light'], click: SITE + '#/trade/' + encodeURIComponent(z.sym) });
    st.zones[z.id] = { lastHit: nowMs, armedAt: z.armedAt, off: !z.repeat, hits: (zs.hits || 0) + 1, by: 'server' }; stDirty = true; if (r.ok) log.sent++; else log.errors.push(r.err || r.skip);
  }
  // candle closes: one message for everything that closed now
  if (due.length && inHours(cc, B * 1000)) {
    const rows = [];
    for (const tf of ['1d', '4h', '1h', '15m']) { if (!due.includes(tf)) continue; for (const p of cc.sel[tf]) { const c = agg(data[p.sym + '|' + TF[tf].base], B, TF[tf].s); if (c) rows.push({ p, tf, c }); } }
    log.cc = rows.map(r => r.p.sym + ' ' + r.tf);
    if (rows.length) {
      const line = ({ p, tf, c }) => { const ch = (c.c - c.o) / c.o * 100, up = c.c > c.o, dn = c.c < c.o; return `${up ? '🟢' : dn ? '🔴' : '⚪'} ${p.name} ${TF[tf].label} ${up ? 'bullish' : dn ? 'bearish' : 'doji'} · close ${fmt(c.c, p.dp)} (${ch >= 0 ? '+' : ''}${ch.toFixed(2)}%)`; };
      const one = rows.length === 1 ? rows[0] : null; const labels = [...new Set(rows.map(r => TF[r.tf].label))];
      const title = one ? `${one.p.name} · ${TF[one.tf].label} candle closed` : `${labels.join(' + ')} candles closed · ${hm(B * 1000)} SAST`;
      const message = one ? `${line(one).replace(/^\S+ \S+ \S+ /, '')} · H ${fmt(one.c.h, one.p.dp)} · L ${fmt(one.c.l, one.p.dp)} · ${hm(B * 1000)} SAST` : rows.map(line).join('\n');
      const r = await push(env, { title, message, priority: 4, tags: [one ? (one.c.c >= one.c.o ? 'chart_with_upwards_trend' : 'chart_with_downwards_trend') : 'hourglass'], click: SITE + '#/trade/' + encodeURIComponent((one || rows[0]).p.sym) });
      if (r.ok) log.sent++; else log.errors.push(r.err || r.skip);
    }
  }
  if (stDirty) await env.KV.put('state', JSON.stringify(st));
  await saveLast(log.sent > 0 || (log.errors.length > 0 && now % 300 < 60));
  return log;
}

// ---- small HTTP API used by Bias Desk ----
const CORS = { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Methods': 'GET,POST,OPTIONS', 'Access-Control-Allow-Headers': 'Content-Type,X-Key' };
const J = (o, s = 200) => new Response(JSON.stringify(o), { status: s, headers: { 'Content-Type': 'application/json', ...CORS } });
function cleanCfg(c) {
  const sym = x => String(x || '').slice(0, 40), num = x => +x;
  const pair = p => ({ sym: sym(p.sym), deriv: sym(p.deriv), binance: sym(p.binance), name: sym(p.name || p.sym), dp: Math.max(0, Math.min(8, num(p.dp) || 5)) });
  const sel = {}; for (const tf of Object.keys(TF)) sel[tf] = ((c.cc && c.cc.sel && c.cc.sel[tf]) || []).slice(0, 40).map(pair).filter(p => p.deriv || p.binance);
  const zones = (c.zones || []).slice(0, 200).map(z => ({ ...pair(z), id: sym(z.id), lo: num(z.lo), hi: num(z.hi), mode: z.mode === 'close' ? 'close' : 'touch', tf: TF[z.tf] ? z.tf : '1h', repeat: !!z.repeat, on: !!z.on, armedAt: num(z.armedAt) || 0, kind: z.kind === 'level' ? 'level' : 'zone' })).filter(z => z.id && isFinite(z.lo) && isFinite(z.hi) && (z.deriv || z.binance));
  const ss = c.sess || {};
  return { sess: { london: !!ss.london, ny: !!ss.ny, nyse: !!ss.nyse, atOpen: !!ss.atOpen, lead: Math.max(1, Math.min(120, +ss.lead || 15)) }, cc: { on: !!(c.cc && c.cc.on), anchor: c.cc && c.cc.anchor === 'utc' ? 'utc' : 'ny', from: String((c.cc && c.cc.from) || '00:00').slice(0, 5), to: String((c.cc && c.cc.to) || '23:59').slice(0, 5), sel }, zones, at: Date.now() };
}
export default {
  async scheduled(event, env, ctx) { ctx.waitUntil(run(env).catch(async e => { await env.KV.put('last', JSON.stringify({ at: Date.now(), errors: [String(e && e.message || e)] })).catch(() => { }); })); },
  async fetch(req, env) {
    const url = new URL(req.url);
    if (req.method === 'OPTIONS') return new Response(null, { headers: CORS });
    if (url.pathname === '/health') { const last = await env.KV.get('last', 'json'); return J({ ok: true, topic: !!env.NTFY_TOPIC, last }); }
    if (!env.ALERTS_KEY || req.headers.get('X-Key') !== env.ALERTS_KEY) return J({ error: 'wrong key' }, 401);
    if (url.pathname === '/config' && req.method === 'POST') { const c = cleanCfg(await req.json()); await env.KV.put('cfg', JSON.stringify(c)); return J({ ok: true, zones: c.zones.length, pairs: Object.values(c.cc.sel).reduce((a, b) => a + b.length, 0) }); }
    if (url.pathname === '/state') { const st = (await env.KV.get('state', 'json')) || { zones: {} }; return J({ zones: st.zones || {} }); }
    if (url.pathname === '/fired' && req.method === 'POST') { const b = await req.json(); const st = (await env.KV.get('state', 'json')) || { side: {}, zones: {} }; const zs = st.zones[b.id] || {}; st.zones[String(b.id).slice(0, 40)] = { lastHit: +b.at || Date.now(), armedAt: +b.armedAt || 0, off: !b.repeat, hits: (zs.hits || 0) + 1, by: 'browser' }; st.side[b.id] = 'in'; await env.KV.put('state', JSON.stringify(st)); return J({ ok: true }); }
    if (url.pathname === '/probe') { const t = Date.now(); const r = await derivBatch([{ ticks_history: 'frxEURUSD', adjust_start_time: 1, count: 3, end: 'latest', style: 'candles', granularity: 60 }, { ticks_history: 'frxXAUUSD', adjust_start_time: 1, count: 3, end: 'latest', style: 'candles', granularity: 3600 }]); const b = await binance('BTCUSDT', '1m', 2); return J({ deriv: r.map(m => m ? (m.error ? m.error.message : candles(m).length + ' candles') : 'no answer'), binance: b.length + ' candles', ms: Date.now() - t }); }
    if (url.pathname === '/test') { const r = await push(env, { title: 'Bias Desk server ✅', message: `The always-on alert server works · ${hm(Date.now())} SAST`, priority: 4, tags: ['white_check_mark'] }); return J(r); }
    return J({ error: 'not found' }, 404);
  }
};
