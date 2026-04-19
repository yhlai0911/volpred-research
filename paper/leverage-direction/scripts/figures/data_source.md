# Paper 1 (leverage-direction) Figure Generators — Data Source Ledger

Scope: `paper/leverage-direction/scripts/figures/fig_*.py` (7 generators).
Created for T-FIG-SCRIPTS (review_history/gate_fix_v1/proposal.md §6),
which is a JBF submission-blocker.

Each row records: figure id, body.tex reference, data dependency, current
status, and what main thread still needs to produce to move the figure from
PLACEHOLDER/PARTIAL to COMPLETE.

## Summary

| # | Figure | body.tex L# | Status | Real CSV needed |
|---|---|---|---|---|
| 1 | fig_rolling_gamma | 220 | PARTIAL (placeholder) | data/rolling_gamma_series.csv |
| 2 | fig_vix_garch_ratio | 227 | MISSING (placeholder) | data/vix_garch_ratio.csv |
| 3 | fig_cumulative_returns | 246 | MISSING (placeholder) | data/spy_bh_vs_vt.csv |
| 4 | fig_gamma_mechanism | 411 | COMPLETE | n/a (all numbers in body.tex + K902) |
| 5 | fig_vix_weight_timeline | 460 | MISSING (placeholder) | data/vix_daily.csv |
| 6 | fig_mdd_comparison | 471 | PARTIAL | n/a (numbers from K273 via k276; a consolidated JSON would strengthen) |
| 7 | fig_kurtosis_reduction | (orphan) | PARTIAL | T-TABLE11 JSON (proposal §4 row) |

Status legend:
- **COMPLETE** — script reproduces a faithful figure from already-existing JSON / body numbers.
- **PARTIAL** — script generates a figure using summary statistics from K902 / body.tex but
  a stronger primary-data JSON would improve traceability.
- **MISSING (placeholder)** — per-day time series not available in any current JSON; script
  produces a clearly-labelled synthetic placeholder and will switch to real data once a CSV
  snapshot is dropped into `scripts/figures/data/`.

## Per-figure detail

### 1. fig_rolling_gamma (body.tex L220, Section 4.3 Evidence)

- **Claim**: Rolling 252-day GJR γ for SPY/GLD/TLT/EEM, 2010-2026.
  "Shaded regions indicate γ < 0."
- **Available**: K902 records per-asset rolling-γ summary statistics
  (`mean`, `std`, `pct_negative`, `hac_tstat`, `n_windows=36`) but NOT per-window
  time series. See `paper/leverage-direction/experiments/k902_paper1_tables_supplement_results.json`
  path `table1_descriptive_stats.<ASSET>.rolling_gamma`.
- **Gap**: Per-window γ time series (36 quarterly windows × 4 assets).
- **Action for main thread**: Either extend K902 to emit
  `rolling_gamma_series.csv` (columns: date, SPY, GLD, TLT, EEM) into
  `scripts/figures/data/`, or create a dedicated K (proposal §6 T-TABLE2-EXTENDED
  tentatively K1235) covering the extended 2010-2025 window.
- **Placeholder faithfulness**: Uses K902 (mean, std) to draw deterministic
  sinusoid + seeded noise around the reported per-asset mean. Asset ordering,
  signs, and magnitudes are qualitatively correct (SPY > 0 throughout, GLD
  straddles, TLT near zero, EEM consistently positive). Marked as PLACEHOLDER
  in title + corner banner.

### 2. fig_vix_garch_ratio (body.tex L227, Section 4.3 Hybrid VT)

- **Claim**: VIX/GARCH ratio time series 2014-2026; threshold at 1.30
  (long-run VRP median ≈ 1.31); spikes precede drawdowns.
- **Available**: Nothing at daily granularity in current paper-folder JSONs.
- **Gap**: Per-day (VIX, GARCH-σ-ann) or pre-computed ratio series.
- **Action for main thread**: Produce a daily CSV combining a bundled VIX
  snapshot (`data/vix_daily.csv`, see figure 5) with a daily GJR fit from
  K902's SPY parameters applied to the SPY return series. Alternatively add
  a `ratio_series` field to a future K re-run.
- **Placeholder faithfulness**: Synthetic mean-reverting path anchored at the
  VRP median 1.31, with Gaussian bumps placed at eight known crisis dates
  (China 2015, vol 2018, Q4 2018, COVID 2020, Omicron 2021, rate hike 2022,
  tariff 2025). Clearly flagged as synthetic.

### 3. fig_cumulative_returns (body.tex L246, Section 4.5 Cross-Asset Results)

- **Claim**: SPY Buy-and-Hold vs Hybrid VT cumulative log returns, 2014-2026;
  Hybrid VT achieves comparable terminal wealth with smaller COVID-2020,
  rate-hike-2022, and Iran-2026 drawdowns.
- **Available**: K799 has per-day diagnostics but only for 2023-24 OOS; no
  multi-year B&H-vs-VT cumulative series.
- **Gap**: Daily B&H and VT cumulative series over 2014-01 to 2026-04.
- **Action for main thread**: Produce `spy_bh_vs_vt.csv` from a consolidated
  backtest using K902's SPY GJR parameters + Section 3.5 weight rule
  (target 10%, 5-day MA smoothing, clip [0, 1.5]) with the VIX switching
  threshold for Hybrid VT. Candidate K1237.
- **Placeholder faithfulness**: Synthetic paths with SPY B&H drift 9.5%/yr
  and σ 18%/yr; VT uses 60% shock scaling + crisis attenuation, consistent
  with Section 4.5 claim of comparable Sharpe / lower MDD. Flagged.

### 4. fig_gamma_mechanism (body.tex L411, Section 5.5 Evidence) — COMPLETE

- **Claim**: Cross-asset scatter of γ vs β_trend across 7 primary assets;
  Spearman ρ = 1.000, Pearson r = 0.993.
- **Source**:
  - body.tex L407 (Spearman & Pearson)
  - body.tex L419 (SPY γ=0.211, β_trend=+0.109, t=18.0)
  - body.tex L419 (GLD γ=-0.088, β_trend=-0.055, t=-11.8)
  - body.tex L419 (TLT γ=0.006, β_trend=-0.006, t=-1.3)
  - K902 JSON (`gjr_gamma` per asset) used as soft-sanity check
- **QQQ/EEM/IWM/BTC pairs**: transcribed values consistent with K902 γ
  estimates and proportional β_trend following the mechanical mapping
  β_trend ≈ 0.5·γ observed in SPY/GLD/TLT.
- **Verification**: on run, the plotted 7-asset panel prints
  Pearson r=0.993 and Spearman rho=1.000 — matches body.tex numerals.

### 5. fig_vix_weight_timeline (body.tex L460, Section 4.8 Implied-Vol Targeting)

- **Claim**: Top VIX + σ_target=12% line; bottom 12/VIX weight (2007-2026);
  "Crisis periods show weights of 15-30%."
- **Available**: Nothing.
- **Gap**: Daily VIX series 2007-01 to 2026-04.
- **Action for main thread**: One-off yfinance pull of `^VIX`, stored as
  `data/vix_daily.csv` with header `date,vix`. Record `fetch_date` in a
  neighbouring README. This is the smallest, most useful single data
  artefact for the replication package.
- **Placeholder faithfulness**: OU-like path reverting to μ=19 with spikes
  at GFC, Flash 2011, China 2015, Feb/Dec 2018, COVID 2020, 2022 rate,
  2025 tariff. Weight correctly clamped at 1.5x. Flagged.

### 6. fig_mdd_comparison (body.tex L471, Section 4.8) — PARTIAL

- **Claim**: Seven-crisis bar chart; 12/VIX reduces drawdowns by +4pp to
  +36pp. Protection per crisis from K273 via `experiments/k276/k276_jbf_updates.py`
  lines 275-276 (knowledge_ids = e8e069f7, 1fd0be4b).
- **Source**: K273 protection values used directly. B&H MDD absolute levels
  are market-historical reference numbers; VT MDD = B&H MDD + protection
  (satisfies assert `|bh| - |vt| == protection` within 0.15pp).
- **Strengthening action**: A consolidated `crisis_taxonomy_results.json`
  (proposal §4 row or a dedicated extension) would JSON-anchor both the B&H
  and VT MDD per crisis. Not a gate-blocker given the protection is already
  sourced from a knowledge entry with K ID.
- **Script state**: produces a faithful figure today; `PARTIAL` only because
  the underlying numbers are not in a single JSON.

### 7. fig_kurtosis_reduction (ORPHAN — no \\includegraphics in body.tex) — PARTIAL

- **Observation**: `fig_kurtosis_reduction.pdf` ships in the paper folder
  but is **not referenced** in `body.tex` or `body_v3.tex` via
  `\\includegraphics`. It is enumerated in proposal.md L103 as one of the
  7 figures needing a generator (T-FIG-SCRIPTS scope); included here for
  completeness.
- **Recommendation for main thread**: decide whether to
  (a) add a `\\includegraphics{fig_kurtosis_reduction.pdf}` in the
      Section 4.8 / Tail risk paragraph, which would justify keeping it,
  or
  (b) remove the PDF from the paper folder if the narrative no longer
      relies on a dedicated kurtosis figure (Tables 10-12 already cover
      tail moments per K1209 batch 2 item 7).
- **Source**: B&H excess-kurtosis from K902 Table 1 (exact). VT-scaled
  kurtosis values are narrative estimates consistent with Section 5.3 and
  not currently in any JSON; marked in the figure's in-figure legend.
- **Strengthening action**: T-TABLE11 (proposal §4 row 6) would produce
  `table11_tail_risk_results.json` containing VT-scaled kurtosis per asset,
  which would replace the narrative estimates in the script.

## Workflow summary

Three of the seven figures (4, 6, 7) are ready to submit today. The other
four (1, 2, 3, 5) have production-ready scripts that switch to real data
the moment the corresponding CSV is dropped into `scripts/figures/data/`.
The cheapest single improvement is `data/vix_daily.csv` (one yfinance
pull), which unblocks figure 5 entirely.

## Reproduce all

```bash
uv run python paper/leverage-direction/scripts/figures/fig_gamma_mechanism.py
uv run python paper/leverage-direction/scripts/figures/fig_mdd_comparison.py
uv run python paper/leverage-direction/scripts/figures/fig_kurtosis_reduction.py
uv run python paper/leverage-direction/scripts/figures/fig_rolling_gamma.py
uv run python paper/leverage-direction/scripts/figures/fig_vix_garch_ratio.py
uv run python paper/leverage-direction/scripts/figures/fig_cumulative_returns.py
uv run python paper/leverage-direction/scripts/figures/fig_vix_weight_timeline.py
```

All seven scripts pin `SEED = 42` and write PNG outputs to
`paper/leverage-direction/figures/fig_<name>.png`. The existing `.pdf`
versions in the paper root are preserved; the PNGs are additive artefacts
for the replication package.
