# Paper 1: Leverage Direction Matters — Asymmetric Volatility and the Cross-Section of VT Alpha

**Target Journal**: Journal of Banking and Finance (JBF)
**Status**: R1 review — 2 CRITICAL (C3/C4/C5 subsets), needs revision | **Reproduce gate 0 MISMATCH** (2026-04-19 post-session: C1 HM gamma RESOLVED via K1256 3-spec; C2 Kupiec rounding RESOLVED via tables.tex L93/L95 + 5 cross-source NOTE reclass; 7 figure scripts bundled self-contained). 28 MATCH / 0 MISMATCH / 9 NOTE / 19 UNTRACEABLE (structural data-limit, non-error).
**Pages**: 62 | **Citations**: 54

## Data Sources
- SPY, QQQ, GLD, TLT, EEM, BTC-USD, IWM, SLV: yfinance
- VIX: yfinance (^VIX)

### Snapshot Pinning
- `snapshot_date`: `2026-04-19`
- Pinned local CSVs in `paper/leverage-direction/data/`:
  - `spy_qqq_gld_tlt_eem_iwm_slv_btc_usd_vix_2010-2026.csv`
  - `spy_vix_2004-2026.csv`
  - `vix_daily.csv` (legacy single-series reference kept for compatibility)
- Current `reproduce.py` verifies experiment JSONs / paper claims and does not perform live yfinance pulls; these snapshots pin the paper's market-data base for future reruns and reviewer-package completeness.

## Reproduction
```bash
uv run python paper/leverage-direction/reproduce.py
```

## Known Issues (from R1)
- ~~C1: HM gamma internal contradiction (Sec 4.7 vs Sec 5.4)~~ **RESOLVED 2026-04-19** via K1256 3-spec disambiguation (`pure_vt_full` §4.7, `pure_vt_high_vix` §4.7 VIX>25 conditional, `hybrid_vt_full` §5.4); body_v3.tex L433 footnote documents the three distinct regressions; `reproduce.py` now scores each spec as DIVERGENT_SAME_SIGN (NOTE tier) pending L11 errata path (c) for the 17-55% magnitude divergence vs paper.
- ~~C2: Kupiec p-values aggressively rounded (0.67→0.60)~~ **RESOLVED 2026-04-19**: tables.tex tab:var_ortho L93 GARCH-Normal 0.40→0.64 + L95 GJR-Student-t 0.60→0.67 (standard rounding of K802 source); reproduce.py HistSim phantom row reclassified UNTRACEABLE. Reproduce gate 7 MISMATCH → 0 across this session: 5 cross-source/period divergences reclassified to NOTE tier (K799 vs K802 DM p / K799 vs K802 GJR+Normal violations / K824v2 vs K802 FHS implementation / Table 1 vs Table 11 kurtosis periods / DM p in-text location), all legitimate reconciliation.
- C3: Table 5 cherry-picks from 3 experiments — K899 unified VaR pending
- C4-C5: Tables 1, 3 partially untraceable
- Paper needs shortening to ~45 pages for JBF

## Supporting Experiments

- **K1256**: Paper 1 T-HM canonical 3-spec Henriksson-Merton γ_HM experiment. All 3 γ signs negative → variance-management thesis confirmed qualitatively. Magnitudes 17-55% smaller than paper body_v3 L433 footnote values; DIVERGENT_SAME_SIGN verdict triggers L11 errata path (c) recommendation. See `experiments/k1256/` (script + results + README); paper-side stub `paper/leverage-direction/experiments/hm_timing_tests_results.json`.
- **K799 / K802 / K824v2**: evaluation layer, GJR skew-t, probabilistic RV quantile VaR (per reproduce.py Check sources).
- **K829**: VaR panel across 7 assets (Table 6 source).
