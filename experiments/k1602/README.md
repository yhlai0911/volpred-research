# K1602 — Tax-loss-harvesting crowding and the year-end single-stock RV reversal

## Motivation

The classic **tax-loss-selling hypothesis** (Roll 1983 JPM; Ritter 1988 JF; D'Mello,
Ferris & Hwang 2003) argues that stocks with large year-to-date losses face
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

- Compute enqueued via `scripts/compute_queue.py`; interpretation + Codex review at the
  follow-up step before any knowledge.json write. Verdict written only after review.
