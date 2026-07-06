# paper2_tsmc_gamma_zeromean_sens

**Date**: 2026-07-06
**Paper**: taiwan-vt (Paper 2), body_v3 disclosure fix
**Task**: `paper2_taiwan_vt_body_v3_se_method_and_zero_mean_disclosure`

## Motivation

The v3 canonical body reports TSMC (2330.TW) leverage `gamma = 0.052 (t = 3.98)` from a
**Constant-mean** GJR-GARCH(1,1) MLE (K892). A reviewer may ask whether the constant-mean spec
was selected because it makes TSMC significant. The legacy body_v2 footnote hedged with a
"zero-mean spec gives gamma = 0.039 / t = 0.87 (insignificant)" figure — but the gamma
unification audit
(`paper/taiwan-vt/review_history/gate_fix_v1/gamma_unification_proposal.md:45`) found that
number **UNTRACEABLE**: *"no single spec reproduces (0.039, 0.87)."* Reintroducing it would
violate research honesty.

This experiment re-estimates the zero-mean spec on the **exact K892 canonical sample/pipeline**
so the mean-spec sensitivity disclosure carries real provenance.

## Method

- Ticker 2330.TW, download window `start=2000-01-01, end=2026-04-05`, `auto_adjust=True`
  (adjusted close) — reproduces K892 canonical `n = 6525` exactly.
- Returns = `Close.pct_change() * 100`.
- GJR-GARCH(1,1), Normal innovations, arch default robust (Bollerslev–Wooldridge) covariance.
- Two mean specs: `Constant` (canonical) and `Zero`.
- arch MLE is deterministic (analytic optimizer) → no random seed required; reproducibility
  pinned by the fixed download window.
- Not a forecasting/backtest task → no signal lag / lookahead applicable (in-sample parameter
  estimation only).

## Result

| Mean spec | gamma | t(gamma) | significant | converged |
|-----------|-------|----------|-------------|-----------|
| Constant (canonical) | 0.0525 | 3.98 | yes | flag=0 |
| Zero | 0.0593 | 4.25 | yes | flag=0 |

**Conclusion**: TSMC's asymmetric-volatility (leverage) parameter is **significant under both
mean specifications** (t ≈ 3.98–4.25), and the zero-mean estimate is if anything *stronger*.
The finding is **robust to mean specification** — it was NOT produced by cherry-picking the
constant-mean spec. The legacy untraceable "0.039 / t = 0.87" figure is refuted and must not
be used.

## Files

- `paper2_tsmc_gamma_zeromean_sens.py` — estimation script
- `paper2_tsmc_gamma_zeromean_sens_results.json` — full parameter output for both specs

## Reviewer

Codex CLI review 2026-07-06 (see task completion note).
