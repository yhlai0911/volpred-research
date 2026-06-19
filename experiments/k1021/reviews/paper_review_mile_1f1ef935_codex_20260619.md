# K1021 / mile_1f1ef935 Codex 24h Publication Review

- Article: `mile_1f1ef935` - "同一個模型，只是把尾巴想厚一點，風險警報就差很多"
- Task: `paper_review_mile_1f1ef935`
- Source experiment: `experiments/k1021/`
- Reviewer: Codex
- Review date: 2026-06-19
- Verdict: **PASS**

## Bottom Line

The production article is supported by the K1021 source artifacts. The main numeric claims match `experiments/k1021/k1021_results.json`, and the implementation uses one-step-ahead information for the OOS variance and VaR forecasts.

No article patch, retraction, or results change is required.

## Claim-Evidence Match

| Article claim | Source check | Status |
|---|---:|---|
| OOS period is 2019-01-02 to 2026-04-09 with 1,827 OOS trading days | `results.SPY.oos_period` and `results.QQQ.oos_period` both report `start=2019-01-02`, `end=2026-04-09`, `n=1827` | PASS |
| Normal model underestimates 1% tail risk: SPY violation rate 1.64%, QQQ 2.13% | `A4f-VIX9D-N.var_es.0.01.violation_rate` is 1.64 for SPY and 2.13 for QQQ | PASS |
| QQQ Normal 1% result is red | `A4f-VIX9D-N.var_es.0.01.Basel` for QQQ is `RED` | PASS |
| Joint Student-t estimate is thicker-tailed but still not enough for QQQ 1% | QQQ `A4f-VIX9D-t-joint` has mean df 8.625, 1% violation rate 1.70, scorecard `1/4`, Basel `YELLOW` | PASS |
| Fixed df=5 is the cleanest conservative VaR choice | Fixed df=5 has `4/4`, `6/6`, `4/4` scorecards at 1%, 2.5%, 5% for both SPY and QQQ | PASS |
| General QLIKE performance does not materially change the article's conclusion | QLIKE values are close across model variants. SPY fixed5 vs fixed8 is statistically different in the stored DM table, but the article does not claim all QLIKE differences are statistically insignificant; it uses QLIKE only as a general-performance contrast to VaR calibration. | PASS with caveat |

## Lookahead / Timing Audit

No lookahead defect was found in the OOS forecast loop.

- At each OOS index `t`, the refit sample is `returns[s:t]`, excluding the target return at `t`.
- The forecast uses `vix9d2[t-1]` and `returns[t-1]` to produce `forecasts[t]`.
- Evaluation then compares that forecast against `returns[t]` through `returns_oos` and `h_oos`.

This satisfies the project convention: signal and conditioning information from `t-1`, realized return at `t`.

The generic `scripts/lookahead_audit.py` scan is not targeted at this volatility-forecast structure, but it also does not flag `experiments/k1021/k1021.py` as part of its weights-times-returns pattern family.

## DM / Harvey / Statistical Claims

The article does not overclaim DM or Harvey significance. K1021 stores the DM comparisons and uses Harvey `abs(t)>3.0` only inside the experiment-level results. The public article's stronger claims are VaR calibration claims, which are supported by the stored Kupiec, Christoffersen, DQ, ES, and scorecard outputs.

One wording caveat: the experiment's `Basel` flag is a simplified Basel-style traffic-light score based on violation-count thresholds in `var_es_evaluation()`. The article's reader-facing wording is acceptable because it does not present a formal capital multiplier calculation, but future technical writeups should prefer "Basel-style" if discussing the exact implementation.

## Reproducibility / Provenance Caveat

K1021 has the required experiment triad:

- `experiments/k1021/README.md`
- `experiments/k1021/k1021.py`
- `experiments/k1021/k1021_results.json`

The experiment relies on yfinance downloads and does not pin local raw price snapshots. I did not rerun the full MLE pipeline during this review because a fresh vendor pull could change the comparison target. This review verifies the committed source/results/article consistency rather than regenerating all model estimates.

## Verification

- `uv run python -m py_compile experiments/k1021/k1021.py` passed.
- Deterministic JSON checks confirmed the article's SPY/QQQ 1% Normal violation rates, QQQ red flag, QQQ joint-t yellow flag, fixed-df5 scorecards, and OOS period.
- `uv run python scripts/lookahead_audit.py --json` reported `k1021_present: false`, meaning K1021 is outside the known weights-times-returns lookahead pattern family.

## Verdict

`PASS`.

The public article can remain published. No source or content correction is required.
