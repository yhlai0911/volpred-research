# Re-certification Review: `experiments/nfp_20260807_t2`

**Target Experiment**: `experiments/nfp_20260807_t2` in `/Users/yhlai0911/volpred-research`  
**Verdict**: **PASS**  
**Reviewer**: `agy` (Gemini 3.6 Flash High re-certification review; Codex quota exhausted until 2026-08-08)  
**Reviewed Commit**: `76c254bf09de9072975f8daca44af525f7658f4e`  
**Reviewed Code SHA256 (`nfp_20260807_t2.py`)**: `5a7e8b0ce8d59a9bbea36e2fbb3d3ad463fed4a7d8a2f31bb674778e3facaa37`  
**Date**: 2026-08-05  

---

## 1. Executive Summary

The experiment `experiments/nfp_20260807_t2` previously certified a `PASS` verdict. A CI ratchet test (`scripts/tests/test_canonical_stat_helper_ratchet.py`) subsequently failed because `nfp_20260807_t2.py` contained a local function definition `holm_adjust`, violating the project rule prohibiting private copies of shared statistical helpers.

To fix the ratchet failure, `holm_adjust` was deleted and replaced by a call to the canonical `volpred.stats.inference.holm_step_down`. Because this modified `nfp_20260807_t2.py`, its SHA-256 hash changed from `97a21197a109...` to `5a7e8b0ce8d5...`, requiring re-certification.

Following a strict audit of the code diff, algorithmic logic, numerical outputs, input validation, and artifact claims, **this change is confirmed to be genuinely inert with respect to every published number and scientific conclusion**. Re-running the experiment is unnecessary and `nfp_20260807_t2_results.json` remains completely valid.

---

## 2. Detailed Claim Verification

### (a) Algorithmic and Implementation Equivalence
We performed a line-by-line comparative analysis between the deleted local `holm_adjust` function and the canonical `volpred.stats.inference.holm_step_down` function:

1. **Step-Down Recursion & Rank Indexing**:
   - *Deleted copy*: Sorts key-value pairs by p-value ascending (`rank` from `0` to `m - 1`), multiplying each p-value by `(m - rank)`.
   - *Canonical helper*: Obtains indices via stable sort (`rank` from `0` to `family_size - 1`), multiplying each sorted p-value by `(family_size - rank)`. Both evaluate the identical scale factors for ranked p-values.
2. **Cap & Running Maximum**:
   - Both enforce `min(1.0, (m - rank) * p)` to bound adjusted values at 1.0.
   - Both maintain an accumulating running maximum (`running = max(running, candidate)` vs `running_max = max(running_max, candidate)`) to ensure monotonicity across the step-down sequence.
3. **Tie-Handling**:
   - *Deleted copy*: Uses Python's built-in `sorted(..., key=lambda item: item[1])`, which relies on Timsort (a stable sort algorithm). Equal p-values retain their initial dict insertion order.
   - *Canonical helper*: Uses `np.argsort(p_array, kind="stable")`, explicitly specifying stable sort. Equal p-values retain their initial vector order.
4. **Order and Key-Lookup Invariance**:
   - *Deleted copy*: Constructed and returned a dictionary with keys inserted in ascending p-value order.
   - *Canonical helper*: Returns `HolmStepDownResult` preserving caller input order. The caller constructs `holm_names = list(raw_pvalues)` and zips names with `adjusted_p_values`.
   - *Key Lookup*: Callers evaluate Holm values via dictionary key indexing (e.g. `holm[row["regime"]]`). In Python (and hash map semantics generally), dictionary lookups by key are strictly invariant to dictionary insertion/iteration order.

*Randomized Numerical Test*: A simulation of 2,000 randomized p-value vectors (including ties, edge cases 0.0 and 1.0, and varying family sizes) confirmed a maximum absolute difference of `0.0` between the old local function and the new canonical wrapper.

### (b) Input Validation Safety
The canonical helper `holm_step_down` enforces strict input checks:
- Inputs must be non-empty, finite, one-dimensional iterables.
- Every p-value must lie in the closed interval `[0, 1]`.

In `nfp_20260807_t2.py`, the p-values passed to Holm adjustment (`raw_pvalues`) are two-sided p-values derived from Newey-West OLS regressions across regime subsets (`hac_p_two_sided`). Standard regression p-values calculated from normal/t cumulative distribution functions are strictly finite numbers within `(0, 1)`. The actual raw p-values calculated in this experiment are `0.840983`, `0.070821`, `0.463246`, and `0.095642`. None will ever trigger a validation exception or behave differently under the canonical helper.

### (c) Recomputation of Published Artifact Values
We recomputed the Holm step-down adjustments directly from the raw `hac_p_two_sided` values stored in `nfp_20260807_t2_results.json`:

| Regime Cell | Raw `hac_p_two_sided` | Stored `hac_p_holm` | Recomputed `holm_step_down` | Absolute Diff |
| :--- | :--- | :--- | :--- | :--- |
| `<15` | `0.8409831802870074` | `0.9264911529393378` | `0.9264911529393378` | `0.000000e+00` |
| `15-20` | `0.07082122547891881` | `0.28328490191567524` | `0.28328490191567524` | `0.000000e+00` |
| `20-25` | `0.4632455764696689` | `0.9264911529393378` | `0.9264911529393378` | `0.000000e+00` |
| `>=25` | `0.09564207948335673` | `0.2869262384500702` | `0.2869262384500702` | `0.000000e+00` |

Every recomputed value matches the published JSON result down to double-precision machine epsilon (diff = `0.0`).

### (d) Scope of Claim Surface & Artifact Integrity
- **`nfp_20260807_t2_results.json`**: All statistical figures, sample counts, regression parameters, and limitation disclosures remain identical.
- **`README.md`**: Formatted table numbers (e.g. `0.926`, `0.283`, `0.926`, `0.287`) reflect the exact recomputed Holm values.
- **`nfp_20260807_t2_window.png`**: Plots return distributions and pre-event decompositions; it does not depend on Holm adjustments.
- **`nfp_20260807_t2_events.csv` & `nfp_20260807_t2_controls.csv`**: Data tables contain raw event and control return series, unaffected by inference adjustments.
- **Verdict & Conclusion**: The primary conclusion (`NULL_FAILURE_TO_DETECT`) is completely unaffected.

---

## 3. Final Certification Decision

- **Verdict**: **PASS**
- **Blocking Defects**: None (`[]`)
- **Action Required**: Update review verdict file with current commit and SHA256 identity as specified.
