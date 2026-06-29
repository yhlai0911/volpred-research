# K1569 Codex Source-Level Review

**Reviewer**: Codex CLI interactive session  
**Date**: 2026-06-29  
**Verdict**: `CONDITIONAL_PASS` for artifact integrity; research verdict remains `NULL`.

## A. Lookahead

- A1 signal lag: **PASS**. Rolling z-score baselines use shifted mean/std at `k1569.py:146-151`; transition, credit, and interaction signals are explicitly lagged at `k1569.py:454-459`; regressions consume `*_lag1` at `k1569.py:648-655`.
- A2 XBRL availability: **PASS**. Annual CompanyFacts observations are filtered to 10-K/FY rows at `k1569.py:235-268`, then made available only after filing date + 1 calendar day at `k1569.py:307-310`, and aligned to the first subsequent ETF trading date at `k1569.py:380-390`.
- A3 forward labels: **PASS**. Forward RV, downside variance, return, and volume targets are built with `shift(-i)` for `i=1..H` at `k1569.py:475-493`, so the realized window is strictly `[t+1,t+H]`.
- A4 primary grouping: **PASS with proxy caveat**. High/low groups use only daily available XBRL scores at `k1569.py:523-553`; this avoids future target data, but representative company baskets are current/manual proxies, not historical ETF constituents.

## B. Statistical Tests

- B1 HAC: **PASS**. Controlled OLS uses statsmodels HAC with `maxlags=horizon` at `k1569.py:556-573`.
- B2 Spearman CI: **PASS**. Moving-block bootstrap uses block=`H`, `B=1000`, seed=42 at `k1569.py:576-605`.
- B3 pooled inference: **PASS**. Primary inference is a date-level high-minus-low series, not stacked sector-day rows (`k1569.py:523-553`, `k1569.py:639-666`).
- B4 duplicate-control bug: **FIXED / PASS**. Initial implementation included `credit_stress_lag1` as a control even when the tested signal was `credit_stress`. The final code removes that duplicate control for `credit_stress` tests at `k1569.py:648-652`; results were rerun after the fix.
- B5 downside log caveat: **WARN**. Log downside variance uses `log(var + 1e-12)` at `k1569.py:481-484`; short windows with no negative returns create a lower point mass. This does not affect the NULL verdict but limits interpretation of downside cells.

## C. Multiple Testing

- C1 primary family disclosure: **PASS**. Primary family is 18 controlled-HAC tests, declared in results and built from 2 horizons x 3 outcomes x 3 signals at `k1569.py:847`.
- C2 correction implementation: **PASS**. Bonferroni and Holm-Bonferroni are computed over all primary rows at `k1569.py:608-636`.
- C3 significant cells: **PASS**. Two family-corrected survivors exist, but both have negative coefficients (`HL|5d|log_rv|transition_shock`, `HL|21d|log_rv|transition_shock`). The verdict logic counts only positive survivors for the proposed legacy-fragility claim at `k1569.py:689-719`.

## D. Verdict Honesty

- D1 claim strength: **PASS**. README and JSON state the design is a public proxy, not true stranded assets, transformation spending, or private credit-spread evidence.
- D2 numbers vs verdict: **PASS**. No positive raw-significant high-minus-low response exists; the corrected significant evidence is reversed. `NULL` is the correct verdict for the proposed mechanism.
- D3 publication safety: **PASS**. A publishable claim would have to be framed as "public proxy fails / reversed for RV", not "legacy-heavy sectors are fragile after transition shocks."

## Overall

`CONDITIONAL_PASS`: source-level integrity is acceptable after the duplicate credit-control fix and rerun. The result is a proxy-limited NULL with reversed RV evidence, not support for legacy-asset overhang amplification.
