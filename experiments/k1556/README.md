# K1556: US Macro News Global Co-Jump Beta

## Motivation

REStud 2026 "The U.S., Economic News, and the Global Financial Cycle" argues that
scheduled U.S. macroeconomic news releases move foreign equity indexes, the VIX,
and commodities nearly instantaneously. K1556 tests whether a free-data ETF proxy
can reproduce that mechanism at daily frequency:

- U.S. releases: FRED release-calendar pages for CPI, Employment Situation, and
  GDP.
- Global ETFs: EFA, EEM, EWJ, EWG, EWT, EWY, EWZ, INDA.
- U.S. shock proxy: SPY daily return z-score and a FRED actual-minus-trailing
  nowcast proxy. No paid consensus-surprise feed is used.

This is intentionally narrower than the paper's intraday 27-country design. It
is a daily ETF proxy diagnostic, not a replication of high-frequency causal
identification.

## Literature and Source Check

- Boehm and Kroner, "The U.S., Economic News, and the Global Financial Cycle",
  Review of Economic Studies 2026 / NBER WP 30994. The paper reports large
  intraday responses of 27 foreign stock indexes, VIX, and commodity prices to
  U.S. macro news. Sources: https://academic.oup.com/restud/article/93/1/215/8105821
  and https://www.nber.org/papers/w30994
- Andersen, Bollerslev, Diebold, and Vega, "Micro Effects of Macro
  Announcements: Real-Time Price Discovery in Foreign Exchange", AER 2003.
  Source: https://www.aeaweb.org/articles?id=10.1257/000282803321455151
- Andersen, Bollerslev, Diebold, and Vega, "Real-Time Price Discovery in Global
  Stock, Bond and Foreign Exchange Markets", Journal of International Economics
  2007. Source: https://ideas.repec.org/a/eee/inecon/v73y2007i2p251-277.html
- Lahaye, Laurent, and Neely, "Jumps, Cojumps and Macro Announcements" motivates
  linking scheduled macro news to jumps/cojumps. Source:
  https://public.econ.duke.edu/~get/browse/courses/201/spr09/Applications-Real-World/LLH-StLouisFed-2007-032.pdf
- Release calendars: FRED release-calendar pages for CPI (`rid=10`),
  Employment Situation (`rid=50`), and GDP (`rid=53`); BLS schedule pages and
  BEA release schedule are used as official context. Sources:
  https://fred.stlouisfed.org/releases/calendar,
  https://www.bls.gov/schedule/news_release/empsit.htm,
  https://www.bls.gov/cpi/, and https://www.bea.gov/news/schedule

## Data

- Market data: yfinance adjusted daily close, 2014-01-01 to 2026-06-28, for
  SPY, ^VIX, EFA, EEM, EWJ, EWG, EWT, EWY, EWZ, INDA. The 2014-2024 segment is
  used only for rolling baselines.
- Macro levels: local FRED CSVs under `storage/macro/`:
  `PAYEMS`, `UNRATE`, `CPIAUCSL`, and `GDPC1`.
- Release calendar: FRED release-calendar scrape cached at
  `experiments/k1556/data/fred_release_calendar.csv`. The public FRED calendar
  page used here returns 2025-2026 schedules, so the formal event/control
  analysis is restricted to 2025-01-01 onward.
- Effective daily sample depends on ETF availability, release-calendar coverage,
  and rolling baselines.

## Method

The experiment separates contemporaneous event-study evidence from predictive
or persistence evidence.

1. **Event-day cojump diagnostics**
   - Map CPI / Employment / GDP release dates to the next available trading day.
   - Compute country ETF return z-scores using only prior 252 trading days.
   - Define cojump count as the number of country ETFs with `|ret_z| > 2`.
   - Compare release days with non-release, non-neighbor control days using
     Welch tests, Mann-Whitney tests, and seed-42 bootstrap confidence intervals.

2. **Country cojump beta**
   - For each ETF, regress country return z-score on SPY return z-score,
     `macro_release_day`, and `SPY_z × macro_release_day`.
   - HAC(5) standard errors test whether macro release days amplify the country
     beta relative to ordinary days.

3. **Lagged persistence test**
   - Required no-lookahead guard:
     `macro_release_signal = macro_release_day.shift(1)`.
   - A second lagged signal uses the absolute FRED actual-minus-trailing-nowcast
     proxy: `macro_abs_surprise_signal = macro_abs_surprise_proxy.shift(1)`.
   - Test whether the post-release day has higher next-5-day average country ETF
     RV z-score than controls.

## Lookahead Policy

- Event-day results are contemporaneous response diagnostics, not trading
  signals.
- All predictive/persistence signals are explicitly lagged with `.shift(1)`.
- Rolling baselines for return, VIX, and RV z-scores use `.shift(1)` so the
  current day is not included in its own normalization.
- The FRED actual-minus-trailing-nowcast proxy is not paid consensus data and is
  not a real-time vintage surprise. It is used only as a free proxy and is
  lagged before persistence tests.

## Success Criteria

Strong evidence would require:

- Event-day cojump or average country absolute-return z-score difference with
  Harvey-style `|t| >= 3`.
- VIX jump difference with `|t| >= 3`.
- Macro-day SPY beta amplification positive for most country ETFs, with at least
  two interaction `t >= 3`.
- Lagged t+5 RV persistence also positive with `t >= 3`.

Conditional evidence is allowed only if the event-day mechanism is strong but
the lagged persistence or beta criteria fail. Null results are reported as null.

## Result Summary

Run `uv run python experiments/k1556/k1556.py` to reproduce. The current results
are in `k1556_results.json`.

Current run verdict: `NULL_PROXY`. Release-day cojump, country ETF
absolute-return z-scores, and VIX jump are directionally higher than controls,
but no event-day statistic, beta interaction, or lagged t+5 RV persistence test
clears the Harvey-style `|t| >= 3` gate. This should not be published as
evidence that daily ETF data reproduces the REStud intraday global financial
cycle mechanism.

Key numbers from `k1556_results.json`:

- Effective analysis rows: 368 trading days from 2025-01-02 to 2026-06-22.
- Mapped release rows within price data: 51; distinct macro release days: 50.
- Release-day cojump count: 0.72 vs 0.55 control, diff +0.17, Welch t=0.68.
- Release-day average country `|ret_z|`: 0.96 vs 0.77 control, diff +0.18,
  Welch t=1.54.
- VIX jump z: 0.46 vs 0.31 control, diff +0.16, Welch t=1.05.
- Lagged post-release next-5d RV z: -0.25 vs 0.10 control, diff -0.35,
  Welch t=-2.06; bootstrap CI is negative but fails the `|t| >= 3` gate and is
  opposite the persistence hypothesis.
- Positive beta interactions: 5/8 ETFs. Strongest beta amplification is EFA
  interaction +0.257, t=2.06; below gate.
