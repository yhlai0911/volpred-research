# K1314 — Graph Signal Processing HAR (GSP-HAR) Replication / Honest Test

## Motivation

Research backlog (research_program.md L285) flagged arXiv:2410.22706 "Graph Signal Processing Heterogeneous Autoregressive (GSP-HAR) Model" as frontier direction. Authors claim GSP-HAR "consistently outperforms HAR-type benchmarks and a GNN-based HAR" on 24 global indices.

We test the **simplified core idea** — does adding cross-asset graph-filtered RV as an extra HAR regressor produce a Harvey-significant QLIKE improvement vs standard HAR(1,5,22), or is this another methodology over-claim like the K530/K782 lesson (HAR's edge depends entirely on the RV proxy)?

**Hypothesis under test (H0)**: GSP-augmented HAR ≤ standard HAR at Harvey |t|>3 / DM-HLN 5% significance.

We *expect* a NULL — daily squared-return RV proxy is noisy, and per K530/K782 cross-asset spillover usually adds noise unless 5-min RV is available. A NULL is a legitimate, publishable result (research_program §6 — null result honest reporting).

## Method spec

### Data
- Tickers: SPY, QQQ, GLD, TLT, IWM (5 assets, US ETFs only — uniform calendar)
- Period: 2005-01-01 to 2024-12-31 (20 years)
- Source: yfinance (auto_adjust=False)
- RV proxy: daily squared log return, `rv_t = log(P_t/P_{t-1})^2`
  - Acknowledged inferior to 5-min realized variance, but consistent across assets and lookahead-safe.
  - This proxy known to handicap HAR (K782 lesson) — bias is *against* GSP-HAR also, so DM comparison remains fair.

### Models

**Baseline — Standard HAR(1,5,22) (Corsi 2009) in log-RV space:**
```
log(rv_{t+1}) = β0 + β_d·rv_t + β_w·mean(rv_{t-4:t}) + β_m·mean(rv_{t-21:t}) + ε
rv_pred_{t+1} = exp(Xβ)
```
Per-asset OLS, expanding window refit each day. Log-target follows Corsi (2009)
standard practice and is required to ensure positivity of QLIKE — a first-pass
linear OLS produces occasional large-negative predictions on equity-like assets
which catastrophically blow up QLIKE (observed in the K1314 v0 dry run; fixed).

**GSP-augmented HAR:**
```
rv_{i,t+1} = β0 + β_d·rv_{i,t} + β_w·mean5(rv_i) + β_m·mean22(rv_i)
           + γ_d·gsp_d(t)  + γ_w·gsp_w(t) + γ_m·gsp_m(t) + ε
```
where `gsp_*(t)` is the row-i entry of the graph-filtered cross-asset RV vector at the corresponding lag scale.

**Graph construction (simplified vs paper's DY+magnetic-Laplacian — see deviation note):**
- Compute Pearson correlation matrix of RV (one period) using **expanding window up to t-1 only** (lookahead-safe).
- For each asset, keep top-2 nearest neighbours (highest |corr|, excluding self).
- Build sparse 5x5 adjacency `A`; symmetrize via `(A + A^T) / 2`.
- Normalized graph Laplacian `L = I - D^{-1/2} A D^{-1/2}`.
- Low-pass filter: `H = exp(-tau * L)` with `tau = 1.0` (single fixed hyperparameter — no in-sample tuning to avoid p-hacking).
- Apply `H` to the per-period RV vector to get filtered signal, then take HAR-style daily/weekly/monthly aggregates.

### Out-of-sample evaluation
- Train: 2005-01-01 → 2019-12-31
- OOS: 2020-01-01 → 2024-12-31 (~1260 obs/asset, covers COVID + 2022 bear + 2024 rally)
- Walk-forward refit daily (expanding window).
- Random seed: 42 (used for any random init / shuffles; OLS is deterministic).

### Lookahead defenses
1. All HAR features use `rv_{t-1}` and earlier — `signal.shift(1)` baked into feature builder.
2. Graph correlation computed on **expanding window strictly < t** (no peeking).
3. Per-day refit uses data through t-1 only.
4. Final certification block in results JSON: `lookahead_free_certification`.

### Metric
- Per-asset QLIKE = `rv_true/rv_pred - log(rv_true/rv_pred) - 1` (Patton 2011, robust to RV proxy noise).
- Cross-asset average QLIKE.
- DM-HLN test (Harvey-Leybourne-Newbold 1997 small-sample correction) per asset + pooled.
- HAC SE via Newey-West (bandwidth = floor(n^(1/3))).

### Success criteria
- Implementation runs end-to-end, byte-traceable results JSON.
- DM-HLN reported honestly (sign + p-value + HAC-corrected t-stat).
- Verdict labeled: `PASS_HARVEY` if |t|>3 in ≥3/5 assets, `MARGINAL` if 5% but not 3σ, `NULL` otherwise.
- No over-claim — paper claims "consistently outperforms"; we test whether the simplest replication confirms this on US ETFs.

## Expected result (pre-registered)

Given (a) daily squared-return RV proxy noise, (b) simplified graph (Pearson 2-NN vs DY framework), (c) no learnable filter, (d) 5 US ETFs vs 24 global indices, we expect **NULL or MARGINAL**. A PASS would be surprising and warrant Codex re-verify.

## Deviations from paper

| Aspect | Paper (Yan et al. 2024) | This K1314 |
|---|---|---|
| Graph adjacency | DY framework + abs Pearson | Pearson top-2 k-NN (simpler) |
| Filter | Magnetic Laplacian + GFT + learned convex weights | Heat kernel `exp(-tau·L)`, fixed tau |
| Spectral domain | Real+imag with NN fusion | Spatial domain only |
| Universe | 24 global stock indices | 5 US ETFs |
| RV proxy | 5-min realized variance | Daily squared log return |

These simplifications make the test conservative — if even *this* simple GSP augmentation produces a positive DM, the full paper's claim is plausible. If NULL, the paper's gain may come from architectural complexity (learned filters, NN fusion) rather than the GSP idea itself.

## Multiple-testing and placebo robustness checks

Post-publication Codex source review (`paper_review_mile_81df26b0`, 2026-06-28)
flagged two inferential gaps in the original K1314 artifacts:

1. The five per-asset DM-HLN p-values were raw only.
2. The random-graph placebo was a single seed, not an empirical randomization
   distribution.

K1314 v2 fixes both issues without changing the model specification.

### Multiple testing

`k1314.py` now annotates each per-asset DM-HLN result with Bonferroni, Holm, and
Benjamini-Hochberg adjusted p-values over the 5-asset family. SPY remains
significant after all three corrections; QQQ, GLD, TLT, and IWM remain
non-significant.

| asset | raw p | Bonferroni | Holm | BH-FDR | conclusion |
|---|---:|---:|---:|---:|---|
| SPY | 7.60e-08 | 3.80e-07 | 3.80e-07 | 3.80e-07 | survives |
| QQQ | 0.3772 | 1.0000 | 0.6260 | 0.3772 | NS |
| GLD | 0.3130 | 1.0000 | 0.6260 | 0.3772 | NS |
| TLT | 0.1409 | 0.7043 | 0.5438 | 0.2348 | NS |
| IWM | 0.1359 | 0.6797 | 0.5438 | 0.2348 | NS |

The 14.1% SPY improvement is a raw QLIKE effect size, not an adjusted p-value.

### Random-graph placebo

Implementation issue worry: SPY DM t=5.41 was suspiciously strong. We now run
two placebo layers in `k1314_placebo.py`:

1. A seed=42 all-asset reference table, preserving the original K1314 sanity
   check.
2. A 100-seed SPY random-graph distribution using seeds 1..100.

The primary empirical placebo p-value compares SPY's real-graph QLIKE
improvement against the random-graph improvement distribution with +1 smoothing:
`p = (count(random >= observed) + 1) / (100 + 1)`.

| statistic | observed real graph | random mean | random median | random max | empirical p |
|---|---:|---:|---:|---:|---:|
| QLIKE improvement % | 14.065 | 4.421 | 4.055 | 14.245 | 0.0198 |
| mean loss reduction | 0.801 | 0.252 | 0.233 | 0.811 | 0.0198 |
| DM-HLN t | 5.409 | 1.901 | 1.783 | 4.562 | 0.0099 |

Interpretation: SPY is stronger than almost all random graphs, but one random
seed (`84`) slightly beats the real graph on raw QLIKE improvement. Therefore
SPY passes the DM-t placebo tail but **does not pass the pre-registered
p<0.01 effect-size placebo gate**.

The original seed=42 all-asset reference remains:

| asset | main DM t | seed=42 placebo DM t | diff | survives single-seed check |
|---|---|---|---|---|
| SPY | +5.41 | +2.69 | +2.72 | YES |
| QQQ | +0.88 | -2.53 | +3.41 | no (main NS) |
| GLD | -1.01 | +0.64 | -1.65 | no |
| TLT | +1.47 | +0.74 | +0.73 | no (main NS) |
| IWM | +1.49 | +4.30 | -2.81 | no (placebo wins) |

**Robustness read:** SPY is the only asset with a strong real-graph result, and
it survives multiple-testing adjustment. However, the 100-seed placebo shows
that random graph structure can occasionally match or slightly exceed the SPY
effect size. The correct language is therefore **SPY is a real-signal
candidate, not a fully placebo-confirmed result at p<0.01 on effect size**.
IWM in particular shows seed=42 placebo > main, strongly suggesting that much
of the favorable pooled DM t=3.73 is extra-regressor fitting, not graph
information.

## Final verdict

**MARGINAL with placebo caveat** — does not support the paper's
"consistently outperforms" claim under our simplified replication. SPY
result is statistically strong versus HAR and survives 5-asset multiple-testing
adjustment, but it is not fully confirmed by the 100-seed random-graph
effect-size placebo at p<0.01. 4/5 of the universe shows NULL or worse.

Honest interpretation: the GSP idea may have merit on broader universes with
cleaner (5-min) RV proxies and learned filters, but a minimal-config
single-fixed-tau heat-kernel + Pearson-2NN augmentation on a 5-ETF US panel
with daily-squared RV does not reliably beat standard HAR(1,5,22).

## Files
- `k1314.py` — main reproducible script
- `k1314_placebo.py` — random-graph placebo sanity check
- `k1314_results.json` — per-asset QLIKE + DM-HLN + placebo + certification
- `k1314_placebo_results.json` — placebo standalone output
- `k1314_qlike_chart.png` — bar chart (5 assets × 2 models)

## Related K
- K530 HAR Multi-Scale (HAR-RV strongest on |r| proxy)
- K782 HAR vs GJR (proxy more important than model — handicap warning)
- K783c regime-dependent window (expanding generally best)
- K1098/K1316 cross-market VIX channel NULL (parallel cross-asset NULL)
