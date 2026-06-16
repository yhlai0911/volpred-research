# K1520 Codex Review

- **Reviewer**: Codex
- **Date**: 2026-06-17
- **Verdict**: `CONDITIONAL_PASS`

## Scope

Reviewed `experiments/k1520/k1520.py` and `k1520_results.json` for lookahead, baseline fairness, DM/QLIKE interpretation, and claim strength.

## Findings

1. **Lookahead**: PASS. Features at forecast origin `t` use SPY returns through `t`; VIX is explicitly shifted by one day; training rows require `target_date <= current_date`, which prevents forward-label leakage.
2. **Initial baseline issue caught and fixed**: The first run compared VIX-using analog retrieval against pure HAR only and produced an apparent PASS. This was unfair because analog retrieval and regime labels used `VIX_lag1`. The script was corrected to add `HAR+VIX` as the primary baseline.
3. **Final inference**: PASS. Against pure HAR, combo analog variants can look strong, but against HAR+VIX no analog / regime / combo variant passes the positive-improvement + `|t|>3` + BH gate.
4. **Claim strength**: CONDITIONAL PASS. The experiment supports a narrow NULL: regime-aware retrieval does not beat HAR+VIX on daily SPY r². It does not test a frozen external LLM API.
5. **Overclaim guard**: README correctly frames K1520 as a reproducible ICL-surrogate test, not evidence about all LLMs.

## Required Wording

Any downstream article must say: "regime-aware analog retrieval beats pure HAR but does not beat HAR+VIX." It must not say "LLMs fail" or "in-context learning is useless" without a frozen LLM benchmark.
