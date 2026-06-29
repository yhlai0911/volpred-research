# K1570 Codex Source Review

**Review date**: 2026-06-29  
**Reviewer**: Codex CLI  
**Code integrity verdict**: `PASS_WITH_WEAK_PARTIAL_RESULT`

## Scope

Reviewed:

- `experiments/k1570/k1570.py`
- `experiments/k1570/k1570_results.json`
- `experiments/k1570/README.md`

## Lookahead

PASS.

- FRED CRE delinquency is not used on the observation date. Quarterly observations are mapped to daily only at quarter-end plus 50 calendar days in `fred_quarterly_release_lag_to_daily()` (`k1570.py:157-172`).
- All predictive signals are explicitly shifted once: `df[f"{sig}_lag1"] = raw_signals[sig].shift(1)` (`k1570.py:358-360`).
- Market controls are lagged (`spy_log_rv21_lag1`, `vix_z_lag1`, `credit_spread_stress_lag1`) (`k1570.py:362-367`).
- Target own RV controls are lagged (`k1570.py:371-372`).
- Forward labels use `ret.shift(-1).rolling(H).shift(-(H-1))`, which aligns the label at date `t` to returns `[t+1, t+H]` (`k1570.py:213-218`, `k1570.py:378-384`).

## Statistical Tests

PASS.

- Overlapping 5-day and 21-day forward labels use HAC / Newey-West with `maxlags = H` (`k1570.py:255-270`, `k1570.py:411-414`).
- Spearman diagnostics use moving-block bootstrap with `block=H`, `B=1000`, and seed 42 (`k1570.py:221-252`, `k1570.py:428-438`).
- Multiple testing is disclosed and implemented on the 96-cell primary family with both Bonferroni and Holm (`k1570.py:440-456`).
- Success threshold requires positive coefficient, Holm `p < 0.05`, and Harvey-style `|t| >= 3`, avoiding ordinary 1.96 overclaim (`k1570.py:451-456`).

## Numerical / Interpretation Checks

PASS after one correction.

- The first run exposed an event-study reporting issue: the ratio field divided log means. This was corrected to report `exp(log RV variance)` mean ratios while retaining bootstrap CI on log-RV mean differences (`k1570.py:283-317`).
- The primary result is narrow: 2/96 primary cells survive, both `CMBS` 5-day forward RV. No KRE/REIT/office-basket primary cell survives Holm + Harvey.
- README correctly labels the empirical verdict as `WEAK_PARTIAL` and does not claim broad CRE-to-bank/REIT predictability.

## Residual Risks

- `DRCRELEXFACBS` is quarterly and slow; the release-lag rule is conservative but coarse.
- Office REIT market stress is a public price proxy, not direct office-loan refinancing pressure.
- `CMBS` ETF RV is not the same as conduit CMBS spread or loan-level refinancing risk.
- The Spearman bootstrap uses precomputed full-sample ranks for speed; it is a diagnostic only, not the primary inference path.

## Verdict

`PASS_WITH_WEAK_PARTIAL_RESULT`.

The code is lookahead-safe and the statistical framing is honest. The evidence supports only a narrow public-market finding: office/combined CRE pressure leads `CMBS` 5-day forward RV after controls. It does not support a broad claim that the office-CRE refinancing wall predicts regional-bank or REIT volatility.
