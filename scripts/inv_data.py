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
UA = {"User-Agent": "Mozilla/5.0"}  # Yahoo answers this exact tag from GitHub's servers (longer browser tags and curl/python get HTTP 429)
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


def yahoo(ticker, host="query1"):
    raw = json.loads(get(f"https://{host}.finance.yahoo.com/v8/finance/chart/{urllib.request.quote(ticker)}?range=10y&interval=1d&events=split%2Cdiv"))
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


BLS = {"CPI": "CUUR0000SA0", "CORE_CPI": "CUUR0000SA0L1E", "UNRATE": "LNS14000000", "PAYROLLS": "CES0000000001"}


def bls(series_ids):
    """US Bureau of Labor Statistics public API (no key: 10 years per call, 25 calls a day)."""
    out = {}
    end = datetime.now(timezone.utc).year
    for start in (end - 19, end - 9):
        body = json.dumps({"seriesid": list(series_ids.values()), "startyear": str(start), "endyear": str(min(end, start + 9))}).encode()
        req = urllib.request.Request("https://api.bls.gov/publicAPI/v2/timeseries/data/", data=body, headers={"Content-Type": "application/json", **UA})
        with urllib.request.urlopen(req, timeout=60) as r:
            js = json.loads(r.read())
        if js.get("status") != "REQUEST_SUCCEEDED":
            raise RuntimeError("; ".join(js.get("message") or ["BLS error"]))
        for sr in js["Results"]["series"]:
            name = next(k for k, v in series_ids.items() if v == sr["seriesID"])
            for d in sr["data"]:
                if d["period"].startswith("M") and d["period"] != "M13" and d["value"] not in ("-", ""):
                    out.setdefault(name, {})[f"{d['year']}-{d['period'][1:]}-01"] = float(d["value"])
        time.sleep(1)
    return {k: sorted(v.items()) for k, v in out.items()}


def treasury():
    """Daily US Treasury par yield curve (3 months, 2 years, 10 years) from treasury.gov, one CSV per year."""
    cols = {"3 Mo": "T3M", "2 Yr": "T2Y", "10 Yr": "T10Y"}
    out = {v: {} for v in cols.values()}
    y1 = datetime.now(timezone.utc).year
    for y in range(y1 - 10, y1 + 1):
        txt = get(f"https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/{y}/all?type=daily_treasury_yield_curve&field_tdr_date_value={y}&page&_format=csv").decode("utf-8", "ignore")
        for r in csv.DictReader(io.StringIO(txt)):
            m, d, yy = r["Date"].split("/")
            for c, k in cols.items():
                if r.get(c) not in (None, ""):
                    out[k][f"{yy}-{m}-{d}"] = float(r[c])
    return {k: sorted(v.items()) for k, v in out.items()}


def clean(rows):
    """Fix Yahoo's known glitches. JSE prices are in cents, but Yahoo sometimes prints a day in rand
    (a one-day -99% then +9900% spike): those days are scaled back x100. A one-day spike that reverses
    (>60% away from both neighbours) is dropped. Returns (rows, notes)."""
    notes = []
    if len(rows) < 3:
        return rows, notes
    out = [rows[0]]
    for i in range(1, len(rows) - 1):
        p, c, n = rows[i - 1][4], rows[i][4], rows[i + 1][4]
        if c and p and n and c > 0:
            if 0.005 < c / p < 0.02 and 0.005 < c / n < 0.02:  # one day quoted in rand instead of cents
                r = list(rows[i]); r[1:6] = [x * 100 if x else x for x in r[1:6]]; out.append(r)
                notes.append(f"{r[0]} x100 (rand/cents glitch)"); continue
            if (c / p > 1.6 and c / n > 1.6) or (c / p < 0.4 and c / n < 0.4):
                notes.append(f"{rows[i][0]} dropped (one-day spike)"); continue
        out.append(rows[i])
    out.append(rows[-1])
    return out, notes


def check(rows, market, ticker=""):
    """Data-quality checks on one price file. Returns (ok, problems list, stats)."""
    probs = []
    n = len(rows)
    if n < 120:
        probs.append(f"only {n} rows")
    bad = 0 if ticker == "CL=F" else sum(1 for r in rows if not (r[4] and r[4] > 0))  # oil futures really went negative in April 2020
    if bad:
        probs.append(f"{bad} zero/negative closes")
    hl = sum(1 for r in rows if r[2] is not None and r[3] is not None and r[2] < r[3])
    if hl:
        probs.append(f"{hl} rows with high < low")
    jumps = []
    lim = 0.6 if market == "Crypto" else 0.35
    if ticker in ("^VIX", "CL=F"):
        lim = 9e9  # these really do jump
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
            rows, fixes = clean(rows)
            if fixes:
                meta = dict(meta or {}); meta["cleaned"] = fixes[-10:]
                save(path, {**old, "rows": rows, "meta": meta})
        else:
            rows = meta = None; src = None; errs = []
            if a.mock:
                rows, meta, src = mock_rows(t), {"currency": "USD"}, "mock"
            else:
                try:
                    rows, meta = yahoo(t); src = "yahoo"
                except Exception as e:
                    errs.append(f"yahoo: {e}")
                    try:  # second Yahoo host
                        rows, meta = yahoo(t, "query2"); src = "yahoo"
                    except Exception as e2:
                        errs.append(f"yahoo2: {e2}")
            if rows is not None and not rows:
                errs.append("yahoo returned no price rows")
                rows = None
            if rows:
                rows, fixes = clean(rows)
                if fixes:
                    (meta or {}).setdefault("cleaned", fixes[-10:])
                good, probs, st = check(rows, mkt, t)
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
        good, probs, st = check(rows, mkt, t)
        entry.update(st)
        if (meta or {}).get("cleaned"):
            entry["cleaned"] = meta["cleaned"]; entry["source"] = src; entry["name"] = (meta or {}).get("name") or ins.get("name"); entry["currency"] = (meta or {}).get("currency")
        if (meta or {}).get("splits"):
            entry["splits"] = meta["splits"][-3:]
        entry["problems"] = probs
        print(f"{t:10s} {src or '-':6s} {st['rows']:5d} rows, last {st['last']}" + (f"  [{'; '.join(probs)}]" if probs else ""), flush=True)
        entry["status"] = "ok" if good and not probs else ("warning" if good else "failed")
        ok += entry["status"] == "ok"; warn += entry["status"] == "warning"; fail += entry["status"] == "failed"
        report["instruments"].append(entry)
    fok = ffail = 0
    # Economy data. FRED doesn't answer GitHub's servers, so the US government sources are used directly:
    # BLS (CPI, unemployment, payrolls) and the Treasury (yield curve). VIX, dollar and oil come from Yahoo above.
    econ = []
    for name, fn in (("bls", lambda: bls(BLS)), ("treasury", treasury)):
        path = os.path.join(a.cache, "econ", name + ".json.gz")
        old = load(path)
        try:
            if old and old.get("fetched") == today and not a.force:
                data = old["series"]
            elif a.mock:
                data = {k: [[f"{2016 + i // 12}-{i % 12 + 1:02d}-01", 2 + math.sin(i / 9)] for i in range(120)] for k in (BLS if name == "bls" else ("T3M", "T2Y", "T10Y"))}
                save(path, {"source": name, "fetched": today, "series": data})
            else:
                data = fn(); save(path, {"source": name, "fetched": today, "series": data})
            for k, rows in data.items():
                report["fred"].append({"series": f"{k} ({name})", "status": "ok", "rows": len(rows), "first": rows[0][0], "last": rows[-1][0]}); fok += 1
        except Exception as ex:
            if old:
                for k, rows in old["series"].items():
                    report["fred"].append({"series": f"{k} ({name})", "status": "warning", "rows": len(rows), "last": rows[-1][0], "note": f"download failed, previous copy: {ex}"}); fok += 1
            else:
                report["fred"].append({"series": name, "status": "failed", "note": str(ex)}); ffail += 1
    for s in ([] if not a.mock and not os.environ.get("TRY_FRED") else uni.get("fred", [])):
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
             f"Instruments: **{ok} ok**, {warn} with warnings, **{fail} failed** (of {len(uni['instruments'])}). Economy series: {fok} ok, {ffail} failed.", "",
             "| Ticker | Market | Status | Rows | Last bar | Source | Problems |", "|---|---|---|---|---|---|---|"]
    for x in sorted(report["instruments"], key=lambda x: ({"failed": 0, "warning": 1, "ok": 2}[x.get("status", "failed")], x["ticker"])):
        lines.append(f"| {x['ticker']} | {x['market']} | {x.get('status')} | {x.get('rows', '')} | {x.get('last', '')} | {x.get('source', '')} | {'; '.join(x.get('problems') or []) or x.get('note', '')}{(' (fixed: ' + ', '.join(x['cleaned'][:3]) + ')') if x.get('cleaned') else ''} |")
    lines += ["", "| Economy series | Status | Rows | Last value date |", "|---|---|---|---|"] + [f"| {e['series']} | {e['status']} | {e.get('rows', '')} | {e.get('last', '')} |" for e in report["fred"]]
    open(os.path.join(a.cache, "reports", "data_quality.md"), "w").write("\n".join(lines) + "\n")
    print("\n".join(lines[:3]))
    if not a.mock and (fail > max(5, 0.1 * len(uni["instruments"])) or ffail > 2):
        alert("Bias Desk: data problem", f"Investor data download: {fail} of {len(uni['instruments'])} instruments and {ffail} FRED series failed. Yesterday's data is kept.", "low", ["warning"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
