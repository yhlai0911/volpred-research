# K1730 — nested-DM exposure: claim inventory and retract/repair adjudication

**Task**: `k1730_nested_dm_detector_exposure`
**Adjudicated**: 2026-07-21 17:21 (Asia/Taipei)
**Scope owner**: K1730 (arm A). K1731 references are *listed only* — their repair is owned by
`k1731_F3_armA_production_recheck`, not by this document.
**Trigger**: `scripts/audit_nested_dm_misuse.py` rev7 added a coefficient-mask AST channel; the
channel fired on `experiments/k1730/k1730_gevreg_midas_ssvs.py:141-144`, flipping the file from
PASS to FAIL and freezing it into `storage/ops/nested_dm_misuse_baseline.json` under
`active.exposed`.

---

## 0. Verdict in one paragraph

The nested comparison **GEVReg-MIDAS-SSVS vs GEV-HAR** in K1730 satisfies all three conditions that
K1731 F1 established have **no published inference method**: the models are nested, the loss is
pinball (non-differentiable, general), and the estimation scheme is recursive/expanding. The raw DM
statistic `t = +2.130, p = 0.0334` therefore **has no asymptotic-normal limit and is not a test**.
It is **RETRACTED as inference and re-labelled diagnostic-only**, exactly as K1731 arm B was. The
*substantive* null conclusion — macro is **not detected** to add incremental value to weekly RV
interval forecasts (this design has no power to distinguish zero from weak signal; §3.2) —
**survives**, but it now rests on descriptive loss ordering plus a coarse lag-shift placebo, not on
the DM p-value. No repair by Clark–West, Giacomini–White or McCracken is available; one genuinely
valid repair route (a full randomization test) does exist and is specified in §4.

**Outward-facing exposure was NOT zero.** `knowledge.json` entry `f932cb04` cited K1730's raw DM as
key numbers (v1 "t = +1.998, p = 0.046" and the quick-mode "t = 2.130, p = 0.033") and called the
permutation test 「決定性」 (decisive). That entry was **revised on 2026-07-21** (thread
`hourly-slot-1-ad6c5e1c`, via `revise_knowledge_entry.py`), retracting those supports while keeping
the NULL direction. There is still no feed article and no paper citing K1730, but the correction
list is **not empty** — it contains `f932cb04`, now remediated (see §5). [Amended 2026-07-27 —
item 1.]

---

## 1. Claim inventory

### 1.0 K1730's prose surfaces — what exists and where

A closeout **did** happen, on a salvage/preservation ref rather than in this worktree's working
tree. The earlier claim that "K1730 never went through closeout / has no README / had no brief" is
**withdrawn**:

- **README exists.** `experiments/k1730/README.md` (**227 lines**) exists on salvage ref
  `edcb5b0d0` (task `k1730_salvage_ref_integrate_v2_closeout`); it records the NULL result and a
  production run (`quick_mode = false`, seed 42, runtime 3.7 h, finished 2026-07-19T16:04:42Z).
  Verified: `git show edcb5b0d0:experiments/k1730/README.md | wc -l` = 227.
- **Agent briefs exist.** `storage/ops/agent_briefs/` holds
  `agent-brief_k1730_gevreg_midas_ssvs-cdcac4.md` (2026-07-18) and
  `agent-brief_k1730_remediation-832ffa.md` (2026-07-19), plus this adjudication's own
  `k1730_nested_dm_adjudication_20260721.md`. A brief **was** written.

The inventory below still uses the results-JSON fields, code-level claim sinks and K1731 citation
sites, because those remain the machine-readable claim surfaces. Corrected surface sweep:

| Surface | Result |
|---|---|
| `experiments/k1730/README.md` (salvage ref `edcb5b0d0`) | **exists, 227 lines** — NULL closeout |
| `storage/ops/agent_briefs/*k1730*` | **≥2 briefs exist** (see above) |
| `storage/memory/knowledge.json` | **1 match** — entry `f932cb04` (revised 2026-07-21; §0, §5) |
| `storage/memory/experiment_experiences.json` | 0 matches |
| `research_program.md` | 0 matches |
| `docs/` | **real hit** at `docs/governance/2026-07/nested_dm_coefficient_mask_audit.md:25,32` (governance record of the K1730 nested-DM detection) — **not** the earlier "1730 篇" article-count false positive |

[Amended 2026-07-27 — items 2, 3, 8, 1.]

### 1.1 The statistic itself — provenance

**Production values (`quick_mode = false`, salvage ref `edcb5b0d0`)** —
`experiments/k1730/k1730_gevreg_midas_ssvs_results.json` →
`oos.dm_tests["GEVReg-MIDAS-SSVS_vs_GEV-HAR"]`:

| Field | Value (production) |
|---|---|
| `t_stat` | `2.1589129768737063` |
| `p_value` | `0.03110257906915459` |
| `n` | `967` |
| `mean_loss_differential` | `0.002106184840034207` |
| `favours` | `"benchmark"` |
| `canonical_hac_lag` | `10` |
| `harvey_significant` | `false` |
| `t_stat_by_hac_lag` | lag_0 `2.6063`, lag_1 `2.4114`, lag_5 `2.1951`, lag_10 `2.1589`, lag_20 `2.0360` |

These **replace the earlier quick-mode figures** (`t = 2.1297`, `p = 0.0334`,
`mean_loss_differential = 0.001954`). The production run landed on salvage ref `edcb5b0d0` and
points the **same direction with the same verdict** (see §6.1). Every "+2.13" attributed to arm A
by K1731 is K1731's rounding of the *quick-mode* `2.1297`; the production statistic rounds to +2.16.

Note `favours = "benchmark"` and `mean_loss_differential > 0`: the **macro model has the HIGHER
(worse) pinball loss**. This direction is load-bearing for the adjudication — see §3.2.
[Amended 2026-07-27 — item 4.]

### 1.2 Claims that depend on this statistic

| # | File | Line / section | Verbatim | How it depends | Disposition |
|---|---|---|---|---|---|
| A1 | `experiments/k1730/k1730_gevreg_midas_ssvs_results.json` | `oos.dm_tests["GEVReg-MIDAS-SSVS_vs_GEV-HAR"].p_value` | `0.03344923473733519` | **Is** the invalid inference — a p-value computed from a statistic with no normal limit | **RETRACT as inference**; keep the number as a labelled diagnostic |
| A2 | same file | same block, `.t_stat` | `2.129693022321511` | The statistic itself | **Re-label diagnostic-only**; retain (it is a valid descriptive loss-gap summary) |
| A3 | same file | same block, `.harvey_significant` | `false` | Governing significance field; rule is `abs(t_stat) > 3.0` (`k1730_scoring.py:307`) | **No change** — already `false`. See §1.4 |
| A4 | `experiments/k1730/k1730_gevreg_midas_ssvs.py` | call at 293-294 (loop header `for bench in MODELS:` at :290; comment header at :288) | `results["dm_tests"][f"{focal}_vs_{bench}"] = S.dm_with_diagnostics(pinball[focal], pinball[bench], h=1)` | Producer: feeds pinball loss vectors into a raw DM. The `GEV-HAR` iteration of this loop is the nested one | **Annotate** with a `nested-dm: diagnostic-only` marker above the loop at :288-289 (see §4.1) |
| A5 | `experiments/k1730/k1730_gevreg_midas_ssvs.py` | 141-144 | `active = np.ones(n_beta)` / `active[n_beta - n_macro:] = 0.0` / `gev_har = M.fit_gev_reg(..., active=active)` | Establishes the nesting: `GEV-HAR` **is** `GEVReg-MIDAS-SSVS` with the macro coefficient block restricted to zero | Not a claim; this is the *evidence of nesting*. No change |
| A6 | `experiments/k1730/k1730_gevreg_midas_ssvs.py` | 140 (comment) | `# --- GEV without any macro block (isolates what macro adds) ---` | Prose asserting the comparison isolates macro's contribution — true as a *design* statement, but the word "isolates" invites reading the DM gap as a clean causal measure | **Amend** to note the isolation is confounded by estimation noise under nesting |
| A7 | `experiments/k1730/k1730_gevreg_midas_ssvs.py` | 672-674 (`_print_summary`) | prints each DM entry with `star = " *Harvey-sig*" if v.get("harvey_significant")` | stdout claim sink fed by the DM block | **Amend** printer to tag the nested row as diagnostic-only |
| A8 | `experiments/k1730/k1730_gevreg_midas_ssvs.py` | 22-26 (docstring, "Scoring") | `Scoring ... pinball loss, McNeil-Frey ES backtest, Diebold-Mariano (repo-canonical HAC)` | Lists DM as a scoring/inference instrument without a nesting caveat | **Amend** to state DM is diagnostic-only for the nested pair |

### 1.3 K1731 citation sites — **list only, do not modify**

Repair of these is owned by `k1731_F3_armA_production_recheck`. Recorded here so that task has a
complete target list.

| File | Line | Verbatim (abridged) |
|---|---|---|
| `experiments/k1731/README.md` | 36-38 | "arm A points the same way on its own target (**t = +2.13** against its no-macro nested model — same nested-DM caveat)" |
| `experiments/k1731/README.md` | 336-344 | "Arm A's own DM test of its macro model against its nested GEV-HAR gives **t = +2.13 (p = 0.033)**" |
| `experiments/k1731/README.md` | 636-645 | "Arm A's macro model also loses to its own nested GEV-HAR (**t = +2.13**) … read it as a direction" |
| `experiments/k1731/README.md` | 823 | "Confirmed and retracted. Arm A's macro model also loses to its own nested baseline (**t = +2.13**)" |
| `experiments/k1731/README.md` | 908 | "Arm A's `t = +2.13` is now labelled a direction, not a test" |
| `experiments/k1731/README.md` | 911 | arm A "(`k1730_gevreg_midas_ssvs.py`, `review_required`) … Arm A is arm A's to fix and is handed back, not repaired here" |
| `experiments/k1731/k1731_gevreg_midas_ssvs_returns_results.json` | 5202 | `cross_arm_comparison.what_cannot_be_said` |
| `..._results_corrected.json` | 5247 | same field |
| `..._results_corrected_rev5.json` | 5270 | same field |
| `experiments/k1731/k1731_regression_check_results.json` | 155-156 | `old` / `new` — the diff that softened the claim |
| `experiments/k1731/k1731_armB_rev6.json` | 31, 150 | |
| `experiments/k1731/k1731_armB_rev7_remediation.json` | 19, 110 | |
| `experiments/k1731/regression_baseline/…_results.json` | 5178 | older wording: "in arm A it demonstrably does not" |
| `experiments/k1731/regression_baseline/…_results_corrected.json` | 5231 | |

**Assessment of K1731's current wording**: lines 36-38, 645, 823 and 908 already label the statistic
"a direction, not a test" and carry the "same nested-DM caveat" rider. That wording is **consistent
with this adjudication** and needs no strengthening on the inference point. The one line that still
overstates is **336-344**, which quotes "**t = +2.13 (p = 0.033)**" — reproducing a p-value that
this adjudication retracts. Recommend K1731's owner drop the parenthetical p-value there.

### 1.4 An internal inconsistency worth recording

K1731 README:339 quotes arm A as "t = +2.13 (**p = 0.033**)", which reads as significant. But
K1730's own artifact sets `harvey_significant: false`, because the repo's Harvey bar is
`abs(t_stat) > 3.0` (`k1730_scoring.py:307`). **On its own governing field, K1730 never claimed
significance.** The apparent significance was introduced downstream by quoting the raw `p_value`
instead of the governing verdict field. This is independent of the nesting problem and would have
been an overstatement even if the DM were valid.

### 1.5 Figures

`fig1_rolling_coverage.png`, `fig2_ssvs_pip.png`, `fig3_interval_vs_realized.png` — none plot or
annotate the DM statistic (they show interval coverage, SSVS posterior inclusion probabilities, and
intervals vs realized). **No figure depends on the retracted statistic.** No figure regeneration
required.

---

## 2. Why the statistic is invalid — the three conditions

K1731 F1 (`experiments/k1731/k1731_f1_nested_inference_results.json`) established:

> "No published inference method covers this comparison: NESTED models + GENERAL
> (non-differentiable, pinball) loss + RECURSIVE (expanding) estimation window. The three
> constraints have been solved pairwise and never jointly."

K1730 meets all three, verified in code:

| Condition | Evidence in K1730 | Verified at |
|---|---|---|
| **Nested** | `active = np.ones(n_beta); active[n_beta - n_macro:] = 0.0; fit_gev_reg(..., active=active)` — GEV-HAR is the macro block restricted to zero | `k1730_gevreg_midas_ssvs.py:141-144` |
| **Pinball / general loss** | DM is fed `pinball[focal], pinball[bench]`, built by `S.mean_pinball_across_taus` over 13 quantile levels | `k1730_gevreg_midas_ssvs.py:259, 291-294`; `k1730_scoring.py:136-153` |
| **Recursive / expanding** | "Estimation — expanding window, re-estimated each 1 January"; `est = (block_end < refit_date).values` inside the annual refit loop | `k1730_gevreg_midas_ssvs.py:17, 81, 101-104` |

This is the **same construction as K1731 arm B**, on the same engine, differing only in target
(weekly max Parkinson RV vs returns) and macro set. The auditor's coefficient-mask channel docstring
names arm B as the reference case and arm A as the co-discovered false negative
(`scripts/audit_nested_dm_misuse.py:80-88`).

---

## 3. Adjudication: RETRACT, not repair

### 3.1 Why no repair by an existing test is available

Drawn from K1731 F1's `literature_basis.coverage`, applied to K1730's design:

| Candidate | Why it fails **for K1730** |
|---|---|
| **Clark & West (2006, 2007)** | MSPE-adjustment is algebraic in *squared errors*; there is no pinball analogue. F1's `must_not_do` is explicit: "Do not cite Clark & West … as authority for a PINBALL-loss nested test." Usable only to name the bias *mechanism* |
| **Giacomini & White (2006)** | Theorem 1 requires a finite maximum estimation window `m < ∞`; Comment 2 explicitly rules out recursive/expanding schemes. K1730 is expanding (`:17`) → **inadmissible without re-running the whole experiment on a rolling window** |
| **McCracken (2000)** | The only cell covering nested + general loss + recursive, but a DGP-free limit requires **estimation loss = evaluation loss**. K1730 estimates by GEV likelihood / SSVS MCMC and evaluates by pinball → violated, same as arm B |
| **Clark & McCracken (2001, 2012, 2015)**, **Pitarakis (2025)** | Quadratic-loss / MSE differentials only |
| **Giacomini & Komunjer (2005)** | Purpose-built for tick loss, but it is an **encompassing** test, not equal-accuracy; window requirement unverified from primary text |
| **Calhoun** ("large P rescues normality") | F1's `must_not_do`: the condition is `P²/T → 0`, and large `P` yields undersized, underpowered tests **biased toward the simpler model** — which is the direction K1730's result already points, so invoking it would be self-serving |

**Conclusion: not repairable in place.** Per the task's own decision rule — "若不能 → 撤回該宣稱並
標為診斷性" — the verdict is **RETRACT**.

### 3.2 What exactly is retracted, and what survives

This distinction matters and is not hedging; the two statements have different evidentiary status.

**RETRACTED — the inference layer:**
- `p = 0.0334` as a p-value. It is computed against a normal reference distribution the statistic
  does not have. **It is not a probability of anything.**
- Any statement that the loss gap is "significant", or that macro **demonstrably hurts** interval
  forecasts.
- Any use of `t = +2.130` as a *test outcome* — in K1730 or quoted cross-arm.

**SURVIVES — the descriptive/null layer:**
- **Macro is not *detected* to add incremental value to K1730's weekly RV interval forecasts — and
  this design cannot say more than "not detected".** This is a NULL result and must be stated as
  **"undetectable / no discriminating power"**, *not* as "macro adds no incremental value": because
  the nesting bias points the same way as the null (below), the design has **no power to
  distinguish a true zero signal from a weak one**. Supporting grounds (production, `edcb5b0d0`):
  1. **Loss ordering** — mean pinball: macro model `0.11434` vs no-macro GEV-HAR `0.11224`. The
     macro model is worse by `0.002106` (= `mean_loss_differential`).
  2. **Lag-shift placebo** — the single-draw permutation used in v1 is **retracted**:
     `REMEDIATION_v2.md` (2026-07-19) found the whole-sample shuffle leaked the future (it moved
     later macro releases in front of earlier origins; 54,950/118,080 cells affected), so it cannot
     serve as a placebo or a leakage test. It was replaced by a **non-circular lag-shift placebo**
     (`placebo_test`: shifts [52,104,156,208,260] weeks, first 260 blocks dropped, 1,380 matched
     blocks, zero-lookahead re-verified per shift). Result: `real_matched = 0.11415`, placebo range
     `[0.11245, 0.11471]`; **4 of 5** placebo arms do at least as well as the real alignment →
     **one-sided p = 0.833**. This is explicitly **coarse resolution** (5 shifts → smallest
     attainable p = 1/6 = 0.167, per `p_value_resolution_note`); it can only corroborate the NULL,
     it cannot support any positive claim.
  3. **The artifact's own governing field** — `harvey_significant: false`.
- **Grounds (1) and (3) are not independent.** Both are the same DM statistic in two presentations
  (`harvey_significant` is just `abs(t) > 3.0` applied to the `t` behind the loss gap). So the
  descriptive support reduces to *one* loss-ordering fact (1)/(3) plus *one* coarse placebo (2) —
  **not** three independent legs, and the earlier "three independent descriptive grounds" framing
  overstated the evidence.
- Critically, **the nesting bias runs in the same direction as this null**. Under the nested null,
  the larger model's extra estimated coefficients add forecast noise, so `E[loss_large −
  loss_small] > 0` is exactly what H0 predicts. Observing `+0.002106` is therefore **fully
  consistent with "macro contributes nothing"** and requires no appeal to a test. But that same
  coincidence of directions is precisely why this design **cannot discriminate zero signal from
  weak signal**: the strongest honest statement is "no incremental value is *detected*", not "macro
  adds no value", and certainly not that macro *degrades* forecasts beyond estimation noise. Those
  stronger readings are unsupported and must not be made.

So the null conclusion is not weakened by the retraction; it is **re-grounded and correctly
downgraded** to "undetectable (no discriminating power)". The retraction removes a false precision,
not the finding. [Amended 2026-07-27 — items 4, 5, 6.]

### 3.3 Consistency with the K1731 arm B precedent

Arm B set, in `k1731_f1_nested_inference_results.json.claim_status`:
`role = "nested-dm: diagnostic-only"`, `retracted_claim_still_retracted = true`, and recorded that
no number in the artifact is licensed as claim-bearing inference. **K1730 arm A is hereby placed in
the same status.** Same engine, same restriction mechanism, same loss, same scheme → same verdict.
Treating them differently would be inconsistent, and the baseline file's own note
(`storage/ops/nested_dm_misuse_baseline.json:9`) already records that "understating debt is the
worse error direction."

### 3.4 Auditor bucket

**Scope caveat — worktree vs canonical.** The bucket claim below holds only for the **worktree
copy** of `storage/ops/nested_dm_misuse_baseline.json` (buckets `count 196 / exposed 106 /
diagnostic_only 90`, `scanned 1880`), which lists `experiments/k1730/k1730_gevreg_midas_ssvs.py` in
`active.exposed` (1 of 106). In **canonical** `storage/ops/nested_dm_misuse_baseline.json` the
buckets are `193 / 103 / 90` (`scanned 1826`) and **`grep k1730` returns 0** — K1730 is not present
at all, consistent with the governance note that K1730/K1731 are not yet in canonical main
(`docs/governance/2026-07/nested_dm_coefficient_mask_audit.md:25`). So "1 of 106 in
`active.exposed`" is a **worktree-local** state, not a canonical fact.

K1731 README:911 describes arm A's classification as `review_required`. That is a **bucket-label
discrepancy** between the README prose and the frozen (worktree) artifact — flagged in §6, not
resolved here (the baseline file is shared ops state and out of this worktree's write scope).
[Amended 2026-07-27 — item 7.]

Once the §4.1 annotation lands, arm A should move `exposed → diagnostic_only`. That move requires
a baseline re-freeze and is **not** performed by this task.

---

## 4. Concrete remediation

### 4.1 Immediate — annotation (no re-run, no new numbers)

Mark the nested pair diagnostic-only so the auditor's `DM_DIAGNOSTIC_RE` channel recognises it
(`scripts/audit_nested_dm_misuse.py:143-150`), and so no reader can take the p-value as inference:

1. `k1730_gevreg_midas_ssvs.py` — add the marker at :288-289, above the DM loop (the
   `for bench in MODELS:` header is at :290 and the `dm_with_diagnostics` call at :293-294):
   `# nested-dm: diagnostic-only — GEV-HAR is this model with the macro block restricted to zero`
   `# (:141-144). Nested + pinball + expanding has no valid limit theory (K1731 F1); the DM entry`
   `# for that pair is a descriptive loss gap, not a test. See K1730_NESTED_DM_ADJUDICATION.md.`
2. `k1730_gevreg_midas_ssvs.py:22-26` (docstring "Scoring") — append: "DM is a directional
   cross-check only for the nested GEV-HAR pair; ordinary DM is descriptive only there."
3. `k1730_gevreg_midas_ssvs.py:140` — amend the comment: isolation is by design, but the resulting
   loss gap is confounded by estimation noise under nesting.
4. `_print_summary` (`:672-674`) — suppress or asterisk the `*Harvey-sig*` tag for the nested row.
5. Results JSON: on the next run, emit
   `oos.dm_tests["GEVReg-MIDAS-SSVS_vs_GEV-HAR"].inference_validity = "diagnostic_only_not_a_test"`,
   matching arm B's `production_reference.inference_validity` field name exactly.

**Note**: items 1-4 are source edits and item 5 changes artifact schema. Because the production
re-run is already queued (§5), these should land *before* that run so the new artifact is born
correctly labelled rather than needing a second correction pass.

### 4.2 Genuinely available repair route — full randomization test

The existing permutation block (`:557-612`) draws **one** permutation
(`perm = rng.permutation(len(weeks))`, single call, single scored run). One draw yields no null
distribution, hence **no p-value** — which is why §3.2 lists it as descriptive corroboration, not
as a test.

Upgrading it to `B ≥ 999` permutations of the macro block, re-scoring each, and locating the
observed `mean_pinball_real − mean_pinball_shuffled` in that empirical distribution would give an
**exact finite-sample p-value** for the sharp null "the macro block carries no incremental
predictive content". This route is valid where DM is not, because:

- it is a randomization test — it never invokes an asymptotic limit, so the nested non-normality
  is irrelevant;
- it makes no smoothness assumption on the loss, so pinball's non-differentiability is irrelevant;
- the expanding window is held fixed across permutations and so cancels.

**Caveat on interpretation**: this tests the *macro block's* contribution under time-permutation,
which is a slightly different null from DM's equal-expected-loss. It is a legitimate and
publishable test of the question K1730 actually asks ("do macro variables improve interval
forecasts?"), but it should be reported as what it is, not relabelled as a DM substitute.

**Cost**: `run_production.log` shows ~61-79 s per annual refit × 19 refits ≈ 21 min per full
pipeline (K1731 F1 measured `1583.6 s` for the sibling engine). At `B = 999` that is ~350 h
single-threaded — **not viable as specified**. Viable variants, in preference order:
1. Permute only the macro tensor and reuse the cached HAR/GEV-HAR fits (the no-macro model is
   invariant to macro permutation), cutting per-draw cost substantially;
2. `B = 199` (exact p-value resolution 0.005) rather than 999;
3. Run on the compute queue rather than inline.

This should be **enqueued as a separate task**, not attempted here. It is the single concrete path
by which K1730's null could be upgraded from descriptive to tested.

### 4.3 Route explicitly NOT recommended

Re-running K1730 on a **rolling** (fixed-memory) window purely to unlock Giacomini–White. It would
work theoretically, but (a) it changes the experiment's design to suit a test rather than the
research question, (b) it discards the expanding-window rationale, and (c) K1731's own
`primary_unconditional_gw_dm_fixed_memory` route is still blocked on an external-reviewer PASS
(Codex quota-exhausted until 2026-07-25). Arm A should not race ahead of arm B on an unadjudicated
route.

---

## 5. Outward-facing correction list

**ONE memory entry, now remediated. No reader-facing (feed/paper) exposure.**

There is **no** feed article and **no** paper citing K1730 (verified by the sweep below). But there
**was** a `knowledge.json` exposure — entry `f932cb04` — which cited the raw DM as key numbers and
called the permutation 「決定性」 (decisive). It was **revised on 2026-07-21**
(`revise_knowledge_entry.py`, thread `hourly-slot-1-ad6c5e1c`) to retract the DM-as-test, the
"decisive permutation", the SSVS-PIP evidence and the multimodality claim, keeping only the
descriptive NULL direction. So the correction list is **not empty**: it holds `f932cb04` (done).

Verified by exhaustive sweep (read-only, 2026-07-21; memory + docs rows re-checked 2026-07-27):

| Surface | Files searched | K1730 hits |
|---|---|---|
| `storage/reports/feed.json` (15 MB) | whole file, grep | **0** |
| `storage/reports/` entire tree (incl. `INDEX.md`, `_archive_mile_files/`, `drafts/`, `evidence/`, 3 `feed.json` backups) | all | **0** |
| `paper/` (14 paper subdirectories, all `.tex` / `.md` / `.bib`) | all | **0** |
| `paper_sections/`, `paper_complete.md`, `paper_outline.md`, `paper_frl_short.md` | all | **0** |
| `storage/memory/knowledge.json` + all backups | grep | **1** — entry `f932cb04` (revised 2026-07-21; see above) |
| `docs/` | all | **1 real hit** — `docs/governance/2026-07/nested_dm_coefficient_mask_audit.md:25,32` (governance record) |
| `research_program.md` | grep | **0** |

Cross-checked under paraphrase: `GEVReg`, `GEV-HAR`, `MIDAS-SSVS`, `gev_expected_shortfall` also
return **zero** hits in `storage/reports/` — it is not published under a renamed identity either.

**No `mile_id` to correct. No paper paragraph to amend. One knowledge entry (`f932cb04`) was
revised on 2026-07-21.**

K1730 *did* complete a closeout on salvage ref `edcb5b0d0` (README + agent briefs; §1.0). The
retraction's **reader-facing** footprint is nil (no feed, no paper), but its **memory footprint was
real and has been corrected**. The only remaining citation surface is K1731 (§1.3), whose repair is
owned elsewhere. [Amended 2026-07-27 — items 1, 3.]

---

## 6. Unresolved / pending production

Items this adjudication deliberately does **not** settle.

### 6.1 Production has landed (salvage ref `edcb5b0d0`) — numbers updated, verdict unchanged

At adjudication time (2026-07-21) the in-tree `k1730_gevreg_midas_ssvs_results.json` was a
`"quick_mode": true` copy, byte-identical to `k1730_quickmode_results.json` (md5
`af6167c936d435c5c9ce13cddefea3db`), and `run_production.log` stopped at the 2019 refit (12 of 19).
That is now **superseded**: a full `quick_mode = false` production artifact exists on salvage ref
`edcb5b0d0` (seed 42, runtime 3.7 h, finished 2026-07-19T16:04:42Z; README documents it).

**Production DM** (`oos.dm_tests["GEVReg-MIDAS-SSVS_vs_GEV-HAR"]`): `t = +2.1589`, `p = 0.0311`,
`mean_loss_differential = +0.002106`, `favours = "benchmark"`, `harvey_significant = false`. §1.1
and §3.2 above have been updated to these production figures.

**What the production run confirmed:**

- **Adjudication in §3 unchanged.** Nesting, pinball loss and the expanding window are properties of
  the *design*, not of sample size or MCMC draws. `t` moved (`+2.130` → `+2.1589`) but still has no
  valid limiting distribution. **The retraction is final.**
- **Null direction holds, same sign.** Production keeps `mean_loss_differential > 0` (`+0.002106`,
  up from the quick-mode `+0.00195`), `favours = "benchmark"`, and `harvey_significant = false`; the
  lag-shift placebo (§3.2) also corroborates the NULL (one-sided p = 0.833). **The verdict does not
  flip.**
- Commit `83dfd5618` had claimed a production run was received and adjudicated NULL. As of 2026-07-21
  the *in-tree* artifact contradicted that (still quick-mode); the production artifact on `edcb5b0d0`
  now substantiates the NULL direction, resolving that discrepancy. [Amended 2026-07-27 — item 4.]

### 6.2 Auditor bucket move

Arm A sits in `active.exposed` but README:911 calls it `review_required` (§3.4). After §4.1's
annotation, it should move to `diagnostic_only`. Requires a baseline re-freeze on shared ops state
— out of scope for this worktree.

### 6.3 Randomization test not run

§4.2's route is specified but not executed (cost, §4.2). Until it runs, K1730's null is
**descriptive, not tested**. Needs enqueueing as its own task.

### 6.4 Annotations not applied

This task's deliverable is the adjudication. The §4.1 source edits are specified but **not
applied** — they should land before the production re-run so the new artifact is born labelled.
Deliberate: applying them now would put uncommitted source edits under an in-flight production job.

### 6.5 K-id collision (housekeeping, unrelated to inference)

`storage/ops/k_id_registry.json` reserves `K1730` for a **different** topic (overnight/intraday
volatility risk premium clustering and day-of-week timing, claimed 2026-07-18 by
`research_backlog_auto`), still `pending` in `storage/next_tasks.json:41106-41109`. The GEVReg
arm A was dispatched as a boss-assigned P1 (`221c7abb7`) and took the K1730 number without going
through the registry. Two different experiments now share one K-id. Additionally, that backlog
entry's `source_line: 596` points into `research_program.md`, which contains **no occurrence of
"1730"** — a stale back-reference. Flagged for the registry owner.

### 6.6 Task handle — now present in the queue

`experiments/k1731/k1731_armB_rev8_remediation.json:174` hands off to task
`k1730_nested_dm_detector_exposure`. As of 2026-07-27 that id **is** present in
`storage/next_tasks.json`, with `status = "succeeded"` (title: "K1730 (arm A) 新被 nested-DM
detector flag：t=+2.13 的 raw DM 同屬 nested 缺陷類"). So the earlier "appears nowhere / grep = 0"
statement is **outdated** — the handoff is no longer dangling; the task was recorded and has
completed. (It originally ran only because it was picked up manually, then was registered.) It
remains worth checking whether *other* handoffs written the same way are silently dangling.
[Amended 2026-07-27 — item 8.]

---

## 7. Provenance of every number in this document

| Number | Source |
|---|---|
| **(production, `edcb5b0d0`)** `t = 2.1589129768737063`, `p = 0.03110257906915459`, `n = 967`, `mean_loss_differential = 0.002106184840034207`, `favours = "benchmark"`, `canonical_hac_lag = 10`, `harvey_significant = false`, `t_stat_by_hac_lag` | `k1730_gevreg_midas_ssvs_results.json` (`quick_mode = false`) → `oos.dm_tests["GEVReg-MIDAS-SSVS_vs_GEV-HAR"]` |
| **(production)** by_model pinball `0.11434474532709275` (macro), `0.11223856048705853` (no-macro GEV-HAR); lag-shift placebo `real_matched = 0.11415`, placebo `[0.11245, 0.11471]`, `one_sided_p_value = 0.833` (5 shifts → resolution 0.167). The v1 single-draw `permutation_test` is **retracted** (leakage; §3.2). | same file → `oos.by_model` and `placebo_test` |
| **(production)** `macro − no-macro = 0.002106184840034207` ≡ `mean_loss_differential` | computed from `oos.by_model`; matches to < 1e-9 |
| Harvey bar `abs(t_stat) > 3.0` | `k1730_scoring.py:307` |
| OOS `967` blocks, `2008-01-07` .. `2026-07-13` | same file → `oos` |
| md5 `af6167c936d435c5c9ce13cddefea3db` (both artifacts) | computed 2026-07-21 |
| 61-79 s/refit, run stops at 2019 | `run_production.log` |
| `1583.6 s` per full sibling pipeline | `k1731_f1_nested_inference_results.json` → `engine_fidelity_gate` |
| arm B `t = 1.3941542613188764`, `inference_validity = "diagnostic_only_not_a_test"`, `scheme = "expanding"` | same file → `production_reference` |
| Literature coverage table (§3.1) | same file → `literature_basis.coverage` and `.must_not_do` |
| Baseline buckets **(worktree copy)**: `count 196`, `exposed_count 106`, `diagnostic_only 90`, `scanned 1880`; **canonical** is `193 / 103 / 90` (`scanned 1826`) with **no k1730** (§3.4) | `storage/ops/nested_dm_misuse_baseline.json` (worktree vs canonical) |
| All line numbers | read directly from the cited files, 2026-07-21 |

**Nothing in this document is estimated, rounded from memory, or carried over from another
experiment's write-up.** As of the 2026-07-27 amendment, the K1730 magnitudes are **production**
(`quick_mode = false`, salvage ref `edcb5b0d0`), not quick-mode; see §6.1.

---

## 8. Amendment log (2026-07-27)

This revision corrects eight factual errors in the original 2026-07-21 adjudication. The **core
RETRACT verdict, the §3.1 "no valid repair" argument, and the §4.2 randomization-test route/cost are
unchanged.** All error directions were toward *understating* the debt; each fix discloses it. Every
change was evidence-verified before being written.

| # | What was wrong | What it now says | Evidence verified |
|---|---|---|---|
| 1 | §0/§5 claimed "zero outward exposure / correction list empty" | §0 + §5 now record the `knowledge.json` `f932cb04` exposure, revised 2026-07-21; correction list is not empty | `grep f932cb04 storage/memory/knowledge.json` = 1; entry text cites raw DM + "決定性 permutation", carries "2026-07-21 修訂" note |
| 2 | §1.0 "no agent brief was ever written" | §1.0 lists two real briefs (+ this adjudication's own) | `ls storage/ops/agent_briefs/*k1730*` → `agent-brief_k1730_gevreg_midas_ssvs-cdcac4.md`, `agent-brief_k1730_remediation-832ffa.md` |
| 3 | §1.0 "K1730 never went through closeout / no README" | §1.0 records the 227-line README on salvage ref `edcb5b0d0` | `git show edcb5b0d0:experiments/k1730/README.md \| wc -l` = 227 (status: NULL, `quick_mode = false`) |
| 4 | §1.1/§3.2/§6.1/§7 quoted quick-mode numbers; §6.1 said production "pending" | Swapped to production `t = +2.1589`, `p = 0.0311`, `mean_loss_differential = +0.002106`, `harvey_significant = false`; §6.1 records production landed, verdict not flipped | `git show edcb5b0d0:…_results.json` → `quick_mode=false`; DM block matches; direction/sign identical |
| 5 | §3.2 pillar 2 cited the retracted v1 single-draw permutation as a surviving null leg | Removed it; §3.2 now describes the non-circular lag-shift placebo (one-sided p = 0.833; coarse, 5 shifts → 0.167 floor) and its leakage-retraction basis | `experiments/k1730/REMEDIATION_v2.md` (canonical) §1; production `placebo_test` in `…_results.json` on `edcb5b0d0` |
| 6 | §3.2 called the grounds "three independent"; heading over-claimed "macro adds no incremental value" | Noted grounds (1)/(3) are the same `t`; downgraded to "not *detected* / no discriminating power" | logic + `harvey_significant` = `abs(t)>3.0` (`k1730_scoring.py:307`) |
| 7 | §3.4/§7 cited baseline `196/106` incl. k1730 as fact | Marked `196/106/90` (scanned 1880) as **worktree** state; canonical is `193/103/90` (scanned 1826) with **no k1730** | canonical `grep k1730 …baseline.json` = 0; buckets 193/103/90; worktree copy = 196/106/90, k1730 present |
| 8 | §6.6 said the handoff task "appears nowhere"; §1.2 A4 / §4.1 line refs; §1.0 docs note wrong | §6.6 records the task now in `next_tasks.json`; A4/§4.1 line refs corrected (call 293-294, loop header 290, marker 288-289); §1.0 docs hit corrected | `next_tasks.json` entry `status="succeeded"`; `.py` lines 288/290/293-294 read directly; `docs/governance/2026-07/nested_dm_coefficient_mask_audit.md:25,32` |

**One discrepancy vs the tasking note (handled conservatively):** the task brief said
`k1730_nested_dm_detector_exposure` is `status=in_progress`. The actual `next_tasks.json` entry reads
`status="succeeded"`. §6.6 uses the **verified** value (`succeeded`), not the briefed one.

**Scope preserved:** the §4.2 route/cost was not edited (per scope); its cross-reference to the v1
"permutation block" is now historical, since §3.2 no longer relies on that permutation.
