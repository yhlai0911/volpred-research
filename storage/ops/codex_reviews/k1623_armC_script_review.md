# K1623 arm C — pre-execution script review

**Reviewed artifact**: `experiments/k1623/k1623_rev3_armc_mc.py` (new) +
`experiments/k1623/k1623_rev2_mc.py` (modified: docstring pointer + `_guard_frozen_artifact()`)
**Review purpose**: gate on whether the third MC arm may be enqueued to the compute queue.
The code had **not been run** at review time (repo rule: 實驗碼一律先審後跑).
**Date**: 2026-07-21 (台灣時間)
**Task**: `k1623_mc_third_arm_mean_structure_share`

---

## ⚠️ Reviewer source — primary path was UNAVAILABLE

**Codex (primary path) could not review this.** `codex exec` returned:

```
ERROR: You've hit your usage limit. Visit https://chatgpt.com/codex/settings/usage
       to purchase more credits or try again at Jul 25th, 2026 1:30 PM.
```

This is a **quota wall with a stated reset date, not a configuration fault** — the
`.claude/rules/experiments.md` Codex diagnostic ladder (version → login status → config model →
drop `model=` → smoke) does not apply, because `codex --version` (0.144.6) and
`codex login status` (Logged in using ChatGPT) both report healthy. No config change can restore
credits.

Per `.claude/rules/experiments.md` §Fallback, the review was therefore run by **two independent
non-Codex reviewers**:

| # | Reviewer | Model family | Verdict |
|---|---|---|---|
| 1 | `agy` CLI (Antigravity, Google) | Gemini-family | **PASS** |
| 2 | `feature-dev:code-reviewer` subagent | Claude, fresh context | see §2 |

**This is explicitly NOT a primary-path Codex PASS.** Per the K1259 lesson recorded in
`.claude/rules/experiments.md`: *"Subagent fallback PASS ≠ primary-path Codex PASS"* — when Codex
credits reset (≥ 2026-07-25), **this script must be re-reviewed by Codex before the round-3
verdict is signed**, and that re-review is a blocking precondition for merge, not a formality.
K1259 is the precedent: a subagent PASS was followed a day later by Codex finding 12 residual
defects in the same code.

---

## 1. Reviewer 1 — `agy` (Gemini-family): **VERDICT: PASS**

Full transcript: `/tmp/agy_armc_review.txt` (session-local; key findings reproduced here).

Answers to the six questions put to the reviewer:

1. **Arm C implementation** — correct. `x - level` is numerically exactly the raw simulated ARFIMA
   path, since `x = fractional_integrate(eps, d_hat)[BURN:] + level`. Defining arm C as the
   level-oracle baseline is sound.
2. **Shared paths** — confirmed. RNG consumption per replication is one `rng.normal` call,
   identical to `k1623_rev2_mc.analyse`; arm C draws no random numbers, so the eps stream cannot
   shift. On the tolerance: BLAS reduction-order noise sits at 1e-15–1e-16 while any genuine path
   divergence moves arm means/sds at the 1e-2 level, so `rtol=1e-9` sits in a very wide safe band —
   it can neither false-kill nor false-pass.
3. **Decomposition algebra** — verified: `(A-B) + (B-C) = A-C` telescopes exactly, and the
   multiplicative sd decomposition `sd_A/SE = (sd_C/SE)·(sd_B/sd_C)·(sd_A/sd_B)` cancels exactly.
   The `shares_are_interpretable` guard (suppress percentage shares when the two components have
   opposite signs or the total is ~0) was judged necessary and sufficient.
4. **Research honesty** — no pre-baked conclusions found. `finding_1/2/3` interpolate computed
   ranges rather than asserting a direction, and `finding_3` explicitly states the result *"must be
   read whichever way it came out"*. Scope limits judged complete.
5. **`_guard_frozen_artifact()`** — logic correct and the decision judged sound: it prevents an
   automated re-run from silently destroying the `claim_corrections_rev3` audit trail, which the
   reviewer characterised as consistent with the repo's 永遠修流程，不修資料 principle.
6. **Bugs that would make B-C untrustworthy** — none found.

### 1a. Precision defect surfaced by reviewer 1, and fixed

Reviewer 1's answer to Q1 established a point the script's own wording had **overstated**:

> Arm B estimates K+1 segment means; **arm C estimates 1 grand mean** (ELW `exact=True`
> internally subtracts a sample grand mean, as Shimotsu–Phillips requires). B-C therefore
> differences out ELW's single-demeaning bias and isolates the *incremental* cost of the
> segment means.

The reviewer framed this as a point in the design's favour, and it is — but the draft artifact
said arm C meant *"no part of the mean structure is estimated"*, which is **stronger than what is
true** and would license quoting B-C as "the cost of estimating any mean at all".

Fixed post-review, in four places, all wording-only (no numeric or control-flow change):

- module docstring — added the "one caveat that decides how B - C may be quoted" paragraph
- `arm_c_full_oracle_known_level.one_caveat_do_not_overread` — new field stating arm C is **not**
  a zero-mean oracle
- `bias_decomposition.definition` — B-C relabelled as INCREMENTAL over ELW's single demeaning
- `scope_limits` — new entry; and `summary.finding_1` now carries the qualifier inline

**Post-fix state**: `py_compile` + import re-verified clean. These edits move the file's sha256, so
the review pins below are stated against the post-fix bytes.

---

## 2. Reviewer 2 — `feature-dev:code-reviewer` subagent (Claude, fresh context): **VERDICT: CONDITIONAL PASS**

**The single required fix is the same defect reviewer 1 surfaced** — two independent reviewers, in
different model families, converging on one issue. Reviewer 2 stated it as a blocking condition
rather than an aside, and traced it to the precedent:

> `local_whittle(exact=True)` **always** internally demeans by the sample mean
> (`k1623.py:211`, `xd = x - mean(x)`). For arms A/B this is a no-op (per-segment demeaning
> already zeroes the total mean); for arm C, `x - level` has a generically nonzero sample mean, so
> one more global mean-removal *does* happen — which arm C's text claimed did not.
> *"This experiment already had to retract once for calling arm B 'ELW alone' when it was not …
> the exact same class of error is one plausible-sounding sentence away from recurring here for
> arm C."*

Reviewer 2 required three edits; **all three are applied** (see §1a, plus the two it caught that
reviewer 1 did not):

| Required edit | Status |
|---|---|
| `arm_c…what_it_is` — drop "no part of the mean structure is estimated" | ✅ reworded to "SEGMENTED (multi-break) mean structure" |
| `finding_2_elw_own_bias_is_now_separated` — drop "nothing to do with the mean structure being estimated" | ✅ now "BREAK-DRIVEN (segment-level)", and discloses the internal demeaning + FD_MAXK |
| new `scope_limits` bullet disclosing the internal demeaning applies in all three arms | ✅ added, stating both consequences (contrasts uncontaminated; but B-C is incremental) |

A follow-up self-scan caught a **third** site neither reviewer flagged — the inline comment at
`elw_own = mean_c - d_hat  # ELW alone, no generated regressor` — plus two further "ELW alone"
phrasings in the docstring and payload. All corrected, because a code comment asserting the
overclaim is exactly how the phrasing survives into the next revision's prose.

Reviewer 2 additionally confirmed, independently of reviewer 1: RNG consumption is one
`rng.normal` per replication with no in-place mutation of `x` (`piecewise_demean`/`bai_perron` both
copy); `atomic_write_json` is called once after the full loop, so a mid-loop `ReproductionFailure`
writes nothing; the `shares_are_interpretable` guard is *mathematically* sufficient (same sign ⟹
`|total| = |loc| + |meanest|` ⟹ both shares bounded in [0,1]).

**Operational note from reviewer 2, carried into the follow-up brief**: if numpy/scipy versions or
the OHLC cache drifted since the rev2 freeze, the gates will correctly *raise* rather than
misbehave. **If that happens, investigate the drift — do not loosen `rtol`.**

---

## 2b. ⚠️ Process incident — the reviewer executed the code it was reviewing

**What happened.** The `feature-dev:code-reviewer` subagent, briefed to review pre-execution code,
**ran** `k1623_rev3_armc_mc.py` during its review (artifact timestamped 00:32 台灣時間, 444s
runtime, mid-review). This violates the repo rule 實驗碼一律先審後跑 and produced an
`k1623_rev3_armc_results.json` in the experiment directory that:

- was generated from **superseded bytes** (pre-wording-fix), so its embedded text carries the very
  overclaims both reviewers required be removed;
- **bypassed the compute queue**, so it has no job receipt and never had the runner's
  `experiment_gates.py` pass applied;
- sat at the canonical artifact path, where the verdict template would have pinned it as if it
  were the reviewed result.

**Disposition.** Moved out of the experiment directory (preserved at
`/tmp/k1623_quarantine/armc_prefix_unauthorized_run.json`, session-local) and **not committed**.
The canonical artifact will be produced by the queued run. Its numbers are recorded in the
delivery JSON as a **preview**, explicitly flagged as non-citable.

**Why the numbers are still informative.** Every fix applied after that run was wording-only — no
change to the DGP, RNG, gate logic, or any computed field (both reviewers stated the edits needed
no re-verification of the shared-path or decomposition argument). So the queued run is expected to
reproduce these values exactly; if it does not, that discrepancy is itself a finding and must be
investigated, not reconciled.

**What the preview establishes (pending the queued run):**

1. **The shared-path design is proven, not merely argued.** The reproduction gate passed on all 5
   assets, and the recomputed A−B values match the frozen artifact **bit-for-bit to all 18
   significant digits** (e.g. TW0050 `-0.05562014170297003` in both). Arm C therefore sits on
   exactly the frozen run's paths and B−C is a clean paired contrast.
2. **The blocked item resolves to a materially large quantity.** B−C = **−0.0225 to −0.0431**,
   comparable in magnitude to the break-location effect A−B (−0.0200 to −0.0556). The
   mean-estimation share was **not** negligible — which is precisely why leaving it unmeasured was
   a real gap rather than a formality.
3. **It puts pressure on rev2's `finding_2`.** rev2 asserted the SE understatement comes mainly
   from the asymptotic 1/(2√m) formula. With mean estimation finally visible, the dominant sd
   factor is `asymptotic_formula` for only **2 of 5** assets (VIX, SPY); it is `mean_estimation`
   for QQQ and N225 and `break_location` for TW0050. Factor ranges: asymptotic 1.043–1.195,
   mean-estimation 1.058–1.188, break-location 1.010–1.101. **README §6.4 finding 2 will need
   revision, not just extension** — this is flagged for the collecting fire.

---

## 3. Hard-constraint compliance (verified mechanically, not by reviewer assertion)

| Constraint | Evidence | Result |
|---|---|---|
| Frozen `k1623_rev2_mc_results.json` unmutated | flatten-diff vs `git HEAD`: 181 keys → 181 keys, **0 changed / 0 removed / 0 added**; `git diff --stat` on the path is empty | ✅ |
| New results go to a NEW file | script writes `k1623_rev3_armc_results.json`; opens the rev2 JSON read-only | ✅ |
| Re-running rev2 script can no longer clobber the frozen artifact | guard executed live: refuses with a non-zero-intent `SystemExit` **before** loading data; frozen sha256 unchanged after the attempt | ✅ |
| Fixed seed | `SEED`, `N_REPS`, `BURN` imported from `k1623_rev2_mc`, not re-typed; script raises if the frozen artifact's recorded values disagree | ✅ |
| Experiment-integrity gates | `experiment_gates.py run --path experiments/k1623` → PASS, 6 files, 4 gates | ✅ |
| Lookahead | N/A — this is a parametric Monte Carlo on simulated paths; there is no forecast/target alignment surface | ✅ |

---

## 4. Disposition

**Approved for compute-queue enqueue** on the strength of two independent fallback reviews plus
the mechanical checks in §3.

**Outstanding, and blocking for round-3 sign-off** (not for enqueue):

1. **Codex primary-path re-review once credits reset (≥ 2026-07-25).** Fallback verdicts do not
   close this. See the K1259 precedent above.
2. **`review_verdict.json` must be regenerated again after the arm-C results land** — the claim
   surface is `*.py` + `README.md` + `*_results.json`, so `k1623_rev3_armc_results.json` will
   re-pin it. The regeneration done in this job reflects only the current (pre-results) bytes.
