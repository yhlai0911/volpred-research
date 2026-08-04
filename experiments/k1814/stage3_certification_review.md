# K1814 — stage-3 independent certification review

**Reviewer:** `claude-opus-5 / xhigh`
**Reviewed at:** 2026-08-02T09:36:44Z
**Reviewed commit:** `e79386351` (worktree `dispatch-slot-1-8af0700e-k1814`, branch
`wt/dispatch-slot-1-8af0700e-k1814`)
**Verdict:** **PASS** — `blocking_defects: []`

This review was performed by reading the frozen bytes, not by inheriting stage 2's
conclusions. Two real defects were found. Both are in the **write-up layer**, not in the
frozen science; both were remediated inside this worktree and are documented in full in §4.
The PASS certifies the post-remediation bytes, whose sha256 the verdict file pins.

---

## 1. What was actually read and run

| artifact | sha256 (as reviewed) | how it was checked |
|---|---|---|
| `gate_history/b1a67269__k1814.py` | `b1a67269d6f6…` | read in full (1,343 lines); this is the code that produced the results |
| `k1814.py` (working) | `d5b851a99cfc…` | diffed against the frozen blob |
| `K1814_results.json` | `73fa1562cfdf…` | parsed; every headline number re-derived or re-checked |
| `README.md` | re-pinned post-fix | read in full; §2/§3/§4 hand-typed numbers re-computed from raw CSVs |
| `render_readme_results.py` | re-pinned post-fix | read in full; every static prose assertion inside the gated block audited |
| `reproduce_spec.json` | `74c68fc83d26…` | entrypoint pin verified against the preserved blob |
| `k1814_stage1_landing.json`, `review_verdict.json` (stage 2) | — | read for context, not relied upon |

Commands run: `python render_readme_results.py --check`,
`scripts/check_experiment_artifacts.py check --path experiments/k1814`,
`bash scripts/merge_worktree.sh --dry-run …`, plus ad-hoc recomputation scripts.
**`k1814.py` was not re-run.** `reproduce_spec.json` was not repinned.
`storage/memory/knowledge.json` was not touched. `merge_worktree.sh` was not executed
outside `--dry-run`.

### Entrypoint divergence — confirmed correct as documented

`reproduce_spec.json` pins `b1a67269…`; the working `k1814.py` is `d5b851a9…`. The full diff
is 4 added lines and 1 changed line, confined to the ablation loop's `checkpoint()` call:
the frozen version passed a literal `[]` as the unresolved list on every iteration, the
working version names the not-yet-run ablation specs. It touches no estimation, no data and
no verdict logic — only what a *future partial* artifact would say about its own
completeness. The pin is correct as written and must not be moved. README §10 states this
accurately.

---

## 2. Independent verification of the claim surface

### 2.1 Lookahead — verified in the frozen bytes, not in the prose

| requirement | verdict | evidence |
|---|---|---|
| Targets use only rv indexed in `(t, t+h]` | **HOLDS** | `build_panel` accumulates `rv[rows + i]` for `i` in `1..h` — the loop starts at 1, so day `t` itself is excluded |
| Features use only rv/return indexed `≤ t` | **HOLDS** | `back_mean(k)` sums `rv[rows - i]` for `i` in `0..k-1`; `lag_x`/`seq` index `rows - k`, `k ≥ 0`; `harl_x` uses `ret[rows]`, and `ret[t] = log(C_t/C_{t-1})` is known at the close of day `t` |
| Direct-h-step embargo: training rows satisfy `t + h ≤ T` | **HOLDS, and is tight** | `rolling_forecasts` sets `tr_end = min(T-h+1, T)` with an exclusive slice, so the last training row is `T-h`. Its target ends at raw day `row_of(T)`, which is exactly the information set available when row `T` is forecast. Applied identically to `har`/`harl`/`ar1`/`ridge_lags` and to the DL arms |
| Fit/validation purge is `h−1` | **HOLDS in the rolling engine; DOES NOT HOLD in hyperparameter selection** | see Finding A |
| Scalers per-origin, never full-sample | **HOLDS** | DL `mu`/`sd`/`ymu`/`ysd` computed from `seq_tr`/`y_tr` inside `fit_dl`, called fresh at each origin; ridge `zmu`/`zsd` from `panel.lag_x[lin_sl]`. No standardisation is computed outside an origin's training slice |
| Lognormal level correction per-origin | **HOLDS** | `s2` is stored **per row** as `(reps, n)` arrays, not averaged across origins; `to_level` consumes the row's own value |
| Non-positive RV floor is not data-dependent | **HOLDS** | `RV_FLOOR = 1e-7` is a module constant. A sample quantile here would be full-sample leakage that a post-flooring perturbation test could not see; the code comments show this was reasoned about, and the self-test applies flooring *inside* the perturbed rebuilds |

I re-derived the purge arithmetic independently. In `rolling_forecasts`, `purge = h-1` puts
the last fit row at `tr_end - n_va - h`, whose target ends exactly at raw day
`row_of(val_sl.start)`, while the first validation row's target begins at
`row_of(val_sl.start) + 1`. The two are **exactly disjoint** — `h−1` is the correct purge
width, not an approximation.

The mechanical self-test (`lookahead_selftests`) is genuine, not decorative: it rebuilds the
panel under perturbation in both directions, requires `np.array_equal` (atol=0, not
`allclose`), and independently re-derives each probe row by naive slicing. The artifact
records 40/40 passes on all three checks.

### 2.2 Baseline fairness

All four linear baselines and both DL arms share the **same** origin list, the same embargo,
and the same test slices — they are produced inside one loop over `origs` with a single `te`
slice. `score()` then masks to rows finite for *every* model, so all six are evaluated on an
identical row set. The artifact confirms it: n_oos = 13,176 and OOS window 1974-03-22 →
2026-06-26 are byte-identical across all three horizons and all six models.

The one asymmetry is real and runs **against** the DL arm: linear models are fit on the full
3,000-row window (`lin_sl`), while DL loses the 450-row validation tail plus the `h−1` purge
— 2,550 / 2,546 / 2,529 rows at h = 1 / 5 / 22, about 85%. This is forced by early stopping
and is the correct choice (handicapping OLS to match would be the weakened-baseline failure
mode this experiment exists to avoid). It **cannot manufacture a "baseline better" finding
in the sense that matters** — it cannot produce a spurious *DL win* — but it does mean part
of the h=22 deficit could be a training-sample-size effect. README §6.7 disclosed the
mechanism but not this consequence; I added it, and added §9 item 8. See §4, Fix C.

Two further design choices tilt *toward* the DL arm, which strengthens the null:
- `best_dl` is selected as the **lower-QLIKE** of LSTM/Transformer before its DM test is
  reported. Since the finding is "DL loses", headlining DL's better model is conservative.
  The multiplicity this could introduce is already absorbed: both architectures are members
  of the 6-test BH-FDR family, so the reported `q` is corrected across them.
- DL `resid_var` for the level correction comes from **held-out validation** residuals, while
  OLS uses the dof-adjusted in-sample estimate. The code comment is right that an in-sample
  estimate for an early-stopped net would be optimistic and would under-inflate the DL level
  forecast, which QLIKE punishes asymmetrically.

### 2.3 Number-for-number agreement

- **BH-FDR recomputed from scratch** on the 12 raw p-values (both families): all 12 adjusted
  values match the stored `p_bh` to < 1e-12, and all 12 reject/accept flags match.
- **DM-HLN arithmetic reconstructed** for all 12 primary tests from `dm_raw`, `n` and `h`:
  the HLN factor `sqrt((n+1-2h+h(h-1)/n)/n)`, the corrected statistic, and
  `p = 2(1 - t.cdf(|stat|, n-1))` all reproduce to < 1e-9. `hac_lag == h-1` in every case,
  and the sign of every statistic agrees with the sign of its `mean_loss_diff`.
- **Verdict block internal consistency**: for all three horizons, `best_dl_model`, all four
  QLIKE fields, both difference fields, both DM statistics, both `q` values,
  `effective_independent_obs` and `dl_beats_both_baselines` all re-derive exactly from
  `primary.horizons`.
- **README §2/§3/§4 are hand-typed** (they sit outside the render-gated block, so
  `--check` does not cover them). I recomputed them from the raw CSVs. The §3 decade table
  reproduces **exactly**: Open == prior Close at 96.68 / 92.44 / 65.47 / 76.66 / 63.78 /
  6.24 / 0.06 % by decade, 59.14% overall, zero-range 0.96 / 0.71 / 0.04 / 0 %, 38
  non-positive Parkinson estimates (0.23%), SPY 1.89%, QQQ 1.18%. §2 and §4 match
  `data_calibre_gate` exactly.
- **`render_readme_results.py --check` exits 0** both before and after my edits.

### 2.4 The headline is a negative null and remains one

`h_star = null`, `horizons_with_dl_win = []`, `H2_boundary_exists = false`,
`H1_short_horizon = FAIL_TO_REJECT`. At h=22, `decision_vs_harl_strong = "HARL_BETTER"`
(DM-HLN −2.3133, BH-FDR q = 0.0414).

I swept **all 12 tests across both 6-test families**: 5 rejections at q = 0.05, and every
single one carries `direction: "baseline_better"`. Zero rejections favour DL. I also swept
every robustness arm — all 9 arm × horizon cells have negative DM against *both* of their own
baselines, with no exceptions.

README §8.1 states the result as "significantly worse … in the direction opposite to the
hypothesis" and explicitly says it is "stronger than 'no difference'". **It is not softened
anywhere**, and the auto-bandwidth robustness columns do not flip a single sign (at h=22 the
data-driven bandwidth selects the same lag 21, so the statistics are identical).

### 2.5 The one positive is reported, not buried

`channels_with_returns` has the LSTM beating its own HAR-L at h=1 (DM +3.088, raw p = 0.0020)
and h=5 (DM +2.085, raw p = 0.0371), and losing at h=22 (DM −0.343). README §8.5 reports it
under the heading "the one place DL wins", states plainly that "burying it would be selective
reporting", and discloses all three caveats the brief requires: outside the pre-registered
FDR families so p is **uncorrected** (I confirmed no `p_value_bh_fdr` key exists on any
ablation DM result), `n_seeds = 2` against the primary arm's 5, and `refit_every = 3000`
degrading the arm's own baselines. It is framed as a hypothesis for a future pre-registered
test, not as a DL win. **Correctly handled in both directions.**

I swept every ablation for DL-positive results to check nothing else was omitted. The only
other positives are `refit_250` h=1/h=5 vs HAR (p = 0.40, 0.72) and `window_L66` h=1 vs HAR
(p = 0.0519) — none significant, none load-bearing.

### 2.6 Calibre discipline

The task title says "5-min RV"; the experiment ran Route B, a daily Parkinson realized-range
proxy. I traced the data flow in the frozen bytes: `probe_intraday_limits()` returns into
`data_calibre_gate.measured_intraday_limits` and `proxy_validation()` into
`proxy_vs_true_rv` and the figures. **Neither ever reaches `run_arm`**, which draws solely
from `load_daily()` → the daily OHLC CSVs. No 5-minute or 1-hour bar enters any model, any
feature, any target, or any scaler.

The write-up does not let a reader mistake the numbers for 5-minute RV: the title says "on a
daily realized-range proxy", a blockquote warning sits above the fold, §2 justifies the route
arithmetically, §4 measures the gap (~31% median level bias, 0.62–0.73 log correlation), §7
repeats it, and §9 item 1 names it the binding limitation. Figure labels are calibre-honest
too ("ACF of log RV-proxy", "Parkinson proxy", "Range proxy vs genuine intraday RV"). §4's
argument that the *level* bias cancels under scale-invariant QLIKE while the extra *noise*
does not is correct and is the right distinction to draw.

---

## 3. On stage 2's CONDITIONAL_PASS

Stage 2's two conditions were discharged before this review began: the `knowledge.json`
entry now exists (`eba9964a`) and `reproduce_spec.json` was not repinned. Stage 2's
substantive audit of lookahead, baseline fairness and the entrypoint divergence was, on my
independent re-derivation, **correct** — I reached the same conclusions from the bytes.

Stage 2 also used a bespoke schema the certification gate cannot read. Its file has been
preserved at `stage2_review_verdict.json` rather than overwritten; it is audit history.

What stage 2 **missed** is Findings A and B below. Both live in the write-up layer, which is
where an overclaim actually reaches a human.

---

## 4. Findings

### Finding A — the `h−1` purge does not cover hyperparameter selection, but the artifact says it does

**Severity:** non-blocking (no OOS leakage, no reported number affected).

`rolling_forecasts` applies `purge = h - 1` between the fit and validation slices.
`select_hyperparams` — which chooses `(hidden, lr)` once at the first origin — **does not**:

```python
fit_sl = slice(tr_beg, tr_end - n_va)      # select_hyperparams: no purge
val_sl = slice(tr_end - n_va, tr_end)
```

This is confirmed by the artifact's own `selection_window` fields, independent of my reading
of the source: at h=22 the fit slice ends at row 2560 and the validation slice is
`rows[2560:3010]` — they abut with a zero-row gap, where the rolling engine would have left
21 rows.

The frozen artifact's `lookahead_policy.fit_validation_purge` string claims the purge means
"early stopping **and hyperparameter selection** never score on targets that overlap the
fitted rows' targets". For hyperparameter selection that is **false**.

**Why it is not blocking.** The entire selection window is strictly pre-OOS: it ends `h` rows
before the first forecast origin, so the last validation target closes at raw day
`row_of(oos_start - 1)` — inside the information set available at the first origin. No
out-of-sample observation is touched and no reported number moves. The only reach is which of
six `(hidden, lr)` pairs was chosen, and the bias is toward larger capacity, which works
against the DL arm rather than for it.

**Remediation.** The artifact string is frozen (correcting it would mean re-running a
6,170-second experiment for a methods sentence, which is not warranted). README §6 item 3 now
carries an explicit scope correction stating what the code does, what the artifact string
says, and why the difference has no consequence. README §6 was already narrower and correct
("early stopping"), so the README never asserted the false version.

### Finding B — a false robustness claim, hidden inside the drift-gated block

**Severity:** would have been blocking as written; **fixed**.

README §8.2 asserted:

> Neither conclusion depends on the lognormal level correction: `qlike_no_lognormal_correction`
> reports the uncorrected `exp(m)` variant for every cell, and **the ranking is unchanged**.

The ranking is **not** unchanged. Of the 6 best-DL-vs-baseline cells, **2 reverse** under the
uncorrected variant:

| cell | corrected | uncorrected |
|---|---|---|
| h=1 vs HAR-L | HAR-L ahead, 0.371266 vs 0.371322 (gap 0.000055) | **LSTM ahead**, 0.441522 vs 0.447215 (gap 0.005693) |
| h=5 vs HAR-RV | HAR-RV ahead, 0.202662 vs 0.205351 (gap 0.002689) | **LSTM ahead**, 0.218942 vs 0.222321 (gap 0.003379) |

Two things make this worse than a slip:

1. **The direction favours the paper's own conclusion.** Both reversals are cases where the
   DL arm looks *better* under the alternative specification. A blanket "the ranking is
   unchanged" concealed both — the same selective-reporting failure mode the brief flags for
   `channels_with_returns`, in a less visible place.
2. **The drift gate could not catch it.** The sentence was a hardcoded string literal inside
   the `RESULTS:MAIN` block, so `render_readme_results.py --check` certified the section as
   "matching the artifact" while the sentence contradicted it. The gate was giving false
   assurance for exactly this class of claim.

**Why the headline still stands.** Every DM statistic, both BH-FDR families and every decision
field are computed on the **corrected** losses; nothing that is reported as a test moves. Both
reversed cells are ones the corrected variant already reports as statistically
indistinguishable (h=1 vs HAR-L: DM −0.011, q = 0.9915; h=5 vs HAR-RV: DM −0.503, q = 0.6153),
so neither is a DL win under either variant. The h=22 cells that carry the headline keep both
baselines ahead under both variants.

**Remediation.** The renderer now **derives** this claim from the artifact instead of
asserting it: it compares corrected and uncorrected orderings across all 6 cells, counts the
reversals, names each one with both gaps, and states why no reported test moves. The claim is
now covered by the drift gate rather than merely surrounded by it. README §9 gained item 9.

### Class sweep for Finding B

Finding B is an instance of "hardcoded prose assertion inside a gate-certified block", so I
audited **every** static claim in `render_readme_results.py` rather than patching the one
instance. The others are all true, verified against the artifact:

| static claim | verdict |
|---|---|
| "All nine arm × horizon cells put the best DL model behind both of its own baselines" | **true** — 9/9 cells, no positive DM |
| "Ridge on all 22 individual lags never beats HAR's three aggregates" | **true** at all three horizons (0.3832/0.2059/0.2026 vs 0.3768/0.2027/0.1931) |
| "`ar1` and `ridge_lags` are not run in the ablation arms, and the Transformer is not run in `refit_250`" | **true** — model sets confirmed in the artifact |
| OOS window "contains the 1973-74, 1987, 2000-02, 2008-09, 2020 and 2022 drawdowns" | **true** — window opens 1974-03-22, inside the 1973-74 bear market |
| "the four non-`channels` ablations … each move the result the wrong way or leave it unchanged" | **true** |

### Fix C — training-window asymmetry consequence (disclosure gap, not a defect)

README §6.7 disclosed that linear models get the full window, but not the consequence that the
DL arm therefore fits on ~15% fewer rows, and §9 did not carry it as a limitation. Added to
both. This is a completeness improvement, not a correction — nothing previously stated was
false.

---

## 5. Changes made by this review

All confined to `experiments/k1814/`. **No frozen byte, no number, no verdict field, and no
scientific result was altered.**

| file | change |
|---|---|
| `render_readme_results.py` | replaced the hardcoded lognormal-robustness sentence with a derived computation (Finding B) |
| `README.md` | §8.2 re-rendered from the fixed renderer; §6.3 scope correction (Finding A); §6.7 asymmetry consequence (Fix C); §9 items 8 and 9 |
| `review_verdict.json` (stage 2) | moved to `stage2_review_verdict.json`, preserved verbatim |
| `stage3_certification_review.md` | this file |
| `review_verdict.json` | regenerated from `experiment_gates.py verdict-template` and filled in |

`gate_history/b1a67269__k1814.py`, `k1814.py`, `K1814_results.json`, `reproduce_spec.json`,
`k1814_stage1_landing.json` and all five figures are **untouched**.

**Independence note, stated plainly:** I both found and fixed Findings A/B/C. The fixes are
mechanical corrections of prose to match the artifact, verifiable by `--check` and by the
recomputations in §2.3 — not scientific judgement calls. The alternative (FAIL and hand back
a one-paragraph prose fix) would have stalled a correct experiment for no gain. The verdict
pins the sha256 of the **post-fix** bytes, so what is certified is what will merge.

---

## 6. Residual risks (disclosed, not blocking)

1. **`effective_independent_obs = n_oos / h`** is a crude overlap adjustment. At h=22 it gives
   598.9 against 13,176 rows. The HAC-corrected DM is the actual inferential instrument;
   README §8.2 already flags h=22 as "the thinnest evidence in the table". Fine as reported.
2. **Loss-differential ACF(1) at h=22 is ~0.85** across all four h=22 tests. The `h−1 = 21`
   truncation and the data-driven bandwidth coincide there, so no second opinion on the
   bandwidth is available at the horizon that carries the headline. Reported honestly in the
   artifact (`loss_diff_acf1`), but a reader should treat the h=22 q-values as the least
   robust numbers in the experiment.
3. **The DL training-sample handicap** (§2.2) means the h=22 deficit is not cleanly separable
   from a sample-size effect. Now stated in §9 item 8.
4. **Finding A's artifact string remains uncorrectable** without a re-run. Anyone reading
   `K1814_results.json` directly, without the README, will see the broader claim. The README
   correction is the only available mitigation short of re-running.
5. **GPH/Hurst** are descriptive only, with a Hurst of 0.9802 that is implausible as a
   long-memory parameter for log RV. The artifact and README both explicitly disclaim these
   as non-inferential with no CI, and no claim rests on them.

---

## 7. Verdict

**PASS.** The frozen bytes implement the lookahead policy they claim, with a tight and
correct direct-h-step embargo and an exactly-disjoint fit/validation purge in the rolling
engine. Baselines share the DL arm's origins, embargo and evaluation rows, and the one
asymmetry runs against the DL arm. Every headline number re-derives from the artifact, the
BH-FDR correction reproduces exactly from scratch, and the negative null is stated at full
strength with the single positive result reported and correctly caveated. The two defects
found were in the write-up layer and are fixed.

`blocking_defects: []`.
