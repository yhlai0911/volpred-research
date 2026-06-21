# k_vix_complacency_20260621 — Does Low VIX Signal an Imminent Crash?

**An honest empirical test of the "market complacency / low-VIX tail risk" narrative.**

## Motivation

A perennially popular market narrative says: *"low VIX = complacency = hidden
danger = imminent crash."* It is intuitive, it sells fear, and it is repeated
every time the VIX drifts into the low teens. The VolPred platform's
credibility depends on **testing this honestly rather than cherry-picking data
to validate fear.**

The academic prior runs against the naive version of the claim:
- **Volatility is highly persistent.** Low-vol regimes last *years*, not weeks.
  A low VIX today says far more about tomorrow's VIX than about a crash.
- The **"volatility paradox" / fragility view** (Minsky; Brunnermeier &
  Sannikov; Danielsson et al.) says low realized volatility coincides with
  *compressed risk premia and rising leverage*, so that **when a shock
  eventually arrives, the conditional tail can be fat** — but the *timing* of
  that shock is not forecastable from the VIX level.

So the honest question is not "does low VIX precede a crash?" but **"is low VIX
a crash-TIMING signal, or merely a backdrop of compressed risk premia whose
tail only matters once an exogenous shock hits?"**

## Data

- `^VIX` and `^GSPC` daily closes from **yfinance**, `auto_adjust=False`.
- Multi-index columns handled explicitly (`df['Close']['^VIX']`).
- Full overlap sample: **1990-01-02 → 2026-06-18, N = 9,183 trading days**
  (N = 9,120 with a complete forward-63-day window).

## Method

For each day *t*:
1. **Regime label** is assigned using **only VIX information up to and
   including day t** — no future data enters the label.
2. **Forward tail measures** (forward 21 and 63 trading days) are computed:
   - **forward max drawdown** = worst peak-to-trough return of SPX over
     `t … t+h`, anchored at today's price (reported as a positive magnitude);
   - **forward realized vol** = annualized std of SPX log returns over
     `t+1 … t+h`.
   - These windows are **forward by design — that IS the research question**,
     not lookahead. (Cross-checked against `.claude/rules/experiments.md`: the
     forward label is the object of study; only feature/regime construction
     must be lag-clean, and it is.)

### Regime definitions

| Regime | Definition | Lookahead status |
|---|---|---|
| **`bottom_quintile_realtime`** (PRIMARY) | VIX ≤ expanding-window 20th percentile (≥252 prior obs) | **Real-time, lookahead-free** |
| `bottom_quintile` | VIX ≤ 13.33 (20th pct of full history) | Descriptive (full-sample threshold) |
| `bottom_decile` | VIX ≤ 12.15 (10th pct of full history) | Descriptive |
| `vix_lt_15` | VIX < 15.0 | Fixed absolute (clean) |
| `vix_lt_13` | VIX < 13.0 | Fixed absolute (clean) |

The primary regime is the **real-time expanding-percentile** version so that no
future VIX distribution leaks into the day-t label (a Codex-review fix; the
full-history percentile is retained only as a descriptive benchmark).

### Statistics

- **Conditional vs unconditional** forward-tail distributions (median / p95 /
  worst), plus an explicit **low-vs-non-low** contrast (non-overlapping
  subsets).
- **Moving-block bootstrap** (block = 63, fixed seed `20260621`, 2,000 reps)
  for the median-drawdown difference — block length matches the forward
  horizon so overlapping-window serial dependence is respected.
- **Fragility / "conditional-on-shock" test**: P(forward-63d drawdown > 10%)
  and the median drawdown *depth given a shock occurs*, by regime.
- **Sensitivity**: 4 thresholds (real-time quintile, full-hist decile,
  VIX<15, VIX<13) and a **pre-2008 / post-2008 sub-period split** with
  sub-period-local thresholds.

## Key results (all from `*_results.json`)

**Current VIX = 16.40 (2026-06-18) = 42nd percentile** of the full history.
It is **NOT in the low-VIX regime** (bottom-quintile threshold ≈ 13.3) — so the
"complacency" framing does not even apply to the current tape.

**Forward 63-day max drawdown (magnitudes):**

| Regime | median | p95 (bad tail) | worst |
|---|---|---|---|
| Low-VIX (real-time bottom quintile) | **4.08%** | **10.16%** | 33.92% |
| Non-low-VIX | 6.11% | 19.31% | 42.15% |
| Unconditional (all days) | 5.58% | 18.89% | 42.15% |

- **Low VIX precedes SHALLOWER, not deeper, forward drawdowns** — the opposite
  of the fear narrative, on both the median and the p95 bad tail.
- **Moving-block bootstrap, low − non-low median drawdown = −2.03%, 95% CI
  [−3.14%, −1.18%]** (entirely below zero). Robust to serial dependence and to
  a clean non-overlapping baseline.
- **Crash frequency:** P(forward-63d drawdown > 10%) = **5.9%** in the low-VIX
  regime vs **32.7%** in the high-VIX (top-quintile) regime and 19.7%
  unconditionally.
- **Forward realized vol** median: 10.0% (low-VIX) vs 13.3% (unconditional) —
  vol persistence, exactly as the prior predicts.

**Sensitivity holds across all variants** (real-time quintile, full-hist
decile, VIX<15, VIX<13 all show lower median/p95 drawdowns) and **across both
sub-periods** (pre-2008 low-VIX median 3.73% vs uncond 5.24%; post-2008 4.06%
vs 5.73%).

**The fragility caveat (this is the honest part).** Low VIX is *not* an
all-clear:
- The **worst** forward-63d drawdown that began in a low-VIX regime is still
  **−33.9%** (post-2008) — low vol did not prevent it, it only made it rarer.
- *Given* a >10% shock does occur, the median depth is ~11% in low-VIX vs ~14%
  in high-VIX — shocks that strike from a calm base are not trivially small.
- The low-VIX p95 and worst drawdowns are **markedly fatter post-2008** (p95
  7.7%→12.3%, worst 9.4%→33.9%) — consistent with the fragility/leverage view
  that compressed-vol regimes can carry a heavier conditional tail in the
  modern, more-levered market structure.

## HONEST VERDICT

**The data supports the academic prior, not the fear narrative.**

Low VIX is a **poor crash-TIMING signal**: low-VIX days are *followed by lower*
typical and tail drawdowns, *lower* crash frequency, and *lower* forward
realized vol — because volatility is persistent and calm regimes mostly beget
more calm. Anyone treating "low VIX" as a contrarian "sell / crash-is-coming"
trigger would have been wrong far more often than right, in every threshold and
both sub-periods tested.

**But low VIX is also not a fragility-free all-clear.** The left tail does not
vanish — the worst low-VIX forward drawdown is still −34%, depth-given-shock is
still double-digit, and the conditional tail has visibly fattened post-2008.
This is the **"volatility paradox":** low VIX is best read as an indicator of
**compressed risk premia and a quiet base from which a rare-but-real shock can
still detonate** — *not* as a clock that tells you a crash is imminent. The
correct posture is risk-management (sizing, hedges, awareness that calm raises
fragility), **not** market-timing on the VIX level.

## Files

- `k_vix_complacency_20260621.py` — full analysis (seed `20260621`).
- `k_vix_complacency_20260621_results.json` — all numbers.
- `k_vix_complacency_fwd_drawdown.png` — 4-panel chart:
  (a) VIX history + low-VIX bands + current level;
  (b) forward-63d drawdown distribution, low-VIX vs all;
  (c) median vs p95 forward drawdown by regime;
  (d) crash **frequency** (low when VIX is low) vs crash **depth given a
  shock** (the fragility view).

## Review

- **Codex CLI review (codex-cli 0.139.0):** CONDITIONAL_PASS. Forward-window
  mechanics, RV/return alignment, max-drawdown computation, and NaN boundary
  handling all verified PASS. Three findings addressed in this version:
  (1) FAIL on full-history percentile lookahead → added **real-time
  expanding-window** primary regime; (2) iid-bootstrap dependence caveat →
  switched to **moving-block bootstrap** (block = 63); (3) low-vs-unconditional
  nesting caveat → added explicit **low-vs-non-low** clean contrast.

## Caveats / scope

- Sample is the historical VIX/SPX joint record (1990–2026); regime sizes:
  real-time low-VIX n = 2,082 days with full fwd63 windows.
- Overlapping forward windows are inherent to the forward-tail design; the
  block bootstrap mitigates but does not fully remove dependence — CIs are
  indicative, not exact.
- The full-history percentile threshold uses the whole sample to *define* "low"
  (descriptive benchmark only); the real-time regime and fixed thresholds are
  the lookahead-clean anchors and reach the same conclusion.
