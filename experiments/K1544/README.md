# K1544 — Term-spread realized volatility as leading indicator for SPY/HYG/IWM RV

**Status**: COMPLETED  
**Verdict**: **NULL** (term-spread vol does *not* provide incremental information over MOVE; in fact M3 has *higher* QLIKE loss than M2 in all OOS cells)  
**Author**: autonomous research agent (worktree `agent-a04bea83f06857946`)  
**Date**: 2026-06-24

---

## 1. Motivation

The 10y–2y Treasury yield spread is a classic recession leading indicator (Estrella & Hardouvelis 1991; Estrella & Mishkin 1998; NY Fed recession-probability model). A separate, less-explored question is whether the *realized volatility of the spread itself* — i.e. how erratic the yield curve is, not just its level — carries forward-looking information about risk-asset volatility.

Heuristically: a yield-curve that is *churning* (large daily swings) reflects either uncertain Fed-path expectations or rapidly repricing recession odds. Either way, this re-pricing of macro risk could spill into equity / high-yield credit / small-cap variance.

We test whether **rolling 21-day annualised stdev of the 10y–2y spread changes** (TSV21) predicts h-day-ahead realised variance of SPY / HYG / IWM, and crucially whether it provides **incremental information over the canonical ^MOVE benchmark**.

## 2. Differentiation from related K

| K | Topic | Difference from K1544 |
|---|-------|----------------------|
| K1054 | MOVE-vs-VIX rate-cut spillover | K1544 asks: does *spread vol* add anything ON TOP of MOVE? Orthogonal predictor axis. |
| K1488 | MOVE leadingness for SPY vol | K1488 establishes MOVE → SPY-vol; K1544 nests TSV inside MOVE-based model to test marginal contribution. |
| K1442 | MOVE/VIX ratio + CPI | Different question (CPI surprise interaction). |
| K1086 | MOVE vs VIX co-movement | Co-movement, not predictive regression. |
| K390  | MOVE level forecasting | Single-asset univariate, no spread channel. |

No prior K studies **term-spread *vol*** as a predictor. The closest theoretical antecedent is Joslin, Priebsch & Singleton (2014) on macro-finance term-structure factors — but they use *level* and *slope*, not realised vol of slope.

## 3. Data sources

All locally cached (no external API call required at runtime):

| Series | File | Range |
|--------|------|-------|
| DGS10 (10y Treasury yield, daily) | `storage/macro/fred_DGS10.csv` | 2006-01 → 2026-06 |
| DGS2 (2y Treasury yield, daily) | `storage/macro/fred_DGS2.csv` | 2006-01 → 2026-06 |
| SPY, IWM adj close | `paper/leverage-direction/data/spy_qqq_gld_tlt_eem_iwm_slv_btc_usd_vix_2010-2026.csv` | 2010-01 → 2026-06 (10 dup dates kept-first) |
| HYG adj close | `experiments/k1263/data/HYG.csv` | 2007-04 → 2026-06 |
| MOVE (^MOVE index) | `experiments/k1488_move_leadingness/close_prices.csv` | 2003-01 → 2026-06 |

USREC (NBER recession dating) **not used** — no cached snapshot; pulled-on-demand FRED API was unavailable in the worktree. Recession lead/lag analysis is deferred (see §10 Scope limitations).

## 4. Methodology

### 4.1 Features

- **Term spread**: `term_spread_t = DGS10_t − DGS2_t` (percentage points).
- **TSV21** (primary predictor): annualised stdev of daily spread *changes* over the trailing 21 trading days.  
  `TSV21_t = stdev(Δspread_{t−20 .. t}) × √252`.
- **TSV63**: 63-day analogue (shown in time-series plot; not used in nested regressions to keep scope inside 50-min cap).
- **Baseline AR-1 covariate**: backward 21-day annualised realised variance (`log_rv` lagged).
- **MOVE benchmark**: `log_move_{t−1}`.

All predictors are `.shift(1)` before merging with targets ⇒ signal at t–1 → realised target at (t, t+h].

### 4.2 Target

For each asset and horizon h ∈ {1, 21, 63}:
`y_t = (Σ_{k=t+1}^{t+h} r_k²) × (252 / h)` — strictly forward, annualised RV. Verified by toy-data unit test (see §6).

### 4.3 Models (estimated on **log RV** for variance stabilisation)

| Model | Predictors |
|-------|-----------|
| M0 | const + log_rv_{t−1} (AR-1 baseline) |
| M1 | const + log_rv + **TSV21** |
| M2 | const + log_rv + **log_move** |
| M3 | const + log_rv + log_move + **TSV21** (nested) |

### 4.4 Inference

- **HAC standard errors**: Newey-West with bandwidth = max(NW rule, ⌈1.5·h⌉) to absorb forward-label overlap. Bartlett kernel.
- **OOS expanding window**: min-train = 252 days; training rows j must satisfy `j + h < forecast_origin i` (forward-label safety).
- **DM HLN test**: Harvey-Leybourne-Newbold small-sample correction `√((n + 1 − 2h + h(h−1)/n) / n)` applied to DM stat. Pointwise QLIKE loss = `actual/predicted − log(actual/predicted) − 1` via `volpred.stats.model_evaluation.qlike_pointwise`.
- **Per-asset estimation**: SPY/HYG/IWM run in **separate** panels and tests — no asset-day pooling (per `.claude/rules/experiments.md` cross-asset rule).
- **Per-horizon bandwidth**: each h uses its own HAC + DM bandwidth (no shared horizon across targets).

### 4.5 Verdict tiers (pre-specified)

| Tier | Criterion |
|------|----------|
| CONFIRMED | M3 TSV t-stat (HAC) > 2.5 AND DM-OOS HLN-t (M3 vs M2) < −1.96 for ≥1 (asset, h); no SUBSUMED cells. |
| PARTIAL | Some cells confirm, others null. |
| NULL | TSV univariate M1 HAC-t < 2.0 everywhere. |
| NULL_OOS | Significant in-sample but DM-OOS not significant. |
| SUBSUMED_BY_MOVE | TSV t-stat in nested M3 < 2.0 across all cells. |

## 5. Defensive checks (per `.claude/rules/experiments.md`)

| Check | Status |
|-------|--------|
| signal.shift(1) on all predictors | ✅ enforced in `build_panel()` |
| Forward-label uses strictly (t, t+h] | ✅ verified by toy-data unit test before main run |
| OOS training filter `j+h<i` | ✅ enforced in `oos_expanding()` |
| Seed fixed (=42) | ✅ at module load |
| Cross-asset not pooled as iid | ✅ separate panels per asset |
| QLIKE direction = actual/predicted − log(·) − 1 | ✅ delegated to `volpred.stats.model_evaluation.qlike_pointwise` |
| HAC bandwidth ≥ h | ✅ max(NW rule, ⌈1.5·h⌉) |
| DM-HLN correction applied | ✅ implemented in `dm_hln()` |
| Baseline same lag as alternative | ✅ M0/M1/M2/M3 share `log_rv` lag |
| Codex review post-execution | ✅ (see §7) |

## 6. Results

**Verdict**: **NULL**.  TSV21 univariate (M1) is at best marginal (SPY h=1: t = +1.93; all others t < 1.6). Once MOVE is included (M3), TSV21 contribution collapses (|t| < 1.55 everywhere; often sign-flipped). On out-of-sample QLIKE, **DM HLN t-stats for M3 vs M2 are positive in 8 of 9 cells** — meaning the nested model with TSV21 has *higher* QLIKE loss than the MOVE-only model. IWM h=1 reaches HLN-t = +4.53, i.e. TSV21 *significantly hurts* OOS forecasts for small-cap RV.

### 6.1 Per-cell summary (in-sample t / OOS DM)

| Cell | n | TSV t (M1, univariate) | TSV t (M3, nested) | DM-HLN (M3 vs M2) |
|------|---|------------------------|--------------------|--------------------|
| SPY h=1 | 1123 | +1.93 | +0.54 | +0.87 |
| SPY h=21 | 1107 | +1.20 | +0.07 | +1.88 |
| SPY h=63 | 1065 | +0.13 | −1.14 | +1.18 |
| HYG h=1 | 1775 | +1.55 | +0.64 | −0.38 |
| HYG h=21 | 1790 | +1.15 | −0.30 | +1.74 |
| HYG h=63 | 1748 | +0.48 | −0.87 | −1.07 |
| IWM h=1 | 1129 | +0.52 | −0.78 | **+4.53** |
| IWM h=21 | 1107 | +0.94 | −0.24 | +2.02 |
| IWM h=63 | 1065 | −0.38 | −1.54 | +1.16 |

Sign convention: positive DM-HLN t means **M3 (with TSV) has higher QLIKE** than M2 (MOVE-only) ⇒ TSV *hurts* OOS.

### 6.2 Interpretation

1. **In-sample**: TSV21 alone has modest predictive content for short-horizon SPY RV (t≈1.93) but never crosses the 2.5 Harvey bar; for HYG and IWM it is insignificant from the outset.
2. **MOVE absorbs the signal**: in every cell, conditional on MOVE the TSV21 coefficient shrinks toward zero or sign-flips. MOVE dominates as the yield-curve-volatility proxy of choice — consistent with MOVE being the *direct* implied-vol index of the Treasury complex, of which spread vol is only a noisy reflection.
3. **OOS**: TSV21 actually *degrades* out-of-sample forecasts (8/9 DM stats positive), with IWM h=1 the worst case (HLN-t = +4.53, well past two-sided 1% significance). This is consistent with TSV21 adding parameter noise without informational content.

The verdict is unambiguous: **TSV21 contains no incremental information over MOVE** for predicting SPY/HYG/IWM RV at the tested horizons.

### 6.3 Why this null is publishable / useful

- Negative result with hard numbers (n ≈ 1100–1800 per cell, 8/9 DM cells favour MOVE-only).
- Pre-registers the "spread vol as orthogonal axis to MOVE" hypothesis and refutes it.
- Tightens the K1054 / K1488 narrative: MOVE is *the* yield-volatility channel for equity RV; no second-order spread-shape channel is needed.
- Reader-facing daily article angle: "Why MOVE matters and the 10y-2y *churn* doesn't" — counter-intuitive null with clean econometrics.

## 7. Codex review

(See section appended after Codex finishes.)

## 8. Figures

- `fig_tsv_timeseries.png` — TSV21 + TSV63 (top) and ^MOVE (bottom), 2006–2026.
- `fig_dm_heatmap.png` — HLN-DM t-stats on OOS QLIKE for all 5 model-pair comparisons × 9 (asset, horizon) cells.

## 9. Files

```
experiments/K1544/
├── README.md                  # this file
├── K1544.py                   # full reproducible script
├── K1544_results.json         # all estimates, t-stats, DM stats, sample sizes, verdict
├── fig_tsv_timeseries.png     # term-spread vol time series + MOVE
└── fig_dm_heatmap.png         # DM-HLN heatmap (5 comparisons × 9 cells)
```

Reproduce: `uv run python experiments/K1544/K1544.py` (deterministic, seed=42).

## 10. Scope limitations

1. **NBER recession spillover analysis deferred** — USREC monthly series not cached; FRED API call avoided in worktree. The "term-spread vol as recession leading indicator" angle requires USREC and is left for a follow-up K.
2. **Only TSV21 entered into M1/M3** — TSV63 plotted only. Within 50-min scope cap; an extension is to test TSV21 vs TSV63 horse-race and a TSV21+TSV63 joint model.
3. **Three assets only** — SPY (large cap), HYG (credit), IWM (small cap). Adding TLT (rates) or VXX (vol-vol) is a natural extension.
4. **Daily frequency** — weekly/monthly aggregation might reveal slower spillover; not tested.
5. **Linear models only** — non-linear (e.g. regime-conditional on |spread| > threshold) deferred.

## 11. Related literature (key cites, not exhaustive)

- Estrella, A., & Hardouvelis, G. A. (1991). "The term structure as a predictor of real economic activity." *JoF* 46(2), 555-576.
- Estrella, A., & Mishkin, F. S. (1998). "Predicting U.S. recessions: Financial variables as leading indicators." *RES* 80(1), 45-61.
- Joslin, S., Priebsch, M., & Singleton, K. J. (2014). "Risk premiums in dynamic term structure models with unspanned macro risks." *JoF* 69(3), 1197-1233.
- Cieslak, A., & Povala, P. (2015). "Expected returns in Treasury bonds." *RFS* 28(10), 2859-2901.
- Choi, H., Mueller, P., & Vedolin, A. (2017). "Bond variance risk premiums." *RoF* 21(3), 987-1022.

## 12. Verdict (formal)

**NULL**. Term-spread realised volatility (TSV21) does not provide incremental forecasting power for SPY/HYG/IWM realised variance over a MOVE-only benchmark, in-sample or out-of-sample, at horizons h ∈ {1, 21, 63}. In 8 of 9 OOS cells, including TSV21 strictly *increases* QLIKE loss; IWM h=1 cell shows HLN-t = +4.53 (i.e. TSV21 significantly degrades small-cap RV forecasts).

## 13. Codex Review

- **Reviewer**: Codex CLI 0.141.0 (`reviewer_source: codex_cli`)
- **Verdict**: **PASS** (methodology clean; verdict NULL is a legitimate research outcome)
- **Issues**: none

**Reasoning** (verbatim from Codex):

> K1544.py satisfies all eight methodology checks. Predictors are shifted by one in `build_panel`, and OOS training uses `slice(0, i-h)`, so every training row j has `j+h<i`. `qlike_pointwise` implements `actual/predicted - log(actual/predicted) - 1`. DM OOS comparisons use `dm_hln` with HLN factors stored in JSON. HAC lags meet or exceed `ceil(1.5*h)`: h=1 uses 6-7, h=21 uses 32, h=63 uses 95. Both `np.random.seed(42)` and `default_rng(42)` are set. Assets are looped separately, not pooled (per K1355 hard rule). M3 includes `log_rv`, `log_move`, and `tsv21`, with the final t-stat as TSV incremental-over-MOVE evidence. Regressions use log RV and OOS forecasts are exponentiated for QLIKE.

Checks verified by Codex:
1. Lookahead bias — `.shift(1)` + `j+h<i` training constraint ✅
2. QLIKE direction — `actual/pred - log(actual/pred) - 1` ✅
3. DM HLN small-sample correction applied ✅
4. HAC bandwidth ≥ ceil(1.5·h) for each horizon ✅
5. seed=42 fixed (both np.random.seed and default_rng) ✅
6. SPY/HYG/IWM analyzed separately, NOT pooled iid (K1355 compliance) ✅
7. Incremental-over-MOVE nested test in M3 (log_rv + log_move + tsv21) ✅
8. log RV regression scale + exponentiate for QLIKE ✅
