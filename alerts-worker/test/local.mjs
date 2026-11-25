// Offline test: fake KV + fake Deriv socket. Run: node alerts-worker/test/local.mjs
import worker, { run, boundary } from '../src/worker.js';
const kv = () => { const m = new Map(); let writes = 0; return { m, get writes() { return writes; }, async get(k, t) { const v = m.get(k); return v == null ? null : t === 'json' ? JSON.parse(v) : v; }, async put(k, v) { writes++; m.set(k, v); } }; };
let PRICE = 1.1000; // fake market
class FakeWS { constructor() { this.l = {}; setTimeout(() => this.emit('open', {}), 5); } addEventListener(t, f) { (this.l[t] ||= []).push(f); } emit(t, e) { (this.l[t] || []).forEach(f => f(e)); } close() { }
  send(s) { const r = JSON.parse(s); const g = r.granularity, n = r.count, now = Math.floor(Date.now() / 1000); const last = Math.floor(now / g) * g;
    const cs = Array.from({ length: n }, (_, i) => { const t = last - (n - 1 - i) * g; const o = PRICE - 0.0004, c = PRICE; return { epoch: t, open: o, high: Math.max(o, c) + 0.0002, low: Math.min(o, c) - 0.0002, close: c }; });
    setTimeout(() => this.emit('message', { data: JSON.stringify({ req_id: r.req_id, candles: cs.reverse() }) }), 5); } }
globalThis.WebSocket = FakeWS;
const env = { KV: kv(), NTFY_TOPIC: 't', ALERTS_KEY: 'k', DRY_RUN: 1 };
const post = (path, body) => worker.fetch(new Request('https://x' + path, { method: 'POST', headers: { 'X-Key': 'k' }, body: JSON.stringify(body) }), env).then(r => r.json());
const P = { sym: 'EURUSD', deriv: 'frxEURUSD', name: 'EURUSD', dp: 5 };
console.log('config', await post('/config', { cc: { on: true, anchor: 'ny', sel: { '15m': [P], '1h': [P] } }, zones: [{ ...P, id: 'Z1', lo: 1.1050, hi: 1.1060, mode: 'touch', on: true, armedAt: 1 }] }));
console.log('wrong key', (await worker.fetch(new Request('https://x/state', { headers: { 'X-Key': 'bad' } }), env)).status);
const t0 = Math.ceil(Date.now() / 900000) * 900000; // a 15-minute close
const tick = async (ms, px) => { PRICE = px; const r = await run(env, ms); return r; };
let r = await tick(t0 - 120000, 1.1000); console.log('first look (no alert):', r.sent, env.SENT?.length || 0);
r = await tick(t0 - 60000, 1.1055); console.log('price enters zone →', env.SENT.map(x => x.title));
r = await tick(t0 - 30000, 1.1100); r = await tick(t0 - 20000, 1.1055); console.log('again (zone is off now) → total', env.SENT.length);
env.SENT = []; r = await tick(t0 + 5000, 1.1001); console.log('15m close →', env.SENT.map(x => [x.title, x.message]));
const hourly = Math.ceil(Date.now() / 3600000) * 3600000; env.SENT = []; await tick(hourly + 5000, 1.1002); console.log('hour close →', env.SENT.map(x => x.title));
console.log('KV writes in this test:', env.KV.writes);
const f = t => new Date(t * 1000).toLocaleString('en-GB', { timeZone: 'Africa/Johannesburg', hour: '2-digit', minute: '2-digit' });
console.log('4H NY boundary now:', f(boundary('4h', Math.floor(Date.now() / 1000), 'ny')), '| daily:', f(boundary('1d', Math.floor(Date.now() / 1000), 'ny')));
