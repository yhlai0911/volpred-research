# K1511 Codex Review

Date: 2026-06-16
Reviewer: codex-cli gpt-5.4
Verdict: CONDITIONAL_PASS

## Scope

Task `k1511_codex_review_followup` asked for source-level review before knowledge.json entry:

1. Strict lag / no lookahead
2. HAC Newey-West implementation
3. Whether N=144 can detect the EFM +40bp/month reference effect
4. TWSE fetch retry/backoff logic

## Findings

### 1. Lookahead: PASS

`k1511.py` constructs `ret_next = ret_log.shift(-1)` and tests month-t signals against t+1 month 0050 log return. The target is forward-looking, while signal variables use month-t foreign net flow and month-end margin-balance change. No same-month return is used as the dependent variable.

### 2. HAC Newey-West: PASS

The focus dummy regression uses `sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": 3})`. For monthly N=144 data, maxlags=3 is reasonable as a PoC convention and close to T^(1/4). It is not a full sensitivity grid, but it is not a bug.

### 3. Power / sample size: CONDITIONAL

The original README wording implied the PoC was powered for ~50bp/month medium effects. That was too strong. With N_focus=39 and N_other=105, the estimated standard error of the focus-minus-other mean difference is about 108bp/month. Approximate two-sided power is only 6.6% for +40bp/month and 7.5% for +50bp/month; an 80% power two-sided test needs about 303bp/month.

Therefore K1511 may report "not detected / no statistically significant difference" and the point estimate (−20.6bp), but it must not claim that Taiwan 0050 rejects an EFM-scale +40bp effect. The 95% CI [−232bp, +191bp] includes +40bp.

### 4. Fetch retry/backoff: PASS

`fetch_monthly_inst_flow()` retries each TWSE BFI82U month up to 5 times with exponential backoff and a one-second inter-request pause. This directly addresses the earlier small-N fetch failure documented in the README. The cached rerun produces N=144 over 2014-03 to 2026-04.

## Required Patch Applied

- Added `power_analysis` to `k1511_results.json`.
- Updated `README.md` to state `NULL (underpowered for EFM +40bp)`.
- Reworded conclusion from "does not replicate / direction opposite" to "not detected; cannot reject +40bp".

## Knowledge Gate

Allowed knowledge entry wording:

> K1511 finds no statistically significant next-month 0050 return difference after foreign-sell / margin-buy months (point estimate −20.6bp, NW t=−0.22, p=0.83), but the monthly PoC is underpowered for EFM-scale +40bp effects (approx power 6.6%, CI includes +40bp). Treat as an underpowered null / no-detection result, not evidence that the EFM effect is absent in Taiwan.
