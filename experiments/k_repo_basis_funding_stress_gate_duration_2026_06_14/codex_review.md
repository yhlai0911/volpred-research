# Codex Review: k_repo_basis_funding_stress_gate_duration_2026_06_14

Verdict: `PASS_AFTER_LOOKAHEAD_FIX_NULL_RESULT`

## Scope

Reviewed the repo-basis funding stress experiment artifacts that were produced in the same live task-pool window as the BNPL task: script, README, results JSON, and generated figures.

## Finding Fixed

Initial script version standardized SOFR-EFFR, SOFR-TGCR, and basis-short proxy with full-sample mean and standard deviation. That contaminates OOS forecasts because future feature distribution enters the stress index. I changed this to expanding z-score standardization and dropped the initial NaN warm-up period before fitting and plotting.

## Checks

- Experiment artifact completeness: PASS. README, script, results JSON, figures, and this review are present.
- Lookahead after fix: PASS for the audited issue. CFTC report dates are shifted to Friday release dates, targets use the next five trading days after release, and stress scaling no longer uses future sample moments.
- Randomness: PASS. Bootstrap uses `SEED=42`, `BOOTSTRAP_B=2000`, `BOOTSTRAP_BLOCK=8`.
- Formal tests: PASS. The script reports HAC coefficient tests, block-bootstrap coefficient sign tests, and expanding-window OOS QLIKE/DM comparisons.
- Claim strength: PASS. README now reports `NULL` after the lookahead-safe rerun and removes the prior reverse-sign conclusion.

## Current Result

After expanding-standardization rerun:

- `TLT`: beta `+0.0403`, HAC t `0.35`, bootstrap p `0.948`, QLIKE delta `-0.0054`, OOS R2 `-0.0240`.
- `IEF`: beta `-0.0351`, HAC t `-0.37`, bootstrap p `0.524`, QLIKE delta `-0.0011`, OOS R2 `-0.0216`.
- `ZN=F`: beta `-0.0567`, HAC t `-0.57`, bootstrap p `0.497`, QLIKE delta `-0.0018`, OOS R2 `-0.0168`.

Conclusion: NULL. The repo-basis funding stress proxy does not robustly predict next-week duration RV under lookahead-safe scaling.
