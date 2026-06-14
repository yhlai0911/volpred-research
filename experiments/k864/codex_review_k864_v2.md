# K864-v2 Codex Closure Review

Date: 2026-06-14

## VERDICT

CONDITIONAL_PASS

K864-v2 closes the critical source-code issues found in the published K864 review, provided the article keeps the revised model-conditional claim: heterogeneous VT amplifies market risk in the primary quadratic herding ABM, but the effect is essentially null under the linear demand sensitivity.

## Critical Issues Closed

- Lookahead / crash metric: crash frequency now uses rolling t-1 22-day sigma (`r_t < -3 * sigma_{t-1}`), and the prior ex-post full-sample sigma metric is retained only as `expost_flash_crash_freq`.
- Price clamp state consistency: when the simulated return is clamped, the daily return stored into the rolling volatility buffer is updated from the clamped price path.
- Noise trader demand accounting: net demand now uses the realized clipped noise weight change, not the raw pre-clip noise signal.
- DM / Harvey significance: primary comparisons now use common-random-number paired differences with Harvey-Leybourne-Newbold small-sample correction and a `|HLN t| >= 3` reporting gate. This is correctly described as an ABM Monte Carlo regime comparison, not a forecast-loss DM panel.
- Demand scaling identification: the primary quadratic demand rule is now explicitly declared, and the experiment adds a linear demand sensitivity run with the same seeds.
- Mechanism evidence: per-type flow diagnostics show A-to-C and A-to-D lag correlations are small negative at 50% adoption, while C-to-D is mainly contemporaneous. The old A/C/D lead-lag cascade claim is withdrawn.
- Individual performance interpretation: results now include per-type performance. At 50% adoption, Sharpe is A=-0.245, B=-0.170, C=0.773, D=1.173; aggregate VT Sharpe improvement is not interpreted as every agent improving.

## Key Verification Results

- Primary quadratic, 50% adoption: annual market volatility rises from 19.0% to 29.0%; rolling crash frequency rises from 0.756/year to 5.563/year; max drawdown worsens from -41.1% to -53.6%.
- Primary quadratic, 50% adoption, HLN tests: annual vol `t=76.00`, crash frequency `t=94.66`, max drawdown `t=-25.00`, VT Sharpe `t=15.04`; all pass the Harvey 3-sigma gate.
- Linear demand, 50% adoption: annual vol is 16.0078% vs 16.0078%, rolling crash frequency is 0.987 vs 0.987/year, and VT Sharpe is 0.474 vs 0.472; none pass the Harvey 3-sigma gate.
- Article `mile_1a6d9369` was revised from a broad claim to a model-conditional warning and now references the K864-v2 results and sensitivity figures.

## Remaining Caveats

- The primary positive result is conditional on quadratic demand amplification. It should not be presented as an empirical market law.
- The 100% heterogeneous quadratic scenario remains pathological because the simulation hits repeated price clamps; interpret it as stress-test evidence only.
- The paired HLN test is appropriate for common-random-number Monte Carlo comparisons here, but it is not a substitute for forecast-loss DM testing on an empirical time series.
- Local article files were updated. The attempted `feed-sync --apply` hung and was killed, so remote Supabase projection still needs separate confirmation.

## Verification Commands

- `python -m py_compile experiments/k864/k864_heterogeneous_abm.py`
- `K864_N_SIMS=2 python experiments/k864/k864_heterogeneous_abm.py`
- `python experiments/k864/k864_heterogeneous_abm.py`
- `python scripts/build_feed_index.py`
