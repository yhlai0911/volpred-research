# Cumsum-Metric Pattern Audit (K1018-derivative)

**Date**: 2026-05-02
**Auditor**: main-thread (Claude)
**Scope**: All `cum = np.cumsum(r)` usages in `experiments/**/*.py` (excluding `__pycache__`)
**Trigger**: K1018 had bug `cum = np.cumsum(r)` followed by `dd = cum - peak` — only valid for log returns. K1018 fix applied; this audit checks for systemic pattern across other experiments.

## Classification key

- **(A) BUG** — `cum = np.cumsum(r)` where `r` is **arithmetic** daily return, used for MDD/CAGR/Calmar. Fix: `cum = np.cumprod(1 + r)` and `dd = (cum - peak) / peak`, or convert `r` to log.
- **(B) OK — log-space** — `r` is `np.log(price/price.shift(1))` or equivalent. cumsum = correct compound log path; `cum - peak` is the log-MDD (`np.exp(mdd) - 1` recovers pct).
- **(C) OK — non-metric** — cumsum used for exposure / counts / signal aggregation, not a NAV path. (No instances found.)

## Results table

| File | Line(s) | Class | Notes |
|------|---------|-------|-------|
| `experiments/hawkes_vol_jump/hawkes_vol_jump.py` | 669 | B | `returns = np.log(spy / spy.shift(1))` (L82); `ret_arr` derives from log returns. |
| `experiments/k1074/k1074.py` | 487, 735 | B | `r_spy = np.log(SPY/SPY.shift(1))` (L141-142); both `metrics()` and DD-curve plot operate on log returns. |
| `experiments/k1094/k1094.py` | 504 | B | `r_tw = np.log(TW/TW.shift(1))`, `r_gld = np.log(...)` (L170-171); same `metrics()` template as K1074 but log inputs. |
| `experiments/k157/k157_correlation_forecasting.py` | 557 | **A** | `returns_df = price_df.pct_change()` (L742) → arithmetic; `port_ret_5050 = 0.5*fwd_r1.sum() + 0.5*fwd_r2.sum()` aggregates monthly arithmetic returns. MDD computed from `cum - peak` understates wealth drawdown for monthly compounding. |
| `experiments/k191/k191_put_call_ratio.py` | 759 | B | `df["ret"] = np.log(close/close.shift(1))` (L185); `oos_ret` and downstream `strat_ret` are log. |
| `experiments/k201/k201_tda_vt_strategy.py` | 304 | B | `returns = np.log(prices/prices.shift(1))` (L63); `compute_metrics` receives log returns. |
| `experiments/k204/k204_gld_momentum_vt.py` | 289 | B | `merged["{asset}_ret"] = np.log(...)` (L95); explicit "Log returns" comment. |
| `experiments/k215/k215_seasonality.py` | 602 | B | `df['Return'] = np.log(Close/Close.shift(1))` (L56); seasonality overlay multiplies log returns. |
| `experiments/k217/k217_nonequity_optimal_vt.py` | 480 | B | `df["ret"] = np.log(...)` (L95); same function uses `np.exp(cum[-1]) - 1` and `cum_wealth = np.exp(cum)` for proper wealth-space MDD — log-space is intentional and correct. |
| `experiments/k228/k228_leverage_dynamics.py` | 824, 825 | B | `df["returns"] = np.log(Close/Close.shift(1))` (L239); both `vt_cum` and `bh_cum` operate on log. |
| `experiments/k281/k281_vix_trigger.py` | 284 | B | `data["spy_ret"] = np.log(...)`, `data["gld_ret"] = np.log(...)` (L59-60); `port_ret = lagged_w * (0.5*spy + 0.5*gld)` is log. |
| `experiments/k288/k288_cross_period_stability.py` | 108 | B | `df["spy_ret"] = np.log(SPY/SPY.shift(1))` (L90-91); function docstring explicitly states "Maximum drawdown from daily log returns". |
| `experiments/k300/k300_vix_speed_validation.py` | 643, 675 | B | `df['Return'] = np.log(SPY_Close/SPY_Close.shift(1))` (L194); both BH and strategy cumsum on log returns. |
| `experiments/k306/k306_vix_speed_trigger.py` | 151 | B | Function docstring "Calculate strategy metrics from daily log returns"; `cum_ret = np.exp(np.sum(dr)) - 1`, `mdd_pct = np.exp(mdd) - 1` confirms log-space treatment. |
| `experiments/k503/k503_vix_meanrevert_strategy.py` | 132 | B | `data["SPY_ret"] = np.log(SPY/SPY.shift(1))` (L87); `gross_ret = w * spy_ret_arr + (1-w) * RF_DAILY` where RF_DAILY is also log. |
| `experiments/k561/k561_bond_equity_switch.py` | 290 | B | `returns = np.log(prices/prices.shift(1))` (L76); `port_ret` aggregates log returns. |
| `experiments/k568/k568_optimal_weight_function.py` | 190 | B | `r_SPY = np.log(...)`, `r_GLD = np.log(...)` (L157-158); `r_port = 0.5*r_SPY + 0.5*r_GLD` is log. |
| `experiments/k583/k583_iv_surface.py` | 665 | B | `df['log_return'] = np.log(spy_close/spy_close.shift(1))` (L183); `spy_ret` is log throughout. |
| `experiments/k843/k843_intraday_futures.py` | 462 | **A** | Intra-day returns built as `(close - open) / open` arithmetic (L261, 275, 280: `s0_ret`, `slot_c_ret`, `day_ret`). Cumsum-MDD treats these as log; impact is **small** (intraday returns are tiny so log≈arith) but methodologically incorrect. |
| `experiments/vt_crowding_simulation/vt_crowding_simulation.py` | 291, 301 | B | Input `returns = np.log(spy_close/spy_close.shift(1))` (L68); simulated `mod_returns` and `vt_ret = weights * mod_returns` retain log scale. |

## Summary

- **Class A (BUG)**: **2 files** — k157, k843
- **Class B (OK log-space)**: **18 files**
- **Class C (non-metric)**: 0 files

## Recommended fixes (priority order)

### Priority 1 — k157 (`experiments/k157/k157_correlation_forecasting.py`)
- **Why higher priority**: Methodology paper / strategy research output (correlation forecasting + VT portfolio). Monthly arithmetic returns + cumsum-MDD systematically understates true wealth drawdown for monthly compounding. Magnitude error is non-trivial (monthly ret ~1-3% so deviations between log≈arith become material).
- **Fix**: Either convert `port_ret` to log via `np.log(1 + port_ret_5050)` before storing, **or** change the MDD block to:
  ```python
  cum = np.cumprod(1 + rets)
  peak = np.maximum.accumulate(cum)
  dd = (cum - peak) / peak
  mdd = float(np.min(dd))
  ```
- **Affected metrics**: `max_drawdown` field in `summary[key]` for all weight schemes (50/50, model-based portfolios across SPY-GLD, SPY-TLT, GLD-TLT pairs).
- **Active strategy / paper-cited?**: Check `storage/memory/knowledge.json` for K157 status before propagating; methodology piece — likely still feeds a feed article / paper appendix.

### Priority 2 — k843 (`experiments/k843/k843_intraday_futures.py`)
- **Why lower priority**: Intra-day returns are tiny (often <0.5%), so log≈arithmetic and MDD numerical error is minimal in practice (probably <5 bps on absolute MDD value). Methodologically still wrong.
- **Fix**: Same pattern — either log-transform arithmetic intraday returns before cumsum, or switch MDD computation to `np.cumprod(1 + r)` form.
- **Affected metrics**: `mdd` in the per-strategy stats dict (intraday TX futures strategy).
- **Active strategy?**: Cross-check with `STRATEGY_REGISTRY` / `docs/strategy-registry.md` — if not on registry, low urgency.

### Priority 3 — none
All other 18 files are correctly using log returns. No further fixes needed in scope of this audit.

## Cross-reference

- Knowledge entries: `pending_fix_k1018_metric_helper_cumsum_to_cumprod`, `audit_2026_05_02_simplified_metric_helper_systemic_pattern`
- K1018 is the source incident; same `metrics()` helper template was copy-pasted across many experiments but **the input convention (log vs arith) varied**. This audit confirms the systemic-pattern hypothesis is bounded — only 2 of 20 grep hits are actual bugs because most authors paired the helper with log returns.

## Blind-spot follow-up audit (2026-05-02 21:54 CST)

Original grep `cum = np.cumsum` missed pandas `.cumsum()` method calls and inline `ret.cumsum() - ret.cumsum().cummax()` patterns. Re-audit with `grep -rn '\.cumsum()'` found 2 additional class-A bugs:

| File | Line | Class | Notes |
|------|------|-------|-------|
| `experiments/order_flow_vol/order_flow_vol.py` | 542, 548, 554, 559 | **A** | `df["ret"] = df["close"].pct_change()` (L65) → arithmetic; 4 strategies (base / vol / ami / bh) all compute MDD inline as `ret_oos.cumsum() - ret_oos.cumsum().cummax()` |
| `experiments/k1176/k1176.py` | 197, 241/381/401 | **A** | `max_drawdown()` helper L194-200 uses `cum = r.cumsum(); dd = cum - cum.cummax()`. Docstring "arithmetic cumulative sum (percent)" encodes the bug. Caller at L241 passes `strat = pos * mret - tc_drag` where `mret` traces back to `pct_change()` at L131. Helper is also called at L381, L401 (5050 / global combo) |
| `experiments/k256/k256_fed_communication.py` | 498/499/507 | B | `TLT_ret = np.log(...)` (L164) — log space; OK |

**Updated tally**: Class A bugs now **4 files** (k157 + k843 already source-fixed; order_flow_vol + k1176 pending fix; defer until codex quota reset 12:47 AM CST per hook discipline).

**Future audit**: always run **both** `'cum = np.cumsum'` and `'\\.cumsum()'` patterns + spot-check helper functions named `max_drawdown` / `mdd` / `compute_metrics` for hard-coded simplified pattern.

## Audit v3 helper-function pass (2026-05-02 22:00 CST)

Scanned 20+ helper-function definitions across `experiments/`：

| File | Line | Pattern | Verdict |
|------|------|---------|---------|
| k1191, k1177, k1196, k1122, k1123, k413 | various | `(1 + r).cumprod() → (cum-peak)/peak` | ✅ canonical |
| k1197, k229, k289 | various | `np.exp(np.cumsum(log_r))` → NAV path → `(cum-peak)/peak` | ✅ correct log handling |
| k533 | 94 | `np.cumprod(1+r) → (cum-peak)/peak` | ✅ canonical |
| k288 | 106 | `cum=np.cumsum(returns); dd=cum-running_max` (returns are log per docstring) | B (log-space, OK if downstream applies `np.exp(mdd)-1`) |
| k573, k574, k818, k272, decision_router, behavioral_vt | various | `max_drawdown(cum_series)` callers — input already a cumulative series | depends on caller |
| **k818 L643-651, 657** | 643/644/651 | `cum = np.cumsum(strat_ret)` where `strat_ret` = `pct_change()*100`; `dd = cum - peak` (raw level diff, no /peak division) | **A** |
| k250, k243, k667 | various | `np.cumprod(1+r)` or `cum/np.maximum.accumulate(cum)-1` | ✅ |

**New Class A (BUG)**: `experiments/k818/k818_ssvs_return_prediction.py` — `pct_change()*100` (percentage points) → `cumsum()` → `dd = cum - peak` produces percentage-point cumulative drawdown, not NAV-fraction MDD. Distortion compounds over long horizons.

**Updated tally** (post-v3): 5 class-A files
- k157 ✅ source-fixed
- k843 ✅ source-fixed
- order_flow_vol ⏸ deferred
- k1176 ⏸ deferred
- **k818** ⏸ deferred (newly identified)

All deferred fixes pending codex quota reset 12:47 AM CST 2026-05-03.

## Audit methodology compliance (per `.claude/rules/experiments.md` 2026-04-29 hard rule)

- **Scan range**: full population of `grep -rln 'cum = np.cumsum' experiments/ --include='*.py'` excluding `__pycache__` → 20 files.
- **Blind-spot analysis**: pattern variants not covered:
  - `cum = np.cumsum(<some_expr>)` where rhs is computed inline (not a bare variable name) — possible if other experiments use e.g. `np.cumsum(strat_ret_arr * weights)` directly. Spot-check on `grep 'cumsum(' experiments/` recommended as follow-up.
  - `np.cumsum(...)` assigned to other variable names (e.g. `wealth = np.cumsum(...)`, `nav = np.cumsum(...)`) — out of this audit's grep filter.
  - Pandas `.cumsum()` method calls (e.g. `r.cumsum()`) — out of grep pattern but same bug class possible.
- **Verification method**: per file, traced the variable passed to cumsum back to its definition (np.log vs pct_change vs `(close-open)/open`). Where ambiguous, confirmed via secondary evidence (docstring, downstream `np.exp()` usage, comment).

**Suggested follow-up audit** (not part of this report): re-run with broader grep `grep -rln 'cumsum' experiments/ --include='*.py' | grep -v __pycache__` to catch the blind-spot patterns above.
