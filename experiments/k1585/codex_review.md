# Codex Review - K1585

## Verdict

**CONDITIONAL_PASS** for the experiment artifact. **Do not promote as a positive forecast finding.**

The script is reproducible, uses a fixed seed, builds the required lagged signals explicitly, and protects the expanding OOS forecast against overlapping-target leakage. The empirical conclusion must stay at `WEAK_RAW_ONLY`: raw regime diagnostics are suggestive, but the primary VIX+SPF OOS QLIKE comparison fails.

## Checks

- Required files present: `README.md`, `k1585.py`, `k1585_results.json`.
- Data sources are identified: local SPY/VIX daily CSV and Philadelphia Fed SPF D2 workbook.
- Lookahead guard is explicit:
  - `vix_close.shift(1)`.
  - `spf_disagreement_raw.shift(1)`.
  - SPF availability is conservatively lagged by quarter end + 45 calendar days.
  - OOS training uses only rows whose forward-RV targets are fully realized before the forecast origin.
- Randomness is fixed with `SEED = 42`.
- Formal comparison uses QLIKE and DM tests rather than only regime charts.

## Findings

### F1 - Claim strength must remain capped

The raw 21-day regime contrast is positive:

- High VIX / low SPF disagreement mean RV21: `0.007739`.
- High VIX / high SPF disagreement mean RV21: `0.004946`.
- Difference: `0.002793`.
- Moving-block bootstrap one-sided p-value: `0.044`.

But the 95% bootstrap interval is `[-0.000375, 0.006391]`, so the two-sided interval crosses zero. Tail evidence is also weak: tail event difference `0.0554`, one-sided p-value `0.1875`.

### F2 - Incremental forecast gate fails

The primary OOS QLIKE test rejects any positive forecast claim:

| Horizon | Baseline QLIKE | VIX+SPF QLIKE | Improvement | DM t |
|---|---:|---:|---:|---:|
| 5d | 0.403495 | 0.406376 | -0.714% | 0.874 |
| 21d | 0.335947 | 0.346609 | -3.174% | 1.809 |

The augmented model is worse on QLIKE at both horizons. This means K1585 does not challenge the VIX-sufficient prior as a forecasting result.

### F3 - Measurement limitations are material

The SPF workbook has quarterly survey labels but not exact release timestamps. The script uses a conservative quarter-end-plus-45-days availability lag. That prevents lookahead but may blur the timing of survey information. The experiment also uses VIX as the uncertainty level, not JLN, and uses SPF macro forecast dispersion rather than the consumer disagreement measure in Gambetti et al.

## Recommendation

Keep K1585 as a weak/null diagnostic. It is acceptable as an experiment artifact, but it should not be written into the knowledge base as a positive finding unless a later exact-release-date or JLN-level replication passes the OOS QLIKE/DM gate.
