"""Quick check of which free data sources answer from GitHub's servers (used while building phase 1)."""
import time, urllib.request
def try_(name, url, hdr):
    t = time.time()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=hdr), timeout=60) as r:
            b = r.read(); print(f"{name}: {r.status} {len(b)}B {time.time()-t:.1f}s | {b[:90]!r}", flush=True)
    except Exception as e:
        print(f"{name}: ERR {e} {time.time()-t:.1f}s", flush=True)
for ua in ["Mozilla/5.0", "curl/8.5.0", "python-urllib"]:
    for tk in ["AAPL", "MSFT", "NPN.JO", "BTC-USD", "ZAR=X"]:
        try_(f"yahoo q1 [{ua}] {tk}", f"https://query1.finance.yahoo.com/v8/finance/chart/{tk}?range=10y&interval=1d", {"User-Agent": ua})
        time.sleep(0.4)
try_("yahoo q2 AAPL", "https://query2.finance.yahoo.com/v8/finance/chart/AAPL?range=10y&interval=1d", {"User-Agent": "Mozilla/5.0"})
try_("stooq aapl.us", "https://stooq.com/q/d/l/?s=aapl.us&i=d", {"User-Agent": "Mozilla/5.0"})
try_("fred csv DGS10", "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10", {"User-Agent": "Mozilla/5.0"})
try_("fred csv DGS10 cosd", "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10&cosd=2015-01-01", {"User-Agent": "Mozilla/5.0"})
try_("fred alt host", "https://fred.stlouisfed.org/series/DGS10/downloaddata/DGS10.csv", {"User-Agent": "Mozilla/5.0"})
try_("treasury yields", "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/2026/all?type=daily_treasury_yield_curve&field_tdr_date_value=2026&page&_format=csv", {"User-Agent": "Mozilla/5.0"})
try_("bls cpi", "https://api.bls.gov/publicAPI/v2/timeseries/data/CUUR0000SA0", {"User-Agent": "Mozilla/5.0"})
try_("ntfy", "https://ntfy.sh/v1/health", {"User-Agent": "Mozilla/5.0"})
