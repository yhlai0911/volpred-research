# K1458 — Paper 6 v5 H1 Trough-Window Decomposition

## Motivation

Gemini v4 review (`paper/vt-trend-following/review_history/v5/README.md` §A H1) requires a **quantitative decomposition** of daily PureVT returns around MDD troughs (2009-03, 2020-03) to show whether the MDD retention of PureVT vs. Buy-and-Hold comes from:

- **VIX timing** (the VT component reducing exposure in high-VIX months), or
- **Mechanical TSMOM short-hedge** profiting during V-shaped rebounds when `sign(past-12m return) = -1` makes `TSMOM_t = -r_t` negative on positive rebound days, so `-beta * TSMOM_t > 0`.

Body v3 only added verbal caveat citing Daniel & Moskowitz (2016) — no empirical decomposition exists. This experiment closes that gap.

## Decomposition

For each of 5 canonical assets (SPY / 50-50 SPY+GLD / DIA / QQQ / IWM):

1. Find Buy-and-Hold drawdown trough date inside calendar windows 2008-06 → 2010-06 and 2019-06 → 2021-06.
2. ±63 trading-day window around trough.
3. Decompose `PureVT_t = VT_t + (-beta_t * TSMOM_t)`:
   - `VIX-timing contribution_t = VT_t - BH_t`
   - `TSMOM-hedge contribution_t = -beta_t * TSMOM_t`
4. Partition window days by `sign(TSMOM_t)`:
   - `TSMOM<0`: market rebounding while past-12m return negative, hedge mechanically positive.
   - `TSMOM>=0`: other.
5. Headline ratio: cumulative TSMOM-hedge contribution on `TSMOM<0` days divided by total PureVT excess over BH inside window.

### Decomposition identity (additive — clarified per v6 Codex CRITICAL)

Daily and window-aggregated identities are both strictly **additive** (sums of arithmetic returns):

```
Daily:    PureVT_excess_t  =  VIX_timing_contrib_t  +  TSMOM_hedge_contrib_t
Window:   sum(PureVT_excess) =  sum(VIX_timing)     +  sum(TSMOM_hedge_full)
```

**Important**: `VIX_timing_contrib` is **NOT equal to** `PureVT_excess_vs_BH`. The two are equal only in the degenerate case `TSMOM_hedge_full = 0` (i.e., beta clipped to 0 throughout the window). Reading any prior text that conflates the two is a documentation error; the JSON numbers themselves obey the additive identity above. Verifiable from `k1458_results.json`:

| Asset | Trough | `pure_vt_excess_bh_total_arith` | `vix_timing_total_arith` | `tsmom_hedge_total_arith` | Sum check |
|---|---|---|---|---|---|
| SPY | 2020-03 | +0.0377 | −0.0843 | +0.1220 | −0.0843 + 0.1220 = +0.0377 ✓ |
| QQQ | 2020-03 | −0.1102 | −0.1406 | +0.0304 | −0.1406 + 0.0304 = −0.1102 ✓ |

Per-asset windowed identity holds exactly because contributions are summed in arithmetic-return space (no log compounding inside the sum). Cross-asset *medians* do not preserve this identity (median is not a linear operator), so `cross_asset_summary` medians should be read componentwise, not added together.

## Output

`k1458_results.json` — per-asset × per-trough × per-partition cumulative arithmetic / log returns + cross-asset median share.

## How to interpret

**Note**: Codex 2026-06-10 audit FAIL'd the original headline-share ratio (numerator and denominator can have opposite signs, producing unbounded values; observed SPY 2020 = 9.18, 50/50 2020 = −6.93). Fix: report raw arithmetic contributions; share only computed when both num and den positive.

- Look at raw `pure_vt_excess_arith.median`, `vix_timing_arith.median`, `tsmom_hedge_full_arith.median`, `tsmom_hedge_on_tsmom_neg_days_arith.median` per trough.
- `valid_share_count == n_assets` → all assets have same-signed positive components, ratio interpretable.
- `valid_share_count < n_assets` → at least one asset has mixed signs; ratio unreliable, rely on raw contributions.

## Results (2026-06-10 run)

### 2009-03 trough

| Component (cross-asset median) | Value |
|---|---|
| PureVT − BH (arith sum) | **−0.050** |
| VIX-timing contribution | **−0.050** |
| TSMOM-hedge contribution (full window) | **+0.000** |
| TSMOM-hedge contribution (TSMOM<0 days only) | **+0.000** |

**Beta-clip evidence (per v6 Codex Finding 4 quantification)** — 3 of 5 assets (SPY, DIA, IWM) had `tsmom_hedge_total_arith = 0` across the full 127-day window. Because `hedge_t = -beta_t × TSMOM_t` and `TSMOM_t` is non-zero on most days, a window-wide hedge sum of exactly 0 implies `beta_t = 0` for every day in the window — consistent with the `.clip(0, 0.5)` operation in `k1458_h1_trough_decomposition.py:215` binding at 0 for assets whose rolling-beta lookback has not yet accumulated from the 2004-06-01 data start. The remaining 2 of 5 assets (50/50 SPY+GLD: +0.021; QQQ: −0.035) show partial beta accumulation. This is an **indirect** quantification — we do not store the beta path in `k1458_results.json`, so the conclusion is *conditional* on the assumption that a 127-day window-summed hedge of exactly zero arises only from beta-clipping (not from offsetting signed contributions; verified by per-asset partition `tsmom_neg_partition.tsmom_hedge.sum_arith_return = 0` for SPY/DIA/IWM, which confirms the all-zero pattern is not a sum-to-zero coincidence).

2 assets had positive valid-share: QQQ (0.17) and 50/50 (1.79). PureVT lost to BH in trough window across all 5 assets — **Gemini H1 concern NOT validated for 2009-03**: mechanical rebound hedge contributed ≈ 0 (for the 3 clipped assets) or had small offsetting contributions (50/50 +2.1pp, QQQ −3.5pp), so it cannot be the dominant source of PureVT MDD retention here.

### 2020-03 trough

| Component (cross-asset median) | Value |
|---|---|
| PureVT − BH (arith sum) | **−0.043** |
| VIX-timing contribution | **−0.078** |
| TSMOM-hedge contribution (full window) | **+0.030** |
| TSMOM-hedge contribution (TSMOM<0 days only) | **+0.300** |

Mechanical rebound hedge DID contribute positively (median +3.0pp full / +30pp on TSMOM<0 days; SPY = +12pp full, QQQ = +56pp on TSMOM<0 days). But VIX-timing component lost money during the trough window (median −7.8pp), so PureVT overall still underperformed BH (median −4.3pp). **Gemini H1 concern PARTIALLY validated for 2020-03**: mechanical hedge is empirically present and material, but PureVT does not actually "beat" BH in the trough window. The within-window arithmetic-sum negative result is consistent with PureVT's MDD retention coming from a shallower drawdown peak rather than from a faster rebound; however, K1458 does not directly decompose the synchronized PureVT/BH MDD path, so the "shallower peak, not faster rebound" reading is an **inference** from window-summed arithmetic contributions, not a direct path-level measurement.

### Narrative implication for Paper 6 v6 body.tex

The original body v3 caveat ("MDD improvement can arise mechanically when the hedge trims exposure during rebound windows") is empirically validated for 2020 but NOT for 2009. Body should be revised to acknowledge:
1. K1458 Table: per-trough, per-asset decomposition into VIX-timing vs TSMOM-hedge contributions.
2. PureVT does NOT outperform BH in either trough window (window-summed arithmetic returns are negative or near-zero). The interpretation that this reflects a shallower PureVT drawdown peak (rather than a faster rebound) is an **inference** consistent with the window arithmetic, not a direct synchronized-path measurement; body text should phrase it accordingly.
3. Mechanical rebound hedge is empirically present in 2020 (median TSMOM-hedge contribution on TSMOM<0 days = +30pp; 4/5 assets non-zero hedge) but **largely absent in 2009** for 3/5 assets, consistent with rolling-beta being clipped to 0 in early sample (see Beta-clip evidence above). The 2/5 unclipped 2009 assets show small offsetting contributions (50/50 +2.1pp, QQQ −3.5pp), so the asymmetry between 2009 and 2020 reflects mechanical hedge availability, not just market dynamics. Body should note this conditional caveat.

## Provenance

- Task: `paper_body_vtt_v6_fixes_round4_2026_06_10`
- Source for decomposition spec: `paper/vt-trend-following/review_history/v5/README.md` §A H1
- Strategy helpers reused verbatim from `experiments/k1192/k1192.py` (VT monthly rebalance, TSMOM factor, rolling-beta hedge — only the post-hoc trough decomposition is new).
- TSMOM lookback, VT numerator, data window all inherited from K1192 (so the decomposition references the same PureVT series whose MDD CI is reported in Table 3).

## Run

```
uv run python experiments/k1458_h1_trough_decomposition/k1458_h1_trough_decomposition.py
```

Or via compute_queue (heavy yfinance + rolling-beta on 21-year window):

```
uv run python scripts/compute_queue.py enqueue \
  --script experiments/k1458_h1_trough_decomposition/k1458_h1_trough_decomposition.py \
  --title "K1458 H1 trough decomposition (Paper 6 v5)" \
  --result-artifact experiments/k1458_h1_trough_decomposition/k1458_results.json \
  --followup-brief "Interpret k1458_results.json cross_asset_summary.median_share for 2009-03 and 2020-03 troughs. If median_share > 0.5 → support Gemini H1 concern (mechanical rebound dominates), recommend body.tex Section 3.x add quantitative decomposition table. If < 0.2 → reject Gemini H1 concern, recommend strengthen verbal caveat by citing this experiment. Update paper/vt-trend-following/review_history/v6/README.md with H1 closure verdict." \
  --followup-task-type paper_review \
  --timeout 1200
```
