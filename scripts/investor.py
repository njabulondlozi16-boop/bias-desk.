#!/usr/bin/env python3
"""Bias Desk - Investor Desk: your free AI economist + stock scanner.

Runs on GitHub Actions once a day after the US close. Free data only:
  * Prices      - Yahoo Finance daily candles (US shares, ETFs, JSE shares, crypto)
  * Economy     - FRED (US Federal Reserve data): rates, inflation, jobs, credit stress, VIX, dollar, oil
  * Companies   - SEC EDGAR annual reports (revenue growth, margins, ROE, cash flow, debt, P/E)
  * News        - Google News headlines for the best candidates + the market
  * Writing     - free Gemini model (GEMINI_API_KEY secret, same as the bias job); plain templates if missing
Writes investor.json (read by the Investor page), investor_history.json (track record of every pick)
and investor_fundamentals.json (weekly cache of company data).

It does NOT tell you to buy anything. It tells you WHERE to go and do your technical analysis,
and why, then keeps score of its own ideas so you can see whether it is any good.

Only the Python standard library is used.
"""
import bisect, datetime, html, json, math, os, re, sys, time, urllib.parse, urllib.request
from zoneinfo import ZoneInfo

SAST = ZoneInfo("Africa/Johannesburg")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "investor.json")
HISTORY = os.path.join(ROOT, "investor_history.json")
FUND = os.path.join(ROOT, "investor_fundamentals.json")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
SEC_UA = os.environ.get("SEC_UA") or "BiasDesk investor research bias-desk-bot@users.noreply.github.com"

# ───────────────────────────────────────── universe: ticker -> (name, market, sector ETF)
SECTOR_NAMES = {"XLK": "Technology", "XLC": "Communication", "XLY": "Consumer discretionary", "XLP": "Consumer staples",
                "XLV": "Health care", "XLF": "Financials", "XLI": "Industrials", "XLE": "Energy", "XLB": "Materials",
                "XLU": "Utilities", "XLRE": "Real estate"}
UNIVERSE = {
    # US technology
    "AAPL": ("Apple", "US", "XLK"), "MSFT": ("Microsoft", "US", "XLK"), "NVDA": ("Nvidia", "US", "XLK"),
    "AVGO": ("Broadcom", "US", "XLK"), "AMD": ("AMD", "US", "XLK"), "ORCL": ("Oracle", "US", "XLK"),
    "CRM": ("Salesforce", "US", "XLK"), "ADBE": ("Adobe", "US", "XLK"), "QCOM": ("Qualcomm", "US", "XLK"),
    "MU": ("Micron", "US", "XLK"), "INTC": ("Intel", "US", "XLK"), "PLTR": ("Palantir", "US", "XLK"),
    "CRWD": ("CrowdStrike", "US", "XLK"), "PANW": ("Palo Alto Networks", "US", "XLK"), "NOW": ("ServiceNow", "US", "XLK"),
    # communication
    "GOOGL": ("Alphabet", "US", "XLC"), "META": ("Meta", "US", "XLC"), "NFLX": ("Netflix", "US", "XLC"),
    "DIS": ("Disney", "US", "XLC"),
    # consumer discretionary
    "AMZN": ("Amazon", "US", "XLY"), "TSLA": ("Tesla", "US", "XLY"), "HD": ("Home Depot", "US", "XLY"),
    "MCD": ("McDonald's", "US", "XLY"), "NKE": ("Nike", "US", "XLY"), "BKNG": ("Booking", "US", "XLY"),
    "SHOP": ("Shopify", "US", "XLY"), "UBER": ("Uber", "US", "XLI"),
    # staples
    "WMT": ("Walmart", "US", "XLP"), "COST": ("Costco", "US", "XLP"), "PG": ("Procter & Gamble", "US", "XLP"),
    "KO": ("Coca-Cola", "US", "XLP"), "PEP": ("PepsiCo", "US", "XLP"),
    # health care
    "LLY": ("Eli Lilly", "US", "XLV"), "UNH": ("UnitedHealth", "US", "XLV"), "JNJ": ("Johnson & Johnson", "US", "XLV"),
    "MRK": ("Merck", "US", "XLV"), "ABBV": ("AbbVie", "US", "XLV"), "PFE": ("Pfizer", "US", "XLV"),
    "TMO": ("Thermo Fisher", "US", "XLV"), "ISRG": ("Intuitive Surgical", "US", "XLV"),
    # financials
    "JPM": ("JPMorgan", "US", "XLF"), "BAC": ("Bank of America", "US", "XLF"), "GS": ("Goldman Sachs", "US", "XLF"),
    "MS": ("Morgan Stanley", "US", "XLF"), "V": ("Visa", "US", "XLF"), "MA": ("Mastercard", "US", "XLF"),
    "BRK-B": ("Berkshire Hathaway", "US", "XLF"), "AXP": ("American Express", "US", "XLF"), "COIN": ("Coinbase", "US", "XLF"),
    # industrials
    "CAT": ("Caterpillar", "US", "XLI"), "DE": ("Deere", "US", "XLI"), "GE": ("GE Aerospace", "US", "XLI"),
    "HON": ("Honeywell", "US", "XLI"), "LMT": ("Lockheed Martin", "US", "XLI"), "RTX": ("RTX", "US", "XLI"),
    "BA": ("Boeing", "US", "XLI"), "UNP": ("Union Pacific", "US", "XLI"),
    # energy / materials / utilities / real estate
    "XOM": ("ExxonMobil", "US", "XLE"), "CVX": ("Chevron", "US", "XLE"), "COP": ("ConocoPhillips", "US", "XLE"),
    "SLB": ("Schlumberger", "US", "XLE"), "LIN": ("Linde", "US", "XLB"), "FCX": ("Freeport-McMoRan", "US", "XLB"),
    "NEM": ("Newmont", "US", "XLB"), "NEE": ("NextEra Energy", "US", "XLU"), "DUK": ("Duke Energy", "US", "XLU"),
    "PLD": ("Prologis", "US", "XLRE"), "AMT": ("American Tower", "US", "XLRE"),
    # ETFs (indices, sectors, assets)
    "SPY": ("S&P 500", "ETF", None), "QQQ": ("Nasdaq 100", "ETF", None), "IWM": ("Russell 2000 small caps", "ETF", None),
    "DIA": ("Dow Jones", "ETF", None), "SMH": ("Semiconductors", "ETF", "XLK"),
    "XLK": ("Technology sector", "ETF", "XLK"), "XLC": ("Communication sector", "ETF", "XLC"),
    "XLY": ("Consumer discretionary sector", "ETF", "XLY"), "XLP": ("Consumer staples sector", "ETF", "XLP"),
    "XLV": ("Health care sector", "ETF", "XLV"), "XLF": ("Financials sector", "ETF", "XLF"),
    "XLI": ("Industrials sector", "ETF", "XLI"), "XLE": ("Energy sector", "ETF", "XLE"),
    "XLB": ("Materials sector", "ETF", "XLB"), "XLU": ("Utilities sector", "ETF", "XLU"),
    "XLRE": ("Real estate sector", "ETF", "XLRE"),
    "GLD": ("Gold", "Commodity", "GLD"), "SLV": ("Silver", "Commodity", "GLD"), "USO": ("Crude oil", "Commodity", "XLE"),
    "TLT": ("US long bonds (20y+)", "Bond", "TLT"), "EEM": ("Emerging markets", "ETF", None),
    # crypto
    "BTC-USD": ("Bitcoin", "Crypto", None), "ETH-USD": ("Ethereum", "Crypto", None), "SOL-USD": ("Solana", "Crypto", None),
    # JSE (prices in cents)
    "NPN.JO": ("Naspers", "JSE", None), "PRX.JO": ("Prosus", "JSE", None), "CPI.JO": ("Capitec", "JSE", None),
    "FSR.JO": ("FirstRand", "JSE", None), "SBK.JO": ("Standard Bank", "JSE", None), "MTN.JO": ("MTN Group", "JSE", None),
    "AGL.JO": ("Anglo American", "JSE", None), "BHG.JO": ("BHP Group", "JSE", None), "SOL.JO": ("Sasol", "JSE", None),
    "SHP.JO": ("Shoprite", "JSE", None), "GFI.JO": ("Gold Fields", "JSE", None), "ANG.JO": ("AngloGold Ashanti", "JSE", None),
    "VOD.JO": ("Vodacom", "JSE", None), "ABG.JO": ("Absa", "JSE", None),
}
BENCH = "SPY"

# what each economic regime tends to favour (classic sector-rotation playbook)
REGIME_TILT = {
    "Expansion (risk-on)":       (["XLK", "XLY", "XLI", "XLF", "SMH", "XLC"], ["XLU", "XLP", "TLT"]),
    "Overheating (late cycle)":  (["XLE", "XLB", "XLF", "GLD", "XLI"], ["TLT", "XLU", "XLRE"]),
    "Slowdown (risk-off)":       (["XLV", "XLP", "XLU", "TLT", "GLD"], ["XLY", "XLI", "XLB", "IWM"]),
    "Stagflation risk":          (["GLD", "XLE", "XLP", "XLV"], ["XLY", "TLT", "XLRE", "IWM"]),
    "Recovery (early cycle)":    (["IWM", "XLY", "XLF", "XLI", "XLB"], ["XLU", "XLP"]),
}

POS = re.compile(r"\b(beat|beats|tops|upgrade[sd]?|raises?|raised|record|surges?|soars?|jumps?|rall(y|ies)|approv(al|ed)|"
                 r"wins?|buyback|outperform|strong demand|boosts?|expands?|partnership|bullish)\b", re.I)
NEG = re.compile(r"\b(miss(es)?|downgrade[sd]?|cuts?|plunges?|falls?|slumps?|sinks?|tumbles?|lawsuit|probe|investigation|"
                 r"recall|layoffs?|warning|warns|bankrupt\w*|fraud|halt\w*|bearish|weak|delay(s|ed)?|fine[sd]?)\b", re.I)


# ───────────────────────────────────────── helpers
def get(url, timeout=25, ua=UA, tries=3):
    last = None
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept-Language": "en-US,en;q=0.9"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            last = e
            time.sleep(1.5 * (k + 1))
    raise last


def sma(x, n):
    return sum(x[-n:]) / n if len(x) >= n else None


def pct(a, b):
    return (a / b - 1) * 100 if a and b else None


def rsi(close, n=14):
    if len(close) < n + 2:
        return None
    gains = losses = 0.0
    for i in range(1, n + 1):
        d = close[i] - close[i - 1]
        gains += max(d, 0); losses += max(-d, 0)
    ag, al = gains / n, losses / n
    for i in range(n + 1, len(close)):
        d = close[i] - close[i - 1]
        ag = (ag * (n - 1) + max(d, 0)) / n
        al = (al * (n - 1) + max(-d, 0)) / n
    return 100.0 if al == 0 else 100 - 100 / (1 + ag / al)


def atr_pct(h, l, c, n=14):
    if len(c) < n + 1:
        return None
    trs = [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(len(c) - n, len(c))]
    return sum(trs) / n / c[-1] * 100


def rank_pct(values):
    """dict key->value  ->  key->percentile 0..100 (None stays None)"""
    items = sorted((v, k) for k, v in values.items() if v is not None)
    n = len(items)
    out = {k: None for k in values}
    for i, (_, k) in enumerate(items):
        out[k] = 100.0 * i / (n - 1) if n > 1 else 50.0
    return out


def fmt_price(p, market):
    if p is None:
        return None
    if market == "JSE":
        return round(p)               # cents
    return round(p, 2) if p >= 1 else round(p, 4)


def tv_symbol(t, market):
    if market == "JSE":
        return "JSE:" + t.replace(".JO", "")
    if market == "Crypto":
        return "COINBASE:" + t.replace("-", "")
    return t.replace("-", ".")


# ───────────────────────────────────────── data
def yahoo(ticker):
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(ticker)}"
           f"?range=2y&interval=1d&includeAdjustedClose=true")
    j = json.loads(get(url))
    r = j["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    adj = (r["indicators"].get("adjclose") or [{}])[0].get("adjclose") or q["close"]
    rows = [(t, o, h, l, c, a, v) for t, o, h, l, c, a, v in
            zip(r["timestamp"], q["open"], q["high"], q["low"], q["close"], adj, q["volume"])
            if None not in (o, h, l, c, a)]
    return {"t": [x[0] for x in rows], "o": [x[1] for x in rows], "h": [x[2] for x in rows],
            "l": [x[3] for x in rows], "c": [x[4] for x in rows], "a": [x[5] for x in rows],
            "v": [x[6] or 0 for x in rows]}


def fred(series):
    txt = get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}")
    out = []
    for line in txt.strip().splitlines()[1:]:
        p = line.split(",")
        try:
            out.append((p[0], float(p[1])))
        except (ValueError, IndexError):
            pass
    return out


def google_news(query, limit=6, days=3):
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": f"{query} when:{days}d", "hl": "en-US", "gl": "US", "ceid": "US:en"})
    xml = get(url)
    items = []
    for it in re.findall(r"<item>(.*?)</item>", xml, re.S)[:limit]:
        title = html.unescape(re.sub(r"<.*?>", "", (re.search(r"<title>(.*?)</title>", it, re.S) or [None, ""])[1]))
        link = (re.search(r"<link>(.*?)</link>", it, re.S) or [None, ""])[1].strip()
        src = html.unescape((re.search(r"<source[^>]*>(.*?)</source>", it, re.S) or [None, ""])[1])
        date = (re.search(r"<pubDate>(.*?)</pubDate>", it, re.S) or [None, ""])[1]
        if title:
            items.append({"title": title, "link": link, "source": src, "date": date})
    return items


def tone_of(titles):
    p = sum(len(POS.findall(t)) for t in titles)
    n = sum(len(NEG.findall(t)) for t in titles)
    return (p - n) / max(p + n, 1), p, n


# ───────────────────────────────────────── fundamentals (SEC EDGAR, weekly cache)
CONCEPTS = {
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet",
                "RevenuesNetOfInterestExpense"],
    "net_income": ["NetIncomeLoss"],
    "equity": ["StockholdersEquity"],
    "ocf": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment"],
    "debt": ["LongTermDebtNoncurrent", "LongTermDebt"],
    "eps": ["EarningsPerShareDiluted", "EarningsPerShareBasic"],
}


def annual_values(facts, names, instant=False):
    for name in names:
        node = facts.get("us-gaap", {}).get(name)
        if not node:
            continue
        units = node.get("units", {})
        vals = units.get("USD") or units.get("USD/shares") or []
        by_end = {}
        for v in vals:
            if v.get("form") not in ("10-K", "10-K/A", "20-F", "40-F") or v.get("fp") != "FY":
                continue
            if not instant:
                try:
                    days = (datetime.date.fromisoformat(v["end"]) - datetime.date.fromisoformat(v["start"])).days
                except (KeyError, ValueError):
                    continue
                if not 340 <= days <= 380:
                    continue
            by_end[v["end"]] = v["val"]
        if by_end:
            return [by_end[k] for k in sorted(by_end)]
    return []


def fundamentals(tickers):
    cache = {}
    if os.path.exists(FUND):
        cache = json.load(open(FUND))
    age = (datetime.date.today() - datetime.date.fromisoformat(cache.get("date", "2000-01-01"))).days
    if age < 7 and cache.get("data"):
        print(f"[fund] using cache from {cache['date']}")
        return cache["data"]
    print("[fund] refreshing SEC company data (weekly)")
    try:
        cik_map = {v["ticker"].upper(): str(v["cik_str"]).zfill(10)
                   for v in json.loads(get("https://www.sec.gov/files/company_tickers.json", ua=SEC_UA)).values()}
    except Exception as e:
        print("[fund] SEC ticker list failed:", e)
        return cache.get("data", {})
    data = {}
    for t in tickers:
        cik = cik_map.get(t.replace("-", ".").upper()) or cik_map.get(t.replace("-", "").upper())
        if not cik:
            continue
        try:
            facts = json.loads(get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json", ua=SEC_UA, timeout=40))["facts"]
        except Exception as e:
            print(f"[fund] {t}: {e}")
            continue
        rev, ni = annual_values(facts, CONCEPTS["revenue"]), annual_values(facts, CONCEPTS["net_income"])
        eq, ocf = annual_values(facts, CONCEPTS["equity"], True), annual_values(facts, CONCEPTS["ocf"])
        capex, debt = annual_values(facts, CONCEPTS["capex"]), annual_values(facts, CONCEPTS["debt"], True)
        eps = annual_values(facts, CONCEPTS["eps"])
        d = {}
        if len(rev) >= 2 and rev[-2] > 0:
            d["rev_growth"] = round((rev[-1] / rev[-2] - 1) * 100, 1)
        if rev and ni and rev[-1] > 0:
            d["net_margin"] = round(ni[-1] / rev[-1] * 100, 1)
        if eq and ni and eq[-1] > 0:
            d["roe"] = round(ni[-1] / eq[-1] * 100, 1)
        if rev and ocf and rev[-1] > 0:
            d["fcf_margin"] = round((ocf[-1] - (capex[-1] if capex else 0)) / rev[-1] * 100, 1)
        if eq and debt and eq[-1] > 0:
            d["debt_equity"] = round(debt[-1] / eq[-1], 2)
        if eps:
            d["eps"] = eps[-1]
        data[t] = d
        time.sleep(0.15)                                   # SEC asks for <= 10 requests a second
    json.dump({"date": datetime.date.today().isoformat(), "data": data}, open(FUND, "w"), indent=1)
    print(f"[fund] {len(data)} companies")
    return data


# ───────────────────────────────────────── economy: regime from FRED
def macro():
    def series(sid):
        try:
            return fred(sid)
        except Exception as e:
            print(f"[macro] {sid}: {e}")
            return []

    def last(s):
        return s[-1][1] if s else None

    def ago(s, days):
        if not s:
            return None
        cut = (datetime.date.fromisoformat(s[-1][0]) - datetime.timedelta(days=days)).isoformat()
        prev = [v for d, v in s if d <= cut]
        return prev[-1] if prev else None

    cpi, unrate, ffr = series("CPIAUCSL"), series("UNRATE"), series("DFF")
    y10, curve, hy, vix = series("DGS10"), series("T10Y2Y"), series("BAMLH0A0HYM2"), series("VIXCLS")
    usd, oil, claims = series("DTWEXBGS"), series("DCOILWTICO"), series("ICSA")

    infl = pct(last(cpi), ago(cpi, 365)) if cpi else None
    infl_3m = pct(ago(cpi, 90), ago(cpi, 455)) if cpi else None
    un_now = last(unrate)
    un_low12 = min([v for d, v in unrate[-13:]]) if unrate else None
    sahm = (sum(v for _, v in unrate[-3:]) / 3 - un_low12) if len(unrate) >= 13 else None
    claims_chg = pct(sum(v for _, v in claims[-4:]) / 4, sum(v for _, v in claims[-30:-26]) / 4) if len(claims) >= 30 else None
    hy_now, hy_avg = last(hy), (sum(v for _, v in hy[-250:]) / len(hy[-250:]) if hy else None)
    signals = []

    def sig(name, value, read, tone, unit=""):
        signals.append({"name": name, "value": None if value is None else round(value, 2), "unit": unit,
                        "read": read, "tone": tone})

    if infl is not None:
        rising = infl_3m is not None and infl > infl_3m + 0.2
        sig("Inflation (CPI, yearly)", infl, f"{'rising' if rising else 'cooling or steady'}"
            f"{' - above the Fed 2% target' if infl > 2.5 else ''}", -1 if rising else 1, "%")
    if un_now is not None:
        sig("Unemployment", un_now, "jobs weakening (recession warning)" if sahm is not None and sahm >= 0.5
            else "jobs market holding up", -1 if sahm is not None and sahm >= 0.5 else 1, "%")
    if claims_chg is not None:
        sig("Jobless claims trend (6 months)", claims_chg, "more people losing jobs" if claims_chg > 10 else "stable",
            -1 if claims_chg > 10 else 0, "%")
    if ffr:
        chg = (last(ffr) - ago(ffr, 180)) if ago(ffr, 180) is not None else 0
        sig("Fed interest rate", last(ffr), "being cut (easier money)" if chg < -0.1 else
            "being raised (tighter money)" if chg > 0.1 else "on hold", 1 if chg < -0.1 else -1 if chg > 0.1 else 0, "%")
    if y10:
        chg = (last(y10) - ago(y10, 90)) if ago(y10, 90) is not None else 0
        sig("10-year bond yield", last(y10), f"{'up' if chg > 0 else 'down'} {abs(chg):.2f} in 3 months"
            f"{' - pressure on growth stocks' if chg > 0.3 else ''}", -1 if chg > 0.3 else 1 if chg < -0.3 else 0, "%")
    if curve:
        c = last(curve)
        sig("Yield curve (10y minus 2y)", c, "inverted - classic recession warning" if c < 0 else "normal",
            -1 if c < 0 else 1, "%")
    if hy_now is not None:
        stress = hy_now > hy_avg * 1.15
        sig("Credit stress (junk bond spread)", hy_now, "rising - investors getting nervous" if stress
            else "calm - credit flowing", -1 if stress else 1, "%")
    if vix:
        v = last(vix)
        sig("Fear index (VIX)", v, "high fear" if v > 25 else "elevated" if v > 18 else "calm", -1 if v > 25 else 0 if v > 18 else 1)
    if usd:
        chg = pct(last(usd), ago(usd, 90))
        sig("US dollar (3 months)", chg, "stronger dollar - tough for gold, EM and JSE" if chg and chg > 2 else
            "weaker dollar - helps gold, EM and JSE" if chg and chg < -2 else "steady", 0, "%")
    if oil:
        chg = pct(last(oil), ago(oil, 90))
        sig("Oil price (3 months)", chg, "rising - inflation pressure, good for energy" if chg and chg > 10 else
            "falling - eases inflation" if chg and chg < -10 else "steady", 0, "%")

    growth_bad = (sahm is not None and sahm >= 0.5) or (claims_chg is not None and claims_chg > 15)
    infl_hot = infl is not None and infl > 3 and infl_3m is not None and infl >= infl_3m
    stress = hy_now is not None and hy_now > hy_avg * 1.15
    if growth_bad and infl_hot:
        regime = "Stagflation risk"
    elif growth_bad or stress:
        regime = "Slowdown (risk-off)"
    elif infl_hot:
        regime = "Overheating (late cycle)"
    elif ffr and ago(ffr, 180) is not None and last(ffr) < ago(ffr, 180) - 0.25 and (un_now or 0) > (un_low12 or 0) + 0.3:
        regime = "Recovery (early cycle)"
    else:
        regime = "Expansion (risk-on)"
    fav, avoid = REGIME_TILT[regime]
    return {"regime": regime, "favor": fav, "avoid": avoid, "signals": signals}


# ───────────────────────────────────────── technical picture per ticker
def analyse(t, d, bench):
    c, a, h, l, v = d["c"], d["a"], d["h"], d["l"], d["v"]
    if len(a) < 210:
        return None
    s20, s50, s200 = sma(a, 20), sma(a, 50), sma(a, 200)
    price = c[-1]
    k = c[-1] / a[-1] if a[-1] else 1                      # adjusted -> real price scale
    r = {n: pct(a[-1], a[-1 - p]) for n, p in (("r1m", 21), ("r3m", 63), ("r6m", 126), ("r12m", 252)) if len(a) > p}
    ba = bench["a"] if bench else None
    rs3 = (r.get("r3m") or 0) - (pct(ba[-1], ba[-64]) or 0) if ba and len(ba) > 64 else None
    rs6 = (r.get("r6m") or 0) - (pct(ba[-1], ba[-127]) or 0) if ba and len(ba) > 127 else None
    hi52, lo52 = max(h[-252:]), min(l[-252:])
    hi3m, lo1m = max(h[-63:]), min(l[-21:])
    vol_ratio = (sum(v[-5:]) / 5) / (sum(v[-50:]) / 50) if sum(v[-50:]) > 0 else None
    return {
        "price": price, "s20": s20 * k, "s50": s50 * k, "s200": s200 * k,
        "up": a[-1] > s50 > s200, "down": a[-1] < s50 < s200, "above200": a[-1] > s200,
        "rsi": rsi(a[-120:]), "atr": atr_pct(h, l, c), "vol_ratio": vol_ratio,
        "hi52": hi52, "lo52": lo52, "hi3m": hi3m, "lo1m": lo1m, "hi1m": max(h[-21:]),
        "d_hi52": pct(price, hi52), "d_lo52": pct(price, lo52), "d_s50": pct(a[-1], s50),
        "rs3": rs3, "rs6": rs6, **r,
    }


def swing_setup(x):
    """Which swing pattern is forming -> (side, setup name, base points, key levels)"""
    rsi_ = x["rsi"] or 50
    if x["up"] and x["d_hi52"] is not None and x["d_hi52"] > -3 and 52 <= rsi_ <= 78:
        return 1, "Breakout watch", 30, {"trigger": x["hi52"], "support": x["s20"], "stop_idea": x["lo1m"]}
    if x["up"] and pct(x["price"], x["hi3m"]) is not None and pct(x["price"], x["hi3m"]) > -2 and 52 <= rsi_ <= 78:
        return 1, "Breakout watch (3-month high)", 25, {"trigger": x["hi3m"], "support": x["s20"], "stop_idea": x["lo1m"]}
    if x["above200"] and x["s50"] > x["s200"] and x["d_s50"] is not None and -3 <= x["d_s50"] <= 2 and rsi_ <= 52:
        return 1, "Pullback in uptrend", 28, {"buy_zone": x["s50"], "support": x["s200"], "target_idea": x["hi1m"]}
    if x["down"] and x["d_lo52"] is not None and x["d_lo52"] < 4 and 20 <= rsi_ <= 48:
        return -1, "Breakdown watch", 25, {"trigger": x["lo52"], "resistance": x["s20"], "stop_idea": x["hi1m"]}
    if x["down"] and x["d_s50"] is not None and -2 <= x["d_s50"] <= 3 and rsi_ >= 45:
        return -1, "Bear rally into resistance", 24, {"sell_zone": x["s50"], "resistance": x["s200"], "target_idea": x["lo1m"]}
    return 0, None, 0, {}


# ───────────────────────────────────────── track record
def update_history(date, picks, data):
    hist = json.load(open(HISTORY)) if os.path.exists(HISTORY) else {"about": "Every pick the Investor Desk made", "days": {}}
    hist["days"][date] = picks
    keep = (datetime.date.fromisoformat(date) - datetime.timedelta(days=420)).isoformat()
    hist["days"] = {k: v for k, v in hist["days"].items() if k >= keep}
    json.dump(hist, open(HISTORY, "w"), indent=1)
    # score old picks: return after 5 / 20 / 60 trading days, in the pick's direction, vs SPY
    bench = data.get(BENCH)
    res = {}
    for horizon in (5, 20, 60):
        for lst in ("swing", "longterm"):
            n = hits = 0
            tot = exc = 0.0
            for day, p in hist["days"].items():
                ts0 = datetime.datetime.fromisoformat(day + "T23:59:00").timestamp()
                for t, info in p.get(lst, {}).items():
                    d = data.get(t)
                    if not d:
                        continue
                    i0 = bisect.bisect_right(d["t"], ts0) - 1
                    if i0 < 0 or i0 + horizon >= len(d["a"]):
                        continue
                    ret = pct(d["a"][i0 + horizon], d["a"][i0]) * info.get("side", 1)
                    bret = 0.0
                    if bench:
                        j0 = bisect.bisect_right(bench["t"], ts0) - 1
                        if j0 >= 0 and j0 + horizon < len(bench["a"]):
                            bret = pct(bench["a"][j0 + horizon], bench["a"][j0]) * info.get("side", 1)
                    n += 1; hits += ret > 0; tot += ret; exc += ret - bret
            if n:
                res[f"{lst}_{horizon}d"] = {"picks": n, "hit_rate": round(hits / n * 100, 1),
                                            "avg_return": round(tot / n, 2), "vs_spy": round(exc / n, 2)}
    return res


# ───────────────────────────────────────── AI writing (free Gemini, optional)
def ask_gemini(prompt):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None
    models = []
    try:
        lst = json.loads(get("https://generativelanguage.googleapis.com/v1beta/models?pageSize=200&key=" + key))
        names = [m["name"].split("/")[-1] for m in lst.get("models", [])
                 if "generateContent" in m.get("supportedGenerationMethods", [])]
        models = sorted([n for n in names if re.match(r"gemini-[\d.]+-flash(-lite)?$", n)], reverse=True)
    except Exception as e:
        print("[ai] model list failed:", e)
    for model in (models or ["gemini-2.5-flash", "gemini-2.0-flash"])[:5]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
        body = json.dumps({"contents": [{"parts": [{"text": prompt}]}],
                           "generationConfig": {"temperature": 0.3, "responseMimeType": "application/json"}}).encode()
        try:
            req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=90) as r:
                j = json.loads(r.read().decode())
            text = j["candidates"][0]["content"]["parts"][0]["text"]
            print(f"[ai] written by {model}")
            return json.loads(text), model
        except Exception as e:
            print(f"[ai] {model}: {e}")
    return None


def ai_commentary(mac, sectors, swing, longterm, headlines):
    facts = {
        "regime": mac["regime"], "signals": [f"{s['name']}: {s['value']}{s['unit']} ({s['read']})" for s in mac["signals"]],
        "sector_leaders": [f"{s['name']} {s['r3m']:+.1f}% 3m" for s in sectors[:3] if s.get("r3m") is not None],
        "sector_laggards": [f"{s['name']} {s['r3m']:+.1f}% 3m" for s in sectors[-3:] if s.get("r3m") is not None],
        "market_headlines": [h["title"] for h in headlines[:10]],
        "swing": [{"t": s["ticker"], "name": s["name"], "side": s["side"], "setup": s["setup"], "facts": s["why"],
                   "headlines": [h["title"] for h in s["news"]["headlines"][:4]]} for s in swing[:10]],
        "longterm": [{"t": s["ticker"], "name": s["name"], "facts": s["why"]} for s in longterm[:8]],
    }
    prompt = ("You are a careful macro economist and equity analyst writing a daily note for a young trader in "
              "South Africa. Use ONLY the facts given (no invented numbers). Plain English, short sentences.\n"
              "Return JSON: {\"summary\": \"4-6 sentences: what the economy is doing, what that usually means for "
              "markets, which areas to focus on and which to be careful with\", "
              "\"risks\": [\"up to 3 short risks to watch this week\"], "
              "\"notes\": {\"TICKER\": \"1-2 sentences: why this is worth a technical look now and what would "
              "confirm or cancel the idea\"}}\nFACTS:\n" + json.dumps(facts))
    r = ask_gemini(prompt)
    return r if r else None


def clean(o):
    """NaN / infinity are not valid JSON for the website -> null"""
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    return o


# ───────────────────────────────────────── main
def main():
    now = datetime.datetime.now(SAST)
    date = now.strftime("%Y-%m-%d")
    if os.environ.get("INV_AUTO") == "true" and os.path.exists(OUT):
        try:
            if json.load(open(OUT)).get("date") == date:
                print("Already ran today."); return
        except Exception:
            pass

    print("[prices] downloading", len(UNIVERSE), "tickers")
    data = {}
    for t in UNIVERSE:
        try:
            data[t] = yahoo(t)
        except Exception as e:
            print(f"[prices] {t}: {e}")
        time.sleep(0.25)
    if len(data) < 20:
        sys.exit("Too few prices downloaded - Yahoo may be blocking; keeping yesterday's file.")
    bench = data.get(BENCH)
    tech = {t: x for t, x in ((t, analyse(t, d, bench)) for t, d in data.items()) if x}

    mac = macro()
    print("[macro]", mac["regime"])

    # sectors ranked by 3-month strength
    sectors = []
    for etf, name in SECTOR_NAMES.items():
        x = tech.get(etf)
        if x:
            sectors.append({"etf": etf, "name": name, "r1m": x.get("r1m"), "r3m": x.get("r3m"), "r6m": x.get("r6m"),
                            "trend": "up" if x["up"] else "down" if x["down"] else "mixed",
                            "macro": "favoured" if etf in mac["favor"] else "avoid" if etf in mac["avoid"] else ""})
    sectors.sort(key=lambda s: s["r3m"] if s["r3m"] is not None else -999, reverse=True)
    sector_rank = {s["etf"]: i for i, s in enumerate(sectors)}

    rs_rank = rank_pct({t: x.get("rs6") for t, x in tech.items()})

    # ── swing candidates
    cands = []
    for t, x in tech.items():
        name, market, sec = UNIVERSE[t]
        side, setup, base, levels = swing_setup(x)
        if not side:
            continue
        score, why = base, []
        rs = rs_rank.get(t)
        if rs is not None:
            pts = (rs if side == 1 else 100 - rs) * 0.30
            score += pts
            why.append(f"Stronger than {rs:.0f}% of the list over 6 months" if side == 1
                       else f"Weaker than {100 - rs:.0f}% of the list over 6 months")
        if x["vol_ratio"] and x["vol_ratio"] > 1.2:
            score += 8
            why.append(f"Volume {x['vol_ratio']:.1f}x its normal level this week - big players active")
        fit = 0
        if sec in mac["favor"] or t in mac["favor"]:
            fit = 1 if side == 1 else -1
        elif sec in mac["avoid"] or t in mac["avoid"]:
            fit = -1 if side == 1 else 1
        score += 12 * fit
        if fit:
            why.append(f"{'Fits' if fit > 0 else 'Goes against'} the economic picture ({mac['regime']})")
        if sec in sector_rank:
            sr = sector_rank[sec]
            if (side == 1 and sr <= 2) or (side == -1 and sr >= len(sectors) - 3):
                score += 8
                why.append(f"Its sector ({SECTOR_NAMES.get(sec, sec)}) is among the {'strongest' if side == 1 else 'weakest'} right now")
        why.insert(0, f"{setup}: price {fmt_price(x['price'], market)}, RSI {x['rsi']:.0f}, "
                      f"{'above' if x['above200'] else 'below'} the 200-day average")
        cands.append({"ticker": t, "name": name, "market": market, "side": side, "setup": setup,
                      "score": round(score, 1), "price": fmt_price(x["price"], market),
                      "levels": {k: fmt_price(v, market) for k, v in levels.items()},
                      "atr_pct": round(x["atr"], 2) if x["atr"] else None,
                      "r1m": x.get("r1m"), "r3m": x.get("r3m"), "why": why, "tv": tv_symbol(t, market)})
    cands.sort(key=lambda c: c["score"], reverse=True)

    # news for the top candidates; adjust score by headline tone
    for c in cands[:30]:
        try:
            hl = google_news(f'"{c["name"]}" stock' if c["market"] != "Crypto" else c["name"], limit=6)
        except Exception as e:
            print(f"[news] {c['ticker']}: {e}")
            hl = []
        tone, p, n = tone_of([h["title"] for h in hl])
        c["news"] = {"count": len(hl), "tone": round(tone, 2), "headlines": hl[:5]}
        if hl and abs(tone) >= 0.3:
            agree = (tone > 0) == (c["side"] == 1)
            c["score"] += 8 if agree else -8
            c["why"].append(f"News flow {'supports' if agree else 'goes against'} the idea ({p} positive vs {n} negative headlines)")
        time.sleep(0.4)
    for c in cands[30:]:
        c["news"] = {"count": 0, "tone": 0, "headlines": []}
    cands.sort(key=lambda c: c["score"], reverse=True)
    swing = [c for c in cands if c["side"] == 1][:12] + [c for c in cands if c["side"] == -1][:6]
    swing.sort(key=lambda c: c["score"], reverse=True)

    # ── long-term candidates
    fund = fundamentals([t for t, (n, m, s) in UNIVERSE.items() if m == "US"])
    lt = []
    q_rank = rank_pct({t: (f.get("roe") or 0) * 0.4 + (f.get("net_margin") or 0) * 0.3 + (f.get("fcf_margin") or 0) * 0.3
                       for t, f in fund.items() if f})
    g_rank = rank_pct({t: f.get("rev_growth") for t, f in fund.items()})
    for t, x in tech.items():
        name, market, sec = UNIVERSE[t]
        f = fund.get(t, {})
        why, parts = [], {}
        trend = (50 if x["above200"] else 0) + (25 if x["up"] else 0) + max(min((x.get("r12m") or 0), 50), -50) / 2
        parts["trend"] = round(trend, 1)
        if f:
            pe = x["price"] / f["eps"] if f.get("eps") and f["eps"] > 0 else None
            growth = f.get("rev_growth")
            peg = pe / growth if pe and growth and growth > 0 else None
            value = 100 - min(peg * 33, 100) if peg else (40 if pe and pe < 20 else 20 if pe else 0)
            quality, grow = q_rank.get(t) or 0, g_rank.get(t) or 0
            score = 0.35 * quality + 0.25 * grow + 0.20 * value + 0.20 * trend
            parts.update(quality=round(quality), growth=round(grow), value=round(value))
            if f.get("roe") is not None:
                why.append(f"Return on equity {f['roe']:.0f}%, profit margin {f.get('net_margin', 0):.0f}%")
            if growth is not None:
                why.append(f"Revenue grew {growth:+.0f}% last year")
            if pe:
                why.append(f"P/E {pe:.0f}" + (f" (PEG {peg:.1f} - {'cheap' if peg < 1.2 else 'fair' if peg < 2 else 'pricey'} for its growth)" if peg else ""))
            if f.get("debt_equity") is not None:
                why.append(f"Debt/equity {f['debt_equity']:.1f} ({'low' if f['debt_equity'] < 0.6 else 'moderate' if f['debt_equity'] < 1.5 else 'high'})")
            kind = "company"
            metrics = {**f, "pe": round(pe, 1) if pe else None}
        else:
            score = 0.6 * trend + 0.4 * ((rs_rank.get(t) or 0))
            kind = "trend-only"
            metrics = {}
            why.append("No company accounts used (ETF, crypto or JSE) - ranked on long-term trend and strength")
        if sec in mac["favor"] or t in mac["favor"]:
            score += 10
            why.append(f"Favoured in the current economy ({mac['regime']})")
        elif sec in mac["avoid"] or t in mac["avoid"]:
            score -= 10
            why.append(f"Usually struggles in the current economy ({mac['regime']})")
        if not x["above200"]:
            score -= 15
            why.append("Wait: still in a downtrend - let price get back above its 200-day average before buying")
        why.insert(0, f"{'Above' if x['above200'] else 'Below'} its 200-day average, {(x.get('r12m') or 0):+.0f}% over 12 months")
        lt.append({"ticker": t, "name": name, "market": market, "score": round(score, 1), "kind": kind,
                   "price": fmt_price(x["price"], market), "parts": parts, "metrics": metrics,
                   "levels": {"s200": fmt_price(x["s200"], market), "s50": fmt_price(x["s50"], market),
                              "hi52": fmt_price(x["hi52"], market)},
                   "why": why, "tv": tv_symbol(t, market)})
    lt.sort(key=lambda c: c["score"], reverse=True)
    longterm = [c for c in lt if c["kind"] == "company"][:12] + [c for c in lt if c["kind"] == "trend-only"][:6]

    # market headlines
    headlines = []
    for q in ("stock market", "Federal Reserve economy", "JSE stocks rand"):
        try:
            headlines += google_news(q, limit=5, days=1)
        except Exception as e:
            print(f"[news] {q}: {e}")

    # AI note (free Gemini) or plain template
    ai = ai_commentary(mac, sectors, swing, longterm, headlines)
    model = None
    if ai:
        ai, model = ai
        for c in swing + longterm:
            note = (ai.get("notes") or {}).get(c["ticker"])
            if note:
                c["ai_note"] = note
    good = [s["name"] for s in mac["signals"] if s["tone"] > 0]
    bad = [s["name"] for s in mac["signals"] if s["tone"] < 0]
    summary = (ai or {}).get("summary") or (
        f"The economy reads as {mac['regime']}. Supportive: {', '.join(good) or 'nothing major'}. "
        f"Warning signs: {', '.join(bad) or 'none major'}. In this kind of economy "
        f"{', '.join(SECTOR_NAMES.get(e, UNIVERSE.get(e, (e,))[0]) for e in mac['favor'][:3])} usually do best, while "
        f"{', '.join(SECTOR_NAMES.get(e, UNIVERSE.get(e, (e,))[0]) for e in mac['avoid'][:3])} usually lag.")

    picks = {"swing": {c["ticker"]: {"side": c["side"], "setup": c["setup"], "price": c["price"]} for c in swing},
             "longterm": {c["ticker"]: {"side": 1, "price": c["price"]} for c in longterm}}
    track = update_history(date, picks, data)

    out = {
        "date": date, "generated_at": now.strftime("%H:%M SAST"), "model": model,
        "coverage": {"tickers": len(tech), "companies_with_accounts": len(fund)},
        "macro": {**mac, "summary": summary, "risks": (ai or {}).get("risks", [])},
        "sectors": sectors, "swing": swing, "longterm": longterm, "headlines": headlines[:12], "track": track,
        "note": "Ideas to research, not advice. Always confirm on the chart with your own technical analysis.",
    }
    json.dump(clean(out), open(OUT, "w"), indent=1, allow_nan=False)
    print(f"Saved investor.json: {len(swing)} swing ideas, {len(longterm)} long-term ideas")


if __name__ == "__main__":
    main()
