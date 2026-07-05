# Codex Review - K1640

Verdict: `CONDITIONAL_PASS_HALF_TRUE_QUALIFIED`

## Scope Reviewed

- `experiments/k1640/k1640.py`
- `experiments/k1640/k1640_results.json`
- Generated CSV and PNG outputs under `experiments/k1640/data/` and `experiments/k1640/figures/`
- Cross-check against the overlapping 30/40 cells in K1633

## Checks

- Re-ran `uv run python experiments/k1640/k1640.py`.
- Confirmed `k1640_results.json` parses with `python -m json.tool`.
- Confirmed source compiles with `python -m py_compile`.
- Confirmed output files are non-empty.
- Confirmed task-required seed is fixed at `SEED = 42`.
- Confirmed explicit lag robustness uses `signal.shift(1)`.
- Confirmed complete forward windows only: events require `entry + horizon < n`.
- Confirmed overlapping-window inference uses HAC `maxlags = horizon`.

## Findings

No blocking issue found.

K1640 correctly frames lag0 as an event-study convention rather than same-close executable trading. The lag1 robustness materially weakens the claim, which is properly reported.

The main conclusion is half true and qualified:

- VIX>30 has 50 de-clustered events; VIX>40 has 17.
- Lag0 has 7/8 positive excess-return cells.
- Strict FDR 5% leaves no individual cell.
- FDR 10% leaves VIX>30/H5, VIX>30/H60, and VIX>40/H60.
- Lag1 has no FDR 10% survivors.

The overlapping lag0 30/40 results match K1633 up to rounding, so K1640 is a focused replication rather than a conflicting new finding.

## Limitations to Preserve

- Do not claim "VIX>40 always works"; N=17 is small.
- Do not market lag0 as an immediately executable signal.
- Do not ignore the unconditional SPY drift baseline: H60 random-entry win rate is already 71.9%.
