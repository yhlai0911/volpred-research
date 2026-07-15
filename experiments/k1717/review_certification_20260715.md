# K1717 final independent review certification

- Verdict: **PASS**
- Reviewer: Codex CLI v0.144.1 / `gpt-5.6-sol` / effort=`ultra`
- Review mode: independent, read-only; formal estimation was not rerun
- Reviewed at: 2026-07-15T23:55:51+08:00
- Reviewed HEAD: `49f4c5dcf56296949585e5e09c75ff8ece71d7ee`
- Frozen claim hashes: recorded in `review_verdict.json`; all 5 matched
- Data snapshot SHA-256: `c8eb6b30189bbe7d74b2139f2e7320be40b7ebdb9ce7b5ae7fcab664aff64fca`; matched `k1717_results.json`

## Scope and finding

The reviewer checked the frozen script, README, result JSON, both charts, verdict template, and data snapshot. The read-only audit covered strict backward as-of timing, the 16 vendor-calendar gap exclusions, HAR lag state, expanding OOS construction, QLIKE and canonical HAC DM inference, Holm/Harvey information gate, strategy skip, GARCH boundary diagnostics, strict JSON, and cross-artifact consistency.

No CRITICAL or HIGH defect was found. The reported NULL/MIXED conclusion is supported: India VIX has lower mean OOS QLIKE in both model families, but the GARCH-X primary canonical DM statistic is `-2.86796`, which does not satisfy the pre-registered `t < -3` threshold. Skipping the VT simulation is therefore correct.

## Independent corroboration

A separate fresh-context Codex audit also returned PASS on the same hashes. It independently recomputed the 16 calendar-gap targets from the snapshot, confirmed strict-as-of source dates, verified the snapshot/JSON/README hashes, and found no CRITICAL/HIGH blocker.
