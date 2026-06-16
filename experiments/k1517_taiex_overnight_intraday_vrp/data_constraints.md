# K1517 Data Constraints

## Why no true (option-implied) VRP for TAIEX

The original Papagelis & Dotsis (2025) overnight-vs-intraday VRP
decomposition uses model-free option-implied variance (VIX-style index).
For TAIEX the natural analog is **VIXTWN** (Taiwan VIX from TAIFEX TXO
options).

**The VIXTWN history available in this repo is too short for the 2007-2026
analysis window:**

- File: `data/vixtwn/vixtwn_daily.csv`
- Rows: 129
- Date range: 2025-12-01 → 2026-06-XX (≈ 6 months of daily obs)

129 obs falls far below:

- The 500-obs research-honesty gate (`research_program.md`)
- The 4,691-obs sample we have for the GARCH proxy
- The bootstrap requirement (1000 reps × 21d blocks → need ≥ 200 obs for
  even minimal block coverage)

## Decision

Use the **same GARCH(1,1) pseudo-VRP proxy** as the parent SPY/QQQ/IWM/EFA
experiment (`experiments/research_intraday_vs_overnight_vrp/`) so the
cross-market comparison is **methodologically symmetric**. This is per
`.claude/rules/experiments.md`:

> 跨市場比較必 symmetric refinement — 若 benchmark 用 canonical spec、
> alternative 用 unrefined EM-only，得到的係數差是 asymmetric artifact
> 不是真效應。

A true option-implied VIXTWN-based TAIEX VRP comparison is **deferred** to a
future K when one of:

1. The VIXTWN history is back-filled from TAIFEX archives to ≥ 2006.
2. A scripted reconstruction of model-free implied variance from TXO option
   chains is available.
3. A 5+ year VIXTWN window builds up naturally.

## Robustness option NOT executed

The brief suggested running a **VIXTWN robustness check on the 129-day
subset** as a non-primary signal. We **decided not to include** this in the
results JSON because:

- 129 obs is below the 200-obs hard floor for block-bootstrap reliability.
- A 6-month window does not span any volatility regime change (2025-12 →
  2026-06 is a single quasi-low-vol regime).
- Reporting any t-stat from 129 obs would invite over-interpretation that
  contradicts the research-honesty principle ("結論強度不超過證據").

If a future K wants to revisit, the inputs are documented at
`data/vixtwn/vixtwn_daily.csv` and a stub helper can be added without
touching this experiment.

## TAIFEX 0050 intraday

The TAIFEX 5-min 0050 series (`data/intraday/0050_TW_5min_*.csv`) is also
**not** used here because:

- 0050 is the Yuanta TW50 ETF, not the TAIEX cash index.
- Using 0050 intraday RV against TAIEX overnight gap would introduce a
  benchmark mismatch (different basket, different liquidity, different
  close-to-open gap dynamics).
- Keeping a single, clean TAIEX-OHLC source preserves the parent-experiment
  symmetry.

A separate K can extend to 0050 (or TX futures) intraday RV when that
becomes the primary research question.

## TAIEX session model

TAIEX cash trading is 09:00–13:30 TPE. There is **no formal night session
for the cash index**. "Overnight" in K1517 = the open-to-prior-close gap,
which captures:

- US-hours news flow (S&P 500 close at 04:00 TPE next day during DST,
  03:00 outside).
- Asian morning macro releases (BOJ, China data).
- TAIFEX after-hours futures price discovery (15:00 prior day to 05:00
  next morning) implicitly bleeds into TAIEX cash open via futures-cash
  basis arbitrage.

This is the same operational definition Papagelis & Dotsis (2025) use for
markets without continuous trading.
