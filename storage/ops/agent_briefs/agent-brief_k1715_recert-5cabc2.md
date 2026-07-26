# K1715 re-certification (bounded diff review)

**Model**: claude-opus-4-8 / high (per model_router)

## Context
K1715 (score-driven GAS/DCS vs GARCH for joint VaR+ES on SPY) already earned a
Codex PASS verdict (`experiments/K1715/review_verdict.json`, reviewer Codex
gpt-5.6-sol/xhigh, reviewed_commit 823279d0, blocking_defects=[]) pinning
`K1715.py` sha256 = `98941ea0dba5fcace9d888a5b2cbf13fe83541a894f7c5ce0d549ad136a75fce`.

The main-thread collect step then added the missing reproducibility artifacts so the
experiment can pass the merge artifact gate (all other experiments use
network=deny + frozen snapshot):
- `K1715_source_snapshot.csv` (sha256 `d5dae218deed40ea38969fb295c72a84f9e3711a6bf2837ea473bf7093174fec`) — frozen SPY auto-adjusted close window.
- `reproduce_spec.json` — network=deny, seed=42, snapshot input, tol 1e-6/1e-8 with a reason.
- One code change in `K1715.py`: `load_returns()` now reads the snapshot CSV when present
  (download-and-write fallback, mirroring the k1719 `load_or_download_snapshot` convention),
  and a `SNAPSHOT` constant was added. **No statistical / model / evaluation logic changed.**

This edit moved `K1715.py` to sha256 `11953fcd8daf9a644a516c0b4cded2aab437ed920bd0a3e7670f88c882facb25`,
which correctly de-certifies the experiment (the cert gate is byte-exact). Per the gate
remedy, the new bytes must be re-reviewed by Codex — a hand-edited verdict is forbidden.

## Your task (bounded — this is NOT a fresh full review)
Work in this worktree cwd. Use `codex exec` (codex-cli, ChatGPT auth) for the actual
review judgement, exactly as the original adjudication did.

1. `git -C . diff 823279d09 -- experiments/K1715/K1715.py` (or diff reviewed sha vs current)
   to isolate the exact change. Confirm the ONLY functional change is the snapshot
   data-loader in `load_returns()` + the `SNAPSHOT` constant, and that it is
   **behavior-preserving**: when the snapshot equals the live-fetched data, the returns
   series is identical, so all downstream results are unchanged.
2. Verify the snapshot actually reproduces the archived data window WITHOUT a full re-run:
   load `K1715_source_snapshot.csv`, compute `100*log(close/close.shift(1))`, and confirm
   n_ret = 6678, first return date 2000-01-04, last 2026-07-24 — matching
   `K1715_results.json` `data` (n_total=6678, end=2026-07-24). Report the numbers.
3. Have Codex read the FROZEN current K1715.py and rule on whether the change is safe
   (behavior-preserving, no logic drift, results still valid). Do NOT demand a full
   multistart-MLE + bootstrap re-run — that is heavy compute and not required to certify
   a data-loader diff; the snapshot-window check in step 2 is the evidence.
4. If Codex confirms safe → regenerate the certification skeleton and fill it from the
   Codex verdict:
   `uv run python scripts/experiment_gates.py verdict-template --path experiments/K1715 --out experiments/K1715/review_verdict.json`
   then write verdict=PASS, reviewer=<Codex model/effort + session>, reviewed_at, review_artifact
   pointing at a saved Codex re-review log (e.g. `experiments/K1715/codex_recert.md`), and
   `reviewed_sha256` covering the FULL claim surface AT THIS COMMIT: K1715.py (must equal
   `11953fcd8daf9a644a516c0b4cded2aab437ed920bd0a3e7670f88c882facb25`), the 3 figures,
   K1715_results.json, README.md, build_readme.py. Commit the updated verdict + codex log
   in this worktree branch.
5. If Codex finds the change is NOT behavior-preserving (e.g. snapshot alters returns) →
   do NOT certify; write the defect into `experiments/K1715/codex_recert.md`, leave the
   verdict FAILing, and say so in your result — the main thread will 3-strike it.

## Result artifact
`experiments/K1715/review_verdict.json` updated so its `reviewed_sha256["K1715.py"]`
== `11953fcd8daf9a644a516c0b4cded2aab437ed920bd0a3e7670f88c882facb25` and verdict=PASS
(or an explicit FAIL with the defect recorded).
