# K1715 — recert round 3 (bounded): certify HEAD or state exactly what still blocks

**Model**: opus / max (per model_router, task_type=experiment)

## Your job in one sentence

Codex recert round 2 returned **FAIL** on four blocking defects. All four have since been
remediated **and** the remediation is now machine-checkable. Commission an **independent
Codex review** of the current HEAD and record the verdict. If it passes, K1715 is finally
certifiable and you merge it; if not, you record precisely what blocks it — you do **not**
paper over it.

**Worktree**: `.claude/worktrees/k1715-204d556b`, branch `worktree-k1715-204d556b`.
Read `experiments/K1715/codex_recert2.md` first — it is the verdict you are answering.

## What is already established (verify, do not redo)

A prior fire (`hourly-slot-1-11618677b35f48a79c974c99c29f0f08`, 2026-07-29 04:07 CST)
mechanically closed all four round-2 defects and committed a re-runnable checker.

Re-run it as your first action:

```bash
uv run python experiments/K1715/verify_recert2_defects.py    # must exit 0, all four PASS
```

It writes `experiments/K1715/recert2_defect_closure.json`. Closure status at HEAD:

| Round-2 defect | How it was closed | Verified by |
|---|---|---|
| D1 estimator lineage mismatch | `K1715_results.json` `code_trace.sha256` == `sha256(K1715.py)` == `133c6f81…` | checker D1 |
| D2 no artifact from current code | guard-era keys present (`guarded_polish_gain`/`accepted_method`/`accepted_optimizer_success`/`accepted_nll`), retired `nm_to_bfgs_improve` absent (0 occurrences), committed blob == working-tree blob (`d622e1eb…`) | checker D2 |
| D3 schema break → `KeyError` | `build_readme.build()` runs end to end and reproduces the committed `README.md` **byte-identical** | checker D3 |
| D4 dirty certification surface | `git status --porcelain` empty | checker D4 |

Note the checker excludes exactly one path from D4 — its own report — because the report is
written by the check itself. Any other uncommitted file still fails. Confirm that exclusion is
the only one; if it has been widened, that is a finding.

## The substantive question round 3 must actually answer

Round 2's deepest objection was **not** clerical. It was that commits `9926bca90` /
`c9d75cf1d` added a BFGS min-NLL guard that **changes which parameter vector is selected**:

```python
res = res_bfgs if isfinite(res_bfgs.fun) and res_bfgs.fun <= res_nm.fun else res_nm
# previously: res was unconditionally the BFGS result
```

Round 2 correctly refused to carry the earlier **science** PASS across that change.

**The measured answer is that the guard is empirically inert on this dataset**, and this is the
load-bearing claim you must have Codex adjudicate:

- `accepted_method` is **`BFGS` in 536/536 refits** — the guard never once fell back to
  Nelder-Mead. Old code (unconditional BFGS) and new code therefore select the *same*
  parameter vector in every single refit.
- `guarded_polish_gain` (= `nm_nll - accepted_nll`, ≥0 by construction) has
  max ≈ **5.2e-11** across all four models — numerical noise, not a material improvement.
- `comparator_closeout_report.json`: **0 of 280** archived-only and **0 of 1,356** new-only
  leaves are science-classed; 280/280 archived-only leaves reappear under the renamed key with
  **identical values**; `category_c_found = false`; `archived_values_negative = 0`
  (independently confirming the guard never had to clip a polish step).

So the argument to be certified is: *the estimator lineage changed textually, but its output
is identical on this data, therefore the prior science PASS carries over on evidence rather
than on assertion.* **Have Codex attack that argument.** If it holds, the FAIL is cleared.

One honest wrinkle you must surface rather than hide: `bfgs_success_rate = 0.0` while
`accepted_method` is 100% BFGS. That is not a contradiction — BFGS's `gtol=1e-5` flag fails on
the near-integrated ridge while its NLL is still the lower of the two — but a reviewer will
trip on it, so put it in front of them explicitly.

## Steps

1. Run the checker (above). If it does **not** exit 0, stop and report — do not commission a
   review of a tree that fails its own preconditions.
2. Read `codex_recert2.md`, `comparator_closeout_report.json`, `snapshot_repro_report.md`,
   and `README.md`.
3. Commission a **bounded** Codex review at the exact current HEAD. In the commissioning
   prompt: name the HEAD sha explicitly, state the scope is (a) are the four round-2 defects
   closed, and (b) does the 536/536 `accepted_method` equivalence argument justify carrying
   the prior science PASS across the guard commit. Explicitly tell it a fresh full science
   review is **not** in scope — the science already holds a Codex PASS with
   `blocking_defects=[]`, contingent only on (b).
4. Write the verdict to `experiments/K1715/review_verdict.json` in the existing schema
   (`kid`, `verdict`, `reviewer`, `reviewed_at`, `reviewed_commit`, `review_artifact`,
   `blocking_defects`), with the raw review saved alongside as `codex_recert3.md`.
   **`reviewed_commit` must be the sha you actually reviewed** — that mismatch is precisely
   what sank round 2.
5. **If PASS**: merge the worktree via the official
   `uv run python scripts/git_writer_lock.py run --actor merge-worktree -- bash scripts/merge_worktree.sh k1715-204d556b`,
   then write the K1715 finding to `storage/memory/knowledge.json` through the proper CLI
   (never hand-edit), recording it honestly as the **NULL result** it is.
   **If FAIL**: leave the worktree unmerged, record the blocking defects, and do not retry the
   same way — `model_router --attempt 2` already reports `exhausted=true`, so a further
   same-method loop is barred. Escalate instead.

## Non-negotiables

- Research honesty outranks closing this ticket. K1715 is a **NULL result** (score-driven
  GAS/DCS does not beat the GARCH family at joint VaR+ES). A NULL result correctly certified is
  a success; a NULL result massaged into a PASS is a failure.
- Do not re-run the estimator. Re-running mints a new artifact and invalidates the very
  lineage this round exists to certify.
- Do not hand-edit `K1715_results.json`, `README.md`, or `reproduce_spec.json`.
  `reproduce_spec.json` is generated at run time and its
  `spec.entrypoint.sha256 == results.code_trace.sha256 == sha256(K1715.py) == 133c6f81…`
  invariant must survive. The closeout report lists two understated (not wrong) comparator
  strings at `K1715.py:114` deliberately left alone for exactly this reason — leave them.
- No `--no-verify`, no force push, no `git add -A`. Commit exact paths.
