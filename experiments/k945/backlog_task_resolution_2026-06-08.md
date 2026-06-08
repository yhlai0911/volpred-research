# Backlog Task Resolution — `research_quadratic_hedging_under_garch`

Date: 2026-06-08  
Resolver: Codex CLI

## Verdict

This backlog item is already directly covered by existing experiment `K945`.

## Coverage mapping

Backlog task:
- `research_quadratic_hedging_under_garch`

Existing experiment:
- [README.md](/Users/yhlai0911/Desktop/volpred-research/experiments/k945/README.md:1)
- [k945.py](/Users/yhlai0911/Desktop/volpred-research/experiments/k945/k945.py:1)
- [k945_results.json](/Users/yhlai0911/Desktop/volpred-research/experiments/k945/k945_results.json:1)

The match is exact: `K945` is titled `Quadratic vs Minimum-Variance Hedging under GARCH`.

## What K945 already answers

- Core question: whether quadratic hedging (QH) meaningfully improves on minimum-variance hedging (MV) under GARCH-style conditional dynamics
- Asset pairs:
  - `SPY-QQQ`
  - `GLD-SLV`
  - `SPY-IWM`
- OOS period: `2016-01-01` to `2025-12-31`
- Methods:
  - Static OLS
  - Rolling OLS
  - MV-GARCH
  - QH-GARCH
  - Naive 1:1
- Extensions already included:
  - monthly-frequency analysis
  - high-vol vs low-vol regime analysis
  - HE / VaR / ES reduction comparison
  - DM tests with Harvey threshold

## Main result already recorded

`K945` concludes:
- daily-frequency `QH ≈ MV`
- QH-MV hedge ratio correlation is `> 0.9999` across all pairs
- mean absolute hedge-ratio difference is `< 0.001`
- no pair shows Harvey-significant DM advantage for QH over MV
- monthly differences become measurable but still economically negligible (`< 0.15%` objective improvement)

So the repo already contains the exact null answer this backlog item asks for.

## Why this closes the backlog item

This is not a thematic overlap or a broad literature-family match. It is the same question, already implemented and documented as a completed experiment. Keeping `research_quadratic_hedging_under_garch` in pending state would duplicate `K945` rather than create new knowledge.

## Remaining gap, if any

If the team wants to reopen this line, the next meaningful step is narrower:
- replace ETF proxies with actual spot-futures data
- estimate a fuller conditional covariance process instead of the simplified rolling proxy
- test whether rare extreme regimes make the QH correction economically relevant

Those are follow-on extensions, not reasons to keep this generic backlog item open.
