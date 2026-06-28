# K1555 Codex Review

- Review date: 2026-06-28
- Reviewer: Codex
- Verdict: `CONDITIONAL_PASS_WITH_STRONG_CAVEATS`

## Scope

Reviewed `experiments/k1555/k1555.py`, `k1555_results.json`, data snapshots,
event calendar, plot output, and README.

## Checks

- Required package is present: `README.md`, `k1555.py`, and
  `k1555_results.json`; chart and data snapshots are under
  `experiments/k1555/`.
- Seed is fixed at 42.
- Event timing is explicit: raw tariff calendar events are mapped to trading
  days, then applied with `event_abs_signal = raw_event_abs.shift(1)`.
- Forward targets start on the applied signal date.
- Abnormal z-score baselines are built from trailing realized windows only; the
  code does not roll over forward target windows.
- GDELT is not silently used or imputed. The blocked headline-intensity source is
  recorded in `data.blocked_sources`.
- Event count is small, and no target clears t >= 3. The result is therefore not
  promoted beyond a conditional public-proxy diagnostic.

## Verification Commands

```bash
uv run python experiments/k1555/k1555.py
uv run python -m compileall experiments/k1555/k1555.py
uv run python scripts/lookahead_audit.py --json | jq '.findings["experiments/k1555/k1555.py"] // "no finding for K1555"'
```

The targeted lookahead audit returned `"no finding for K1555"`. The broader repo
strict audit has unrelated historical findings and is not a K1555 blocker.

## Findings

No blocking source issue found.

Limitations:

- The event calendar is hand-curated and sparse.
- The strongest evidence is USD drawdown, not the full EM/commodity spillover
  chain.
- The 2026-02-23 event is sourced from a market-news live report, not the same
  official White House/USTR event stream as the 2025 entries.
- ETF proxies are noisy: `CEW`, `EMLC`, and `EEM` mix currency, rates, credit,
  and equity-risk channels.
- This does not write `storage/memory/knowledge.json`; promotion should go
  through the canonical writer/gate.
