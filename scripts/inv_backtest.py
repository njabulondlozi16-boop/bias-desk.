"""Investor desk - Phase 2: backtesting engine + swing scanners (the profit gate).

Rules (from docs/INVESTOR_DESK_BUILD_PROMPT.md):
  * signals use only data up to that day's close; entry at the NEXT day's open (no look-ahead)
  * costs on every trade (per side): US shares 0.15% + 0.05% slippage, ETFs 0.10% + 0.03%, JSE 0.30% + 0.10%, crypto 0.20% + 0.05%
  * stops and targets are checked on daily highs/lows; if both are touched on one day we assume the stop (worst case);
    a gap through the stop fills at the open
  * settings are chosen on TRAIN years (to end-2022) and judged on TEST years (2023 -> now); plus a yearly walk-forward
  * gate: test profit factor >= 1.3, >= 50 test trades and a bootstrap p-value (adjusted for how many settings were
    tried) below 0.05. Otherwise the signal stays "in research".

    python scripts/inv_backtest.py --cache cache --out cache/reports
"""
import argparse, gzip, itertools, json, math, os, sys
from datetime import date, datetime, timezone, timedelta
import numpy as np

SAST = timezone(timedelta(hours=2))
TRAIN_END = "2022-12-31"
COST = {"US": 0.0020, "ETF": 0.0013, "Commodity": 0.0013, "JSE": 0.0040, "Crypto": 0.0025}
SWING_MARKETS = ("US", "ETF", "Commodity", "JSE", "Crypto")


# ---------------------------------------------------------------- data
def load_universe(cache, root):
    uni = json.load(open(os.path.join(root, "config", "universe.json")))
    data = {}
    for ins in uni["instruments"]:
        t = ins["ticker"]
        p = os.path.join(cache, "prices", t.replace("^", "_").replace("=", "_") + ".json.gz")
        if not os.path.exists(p):
            continue
        rows = json.load(gzip.open(p, "rt"))["rows"]
        if len(rows) < 300:
            continue
        d = np.array([r[0] for r in rows])
        a = np.array([[r[1], r[2], r[3], r[4], r[5], r[6] or 0] for r in rows], dtype=float)
        f = np.where(a[:, 3] > 0, a[:, 4] / a[:, 3], 1.0)  # dividend/split adjustment factor
        data[t] = {"d": d, "o": a[:, 0] * f, "h": a[:, 1] * f, "l": a[:, 2] * f, "c": a[:, 4], "v": a[:, 5], "market": ins["market"], "info": ins}
    return uni, data


def sma(x, n):
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        c = np.cumsum(np.insert(x, 0, 0.0))
        out[n - 1:] = (c[n:] - c[:-n]) / n
    return out


def rolling(x, n, fn):
    out = np.full(len(x), np.nan)
    from numpy.lib.stride_tricks import sliding_window_view
    if len(x) >= n:
        out[n - 1:] = fn(sliding_window_view(x, n), axis=1)
    return out


def rsi(c, n=14):
    d = np.diff(c, prepend=c[0]); up = np.where(d > 0, d, 0.0); dn = np.where(d < 0, -d, 0.0)
    au = np.full(len(c), np.nan); ad = np.full(len(c), np.nan)
    if len(c) > n:
        au[n] = up[1:n + 1].mean(); ad[n] = dn[1:n + 1].mean()
        for i in range(n + 1, len(c)):
            au[i] = (au[i - 1] * (n - 1) + up[i]) / n; ad[i] = (ad[i - 1] * (n - 1) + dn[i]) / n
    rs = au / np.where(ad == 0, np.nan, ad)
    return np.where(ad == 0, 100.0, 100 - 100 / (1 + rs))


def prep(x):
    if "sma50" in x:
        return x
    c, h, l, v = x["c"], x["h"], x["l"], x["v"]
    x["sma20"], x["sma50"], x["sma200"] = sma(c, 20), sma(c, 50), sma(c, 200)
    x["hi252"], x["lo252"] = rolling(h, 252, np.max), rolling(l, 252, np.min)
    x["lo10"], x["hi10"], x["hi60"] = rolling(l, 10, np.min), rolling(h, 10, np.max), rolling(h, 60, np.max)
    x["v5"], x["v50"] = sma(v, 5), sma(v, 50)
    x["rsi"] = rsi(c)
    x["r63"] = np.concatenate([np.full(63, np.nan), c[63:] / c[:-63] - 1])
    return x


# ---------------------------------------------------------------- trade simulation
def simulate(x, i, side, stop, target_r, max_days, cost):
    """Signal on bar i (close). Enter at open i+1. Returns trade dict or None."""
    o, h, l, c, d = x["o"], x["h"], x["l"], x["c"], x["d"]
    if i + 1 >= len(c):
        return None
    e = o[i + 1]
    risk = (e - stop) if side > 0 else (stop - e)
    if not (risk > 0) or risk / e > 0.25 or risk / e < 0.003:
        return None
    tgt = e + side * target_r * risk if target_r else None
    j_end = min(len(c) - 1, i + max_days)
    ex, why, j = None, "time", j_end
    for k in range(i + 1, j_end + 1):
        if side > 0:
            if k > i + 1 and o[k] <= stop:
                ex, why, j = o[k], "stop", k; break
            if l[k] <= stop:
                ex, why, j = stop, "stop", k; break
            if tgt and h[k] >= tgt:
                ex, why, j = (o[k] if (k > i + 1 and o[k] >= tgt) else tgt), "target", k; break
        else:
            if k > i + 1 and o[k] >= stop:
                ex, why, j = o[k], "stop", k; break
            if h[k] >= stop:
                ex, why, j = stop, "stop", k; break
            if tgt and l[k] <= tgt:
                ex, why, j = (o[k] if (k > i + 1 and o[k] <= tgt) else tgt), "target", k; break
    if ex is None:
        if j_end == len(c) - 1 and j_end < i + max_days:
            return None  # still open today - not counted
        ex = c[j_end]
    gross = side * (ex / e - 1)
    net = gross - 2 * cost
    return {"date": d[i], "exit": d[j], "entry": e, "stop": stop, "ret": net, "R": net * e / risk, "why": why, "days": j - i}


# ---------------------------------------------------------------- signals (each returns a list of (i, side, stop))
def sig_breakout(x, dist=0.03, vmult=1.2, **_):
    out = []
    c = x["c"]
    m = (c > x["sma50"]) & (x["sma50"] > x["sma200"]) & (c >= (1 - dist) * x["hi252"]) & (x["v5"] >= vmult * x["v50"])
    for i in np.flatnonzero(m):
        out.append((i, 1, x["lo10"][i]))
    return out


def sig_pullback(x, rsi_max=50, near=0.01, bench=None, **_):
    out = []
    c, l = x["c"], x["l"]
    rs_ok = (x["r63"] > bench) if bench is not None else (x["r63"] > 0)
    m = (x["sma50"] > x["sma200"]) & (c > x["sma200"]) & (l <= x["sma50"] * (1 + near)) & (c >= x["sma50"] * 0.98) & (x["rsi"] < rsi_max) & rs_ok
    for i in np.flatnonzero(m):
        out.append((i, 1, min(x["lo10"][i], x["sma200"][i]) * 0.995))
    return out


def sig_gap(x, gap=0.04, vmult=2.0, side=1, **_):
    """Earnings-style gap drift (proxy: free data has no earnings dates/consensus, so any big gap on heavy volume counts)."""
    out = []
    o, c, h, l, v = x["o"], x["c"], x["h"], x["l"], x["v"]
    for i in range(60, len(c) - 3):
        g = o[i] / c[i - 1] - 1
        if side * g >= gap and v[i] >= vmult * x["v50"][i - 1]:
            j = i + 2  # held the gap for 2 days -> signal at that close
            held = (min(l[i + 1:j + 1]) > c[i - 1]) if side > 0 else (max(h[i + 1:j + 1]) < c[i - 1])
            if held:
                out.append((j, side, l[i] if side > 0 else h[i]))
    return out


def sig_breakdown(x, dist=0.03, vmult=1.2, **_):
    """Mirror: new 52-week lows in a downtrend on rising volume -> short / avoid."""
    out = []
    c = x["c"]
    m = (c < x["sma50"]) & (x["sma50"] < x["sma200"]) & (c <= (1 + dist) * x["lo252"]) & (x["v5"] >= vmult * x["v50"])
    for i in np.flatnonzero(m):
        out.append((i, -1, x["hi10"][i]))
    return out


SIGNALS = {
    "breakout_52w": {"name": "52-week-high breakout with volume", "fn": sig_breakout, "markets": SWING_MARKETS,
                     "grid": {"dist": [0.02, 0.03, 0.05], "vmult": [1.2, 1.5], "target_r": [2, 3, None], "max_days": [20, 40]}},
    "pullback_uptrend": {"name": "Pullback to the 50-day in an uptrend", "fn": sig_pullback, "markets": SWING_MARKETS,
                         "grid": {"rsi_max": [45, 50], "near": [0.0, 0.01], "target_r": [2, 3, None], "max_days": [20, 40]}},
    "gap_drift_up": {"name": "Big gap up that holds (earnings-style drift)", "fn": sig_gap, "markets": ("US", "JSE"), "fixed": {"side": 1},
                     "grid": {"gap": [0.04, 0.06], "vmult": [2.0, 3.0], "target_r": [3, None], "max_days": [20, 40, 60]}},
    "gap_drift_down": {"name": "Big gap down that holds (short)", "fn": sig_gap, "markets": ("US", "JSE"), "fixed": {"side": -1},
                       "grid": {"gap": [0.04, 0.06], "vmult": [2.0, 3.0], "target_r": [3, None], "max_days": [20, 40, 60]}},
    "breakdown_52w": {"name": "52-week-low breakdown (short / avoid)", "fn": sig_breakdown, "markets": SWING_MARKETS,
                      "grid": {"dist": [0.03, 0.05], "vmult": [1.2, 1.5], "target_r": [2, 3, None], "max_days": [20, 40]}},
}


# ---------------------------------------------------------------- stats
def stats(tr, years):
    n = len(tr)
    if n == 0:
        return {"trades": 0}
    r = np.array([t["R"] for t in tr]); ret = np.array([t["ret"] for t in tr])
    wins = r[r > 0].sum(); losses = -r[r < 0].sum()
    pf = float(wins / losses) if losses > 0 else None
    # equity at 1% risk per trade, trades taken in exit order (can overlap - approximation)
    eq = np.cumprod(1 + 0.01 * r[np.argsort([t["exit"] for t in tr])]); peak = np.maximum.accumulate(eq)
    dd = float((eq / peak - 1).min())
    cagr = float(eq[-1] ** (1 / max(years, 0.5)) - 1)
    sharpe = float(r.mean() / r.std() * math.sqrt(n / max(years, 0.5))) if r.std() > 0 else None
    return {"trades": n, "win_rate": round(float((r > 0).mean()), 3), "avg_R": round(float(r.mean()), 3), "avg_ret_pct": round(float(ret.mean() * 100), 2),
            "profit_factor": round(pf, 2) if pf else None, "max_dd_pct_at_1pct_risk": round(dd * 100, 1), "cagr_pct_at_1pct_risk": round(cagr * 100, 1),
            "sharpe": round(sharpe, 2) if sharpe else None, "avg_days": round(float(np.mean([t["days"] for t in tr])), 1)}


def boot_p(tr, n=4000, seed=7):
    """One-sided bootstrap p-value that the average R is above 0."""
    if len(tr) < 10:
        return 1.0
    r = np.array([t["R"] for t in tr]); m = r.mean(); rng = np.random.default_rng(seed)
    z = r - m
    sims = rng.choice(z, size=(n, len(z)), replace=True).mean(axis=1)
    return float((sims >= m).mean())


def zar_ret(tr, fx):
    """Trade returns converted to rand (USD assets): (1+r) * (USDZAR exit / entry) - 1."""
    if fx is None:
        return None
    idx = {d: i for i, d in enumerate(fx["d"])}
    out = []
    for t in tr:
        a, b = idx.get(t["date"]), idx.get(t["exit"])
        if a is None or b is None:
            continue
        out.append((1 + t["ret"]) * (fx["c"][b] / fx["c"][a]) - 1)
    return round(float(np.mean(out) * 100), 2) if out else None


def baseline(data, tst, markets):
    """Average return of holding the same instruments for the same number of days on EVERY test-period day (same side, after costs).
    A signal only has an edge if it beats this."""
    if not tst:
        return None
    hold = int(round(np.mean([t["days"] for t in tst]))) or 1
    side = 1 if np.mean([1 if t["ret"] * 0 == 0 and t.get("R", 0) * 0 == 0 else 1 for t in tst]) else 1
    side = -1 if all((t["entry"] < t["stop"]) for t in tst[:20]) else 1
    rets = []
    for tk in {t["ticker"] for t in tst}:
        x = data[tk]
        i0 = int(np.searchsorted(x["d"], "2023-01-01"))
        o = x["o"]; n = len(o)
        if n - i0 - hold - 1 <= 0:
            continue
        r = side * (o[i0 + 1 + hold:n] / o[i0 + 1:n - hold] - 1) - 2 * COST[x["market"]]
        rets.append(r)
    return round(float(np.mean(np.concatenate(rets)) * 100), 2) if rets else None


def sector_rotation(data, ytrain, ytest, top=3, months=1):
    """Each month hold the top sector ETFs by average of 3- and 6-month return; compare with SPY."""
    secs = [t for t, x in data.items() if x["info"].get("sector_etf")]
    if "SPY" not in data or len(secs) < 5:
        return None
    spy = data["SPY"]; dates = spy["d"]
    month_ends = [i for i in range(252, len(dates) - 1) if dates[i][:7] != dates[i + 1][:7]]
    trades, excess = [], []
    for a_, b_ in zip(month_ends, month_ends[1:]):
        d0, d1 = dates[a_], dates[b_]
        score = []
        for t in secs:
            x = data[t]; i = int(np.searchsorted(x["d"], d0, side="right")) - 1
            if i < 126 or x["d"][i] != d0:
                continue
            score.append(((x["c"][i] / x["c"][i - 63] - 1) + (x["c"][i] / x["c"][i - 126] - 1), t, i))
        score.sort(reverse=True)
        spy_r = spy["o"][b_ + 1] / spy["o"][a_ + 1] - 1 if b_ + 1 < len(dates) else None
        for _, t, i in score[:top]:
            x = data[t]; j = int(np.searchsorted(x["d"], d1, side="right")) - 1
            if j + 1 >= len(x["o"]) or spy_r is None:
                continue
            r = x["o"][j + 1] / x["o"][i + 1] - 1 - 2 * COST["ETF"]
            trades.append({"date": d0, "exit": d1, "ticker": t, "market": "ETF", "ret": r, "R": r / 0.05, "days": j - i, "entry": x["o"][i + 1], "stop": 0, "why": "month"})
            excess.append((d0, r - spy_r))
    trn = [t for t in trades if t["date"] <= TRAIN_END]; tst = [t for t in trades if t["date"] > TRAIN_END]
    ex_tr = [e for d, e in excess if d <= TRAIN_END]; ex_te = [e for d, e in excess if d > TRAIN_END]
    s_te = stats(tst, ytest)
    # bootstrap p that the average EXCESS over SPY is above 0
    pv = boot_p([{"R": e} for e in ex_te]) if ex_te else 1.0
    padj = min(1.0, pv * (len(SIGNALS) + 1))
    passed = bool(ex_te and np.mean(ex_te) > 0 and padj < 0.05 and len(ex_te) >= 50)
    return {"name": "Sector rotation (top 3 sector ETFs each month)", "settings": {"top": top, "hold_months": months}, "settings_tried": 1, "markets": ["ETF"],
            "train": stats(trn, ytrain), "test": s_te, "walk_forward": {}, "test_by_market": {},
            "avg_excess_vs_spy_pct_train": round(float(np.mean(ex_tr) * 100), 2) if ex_tr else None,
            "avg_excess_vs_spy_pct_test": round(float(np.mean(ex_te) * 100), 2) if ex_te else None,
            "baseline_avg_ret_pct": None, "edge_vs_holding_pct": round(float(np.mean(ex_te) * 100), 2) if ex_te else None,
            "p_value": round(pv, 4), "p_value_adjusted": round(padj, 4), "avg_ret_pct_in_zar_test": None,
            "status": "live" if passed else "research", "last_trades": tst[-9:]}


# ---------------------------------------------------------------- run
def run_variant(key, spec, data, params, bench_r63):
    out = []
    for t, x in data.items():
        if x["market"] not in spec["markets"] or x["info"].get("context"):
            continue
        prep(x)
        kw = {**spec.get("fixed", {}), **{k: v for k, v in params.items() if k not in ("target_r", "max_days")}}
        if key == "pullback_uptrend" and bench_r63 is not None:
            b = bench_r63.get(x["market"])
            if b is not None:
                bm = dict(zip(b["d"], b["r63"]))
                kw["bench"] = np.array([bm.get(d, np.nan) for d in x["d"]])
        last_exit = None
        for (i, side, stop) in spec["fn"](x, **kw):
            if last_exit is not None and x["d"][i] <= last_exit:
                continue  # one trade at a time per instrument
            if i < 252 or not np.isfinite(stop):
                continue
            tr = simulate(x, i, side, stop, params["target_r"], params["max_days"], COST[x["market"]])
            if tr:
                tr["ticker"] = t; tr["market"] = x["market"]; out.append(tr); last_exit = tr["exit"]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default="cache")
    ap.add_argument("--out", default="cache/reports")
    ap.add_argument("--min-train-trades", type=int, default=80)
    a = ap.parse_args()
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    uni, data = load_universe(a.cache, root)
    fx = data.get("ZAR=X")
    # relative-strength benchmarks: S&P 500 for US/ETF, Satrix 40 for JSE
    bench = {}
    for mk, tk in (("US", "SPY"), ("ETF", "SPY"), ("Commodity", "SPY"), ("JSE", "STX40.JO")):
        if tk in data:
            prep(data[tk]); bench[mk] = data[tk]
    first = min(x["d"][252] for x in data.values() if len(x["d"]) > 252)
    end = max(x["d"][-1] for x in data.values())
    ytrain = (date.fromisoformat(TRAIN_END) - date.fromisoformat(first)).days / 365.25
    ytest = (date.fromisoformat(end) - date.fromisoformat(TRAIN_END)).days / 365.25
    results, n_tried = {}, 0
    for key, spec in SIGNALS.items():
        names = list(spec["grid"]); combos = [dict(zip(names, v)) for v in itertools.product(*spec["grid"].values())]
        rows = []
        for p in combos:
            n_tried += 1
            tr = run_variant(key, spec, data, p, bench)
            trn = [t for t in tr if t["date"] <= TRAIN_END]; tst = [t for t in tr if t["date"] > TRAIN_END]
            rows.append((p, trn, tst, stats(trn, ytrain)))
            print(f"{key:18s} {p} train {len(trn):5d} trades PF {rows[-1][3].get('profit_factor')}", flush=True)
        # choose on TRAIN only: best profit factor with enough trades
        ok = [r for r in rows if r[3]["trades"] >= a.min_train_trades and r[3].get("profit_factor")]
        best = max(ok, key=lambda r: r[3]["profit_factor"]) if ok else max(rows, key=lambda r: r[3]["trades"])
        p, trn, tst, s_tr = best
        # keep only the markets where this signal worked in the TRAIN years (decided before looking at test data)
        keep = [mk for mk in sorted({t["market"] for t in trn}) if (lambda s_: s_["trades"] >= 30 and (s_.get("profit_factor") or 0) >= 1.1)(stats([t for t in trn if t["market"] == mk], ytrain))]
        if keep:
            trn = [t for t in trn if t["market"] in keep]; tst = [t for t in tst if t["market"] in keep]; s_tr = stats(trn, ytrain)
        s_te = stats(tst, ytest)
        pv = boot_p(tst); padj = min(1.0, pv * len(SIGNALS) + 0.0)  # one test per signal type: settings and markets were fixed on train data
        base = baseline(data, tst, keep or list(spec["markets"]))
        # walk-forward: each year, pick the best setting on all earlier years, test on that year
        wf = []
        years = sorted({t["date"][:4] for r in rows for t in r[1] + r[2]})
        for y in years[2:]:
            cand = []
            for (pp, a1, a2, _) in rows:
                prior = [t for t in a1 + a2 if t["date"][:4] < y]
                s = stats(prior, 1)
                if s["trades"] >= 40 and s.get("profit_factor"):
                    cand.append((s["profit_factor"], pp, [t for t in a1 + a2 if t["date"][:4] == y]))
            if cand:
                pf, pp, yt = max(cand, key=lambda z: z[0])
                wf.extend(yt)
        s_wf = stats(wf, max(1, len(years) - 2))
        by_mkt = {}
        for mk in sorted({t["market"] for t in tst}):
            by_mkt[mk] = stats([t for t in tst if t["market"] == mk], ytest)
        passed = bool(s_te.get("profit_factor") and s_te["profit_factor"] >= 1.3 and s_te["trades"] >= 50 and padj < 0.05)
        results[key] = {"name": spec["name"], "settings": {k: v for k, v in p.items()}, "settings_tried": len(combos), "markets": keep or list(spec["markets"]),
                        "baseline_avg_ret_pct": base, "edge_vs_holding_pct": round(s_te.get("avg_ret_pct", 0) - base, 2) if base is not None and s_te.get("trades") else None,
                        "train": s_tr, "test": s_te, "walk_forward": s_wf, "test_by_market": by_mkt,
                        "p_value": round(pv, 4), "p_value_adjusted": round(padj, 4),
                        "avg_ret_pct_in_zar_test": zar_ret([t for t in tst if t["market"] in ("US", "ETF", "Commodity", "Crypto")], fx),
                        "status": "live" if passed else "research",
                        "last_trades": [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in t.items()} for t in tst[-15:]]}
    sr = sector_rotation(data, ytrain, ytest)
    if sr:
        results["sector_rotation"] = sr
    out = {"generated_at": datetime.now(SAST).strftime("%Y-%m-%d %H:%M SAST"), "train_period": f"{first} to {TRAIN_END}", "test_period": f"2023-01-01 to {end}",
           "costs_per_side": COST, "variants_tested_total": n_tried,
           "notes": ["Share results are survivor-biased: free data only has companies that still exist today.",
                     "Gap drift uses any big gap on heavy volume - free data has no earnings dates or analyst forecasts.",
                     "Insider buying and your own FRVP setups are not tested yet (need SEC filings / intraday data)."],
           "signals": results}
    os.makedirs(a.out, exist_ok=True)
    json.dump(out, open(os.path.join(a.out, "investor_signal_stats.json"), "w"), indent=1, allow_nan=False, default=lambda o: None)
    # readable table
    L = [f"# Backtest - swing signals ({out['generated_at']})", "", f"Train {out['train_period']} | Test {out['test_period']} | costs included | {n_tried} settings tried in total", "",
         "| Signal | Markets (picked on train) | Status | Train trades / PF | **Test trades / win % / avg R / PF** | Walk-fwd PF | Test avg trade | Just holding | **Edge** | p (adj.) |", "|---|---|---|---|---|---|---|---|---|---|"]
    for k, r in results.items():
        tr, te, w = r["train"], r["test"], r["walk_forward"]
        L.append(f"| {r['name']} | {', '.join(r.get('markets') or [])} | **{r['status']}** | {tr.get('trades')} / {tr.get('profit_factor')} | {te.get('trades')} / {round((te.get('win_rate') or 0) * 100)}% / {te.get('avg_R')} / **{te.get('profit_factor')}** | {w.get('profit_factor')} | {te.get('avg_ret_pct')}% | {r.get('baseline_avg_ret_pct')}% | **{r.get('edge_vs_holding_pct')}%** | {r['p_value_adjusted']} |")
    L += ["", "Gate to go live: test profit factor >= 1.3, >= 50 test trades, adjusted p < 0.05.", ""] + [f"- {n}" for n in out["notes"]]
    open(os.path.join(a.out, "backtest.md"), "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    sys.exit(main())
