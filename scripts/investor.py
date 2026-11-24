"""Investor desk - daily guide (phases 3 + 5): economy card, watchlists with key levels, sector strength.

Reads the invest-data cache (prices, BLS, Treasury) and reports/investor_signal_stats.json, writes investor.json
for the website and sends phone alerts (Sunday guide, watchlist levels reached, economy regime changes).
These are ideas to research with your own technical analysis - not trade signals and not financial advice.

    python scripts/investor.py --cache cache --out investor.json [--no-alerts]
"""
import argparse, gzip, json, math, os, sys
from datetime import date, datetime, timezone, timedelta
import importlib.util as ilu
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
_sp = ilu.spec_from_file_location("bd_notify", os.path.join(HERE, "notify.py")); _nm = ilu.module_from_spec(_sp); _sp.loader.exec_module(_nm)
_bp = ilu.spec_from_file_location("bd_bt", os.path.join(HERE, "inv_backtest.py")); bt = ilu.module_from_spec(_bp); _bp.loader.exec_module(bt)
SAST = timezone(timedelta(hours=2))
SITE = _nm.SITE + "#/invest"


def gz(p):
    try:
        return json.load(gzip.open(p, "rt"))
    except Exception:
        return None


def last_on_or_before(series, d):
    """series: sorted [[date, value]] -> value on or before date d (ISO)."""
    lo, hi, ans = 0, len(series) - 1, None
    while lo <= hi:
        m = (lo + hi) // 2
        if series[m][0] <= d:
            ans = series[m][1]; lo = m + 1
        else:
            hi = m - 1
    return ans


# ------------------------------------------------------------------ economy
def econ_signals(d, bls, tre, px):
    """All readings as known on date d (BLS monthly figures are only used ~6 weeks after the month, as when published)."""
    pub = (date.fromisoformat(d) - timedelta(days=45)).isoformat()

    def m(name, months_back=0):
        s = [r for r in bls.get(name, []) if r[0] <= pub]
        return s[-1 - months_back][1] if len(s) > months_back else None

    def ms(name, n):
        s = [r for r in bls.get(name, []) if r[0] <= pub]
        return [r[1] for r in s[-n:]] if len(s) >= n else None

    def pxv(t, back=0):
        x = px.get(t)
        if not x:
            return None
        i = int(np.searchsorted(x["d"], d, side="right")) - 1 - back
        return float(x["c"][i]) if i >= 0 else None

    def sma(t, n):
        x = px.get(t)
        if not x:
            return None
        i = int(np.searchsorted(x["d"], d, side="right"))
        return float(np.mean(x["c"][max(0, i - n):i])) if i >= n else None

    sig = []
    # growth
    u = ms("UNRATE", 15)
    if u:
        avg3 = [np.mean(u[i - 2:i + 1]) for i in range(2, len(u))]
        sahm = avg3[-1] - min(avg3[-13:-1]) if len(avg3) > 12 else None
        if sahm is not None:
            sig.append({"key": "sahm", "group": "Growth", "name": "Unemployment trend (Sahm rule)", "value": f"{u[-1]:.1f}% (3-mo avg +{sahm:.2f} pts vs 12-mo low)",
                        "state": "red" if sahm >= 0.5 else "grey" if sahm >= 0.3 else "green",
                        "meaning": "Unemployment rising fast - recessions usually start like this" if sahm >= 0.5 else "Unemployment creeping up - watch" if sahm >= 0.3 else "Jobs market steady"})
    p = ms("PAYROLLS", 4)
    if p:
        ch = (p[-1] - p[0]) / 3
        sig.append({"key": "payrolls", "group": "Growth", "name": "New jobs per month (3-mo avg)", "value": f"{ch:+.0f}k",
                    "state": "green" if ch > 150 else "red" if ch < 50 else "grey",
                    "meaning": "Strong hiring" if ch > 150 else "Hiring has nearly stopped" if ch < 50 else "Hiring is slowing"})
    spy, s200 = pxv("SPY"), sma("SPY", 200)
    if spy and s200:
        sig.append({"key": "spy200", "group": "Markets", "name": "S&P 500 vs 200-day average", "value": f"{(spy / s200 - 1) * 100:+.1f}%",
                    "state": "green" if spy > s200 else "red", "meaning": "Stocks in an uptrend" if spy > s200 else "Stocks in a downtrend"})
    hy, ie = px.get("HYG"), px.get("IEF")
    if hy and ie:
        r_now = (pxv("HYG") or 0) / (pxv("IEF") or 1)
        hist = []
        for k in range(0, 250, 5):
            a_, b_ = pxv("HYG", k), pxv("IEF", k)
            if a_ and b_:
                hist.append(a_ / b_)
        if hist:
            dev = r_now / np.mean(hist) - 1
            sig.append({"key": "credit", "group": "Stress", "name": "Junk bonds vs Treasuries (1-yr)", "value": f"{dev * 100:+.1f}%",
                        "state": "red" if dev < -0.03 else "green" if dev > 0 else "grey",
                        "meaning": "Lenders are nervous - credit stress" if dev < -0.03 else "Credit markets calm" if dev > 0 else "Credit slightly weaker than usual"})
    # inflation
    c = ms("CPI", 16)
    if c:
        yoy = (c[-1] / c[-13] - 1) * 100
        ann3 = ((c[-1] / c[-4]) ** 4 - 1) * 100
        rising = ann3 > yoy + 0.3
        sig.append({"key": "cpi", "group": "Inflation", "name": "Inflation (CPI, yearly)", "value": f"{yoy:.1f}% (last 3 mo: {ann3:.1f}% a year)",
                    "state": "red" if yoy > 3.5 or (yoy > 2.7 and rising) else "green" if yoy < 2.5 and not rising else "grey",
                    "meaning": ("Inflation high and rising" if rising else "Inflation high but cooling") if yoy > 3 else ("Inflation near target" if yoy < 2.7 else "Inflation a bit above target") + (", rising" if rising else "")})
    cc = ms("CORE_CPI", 13)
    if cc:
        cy = (cc[-1] / cc[0] - 1) * 100
        sig.append({"key": "core", "group": "Inflation", "name": "Core inflation (no food/energy)", "value": f"{cy:.1f}%",
                    "state": "red" if cy > 3.3 else "green" if cy < 2.6 else "grey", "meaning": "Sticky price pressure" if cy > 3.3 else "Underlying inflation calm" if cy < 2.6 else "Underlying inflation easing slowly"})
    # policy and curve (Treasury)
    t10, t2, t3m = tre.get("T10Y", []), tre.get("T2Y", []), tre.get("T3M", [])
    a10, a2, a3 = last_on_or_before(t10, d), last_on_or_before(t2, d), last_on_or_before(t3m, d)
    if a10 is not None and a2 is not None:
        sp_ = a10 - a2
        sig.append({"key": "curve", "group": "Stress", "name": "Yield curve (10y - 2y)", "value": f"{sp_:+.2f} pts",
                    "state": "red" if sp_ < 0 else "grey" if sp_ < 0.5 else "green", "meaning": "Inverted - often comes before a slowdown" if sp_ < 0 else "Flat" if sp_ < 0.5 else "Normal, upward-sloping"})
    d6 = (date.fromisoformat(d) - timedelta(days=182)).isoformat(); d3 = (date.fromisoformat(d) - timedelta(days=91)).isoformat()
    b6 = last_on_or_before(t3m, d6)
    if a3 is not None and b6 is not None:
        ch = a3 - b6
        sig.append({"key": "policy", "group": "Policy", "name": "Short-term rates, last 6 months (Fed direction)", "value": f"{a3:.2f}% ({ch:+.2f})",
                    "state": "red" if ch > 0.25 else "green" if ch < -0.25 else "grey", "meaning": "Fed tightening - headwind" if ch > 0.25 else "Fed cutting - tailwind" if ch < -0.25 else "Fed on hold"})
    b3 = last_on_or_before(t10, d3)
    if a10 is not None and b3 is not None:
        ch = a10 - b3
        sig.append({"key": "y10", "group": "Policy", "name": "10-year yield, last 3 months", "value": f"{a10:.2f}% ({ch:+.2f})",
                    "state": "red" if ch > 0.4 else "green" if ch < -0.4 else "grey", "meaning": "Borrowing costs jumping" if ch > 0.4 else "Borrowing costs falling" if ch < -0.4 else "Borrowing costs steady"})
    vix = pxv("^VIX")
    if vix:
        sig.append({"key": "vix", "group": "Stress", "name": "Fear index (VIX)", "value": f"{vix:.1f}",
                    "state": "red" if vix > 25 else "green" if vix < 16 else "grey", "meaning": "Fear is high" if vix > 25 else "Calm markets" if vix < 16 else "Normal nerves"})
    for t, nm, up_bad in (("DX-Y.NYB", "US dollar, last 3 months", True), ("CL=F", "Oil, last 3 months", True)):
        a_, b_ = pxv(t), pxv(t, 63)
        if a_ and b_:
            ch = (a_ / b_ - 1) * 100
            sig.append({"key": t, "group": "Markets", "name": nm, "value": f"{ch:+.1f}%",
                        "state": "grey" if abs(ch) < 4 else ("red" if (ch > 0) == up_bad else "green"),
                        "meaning": (("Strong dollar - pressure on rand, EM and gold" if ch > 0 else "Weak dollar - good for rand, EM and gold") if t.startswith("DX") else ("Oil up - inflation pressure" if ch > 0 else "Oil down - eases inflation")) if abs(ch) >= 4 else "Little change"})
    return sig


def classify(sig, prev_growth=None):
    st = {s["key"]: s["state"] for s in sig}
    pts = {"green": 1, "red": -1, "grey": 0}
    growth = sum(pts[st[k]] for k in ("sahm", "payrolls", "spy200", "credit") if k in st)
    hot = st.get("cpi") == "red" or (st.get("cpi") == "grey" and st.get("core") == "red")
    if prev_growth is not None and prev_growth <= -1 and growth >= 0 and not hot:
        reg = "Recovery"
    elif growth >= 1:
        reg = "Overheating" if hot else "Expansion"
    elif growth <= -1:
        reg = "Stagflation" if hot else "Slowdown"
    else:
        reg = "Overheating" if hot else "Expansion"
    n = len([k for k in ("sahm", "payrolls", "spy200", "credit") if k in st]) or 1
    conf = "high" if abs(growth) >= 3 else "medium" if abs(growth) >= 2 or (prev_growth is not None and abs(growth - prev_growth) >= 2) else "low"
    return reg, conf, growth


REGIME_TEXT = {
    "Expansion": "The economy is growing and inflation is under control - usually good for shares, especially cyclical and tech companies.",
    "Overheating": "Growth is strong but inflation is running hot - rates tend to stay high; energy and materials usually hold up better.",
    "Slowdown": "Growth is fading while inflation is calm - defensive sectors (health care, staples, utilities) and bonds usually hold up better.",
    "Stagflation": "Growth is weak and inflation is high - the hardest mix; cash, gold and energy have usually suffered least.",
    "Recovery": "Growth is turning up after a weak patch - early-cycle sectors (financials, industrials, small caps) usually lead.",
}


def regime_history(bls, tre, px):
    """Classify every month-end (data as known then) and measure each sector ETF's next-3-month return vs SPY."""
    spy = px.get("SPY")
    secs = {t: x for t, x in px.items() if x["info"].get("sector_etf")}
    if not spy:
        return [], {}
    me = [i for i in range(252, len(spy["d"]) - 1) if spy["d"][i][:7] != spy["d"][i + 1][:7]]
    hist, pg = [], None
    for i in me:
        d = spy["d"][i]
        sig = econ_signals(d, bls, tre, px)
        reg, conf, g = classify(sig, pg); pg = g
        j = i + 63
        fwd = {}
        if j < len(spy["d"]):
            sr = spy["c"][j] / spy["c"][i] - 1
            for t, x in secs.items():
                a_ = int(np.searchsorted(x["d"], d, side="right")) - 1; b_ = int(np.searchsorted(x["d"], spy["d"][j], side="right")) - 1
                if a_ > 0 and b_ > a_:
                    fwd[t] = (x["c"][b_] / x["c"][a_] - 1) - sr
        hist.append({"date": d, "regime": reg, "fwd": fwd})
    table = {}
    for reg in REGIME_TEXT:
        rows = [h for h in hist if h["regime"] == reg and h["fwd"]]
        if not rows:
            continue
        per = {}
        for t in secs:
            v = [h["fwd"][t] for h in rows if t in h["fwd"]]
            if v:
                per[t] = {"avg_excess_3m_pct": round(float(np.mean(v)) * 100, 2), "beat_spy_pct": round(float(np.mean([x > 0 for x in v])) * 100), "months": len(v)}
        table[reg] = {"months": len(rows), "sectors": per}
    return hist, table


# ------------------------------------------------------------------ watchlists
def tv_symbol(t, market):
    if market == "JSE":
        return "JSE:" + t.replace(".JO", "")
    if market == "Crypto":
        return "BINANCE:" + t.replace("-USD", "USDT")
    return t.replace("-", ".")


def fmt(v):
    return None if v is None or not np.isfinite(v) else round(float(v), 4 if v < 10 else 2)


def ideas(px, stats, sector_rank, favoured):
    out = []
    sstat = (stats or {}).get("signals", {})

    def hist_line(key):
        s = sstat.get(key)
        if not s or not s.get("test", {}).get("trades"):
            return None
        te = s["test"]
        return {"key": key, "status": s["status"], "trades": te["trades"], "win_rate": te.get("win_rate"), "avg_ret_pct": te.get("avg_ret_pct"),
                "holding_pct": s.get("baseline_avg_ret_pct"), "edge_pct": s.get("edge_vs_holding_pct"), "period": stats.get("test_period"),
                "text": f"Since 2023 this setup won {round((te.get('win_rate') or 0) * 100)}% of {te['trades']} cases, avg {te.get('avg_ret_pct'):+.2f}% a trade after costs, vs {s.get('baseline_avg_ret_pct'):+.2f}% for just holding."}

    r63 = {t: x["r63"][-1] for t, x in px.items() if len(x["c"]) > 300 and np.isfinite(x["r63"][-1]) and not x["info"].get("context")}
    ranks = {t: v for t, v in zip(r63, np.argsort(np.argsort(list(r63.values()))) / max(1, len(r63) - 1))}
    for t, x in px.items():
        if x["info"].get("context") or len(x["c"]) < 300 or x["market"] not in ("US", "ETF", "Commodity", "JSE", "Crypto"):
            continue
        c = x["c"]; i = len(c) - 1
        p, s20, s50, s200 = c[i], x["sma20"][i], x["sma50"][i], x["sma200"][i]
        hi52, lo52, lo10, hi10, hi60 = x["hi252"][i], x["lo252"][i], x["lo10"][i], x["hi10"][i], x["hi60"][i]
        vol_ratio = x["v5"][i] / x["v50"][i] if x["v50"][i] else None
        up = p > s50 > s200; down = p < s50 < s200
        base = {"ticker": t, "name": x["info"].get("name") or x.get("name") or t, "market": x["market"], "price": fmt(p), "currency": x.get("currency"),
                "date": x["d"][i], "tv": tv_symbol(t, x["market"]), "chg_1d_pct": fmt((c[i] / c[i - 1] - 1) * 100), "r63_pct": fmt(x["r63"][i] * 100),
                "momentum_rank": round(float(ranks.get(t, 0.5)) * 100), "vol_ratio": fmt(vol_ratio),
                "sector": x["info"].get("sector"), "favoured": bool(x["info"].get("sector_etf") and t in favoured)}

        def score(extra=0):
            s = 30 * (p > s200) + 15 * (s50 > s200) + 30 * ranks.get(t, 0.5) + 10 * min(1.0, (vol_ratio or 0) / 2) + extra
            return int(max(0, min(100, round(s))))

        # 1) near 52-week high in an uptrend
        if up and p >= 0.97 * hi52:
            out.append({**base, "list": "swing", "setup": "breakout_52w", "setup_name": "Near a 52-week high in an uptrend", "side": "long", "score": score(10 if (vol_ratio or 0) >= 1.2 else 0),
                        "reasons": [f"{(p / hi52 - 1) * 100:+.1f}% from the 52-week high", "Above the 50- and 200-day averages, 50 above 200",
                                    f"Volume this week {vol_ratio:.1f}x normal" if vol_ratio else "Volume n/a", f"3-month return {x['r63'][i] * 100:+.1f}% (stronger than {ranks.get(t, 0.5) * 100:.0f}% of the list)"],
                        "levels": {"trigger": fmt(hi52), "support": fmt(s20), "stop_idea": fmt(lo10)}, "history": hist_line("breakout_52w"),
                        "confirm": f"A daily close above {fmt(hi52)} on strong volume", "cancel": f"A close back below the 20-day average ({fmt(s20)})"})
        # 2) pullback to the 50-day in an uptrend
        if s50 > s200 and p > s200 and x["l"][i] <= s50 * 1.01 and p >= s50 * 0.98 and x["rsi"][i] < 50:
            out.append({**base, "list": "swing", "setup": "pullback_uptrend", "setup_name": "Pullback to the 50-day in an uptrend", "side": "long", "score": score(),
                        "reasons": ["Long-term uptrend (50-day above 200-day)", f"Pulled back to the 50-day average ({fmt(s50)})", f"RSI {x['rsi'][i]:.0f} - momentum has cooled"],
                        "levels": {"buy_zone": fmt(s50), "support": fmt(s200), "target": fmt(hi60), "stop_idea": fmt(min(lo10, s200) * 0.995)}, "history": hist_line("pullback_uptrend"),
                        "confirm": "A bullish reversal candle at the 50-day average", "cancel": f"A close below {fmt(min(lo10, s200))}"})
        # 3) big gap that held (last 5 sessions)
        for k in range(max(60, i - 6), i - 1):
            g = x["o"][k] / c[k - 1] - 1
            if abs(g) >= 0.04 and x["v"][k] >= 2 * x["v50"][k - 1] and x["market"] in ("US", "JSE"):
                held = min(x["l"][k + 1:i + 1]) > c[k - 1] if g > 0 else max(x["h"][k + 1:i + 1]) < c[k - 1]
                if held:
                    out.append({**base, "list": "swing", "setup": "gap_drift_up" if g > 0 else "gap_drift_down", "setup_name": "Big gap up that held" if g > 0 else "Big gap down that held",
                                "side": "long" if g > 0 else "avoid", "score": score(10 if g > 0 else -20),
                                "reasons": [f"Gapped {g * 100:+.1f}% on {x['d'][k]} on {x['v'][k] / x['v50'][k - 1]:.1f}x normal volume", "The gap has not been filled since",
                                            "Often news-driven (results) - check the headline before you trade it"],
                        "levels": {"gap_day_low" if g > 0 else "gap_day_high": fmt(x["l"][k] if g > 0 else x["h"][k]), "gap_fill": fmt(c[k - 1]), "recent_high": fmt(hi10)},
                                "history": hist_line("gap_drift_up" if g > 0 else "gap_drift_down"),
                                "confirm": "Price keeps holding above the gap-day low" if g > 0 else "Bounces fail below the gap", "cancel": f"Price fills the gap ({fmt(c[k - 1])})"})
                    break
        # 4) avoid list: breaking to 52-week lows in a downtrend
        if down and p <= 1.03 * lo52:
            out.append({**base, "list": "avoid", "setup": "breakdown_52w", "setup_name": "Breaking down to 52-week lows", "side": "avoid", "score": score(-40),
                        "reasons": [f"{(p / lo52 - 1) * 100:+.1f}% from the 52-week low", "Below the 50- and 200-day averages"],
                        "levels": {"52w_low": fmt(lo52), "resistance": fmt(s50), "recent_high": fmt(hi10)}, "history": hist_line("breakdown_52w"),
                        "confirm": "Lower lows continue", "cancel": f"A close back above the 50-day ({fmt(s50)})"})
    out.sort(key=lambda z: -z["score"])
    return out


def sector_strength(px, favoured):
    spy = px.get("SPY")
    rows = []
    for t, x in px.items():
        if not x["info"].get("sector_etf"):
            continue
        c = x["c"]; i = len(c) - 1
        r3 = c[i] / c[i - 63] - 1; r6 = c[i] / c[i - 126] - 1
        s3 = spy["c"][-1] / spy["c"][-64] - 1; s6 = spy["c"][-1] / spy["c"][-127] - 1
        rows.append({"ticker": t, "sector": x["info"]["sector"], "r3_pct": round(r3 * 100, 1), "r6_pct": round(r6 * 100, 1), "rs3_pct": round((r3 - s3) * 100, 1), "rs6_pct": round((r6 - s6) * 100, 1),
                     "trend": "up" if c[i] > x["sma200"][i] else "down", "favoured": t in favoured, "tv": t})
    rows.sort(key=lambda r: -(r["rs3_pct"] + r["rs6_pct"]))
    for k, r in enumerate(rows):
        r["rank"] = k + 1
    return rows


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default="cache")
    ap.add_argument("--out", default="investor.json")
    ap.add_argument("--no-alerts", action="store_true")
    a = ap.parse_args()
    uni, px = bt.load_universe(a.cache, ROOT)
    for t, x in px.items():
        bt.prep(x)
        meta = (gz(os.path.join(a.cache, "prices", t.replace("^", "_").replace("=", "_") + ".json.gz")) or {}).get("meta") or {}
        x["name"] = meta.get("name"); x["currency"] = meta.get("currency")
    bls = (gz(os.path.join(a.cache, "econ", "bls.json.gz")) or {}).get("series", {})
    tre = (gz(os.path.join(a.cache, "econ", "treasury.json.gz")) or {}).get("series", {})
    stats = None
    try:
        stats = json.load(open(os.path.join(a.cache, "reports", "investor_signal_stats.json")))
    except Exception:
        pass
    today = px["SPY"]["d"][-1]
    hist, table = regime_history(bls, tre, px)
    sig = econ_signals(today, bls, tre, px)
    prev_g = classify(econ_signals(px["SPY"]["d"][-127], bls, tre, px))[2] if len(px["SPY"]["d"]) > 130 else None
    reg, conf, g = classify(sig, prev_g)
    tab = table.get(reg, {}).get("sectors", {})
    ranked = sorted(tab.items(), key=lambda kv: -kv[1]["avg_excess_3m_pct"])
    favoured = [t for t, v in ranked if v["avg_excess_3m_pct"] > 0 and v["months"] >= 3][:3]
    struggles = [t for t, v in ranked[::-1] if v["avg_excess_3m_pct"] < 0 and v["months"] >= 3][:3]
    secname = {t: x["info"].get("sector") for t, x in px.items() if x["info"].get("sector_etf")}
    sect = sector_strength(px, favoured)
    idl = ideas(px, stats, {r["ticker"]: r["rank"] for r in sect}, favoured)
    swing = [z for z in idl if z["list"] == "swing"]
    avoid = [z for z in idl if z["list"] == "avoid"]
    by_setup = {}
    for z in swing:
        by_setup.setdefault(z["setup"], []).append(z)
    top3, seen = [], set()
    for z in swing:
        if z["ticker"] not in seen and z["side"] == "long":
            top3.append(z["ticker"] + "|" + z["setup"]); seen.add(z["ticker"])
        if len(top3) == 3:
            break
    sstat = (stats or {}).get("signals", {})
    out = {"generated_at": datetime.now(SAST).strftime("%Y-%m-%d %H:%M SAST"), "data_date": today, "markets_scanned": len(px),
           "note": "Ideas to research with your own technical analysis - not trade signals and not financial advice.",
           "economy": {"regime": reg, "confidence": conf, "summary": REGIME_TEXT[reg], "signals": sig,
                       "does_well": [{"ticker": t, "sector": secname.get(t), **tab[t]} for t in favoured],
                       "struggles": [{"ticker": t, "sector": secname.get(t), **tab[t]} for t in struggles],
                       "history_note": f"Sector results by regime use {len(hist)} month-ends since {hist[0]['date'][:7] if hist else '-'} (free data starts there); economic numbers are used ~6 weeks after the month, as when they were published.",
                       "regime_table": table, "regime_months": [{"date": h["date"], "regime": h["regime"]} for h in hist[-36:]]},
           "top3": top3,
           "swing": swing[:60], "avoid": avoid[:25], "sectors": sect,
           "signal_stats": {k: {"name": v["name"], "status": v["status"], "test": v.get("test"), "baseline_avg_ret_pct": v.get("baseline_avg_ret_pct"), "edge_vs_holding_pct": v.get("edge_vs_holding_pct"),
                                "settings": v.get("settings"), "markets": v.get("markets")} for k, v in sstat.items()},
           "test_period": (stats or {}).get("test_period"), "backtest_generated_at": (stats or {}).get("generated_at")}
    prev = None
    try:
        prev = json.load(open(a.out))
    except Exception:
        pass
    json.dump(out, open(a.out, "w"), indent=1, allow_nan=False, default=lambda o: None)
    print(f"regime {reg} ({conf}) | swing {len(swing)} | avoid {len(avoid)} | top3 {top3}")
    if a.no_alerts:
        return 0
    # ---- alerts (max 3 a day): regime change, watchlist levels reached, Sunday guide
    sent = 0
    if prev and prev.get("economy", {}).get("regime") and prev["economy"]["regime"] != reg:
        _nm.alert("Bias Desk: economy changed", f"Economy model moved from {prev['economy']['regime']} to {reg} ({conf} confidence).\n{REGIME_TEXT[reg]}", "default", ["compass"], SITE); sent += 1
    if prev:
        old = {(z["ticker"], z["setup"]): z for z in prev.get("swing", [])}
        for z in swing[:25]:
            o = old.get((z["ticker"], z["setup"]))
            trig = (z.get("levels") or {}).get("trigger")
            if o and trig and o.get("price") and o["price"] < trig <= z["price"] and sent < 3:
                _nm.alert(f"Level reached: {z['ticker']}", f"{z['name']} closed at {z['price']}, above its 52-week-high trigger {trig}.\nDo your TA before acting.", "high", ["dart"], SITE); sent += 1
    if datetime.now(SAST).weekday() == 6 and sent < 3:  # Sunday guide
        lines = [f"Economy: {reg} ({conf})", "Strongest sectors: " + ", ".join(f"{r['sector']} ({r['rs3_pct']:+.1f}%)" for r in sect[:3])]
        lines += ["Look at this week:"] + [f"- {k.split('|')[0]}: {next(z['setup_name'] for z in swing if z['ticker'] + '|' + z['setup'] == k)}" for k in top3]
        _nm.alert("Bias Desk weekly guide", "\n".join(lines), "default", ["chart_with_upwards_trend"], SITE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
