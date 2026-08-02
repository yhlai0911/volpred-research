# K1814 stage 3/3 — independent certification review on frozen bytes

**Model**: claude-opus-5 / xhigh (per model_router)

## Where you are

Worktree: `.claude/worktrees/dispatch-slot-1-8af0700e-k1814`, branch
`wt/dispatch-slot-1-8af0700e-k1814`, frozen at commit `e79386351`. The experiment
lives in `experiments/k1814/`. It is a **completed** run — 6170.6s, 8 arms,
finished 2026-07-30.

**DO NOT re-run `k1814.py`.** It takes 6170s and the brief forbids it.
**DO NOT repin `reproduce_spec.json`.** It correctly pins `b1a67269…`, which is the
preserved blob `gate_history/b1a67269__k1814.py`. The working `k1814.py` is
`d5b851a9…`; that divergence is intentional and already documented in README §10.
**DO NOT write `storage/memory/knowledge.json`** (K1259 — main thread only). It is
already written; that is not your job and not a defect for you to report.
**DO NOT run `scripts/merge_worktree.sh`.** The main thread merges.

## Why this job exists

`scripts/merge_worktree.sh` refuses to merge k1814. Reason, verbatim from the gate:

    [review-certification] reviewer verdict is CONDITIONAL_PASS, not PASS

Two prior stages already ran:
- **Stage 1** (`assign_d10a5a91`): landing inventory → `k1814_stage1_landing.json`.
- **Stage 2** (`agent-brief_k1814_stage2-237513`): rendered README §7/§8 from the
  artifact, audited lookahead / baseline fairness / entrypoint divergence, and wrote
  `experiments/k1814/review_verdict.json` with `verdict: CONDITIONAL_PASS`.

Stage 2's verdict was CONDITIONAL for exactly two reasons, **both now discharged by
the main thread**:
1. the `knowledge.json` entry was missing — it is now written (item `eba9964a`), and
   `scripts/check_experiment_artifacts.py check --path experiments/k1814` now reports
   **PASS**;
2. "do not repin reproduce_spec.json" — the main thread did not repin it.

Stage 2's file also uses a bespoke schema (`volpred.k1814.review_verdict.v1`) that
the certification gate cannot read: the gate requires `verdict` / `reviewed_sha256`,
not a narrative document.

**Your job is NOT to rubber-stamp that.** The certification gate exists because K1709
was merged carrying a non-PASS verdict and turned CI red four times. The gate's
premise is that a PASS verdict is issued by a reviewer who **read the bytes being
merged**. So read them. If stage 2 was wrong about something, say so and fail it.

## What to do

1. **Read the frozen claim surface yourself.** At minimum:
   - `gate_history/b1a67269__k1814.py` — these are the bytes that produced the results.
   - `K1814_results.json` — the canonical artifact.
   - `README.md` — the write-up.
   - `render_readme_results.py` — the script that renders §7/§8; run
     `python render_readme_results.py --check` and confirm it exits 0 (no drift
     between artifact and prose).
   - `reproduce_spec.json`, `k1814_stage1_landing.json`, `review_verdict.json`.

2. **Independently verify, do not inherit.** Specifically:
   - **Lookahead.** Targets must use only rv indexed in `(t, t+h]`; the direct-h-step
     embargo must hold (training rows `t` satisfy `t + h <= T`); the fit/validation
     purge must be `h-1`; scalers and the lognormal level correction must be
     per-origin, never full-sample. Confirm in the frozen bytes, not in the prose.
   - **Baseline fairness.** HAR / HAR-L / AR(1) / ridge-lags must share the DL arm's
     origins, embargo and test slices. Note that the linear models get the whole
     training window while DL loses the validation tail plus the purge — confirm this
     asymmetry disadvantages DL (i.e. it cannot manufacture the "baseline better"
     finding) and that README §6 discloses it.
   - **Number-for-number agreement** between README and `K1814_results.json`.
   - **The headline is a NEGATIVE null, and must stay one.** `h_star` is null,
     `horizons_with_dl_win` is `[]`, and at h=22 the DL arm is *significantly worse*
     than HAR-L (DM `-2.3133`, BH-FDR q `0.0414`, `decision_vs_harl_strong` =
     `HARL_BETTER`). Across both 6-test BH-FDR families every q=0.05 rejection has
     `direction: baseline_better`. **Reject any write-up that softens this into "no
     significant difference".**
   - **The one positive is reported, not buried.** The `channels_with_returns`
     ablation has LSTM beating its own HAR-L at h=1 and h=5. README §8 must disclose
     it *and* its caveats (outside the pre-registered FDR family so p is uncorrected;
     n_seeds=2 vs 5; refit_every=3000 also weakens that arm's own baselines).
     Burying it would be selective reporting — as would presenting it as a DL win.
   - **Calibre discipline.** The task title says "5-min RV". The experiment ran
     Route B, a **daily Parkinson realized-range proxy**, because yfinance returns
     only 60 trading days of 5-minute bars. Confirm the 5-min/1-h probe data is
     *never* fed to a model, and that README does not let a reader mistake these
     numbers for 5-minute RV.

3. **Write the canonical verdict.** Generate the skeleton — do not transcribe it:

   ```
   uv run python scripts/experiment_gates.py verdict-template \
     --path experiments/k1814 --out experiments/k1814/review_verdict.json
   ```

   This **overwrites** stage 2's narrative file. Before you run it, move that file to
   `experiments/k1814/stage2_review_verdict.json` — it is valuable audit history and
   must not be lost. Then fill in the skeleton: `verdict` (`PASS` or `FAIL`),
   `reviewer` (`claude-opus-5 / xhigh`), `reviewed_at`, `reviewed_commit`
   (`e79386351`), `review_artifact` (write your findings to
   `experiments/k1814/stage3_certification_review.md` and point at it), and
   `blocking_defects` (`[]` only if PASS). Leave `reviewed_sha256` exactly as the
   template generated it — those are the real bytes.

4. **Verify your own verdict unblocks the gate**, without merging:

   ```
   uv run python scripts/check_experiment_artifacts.py check --path experiments/k1814
   bash scripts/merge_worktree.sh --dry-run dispatch-slot-1-8af0700e-k1814
   ```

5. **Commit inside the worktree.** Do not touch anything outside
   `experiments/k1814/`.

## Success criterion

`experiments/k1814/review_verdict.json` exists, parses, carries a `verdict` of
literally `PASS` or `FAIL` reached on your own reading of the frozen bytes, and pins
the full claim surface by sha256. `stage2_review_verdict.json` and
`stage3_certification_review.md` are present and committed.

**A FAIL is a completely acceptable outcome and is worth more than a soft PASS.** If
you find a real defect, fail it and list it in `blocking_defects` — the main thread
will act on that. Do not pass something you have not actually checked.
