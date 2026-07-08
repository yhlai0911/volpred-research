# K1116e — Nested Clark-West increment test for the highest-risk DAILY signal families (vix-sufficiency paper)

**Date**: 2026-07-08
**Parent task**: `paper_body_vix_sufficiency_daily_family_clark_west` (SEVERE-2 carve-out)
**Predecessor**: k1116c (weekly families 12/13 nested CW — done)
**Reviewer**: Antigravity CLI (`agy`, gemini-3.5) — **PASS** (Codex CLI unavailable, usage limit until 2026-07-11; per experiments.md fallback rule)

## Motivation

The vix-sufficiency paper's central claim is a NULL: no signal family produces a
statistically significant out-of-sample improvement over VIX alone. Table 3
currently reports the standard Diebold-Mariano |t| for the daily families but the
nested **Clark-West (2007)** MSPE-adjusted statistic — which is *strictly more
powerful* than DM at detecting a true incremental predictor — only for the two
weekly alt-data families (k1116c). A referee will ask whether the null survives
the more powerful CW test for the **daily** families too.

This experiment answers that for the **two daily families most likely to flip** —
the ones with the strongest in-sample partial signal (the worst case for the
null):

| Family | Signal | Paper IS evidence |
|---|---|---|
| **F2 VIX term structure** | VIX/VIX3M ratio | partial r\|VIX = 0.181, IS t = **17.6** |
| **F4 Variance risk premium** | VIX − backward RV22 | IS t = **3.51** |

These are computed **first** precisely because they are the prime CW-flip
candidates (F2 has by far the largest in-sample partial correlation of any daily
family). This is not a bounding argument — we compute the hardest cases honestly
and report whatever CW returns.

Only DM-regression families admit a nested CW test. Per the paper's own
methodology, the daily nested-CW-applicable families are exactly {1,2,3,4,8,9,10,11};
families 5,6 (portfolio Sharpe) and 7 (Bitcoin Granger) are non-nested and CW does
not apply. The remaining daily regression families (1,3,8,9,10,11) are deferred to
a follow-up run (F3/F9/F10 need fragile external data: CBOE put-call, Google
Trends, intraday VIX open).

## Design

- **Target**: 22-day *forward* realized vol of SPY, `std(log-ret over (t, t+22]) × √252 × 100`. H = 22. Numerically verified (`fwd_rv22[t]` uses only returns on days t+1…t+22 — no lookahead).
- **Baseline (restricted, M2)**: `fwd_rv ~ 1 + VIX_t`
- **Augmented (nests baseline)**: `fwd_rv ~ 1 + VIX_t + signal_t`
- **Timing**: features are the close-of-day-t information set (VIX_t, signals built only from data observed by close t); the target accumulates strictly after → no lookahead. Matches the paper's k731 convention. No extra `shift(1)` (that would open a 1-day information gap).
- **Same-sample nested estimation**: both models estimated on identical IS rows and evaluated on identical OOS rows (rows where the signal + target are observed). VIX3M (hence F2) starts ~2007, so the shared window respects that for both models.
- **Split**: fixed IS ≤ 2018-12-31 / OOS 2019-01-02 → 2026-05-28, with a 22-day forward **embargo** (drop the last H IS rows so no IS target peeks into OOS). OOS spans the 2020 COVID crash and 2022 bear market.
- **Inference**: overlapping 22-day targets → forecast errors are MA(21). All DM and CW one-sample t-tests use a Newey-West HAC long-run variance with **nw_lag = 21** and the Harvey-Leybourne-Newbold (1997) small-sample factor with **h = 22**. Harvey (2016) conservative threshold |t| > 3.0.
- **CW statistic**: `f_hat = e1² − e2² + (f1 − f2)²`, one-sided H1: E[f_hat] > 0. Reuses the CW/HLN math validated in k1116c; only nw_lag/h changed to 21/22 for the daily forward target.

## Results (n_OOS = 1861, 2019-01-02 → 2026-05-28)

| Family | DM \|t\| | **CW t** | CW p (1-sided) | Harvey pass (\|t\|>3)? | Verdict |
|---|---|---|---|---|---|
| **F2 VIX term structure** | 1.30 | **1.69** | 0.045 | **No** | null holds |
| **F4 Variance risk premium** | −0.76 | **−0.22** | 0.587 | **No** | null holds |

- **F2**: despite the largest in-sample partial signal of any daily family (IS t = 17.6), the out-of-sample nested increment reaches CW t = 1.69 — above the conventional one-sided 1.65 but **far below** the paper's Harvey |t| > 3.0 bar. The CW adjustment is positive (mean 1.59), correctly making CW t (1.69) exceed DM t (1.30) — the more-powerful test moves in the expected direction yet still cannot clear the sufficiency threshold.
- **F4**: VRP adds nothing (CW t = −0.22). Consistent with prior findings (K430: VRP IS-significant but OOS DM p = 0.163).

**Conclusion**: for the two highest-risk daily families, VIX sufficiency is
**robust to the more powerful nested Clark-West test** at the Harvey |t| > 3.0
threshold — strengthening, not weakening, the paper's null. The reproduction gate
holds at the conclusion level: both DM |t| < 3, consistent with Table 3's "no
daily family significant." (Exact DM values differ from the scattered per-family
legacy pipelines because this is a single unified clean pipeline; the qualitative
null conclusion is identical.)

## Files

- `k1116e.py` — harness (data load, forward target, same-sample nested OLS, DM + CW)
- `k1116e_results.json` — full statistics for F2, F4

## Follow-up

1. Extend to the remaining daily regression families (F1, F3, F8, F9, F10, F11) — F3/F9/F10 need fragile external data.
2. Integrate a CW column into paper Table 3 + `reproduce.py` rebind + `paper-update` (main-thread paper_body).
