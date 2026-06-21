# K1359 Codex Source Review

Review date: 2026-06-21

Reviewer: Codex CLI (`codex-vscode`)

Verdict: **CONDITIONAL_PASS**

The code supports the reported `RISK_SIGNAL_ONLY_NULL_PREMIUM` conclusion. I found no source-level blocker that would reverse the headline null-return / risk-signal interpretation.

## Checks

| Area | Status | Evidence |
|---|---|---|
| Three-piece experiment standard | PASS | `README.md`, `K1359.py`, `K1359_results.json` exist. |
| Data provenance | PASS | Results JSON records yfinance adjusted close source, ticker coverage, 2007-05-31 to 2026-05-31 sample, 229 months. |
| Lookahead | PASS | `K1359.py:260` explicitly uses `signal = feature.shift(1)` after month-end feature construction. Current month outcomes are read only after that lag. |
| Rolling window timing | PASS | Daily estimators use trailing pandas rolling windows before monthly resampling (`K1359.py:207-218`, `K1359.py:253-260`). |
| Same-month return bias | PASS | Feature at month-end `t-1` predicts month `t`; no same-month signal is multiplied by same-month return. |
| Randomness | PASS | `SEED = 42`; bootstrap uses `np.random.default_rng(SEED)` and 1000 reps (`K1359.py:46`, `K1359.py:400-415`). |
| Inference unit | PASS | Primary t-tests are monthly high-minus-low spreads or monthly Fama-MacBeth slopes, not pooled ticker-month observations (`K1359.py:356-397`). This avoids the K1355 pooled cross-asset false-precision issue. |
| Formal tests | PASS | Newey-West HAC mean tests with lag 3 and block bootstrap CIs are in JSON (`K1359.py:299-337`). |
| Claim strength | PASS | README does not claim a tradable premium; it states return premium fails and risk signal remains. |

## Numeric Cross-Check

Headline output from rerun:

```json
{
  "experiment_id": "K1359",
  "verdict": "RISK_SIGNAL_ONLY_NULL_PREMIUM",
  "period": ["2007-05-31", "2026-05-31"],
  "n_months": 229,
  "return_pass_estimators": [],
  "risk_signal_estimators": [
    "bad_winsor_skew",
    "max_loss_gain_gap",
    "semivar_log_ratio",
    "tail_mean_gap"
  ]
}
```

Return-spread HAC t-stat range is `[-1.01, +0.51]`, far below the Harvey `|t| >= 3` discovery bar. RV / left-tail t-stats are positive and often near or above 3, matching the risk-signal-only verdict.

## Caveats

- `CONDITIONAL_PASS`, not full PASS, because the universe has only 9 ETFs and high/low legs contain 2-3 names per month.
- K1359 cannot adjudicate option-implied skew risk premium literature; it only rejects this yfinance returns-only proxy.
- No trading-cost model is included because the experiment is a signal test, not a strategy launch candidate.
- HAC lag 3 is reasonable for monthly spreads, but sensitivity to lag 6/12 is not included in v1.

## Required Interpretation

Allowed:

> ETF realized-return tail-asymmetry estimators flag higher next-month volatility / left-tail exposure, but they do not deliver a robust next-month return premium in this 2007-2026 nine-ETF test.

Not allowed:

> Tail-asymmetry earns a tradable premium.

Not allowed:

> Option-implied skew literature is false.
