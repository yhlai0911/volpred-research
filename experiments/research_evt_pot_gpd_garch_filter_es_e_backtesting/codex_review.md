# Codex Review

Verdict: `CONDITIONAL_PASS`

Scope reviewed:

- GJR-GARCH filter uses `arch_model(..., mean="Constant", vol="GARCH", p=1, o=1, q=1)` on percentage returns.
- Forecast at date `t` fits on `y.iloc[:pos]` only and advances variance with `r[t-1]`; no same-day return enters VaR/ES.
- Student-t VaR/ES uses the unit-variance scale `sqrt((nu-2)/nu)`.
- FHS and EVT-GPD use standardized residuals from the training window only.
- POT/GPD loss-tail formula uses `u + beta/xi * ((p_u/alpha)^xi - 1)` and ES `(VaR_loss + beta - xi*u)/(1-xi)`.
- ES e-backtesting follows the public Wang-Wang-Ziegel/Zhao R reference: positive loss convention, `ep_ES=max(L-VaR,0)/((1-p)*(ES-VaR))`, 250-day GREE/GREL/GREM process.
- Results JSON is atomically written and parse-checked.

No correctness bug found that would flip the main conclusion.

Important limitations:

- This is a two-asset daily adjusted-close diagnostic, not a full regulatory portfolio implementation.
- GPD threshold is fixed at 10%; no threshold-sensitivity grid yet.
- Annual expanding refit differs from strict 250-day rolling Basel estimation.
- Verdict must stay "competitive, not dominant": EVT-GPD wins SPY cells, but Student-t wins HYG cells under FZ loss.
