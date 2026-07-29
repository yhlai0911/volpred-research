# K1734 rev4 — remediate two rev3 blocking defects, then re-certify

**Model**: opus / xhigh (per model_router)

Work in the existing worktree: `.claude/worktrees/dispatch-slot-1-1e5922b4-k1734`, branch
`wt/dispatch-slot-1-1e5922b4-k1734`, currently at `b41509854` (clean tree).
**Do not create a new worktree. Do not redo the experiment from scratch.** The experiment is
complete and its numbers have been independently verified; only two claim/gate defects remain.

## Read first

- `experiments/k1734/review_verdict.json` — the rev3 FAIL, sha-pinned to commit `87594200e`
- `storage/ops/codex_reviews/k1734_primary_path_rev3_verdict.md` — full rev3 reasoning, per dimension
- `experiments/k1734/k1734_h2_gate_fix_report.json` does not exist yet — you will write it (see below)
- `experiments/k1734/k1734_h1_gate_fix_report.json` — the rev2 remediation, **use it as the template
  for how to document a route decision**
- `experiments/k1734/review_history_rev1_rev2.json` — rounds 1-2 history (read-only, do not edit)
- `.claude/rules/experiments.md` §審查認證 — the certification contract you must satisfy

## Defect 1 (blocking) — H2's stated scope is broader than its accept gate

H2 is written as a disjunction: yen **or risk-off** co-moves with / leads carry left-tail events
(`README.md:19`, `k1734.py:21-22`). But `H2_accept` reads only the two yen/FXY tests
(`k1734.py:594-599`) and explicitly sets aside UUP / dVIX / HYG as a "separate, softer claim"
(`k1734.py:601-606`) — even though those regressions strongly support the risk-off limb
(HAC t = -17.26, -11.22, +13.82). So `verdicts.H2_accept=false` and "H2 as literally specified is
rejected" are **not licensed by the hypothesis as stated**.

This is the same defect class as rev2's H1 defect: prose claims one thing, the gate tests a subset.

Two routes. Pick one and justify it:

- **Route A — make the gate match the claim**: formally split H2 into H2a (yen/funding limb) and
  H2b (risk-off limb), give H2b a *same-caliber* test to the ones already in the file (same HAC
  treatment, same significance convention, entering the BH family), and have the gate read both.
  On the evidence H2b will likely accept while H2a stays null, so H2-as-disjunction would accept and
  `H2_accept=false` would flip. That is a substantive change to a headline verdict — which is the point.
- **Route B — narrow the claim to what is gated**: rewrite H2 everywhere (hypothesis statement,
  README prose, results JSON labels) as a yen-specific hypothesis, and relabel the risk-off
  regressions as explicitly descriptive, not hypothesis-testing.

Route A was chosen in rev2 for information preservation and structural durability, and that
reasoning largely carries here. **But do not choose it reflexively**: route A adds a test to the BH
family, which changes every adjusted p-value in the primary family — including `H3_oos_cw_mse`,
which currently survives at BH-adjusted p = 0.0451, a thin margin. **If adding an H2b test to the
family pushes H3 above 0.05, you must report that H3 no longer survives.** Do not shrink the family,
do not move H2b to a secondary family, and do not switch H3 to a one-sided p to save it. If the
choice is between a tidy verdict and an honest one, take the honest one and say so plainly.

## Defect 2 (blocking) — fig4 attaches an MSE p-value to a QLIKE plot

`figures/fig4_oos_loss_differential.png` plots cumulative **QLIKE** gain, but its title appends the
Clark-West `p=0.015`, which tests **MSE** (`k1734.py:969-978`). The QLIKE-specific block bootstrap
is null (mean +0.00516, CI [-0.00923, +0.01871], two-sided p = 0.4744). A reader sees a significant
p beside a non-significant quantity.

Fix: the figure must carry the test of the quantity it plots, or no p at all. Either label it with
the QLIKE bootstrap result (and its null), or drop the p from the title and reference the MSE CW test
only in prose where the metric is named. Do not "fix" this by relabelling the y-axis as MSE.

## Defect 3 (non-blocking, fix while you are here)

`README.md:80` says the BH family contains eight tests; the code and JSON correctly have nine
(and route A would make it ten). Make the prose match whatever the code ends up doing.

## Required workflow

1. Make the code/prose changes. Keep `signal.shift(1)` / `vix_lag1` lag discipline and `seed=42`
   exactly as they are — the lag discipline and OOS split passed rev3 and must not be disturbed.
2. Re-run `k1734.py` to regenerate `K1734_results.json` and the figures. It is deterministic
   (seed 42, cached `data/raw/*.csv`) — **every number that your change does not mechanically touch
   must come back identical**. If an untouched number moves, stop and find out why before continuing;
   that is a bug, not noise.
3. Write `experiments/k1734/k1734_h2_gate_fix_report.json`, modelled on the existing
   `k1734_h1_gate_fix_report.json`: the route you chose, why, what test you added (exact method,
   caliber, and that nothing was tuned), the resulting numbers, the BH-family recomputation and its
   effect on H3, and which verdict fields flipped.
4. Update `README.md` so every claim maps to a test that was actually run and gated.
5. **Re-certify — the shas have drifted, so the rev3 verdict is now void by design.** Regenerate the
   skeleton with the gate's own command (never hand-write or hand-edit it):
   ```
   uv run python scripts/experiment_gates.py verdict-template \
     --path experiments/k1734 --out experiments/k1734/review_verdict.json
   ```
   Then commission a **fresh Codex primary-path rev4 review covering all five dimensions from
   scratch** (lookahead / leakage / statistics / honesty / verdict_supported). Codex is available
   (verified working 2026-07-30 05:1x CST; the "limit until 2026-08-02" note in the rev1 record is
   stale). Call it bounded — `bash scripts/codex_exec_bounded.sh --timeout 900 -s workspace-write` —
   and give it **write access** so it can actually write its verdict; rev2 failed precisely because
   it was read-only. Do not let it treat "only these two items remain" as a premise.
   Write the review artifact to `storage/ops/codex_reviews/k1734_primary_path_rev4_verdict.md`.
6. Keep the commissioning prompt and raw transcript **outside** the worktree (`/tmp/`), or commit
   them before read-back. A stray untracked process file becomes a blocking defect (K1715 round 3).
7. Commit your work on the worktree branch with explicit paths (no `git add -A`).
   Do not attempt to commit in the canonical main checkout — the writer lock rejects it.

## Success criterion

`uv run python scripts/experiment_gates.py certify --path experiments/k1734` either passes with a
genuine rev4 PASS, or blocks on a rev4 FAIL whose blocking defects are newly discovered ones.
**A rev4 FAIL is an acceptable outcome and must be reported as such** — do not manufacture a PASS,
do not delete or edit the verdict file to get past the gate, and do not merge on a FAIL.
Knowledge entry only on CONDITIONAL_PASS minimum; do not write one on a FAIL.
Report honestly which of H1/H2/H3 accept after remediation, including any that flipped.
