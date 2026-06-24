# K1549: Russell Reconstitution Announcement-to-Effective Window Event Study

**Status:** Completed
**Verdict:** See `## Result Summary` and `## Codex Review` below
**Run date:** 2026-06-24

## Motivation

Russell US indices undergo annual reconstitution every June. Unlike S&P 500
inclusion (which is committee-discretionary, continuous, and irregular),
Russell's reconstitution is:

- **Rule-based**: Membership is mechanically determined by May-31 market cap rank
- **Pre-announced**: FTSE Russell publishes a preliminary list in early June
  (announcement date), an effective date roughly one month later (last Friday
  of June 2007-2021, fourth Friday from 2022, with semi-annual adds from 2023+)
- **Single-day rebalance**: Heavy index-tracking AUM (~$10T+) re-weights at the
  close of the effective date

This creates a structurally distinct experimental setting from S&P inclusion:
the entire 1-month announcement→effective window is a publicly known
"front-running incentive" period in which index arbitrageurs, recon traders,
and ETF arbs progressively adjust positioning.

K1549 asks: **does this ex-ante known 1-month window produce systematic
volatility / volume / abs-return elevation in IWM (R2000), IWO (R2000 Growth),
IWN (R2000 Value), IWP (R Midcap Growth) ETFs vs. their pre-window baseline?**

This is conceptually orthogonal to:
- **K1341**: Single-day intraday-range dislocation on Friday-of-rebalance
- **K1341 (S&P arm)**: NULL on S&P, where mechanism is committee-driven

If Russell window effect exists, it validates rule-based scheduled
rebalances as an investable calendar anomaly, even if S&P inclusion is null.

## Literature

- Madhavan, A. (2003). "The Russell Reconstitution Effect." *Financial Analysts
  Journal* 59(4), 51-64. Documents pre-effective return runup in stocks
  flagged for additions.
- Cai, J., & Houge, T. (2008). "Long-Term Impact of Russell 2000 Index
  Rebalancing." *Financial Analysts Journal* 64(4), 76-91. Shows persistent
  flow effects.
- Chen, H., Noronha, G., & Singal, V. (2004). "The Price Response to S&P 500
  Index Additions and Deletions." *Journal of Finance* 59(4), 1901-1930.
  Provides S&P contrast for null-mechanism case.
- Petajisto, A. (2011). "The Index Premium and Its Hidden Cost for Index
  Funds." *Journal of Empirical Finance* 18(2), 271-288.

## Method

### Data
- ETFs: IWM (R2000), IWO (R2000 Growth), IWN (R2000 Value), IWP (R Midcap Growth)
- Source: `yfinance` daily OHLCV, 2010-01-01 to 2026-06-24
- Russell annual reconstitution calendar — hard-coded from FTSE Russell
  historical schedule (announcement date ≈ first Friday of June; effective date
  = last Friday of June through 2021, fourth Friday from 2022)

### Event Window Definition
- D = 0: **announcement_date** (ex-ante public)
- Event window: [announcement_date, effective_date], typically ~21 trading days
- Pre-event baseline: [announcement_date - 90 cal days, announcement_date - 1]
  → ~60 trading-day baseline
- All daily metrics computed from same-day OHLCV (no smoothing across the
  pre/event boundary).

### Lookahead Policy
- **Announcement date is ex-ante public** (FTSE Russell publishes preliminary
  list). All metrics computed from D = announcement_date, **not** from the
  effective date.
- **No `signal.shift(1)` needed for trading signal** because no trading rule
  is constructed — this is a descriptive event study. The "use future
  information" risk is solely whether we accidentally use the *effective*
  date as the anchor (we do not).
- Baseline window strictly precedes the announcement date by ≥1 day.
- No forward-looking smoothing, rolling means, or normalization that spans
  the announcement boundary.

### Metrics (per ETF, per year)
1. **RV ratio**: mean(squared log-return in event window) / mean(squared
   log-return in pre-event baseline). Test H0: ratio = 1.
2. **Volume ratio**: mean(daily share volume in event) / mean(baseline).
3. **Abs-return ratio**: mean(|log-return| in event) / mean(baseline).
   This is a robust intraday-shock proxy that is less sensitive to extreme
   outliers than squared return.

### Statistical Tests
- Per-ETF pooled across ≥10 years:
  - One-sample t-test on log-ratio vs. 0 (i.e., ratio vs. 1)
  - Wilcoxon signed-rank test on log-ratio vs. 0
- **Bonferroni correction**: 4 ETFs × 3 metrics = 12 tests
  → cutoff α = 0.05 / 12 = 0.004167
- Seed = 42 fixed for the wild bootstrap confidence intervals.

### Success Criteria
- ≥1 metric × ETF combination Bonferroni-significant (p < 0.004167) →
  POSITIVE finding; effect direction must be reported with sign.
- All 12 NULL → write four-piece set honestly as NULL result.

## Result Summary

**Verdict: CONDITIONAL_PASS — NULL on Bonferroni-corrected family; nominally
suggestive directional signal on IWM RV not robust to multiplicity.**

**Sample**: 16 Russell reconstitution events (2010-2025), 4 ETFs, 3 metrics
each = 12 family tests. Bonferroni-adjusted α = 0.05/12 = 0.004167.

### Pooled (n=16) event/baseline ratios — geometric mean (raw t-test p)

| ETF | RV (sq ret) | Volume | Abs return |
|-----|-------------|--------|------------|
| IWM | 0.681 (p=0.0403) | 0.987 (p=0.7280) | 0.871 (p=0.0734) |
| IWO | 0.673 (p=0.0298) | 0.918 (p=0.2211) | 0.870 (p=0.0735) |
| IWN | 0.728 (p=0.0918) | 0.966 (p=0.5052) | 0.877 (p=0.1093) |
| IWP | 0.628 (p=0.0606) | 0.828 (p=0.0189) | 0.815 (p=0.0549) |

**None of 12 tests crosses Bonferroni cutoff** (smallest p = 0.0189, IWP
volume; needs ≤ 0.00417). Wilcoxon results align (no Bonferroni-significant
test).

### Direction of nominal trends

All 12 ratios are **below 1** (event window quieter than 90-day baseline).
This is the *opposite* of the announcement-window front-running narrative
that motivated the experiment. Mechanism candidates worth follow-up:

- **Seasonality**: Russell announcement window = early June; baseline
  spans March-May, which often contains earnings season, FOMC meetings, and
  spring tax-related flows. The pre-summer market is structurally quieter
  → a 1-month window straddling June is on average *less* volatile than
  a March-May baseline, regardless of Russell mechanics.
- **Effective-day concentration**: K1341 documents that *single-day*
  closing-auction dislocation on reconstitution Friday is large. K1549's
  monthly aggregation may dilute this single-day shock toward the mean.
- **ETF-level signal masking**: Russell flows affect *individual* small-caps
  more than the cap-weighted ETF (the IWM portfolio is rebalanced
  intra-day on the effective close, but the NAV-weighted sum is mostly
  preserved). A single-name Russell event study would likely be sharper.

### Honest framing

The K1549 family null is consistent with **no aggregate ETF-level
announcement-to-effective excess volatility**, after a calendar-aware
baseline and multiplicity correction. It does **not** falsify the Russell
single-day reconstitution effect (K1341 turf) nor the single-name
front-running literature (Madhavan 2003; Cai & Houge 2008).

### Caveats

- n=16 years is modest; pooled t-test has ~15 df. Bonferroni m=12 is
  conservative given IWO/IWN/IWM correlation (R2000 sub-indices share
  components). A factor-corrected or correlation-aware adjustment would
  raise individual significance slightly but is unlikely to flip the
  Bonferroni verdict.
- Baseline = 90 calendar days pre-announcement could itself contain
  earlier reconstitution rumor activity. Sensitivity to baseline length
  (60 / 120 days) would be a useful robustness check; not run here.
- Russell calendar from 2022 onward uses fourth Friday of June (FTSE Russell
  schedule revision); calendar was hand-coded from the published schedule.

## Codex Review

**Reviewer**: Codex CLI 0.141.0 invocation timed out at 5 min; per
`.claude/rules/experiments.md` fallback policy, switched to
**self-audit** with `reviewer_source = codex_timeout_fallback_self_audit`.

### Self-audit log (3-pass)

**Pass 1 — Lookahead audit**:
- `log_ret = log(Close / Close.shift(1))` (line 90) — backward only.
- `window_stats` (line 103) uses `df.index >= start & <= end` strict bounds;
  no smoothing across announcement boundary.
- Baseline `bl_end = ann - 1 day` (line 128) — strictly precedes
  announcement_date.
- Anchor = published FTSE Russell preliminary-list date, ex-ante public.
- **No lookahead leak.**

**Pass 2 — Seed audit**:
- Only stochastic component = `bootstrap_ci` (line 200); uses
  `np.random.default_rng(SEED)` with `SEED=42` (line 33).
- `stats.ttest_1samp`, `stats.wilcoxon` are deterministic closed-form.
- yfinance fetch order is deterministic (sequential, threads=False).
- **All stochastic points seeded.**

**Pass 3 — Bonferroni / NaN audit**:
- m = 4 ETFs × 3 metrics = 12; α/m = 0.00417 correctly computed (line 247).
- IWO/IWN/IWM are correlated → Bonferroni is conservative (Sidak / FDR
  would be tighter), but conservative is fine for a NULL conclusion.
- NaN handling: `window_stats` calls `dropna(subset=[log_ret, sq_ret,
  abs_ret, Volume])` before any mean; first-row NaN from `shift(1)`
  cannot pollute. Data coverage logged in `results.data_coverage` for
  audit trail.

**Self-audit verdict: CONDITIONAL_PASS** — methodology sound; verdict
contingent on accepting that a 5-min Codex timeout justifies fallback
(per K1259 protocol).

