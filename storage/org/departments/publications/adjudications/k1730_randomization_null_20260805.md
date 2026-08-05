# K1730 — time-series randomization null: transformation-group adjudication

**Canonical task**: `k1730_randomization_null_design_adjudication_20260802` (P2, `paper_review`)
**Assigned**: operations manager, work item `item_20260805T085056035664Z_canonical-k1730-time-series-ran`
**Adjudicated by**: publications department, 2026-08-05
**Predecessor**: `storage/ops/codex_reviews/k1730_randomization_test_upgrade_null_20260802.md`
(`NO_DISPATCH`), contract B
**Prerequisite A**: `k1730_v2_adopt_reconcile_recertify_20260802` — `succeeded` 2026-08-04,
merge `5066c02f4`; the K1730 suite is present in canonical main (30 paths under
`experiments/k1730/`), so the claim surface this adjudication reasons over is the certified one.

---

## VERDICT

**NO VALID EXACT RANDOMIZATION UNDER THIS OBSERVATIONAL DESIGN.**

The result the task explicitly permits is the result the design forces. This is not a deferral
and not a "needs more work" — it is a proof that the class of transformations under discussion
cannot produce an exact test here, plus an assessment of the two escape routes that leave the
class, neither of which earns its cost.

**No B=199 compute task is materialized.** The ~743 CPU-h estimate is not the reason; a valid
design would have justified it. The reason is that no valid design exists in the class, and the
two out-of-class alternatives buy exactness in a currency (an unverifiable nuisance model, or a
symmetry assumption known to fail for nested comparisons) that the resulting p-value cannot
honour.

**K1730's NULL stays descriptive.** The existing five-shift non-circular placebo, with its
honest 1/6 p-value floor, is not a stopgap awaiting an upgrade. §1 below shows it is at the
information ceiling of what a point-in-time-safe index transformation can deliver. That
reframing is the substantive contribution of this adjudication.

---

## 1. The impossibility, stated and proved

### Setup

Let weeks be indexed `T = {1, …, n}` with forecast origins `o_1 < o_2 < … < o_n`. Each week `j`
carries a macro history whose constituent releases all predate `o_j` — that is the point-in-time
(PIT) property the v2 remediation established and verified via
`D.assert_no_lookahead` (`REMEDIATION_v2.md` §1).

A candidate randomization assigns to week `i` the macro history of week `σ(i)` for some
transformation `σ: T → T`. Because release times are monotone in the week index:

> **`σ` is PIT-safe ⟺ `σ(i) ≤ i` for every `i`.**

A randomization test is *exact* only if the transformations form a **group** `G`: closed under
composition, containing the identity and inverses, acting bijectively. Exactness comes from the
null distribution being invariant under `G`; without the group structure there is no invariance
argument and `(r+1)/(B+1)` is not a valid p-value, however many draws are taken.

### Proposition

> `{σ ∈ Bij(T) : σ(i) ≤ i for all i} = {id}`.

**Proof.** Induct on `i`. `σ(1) ≤ 1` forces `σ(1) = 1`. Suppose `σ(k) = k` for all `k < m`. Then
`σ(m) ≤ m`, and `σ(m) ∉ {1, …, m−1}` because those values are already taken and `σ` is
injective. Hence `σ(m) = m`. ∎

### What it rules out — all of it, at once

| Candidate transformation | Verdict | Why |
|---|---|---|
| Whole-row iid time permutation (the withdrawn v1 design) | invalid | Bijective, so by the proposition some `σ(i) > i`. Measured directly: 54,950/118,080 future-release cells |
| **Circular** block/lag shift | invalid | Bijective by construction; wrapping is exactly the mechanism that puts late releases in front of early origins |
| Block permutation, any block size | invalid | Bijective; the proposition applies verbatim |
| Permutation restricted to a sub-window `S ⊂ T` | invalid | The same induction runs on the total order of `S` and returns `id` on `S` |
| **Non-circular** positive lag shift `i ↦ i − L` (the v2 design) | PIT-safe, **not a group** | Not bijective — the first `L` blocks have no preimage. This is precisely why it is PIT-safe, and precisely why it cannot be exact |

The last row is the whole story in one line: **for index transformations, PIT-safety and
bijectivity are mutually exclusive.** Non-circular shifts escape the lookahead defect by
discarding information, and the discarded information is exactly what a group would have needed.

The task's instruction — *"non-circular lag shifts may remain a diagnostic unless exactness is
proved; do not rename a denser placebo grid as a valid test"* — is therefore not a caution to
be discharged by more careful work. Exactness cannot be proved because it is false, and adding
shifts `L ∈ {312, 364, …}` only lowers the p-value floor from 1/6 while leaving the object a
placebo. **Denser grid, same epistemic status.**

### Corollary for how the v2 placebo should be described

The five-shift placebo is not "coarse pending an upgrade". It is **the exact information ceiling
of PIT-safe index transformations on this design**, and its 1/6 floor is a property of the
observational design, not of effort or budget. The README and results JSON should say so.
Recommended wording, for whoever next touches the artifact:

> The five non-circular lag shifts give a six-point reference distribution and hence a p-value
> floor of 1/6. This is not a resolution limit that more draws would relieve: any
> point-in-time-safe reassignment of macro histories to forecast origins is non-invertible, so
> no exact randomization distribution exists for this design (adjudication 2026-08-05). The
> comparison is reported as a placebo because that is the strongest object the design admits.

---

## 2. The two routes that leave the class — assessed, both declined

The proposition constrains transformations of the *time index*. Two families sit outside it.

### Route A — block sign-flipping on the loss differential

Act on the scored output, not the data: partition the `967` out-of-sample loss differentials
into `K` contiguous blocks, and let `G = {−1, +1}^K` flip block signs. This *is* a genuine group
(`(Z/2)^K`), `|G| = 2^K` exceeds 200 for `K ≥ 8`, and PIT is untouched because no macro cell
moves. Cost collapses from ~743 CPU-h to seconds: **no refit is required at all.**

**Declined — the invariance is false for the null that matters.** Sign-flipping is exact under
"the blocked loss differential is distributed symmetrically about zero." K1730's comparison is
**nested** (`k1730_gevreg_midas_ssvs.py:141-144`: GEV-HAR is the macro block restricted to
zero). Under the sharp null that macro adds nothing, the focal model still estimates the extra
parameters, so its expected loss is *higher*, and the differential is skewed rather than
centred-symmetric — this is the very bias mechanism Clark & West correct for in the MSPE case.
A sign-flip test would therefore be exact for "the differential is symmetric about zero," which
is not the research question, and its rejections would be readable as parameter-estimation noise
rather than macro content.

Worth stating plainly because the temptation is real: this route is nearly free, would produce a
precise-looking p-value in seconds, and would be wrong in the same direction the existing result
already points. That combination is how a house p-value gets into a paper.

**Admissible use**: as a labelled diagnostic on differential symmetry, never as a test of
incremental predictive content. Not enqueued here; no result depends on it.

### Route B — conditional randomization test with a fitted macro generator

Do not permute the observed path; **simulate** synthetic macro paths from a fitted conditional
law `X_j | (past through o_j)` and re-score. PIT holds by construction — nothing generated at
origin `j` uses information after `o_j` — and under a correct generator the CRT is exact in
finite samples (model-X, Candès et al. 2018). This is the only route that is both PIT-safe and
genuinely exact for the intended null.

**Declined — the exactness is purchased with an unverifiable nuisance model, at full price.**

1. **Exactness relocates, it does not appear.** The CRT is exact conditional on the macro
   generator being correct. K1730's macro block is release-vintaged, mixed-frequency (MIDAS
   weighting), and cross-sectionally dependent. Specifying its joint conditional law correctly
   is a harder inference problem than the one being tested — and, unlike the original question,
   its misspecification is not diagnosable from the output.
2. **The cost premise is unchanged.** The restricted model is invariant to macro draws so the
   no-macro cache still holds, but every draw refits the focal GEV/SSVS arm: ~3.74 h per arm,
   ~743 CPU-h at B=199 before orchestration.
3. **The purchase is not worth it.** K1730's NULL is already supported descriptively and by the
   PIT-verified placebo. Spending 743 CPU-h to convert "no evidence macro helps" into "no
   evidence macro helps, p = 0.xx, conditional on a macro generator we cannot validate" adds a
   decimal, not a finding. If the macro block had shown signal, the calculus would invert — the
   cost would then buy a defensible claim rather than decorate a null.

**Condition for revisiting**: if a future K1730-family result is *positive* rather than null,
Route B becomes the correct spend, and this adjudication should be reopened with the generator
specification as its own reviewed deliverable — not folded into the runner.

---

## 3. Contract-B checklist — disposition of every required item

The task enumerated what a passing design must prove. Recording each against the verdict, so no
later reader mistakes "not supplied" for "overlooked":

| Required item | Disposition |
|---|---|
| Exact transformation group or conditional draw law | **Not supplied — proved impossible** for index transformations (§1); the two out-of-class laws are assessed and declined (§2) |
| Null invariance / exchangeability argument | Not applicable: no group exists to be invariant under |
| Every macro cell available at its forecast origin | This is the binding constraint. §1 shows it is exactly what forbids bijectivity |
| Serial and cross-variable dependence preserved | Only non-circular shifts preserve both — and they are non-invertible, hence placebo-only |
| Frozen common scoring window + byte-identical no-macro cache hash | Moot; already satisfied by the v2 matched design (967 forecasts identical across arms) and would have carried over unchanged |
| Statistic direction, ties, `(r+1)/(B+1)` | Moot. `monte_carlo_p_value` supplies the arithmetic once a valid draw mechanism exists; none does |
| seed = 42, unique draw identities | Moot |
| Synthetic-null size and known-signal power checks | Moot for the declined routes. For Route B these would have been the gate on the generator, not on the test — recorded for any future reopening |
| Sharded / resumable B=199 compute task | **Not materialized.** Task explicitly conditions this on a passing design verdict; the verdict does not pass |

## 4. What should change in the artifacts

Nothing in the numbers. Three descriptive corrections, all of which belong to whoever owns
`experiments/k1730/` — this department has no write access to that path:

1. `README.md` §4 / Table 8 and the results JSON `p_value_resolution_note`: adopt the §1
   corollary wording. The 1/6 floor is a design property, not a budget shortfall.
2. `REMEDIATION_v2.md` §1: append a pointer to this adjudication where it says the placebo is
   "labelled as one" — the reason it must stay labelled is now proved, not merely prudent.
3. `K1730_NESTED_DM_ADJUDICATION.md` §4.2: that section calls the full randomization test "the
   single concrete path by which K1730's null could be upgraded from descriptive to tested," and
   its three-bullet validity argument (no asymptotics / no smoothness / window cancels) is
   correct as far as it goes but **omits the availability constraint**, which is what actually
   kills the route. §4.2 should be marked superseded by this document rather than silently left
   standing — it is the most likely place a future reader would restart the same 743 CPU-h
   proposal.

## 5. Limits of this adjudication

- The proposition covers transformations that **reassign macro histories across forecast
  origins**. It says nothing about transformations of the *target*, nor about designs that
  change the observational structure (e.g. a genuine panel across markets, where cross-sectional
  exchangeability could be argued). If K1730 is ever extended to a panel, the impossibility does
  not automatically carry over and the question should be re-asked.
- The Route A skewness argument is stated from the nested-estimation mechanism, not measured on
  K1730's own differentials. It is sufficient to decline the route as a *test* — the burden is on
  the design to establish symmetry, not on the reviewer to refute it — but anyone wanting to use
  sign-flipping as a labelled diagnostic should measure the block-sum skewness first.
- **No independent review track was available this session.** `codex exec` and the bounded
  wrapper are both denied under the active permission mode. A methodology adjudication that
  concludes "impossible" should be adversarially checked before it is treated as settled: the
  proposition is elementary and self-contained, so the check is cheap, and it should target the
  *modelling step* (is "PIT-safe ⟺ `σ(i) ≤ i`" the right formalization of availability?) rather
  than the induction.
