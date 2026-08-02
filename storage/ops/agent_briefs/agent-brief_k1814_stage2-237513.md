# K1814 split 2/2 — verify_and_merge

**Model**: opus / xhigh (per model_router)
**Parent timeout job**: `agent-brief_k1814-a3ea90`
**Split stage**: `verify_and_merge`
**Working directory**: `.claude/worktrees/dispatch-slot-1-8af0700e-k1814` (registered linked worktree — do NOT force-remove)
**Single deliverable**: `experiments/k1814/review_verdict.json`

---

## 0. Read this first — stage 1 is already done

`experiments/k1814/k1814_stage1_landing.json` exists and is your ground truth for *what landed*.
It was produced 2026-08-02 by the main thread. Read it before anything else. Key facts it establishes,
which you should NOT re-derive from scratch but SHOULD spot-check:

- The run **completed**. `stages_completed` ends with `complete`; `run_full.log` ends with the
  script's own normal-exit line `done in 6170.6s`. The detached pid 52501 is gone and ended naturally.
- **All 8 declared arms are present and error-free**: primary + 3 robustness
  (`SPY_parkinson`, `SPY_garman_klass`, `QQQ_parkinson`) + 5 ablations
  (`channels_with_returns`, `refit_250`, `window_L66`, `train_len1500`, `loss_qlike_direct`).
  Nothing is missing. There is no partial-arm salvage problem.
- Every artifact is sha256-pinned in `artifact_hashes`. **Verify those hashes still match before you
  trust any number.** If a hash has drifted, stop and report — someone edited an artifact under you.

### ⚠️ Entrypoint sha divergence — read carefully, do not "fix" it

`reproduce_spec.json` pins the entrypoint at sha `b1a67269d6f6…` (66724 bytes). The working
`k1814.py` now hashes to `d5b851a99cfc…` (67086 bytes). This divergence is **intentional and correct**:

- Stage 1 fixed a latent artifact-honesty bug in the ablation loop (`checkpoint(f"ablation:{name}", [])`
  reported zero unresolved items on every iteration, so a mid-loop partial artifact would have claimed
  completeness while holding 1-4 of 5 ablations).
- The exact bytes that produced the archived results are preserved at
  `experiments/k1814/gate_history/b1a67269__k1814.py`, which hashes exactly to the reproduce_spec pin.
- **To audit the numbers, diff against the gate_history blob, not the working file.**
- **Do NOT re-point `reproduce_spec.json` at the new sha.** The spec correctly describes the code that
  produced the results. Repinning it would destroy the traceability it exists to provide.
- **Do NOT re-run `k1814.py`.** The fix affects only future partial artifacts. No number changes.

---

## 1. The one blocking must-fix: README §7 and §8 are empty placeholders

This is the single biggest gap and the main reason this stage exists.

`README.md` contains the literal unrendered tokens:

```
## 7. Descriptive statistics

<!-- RESULTS:DESCRIPTIVE -->

## 8. Results

<!-- RESULTS:MAIN -->
```

…while README line 10 asserts **"Status: results section filled from `K1814_results.json` at run
completion."** That status line is currently **false**. README mtime (2026-07-30T05:00:49) predates
the results json (2026-07-30T06:40:30) by 100 minutes — the fill step belonged to the parent agent
that was killed at 2026-07-29T21:30:24Z.

**Your job**: render both sections from `K1814_results.json`, taking **every number
programmatically** from the json. Never retype a number from a log tail, a summary, or this brief —
this brief's numbers are for orientation only and you must re-read them from the artifact.

Requirements for §8:
- A per-horizon (1/5/22) table: QLIKE for HAR, HAR-L, Ridge control, best DL; the DM statistic vs
  both HAR and HAR-L; raw p and BH-FDR q vs both; `n_oos`; seed sd; the decision.
- The robustness arms and the ablations, each as its own table.
- State the FDR family explicitly (`fdr_family` / `fdr_families` keys exist in the json).
- §7 gets the descriptive block from `primary.descriptive`.

**Honesty constraint on the write-up — this is the crux of the experiment.** The result is a
**NULL, and at the longest horizon it is worse than null**:

- h=1: HAR 0.3768, HAR-L 0.3713, DL(lstm) 0.3713 → DM vs HAR-L −0.01 (q=0.9915) → FAIL_TO_REJECT
- h=5: HAR 0.2027, HAR-L 0.1982, DL 0.2054 → DM vs HAR-L −1.29 (q=0.2382) → FAIL_TO_REJECT
- h=22: HAR 0.1931, HAR-L 0.1914, DL 0.2128 → DM vs HAR-L **−2.31 (q=0.0414)** → FAIL_TO_REJECT

`dl_beats_both_baselines` is `false` at every horizon. The experiment's own hypothesis — "DL wins at
middle/long horizons" — is **contradicted, not merely unsupported**: at h=22 the DL model is
*significantly worse* than HAR-L after BH-FDR correction. The write-up must say this plainly.
Do not soften it into "no significant difference"; do not bury the h=22 sign. Per AGENTS.md,
null results are reported as-is and conclusions may not exceed evidence — in either direction.

---

## 2. Verification checklist — every item needs quotable evidence in the verdict json

1. **Data calibre gate.** Confirm README's stated data provenance matches what the code used.
   Stage 1 already checked this and found it **already correct** (F2): README title, the
   top-of-file calibre warning and §2 all state the **daily Parkinson realized-range proxy on
   `^GSPC` 1962-**, and `data_calibre_gate.route_taken == "B_realized_range_proxy"`. The 5-min
   probe (60 days / 4680 bars) is documented as the *reason Route A was rejected*, not as the data
   source. Re-confirm this holds in the sections you newly render, and confirm the primary arm's
   `n_oos=13176` / `n_daily_bars=16251` / span 1962-01-02→2026-07-29 are stated accurately.
2. **README ↔ results json number-for-number agreement**, for every horizon: QLIKE, DM statistic,
   BH-FDR q, multi-seed sd. After you render §7/§8 this is a check on your own output — do it as a
   separate programmatic pass, not by eye.
3. **Lookahead.** The highest-risk item per AGENTS.md. Verify in code (use the gate_history blob):
   - scaler/normalisation statistics fitted on the **train window only**, never the full series;
   - hyperparameters selected on validation inside the train window (`select_hp` path), never on OOS;
   - the rolling refit genuinely refits — read `primary.config.refit_every=750` against
     `ablation_refit_250` (refit_every=250) and confirm the two really differ in behaviour, which is
     the empirical answer to "is the refit real";
   - target/feature alignment carries an explicit lag (`signal.shift(1)` or equivalent);
   - `primary.lookahead_selftests` exists in the json — report what it actually asserts and whether
     those assertions are meaningful or vacuous.
4. **HAR baseline not weakened.** HAR-L wins or ties everywhere (see §1). Confirm HAR and HAR-L use
   the same lag convention, the same OOS row set and the same loss as the DL arms. A baseline that
   wins is evidence the comparison was fair, but verify it rather than assuming it.
5. **Ablation comparison basis.** `ablations._settings_note` declares each ablation must be compared
   against **its own** har/harl columns, never the primary arm's, because the OOS row set changes
   when `seq_len`/`train_len` change (note `window_L66` n_oos=13132 and `train_len1500` n_oos=14676
   both differ from primary 13176). Verify the rendered text actually obeys this.
6. **Nan columns (stage-1 finding F4).** Ablation arms show `AR1=nan`/`RIDGE=nan`, and `refit_250`
   also `TRF=nan` (Transformer intentionally dropped, n_seeds=1, documented in `_settings_note`).
   Confirm these are by-design omissions and that **no conclusion anywhere rests on a nan column**.
7. **Artifacts gate**: `uv run python scripts/check_experiment_artifacts.py check --path experiments/k1814`.
   Expect it to report the missing `knowledge.json` entry — that is **correct and not yours to fix**
   (K1259: agents must not write knowledge.json; the main thread writes it after PASS). Every other
   complaint is yours.
8. **Ruff**: `uv run ruff check experiments/k1814/k1814.py` reports 21 findings. Stage 1 confirmed
   this count is **identical before and after** the honesty fix, i.e. all 21 are pre-existing. Do not
   attribute them to the fix; note whether any are substantive.

---

## 3. Deliverable format

Write `experiments/k1814/review_verdict.json` containing:

- `verdict`: one of `PASS` / `CONDITIONAL_PASS` / `FAIL`
- `checklist`: one entry per item 1-8 above, each with `status`, the **evidence you actually
  observed** (quoted numbers, file:line, command output), and `must_fix` disposition
- `artifact_hashes_verified`: the sha256 of every artifact **as you observed it**, cross-checked
  against `k1814_stage1_landing.json.artifact_hashes`, with an explicit match/mismatch flag
- `readme_render`: what you rendered into §7/§8 and how each number was sourced
- `residual_risks`: what you could not verify and why

**`CONDITIONAL_PASS` is the minimum bar for merge.** If you reach `FAIL`, do **not** merge — record
the blocking defect precisely and state whether it is remediable in one more pass or warrants
3-strike escalation.

## 4. Boundaries — actions reserved for the main thread

- ❌ Do **not** write `storage/memory/knowledge.json` (K1259).
- ❌ Do **not** run `bash scripts/merge_worktree.sh` — the main thread merges after reading your verdict.
- ❌ Do **not** re-run `k1814.py`, do not repin `reproduce_spec.json`, do not touch `gate_history/`.
- ❌ Do **not** fabricate or forward numbers from this brief; re-read every one from the artifact.
- ✅ Do commit your work inside the worktree.

Report honestly. A well-evidenced `FAIL` is worth more than a `PASS` that papers over the empty
README the parent job left behind.
