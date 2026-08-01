[新架構派發] K1739 round-4 independent review — FAIL

Reviewed on 2026-08-01 UTC in worktree branch
`k1739-slot1-ae8721c1`, whose base was
`9c8543d0d045a28fa92a3af2ee41007b487ef45f`. The claim-surface bytes are
bound by the worktree's `experiments/K1739/review_verdict.json`; the failed
queue receipt itself was not treated as evidence of success. No experiment was
rerun and no claim-surface byte was changed during this review.

## Outcome

| Axis | Verdict | Blocking findings | Worst finding |
|---|---|---:|---|
| Standards | FAIL | 2 | The README promises byte-identical offline reruns, but runtime fields and default CSV float parsing make that promise false. |
| Spec | FAIL | 4 | The mandated pooled asset-clustered inference is diagnostic-only and is absent from the adjudicated/FDR result, despite material disagreement with Driscoll–Kraay in two cells. |

Overall verdict: **FAIL — do not merge and do not promote to
`storage/memory/knowledge.json`.**

## Standards review

1. The pre-review `review_verdict.json` contained only `FILL:` placeholders.
   A file's existence is not certification; the worktree now carries a
   hash-pinned FAIL verdict that deliberately continues to block merge.
2. `README.md` says an offline rerun is byte-identical. That is not true:
   `run_utc`, `runtime_seconds`, `runtime_env`, and reproduce-spec runtime
   metadata vary across runs, and `pd.read_csv` does not request
   `float_precision="round_trip"`. The current stored code, result, input, and
   reproduce-spec hashes are internally consistent, but the defensible claim is
   tolerance-equivalent reproduction, not byte identity.

Nonblocking standards gap: the source/index timezone is not declared in the
CSV, results, diagnostics, or README.

## Spec review

1. The brief requires the pooled panel's main conclusion to use asset-clustered
   SE and requires multiplicity control over that inference. The code instead
   makes Driscoll–Kraay primary and stores asset clustering as an unadjudicated
   diagnostic. This is material: common-sample horizons 2 and 4 have stored
   cluster t-statistics 2.767 and 2.619, unlike the promoted DK path. A repair
   must explicitly reconcile the brief's asset-cluster requirement with the
   invalid small-cluster asymptotics at G=6; silently selecting one path is not
   enough.
2. Asset-level BH covers only the 24 full-sample tests. The required common-
   sample asset-level family is absent.
3. The SUPPORTED branch permits up to 20% robustness sign disagreement even
   though the brief requires any sign flip to downgrade a significant result.
   This branch is dormant for the current NULL, but it implements the wrong
   success rule.
4. The literature section misattributes multiple papers: the Han and Xu/Wang
   initials are wrong, and *Understanding Momentum and Reversal* is by Kelly,
   Moskowitz, and Pruitt (2021), not Cheng et al.; Da, Liu, and Schaumburg
   (2014) is a different paper.

Additional traceability gap: the README's CPER price examples and historical
H2 value 1.716 are not present in the current results JSON, contrary to the
brief's all-reader-facing-numbers traceability requirement.

## Checks that passed

- All six claim-surface hashes match the generated verdict template.
- Entrypoint, result, and cached-input identities match `reproduce_spec.json`.
- The equivalent-lag lookahead construction was rebound to the included daily
  prices; negative controls fail as intended.
- HAC lags are at least the forecast horizon; the stationary bootstrap uses
  whole-week blocks with B=2000, expected block length 8, and seed 42.
- Full/common primary tables, power calculations, robustness summaries,
  figures, and README headline values match the results JSON except for the
  traceability gap above.
- `experiment_gates.py run` passed its four source-integrity gates. Merge
  certification correctly remains blocked by this FAIL verdict, and no
  knowledge entry was written for a failed experiment.

## Bounded remediation

Preserve the current bytes and do not call this receipt a success. The existing
main-thread follow-up `triage_K1739_salvage_20260802` should own a fresh revision:
predeclare how DK, the six-cluster diagnostic, and bootstrap jointly adjudicate
the result; add the missing common-sample asset family and FDR; make any
robustness sign flip downgrade a positive conclusion; correct citations and
reproduction wording; move every quoted number into the result artifact; rerun
once; then conduct a new full-surface review and generate a new pinned verdict.

