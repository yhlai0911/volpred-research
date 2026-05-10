# K1268: GDELT 2.0 High-Frequency (5-min) Public-Bulk Scan vs SPY 5-min RV

**Date**: 2026-05-11
**Status**: in-progress
**Replaces**: K1175_gdelt_fullscan (kid_collision w/ Paper 2 audit), K1176_gdelt_fullscan (kid_collision w/ Paper 2 Table 4 replication)

## Motivation

Prior alt-data work in this codebase has consistently found **VIX sufficiency** at daily frequency:

- **K1116** (FRED EPU+NFCI+STLFSI for SPY): NULL — VIX sufficiency #37
- **K1116b** (FRED publication-delay recheck, TLT): universal NULL after delay alignment
- **K1116c** (PIT-aligned H2 robustness): ROBUST NULL — Paper 4 conclusion stands
- **K1118** (cross-asset GLD/TLT/BTC native IV): universal IV-sufficiency
- **K1118b** (FX IV-sufficiency): mixed; basket-FX fails, VIX actively harms EUR

Open question those leave on the table: **all** prior alt-data tests use **daily** (or coarser) frequency. GDELT 2.0 publishes **96 files/day** (every 15 min), giving 5-min-resolution event-density and sentiment time-series. Does intra-day high-frequency alt-data unlock predictive value that daily aggregation washes out?

If 5-min GDELT bars **lead** SPY 5-min RV by ≤30 min after lookahead-safe lag, the H2 universal NULL conclusion (Paper 4) would need a **frequency-boundary** caveat. If still NULL → strengthens Paper 4 result and lets us write a "VIX sufficiency holds even at intraday alt-data resolution" boundary section.

## Differentiation from K1116/K1116b/K1116c/K1118

| Feature | K1116 family | K1268 |
|---|---|---|
| Frequency | Daily | **5-min intraday** |
| Source | FRED (delayed economic series) | **GDELT 2.0 GKG/Events (15-min publish lag)** |
| Target | Daily RV / VIX | **SPY 5-min RV** |
| Lookahead lag | 1 day | **1 bar = 5 min** (conservative) |
| Window | Multi-year | **3 event days** (focused crisis-day pilot) |

## Data

**Endpoint** (verified 2026-05-11, HTTP 200 OK):
```
http://data.gdeltproject.org/gdeltv2/{YYYYMMDDHHMMSS}.export.CSV.zip
http://data.gdeltproject.org/gdeltv2/{YYYYMMDDHHMMSS}.gkg.csv.zip
```
- No auth required; Google Cloud Storage bulk distribution
- 96 files/day (every 15 min on the :00, :15, :30, :45)
- Each export.CSV has GoldsteinScale (-10..+10), AvgTone (sentiment) per event
- Each gkg.csv has tone vectors + theme counts per article

**Event days sampled** (GDELT 2.0 starts 2015-02-18, so Lehman 2008 unavailable; SVB substituted):
1. 2024-08-05 — Nikkei flash crash / yen-carry unwind (BoJ surprise)
2. 2020-03-12 — COVID-19 WHO pandemic declaration aftermath, SPY -9.5%
3. 2023-03-13 — SVB / Signature aftermath, regional bank stress

96 × 3 days = 288 export files (+ optional gkg). Conservative request budget.

**Equity data**: SPY 1-min OHLCV via yfinance, aggregated to 5-min realized variance using 1-min log-returns squared.

## Hypothesis

**H1**: 5-min GDELT event-density (count) Granger-causes SPY 5-min RV at lag ∈ [1,6] (5–30 min).

**H2**: 5-min GDELT sentiment shock (AvgTone < -3, robust threshold) leads SPY RV jump within 30 min.

Null result is publishable (extends K1116 family).

## Pre-registered methodology

- **Lookahead lag**: All GDELT signals shifted by **1 bar (5-min)** before correlation/regression with same-bar SPY RV; reflects realistic forecaster information set (publish + processing latency ~15 min, but conservative 1-bar shift is minimum and we report sensitivity at lag 0/1/2/3 — only lag ≥1 are causal claims).
- **Cross-correlation** computed at lags ∈ [-6, +6] bars (±30 min); negative lags shown for completeness only, not interpreted as predictability.
- **Bootstrap CI**: n=1000 block bootstrap, block_size=12 bars (1 hour), seed=42 throughout.
- **Sample size**: 96 bars × 3 days = 288 GDELT bars (regular trading hours subset 78 bars × 3 ≈ 234 SPY 5-min bars). Underpowered for daily-claim but adequate for **event-day pilot**.
- **Evaluation**: Pearson + Spearman corr w/ HAC SE (Newey-West 6 lags); Granger F-test (lags 1–6).

## Defensive rules adhered to

- `experiments/k1268/` only; no shared-state writes (feed.json / supabase / paper).
- `signal.shift(1)` enforced in code (assertion).
- All RNG seeded (numpy, random, scipy).
- Sample-size disclaimer in results.json — pilot scope, not full alt-data refresh.
- Codex review (primary path verified working since 2026-04-28).

## Success criteria (verdict mapping)

Headline verdict uses **Bonferroni-corrected α = 0.05 / 12** (3 signals × 4 causal lags = 12 tests/day). Uncorrected α=0.05 result is reported alongside for transparency but is exploratory only.

- **PASS**: ≥2 of 3 event days show |corr| > 0.20 at lag ≥+1 with bootstrap CI excluding zero AND Granger p < α (Bonferroni).
- **CONDITIONAL PASS**: 1 of 3 days passes; warrants K1268b expansion.
- **NULL**: all 3 days CI overlaps zero or fails Granger threshold. Strengthens K1116/K1118 family at intraday resolution.
- **FAIL**: methodology bug found by Codex review.

## References

- Bollen, Mao, Zeng (2011) JoCS — Twitter mood / DJIA, 87.6% directional
- Tetlock (2007) JF — pessimism / DJIA returns, 1-day lag
- Calomiris & Mamaysky (2019) JFinEcon — news flow / volatility, **monthly** frequency
- Manela & Moreira (2017) JFE — text-based VIX, **monthly** NVIX
- Engle & Martins (2020) — high-freq news / vol, finds **5-min lead** for FX (suggests freq matters)

## Files
- `k1268_fetch_gdelt.py` — bulk fetch w/ rate-limit + retry
- `k1268_aggregate.py` — parse zip → 5-min bars (count, mean GoldsteinScale, mean AvgTone)
- `k1268.py` — main analysis (cross-corr, Granger, bootstrap, plot)
- `k1268_results.json` — verdict + per-day stats

## Outcome (2026-05-11)

**Verdict: FAIL_NO_DATA** — experiment cannot be executed under current data pipeline.

**Root cause**: yfinance 1-min granularity is restricted to last 30 days; 5-min restricted to last 60 days. The three pre-registered crisis dates (2024-08-05, 2020-03-12, 2023-03-13) all fall outside this window, so SPY 5-min RV cannot be reconstructed from the only public free source we currently have wired up. GDELT side ran cleanly: 864 bars × 3 days fetched + parsed.

**This is a design-pipeline gap, not a methodology failure**:
- GDELT 2.0 public bulk endpoint works (verified, 200 OK; 864 bars @ 5-min ffill from 288 15-min slots)
- yfinance high-frequency historical access requires paid alternative or self-hosted data store
- VIX in last 30 days is in 17-19 quiet regime — no crisis spike in the yfinance-accessible window, so substituting "recent dates" defeats the crisis-day premise

**Codex review verdict before run**: FAIL with 1 blocking (tz-aware vs naive timestamp comparison) + 3 mid-priority issues. All fixed before run — verdict failure was data, not methodology.

**Lessons (written into research_program.md / error_log.md candidates)**:
1. **High-frequency historical equity data is a hard prerequisite**, not a "yfinance fallback can probably handle it" assumption. Future K1268b must wire one of: (a) Polygon paid tier for 1-min historical, (b) Databento, (c) Kibot, (d) self-hosted SPY 1-min archive built from current rolling windows over the next 60 days.
2. **GDELT 2.0 v2 era starts 2015-02-18** — Lehman 2008 forever unavailable. SVB 2023 substitution worked (data fetched fine).
3. **Codex pre-run review caught 1 blocking timezone bug** that would have produced silent FAIL_NO_DATA even with valid data. Pre-run Codex remains primary path.

## Plan for K1268b

When SPY high-frequency historical is wired:
- Re-run on the same 3 dates (2024-08-05, 2020-03-12, 2023-03-13) + add 2026-04-29 / 2026-05-04 if pipeline ready before they age out of yfinance window
- Same methodology (lag1/2/3/6 causal, Bonferroni 0.05/12 headline)
- Carry GDELT data already fetched (`experiments/k1268/data/`) to avoid re-fetching
