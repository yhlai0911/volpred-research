# K1730 remediation v2 — response to the Codex v1 review

**v1 verdict**: `FAIL` (Codex gpt-5.6-sol / high, 2026-07-19 13:57 台灣時間,
reviewed commit `9060414f9`, artifact `codex_review_v1.md`).
**This document is the entry point for the second review.** It maps each of the
four blocking findings to what changed, where, and how the numbers moved.

Everything below came from re-running `k1730_gevreg_midas_ssvs.py` end to end.
No JSON field was edited by hand.

---

## 0. Summary of what changed, and what did not

| | v1 | v2 |
|---|---|---|
| Headline OOS conclusion | NULL — macro adds nothing | **unchanged, still NULL** |
| Basis for that conclusion | an invalid permutation called "decisive" | a leakage-free matched placebo, reported as coarse |
| GEV verdict | "likelihood surface is multi-modal" | **retracted** — it was a start-feasibility artefact |
| SSVS PIP status | presented as evidence macro is selected | **downgraded to diagnostic-only** |
| `README.md` | absent | present, with a mechanical alignment check |

The conclusion did not move. What moved is the evidence entitled to support it —
two of the three supporting arguments in v1 were not valid, and one of them was
pointing at a defect in the optimizer rather than at the likelihood.

---

## 1. Finding 3 (BLOCKER) — permutation invalid

> *"這是全樣本 permutation，會把較晚週才可得的 macro 值放入較早 origin；依同一
> permutation 重算 availability stamps，54,950/118,080 cells、788/1,640 weeks
> 含未來資訊… 不能稱為 permutation test 或 leakage falsifier."*

**Diagnosis accepted in full.** `rng.permutation(len(weeks))` on the macro tensor
did two separate kinds of damage: it destroyed the serial dependence that makes
the macro block a plausible covariate at all, and it moved later releases in
front of earlier origins. A placebo that itself leaks cannot be evidence about
leakage, and the v1 code never re-ran the point-in-time check on the shuffled
tensor to find out.

**What replaced it** — `run_placebo` / `placebo_submit` / `placebo_collect`,
`k1730_gevreg_midas_ssvs.py:107-300`:

* **Non-circular lag shift.** Week `i` receives the macro history of week
  `i − L`, for `L ∈ {52, 104, 156, 208, 260}` weeks. The tensor is the same
  sequence, so every autocorrelation, trend, level and cross-variable covariance
  survives; what breaks is which target week each history is asked to predict.
* **Zero lookahead by construction.** The releases behind week `i − L` all
  predate origin `i − L`, hence origin `i`. Wrapping is deliberately *not* used —
  wrapping the tail onto the head is precisely what would put 2026 macro in front
  of 1995 origins.
* **Verified, not asserted.** `D.assert_no_lookahead` is re-run on each shifted
  stamp array. All five report 0 violations; the reports are stored per shift in
  `placebo_test.lookahead_recheck_on_shifted_stamps`. This is the check v1
  omitted.
* **Matched sample.** The first 260 blocks are dropped from *every* arm,
  including a `real_matched` arm, so real and placebo differ in the macro
  alignment and nothing else. The dropped head is entirely pre-2008, so the OOS
  scoring sample is byte-for-byte the same 967 forecasts in every arm — the
  matching costs no out-of-sample observations.
* **Honest resolution.** Five shifts give a six-point reference distribution, so
  the smallest attainable one-sided p-value is 1/6 = 0.167. The JSON says so in
  `p_value_resolution_note` and the README repeats it. This is a coarse placebo
  comparison and is labelled as one.

**Also corrected**: v1's JSON claimed "parameters and all other inputs
unchanged". False — each arm re-selects omega, re-standardizes, re-runs the MLE
and re-runs the sampler. The v2 `design` field says so explicitly.

**Result**: see `placebo_test` in the results JSON, and §4 of the README.

---

## 2. Finding 1 (HIGH) — the multi-modality verdict was an artefact

> *"無效參數一律回傳常數 `1e10` … 會讓 L-BFGS-B 在平坦 penalty 上以 0 iteration
> 假收斂 … 0.47–0.51 實際是「可行起點率」，不是似然多峰率."*

**Diagnosis accepted and independently reproduced.** A constant objective has
zero gradient, so any start landing outside the support terminated immediately
and was recorded as a failed start. The reported rate was a property of the
random start distribution, not of the likelihood surface.

**Fix** — `k1730_models.py:330-420`:

* `gev_reg_nll` is now a smooth **exterior-penalty** objective: the log-density
  is evaluated on the support argument clamped at `t ≥ 1e-6`, and a quadratic
  penalty `1e4 · Σ max(0, t_floor − t)²` (plus matching terms for the xi and
  log-sigma ranges) supplies a restoring gradient. Inside the feasible set the
  penalty is exactly zero and the objective is exactly the old NLL, so the
  estimates themselves are on the same likelihood as before.
* `gev_reg_constraint_violation` is exposed separately, and an optimum is only
  counted if it lands *inside* the parameter space — a point held out by the
  penalty is not an MLE however finite its penalized objective.
* The one misleading field is now four unambiguous ones: `feasible_start_rate`
  (what v1 was really reporting), `feasible_optimum_rate`, `lbfgs_success_rate`,
  and `basin_concentration` — the fraction of feasible optima reaching the best
  one, which is the only field that speaks to multimodality.
* **The random starts were deliberately left identical** (same seed, same
  distribution), so the change in the statistics is attributable to the penalty
  alone and not to a friendlier start strategy.

**Re-judgement**: reported in README §5 from the production run. On the 2017
vintage used for development the feasible-start rate reproduced Codex's
diagnosis (0.60, vs the ~0.5 v1 reported as "convergence"), while the feasible
*optimum* rate rose to 0.97 and 26 of 29 feasible optima reached the same best
NLL. **The v1 claim that the likelihood surface is multi-modal is retracted**:
it rested on a number that measured start feasibility. What the corrected
diagnostics show is a surface where the large majority of starts agree, with a
minority reaching inferior optima — reported as such, without the EVT-flavoured
verdict.

**Not changed**: the Hessian checks, the Nelder-Mead cross-check and the
scipy validation all continue to support the selected optimum being stable.
Codex agreed this was never a blocking likelihood bug.

---

## 3. Finding 2 (HIGH) — SSVS not mixing

> *"19 次 refit 中 17 次 ESS<50、18 次 Geweke |z|>2、15 次 PIP chain spread>0.1 …
> 不可把 PIP 或未收斂 posterior 包裝成 macro 無資訊的證據."*

Route **(a) was attempted first and measured, then route (b) was taken.**

**What was tried (a):**

1. **A joint spike↔slab mode-jumping move** (`k1730_models.py:695-720`). This
   was the actual mechanism of the failure: to cross from spike to slab, `beta_j`
   has to grow ~100× while the spike prior still pulls it to zero, and `delta_j`
   will not flip until it has, so a chain stays in whichever regime it started.
   The new move proposes the flip and the coefficient together, drawing `beta_j`
   from the prior of the regime being proposed.
2. **Four overdispersed chains** instead of two, so R-hat and the cross-chain PIP
   spread are informative.
3. **More draws** — 40,000 with 15,000 burn-in.
4. **A correctness fix found on the way**: `log_post` previously rejected points
   by testing `nll >= 1e9`. Since the remediated NLL stays finite outside the
   support, that test would have let the chain sample the penalty instead of the
   likelihood. It now tests feasibility directly.
5. **A diagnostic defect found on the way**: the Geweke statistic used a fixed
   Newey-West `4·(m/100)^(2/9)` bandwidth. For a chain with an autocorrelation
   time of ~110 draws that window truncates the autocovariance sum far too early
   and inflates `|z|`. The tell was that tripling the draws moved R-hat
   1.019→1.006 and ESS 83→218 while the fixed-bandwidth Geweke sat at 5.7→6.0 —
   a statistic that does not improve as the chain improves is measuring its own
   bandwidth. Sizing the window to the measured persistence is the repo's
   standing HAC rule. **Both variants are reported** so the change is auditable
   and not a silently friendlier number.

**Measured on the 2017 vintage (development bench):**

| | v1 | v2 |
|---|---|---|
| worst R-hat | 1.61 | **1.017** |
| min ESS (all parameters) | 6.25 | **159** |
| min ESS (inclusion indicators) | not reported | **215** |
| PIP max chain spread | >0.1 at 15/19 refits | **0.056** |
| Geweke \|z\|, ACF bandwidth | — | **5.84** |
| Geweke \|z\|, fixed bandwidth | 49.3 | 13.39 |

**A ground-truth check was added** — `test_k1730_recovery.py`. The v1 review
could only say it found no algebraic error in the sampler, which is absence of
evidence. The new test simulates a GEV regression with one informative macro
column and one exactly-null column and asks the sampler to tell them apart:

| | result |
|---|---|
| PIP, informative column | **1.000** |
| PIP, null column | **0.120** |
| posterior mean vs true coefficient | 0.4694 vs 0.4500 |
| null coefficient | −0.0019 |
| R-hat / min ESS / Geweke | **1.001 / 3311 / 1.67** |

**This changes how the non-convergence should be read.** The sampler is not
broken and the gate is not unreachable: on a well-identified posterior this same
code converges comfortably and passes all three thresholds. The failure on the
real data is therefore a property of *that* posterior — weakly identified,
strongly correlated macro coefficients — and not an implementation defect. It
also shows the ACF-bandwidth Geweke is discriminating rather than merely
friendlier: it returns 1.67 when the chain is genuinely healthy and 5.84 when it
is not.

**Decision — route (b).** A convergence gate was fixed *before* the production
run at the conventional thresholds (R-hat < 1.05, ESS ≥ 400, |Geweke z| < 2;
Vehtari et al. 2021) and is evaluated mechanically in `ssvs_gev`. R-hat now
passes comfortably; **ESS and Geweke do not, at any configuration affordable
here** — 60,000 draws reached ESS 218, still short of 400, and the ACF-bandwidth
Geweke did not fall below 2. Rather than keep tuning until a number crosses a
line, the gate result is taken at face value:

`ssvs_summary.inference_tier = "diagnostic_only"`

set from the gate, not from prose. Every PIP-derived statement in the README and
the collection document is labelled from that field, the PIP figure carries a
DIAGNOSTIC ONLY subtitle, and **no conclusion in this experiment rests on the
PIP or on the posterior predictive being a converged posterior**. The narrow
claim Codex allowed — "this fixed-seed run did not produce an OOS improvement" —
is the claim that is made.

The sampler improvements were kept regardless: they are genuine, and the
posterior predictive that produces the model's forecast quantiles is better
behaved for them.

---

## 4. Finding 4 (BLOCKER) — missing README, overclaiming prose

> *"指定目錄沒有 `README.md` … 把無效 permutation 稱為「決定性」… 把低可行起點率
> 誤稱多峰 … 另稱 Christoffersen independence 不拒絕只適用 90% interval；95%
> interval 實際 `p=0.0204`、會拒絕."*

* **`README.md` written** — research question, data provenance and sample,
  model, evaluation protocol, results, an explicit statement of what the
  evidence does and does not support, and a limitations section.
* **"決定性" / "decisive" removed.** The NULL conclusion stays; its strength is
  stated as what a coarse 5-shift placebo plus a non-significant DM test
  supports.
* **The multimodality sentence is retracted**, with the retraction visible in the
  collection document rather than silently deleted.
* **The Christoffersen claim is corrected.** v1 wrote that independence is not
  rejected (p=0.73) and concluded the problem is unconditional width rather than
  clustering. That p-value is the 90% interval only; at the 95% interval
  p=0.0204, which rejects at 5%. Both levels are now reported and the "width not
  clustering" conclusion is stated as level-dependent.
* **Alignment is mechanical, not promised** — `verify_readme_alignment.py`
  re-reads the results JSON and checks every headline number quoted in the prose
  against it, fails on the banned claim vocabulary (`decisive` / `決定性` /
  `multi-modal` / `多峰` / `conclusive` / …), and fails if the SSVS tier is
  `diagnostic_only` while a document forgets to say so. Run it as part of review.

---

## 5. Files changed

| File | Change |
|---|---|
| `k1730_models.py` | smooth exterior penalty + feasibility API; corrected multistart diagnostics; SSVS mode-jump move; SSVS feasibility test; ACF-sized Geweke bandwidth; convergence gate |
| `k1730_gevreg_midas_ssvs.py` | non-circular lag-shift placebo replacing the permutation; `valid` row mask; parallel arms; corrected diagnostic field names; inference-tier plumbing; figure relabelling |
| `README.md` | **new** — the three-piece requirement |
| `test_k1730_recovery.py` | **new** — 19 checks: penalty transparency, penalty gradient, multistart field separation, SSVS recovery on known ground truth |
| `verify_readme_alignment.py` | **new** — mechanical prose↔JSON gate |
| `k1730_report_tables.py` | permutation table → placebo table; multistart table split into start-quality vs basin concentration; inference tier surfaced |
| `K1730_ARM_A_FULL_RUN_COLLECTION.md` | overclaims removed, retractions made visible |
| `k1730_gevreg_midas_ssvs_results.json` | regenerated end to end |
| `fig1`–`fig4` | regenerated from the new run |
| `review_verdict.json` | regenerated by `experiment_gates.py verdict-template`, status reset to pending |

## 6. What a second review should check first

1. Does `placebo_test.lookahead_recheck_on_shifted_stamps` show 0 violations for
   all five shifts, and is the matched sample identical across arms?
2. Is `basin_concentration` — not `feasible_start_rate` — the number the
   multistart discussion rests on?
3. Does any surviving sentence about the PIP outrun
   `ssvs_summary.inference_tier`?
4. Does `verify_readme_alignment.py` exit 0?
5. Does `test_k1730_recovery.py` exit 0? In particular check 3 — the sampler
   converging on synthetic ground truth is what licenses reading the real-data
   non-convergence as posterior geometry rather than as a bug.
