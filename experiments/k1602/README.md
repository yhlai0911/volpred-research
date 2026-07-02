# K1602 — Tax-loss-harvesting crowding and the year-end single-stock RV reversal

## Motivation

The classic **tax-loss-selling hypothesis** (Roll 1983 JPM; Ritter 1988 JF; Bhabra,
Dhillon & Ramirez 1999 FAJ; Fountas & Segredakis 2002 AFE) argues that stocks with
large year-to-date losses face
concentrated selling pressure in late December (investors realise losses for tax
purposes), depressing prices into year end, followed by a **January reversal** as the
selling pressure lifts. This is one of the leading explanations for the "January
effect."

**Modern angle / differentiation.** The 2015+ rise of **direct indexing** and
scaled algorithmic **tax-loss harvesting (TLH)** (Frazzini-Lamont style flows,
retail direct-indexing SMAs) mechanically concentrates loss realisation into the
same names at the same time. If TLH is now *crowded*, the year-end selling-pressure /
January-reversal signature in high-loss single stocks should be **stronger post-2015**
than pre-2015.

**Explicit differentiation from prior K676** ("Tax Optimization — tax-loss harvesting
useless"): K676 asked whether TLH improves a single *investor's after-tax return*
(a personal portfolio-optimisation question) and found it not worth it. K1602 asks a
*market-microstructure / cross-sectional anomaly* question: does crowded TLH selling
create a predictable year-end RV / return pattern in the loss stocks themselves.
Different unit of analysis, different literature.

## Literature checked

- Roll (1983), "Vas Ist Das?" DOI: `10.3905/jpm.1983.18`.
- Ritter (1988), "The Buying and Selling Behavior of Individual Investors at the
  Turn of the Year." DOI: `10.1111/j.1540-6261.1988.tb04601.x`.
- Bhabra, Dhillon & Ramirez (1999), "A November Effect? Revisiting the
  Tax-Loss-Selling Hypothesis." DOI: `10.2307/3666300`.
- Fountas & Segredakis (2002), "Emerging stock markets return seasonalities: the
  January effect and the tax-loss selling hypothesis." DOI:
  `10.1080/09603100010000839`.
- Frazzini & Lamont (2008), "Dumb money: Mutual fund flows and the cross-section of
  stock returns." DOI: `10.1016/j.jfineco.2007.07.001`. Used only as background for
  flow-induced mispricing; K1602 does not observe direct-indexing/TLH flows directly.

**Prior from this codebase (research honesty):** calendar / seasonality effects have
repeatedly come back NULL or not-actionable here (K35 VT seasonality null; K215
seasonality hurts; K666 VIX seasonality NS; K736 "Sell in May" R²=0.0000; N153 no
monthly VT seasonality). The prior on finding a robust, actionable effect is LOW. A
NULL is an expected and fully acceptable outcome; the goal is an honest, well-powered
test.

## Hypotheses

- **H1 (selling pressure):** In late December, high-YTD-loss stocks earn lower returns
  than low-loss stocks (loser−winner Dec return < 0).
- **H2 (reversal):** In January, high-YTD-loss stocks earn *higher* returns than
  low-loss stocks (loser−winner Jan return > 0) — the tax-loss-selling reversal.
- **H3 (RV):** High-loss stocks show elevated late-December realised volatility
  (loser−winner Dec RV > 0).
- **H4 (crowding / modern amplification):** The reversal (H2) is stronger in the
  direct-indexing era (2015+) than pre-2015.

## Design

- **Universe:** fixed list of ~90 liquid US single stocks across sectors, deliberately
  including cyclical / high-beta names (airlines, cruises, autos, miners) that
  generate loss candidates. Defined in `TICKERS`.
- **Data:** yfinance daily adjusted close (`auto_adjust=True`), per-ticker CSV cache in
  `data/`. Market control = SPY.
- **Classification window (lag-safe signal):** for each year *Y*, YTD return from the
  first trading day of *Y* through **Nov 30 (Y)**. Loss group = bottom tercile of YTD
  return; winner group = top tercile. The signal uses only data available by Nov 30.
- **Outcome windows (strictly after the signal → no lookahead):**
  - Dec return / Dec RV over Dec 1–31 (Y); also Dec 15–31 (concentrated TLH window).
  - January reversal return / RV over Jan 1–31 (Y+1).
- **Cross-sectional differential per year:** loser-group mean minus winner-group mean of
  each outcome. Differencing loser vs winner within the same December removes the
  market-wide seasonal component (market-neutral by construction).
- **Inference (year is the cluster unit — K1355 lesson):** stack the per-year
  loser−winner differentials into a **year series** and test mean = 0. Do NOT pool
  stock-year observations as iid (same-year names share the December market shock).
  Primary test = t-test on the year series; seeded year-level bootstrap CI.
- **Subsamples:** pre-2015 vs 2015+ (H4).
- **Multiplicity:** 4 primary metrics (Dec ret, Jan ret, Dec RV, Dec15 ret). Verdict
  PASS requires Harvey |t| ≥ 3 on the primary reversal metric (H2 Jan return); weaker
  significance → NULL / suggestive.

## Anti-lookahead / reproducibility

- Signal (loss classification) uses data ≤ Nov 30; every outcome window starts Dec 1 or
  later. Temporal separation is the lag guarantee (documented in code, boundaries
  explicit).
- Bootstrap seeded (`SEED = 42`); no other stochastic step.
- yfinance batch fetch + bootstrap → run via `compute_queue` (heavy-compute policy).

## Results — 2026-07-02 run

- **Data/source:** yfinance adjusted close (`auto_adjust=True`), 2004-2025
  classification years, 82 loaded stocks out of 83 configured tickers. `X` failed
  because yfinance returned empty history; the market control `SPY` loaded.
- **Primary verdict:** `NULL`. The January loser-minus-winner reversal is positive in
  point estimate but economically small and statistically weak: mean `+0.570%`,
  year-clustered `t=0.37`, Student-t `p=0.715`, seeded year-bootstrap 95% CI
  `[-2.31%, +3.63%]`.
- **H1 selling pressure:** December loser-minus-winner return mean `-0.619%`,
  `t=-0.67`, 95% CI `[-2.39%, +1.15%]` → directionally consistent but not
  significant.
- **H3 realised volatility:** December loser-minus-winner RV mean `+3.00pp`
  annualised, `t=1.29`, 95% CI `[-1.10pp, +7.79pp]` → suggestive direction only.
- **H4 direct-indexing-era amplification:** January reversal is not stronger after
  2015. Pre-2015 mean is `+1.91%`; post-2015 mean is `-0.77%`.
- **Codex source review:** `CONDITIONAL_PASS` for a screening experiment. The failed
  ticker path was fixed so missing tickers no longer crash the run; stdout and JSON
  ticker counts now share the same stock-only denominator. Lookahead check passes
  because classification ends on Nov 30 and all return/RV outcomes start strictly
  after the signal window. Inference is year-clustered, not pooled stock-year iid.

## Known caveats

- **Survivorship bias:** yfinance carries only currently-listed tickers → delisted
  losers are excluded. This biases the test **against** finding a tax-loss effect
  (the worst losers, most likely to be dumped, are missing), so a positive finding
  would be conservative; a NULL is partly attributable to this.
- Fixed universe (not point-in-time index membership); adjusted close.
- US-only; ~20 completed years → year-level N ≈ 20 (moderate power for a year-clustered
  test — reported honestly with the January-reversal CI).

## Files

- `k1602.py` — experiment script (fetch → classify → event windows → year-clustered
  tests → bootstrap → figures → `k1602_results.json`).
- `data/` — per-ticker yfinance CSV cache.
- `figures/` — result charts.
- `k1602_results.json` — canonical results artifact.

## Reviewer / provenance

- Initial `compute_k1602` queue run failed on a missing `X` column after yfinance
  returned empty history. Codex failover fixed the failed-ticker path, reran the
  experiment locally, visually checked both figures, and reviewed the timing /
  inference path before knowledge promotion.
