# K1554 Codex Review

- Review date: 2026-06-28
- Reviewer: Codex
- Verdict: `PASS_AS_UNDERPOWERED_NULL`

## Scope

Reviewed `experiments/k1554/k1554.py`, generated `k1554_results.json`, cached
Stocktwits/yfinance data, plot output, and the experiment README.

## Checks

- Required package is present: `README.md`, `k1554.py`, and
  `k1554_results.json`; chart and data snapshots are stored under
  `experiments/k1554/`.
- Seed is fixed at 42.
- Signal timing is explicit: `raw_signal` is formed from messages and trailing
  prices through formation day `t`, then applied with
  `signal = raw_signal.shift(1)`.
- Rolling thresholds for winner, high-RV, message-count shock, and volume
  baselines all use shifted historical windows.
- A timing bug found during review was fixed before final results: the 5-day
  abnormal-volume baseline originally rolled over forward 5-day volume sums,
  which leaked future volume into the baseline. Final code uses historical
  trailing 5-day volume sums before the one-day shift.
- API coverage is not silently treated as zero: Stocktwits 429/502 responses and
  blocked historical endpoints are recorded in `stocktwits_fetch_diagnostics`
  and `data.blocked_sources`.

## Verification Commands

```bash
uv run python experiments/k1554/k1554.py
uv run python -m compileall experiments/k1554/k1554.py
uv run python scripts/lookahead_audit.py --json | jq '.findings["experiments/k1554/k1554.py"] // "no finding for K1554"'
```

The targeted lookahead audit returned `"no finding for K1554"`. The broader repo
strict audit has unrelated historical findings and is not a K1554 blocker.

## Findings

No blocking source issue remains for K1554.

Limitations:

- The result is underpowered: 22 usable events from only KOSS and KSS.
- Many high-attention names only have a few recent Stocktwits days in the public
  stream; several later fetches hit Cloudflare/Stocktwits 429 responses.
- Weekend/social-time aggregation uses UTC date and does not reconstruct exact
  market-session post timing.
- This is a feasibility test of a public proxy, not a replication of the RoF
  investor-platform network design.
