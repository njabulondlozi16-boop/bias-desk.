# Build prompt: my personal AI economist & investor (profit-first) — v2

> **How to use this:** tell Claude: *"Read docs/INVESTOR_DESK_BUILD_PROMPT.md and build the next phase. Stop at the end of the phase, show me the results and wait for my go-ahead."*
> The prompt is written to the AI that builds the system. Text in *italics after "Why:"* explains the reasoning.
> **v2 changes** (Nov 2026) are marked **[v2]**: alerts moved to the front, a real data-hosting plan, a Yahoo backup source, stricter statistics so the backtest can't fool us, rand-based benchmarks, and a realistic plan for data that free sources can't give.

---

## 0. Who I am and what I want

I'm a Computational & Applied Maths student in Johannesburg (South Africa, SAST, UTC+2) with 2 years of trading experience. I already run **Bias Desk**, a GitHub Pages web app (single `index.html`, Python jobs in `scripts/`, GitHub Actions workflows that write JSON files the site reads). Its jobs use only the Python standard library and a free Gemini API key (`GEMINI_API_KEY` secret). **The repo is public**, so nothing private may be committed.

**My goal is to make money**: grow my capital through swing trades (days to weeks) and long-term investments (months to years), in a way that can grow into generational wealth. Everything you build must serve that goal, measured honestly.

Build me a **personal AI economist and investment scout** inside Bias Desk that, every day:
1. reads real economic, market, company and news data from free sources,
2. works out what the economy is doing and which areas of the market should benefit,
3. scans shares, ETFs, JSE shares, commodities and crypto for opportunities,
4. tells me **where to go and do my own technical analysis, and why**, with clear key levels,
5. **keeps score of its own ideas** and automatically trusts what has worked and drops what hasn't,
6. **[v2] keeps me in touch with phone alerts**, so I don't have to keep checking the site.

**Budget: free only.** No paid data, no paid APIs. The free Gemini tier is allowed.

---

## 1. The money rules: read these before writing any code

1. **Only show ideas that have a measured edge.** Every signal type must be backtested over several years *before* it reaches my screen, including costs, and must show its historical win rate, average gain and number of past cases.
   *Why: most trading ideas that "look good" lose money once costs and randomness are included.*
2. **Out-of-sample or it doesn't count.** Pick settings on older data (e.g. 2015–2022) and judge them only on newer data (2023–now). Report both. Prefer walk-forward testing (re-fit every year, test on the next year).
   *Why: my volume-profile bot looked fine on some settings but lost money across 75 settings in the training years. Tuning on the data you judge on just fits noise.*
3. **[v2] Count how many things we tried.** Log every signal variant and setting ever tested. When many variants were tried, raise the bar: report a bootstrap p-value (shuffle the trade dates 1,000 times) and the *deflated* Sharpe ratio, and only call a signal "proven" if it still passes after that.
   *Why: test 50 random ideas and 2–3 will look great by luck. The more we try, the stricter the proof must be.*
4. **Costs are always included**: spreads, commissions and slippage at realistic levels for a South African retail trader (EasyEquities / Interactive Brokers style for shares, broker spread for CFDs).
5. **Risk first, return second.** Every idea comes with a stop level, a position size from my risk budget (default 1% of account per swing trade, in ZAR), and a check against what I already hold.
6. **The AI explains; the numbers decide.** Gemini may only summarise and explain facts the code computed. It must never invent prices, numbers, events or recommendations. If AI output contradicts the data, the data wins.
7. **Track everything, prune ruthlessly.** Log every idea when shown, score it after 5, 20, 60 and 250 trading days against the S&P 500 (and the JSE Top 40 for JSE ideas), and automatically down-weight signal types whose live results fall below their backtest.
8. **[v2] Think in rand.** I earn and spend rand. Show every return two ways: in the asset's own currency and in ZAR (using USD/ZAR on the same days), and compare US ideas with the S&P 500 *in rand* too.
   *Why: a US share up 10% while the rand strengthens 10% made me nothing.*
9. **Explain like I'm smart but busy.** Plain English, short sentences, numbers with units, times in SAST.

---

## 2. Data layer: free sources only

All jobs must survive a source failing: log it, keep yesterday's data, never publish a broken page, and **send me an alert** (section 10).

**[v2] Where the data lives.** 10 years of daily prices for ~150 instruments is too big for the Pages branch. Keep the raw cache on a separate branch **`invest-data`** (gzip JSON per ticker) and publish only small summary files (`investor*.json`, under ~1 MB each) to `main`. Workflows check out both branches.

| Data | Free source | Used for |
|---|---|---|
| Daily prices (shares, ETFs, JSE `.JO`, crypto, futures) | Yahoo Finance chart API `query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=10y&interval=1d` — **[v2] backup: Stooq CSV** `stooq.com/q/d/l/?s={ticker}&i=d` | trend, momentum, levels, backtests |
| US economy | FRED CSV `fred.stlouisfed.org/graph/fredgraph.csv?id=SERIES`: CPIAUCSL, UNRATE, ICSA, DFF, DGS10, DGS2, T10Y2Y, BAMLH0A0HYM2, VIXCLS, DTWEXBGS, DCOILWTICO, INDPRO, UMCSENT | economic regime |
| SA economy | SARB / Stats SA releases, or the Trading Economics pages Bias Desk already reads (repo rate, CPI, rand) + USD/ZAR daily (Yahoo `ZAR=X`) | JSE and rand context |
| Company accounts (US) | SEC EDGAR `data.sec.gov/api/xbrl/companyfacts/CIK##########.json` + `sec.gov/files/company_tickers.json` (User-Agent from secret `SEC_UA`) | quality, growth, value |
| Insider buying (US) | SEC EDGAR Form 4 filings | insider cluster buying |
| Earnings dates and surprises | SEC 8-K item 2.02 + the price reaction on the day | post-earnings drift |
| Big-money positioning | CFTC Commitments of Traders weekly files | gold, oil, currencies, indices |
| News | Google News RSS + company press releases | catalysts and news tone |
| My own data | Bias Desk `scores.json` / `scores_history.json` | bias for forex, gold, indices, BTC |

**[v2] Be polite and robust:** one request per second per host, retries with back-off, a cache so nothing is downloaded twice in a day, and a check that each file looks right (enough rows, no zero prices, no impossible jumps) before it replaces yesterday's copy.

**Universe:** start with about 150 instruments in `config/universe.json` (S&P 100 shares, 11 US sector ETFs, SPY/QQQ/IWM, GLD/SLV/USO/TLT, JSE Top 40, BTC/ETH/SOL). I can add tickers there.

**[v2] What free data can't give — say so, don't fake it:**
- **Delisted shares** (survivorship bias): free sources only have today's survivors. Mark every share backtest "survivor-biased", and prefer signals that also work on ETFs (which don't have this problem).
- **Earnings expectations** (consensus estimates) aren't free. Use the price gap on the results day as the "surprise" instead, and say so.
- **JSE company accounts** aren't on EDGAR. JSE long-term ideas use price, trend and sector only until a free source is found.

*Why: free data is enough for daily and weekly decisions. Paid data mainly helps with intraday speed, which isn't the game here.*

---

## 3. The economist: the economic regime model

Each day, classify the economy into one of: **Expansion, Overheating (late cycle), Slowdown, Stagflation, Recovery (early cycle)**, using growth, inflation, policy, stress and cross-asset signals (unemployment vs 12-month low, jobless claims, industrial production, sentiment; CPI yearly rate and 3-month direction; Fed rate and 10y yield changes; yield curve, junk-bond spread, VIX; dollar, oil, S&P 500 vs its 200-day average).

**[v2] Use data as it was known at the time:** economic numbers get revised. When backtesting, use each number only from its release date (FRED's ALFRED "vintage" data where available, otherwise lag each series by its normal publication delay, e.g. CPI ~2 weeks after the month ends).
*Why: using revised numbers on dates they weren't known yet makes the backtest look smarter than it could ever have been.*

Output: the regime name, a confidence level, each signal with a green/red/grey reading and a one-line plain-English meaning, and the sectors and assets that historically did best and worst in this regime. **Then prove it:** backtest regime → sector returns since 2000 (3 months after each reading). Keep only tilts that held up.

---

## 4. The scanners

Each scanner is a signal type, is backtested (section 6), and shows its own historical statistics on every idea.

### 4a. Swing scanners (days to weeks)
1. **52-week-high breakout with volume** (uptrend, within 3% of the high, volume ≥ 1.2× normal). Levels: trigger, support (20-day average), stop (recent swing low).
2. **Pullback in an uptrend** (to the 50-day average, RSI < 50, relative strength still positive). Levels: buy zone, support (200-day), target (recent high).
3. **Post-earnings drift** (gap ≥ 4% on high volume on results day, holds 2 days) → 20–60 day idea; mirror for misses.
4. **Insider cluster buying** (≥ 2 directors buying within 30 days, meaningful amounts).
5. **Sector rotation** (strongest 2–3 sectors that the regime also favours; best shares inside them).
6. **Avoid / short list** (breakdowns to 52-week lows in weak sectors).
7. **[v2] My own setups as a scanner:** for forex, gold, indices and BTC, combine the daily bias score with my market-structure and volume-profile rules (4H structure, 1H FRVP POC/VAH, FVG overlap) and flag pairs where today's bias and structure agree. Same backtest gate as everything else.
   *Why: these are the markets I actually trade every day.*

### 4b. Long-term scanner (months to years)
Quality, growth, value (vs sector), a **trend gate** (buy-ready only above the 200-day average), a macro-fit bonus, a ranked list and a **model portfolio** of 10–15 names (no sector over 30%). **[v2] Re-rank weekly, not daily** — long-term ideas shouldn't change every day.

### 4c. Score each idea
A 0–100 score with weights **learned on training years only** (logistic regression or rank-weighted average). Show what makes up the score.

---

## 5. News and the AI layer

- Top ~30 ideas: last 3 days of headlines; tone from a word list first; Gemini only on the top ideas (free quota).
- Gemini writes: a 5–6 sentence economy summary, up to 3 risks for the week, and 1–2 sentences per idea on why now and **what would confirm or cancel it**.
- Give Gemini only computed facts + headlines; ask for JSON; fall back to plain templates. Never let it add tickers, prices or targets.

---

## 6. Backtesting engine: the profit gate

`scripts/inv_backtest.py`:
- 10+ years of daily data; survivor-bias warning on share results.
- No look-ahead: signals at that day's close, entry at the next day's open. **[v2] Add a test that would fail if look-ahead crept in** (shift the data one day and check results get worse, not better).
- Costs: shares 0.15%/side + slippage; ETFs 0.1%; JSE 0.3%; crypto 0.2%.
- Exits: stop, target or time exit (20 days swing; 12 months + 200-day trend exit long-term).
- Report per signal type: trades, win rate, average R, profit factor, max drawdown, CAGR, Sharpe, **train vs test**, walk-forward, **[v2] bootstrap p-value and deflated Sharpe, results in USD and in ZAR, and how many variants were tried.**
- **Gate:** goes live only if the *test-period* profit factor ≥ 1.3 with ≥ 50 trades **and [v2] the bootstrap p-value < 0.05**. Otherwise it's listed under "signals in research".
- Save to `investor_signal_stats.json`.

---

## 7. Risk and portfolio layer

- My settings (saved in the browser): account size in ZAR, risk per swing trade (default 1%), max open trades (5), max per sector (2), USD/ZAR (fetched).
- Position size = (account × risk%) ÷ (entry − stop), in shares and in rand. **[v2] Round down to whole shares, and warn when the minimum lot is bigger than my risk budget allows.**
- Correlation check: warn if > 0.7 correlated (60-day returns) with something I hold.
- Paper portfolio linked to my Bias Desk journal.
- SA context: label JSE / TFSA-eligible vs offshore. Remind me to check current TFSA and offshore allowance limits; don't hard-code tax numbers.

---

## 8. Track record and self-improvement

- `investor_history.json`: every idea with date, price, signal, score, side and levels — **[v2] written once and never edited**, so the record can't be quietly improved later.
- Score after 5/20/60/250 trading days vs benchmark; stop or target hit first.
- Page: hit rate, average and excess return by list, signal type, market and score bucket.
- Auto-pruning: live profit factor < 1.0 (≥ 30 ideas) or > 40% below backtest → "under review", lower weight, tell me.
- Monthly report card.

---

## 9. The Bias Desk page (`#/invest`)

Header (date/time SAST, markets scanned, data freshness, refresh) → Economy card → Today's best 3 *proven* ideas → tabs (⚡ Swing | 🌱 Long-term | 🧺 Model portfolio | 📋 Paper portfolio) → filters → idea cards (score ring, reasons, AI note, levels, company numbers, score breakdown, headlines, signal history, position size, "Do my TA on TradingView", paper-buy) → sector strength, track record, headlines → footer "Ideas to research, not financial advice."

Match Bias Desk's style: subtle, refined, muted colours that follow the chosen chart theme; light and dark; mobile-friendly; fast.

---

## 10. **[v2] Alerts: keep me in touch (built first)**

Phone push through **ntfy** (free, no account): the jobs post to `https://ntfy.sh/<my private topic>`; I subscribe to that topic in the free ntfy app (Android/iPhone). The topic name is stored only in the repo secret **`NTFY_TOPIC`** (the repo is public). Optional second channel: a Telegram bot (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`).

| Alert | When | Priority |
|---|---|---|
| ☀️ **Morning brief** | after the daily bias scores are published (~05:15 SAST): strongest biases, today's high-impact news | normal |
| ⚠️ **Scores missing** | no scores by 06:30 SAST (and the job was restarted) | high |
| 🔥 **New proven idea** | a new top idea that passed the gate | normal |
| 🎯 **Level reached** | a watchlist idea crosses its trigger / stop / target (checked with daily data; intraday via the site's browser alerts) | high |
| 🧭 **Regime change** | the economy model changes regime | normal |
| 🛑 **Signal switched off** | auto-pruning puts a signal "under review" | normal |
| 🧯 **Data problem** | a source failed or data went stale | low |
| 📊 **Weekly / monthly report card** | Sunday evening / 1st of the month | low |

Rules: at most ~6 alerts a day (bundle the rest into the next brief), quiet hours 22:00–05:00 SAST except high priority, every alert links to the right Bias Desk page.

---

## 11. Engineering requirements

- Python standard library in GitHub Actions (numpy/pandas allowed for the backtester via `requirements.txt`).
- Workflows: `investor-data.yml` (daily after the US close, backup cron times, skip if done, `workflow_dispatch`), `investor.yml` (daily ideas), `inv_backtest.yml` (weekly, Saturday), all in the `repo-writes` concurrency group.
- JSON with `allow_nan=False`; history files pruned; never commit secrets.
- Tests: mock-data run of every job (no network), JSON schema checks, headless-browser render with zero console errors.
- Work on a branch and open a pull request per phase. Never push to `main` directly.

---

## 12. Build order: each phase must pass its gate before the next

| Phase | Build | Gate |
|---|---|---|
| 1 | **Alerts channel** + data layer + cache (`invest-data` branch) + universe config | A test alert arrives on my phone; all sources download; data-quality report |
| 2 | Backtesting engine + swing scanners | Per-signal train/test table with costs, p-values; which pass the gate |
| 3 | Regime model + regime → sector backtest | Sector returns by regime since 2000 |
| 4 | Long-term scanner + model portfolio backtest | Model portfolio vs S&P 500 (USD and ZAR) and JSE Top 40 since 2015 |
| 5 | Daily job + Investor page (only proven signals live) + morning-brief alert | Screenshot with real data |
| 6 | Risk layer | Worked example with my account size |
| 7 | Track record + auto-pruning + report cards | History scoring checked on past data |
| 8 | Remaining alerts (levels, regime, pruning) | Each alert type received once |

At every gate, tell me plainly: **does this make money after costs, on data it hasn't seen? How sure are we?** If not, say so and propose what to change.

---

## 13. What success looks like

- Within 3 months of going live, the track record shows **positive excess return vs the S&P 500/JSE after costs (in rand)** on ≥ 50 swing and ≥ 20 long-term ideas — or the system has clearly switched off what doesn't work.
- 15–20 minutes a day: read the morning alert and the economy card, check the top 3 on TradingView, decide.
- Every number can be traced to a source or a calculation.

## 14. Honesty requirements
- No guaranteed returns, no hype. Losing results are shown as clearly as winning ones.
- Everything labelled "ideas to research, not financial advice".
- Stale or failed data is shown on the page and alerted.
- If I ask for something that would likely lose money (removing stops, doubling risk after losses), warn me clearly first.
