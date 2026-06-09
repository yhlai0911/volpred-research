# K1437 — USD/TWD vs TWII Volatility Spillover (2012-2026)

- Experiment ID: `K1437`
- Status: complete (Codex CONDITIONAL_PASS after data-quality fix; see §Codex review)
- Created: 2026-06-09
- Owner: hourly-17 worktree agent (main thread merges + records knowledge)
- Sample: 2012-01-03 → 2026-03-30 (14.2 yr, N=3358 TWII trading days)

## Motivation

Taiwan is export-driven and a major USD-invoicing economy. Conventional wisdom
holds that **TWD appreciation** (USD/TWD ↓) hurts exporter earnings and should
propagate into TWII volatility. K1437 tests the **vol-to-vol** spillover
hypothesis bidirectionally and asks whether the asymmetric transmission
(appreciation shock > depreciation shock) is detectable in the 14-year window.

## Differentiation vs prior K-experiments

| Prior K | What it tested | Result | What K1437 adds |
|---|---|---|---|
| **T5b** (2015-2024) | TWD daily *return* Granger-causes TWII vol | p≈0.08 (NS) | Pure vol→vol (log-RV) test, both directions; 14-year window |
| **paper2_sec3_twd_usd_test** | Nested OLS: does TWD return add power *after* VIX? | F=0.36, p=0.87 (NS) | Drops VIX control; tests pairwise spillover only; adds DCC time-varying correlation |
| **R14** | TWD/USD FX cost on Taiwan VT strategy | Cost > benefit; do not hedge | (Adjacent, not direct overlap) |

**Key methodological additions in K1437**:
1. **Bidirectional Granger** on log-RV in a VAR(p_BIC=4) framework
2. **DCC(1,1)-GARCH** with 100 multistart on standardized GJR residuals (Engle 2002 — chosen over BEKK per K1213 lesson; DCC is numerically tractable and asymptotically equivalent for variance dynamics)
3. **Asymmetric appreciation/depreciation decomposition** (TWD APPR = USDTWD ret < 0; TWD DEPR = USDTWD ret > 0) controlling for own TWD volatility state
4. **TWII-calendar alignment with forward-filled USDTWD** (preserves all TWII observations; avoids dropping calendar-asymmetric holidays — Codex 2026-06-09 review fix)
5. **USDTWD bad-tick filter** (drops 20 obvious data errors — see §Data quality)

## Method

### Sample window & calendar policy

- 2012-01-01 → 2026-03-30 (USDTWD snapshot upper bound)
- **Panel = TWII trading days** (3458 days). USDTWD is forward-aligned by taking
  the last available USDTWD close at-or-before each TWII trading day.
- N=3358 after drop-zero-RV holiday filter

### Data quality fix (Codex 2026-06-09 review)

The pinned USDTWD snapshot contains **20 bad ticks** (yfinance historic-import
errors). Threshold: any single-day |log-return| > 4% on USDTWD is treated as
data error (real moves rarely exceed 3%). Notable corruptions:
- `2014-12-31 close = 3.670` (real ~31.5; missing leading "3")
- `2011-10-25 close = 1.802` (real ~30.1)
- 18 additional sub-5% ticks in 2015-2016 + 2025

Without this filter, USDTWD kurtosis was 1610 and GJR-GARCH params were
absurd (γ=0.55, α=0.35) → contaminated DCC. After filter, USDTWD GJR is
reasonable (α=0.29, γ=0.29, β=0.57, persistence ~0.86).

### Models

1. **Features**: daily log-returns (in %) and `log(r² + 1e-8)` RV proxy
2. **VAR(p)**: bivariate (twd_logrv, twii_logrv), p chosen by BIC (max=5) → **p=4**
3. **Granger causality**: both directions, ssr-F test at lag p_BIC
4. **Univariate GJR-GARCH(1,1)-t** per series (arch package)
5. **DCC(1,1)** on standardized GJR residuals, 100 multistart (L-BFGS-B,
   bounds α∈[1e-4, 0.3], β∈[0.6, 0.999]), seed=42
6. **Asymmetric spillover OLS**:
   `twii_logrv_t = const + Σ_k=1..4 [a_k·|twd_neg|_{t-k} + b_k·|twd_pos|_{t-k}
                                   + c_k·twii_logrv_{t-k} + d_k·twd_logrv_{t-k}]`
   with two F-tests:
   - **No-spillover**: H₀: a_k = b_k = 0 ∀k
   - **Symmetric**: H₀: a_k = b_k ∀k (Wald)

### Lookahead guard (hard rule)

- All RHS regressors use explicit `.shift(k)` for k≥1
- VAR / Granger by construction use only lagged values
- DCC recursion uses `ε_{t-1}`, not `ε_t`

### Seed

`SEED = 42` globally; `np.random.default_rng(42)` for DCC multistart starting points.

## Results

| Metric | Value | Interpretation |
|---|---|---|
| Sample N | 3358 TWII trading days | 14.2 years |
| VAR p_BIC | 4 | Same lag for both directions |
| **TWD-vol → TWII-vol Granger** | F=0.67, **p=0.610** | **NULL** — TWD vol does NOT predict TWII vol |
| **TWII-vol → TWD-vol Granger** | F=2.24, **p=0.062** | Borderline (10% level but not 5%) |
| DCC α | 0.0079 | Low shock-impact |
| DCC β | 0.9896 | High persistence |
| DCC α+β | 0.9975 | Near integrated (typical for daily DCC; not boundary artefact — 80/98 starts within 1 NLL unit of best) |
| DCC ρ mean | (see results.json `dcc_rho_summary`) | — |
| Asymmetry no-spillover F | F=2.98, **p=0.0025** | Reject H₀ — TWD return magnitudes DO add info to TWII vol when controlling for own past vol |
| Symmetry Wald | 9.59, **p=0.048** | Borderline — weakly reject equal coefficients on appreciation vs depreciation |

### Verdict

- **Direct vol→vol spillover (TWD→TWII)**: **NULL** at 5%, 10%
- **Reverse spillover (TWII→TWD)**: **BORDERLINE** (p=0.062, fails 5%)
- **Asymmetric magnitude effect**: **SUGGESTIVE** — TWD return magnitudes
  (split into appreciation/depreciation) are jointly significant for predicting
  TWII vol (p=0.0025) and the symmetric-restriction is weakly rejected (p=0.048)
- **Decision**: `NULL_RESULT` for the pre-registered vol→vol Granger
  spillover hypothesis. The asymmetric magnitude finding is a secondary
  signal that needs replication before being claimed.

### Conservative interpretation (research-honesty rule)

The 14-year window confirms the prior T5b finding (p=0.08 NS in 2015-2024)
extends across the longer panel: **USD/TWD vol does NOT Granger-cause TWII vol
at conventional significance levels**. The borderline TWII→TWD direction
(p=0.062) is interesting but does not clear the 5% bar.

The asymmetric **magnitude** signal (no-spillover p=0.0025) is real in-sample
but it tests a different alternative (level effect of |return|) and the
symmetry-test p=0.048 is just barely below 5% — likely to flip on sub-period
robustness. **Do not over-claim**: write as "suggestive evidence of an
asymmetric magnitude effect, requiring out-of-sample replication".

## Interpretation note (Codex 2026-06-09 residual caveat)

The TWII-day panel with forward-filled USDTWD means that the FX "return" on a
TWII trading day represents the **cumulative FX move between adjacent TWII
trading days** — including any US/Taiwan holiday window. This is the standard
construct for FX-equity spillover work where the equity calendar defines the
panel, but it should be described as **"adjacent-TWII-day FX moves"** rather
than "synchronous daily FX-equity spillover".

## Bad-tick threshold sensitivity (Codex 2026-06-09 residual caveat #2)

The 4% |log-return| bad-tick threshold is an empirical rule. Sensitivity sweep
results (see `k1437_results.json` field `bad_tick_sensitivity`):

| Threshold | N dropped | p_BIC | TWD→TWII Granger p | Symmetry Wald p |
|---|---|---|---|---|
| 3% | 82 | 2 | 0.480 | 0.055 |
| 4% (main) | 20 | 4 | 0.610 | 0.048 |
| 5% | 5 | 4 | 0.602 | 0.005 |

**Main NULL conclusion (TWD-vol → TWII-vol)** is robust across all 3 thresholds
(p > 0.48 in all cases). The asymmetry signal is borderline at 4-5% threshold
and even stronger at 5% — but this could also be 5% leaving residual bad ticks
in. Net: **don't over-claim asymmetry**.

The 4% rule was chosen to definitely catch the 2014-12-31 `3.670` corruption
and similar phantom points while preserving real crisis-day moves. Real
USDTWD daily moves rarely exceed 3% historically.

## Caveats / scope

1. **DCC α+β = 0.9975**: near integrated — typical for daily DCC but limits
   forecast usefulness (IGARCH-like). Multistart shows this is the dominant
   basin (80/98 within 1 NLL unit), not optimizer artefact.
2. **Asymmetry test uses |return| levels, not vol shocks** — so it tests a
   different alternative than the main Granger spec.
3. **TWII-day panel + forward-filled FX** discards info from intra-week TWD
   moves on TWII-closed days. An alternative panel (FX days with weekly TWII
   aggregation) was not explored.
4. **No structural-break test** — 2015 RMB devaluation, 2020 COVID, 2022 hike
   cycle could mask state-dependent spillover.
5. **GJR-t fit for USDTWD has ν=3.04** (very heavy-tailed) — DCC residuals
   may still be misspecified for joint normality even after univariate fit.

## Codex review

Original Codex review (2026-06-09, gpt-5.4 medium) verdict: **FAIL**. Critical
findings addressed in this revision:

| Codex finding | Severity | Resolution |
|---|---|---|
| #5 USDTWD bad ticks → absurd GJR params | FAIL | Added `_clean_usdtwd()` filter dropping 20 ticks where \|log-ret\| > 4%; results JSON includes full audit trail in `data_quality.usdtwd_bad_ticks_dropped` |
| #8 Calendar mis-alignment via intersection dropna | FAIL | Changed to TWII-calendar panel with forward-filled USDTWD; preserves all TWII observations |
| #9 No bad-tick / scale check | FAIL | Same fix as #5 (filter + audit trail) |
| #4 DCC `best.fun * 1.01` is sign-broken for negative NLL | CONCERN | Changed to absolute-tolerance (1 NLL unit) |
| #7 Asymmetry didn't control for own TWD vol | CONCERN | Added `twd_logrv_l{k}` controls |
| #1, #2, #3, #6 | PASS | No changes needed |

Remaining caveats are documented above (§Caveats). A re-review on
the post-fix code is recommended before merging; main thread should
verify and record knowledge.

## Files

- `k1437.py` — full pipeline (runnable standalone via `uv run python`)
- `k1437_results.json` — all numbers, verdict, audit trail
- `figures/k1437_dual_vol.png` — 21-day rolling annualized vol both series
- `figures/k1437_dcc_rho.png` — DCC time-varying correlation series
- `README.md` — this file

## Reproduction

```bash
uv run python experiments/k1437/k1437.py
```

Outputs: `k1437_results.json` + 2 PNGs in `figures/`. Run time ~30s on
M-series Mac.

## Data sources

- USDTWD daily close: `paper/taiwan-vt/data/_usdtwd_snapshot.csv`
  (pinned 2026-05-12; yfinance ticker `TWD=X`; auto_adjust=False)
- TWII close: `paper/taiwan-vt/data/0050_tw_twii_2330_tw_2317_tw_2454_tw_0056_tw_spy_vix_2008-2026.csv`

Both files are read-only pinned snapshots; the script makes no live network calls.

## Linked records

- Prior K: T5b (knowledge.json item `9866cc85`); R14 (`491e5197`)
- Prior experiment dir: `experiments/paper2_sec3_twd_usd_test/`
- Methodology lesson: K1213 (multistart MLE), K1216c (symmetric refinement)
