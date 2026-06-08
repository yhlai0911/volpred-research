# Backlog Task Resolution — `research_proxy_reliance_control_in_conformal_var`

Date: 2026-06-08  
Resolver: Codex CLI

## Verdict

This pending backlog task is already substantively covered by existing experiment `K1026`.

## Coverage mapping

Backlog task:
- `research_proxy_reliance_control_in_conformal_var`
- Source prompt: "Proxy-Reliance Control in Conformal VaR — arXiv:2603.22569 (2026)"

Existing experiment:
- [README.md](/Users/yhlai0911/Desktop/volpred-research/experiments/k1026/README.md:1)
- [k1026.py](/Users/yhlai0911/Desktop/volpred-research/experiments/k1026/k1026.py:1)
- [k1026_results.json](/Users/yhlai0911/Desktop/volpred-research/experiments/k1026/k1026_results.json:1)

`K1026` explicitly implements conformal VaR using rolling empirical quantiles of standardized residuals, contrasts it against parametric GJR/A4f Student-t VaR, and evaluates with:
- Kupiec UC
- Christoffersen CC
- DQ
- Basel traffic light
- Acerbi-Szekely ES backtests
- conditional calibration by VIX regime

That is already the core experimental surface implied by the backlog item.

## Key results already available

- Data: SPY, 2005-01-03 to 2026-04-09, OOS from 2013-01-02.
- Reproducibility metadata: `seed=42`, `window=2000`, `refit_every=63`, `cal_window=252`.
- Parametric baseline quality: A4f volatility forecast QLIKE `-8.6439` vs GJR `-8.5367`.
- 2.5% VaR:
  - `M4 Conformal-GJR`: violation rate `2.556%`, scorecard `6/6`
  - `M5 Conformal-A4f`: violation rate `2.71%`, scorecard `6/6`
  - Both materially improve calibration relative to parametric alternatives while paying a modest sharpness cost.
- Overall pass rates from README:
  - `M4 Conformal-GJR`: `11/12`
  - `M5 Conformal-A4f`: `11/12`
  - `M3 A4f+t(8)`: `10/12`

## Why this closes the backlog item

The backlog item asks whether proxy-reliance controlled conformal VaR is worth testing in our framework. `K1026` already does that on the correct axis:
- nonparametric conformal calibration
- comparison to parametric VaR
- proper backtesting, not heuristic coverage anecdotes
- direct integration with our existing A4f / GJR volatility stack

So this is not an unaddressed research gap. It is a duplicate backlog entry that should resolve to the existing `K1026` artifact set.

## Remaining gap, if any

The only meaningful next step is not "do this topic", but "extend K1026":
- cross-asset validation
- adaptive / weighted conformal windows
- tighter linkage to the exact 2026 paper specification if a paper-level replication is desired

Those are follow-on tasks, not reasons to keep this backlog item open.
