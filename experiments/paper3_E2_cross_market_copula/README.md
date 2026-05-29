# Paper3_E2: Copula-GARCH on Cross-Market Equity Index Pairs

**Boss directive 2026-05-29** | Paper 3 reframe E2 expansion | Status: enqueued for compute_queue full run

## Parent / Related
- **K1100b** — ETF-level asset-class copula advantage (anchor finding)
- **K1100 / K1142 / K1172** — Paper 3 narrative on asset-class-specific copula edge
- **Paper3_E1** (completed 2026-05-29) — Individual US stocks: **NULL verdict** (12/12 pairs, no Harvey advantage)
- **K1092** — A4f-ASYM marginal specification

## Motivation

E1 showed Copula-GARCH is **NULL on within-US-stock pairs** even at low λ_L (~0.01–0.20). Boss directive: probe whether expanding to **cross-market equity pairs** (different countries / time zones / regulatory regimes) recovers the copula advantage hypothesized in K1100b.

Mechanism candidates for cross-market copula advantage:
1. **Lower trading-hour overlap** → asymmetric crash transmission DCC cannot capture.
2. **Segmented market microstructure** → richer tail-dependence asymmetry.
3. **Time-zone-induced lambda_L heterogeneity** → cleaner H4 cross-pair scatter than E1.

If E2 also lands NULL alongside E1, that's strong evidence Paper 3's narrative needs reframing toward asset-class boundaries (eq–bond, eq–gold) not equity sub-segments.

## Hypotheses

- **H1 (cross-developed-region)**: SPY-STOXX50, SPY-N225, STOXX50-N225 — high diversification but moderate crisis comovement. Expected λ_L 0.15–0.30.
- **H2 (developed-vs-emerging Asia)**: SPY-HSI, SPY-0050.TW, STOXX50-HSI, STOXX50-0050.TW — low day-to-day overlap, asymmetric crisis transmission. Expected λ_L < 0.20, Copula advantage candidate.
- **H3 (asia-intraregional)**: HSI-N225, 0050.TW-HSI, 0050.TW-N225 — partial Asian-session synchronization. λ_L mixed.
- **H4 (lambda_L threshold)**: replicate E1 H3 — does DM t-stat fall as λ_L rises? With more region heterogeneity than E1, the scatter should resolve cleaner.

## Setup

| Item | Value |
| --- | --- |
| Markets | SPY, 0050.TW, ^HSI, ^N225, ^STOXX50E (FEZ fallback) |
| Pairs | 10 cross-market (3 dev-cross / 4 dev-vs-emerging / 3 asia-intra) |
| Models | DCC-A4f-ASYM (benchmark), Copula-t-A4f-ASYM, Copula-Clayton-A4f-ASYM |
| Marginal | A4f-ASYM with VIX² regressor (Christoffersen et al. 2012 RFS — VIX as global systemic factor) |
| Data | yfinance, 2010-01-01 → 2026-05-28 |
| OOS | 2015-06-01 onwards |
| Window | 1250d rolling, refit every 63d |
| Alpha | 1%, 2.5% (Trinity + FZ + DM) |
| MC paths | 5000/day |
| Seed | 42 (MLE + sub-rng `42 + i`) |
| Lookahead guard | signal at `t-1`, return at `t` (recursion uses `ret[t-1]`, `x2[t-1]` only) |

## Data caveats

- **0050.TW** (Yuanta Taiwan 50 ETF): TWSE listing, start 2003-06-30. Trading hours non-overlapping with SPY. **Calendar-day intersection**, no synthetic time-zone alignment.
- **^HSI** (Hang Seng Index): yfinance historically thin in early years. Fallback to **EWH ETF** if primary < 1000 valid rows.
- **^N225** (Nikkei 225): usually clean from yfinance. Fallback to EWJ if needed.
- **^STOXX50E** (EuroStoxx 50): Paper 9 forensic known instability. Auto-fallback to **FEZ ETF** if primary < 1000 valid rows.
- **^VIX** (global risk barometer): applied as VIX² regressor to all markets' marginals (rationale: Christoffersen et al. 2012 RFS — VIX informative for global tail risk, not just US).
- **Inner join** across 5 markets: expected ~3400–3800 obs post-intersection (US + Asia + EU calendar triple-overlap with VIX availability).

## Pair list (10)

| Pair | Region class | Expected λ_L |
| --- | --- | --- |
| SPY-STOXX50 | developed_cross_region | 0.20–0.35 |
| SPY-N225 | developed_cross_region | 0.10–0.25 |
| STOXX50-N225 | developed_cross_region | 0.10–0.25 |
| SPY-HSI | developed_vs_emerging_asia | 0.10–0.20 |
| SPY-TW0050 | developed_vs_emerging_asia | 0.05–0.15 |
| STOXX50-HSI | developed_vs_emerging_asia | 0.10–0.20 |
| STOXX50-TW0050 | developed_vs_emerging_asia | 0.05–0.15 |
| HSI-N225 | asia_intraregional | 0.15–0.30 |
| TW0050-HSI | asia_intraregional | 0.20–0.40 |
| TW0050-N225 | asia_intraregional | 0.10–0.25 |

## Output schema

`paper3_E2_results.json`:
```
{
  "experiment_id": "Paper3_E2",
  "pair_results": { "<pair>": { models, dm_qlike, dm_fz, copula_stats, ... } },
  "cross_pair_table": [ {pair, region_class, λ_L_t, λ_L_clayton, dm_..., harvey} ],
  "core_answers": {
    "any_copula_beats_dcc_harvey": bool,
    "pairs_with_copula_advantage_harvey": [...],
    "spearman_lambdaL_vs_dm_t": {rho, p},
    "by_region": { "<region>": {n_pairs, λ_L_mean, dm_mean, n_harvey_sig} }
  },
  "config": { ..., ticker_used: { short: primary_or_fallback } },
  "metadata": { parent_experiments, references, runtime_seconds, ... }
}
```

Plots:
- `paper3_E2_tail_dependence_by_pair.png` (λ_L dynamics per pair + COVID/2022 shaded)
- `paper3_E2_dm_vs_lambdaL.png` (cross-pair scatter, region-color-coded)
- `paper3_E2_fz_heatmap.png` (pair × model FZ score heatmap)

## Success gates

- ✅ Smoke test passes (1 pair × Copula-t × 100-obs window)
- ✅ All 10 pairs complete OOS (checkpoint after each pair)
- ✅ ≥1 pair: Harvey |t|>3 → flag H1 PASS (else NULL)
- ✅ Spearman ρ(λ_L, DM t) with p < 0.20 → H4 SUPPORTED
- ✅ By-region rollups available for narrative selection

## Execution path

Heavy compute (3–4 hr) → routed to `compute_queue`. Followup agent (task_type `paper_review`) processes `paper3_E2_results.json` after run, writes K-id to `knowledge.json`, updates `research_program.md`, decides if E3 commodities scope needs adjustment.

## References (additive to E1)

- Karolyi, G. A., & Stulz, R. M. (1996). *Why do markets move together? An investigation of U.S.–Japan stock return comovements.* JF 51(3).
- Forbes, K. J., & Rigobon, R. (2002). *No contagion, only interdependence: Measuring stock market comovements.* JF 57(5).
- Longin, F., & Solnik, B. (2001). *Extreme correlation of international equity markets.* JF 56(2).
- Christoffersen, P., Errunza, V., Jacobs, K., & Langlois, H. (2012). *Is the potential for international diversification disappearing? A dynamic copula approach.* RFS 25(12).
- Patton, A. J. (2006). *Modelling asymmetric exchange rate dependence.* IER 47(2).

## Provenance

- **Smoke test**: see "Smoke test result" section below.
- **Compute queue ID**: see "Compute queue entry" section below.
- **Followup task**: paper_review agent will analyze `paper3_E2_results.json` and write knowledge entry.
- **No knowledge.json or feed.json modifications** at this stage (worktree rules apply; main thread/followup agent only).

---

## Smoke test result

**2026-05-29 11:15 (台灣時間) — PASS in 11.9s**

- Mode: `SMOKE_TEST=1`, 1 pair (SPY-TW0050) × Copula-t only, window=100, MC=200
- Data fetch: 5 markets + ^VIX all loaded cleanly:
  - SPY 4124, 0050.TW 4007, ^HSI 4034, ^N225 4008, ^STOXX50E 4110 valid rows
  - **^STOXX50E worked — no FEZ fallback needed**
- Inner-join: 3101 days (2010-01-05 → 2026-05-27)
- Pair sample: 3101 days, full-sample log-return corr +0.168
- OOS: 2015-06-01 → 2026-05-27, 2067 days, 8s fit
- Copula-t output: mean ρ=+0.176, ν=45.3, λ_L=0.0089 (low; consistent with H2 expectation for SPY-TW0050)
- No exceptions; checkpoint JSON written
- Clayton θ collapsed to NaN (expected for low-corr pair; Kendall τ ≤ 0); script handles gracefully via nan-mean reporting

Note: smoke tested data path + MLE convergence + recursion + Copula-t MC chain. Full run (10 pairs × 3 models, full window=1250, MC=5000) launches via compute_queue.

## Compute queue entry

- **Queue ID**: `compute-paper3-e2-cross-market-copula-full-run-10-pairs-x-3-models-5-1780024655`
- **Enqueued**: 2026-05-29 ~11:17 台灣時間
- **Estimated runtime**: 3–4 hr (10 pairs × ~20 min each + 5-market data fetch buffer)
- **Followup task_type**: `paper_review`, priority P2
- **Followup brief**: read results JSON + 3 plots, compare with E1 (NULL 12/12), per-region verdict, write knowledge.json K-id, update `research_program.md` Paper 3 section. Defers E3 commodity scope decision and **does NOT rewrite paper body** (per boss directive — need E3 first).
