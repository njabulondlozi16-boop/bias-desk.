// Live check from GitHub: can we read Deriv candles with exactly the requests the server sends?
import { derivBatch } from '../src/worker.js';
const r = await derivBatch([
  { ticks_history: 'frxEURUSD', adjust_start_time: 1, count: 3, end: 'latest', style: 'candles', granularity: 60 },
  { ticks_history: 'frxXAUUSD', adjust_start_time: 1, count: 6, end: 'latest', style: 'candles', granularity: 3600 },
  { ticks_history: 'OTC_GDAXI', adjust_start_time: 1, count: 3, end: 'latest', style: 'candles', granularity: 900 }]);
for (const m of r) console.log(m ? (m.error ? 'error: ' + m.error.message : JSON.stringify((m.candles || []).slice(0, 2))) : 'no answer');
if (!r[0] || !r[0].candles) process.exitCode = 1;
