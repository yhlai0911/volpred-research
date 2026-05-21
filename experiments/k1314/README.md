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

## Placebo robustness check

Implementation issue worry: SPY DM t=5.41 was suspiciously strong. We ran a
random-graph placebo (`k1314_placebo.py`) — same architecture, but the graph
adjacency is replaced with a seeded random sparse symmetric matrix carrying
zero cross-asset correlation information. Any DM significance from this
placebo can only come from extra-regressor variance, not from real graph
signal.

Decision rule (encoded in `k1314.py`): asset is a "robust real signal" iff
`main_t > 3.0 AND main_t > placebo_t + 1.0`.

| asset | main DM t | placebo DM t | diff | survives |
|---|---|---|---|---|
| SPY | +5.41 | +2.69 | +2.72 | YES |
| QQQ | +0.88 | -2.53 | +3.41 | no (main NS) |
| GLD | -1.01 | +0.64 | -1.65 | no |
| TLT | +1.47 | +0.74 | +0.73 | no (main NS) |
| IWM | +1.49 | +4.30 | -2.81 | no (placebo wins) |

**Robust real signal: 1/5 (SPY only).** IWM in particular shows placebo > main,
strongly suggesting that 4/5 of the apparent gain (and the favorable pooled
DM t=3.73) is extra-regressor fitting, not graph information.

## Final verdict

**MARGINAL with placebo caveat** — does not support the paper's
"consistently outperforms" claim under our simplified replication. SPY
result is real (likely captures genuine US-equity cross-asset RV spillover
via the Pearson-2NN graph), but 4/5 of the universe shows NULL or worse.

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
