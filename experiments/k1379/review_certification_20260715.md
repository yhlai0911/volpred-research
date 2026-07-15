# K1379 independent review certification

- Reviewer: Codex CLI / gpt-5.6-sol / effort=ultra
- Reviewed at: 2026-07-15T17:01:32+08:00
- Worktree base commit: `30489d5dcb1e7d4ed8f15506bf68ed99c9056642`
- Verdict: **PASS**

## Exact final verdict

```text
VERDICT: PASS
BLOCKING: none
NON_BLOCKING: none
ONE_LINE: All scoped K1379 numerical, statistical, figure, and corrected-paper assertions are internally consistent and verified.
```

## Independent audit performed

- Re-derived all four saved-array QLIKE means, all six Bartlett-HAC DM statistics and p-values, loss-differential ACFs, lag-grid sensitivities, the Harvey-Leybourne-Newbold factor, the 1,849-date positive-forecast diagnostic, and the three floor-driving dates. Maximum discrepancy from `k1379_results.json`: zero at stored precision.
- Reconciled the hash-pinned source snapshot, unique dates, 1,854 OOS forecast dates, two zero-return exclusions, and 1,852 shared valid losses.
- Recomputed the six-test Bonferroni threshold as 2.6383 and checked the paper's validation-family scope.
- Exercised optimizer and OLS failure paths: unsuccessful or non-finite GJR/A4f fits, the A4f infeasible-objective penalty and invalid persistence, and rank-deficient HAR fits all fail closed; valid cases are accepted.
- Checked the K1379 README, figures, corrected Paper 9 section, and public-correction draft for numerical and directional consistency and for withdrawal of the former equivalence/non-inferiority claim.

## Frozen claim-surface SHA-256

| File | SHA-256 |
|---|---|
| `README.md` | `c02967529a8aa178ca4788251cfacfa9daa3daf8be1280cb1f3bc359b860ddec` |
| `k1379.py` | `efd9853704522517e909951d724b72e543d1493fa8eb5819321c9de4d1f28b47` |
| `k1379_general_article_chart.png` | `bcb0386fbd1986256a745fc61534e46fc8a99dd4782b027f12cb9409801909c8` |
| `k1379_hac_lag_sensitivity.png` | `34127298305934522551db02da2fda2c7de9ae90aad96550c0ccf2205b46bb16` |
| `k1379_results.json` | `bc430da7b03ba23a0090b246641a0a5899b712281c80dc8551befe1b844b8517` |

The claim surface was frozen after this review. Any later change to a hashed file requires recertification.
