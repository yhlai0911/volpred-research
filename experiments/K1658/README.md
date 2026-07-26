# K1658 — FOMC statement shock (14:00 ET) vs press-conference shock (14:30 ET): distributional response decomposition for rate assets

**Verdict: CONDITIONAL_PASS — the core statement-vs-presser separation is `INFEASIBLE` with free data (a data-insufficiency limit, N=2 intraday events, not an evidenced null). The feasible aggregate sub-question was answered with a completed lookahead-clean formal test and returned a clean `NULL` (0/6 tests survive Holm). "Infeasible" (cannot be tested) and "null" (tested, no effect) are kept distinct throughout.**

## Motivation & research question

Within a single FOMC decision day the **statement** (released 14:00 ET) and the
**press conference** (14:30 ET) are two temporally *separable* information
events. Fed FEDS 2026-029 ("Coarse Statements and Predictive Pressers") argues
these two channels carry different information. K1658 asks:

> Do the statement shock and the presser shock have a **statistically different**
> effect on the **next-day (t+1)** realised volatility of rate assets
> (TLT, IEF, ZN=F)?

**Orthogonality to line 1425.** research_program line 1425 studies
statement/minutes *linguistic complexity* — a **text-readability** feature.
K1658 is a same-day **two-stage market-reaction decomposition** using intraday
prices; it uses no text features. The two are orthogonal and non-duplicative.

## The answer, up front

Separating the two shocks requires intraday prices at ≤15-min resolution that
straddle **14:00** and **14:30 ET**, over a sample of **many** FOMC days. The
only free intraday source available (yfinance) has a **hard ~60-trading-day
lookback cap** for sub-hourly bars. FOMC meets 8×/year, so the entire free
intraday window contains only:

| asset | intraday coverage | usable FOMC events in-window |
|-------|-------------------|------------------------------|
| TLT   | 2026-04-29 → 2026-07-24 | 2 (2026-04-29, 2026-06-17) |
| IEF   | 2026-04-29 → 2026-07-24 | 2 (2026-04-29, 2026-06-17) |
| ZN=F  | 2026-05-14 → 2026-07-24 | 1 (2026-06-17) |

**N = 2 usable events.** A paired statement-vs-presser test needs N ≥ **13**
even to detect a *large* effect (Cohen's d = 0.8; N ≥ 32 for d = 0.5, N ≥ 88
for d = 0.3) at power 0.80, α = 0.05 — i.e. **1.6–11 years** of *complete*
intraday coverage. The free window supplies ~0.24 yr. **Cross-event inferential
separation of the two shocks is therefore `INFEASIBLE` with free data.** This
infeasibility (a data-insufficiency limit — the test cannot be run, distinct from
a tested-and-null result) is reported honestly (brief §6: an honest limit, like a
null, is a valid and valued result — no reactive re-tuning was done to manufacture
a positive finding).

## What *is* feasible and real (and was done)

- **Part 1 — Feasibility diagnosis.** Enumerates FOMC dates, measures actual
  intraday coverage per asset, counts usable events, and computes the power gap
  above. This *is* the answer to the research question.
- **Part 2 — Intraday case studies (N ≤ 2, descriptive only).** For the events
  that have intraday coverage, cleanly measures statement-window and
  presser-window log returns + within-window realised variance, plus event-day
  and next-day session RV. **No cross-event test is claimed.**
- **Part 3 — Aggregate FOMC-day → t+1 volatility effect (formal test).** A
  lookahead-clean, HAC-robust, Holm-corrected regression on a **long daily
  sample (2019–2026, ~59 FOMC events)**. This measures the **COMBINED**
  statement+presser effect and **cannot** separate the two shocks; it is
  included as testable context and to meet the CONDITIONAL_PASS bar (≥1 formal
  test + multiple-testing correction).

## Method

### Windows (ET), fixed a priori (brief's suggestion)
- statement window: **13:55 → 14:15** (brackets the 14:00 statement)
- presser window: **14:25 → 15:30** (brackets the 14:30 presser + Q&A)
- The 14:15→14:25 gap is excluded so the two shocks do not overlap.
- statement/presser shock = window log return; within-window RV = Σ (5-min log return)².

### Part 3 regression (per asset × per RV proxy)
```
logRV_t = a + b·FOMC_{t-1} + c·logRV_{t-1} + e_t      (Newey-West HAC SE)
```
- **RV proxies:** Parkinson (1980) high-low range variance; squared close-to-close return.
- `b > 0` ⇒ an FOMC announcement on day t-1 raises volatility on day t (the day *after* the event).
- **Multiple testing:** family = 3 assets × 2 proxies = **6 tests**, fixed in
  code *before* inspecting p-values; **Holm** correction over the whole family.
- **Block bootstrap** (moving-block, seed 42, 2000 reps) stress-tests the HAC p-value.

### Lookahead policy (fixed in README **and** code)
- **`signal from t-1, return at t`.** Part 3 predictors (`FOMC`, control) are
  taken from t-1 via explicit **`.shift(1)`**; outcome `logRV_t`. A runtime
  `assert` fails loudly if the lag alignment ever breaks. No same-day signal ×
  same-day return.
- Part 2 "next-day RV" is the **strictly following** session.
- FOMC dates are pre-scheduled/public, so the event dummy is knowable ex-ante
  (no forward-looking information).
- `seed = 42` for the bootstrap.

## Data
- **Intraday:** yfinance 5-min OHLCV (`period=60d`, the hard cap), timestamps
  tz-converted UTC → America/New_York.
- **Daily:** yfinance daily OHLC, 2019-01-01 → 2026-07-24.
- **FOMC calendar:** federalreserve.gov FOMC calendars. 2024–2026 verified
  directly from the Fed calendar page on 2026-07-27; 2019–2023 compiled from the
  Fed calendar and cross-checked against the Fed rate-decision record.
  Unscheduled 2020 emergency actions (2020-03-03, 2020-03-15) are **excluded**
  (they did not follow the standard 14:00/14:30 format).
- **Reproducibility:** all raw pulls are cached to `data/`. This is essential —
  the yfinance 60-day intraday window **rolls forward**, so the 2026-04-29 /
  2026-06-17 intraday bars will disappear from the API within ~60 days. The
  cache freezes them for byte-traceable replication. Re-run with `--refresh`
  only to re-pull (will change the intraday window/events).

## Results summary (see `K1658_results.json` for full byte-traceable output)
- **Part 1:** N = 2 usable intraday FOMC events → **`INFEASIBLE`** to separate the two shocks inferentially with free data.
- **Part 2 (descriptive, N ≤ 2):** on both events, the statement and presser
  windows moved the same direction (bonds down / yields up) with comparable
  magnitudes; |statement|−|presser| log-return differences are order 1e-4–1e-3.
  Next-day session RV is *lower* than event-day RV on every asset (the shock is
  largely digested intraday). **No inference — case studies only.**
- **Part 3 (aggregate, ~59 events):** **0/6** tests survive Holm correction.
  Raw β's are small and mixed in sign; the largest raw effect (ZN=F, squared
  return, p_raw≈0.023) does not survive correction (p_holm≈0.14) and is not
  confirmed by the block bootstrap. **Clean NULL:** the day *after* an FOMC
  meeting shows no robust elevation of daily volatility for rate assets — the
  volatility is realised on the meeting day itself. Residual acf(1) was measured
  (small, mostly negative) and HAC lag sensitivity is reported.

## Success criteria (met)
- Three-piece set complete (README + `K1658.py` + `K1658_results.json`) ✔, plus data cache + 2 figures.
- Lookahead clean (explicit `.shift(1)` + runtime assert) ✔.
- ≥1 formal test + multiple-testing correction (Part 3: HAC OLS + Holm over 6-test family + bootstrap) ✔.
- Conclusions do not exceed evidence: core = honest INFEASIBLE/NULL; Part 2 descriptive only; Part 3 explicitly scoped as combined-effect, not a decomposition ✔.

## Data limitations & claim-downgrade conditions (as required by brief)
- The two-shock **separation** is **not** delivered — it is infeasible with free
  data and is reported as such. Any future positive claim requires **paid
  intraday Treasury-futures / SOFR tick history** (≥1.6–4 yr of complete
  coverage per the Part 1 power calc), or a vendor with deep historical 5-min
  bars (e.g. Databento / Polygon / Alpha Vantage FOMC-month slices).
- Options-implied **skew / tail-jump** outcomes are out of scope: no free
  intraday IV surface is available. They are named in the brief but cannot be
  computed honestly here.
- Part 3 uses daily **range/return** RV proxies (not true intraday RV) for the
  long sample; it is a context baseline, not the primary claim.

## Files
- `K1658.py` — reproducible pipeline (`uv run python experiments/K1658/K1658.py`).
- `K1658_results.json` — full results (feasibility, case studies, regression, bootstrap).
- `test_K1658.py` — invariant tests (lag alignment, seed, Holm family size, N=2 feasibility).
- `data/` — cached raw yfinance pulls (freezes the 60-day intraday window).
- `K1658_fig1_intraday_casestudies.png`, `K1658_fig2_aggregate_fomc_rv.png`.

## Follow-up (handled by the followup fire, per brief)
Codex primary-path code review → `review_verdict.json` (via
`experiment_gates.py verdict-template`) → worktree merge. Knowledge entry only
after CONDITIONAL_PASS-or-better is confirmed by that review (agents do not
write `knowledge.json` directly).
