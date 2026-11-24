# Backtest - swing signals (2026-11-24 16:00 SAST)

Train 2017-08-03 to 2022-12-31 | Test 2023-01-01 to 2026-11-24 | costs included | 132 settings tried in total

| Signal | Markets (picked on train) | Status | Train trades / PF | **Test trades / win % / avg R / PF** | Walk-fwd PF | Test avg trade | Just holding | **Edge** | p (adj.) |
|---|---|---|---|---|---|---|---|---|---|
| 52-week-high breakout with volume | ETF, US | **research** | 823 / 1.26 | 584 / 46% / 0.092 / **1.2** | 1.16 | 0.81% | 1.88% | **-1.07%** | 0.2587 |
| Pullback to the 50-day in an uptrend | ETF, US | **research** | 752 / 1.61 | 552 / 43% / -0.053 / **0.9** | 1.01 | 0.43% | 1.72% | **-1.29%** | 1.0 |
| Big gap up that holds (earnings-style drift) | US | **research** | 155 / 1.79 | 163 / 30% / 0.297 / **1.33** | 1.5 | 1.96% | 2.03% | **-0.07%** | 0.62 |
| Big gap down that holds (short) | US, JSE | **research** | 119 / 0.86 | 130 / 26% / -0.406 / **0.53** | 0.5 | -1.19% | -1.03% | **-0.16%** | 1.0 |
| 52-week-low breakdown (short / avoid) | JSE | **research** | 106 / 1.29 | 75 / 36% / -0.27 / **0.49** | 0.81 | -3.19% | -1.33% | **-1.86%** | 1.0 |
| Sector rotation (top 3 sector ETFs each month) | ETF | **research** | 186 / 1.48 | 135 / 55% / 0.113 / **1.32** | None | 0.57% | None% | **-1.0%** | 1.0 |

Gate to go live: test profit factor >= 1.3, >= 50 test trades, adjusted p < 0.05.

- Share results are survivor-biased: free data only has companies that still exist today.
- Gap drift uses any big gap on heavy volume - free data has no earnings dates or analyst forecasts.
- Insider buying and your own FRVP setups are not tested yet (need SEC filings / intraday data).
