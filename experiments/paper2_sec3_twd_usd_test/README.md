# paper2_sec3_twd_usd_test — Paper 2 Sec 3 TWD/USD nested F-test backfill

- Experiment ID: `paper2_sec3_twd_usd_test`
- Status: completed (DRIFT_LARGE — paper number does NOT reproduce)
- Created At: 2026-05-12
- Paper: `paper/taiwan-vt/` (Section 3, body.tex L201)

## Motivation

Paper 2 (taiwan-vt) reproduce.py was at 92.9% traceable_match (need ≥95%
for review gate per `.claude/rules/paper-workflow.md` hard rule #2). One of
the 7 gap categories was a single number in body.tex L201:

> "The TWD/USD exchange rate does not add significant explanatory power
>  after controlling for VIX (p = 0.08)."

No backing experiment JSON existed. This experiment provides the formal
nested-regression backing.

## Method

**Test design** — nested OLS F-test (NOT bivariate Granger):

- Dependent: 0050.TW squared close-to-close log returns (percent²)
- Restricted (X_r): intercept + lagged VIX (level) at lags 1..5
- Full (X_f):       restricted + lagged TWD/USD log-change (%) at lags 1..5
- F-test joint significance of the 5 TWD/USD coefficients
- df_num = 5, df_denom = N − 11

The restricted-model RHS spec mirrors K1182's matched configuration where
F = 58.8, p < 0.001 (the F=58.8 number stated in the same paragraph of
body.tex L201). Using the same RHS family for the restricted model keeps
the nested test internally consistent with the paper's first claim in
that paragraph.

**Sample window**: 2014-01-09 to 2025-12-31 (N=2920). This mirrors K1182's
matched window where F=58.8 reproduced (K1182 README §"MATCHED"). The full
2008-2026 window collapses signal-to-noise because of the COVID-2020
volatility shock (K1182 already documents this).

**Lookahead guard**:

- All RHS columns use explicit `.shift(k)` for k in 1..MAX_LAG (see
  `build_design()` in `twd_usd_granger_test.py`).
- No contemporaneous regressors. Dependent is at time t; all regressors
  are strictly before t.
- Same lag specification on both restricted and full models (no asymmetry).

**Seed**: `numpy.random.default_rng(42)`. The analytic F-test is
deterministic; the rng is instantiated for any future bootstrap extensions.

## Result

| metric          | value                  |
|-----------------|------------------------|
| Primary F(5,2909)  | 0.3638              |
| Primary p-value    | 0.8735              |
| Paper's claim      | p = 0.08            |
| Delta              | +0.7935             |
| Verdict            | **DRIFT_LARGE**     |

### Sensitivity sweep (13 alternative defensible specs)

| spec                       | lag | F      | p      |
|----------------------------|-----|--------|--------|
| vix_lvl_twd_ret_lag1       | 1   | 0.198  | 0.656  |
| vix_lvl_twd_ret_lag3       | 3   | 0.375  | 0.771  |
| vix_lvl_twd_ret_lag5       | 5   | 0.363  | 0.874  |
| vix_lvl_twd_abs_lag1       | 1   | 0.159  | 0.690  |
| vix_lvl_twd_abs_lag3       | 3   | 0.599  | 0.616  |
| vix_lvl_twd_abs_lag5       | 5   | 0.448  | 0.815  |
| vix_lvl_twd_sq_lag1        | 1   | 0.101  | 0.751  |
| vix_lvl_twd_sq_lag3        | 3   | 0.449  | 0.718  |
| vix_lvl_twd_sq_lag5        | 5   | 0.389  | 0.857  |
| vix_sq_twd_ret_lag1        | 1   | 0.160  | 0.689  |
| vix_sq_twd_ret_lag5        | 5   | 0.418  | 0.837  |
| vix_sq_twd_sq_lag1         | 1   | 0.074  | 0.786  |
| vix_sq_twd_sq_lag5         | 5   | 0.434  | 0.825  |

**None** of the 13 defensible specs land within tolerance of the paper's
p = 0.08. Closest is `vix_lvl_twd_abs_lag3` with p = 0.616 (|delta| = 0.536).

## Conclusion — honest report (CLAUDE.md L46 research integrity)

The paper's p = 0.08 claim **does not reproduce** under any of 13
defensible specifications on the matched sample window. All specs reach
the same qualitative conclusion as the paper (TWD/USD does not add
significant power) but at a much weaker p-value (≥ 0.62 across all specs).

The *direction* of the paper's claim ("not significant") is correct —
TWD/USD genuinely fails to add explanatory power. But the *specific
p-value* 0.08 cited in the paper is unsupported by any defensible spec
checked here. Paper's 0.08 may have come from a different sample window,
a different regressor parameterization (e.g. squared TWD returns on a
specific sub-period), or a clerical error.

**Recommended action** (NOT executed here — this experiment only logs the
finding; main thread decides whether to amend paper):

1. Lowest-cost option: replace "p = 0.08" with a tolerance band like
   "p > 0.6 across robustness specifications" + cite this experiment.
2. Higher cost: erratum entry per `.claude/rules/paper-workflow.md` hard
   rule #4 ("数字不符处理三选一").
3. Reproduce.py change made in this commit treats the row as
   **CONFLICT_RESOLVED** (paper qualitative claim correct, specific
   number unsupported) — analogous to how K892 handles the
   0050.TW γ = 0.087 / t = 2.20 mismatch.

## Caveats

- The paper does not explicitly state the nested-regression spec. We
  inferred VIX-level restricted RHS from K1182's matched F = 58.8 claim
  in the same paragraph.
- Sample window 2014-2025 chosen to match K1182's matched window. The
  2008-2026 full window also produces p ≈ 1.0 (see initial commit's first
  run before sample fix); narrowing the window does not rescue paper's
  number.

## Data sources

- `paper/taiwan-vt/data/0050_tw_twii_2330_tw_2317_tw_2454_tw_0056_tw_spy_vix_2008-2026.csv`
  (pinned snapshot; 0050.TW + VIX close)
- `paper/taiwan-vt/data/_usdtwd_snapshot.csv` (PINNED 2026-05-12,
  fetched once with `auto_adjust=False` per
  `.claude/rules/paper-workflow.md` hard rule #1)

The USDTWD snapshot was fetched **once** via
`fetch_usdtwd_snapshot.py`. `twd_usd_granger_test.py` never makes a live
network call — all data is read from the pinned CSVs.

## Files

- `twd_usd_granger_test.py` — primary script (runnable standalone)
- `fetch_usdtwd_snapshot.py` — one-shot snapshot fetcher (refuses to
  overwrite without `--force`)
- `twd_usd_granger_test_results.json` — full results including sensitivity sweep
- `README.md` — this file

## Codex review

Codex CLI quota reset is 2026-05-13 02:46 UTC. After reset, this script
should be reviewed by `codex exec` with focus on:

1. Lookahead lag discipline (`.shift(k)` on all RHS features)
2. F-test degrees of freedom (df_num=5, df_denom=N-11)
3. Snapshot CSV is read-only (no live fetch)
4. p-value from `1 - scipy.stats.f.cdf(F, df_num, df_denom)` is correct

Fallback per K1259 lesson: `feature-dev:code-reviewer` subagent if Codex
unavailable; Gemini pro as second fallback.

## Success criterion (per task brief)

- estimated_p within ±0.05 of 0.08 → PASS
- otherwise DRIFT_SMALL / DRIFT_LARGE → **honest report** (this case:
  DRIFT_LARGE)
- reproduce.py exit 0 with new row bound to this JSON
- knowledge.json NOT touched (paper-update CLI path, not knowledge path)
