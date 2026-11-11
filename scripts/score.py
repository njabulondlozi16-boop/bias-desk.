#!/usr/bin/env python3
"""Bias Desk — daily fundamental bias scorer.

Runs on GitHub Actions every morning (04:40 SAST) so scores are ready by 05:00.
1. Collects today's market news for every currency / asset (Trading Economics pages,
   with Google News headlines as a backup).
2. Asks a free Gemini model to score each instrument from -10 (strong bearish) to
   +10 (strong bullish), weighting each driver by how much it usually moves price.
3. Writes scores.json, which the website reads automatically.

Only the Python standard library is used. Needs the GEMINI_API_KEY repository secret.
"""
import datetime, html, json, os, re, sys, time, urllib.parse, urllib.request
from zoneinfo import ZoneInfo

SAST = ZoneInfo("Africa/Johannesburg")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "scores.json")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"

# What drives each instrument -> where to read about it
SOURCES = {
    "USD": ("US dollar / Fed", ["https://tradingeconomics.com/united-states/currency"], "US dollar index Federal Reserve"),
    "EUR": ("Euro / ECB", ["https://tradingeconomics.com/euro-area/currency"], "euro ECB"),
    "GBP": ("British pound / BoE", ["https://tradingeconomics.com/united-kingdom/currency"], "British pound Bank of England"),
    "AUD": ("Australian dollar / RBA", ["https://tradingeconomics.com/australia/currency"], "Australian dollar RBA"),
    "NZD": ("New Zealand dollar / RBNZ", ["https://tradingeconomics.com/new-zealand/currency"], "New Zealand dollar RBNZ"),
    "CHF": ("Swiss franc / SNB", ["https://tradingeconomics.com/switzerland/currency"], "Swiss franc SNB"),
    "GOLD": ("Gold (XAUUSD)", ["https://tradingeconomics.com/commodity/gold"], "gold price"),
    "US30": ("Dow Jones (US30)", ["https://tradingeconomics.com/united-states/stock-market"], "Dow Jones stocks"),
    "US100": ("Nasdaq 100 (US100)", ["https://tradingeconomics.com/ndx:ind", "https://tradingeconomics.com/ccmp:ind"], "Nasdaq 100 tech stocks"),
    "GER30": ("DAX (GER30)", ["https://tradingeconomics.com/germany/stock-market"], "DAX German stocks"),
    "BTC": ("Bitcoin (BTCUSD)", ["https://tradingeconomics.com/btcusd:cur"], "bitcoin price"),
}
INSTRUMENTS = ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDCHF", "XAUUSD", "US30", "US100", "GER30", "BTCUSD"]
BOILERPLATE = re.compile(r"trading economics|cookie|subscribe|api access|data is supplied|all rights reserved|"
                         r"do not represent official|contract for difference|third-party providers|sign up|log in", re.I)


def label_for(s):
    if s >= 6: return "Strong Bullish"
    if s >= 3: return "Moderately Bullish"
    if s >= -2: return "Neutral"
    if s >= -5: return "Moderately Bearish"
    return "Strong Bearish"


def get(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def news_paragraphs(page_html, limit=6):
    """Pull the long news paragraphs out of a Trading Economics page."""
    t = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", page_html)
    chunks = re.split(r"(?i)<\s*/?\s*(?:p|div|span|h1|h2|h3|li|td|section|article)[^>]*>", t)
    out, seen = [], set()
    for c in chunks:
        txt = html.unescape(re.sub(r"<[^>]+>", " ", c))
        txt = re.sub(r"\s+", " ", txt).strip()
        if len(txt) < 160 or txt.count(".") < 2 or BOILERPLATE.search(txt):
            continue
        key = txt[:80]
        if key in seen:
            continue
        seen.add(key); out.append(txt[:1200])
        if len(out) >= limit:
            break
    return out


def google_news(query, limit=8):
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": query + " when:1d", "hl": "en-US", "gl": "US", "ceid": "US:en"})
    xml = get(url)
    titles = [html.unescape(re.sub(r"<!\[CDATA\[|\]\]>", "", m)) for m in re.findall(r"<item>.*?<title>(.*?)</title>", xml, re.S)]
    return titles[:limit]


def collect():
    news, status = {}, {}
    for key, (name, urls, q) in SOURCES.items():
        paras, heads = [], []
        for u in urls:
            try:
                paras += news_paragraphs(get(u))
            except Exception as e:
                status.setdefault(key, []).append(f"TE failed: {e}")
            time.sleep(1.5)
        try:
            heads = google_news(q)
        except Exception as e:
            status.setdefault(key, []).append(f"Google News failed: {e}")
        news[key] = {"name": name, "paragraphs": paras, "headlines": heads}
        print(f"[news] {key:6} paragraphs={len(paras)} headlines={len(heads)} {status.get(key, '')}")
        for p_ in paras[:2]:
            print("        >", p_[:110])
    return news, status


PROMPT = """You are a professional FX / macro analyst. Today is {date} (South Africa time).
Below is today's news for each currency and asset. Give each instrument a DAILY fundamental bias score
from -10 (strong bearish) to +10 (strong bullish), for THIS trading day only.

Method (be realistic, not dramatic):
1. First score each currency/asset on its own news. Weight drivers by real market influence:
   - Very high: central-bank rate expectations repricing, hawkish/dovish central-bank speakers, inflation/CPI and jobs data vs forecast.
   - High: growth data (GDP, PMIs) vs forecast, large risk-on/risk-off shifts, bond yields.
   - Medium: risk appetite / geopolitics, commodity moves, momentum already in the price.
   - Low: elections with uncertain outcomes, long-term forecasts, model projections, yearly performance.
   Reduce a score when the move is already priced in or the outcome is still uncertain.
2. Pairs: XXXYYY = strength of XXX minus strength of YYY, scaled realistically (example: NZD +3 and USD +8 -> NZDUSD about -5).
   USDCHF is USD vs CHF. XAUUSD uses gold news plus USD/rate expectations (higher rate bets are bearish for gold).
   US30, US100 and GER30 use their own index news (rate-hike bets weigh on tech/US100 most). BTCUSD uses bitcoin/crypto news and risk mood.
3. If there is little or no news for something, keep it near 0 and say so.

Return ONLY JSON in exactly this shape (integers for score; reason max 15 words, plain English):
{{"currencies": {{"USD": {{"score": 0, "reason": ""}}, "EUR": {{...}}, "GBP": {{...}}, "AUD": {{...}}, "NZD": {{...}}, "CHF": {{...}}}},
 "instruments": {{{inst}}}}}

NEWS:
{news}
"""


def build_prompt(news, date):
    blocks = []
    for key, d in news.items():
        txt = "\n".join("- " + p for p in d["paragraphs"]) or "(no article text)"
        hl = "\n".join("* " + h for h in d["headlines"]) or "(no headlines)"
        blocks.append(f"### {key} — {d['name']}\nArticles:\n{txt}\nHeadlines:\n{hl}")
    inst = ", ".join(f'"{i}": {{"score": 0, "reason": ""}}' for i in INSTRUMENTS)
    return PROMPT.format(date=date, news="\n\n".join(blocks), inst=inst)


def gemini_models(key):
    preferred = [m for m in [os.environ.get("GEMINI_MODEL", "").strip()] if m]
    try:
        data = json.loads(get("https://generativelanguage.googleapis.com/v1beta/models?pageSize=200&key=" + key))
        names = [m["name"].split("/")[-1] for m in data.get("models", [])
                 if "generateContent" in m.get("supportedGenerationMethods", [])]
        flash = [n for n in names if "flash" in n and "image" not in n and "tts" not in n and "live" not in n]
        flash.sort(key=lambda n: (("lite" in n), ("exp" in n or "preview" in n), [-int(x) for x in re.findall(r"\d+", n)[:2]]))
        preferred += flash + [n for n in names if "pro" in n]
    except Exception as e:
        print("[ai] could not list models:", e)
    return preferred or ["gemini-2.5-flash", "gemini-2.0-flash"]


def ask_ai(prompt):
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise SystemExit("GEMINI_API_KEY secret is missing. Add it in GitHub: Settings > Secrets and variables > Actions.")
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}],
                       "generationConfig": {"temperature": 0, "responseMimeType": "application/json"}}).encode()
    last = None
    for model in gemini_models(key)[:6]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
        for attempt in range(2):
            try:
                req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=120) as r:
                    res = json.loads(r.read().decode())
                text = res["candidates"][0]["content"]["parts"][0]["text"]
                text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
                print(f"[ai] scored with {model}")
                return json.loads(text), model
            except Exception as e:
                last = f"{model}: {e}"
                print("[ai] failed", last)
                time.sleep(4)
    raise SystemExit("All Gemini models failed. Last error: " + str(last))


def clamp(v):
    try: return max(-10, min(10, int(round(float(v)))))
    except Exception: return 0


def main():
    now = datetime.datetime.now(SAST)
    date = now.strftime("%Y-%m-%d")
    news, status = collect()
    total = sum(len(d["paragraphs"]) + len(d["headlines"]) for d in news.values())
    if total == 0:
        raise SystemExit("No news could be collected from any source — scores not updated.")
    result, model = ask_ai(build_prompt(news, date))
    scores = {}
    for sym in INSTRUMENTS:
        e = (result.get("instruments") or {}).get(sym)
        if not e or e.get("score") is None:
            continue  # AI gave no score: the site shows "No score yet" instead of a fake 0
        s = clamp(e.get("score"))
        scores[sym] = {"score": s, "label": label_for(s), "reason": str(e.get("reason", ""))[:160]}
    out = {
        "date": date,
        "generated_at": now.strftime("%H:%M SAST"),
        "model": model,
        "scores": scores,
        "currencies": {k: {"score": clamp(v.get("score", 0)), "reason": str(v.get("reason", ""))[:160]}
                       for k, v in (result.get("currencies") or {}).items()},
        "sources": {k: {"paragraphs": len(d["paragraphs"]), "headlines": len(d["headlines"]), "problems": status.get(k, [])}
                    for k, d in news.items()},
    }
    with open(OUT, "w") as f:
        json.dump(out, f, indent=2)
    for sym, v in scores.items():
        print(f"{sym:7} {v['score']:+3d}  {v['label']:20} {v['reason']}")


if __name__ == "__main__":
    main()
