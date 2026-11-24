"""Investor desk - Phase 1 data layer.

Downloads 10 years of daily prices for every instrument in config/universe.json (Yahoo, Stooq as backup for US
tickers) and the FRED economic series, keeps them in a cache folder (the `invest-data` branch), checks each file,
and writes a data-quality report. Standard library only.

    python scripts/inv_data.py --cache cache            # normal run
    python scripts/inv_data.py --cache cache --mock     # offline test with made-up data (no network)
"""
import argparse, csv, gzip, io, json, math, os, random, sys, time, urllib.request
from datetime import datetime, timezone, timedelta

import importlib.util as _ilu  # load notify.py by path (scripts/calendar.py would shadow the stdlib if scripts/ were on sys.path)
_sp = _ilu.spec_from_file_location("bd_notify", os.path.join(os.path.dirname(os.path.abspath(__file__)), "notify.py"))
_nm = _ilu.module_from_spec(_sp); _sp.loader.exec_module(_nm); alert = _nm.alert
from datetime import date

SAST = timezone(timedelta(hours=2))
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
      "Accept": "application/json,text/csv,*/*"}
_last = {}


_dead = {}  # host -> consecutive failures (circuit breaker: stop hammering a host that is blocking us)


def get(url, tries=3, pause=0.6):
    """Polite GET: one request per `pause` seconds per host, retries with back-off."""
    host = url.split("/")[2]
    if _dead.get(host, 0) >= 8:
        raise RuntimeError(f"{host} skipped (blocked earlier in this run)")
    err = None
    for i in range(tries):
        wait = _last.get(host, 0) + pause - time.time()
        if wait > 0:
            time.sleep(wait)
        _last[host] = time.time()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                _dead[host] = 0
                return r.read()
        except Exception as e:
            err = e
            code = getattr(e, "code", None)
            if code in (400, 404):
                break
            time.sleep(2 * (i + 1) + (5 if code == 429 else 0))
    _dead[host] = _dead.get(host, 0) + 1
    raise RuntimeError(f"{err}")


def yahoo(ticker):
    raw = json.loads(get(f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.request.quote(ticker)}?range=10y&interval=1d&events=split%2Cdiv"))
    res = (raw.get("chart") or {}).get("result")
    if not res:
        raise RuntimeError(f"no data ({(raw.get('chart') or {}).get('error')})")
    r = res[0]
    ts = r.get("timestamp") or []
    q = (r.get("indicators") or {}).get("quote", [{}])[0]
    adj = ((r.get("indicators") or {}).get("adjclose") or [{}])[0].get("adjclose") or [None] * len(ts)
    rows = []
    for i, t in enumerate(ts):
        o, h, l, c, v = (q.get(k, [None] * len(ts))[i] for k in ("open", "high", "low", "close", "volume"))
        if c is None or o is None:
            continue
        d = datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d")
        rows.append([d, o, h, l, c, adj[i] if adj[i] is not None else c, v or 0])
    meta = r.get("meta") or {}
    splits = list(((r.get("events") or {}).get("splits") or {}).values())
    return rows, {"currency": meta.get("currency"), "exchange": meta.get("exchangeName"), "name": meta.get("longName") or meta.get("shortName"),
                  "type": meta.get("instrumentType"), "splits": [{"date": datetime.fromtimestamp(s["date"], timezone.utc).strftime("%Y-%m-%d"), "ratio": f"{s.get('numerator')}:{s.get('denominator')}"} for s in splits]}


def stooq(ticker):
    sym = ticker.lower().replace("-", ".") + ".us"
    txt = get(f"https://stooq.com/q/d/l/?s={sym}&i=d").decode("utf-8", "ignore")
    rd = list(csv.DictReader(io.StringIO(txt)))
    if not rd or "Close" not in rd[0]:
        raise RuntimeError("no stooq data")
    cut = (datetime.now(timezone.utc) - timedelta(days=3660)).strftime("%Y-%m-%d")
    rows = [[r["Date"], float(r["Open"]), float(r["High"]), float(r["Low"]), float(r["Close"]), float(r["Close"]), float(r.get("Volume") or 0)] for r in rd if r["Date"] >= cut]
    return rows, {"currency": "USD", "source_note": "Stooq (prices are split-adjusted; dividends not included)"}


def fred(series):
    txt = get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}").decode("utf-8", "ignore")
    rd = list(csv.reader(io.StringIO(txt)))
    out = []
    for r in rd[1:]:
        if len(r) >= 2 and r[1] not in (".", ""):
            try:
                out.append([r[0], float(r[1])])
            except ValueError:
                pass
    if len(out) < 12:
        raise RuntimeError("too few FRED rows")
    return out


def check(rows, market):
    """Data-quality checks on one price file. Returns (ok, problems list, stats)."""
    probs = []
    n = len(rows)
    if n < 120:
        probs.append(f"only {n} rows")
    bad = sum(1 for r in rows if not (r[4] and r[4] > 0))
    if bad:
        probs.append(f"{bad} zero/negative closes")
    hl = sum(1 for r in rows if r[2] is not None and r[3] is not None and r[2] < r[3])
    if hl:
        probs.append(f"{hl} rows with high < low")
    jumps = []
    lim = 0.6 if market == "Crypto" else 0.35
    for a, b in zip(rows, rows[1:]):
        if a[5] and b[5] and abs(b[5] / a[5] - 1) > lim:
            jumps.append(f"{b[0]} {b[5] / a[5] - 1:+.0%}")
    if jumps:
        probs.append(f"{len(jumps)} big one-day jumps (check splits): {', '.join(jumps[:3])}")
    gaps = []
    for a, b in zip(rows, rows[1:]):
        g = (date.fromisoformat(b[0]) - date.fromisoformat(a[0])).days
        if g > (7 if market != "Crypto" else 3):
            gaps.append(f"{a[0]}→{b[0]} ({g}d)")
    if gaps:
        probs.append(f"{len(gaps)} gaps longer than a week: {', '.join(gaps[:3])}")
    last = rows[-1][0] if rows else None
    age = (datetime.now(timezone.utc).date() - date.fromisoformat(last)).days if last else 999
    if age > (3 if market == "Crypto" else 5):
        probs.append(f"stale: last bar {last} ({age} days old)")
    serious = n < 120 or bad > 0 or age > 10
    return (not serious), probs, {"rows": n, "first": rows[0][0] if rows else None, "last": last, "age_days": age}


def mock_rows(seed, years=10):
    random.seed(seed)
    d0 = datetime.now(timezone.utc).date() - timedelta(days=365 * years)
    p, rows, d = 100.0, [], d0
    while d <= datetime.now(timezone.utc).date():
        if d.weekday() < 5:
            o = p; p *= math.exp(random.gauss(0.0003, 0.015)); h = max(o, p) * 1.004; l = min(o, p) * 0.996
            rows.append([d.isoformat(), round(o, 4), round(h, 4), round(l, 4), round(p, 4), round(p, 4), random.randint(100000, 5000000)])
        d += timedelta(days=1)
    return rows


def save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(obj, f, separators=(",", ":"), allow_nan=False)


def load(path):
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default="cache")
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--force", action="store_true", help="download again even if done today")
    a = ap.parse_args()
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    uni = json.load(open(os.path.join(root, "config", "universe.json")))
    today = datetime.now(SAST).strftime("%Y-%m-%d")
    report = {"generated_at": datetime.now(SAST).strftime("%Y-%m-%d %H:%M SAST"), "instruments": [], "fred": [], "summary": {}}
    ok = warn = fail = 0
    for ins in uni["instruments"]:
        t, mkt = ins["ticker"], ins["market"]
        path = os.path.join(a.cache, "prices", t.replace("^", "_").replace("=", "_") + ".json.gz")
        old = load(path)
        entry = {"ticker": t, "market": mkt}
        if old and old.get("fetched") == today and not a.force:
            rows, meta, src = old["rows"], old.get("meta", {}), old.get("source", "cache")
        else:
            rows = meta = None; src = None; errs = []
            if a.mock:
                rows, meta, src = mock_rows(t), {"currency": "USD"}, "mock"
            else:
                try:
                    rows, meta = yahoo(t); src = "yahoo"
                except Exception as e:
                    errs.append(f"yahoo: {e}")
                    if mkt in ("US", "ETF", "Commodity"):
                        try:
                            rows, meta = stooq(t); src = "stooq"
                        except Exception as e2:
                            errs.append(f"stooq: {e2}")
            if rows:
                good, probs, st = check(rows, mkt)
                if good or not old:
                    save(path, {"ticker": t, "market": mkt, "fetched": today, "source": src, "meta": meta, "rows": rows})
                else:  # new download looks broken: keep yesterday's copy
                    entry["note"] = "new download failed checks - kept previous copy"
                    rows, meta, src = old["rows"], old.get("meta", {}), old.get("source")
            elif old:
                rows, meta, src = old["rows"], old.get("meta", {}), old.get("source")
                entry["note"] = "download failed - using previous copy (" + "; ".join(errs) + ")"
            else:
                entry.update({"status": "failed", "problems": errs}); fail += 1
                print(f"{t:10s} FAILED {'; '.join(errs)}", flush=True)
                report["instruments"].append(entry); continue
        good, probs, st = check(rows, mkt)
        entry.update(st); entry["source"] = src; entry["name"] = (meta or {}).get("name") or ins.get("name"); entry["currency"] = (meta or {}).get("currency")
        if (meta or {}).get("splits"):
            entry["splits"] = meta["splits"][-3:]
        entry["problems"] = probs
        print(f"{t:10s} {src or '-':6s} {st['rows']:5d} rows, last {st['last']}" + (f"  [{'; '.join(probs)}]" if probs else ""), flush=True)
        entry["status"] = "ok" if good and not probs else ("warning" if good else "failed")
        ok += entry["status"] == "ok"; warn += entry["status"] == "warning"; fail += entry["status"] == "failed"
        report["instruments"].append(entry)
    fok = ffail = 0
    for s in uni.get("fred", []):
        path = os.path.join(a.cache, "fred", s + ".json.gz")
        old = load(path)
        e = {"series": s}
        try:
            if old and old.get("fetched") == today and not a.force:
                rows = old["rows"]
            else:
                rows = [[(datetime(2000, 1, 1) + timedelta(days=30 * i)).strftime("%Y-%m-%d"), 3 + math.sin(i / 7)] for i in range(320)] if a.mock else fred(s)
                save(path, {"series": s, "fetched": today, "rows": rows})
            e.update({"status": "ok", "rows": len(rows), "first": rows[0][0], "last": rows[-1][0]}); fok += 1
        except Exception as ex:
            if old:
                e.update({"status": "warning", "rows": len(old["rows"]), "last": old["rows"][-1][0], "note": f"download failed, using previous copy: {ex}"}); fok += 1
            else:
                e.update({"status": "failed", "note": str(ex)}); ffail += 1
        report["fred"].append(e)
    report["summary"] = {"instruments": len(uni["instruments"]), "ok": ok, "warnings": warn, "failed": fail, "fred_ok": fok, "fred_failed": ffail,
                         "sources": {k: sum(1 for x in report["instruments"] if x.get("source") == k) for k in ("yahoo", "stooq", "cache", "mock")}}
    os.makedirs(os.path.join(a.cache, "reports"), exist_ok=True)
    json.dump(report, open(os.path.join(a.cache, "reports", "data_quality.json"), "w"), indent=1, allow_nan=False)
    # short human-readable version
    lines = [f"# Investor desk - data quality ({report['generated_at']})", "",
             f"Instruments: **{ok} ok**, {warn} with warnings, **{fail} failed** (of {len(uni['instruments'])}). FRED series: {fok} ok, {ffail} failed.", "",
             "| Ticker | Market | Status | Rows | Last bar | Source | Problems |", "|---|---|---|---|---|---|---|"]
    for x in sorted(report["instruments"], key=lambda x: ({"failed": 0, "warning": 1, "ok": 2}[x.get("status", "failed")], x["ticker"])):
        lines.append(f"| {x['ticker']} | {x['market']} | {x.get('status')} | {x.get('rows', '')} | {x.get('last', '')} | {x.get('source', '')} | {'; '.join(x.get('problems') or []) or x.get('note', '')} |")
    lines += ["", "| FRED series | Status | Rows | Last value date |", "|---|---|---|---|"] + [f"| {e['series']} | {e['status']} | {e.get('rows', '')} | {e.get('last', '')} |" for e in report["fred"]]
    open(os.path.join(a.cache, "reports", "data_quality.md"), "w").write("\n".join(lines) + "\n")
    print("\n".join(lines[:3]))
    if not a.mock and (fail > max(5, 0.1 * len(uni["instruments"])) or ffail > 2):
        alert("Bias Desk: data problem", f"Investor data download: {fail} of {len(uni['instruments'])} instruments and {ffail} FRED series failed. Yesterday's data is kept.", "low", ["warning"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
