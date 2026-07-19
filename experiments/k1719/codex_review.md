# K1719 primary-path Codex review

## Verdict

PASS. The frozen claim surface at commit
`4b91e503e84b2a6327a3eb2f4961fad17f86b7ff` supports the stated MIXED
verdict. No blocking correctness, lookahead, inference, or reproducibility
defect was found.

## Scope and evidence

- Reviewed the full claim surface: `README.md`, `k1719.py`,
  `k1719_results.json`, and `k1719_qlike_improvement.png`.
- Checked the complete result JSON rather than sampling favorable targets.
- Re-ran `k1719.py` from the frozen source snapshot. The worktree remained
  clean, confirming byte-stable results and chart output.
- Re-ran `scripts/experiment_gates.py run`; all four applicable integrity
  gates passed.
- Verified the snapshot SHA-256 in the result JSON against
  `k1719_source_snapshot.csv`.
- Cross-checked the four literature references and the Diebold-Yilmaz erratum
  against publisher, NBER, or bibliographic records.

## Methodology findings

1. Lookahead control is explicit and correctly ordered. Returns and rolling
   features are computed on each market's local non-missing calendar, then
   shifted by one local session before the common-date join. Each rolling OLS
   fit ends at the observation immediately before its forecast row.
2. Baseline and ladder models use the same target, rolling window, clipping,
   and forecast origins. The incremental regressors match the rung definitions
   reported in the README and result JSON.
3. QLIKE uses the canonical actual-over-predicted direction. Raw DM is labeled
   diagnostic-only because the models are nested; the verdict instead uses the
   repository Clark-West helper on log variance.
4. Southeast-Asia inference averages adjusted losses across assets by common
   date before HAC inference, avoiding asset-day pseudo-replication.
5. The pre-registered success gate is evaluated mechanically: only two of six
   targets improve QLIKE, one target clears the Clark-West strength threshold,
   and the panel statistic does not clear it. MIXED is therefore the correct
   bounded verdict.

## Non-blocking limitations

- Daily squared returns are noisy variance proxies and cannot identify an
  intraday transmission chain across overlapping Asian sessions.
- The conservative local-session lag tests predictive association, not causal
  spillover timing.
- Zero target-return rows are excluded. There are only one to five per target
  in the frozen sample, so this is immaterial here, but a future extension
  should retain them with an explicit positive floor to avoid outcome-based
  row selection.
- The source snapshot is pinned through the result JSON, while the generated
  chart is directly certified. The README's broad use of “claim surface” does
  not change the statistical claims or the gate's byte-level certification.

