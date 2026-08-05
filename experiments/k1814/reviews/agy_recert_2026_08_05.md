# Re-Certification Review: `experiments/k1814`

**Target Experiment**: `/Users/yhlai0911/volpred-research/experiments/k1814`  
**Reviewed Commit**: `5e3113ff6bb0177a05804b6a0922f17638643439`  
**Reviewer**: `gemini-3.6-flash / high effort` (agy review context; Codex quota exhausted until 2026-08-08)  
**Date**: `2026-08-05`  
**Verdict**: **PASS**

---

## Context & Background

Experiment `k1814` ("Does deep learning beat HAR at longer horizons? A boundary test on a daily realized-range proxy") originally carried a Stage 3 PASS verdict. Commit `aea1646fb` repaired the Diebold-Mariano HAC bandwidth calculation by introducing the canonical repository floor `max(h-1, ceil(h^(1/3) n^(1/3)))`. Commit `565606951` landed the complete 1.7-hour rerun output, updating `K1814_results.json`, `README.md`, and `fig3_dm_statistics.png`.

Because the pinned SHA256 hashes of the result artifact and figures drifted following the methodology repair and rerun, a formal re-certification was conducted against the current codebase and result bytes.

---

## Hash Verification

All 10 target files specified in the certification template were checked for SHA256 integrity:

| File Path | Expected SHA256 | Actual SHA256 | Status |
| :--- | :--- | :--- | :---: |
| `K1814_results.json` | `2fc91afa501ff2a477e5f41c9e30ad8f9a7d07f4d4978569d53cc091b9db761f` | `2fc91afa501ff2a477e5f41c9e30ad8f9a7d07f4d4978569d53cc091b9db761f` | MATCH |
| `README.md` | `8d3a0c7dc28e68cf3019d0b323aff5675fa0fa29c336bdb924116c93c6424776` | `8d3a0c7dc28e68cf3019d0b323aff5675fa0fa29c336bdb924116c93c6424776` | MATCH |
| `fig1_longmemory_regimes.png` | `643bb9efe1d36122922c16a25a85d0dc461c06f77c5c3cc8e27053f1ebaccc57` | `643bb9efe1d36122922c16a25a85d0dc461c06f77c5c3cc8e27053f1ebaccc57` | MATCH |
| `fig2_qlike_by_horizon.png` | `06ab80d31b044016ef9c4d9a0e888f4385ce17146c8b8d7e645c710f7763346d` | `06ab80d31b044016ef9c4d9a0e888f4385ce17146c8b8d7e645c710f7763346d` | MATCH |
| `fig3_dm_statistics.png` | `b7411b1de713baa3d260057f52d8fdae509c02e7a8c5392c529bca68db668e19` | `b7411b1de713baa3d260057f52d8fdae509c02e7a8c5392c529bca68db668e19` | MATCH |
| `fig4_forecast_vs_actual.png` | `ee8c631fa0283578cff2780302da7f63e649198c55b5a7445f7fbeaac07b02e0` | `ee8c631fa0283578cff2780302da7f63e649198c55b5a7445f7fbeaac07b02e0` | MATCH |
| `fig5_proxy_validation.png` | `50698259bd7c7e494064396c12efeacc4aee9f7cfb3bfff8cc12f4ff861a99fa` | `50698259bd7c7e494064396c12efeacc4aee9f7cfb3bfff8cc12f4ff861a99fa` | MATCH |
| `gate_history/b1a67269__k1814.py` | `b1a67269d6f645eb69e303fd0d80ecaeedf723a60078aa5d3a39398c48c71a3b` | `b1a67269d6f645eb69e303fd0d80ecaeedf723a60078aa5d3a39398c48c71a3b` | MATCH |
| `k1814.py` | `3b4c36711a758621cef21abcee6acc27c3c0504b252dd409b94d0c8734531860` | `3b4c36711a758621cef21abcee6acc27c3c0504b252dd409b94d0c8734531860` | MATCH |
| `render_readme_results.py` | `956db1553c69edc73343d0babbe373c0939277128a90b92b51f7017f9c7c0eeb` | `956db1553c69edc73343d0babbe373c0939277128a90b92b51f7017f9c7c0eeb` | MATCH |

---

## Detailed Check Findings

### (1) HAC Bandwidth Rule Verification
- **Specification**: `hac_lag = max(h - 1, math.ceil(h**(1/3) * n**(1/3)))`.
- **Audit Result**: Verified programmatically across all **204 Diebold-Mariano test dictionaries** in `K1814_results.json` (covering primary, robustness, and ablation arms).
- **Exact values for primary arm (`n = 13,176`)**:
  - `h = 1`: `max(0, ceil(1.000 * 23.619)) = max(0, 24) = 24` (was 0 pre-fix)
  - `h = 5`: `max(4, ceil(1.710 * 23.619)) = max(4, 41) = 41` (was 4 pre-fix)
  - `h = 22`: `max(21, ceil(2.802 * 23.619)) = max(21, 67) = 67` (was 21 pre-fix)
- Zero mismatches found across the entire artifact. `hac_lag_canonical_floor` also accurately records `math.ceil(h**(1/3) * n**(1/3))` for every entry.

### (2) Reconstruction of Pre-Fix Inference (`dm_hln_overlap_only`)
- **Audit Result**: `dm_hln_overlap_only` is genuinely identical to the pre-fix `lag = h - 1` statistic.
- **Implementation Check**:
  - For `h >= 2`: `nw_var(d, h - 1)` is called with the exact same small-sample Harvey-Leybourne-Newbold correction factor `corr` and Student's t degrees of freedom `n - 1`.
  - For `h = 1`: `np.var(d, ddof=0)` is called, which is mathematically identical to `nw_var(d, 0)` since the Newey-West loop over positive lags `1..lag` does not execute when `lag = 0`.
- No silent modifications to loss definitions, degrees of freedom, or small-sample factors were introduced. A reader can directly inspect `dm_hln_overlap_only` and `p_value_overlap_only` to reconstruct the unfloored pre-fix inference.

### (3) Movement of Statistics Across Horizons (`h=1`, `h=5`, `h=22`)
- **Audit Result**: The movement of DM t-statistics across all three horizons is completely consistent with the serial correlation of loss differentials measured by `loss_diff_acf1` and higher-order autocovariances:
  - **`h = 1` (`lag` 0 → 24)**:
    - `harl vs har`: `ACF(1) = -0.0048`, `|t|` moves `2.242 → 2.017`
    - `ar1 vs har`: `ACF(1) = -0.0009`, `|t|` moves `3.784 → 3.764`
    - `ridge_lags vs har`: `ACF(1) = +0.2500`, `|t|` moves `1.492 → 1.172`
    - `lstm vs har`: `ACF(1) = -0.0115`, `|t|` moves `0.980 → 0.897`
    - `transformer vs har`: `ACF(1) = +0.2580`, `|t|` moves `1.380 → 1.032`
  - **`h = 5` (`lag` 4 → 41)**:
    - Loss differentials exhibit positive persistence (`ACF(1)` from `0.04` to `0.56`). Expanding the bandwidth increases long-run variance estimates and shrinks `|t|` across DL-vs-baseline tests (e.g., `transformer vs har`: `|t|` moves `2.473 → 1.335`).
  - **`h = 22` (`lag` 21 → 67)**:
    - Loss differentials exhibit strong long-memory persistence (`ACF(1)` up to `0.89`). Expanding the bandwidth from 21 to 67 shrinks `|t|` consistently (e.g., `lstm vs har`: `|t|` moves `2.113 → 1.876`; `transformer vs har`: `|t|` moves `3.744 → 3.129`).
- Every statistic moves as expected under Newey-West variance estimation with positive higher-lag autocorrelation.

### (4) README & Figure Synchronization
- **Renderer Verification**: Executing `/Users/yhlai0911/volpred-research/.venv/bin/python render_readme_results.py --check` returns:
  `OK: README sections 7 and 8 match K1814_results.json`
  Sections 7 and 8 of `README.md` are 100% programmatically generated from `K1814_results.json`.
- **Figure Verification**: `fig3_dm_statistics.png` was regenerated in commit `565606951` and plots the exact floored DM-HLN statistics (`h=1`: 0.897, -1.032; `h=5`: -0.380, -1.335; `h=22`: -1.876, -3.129).

### (5) Overclaiming & Null-Result Prose Audit
- **Audit Result**: `README.md` maintains strict scientific discipline:
  - Explicitly states that the null result closes the horizon boundary question *specifically for these two architectures at these capacities on this daily realized-range proxy*.
  - Section 8.6 distinguishes between what is closed (`H1_short_horizon = FAIL_TO_REJECT`, `H2_boundary_exists = False`) and what is NOT claimed.
  - Section 9 enumerates 9 binding limitations (proxy noise, missing overnight gap, sparse refit cadence, holdout asymmetry).

### (6) Descriptive-Only Framing for Nested Pairs
- **Audit Result**: `build_verdict()` in `k1814.py` and `render_main()` in `render_readme_results.py` strictly scope inference to non-nested pairs (`lstm` or `transformer` vs linear baselines).
- Both pre-registered FDR families (`dm_vs_har` and `dm_vs_harl`) contain exactly 6 tests (3 horizons × 2 DL models).
- Nested comparisons (`harl`, `ar1`, `ridge_lags` vs `har`) are reported as descriptive QLIKE levels only and are never passed to FDR control, `build_verdict()`, or rendered as DM p-values.

---

## Repository Audit Gates

- `scripts/audit_dm_hac_lag.py`: **0 findings** for `k1814`.
- `scripts/audit_nested_dm_misuse.py`: **0 findings** for `k1814`.

---

## Final Certification Verdict

**PASS** — The rerun artifact, figures, and README prose are a faithful, accurate, and properly scoped account of the corrected experiment.

- **Blocking Defects**: `[]`
