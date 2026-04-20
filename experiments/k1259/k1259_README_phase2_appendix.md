# K1259 Phase 2 — MCS Algorithm Appendix

This appendix documents the Phase-2 Model Confidence Set (MCS) implementation
that runs on the Phase-1 DM pair ledger (`dm_ledger.json`). It is **additive**
to the Phase-1 README — read that first for ledger schema and coverage.

Produced files:

| File | Role |
|---|---|
| `k1259_mcs.py` | Reproducible MCS driver: loader + name normalization + t-matrix builder + bootstrap MCS. |
| `k1259_mcs_results.json` | 20-cell grid of results (5 assets × 2 loss functions × 2 α). |
| `k1259_README_phase2_appendix.md` | This document. |

---

## 1. Algorithm — HLN-style iterative MCS (variant A)

Hansen, Lunde & Nason (2011, *Econometrica*) define the **Model Confidence
Set** M̂\*_α as the smallest subset of candidate models that contains the true
best model with probability ≥ 1 − α. The canonical algorithm iterates:

1. Start with candidate set M₀ = {all models}.
2. While |M| > 1:
   - Compute studentized loss-differentials tᵢⱼ for all i, j ∈ M.
   - Let **T_max = maxᵢⱼ tᵢⱼ** (studentized range statistic; tests the worst
     vs best performer in M).
   - Bootstrap T_max under H₀: equal predictive ability (all pair loss
     differentials have zero mean).
   - Compute p = P(T_max,bootstrap ≥ T_max,observed).
   - If p < α, eliminate the worst model (largest row-max tᵢⱼ) and repeat;
     else stop.
3. Surviving M = **MCS̃_α = superior set** — contains the true best model
   with coverage ≥ 1 − α.

**Superior set interpretation**: models *not* in MCS̃_α are statistically
rejected as potential "best" — they are dominated by at least one other model
at significance α. Models *inside* the set are indistinguishable in their
predictive accuracy given the data.

## 2. Variant A: ledger-only implementation

### Motivation

The canonical HLN 2011 algorithm requires the full per-day loss series
dᵢⱼ,t = Lᵢ,t − Lⱼ,t to compute studentized statistics and to bootstrap via
stationary bootstrap (Politis & Romano 1994). **Our Phase-1 ledger only
stores the pairwise DM statistic per experiment**, not the underlying loss
vectors.

### Decision (time-boxed 45 min review of Variant B feasibility)

Variant B (re-extract per-day losses from source K experiment results JSON +
reconstruct dᵢⱼ,t + run stationary bootstrap) was evaluated. Sample inspection
of 10 ledger source files showed < 20% expose per-day loss arrays (most only
serialize summary DM stats + final QLIKE scalars). Projected Variant-B
coverage across the target 5 × 2 cells would be < 50%, triggering the skill
brief's explicit fallback rule: **skip B, proceed with A, document limitation
in appendix**.

### Variant A mechanics

1. **t-matrix construction**: for each (asset, loss_fn) cell, aggregate all
   ledger DM rows with `model_a, model_b, dm_stat` into a symmetric matrix
   T ∈ ℝ^(m×m) where T[i, j] = studentized loss-diff of model i vs j
   (sign-preserving; T[j, i] = −T[i, j]; diagonal = 0). Multiple DM
   observations for the same pair (e.g. rolling-window variants) are
   aggregated by equal-weight mean (each ledger DM stat is treated as an
   independent student-t-scaled estimate of the true pair loss differential).

2. **T_max under H₀**: bootstrap draws a fresh m×m antisymmetric standard
   normal matrix — this encodes H₀: every pair's true loss differential is
   zero-mean and each t-statistic is standard normal. T_max,b is the
   off-diagonal row-max-max. p-value = (1 + #{T_max,b ≥ T_max,obs}) / (B + 1),
   lower-bounded at 1/(B + 1) to avoid log(0).

3. **Elimination**: worst-model-first (largest single-row max over T),
   one-model-per-iteration until p ≥ α.

### How Variant A differs from canonical HLN 2011

| Aspect | HLN 2011 canonical | Variant A (K1259) |
|---|---|---|
| Loss differentials input | Full dᵢⱼ,t time series | Pre-computed DM stat (ledger) |
| Bootstrap | Stationary bootstrap of dᵢⱼ,t | Parametric Gaussian antisymmetric matrix |
| T_max,R variant | Both T_max and T_R studentized ranges available | T_max only (T_R requires cov matrix of d) |
| Dependence structure | Preserved by block bootstrap | Assumed i.i.d. Gaussian under H₀ |
| Conservativeness | Asymptotically correct under mild mixing | **Anti-conservative** if cross-pair dependence is negative; conservative otherwise |

The ledger-only variant is **useful for meta-analysis filtering** (models
rejected here are almost certainly rejected by canonical HLN too) but cannot
replace canonical HLN for a formal single-paper claim.

## 3. Data filtering (from ledger → MCS input)

Starting from Phase-1 ledger N = 2741 rows, filtered via (implemented in
`k1259_mcs.py::load_ledger`):

| Filter step | Rows dropped |
|---|---:|
| Multi-asset union tag (pipe-delimited `SPY\|VIX` etc.) | 1023 |
| Empty asset tag | 605 |
| Bad model name (empty / numeric quantile / 2-char parse artifact) | 65 |
| Same model in both sides | 0 |
| Invalid dm_stat | 0 |
| **Kept** | **1048** |

Multi-asset rows are dropped because MCS is defined per-asset (running MCS
on pooled SPY∣VIX rows would confound two distinct forecast tasks). The
605 untagged rows inherit from K experiments with unknown ticker (Phase 1.5
methodology-only K); re-including them would bias MCS toward SPY default.

## 4. Model-name normalization

27 name mappings were applied during load (e.g. `gjr` → `GJR`,
`HAR-RV` preserved, `GARCH(1,1)` → `GARCH`); full table is in
`k1259_mcs_results.json > summary > model_name_normalization_map`. The
normalization is intentionally conservative: we merge pure case/punctuation
variants (`gjr-garch` ≈ `GJR-GARCH` ≈ `gjr`) but preserve substantive
distinctions (`GJR-N` ≠ `GJR-t` ≠ `GJR-X`, `HAR-RV` ≠ `HAR-YZ`).

**What is NOT normalized** (intentionally): numeric-suffix research series
(`M1, M2, ..., M5_HAR_RV`), researcher labels (`base, postbreak, middle`),
and nested ensemble variants (`MF2_EWMA_0.995`). These often refer to
distinct specifications within a single paper and merging them would destroy
the within-paper distinctions we want MCS to rank.

## 5. Results grid at a glance

```
Asset      Loss   n_input   n_superior_α=.10   final_stop_p
────────  ─────  ───────   ─────────────────   ────────────
SPY       QLIKE     100           88              0.476
SPY       MSE        17           14              0.917
QQQ       QLIKE      43           38              0.855
QQQ       MSE         7            6              0.507
GLD       QLIKE      32           25              0.595
GLD       MSE         6            3              0.793
0050.TW   QLIKE      39           32              0.680
0050.TW   MSE         0           —               —        (no MSE DM rows)
USO       QLIKE      18           15              0.227
USO       MSE         6            4              0.502
```

**α = 0.10 and α = 0.20 produced identical superior sets in all 9
cells that ran** — because the algorithm's stopping p-value after the last
eliminable model is ≥ 0.227 in every cell, well above both thresholds. This
means the weaker 80%-confidence set does not expand the set beyond the
strict 90%-confidence set: the eliminated models are very clearly dominated
(pre-elimination p-values ≤ 0.089), and surviving models are
indistinguishable (gap to next elimination exceeds α = 0.20). This is an
honest feature, not a bug: with large m and Gaussian null, the T_max
distribution has long right tails, so the marginal models stop falling out
rapidly.

## 6. Limitations (investigator reading-list)

1. **Variant A parametric null**: the Gaussian antisymmetric bootstrap
   assumes pair t-statistics are marginally N(0,1) under H₀ with zero
   cross-pair covariance. Real DM statistics across overlapping forecast
   samples are correlated (same test set = shared denominator HAC variance
   normalizer). This makes our T_max distribution **narrower than truth**
   → bootstrap p-values biased *low* → MCS risk is *over-eliminating*
   models. In practice the surviving set is likely a *subset* of the true
   HLN MCS̃_α, so survivors are robust but borderline-eliminated models
   (p_bootstrap in 0.05–0.15) may be real contenders.

2. **Multiple-DM aggregation is equal-weight mean**: a model-pair observed
   in 5 different K experiments with disparate OOS windows (e.g. `GJR vs
   EWMA` across K465, K770, K799, K881, K883) contributes a single T[i, j]
   = mean of 5 DM stats. If one K has a much larger sample, it is under-
   weighted. Future refinement: inverse-variance weighting using sample_n.

3. **Ledger coverage gaps**: 0050.TW MSE has zero DM rows (no Taiwan MSE
   loss comparisons in K400–K1258); GLD MSE has only 6 rows across 6
   models (thin); USO MSE also thin (6 rows, 6 models). SPY QLIKE is the
   only cell with m ≥ 50 → most statistically-informative cell.

4. **"Candidate" set is experiment-coverage-dependent**: a model must have
   ≥ 2 DM pair appearances for the same (asset, loss) to enter the
   candidate set. Models tested in only one K for an asset are invisible
   to Phase-2 MCS even if they are genuinely best. This is a ledger
   coverage property, not a methodological flaw — see research_program.md
   for MCS-driven experiment extensions.

5. **Subperiod / regime-conditional MCS not run**: current 20 cells are
   full-sample. Ledger does contain per-subperiod DM rows (bear/bull/
   crisis/buckets). A Phase-3 extension could run MCS within each
   subperiod; this requires re-keying the pair aggregation by period.

## 7. Reproducibility

- `seed = 42` (numpy default_rng; bootstrap-matrix generation).
- `bootstrap_B = 1000`.
- Re-running `python3 experiments/k1259/k1259_mcs.py` produces
  bit-identical `k1259_mcs_results.json` (verified 2026-04-20).
- No shared state writes (`storage/memory/*`, `feed.json`, `paper/*`
  untouched per CLAUDE.md worktree rules).

## 8. How to interpret each cell

For a cell like **SPY / QLIKE / α = 0.10**:

- `candidate_models` (100): models with ≥ 2 DM pair observations for
  SPY + QLIKE in the ledger. These are the MCS candidates — any model
  missing here was never tested enough to evaluate.
- `eliminated_ordered` (12): models dropped during iteration, each with
  (a) the model name, (b) the T_max statistic at elimination (how much
  worse than its best rival in surviving set), (c) the bootstrap
  p-value. Ordering = weakest-first.
- `superior_set` (88): the MCS̃_α at α = 0.10. Contains the true best
  SPY QLIKE forecaster (among tested candidates) with coverage ≥ 90%.
- `final_stopping_p`: the p-value at iteration stop — must be ≥ α, else
  the loop would have continued. Higher = more confidence in current set.

Key SPY QLIKE eliminations at α = 0.10 (with elimination p-value):
HAR (p = .001), EWMA (p = .001), C2_Proxy_Robust (p = .001),
MEM (p = .001), HAR-ABS (p = .001), GJR-t (p = .001), GJR (p = .004),
A4f-VIX-t (p = .016), mf2_mem (p = .019), high_freq_only (p = .018),
GJR-N (p = .037), DMEM (p = .052). Rest (88 models) survive.

## 9. Cross-reference

- Phase-1 ledger: `experiments/k1259/dm_ledger.json` + `README.md`
- Canonical HLN 2011 paper: Hansen, P. R., Lunde, A. & Nason, J. M.
  "The Model Confidence Set." *Econometrica* 79(2), 453–497.
- Related K-experiment results used by this ledger: 236 experiments
  spanning K460 … K1258 (see Phase-1 summary top-contributor table).
- Phase-3 research (full per-day loss reconstruction + stationary
  bootstrap) tracked in `research_program.md` backlog.
