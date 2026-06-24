# K1545 — Carbon Auction Regime Events as KRBN RV Event Prior

**Status**: PRELIMINARY (n_events = 25 < 50 ⇒ insufficient power for PASS per task brief)
**Run date**: 2026-06-24
**Author**: K1545 (worktree agent, hourly-08)
**Codex review**: see `codex_review.md` (run with `codex --version 0.141.0`, ChatGPT auth)

## Motivation

K1445 was a descriptive PoC on URA / KRBN volatility clustering (static GARCH(1,1) +
cross-asset correlation). It established that KRBN is a regime-dependent diversifier
but did not test whether **primary-market carbon auction events** are a predictive
prior for forward realized volatility.

K1545 fills that gap with a **forward event study**: do EU ETS / CCA / RGGI regime
events (auction calendar shifts, MSR releases, suspensions, supply-cap reforms)
predict elevated t+1 .. t+5 realized vol in KRBN / GRN / KCCA and spillover into
energy-sector ETFs (XLE / XLU)?

## Differentiation vs K1445

| Dimension | K1445 | K1545 |
|-----------|-------|-------|
| Purpose | descriptive | event-prior / forward-RV |
| Assets | URA, KRBN, SPY, TLT | KRBN, GRN, KCCA, XLE, XLU |
| Method | GARCH(1,1), static ρ | event-study pre/post fwd-5d RV |
| Forward labels | none | strictly post-event RV with lookahead guard |
| Event prior | none | hand-coded EU ETS / CCA / RGGI regime events |

## Data

| Series | Source | Range | n |
|--------|--------|-------|---|
| KRBN  | yfinance (auto_adjust) | 2020-07-31 → 2026-06-23 | 1480 |
| GRN   | yfinance | 2019-09-18 → 2026-06-22 | 1698 |
| KCCA  | yfinance | 2021-10-05 → 2026-06-23 | 1183 |
| XLE   | yfinance | 1998-12-22 → 2026-06-23 | 6916 |
| XLU   | yfinance | 1998-12-22 → 2026-06-23 | 6916 |
| EU ETS / CCA / RGGI regime events | hand-coded `data/eu_ets_regime_events.csv` | 2019-01 → 2025-09 | 25 |

### Data limitation (degradation reported per brief)

Original brief asked for **demand-depth** and **reserve-price bindingness** time
series from EU ETS primary auctions (EEX). EEX per-auction microstructure CSV is
**paywalled** and the World Bank Carbon Pricing Dashboard API returns 403 to
unauthenticated requests. We attempted the following public sources, all blocked:

- EEX auction page: 404
- EEX-transparency: 404
- Sandbag CSV mirror: 403
- WB Carbon Pricing Dashboard API: 403

We degraded to a **regime-event proxy**: hand-coded list of publicly documented
EU ETS / CCA / RGGI events (MSR launch, REPowerEU front-load, EU ETS revision,
ETS2 political agreement, MSR intake-rate change, CARB / RGGI quarterly auction
settlement dates). Hand-coded entries are tagged with `source_class`
(EU_ETS / CCA / RGGI / OTHER) and `source_note`. **Per task brief**: 25 events
< 50 ⇒ verdict capped at **PRELIMINARY** regardless of statistical significance.

## Method

1. Build daily log-returns from `auto_adjust=True` adjusted close.
2. Past-RV at date t = std of returns over `[t-4, t]` × √252 (annualized).
3. Forward-RV at date t = std of returns over `[t+1, t+5]` × √252 (this is
   `rv_past.shift(-5)`; strictly post-event).
4. For each event date e, align to next trading day t:
   - **Baseline (pre)**: mean of past-RV over the 24-obs window `[t-29, t-6]`
     (implemented as `.iloc[:-6].tail(24)`; nominal outer bound is 30 days, but
     actual obs count is `30-6 = 24` trading days). Strictly pre-event, excludes
     the 5 trading days just before t to avoid leakage from the event-window
     rolling-vol estimator.
   - **Event (post)**: forward-5d RV at date t (returns at `t+1..t+5`).
   - **Diff** = post − pre.
5. Per asset: Newey-West HAC SE (lag=5), two-sided z-test, Bonferroni across 5
   asset hypotheses; 10k bootstrap CI for diff mean.
6. Cross-asset: per-date mean of diff across KRBN/GRN/KCCA (one obs per event date)
   → HAC on date series (per K1355 hard rule: never stack asset-day).
7. Gap risk: |return[t+1]| around events vs baseline mean |return|.

## Lookahead audit

| Check | Pass? | Evidence |
|-------|-------|----------|
| Event-day RV uses strictly future returns | ✓ | `rv_past.shift(-5)` → returns `[t+1..t+5]` |
| Baseline uses strictly past returns | ✓ | `iloc[:-PRE_WINDOW[1]].tail(PRE_WINDOW[0]-PRE_WINDOW[1])` excludes `[t-5..t]` |
| Event indicator at t uses info ≤ t-1 | ✓ | event dates are public-news dates; forward window starts at t+1 |
| Bootstrap / random seeds fixed | ✓ | `RNG_SEED = 20260624` (all `np.random.default_rng(seed)`) |
| Cross-asset aggregation before HAC | ✓ | `cross_asset_aggregated_test`: per-date mean, then HAC on date series |
| No expanding-window estimator on forward returns | ✓ | event study uses no learned model |
| K1355 stacked-asset-day avoided | ✓ | per-date aggregation enforced |

## Results

Source: `k1545_results.json`.

| Asset | n | Δ (post−pre) | 95% boot CI | NW-t | p_raw | p_Bonf |
|-------|---|--------------|-------------|------|-------|--------|
| KRBN  | 22 | +0.0377 | [-0.0164, +0.1098] | 1.44 | 0.149 | 0.747 |
| GRN   | 24 | +0.0633 | [-0.0096, +0.1493] | 1.54 | 0.124 | 0.617 |
| KCCA  | 20 | +0.0093 | [-0.0718, +0.0867] | 0.25 | 0.805 | 1.000 |
| XLE   | 25 | -0.0432 | [-0.1473, +0.0514] | -1.86 | 0.062 | 0.312 |
| XLU   | 25 | -0.0153 | [-0.0578, +0.0262] | -1.60 | 0.110 | 0.548 |

**Cross-asset aggregated (KRBN/GRN/KCCA, per-date)**: n_dates=24, Δ=+0.0531,
NW-t=1.81, p_raw=0.071, mean asset-count per date = 2.75. **Not
Bonferroni-protected** (single hypothesis at aggregated level), so this is the
strongest signal but still PRELIMINARY. Asset-count per date < 3 for early
events because KCCA inception is 2021-10-05 — events before that date contribute
only KRBN + GRN to the cross-asset mean. This is acknowledged in
`results.json.cross_asset_aggregated.n_assets_per_date_mean`.

**Gap risk** (|ret[t+1]| event vs baseline):
- KRBN: 0.01285 vs 0.01291 baseline (ratio 1.00, p=0.98) — no gap effect
- GRN: 0.01943 vs 0.01825 baseline (ratio 1.06, p=0.72) — small upward, not sig

**Sector spillover (XLE / XLU)**: per-asset results above show **negative** post−pre
on energy sectors (XLE -0.043, XLU -0.015) with marginal t-stats. Interpretation:
the regime-event dates are not specifically "energy stress" events; they are
**carbon-market regulatory** events whose forward window often coincides with
calmer energy-sector vol periods. This is consistent with a sector-isolation
finding rather than spillover.

## Interpretation (conservative)

- Carbon ETFs (KRBN / GRN) show **positive** forward-5d RV bump after regime
  events (+0.04 to +0.06 ann RV), but no individual asset rejects H0 at
  Bonferroni 10%.
- Date-aggregated cross-asset test is the strongest signal (p_raw=0.071) but
  not robust to PRELIMINARY-sample caveat.
- **No evidence** of energy-sector spillover (XLE / XLU diffs negative, not
  significant).
- **No evidence** of gap-risk (|t+1 return|) elevation after regime events.

## Honest verdict: PRELIMINARY

Per task brief: n_events = 25 < 50 ⇒ **statistical power is insufficient for a
PASS claim** regardless of p-value. The directional pattern (KRBN/GRN bump,
XLE/XLU no spillover) is consistent with carbon-market regulatory events being
**asset-specific** (carbon credits) rather than broadly energy-sector. A
production-grade replication would need:

1. EEX per-auction microstructure data (paywall) — true demand-depth and
   reserve-price bindingness measure.
2. ≥100 events (multi-year + intraday auction-by-auction series).
3. EUA front-month futures rather than only basket ETFs.

## Files

- `k1545.py` — experiment script (fully reproducible, seed=20260624)
- `k1545_results.json` — machine-readable results
- `data/prices.parquet` — yfinance cache
- `data/eu_ets_regime_events.csv` — hand-coded event list (with source notes)
- `figures/fig1_krbn_grn_fwd_rv_events.png` — forward RV with event markers
- `figures/fig2_event_diff_by_asset.png` — Δ by asset with 95% bootstrap CI
- `REFERENCES.md` — literature references
- `codex_review.md` — Codex review verdict

## Reproducibility

```
cd /Users/yhlai0911/Desktop/volpred-research
uv run python experiments/k1545/k1545.py
```

Delete `data/prices.parquet` to re-fetch yfinance data.
