# K1686 R2 Codex primary-path review

- Review date: 2026-07-12
- Reviewer source: Codex primary path (`codex-vscode`), with a fresh-context read-only static cross-check
- Scope: `k1686_contemporaneous_null.py`, rerun JSON, README, generated figure
- Verdict: **PASS**

## Blocking issues from R1

1. **Ambient × sign specification — CLOSED.**
   - Empirical H uses `|r_t|`, pre-shock `VIX_{t-1}`, signed `ΔVIX_t`, and the pooled non-shock denominator.
   - Same-seed null H uses the exact analogue `|r_t|`, `P_{t-1}`, signed `ΔP_t`, and the same denominator.
   - Both sides drop the first observation identically; H adds no random draw, so seeds 0..9999 remain the K897 paths.

2. **Pooled versus up-only inference — CLOSED.**
   - The script resamples complete paired rows `(|r_t|, VIX_t, VIX_{t-1}, ΔVIX_t)` with circular moving blocks.
   - Pooled, current-up, ambient-up, and `pooled-current-up` are recomputed from the identical block draw.
   - Primary block length is 20 trading days; 10/40/63-day sensitivity is stored. Each formal CI requires at least 1,000 valid replications.

## Additional correctness checks

- `NOT_EVALUABLE` has its own verdict and cannot fall through to a negative mechanism conclusion.
- The follow-up gate uses unrounded point estimates and CI endpoints; rounding is output-only.
- Current-regime and ambient-regime shock counts are separately named in JSON.
- The old D point estimate is `-0.1192`; `-0.1226` is retained only as the legacy iid-bootstrap mean.
- B/C/G are not described as well-specified while their calibration failures remain open.
- Results use temporary-file parse verification followed by atomic replacement.

## Result verification (read from JSON)

| Check | JSON value | Status |
|---|---:|---|
| H ambient-up empirical decline | `+1.0465` | matches formal rerun |
| H primary 20-day block CI | `[0.3286, 1.7625]` | excludes zero, positive |
| H block 10 / 40 / 63 CIs | `[0.3299,1.7584]` / `[0.3458,1.7610]` / `[0.3433,1.7615]` | same conclusion |
| H ambient calm / high up-shock n | `47 / 53` | adequate cells |
| H same-seed null CI / MC p | `[-0.6554,0.9887]` / `0.032673` | 9,487 valid paths |
| Paired pooled − current-up | `+0.9353`, CI `[0.3437,1.4991]` | direct test replaces invalid CI comparison |
| K897 replication mean / sd | `0.1734 / 0.2105` | unchanged |
| A mean / CI | `0.6190 / [0.0824,1.0596]` | unchanged |
| D-up empirical / null mean | `-0.1192 / 0.0904` | unchanged |

## Verification commands

- `uv run python -m py_compile experiments/k1686/k1686_contemporaneous_null.py`
- `uv run --extra dev python experiments/k1686/k1686_contemporaneous_null.py`
- targeted `jq` checks of `codex_followup_gate`, H comparisons, block sensitivities, counts, and legacy arms

The fixed follow-up rule is satisfied: the ambient fear-shock mechanism survives this K1686 gate. This does not erase the documented null-calibration limitations or establish a structural causal channel by itself.
