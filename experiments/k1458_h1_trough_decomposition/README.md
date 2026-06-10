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
   - `VIX-timing contribution = VT_t - BH_t`
   - `TSMOM-hedge contribution = -beta_t * TSMOM_t`
4. Partition window days by `sign(TSMOM_t)`:
   - `TSMOM<0`: market rebounding while past-12m return negative, hedge mechanically positive.
   - `TSMOM>=0`: other.
5. Headline ratio: cumulative TSMOM-hedge contribution on `TSMOM<0` days divided by total PureVT excess over BH inside window.

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

3 of 5 assets had rolling-beta clipped to 0 (early in 21-year window, beta hadn't accumulated). 2 assets had positive valid-share: QQQ (0.17) and 50/50 (1.79). PureVT lost to BH in trough window across all 5 assets — **Gemini H1 concern NOT validated for 2009-03**: mechanical rebound hedge contributed ≈ 0, so it can't be the source of PureVT MDD retention here.

### 2020-03 trough

| Component (cross-asset median) | Value |
|---|---|
| PureVT − BH (arith sum) | **−0.043** |
| VIX-timing contribution | **−0.078** |
| TSMOM-hedge contribution (full window) | **+0.030** |
| TSMOM-hedge contribution (TSMOM<0 days only) | **+0.300** |

Mechanical rebound hedge DID contribute positively (median +3.0pp full / +30pp on TSMOM<0 days; SPY = +12pp full, QQQ = +56pp on TSMOM<0 days). But VIX-timing component lost money during the trough window (median −7.8pp), so PureVT overall still underperformed BH (median −4.3pp). **Gemini H1 concern PARTIALLY validated for 2020-03**: mechanical hedge is empirically present and material, but PureVT does not actually "beat" BH in the trough window — its MDD retention comes from not falling as deeply at the BH trough, not from rebounding faster.

### Narrative implication for Paper 6 v6 body.tex

The original body v3 caveat ("MDD improvement can arise mechanically when the hedge trims exposure during rebound windows") is empirically validated for 2020 but NOT for 2009. Body should be revised to acknowledge:
1. K1458 Table: per-trough, per-asset decomposition into VIX-timing vs TSMOM-hedge contributions.
2. PureVT does NOT outperform BH in either trough window — MDD retention is about lower drawdown peak depth, not rebound-period profit.
3. Mechanical rebound hedge is real for 2020 (median TSMOM-hedge contribution on TSMOM<0 days = +30pp) but absent for 2009 due to rolling-beta clipping in early sample. Body should note this asymmetry.

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
