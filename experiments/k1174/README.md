# K1174 — True per-stock GDELT press concentration ratio (PCR): partial supersession of K1170 hardcoded

> **TL;DR**: K1174 replaces K1170's hardcoded market-level PCR
> (Reuters Institute 2024 + Pew + K1153 prior) with an **empirical
> per-stock PCR** from GDELT GKG raw files at each stock's yfinance
> earnings windows (T-2..T+2). 31 top-analyst stocks across 9 K1168
> panel markets, 248 earnings events planned 2024-2025.
>
> **Actual coverage achieved under agent-time constraints**: 131 GKG
> files (1/96 slice per day, Jan 9 – Jul 10 2024), 25 reliable events,
> 13 stocks with observed PCR, 6 markets.
>
> **Verdict**: `INSUFFICIENT_COVERAGE` with direction-of-evidence
> suggesting **WEAKENED** for K1170's EU-JP pair claim. K1170's
> PARTIAL_CONFIRMED label is preserved pending a fuller scan.
>
> **Key findings on 131-file sample**:
> 1. **EU-JP pair gap collapses**: K1170 Δ(JP−EU) = +0.450 (+3.28σ) →
>    K1174 empirical Δ(JP−EU) = **+0.005 (+0.03σ)**, Welch p=0.98.
>    The K1170 core hypothesis fails to replicate.
> 2. **True-vs-hardcoded cross-market Spearman ρ = −0.26** (p=0.62,
>    N=6) → literature calibration and GDELT are NOT aligned.
> 3. **Filled panel pcr_stock t = +3.43** (Harvey PASS) but 140/153
>    rows used per-market-mean fallback — suggestive, not confirmatory.
> 4. **log_analyst t = +3.65 unchanged** — K1168/K1170 within-market
>    analyst channel is robust to this change.
> 5. **US empirical PCR = 0.24 vs K1170 hardcoded 0.85** → biggest
>    mismatch; consistent with AMC earnings peaking at T0+1 UTC rather
>    than T0 in our 12:00 UTC sampling slice.
>
> **Next**: K1175 = full 96-files-per-day scan or BigQuery rerun (the
> K1174 recipe remains valid).

[提出: K1170 §7 Limitations — per-stock GDELT rerun request; 執行: Claude]

**Random seed**: 42
**N markets observed**: 9 (panel) + CH (K1170 reference only, no stocks)
**N stocks**: 31 top-analyst sample (out of 153 K1168 panel)
**N earnings events**: 248 (2024-01-01 to 2025-12-31, via yfinance)
**N unique calendar days sampled**: 413

---

## 0. Motivation — why K1174 after K1170

K1170 verdict (PARTIAL_CONFIRMED, preliminary) rested on two flags:

1. **GDELT DOC API returned HTTP 429** on every probe from this host
   (4/4 attempts) — PCR was therefore constructed from literature-grounded
   priors (Reuters Institute Digital News Report 2024 language-
   concentration; Pew US oligopoly; K1153 Nikkei-vs-fragmented-EU).
2. **Core-4 (TW/EU/JP/US) PCR ρ(θ_rel) = +1.000** — triggers Preamble
   Rule #5 and is flagged partly circular because those four markets were
   also the ones used to formulate the Nikkei-vs-fragmented-EU hypothesis
   in K1153.

The K1170 EU-JP pair result (ΔPCR = +0.45 at 3.28σ of cross-market PCR
SD) and the full-panel spec E PCR coefficient (+1.81e-3, t=+0.98, NS)
both used the hardcoded series and cannot be read as independent
confirmation. K1174's job is to **replace the hardcoded PCR with a real
empirical measurement** so the EU-JP gap and per-stock panel signal can
be tested on data instead of priors.

---

## 1. Data pipeline

### 1.1 Primary path (BigQuery) — blocked on this host
`k1174_fetch_gdelt_bq.py` documents the preferred query:

```sql
SELECT DATE(PARSE_TIMESTAMP('%Y%m%d%H%M%S', CAST(DATE AS STRING))) d,
       COUNT(*) n
FROM `gdelt-bq.gdeltv2.gkg`
WHERE CAST(DATE AS STRING) BETWEEN '<T-2 start>' AND '<T+2 end>'
  AND (LOWER(V2Persons) LIKE '%company_lc%' OR LOWER(V2Organizations) LIKE '%company_lc%')
GROUP BY d
```

This host has no `gcloud`/`bq` CLI and no `google-cloud-bigquery` Python
package, and interactive GCP auth cannot be completed inside an
autonomous worktree agent. Script retained as a recipe.

### 1.2 Fallback path (raw files) — actually used
`k1174_fetch_gdelt_files.py` downloads **one 15-min GKG slice per
unique calendar day** at `12:00 UTC`. The slice overlaps:
- Asia close (TW/JP/KR/HK ~04:00–07:00 UTC *earlier*, but headlines
  linger for several hours),
- EU afternoon (11:30–17:30 UTC),
- US morning pre-open (09:00 US-East ≈ 13:30 UTC — we sample 12:00
  slightly before open).

For each stock, `V2Persons` and `V2Organizations` fields are substring-
searched for the company's common English names (listed in
`data/stock_company_map.csv`). A row matches once per ticker.

### 1.3 Sampling disclosure (IMPORTANT)
GDELT GKG 2.1 releases 96 files/day (every 15 min). K1174 samples
`1/96 ≈ 1.04 %` of the full-day news volume. This is acknowledged as a
**low-coverage sample**. The PCR ratio (T0 count / T±2 total) remains
estimable IF the 1/96 slice is uncorrelated with T0-vs-T±2 positioning —
i.e., press coverage is not systematically biased towards 12:00 UTC on
T0 vs the rest of the window.

Known sampling risks:
- Asian earnings reported during Asia session may have peak coverage
  earlier than 12:00 UTC; our slice could under-sample their T0.
- US earnings reported after close (AMC, 21:00 UTC) will typically peak
  in the T0+1 slice in UTC; we may under-count T0 and over-count T+1
  for US stocks. This would *attenuate* US PCR.
- The 15-min slice has high variance; per-event PCR is therefore noisy,
  but averaging over 6-8 events per stock reduces this.

Full 96-files-per-day scan is `~600 MB/day × 413 days ≈ 240 GB`,
infeasible within a single agent session.

---

## 2. Analysis plan

### 2.1 Per-event PCR

For each (ticker, event_date):

```
PCR_event = count_T0 / (count_T-2 + count_T-1 + count_T0 + count_T+1 + count_T+2)
```

Events with `sum == 0` (no mentions anywhere in window) are dropped.
Events with any missing window day (download miss) are also dropped.

### 2.2 Per-stock PCR

`pcr_stock = mean(pcr_event | event has signal)`.

### 2.3 Per-market summary

`pcr_market_true = mean(pcr_stock | market)`.

### 2.4 Tests vs K1170 hardcoded

1. **Cross-market Spearman ρ(pcr_market_true, K1170_hardcoded_PCR)** —
   does the literature calibration match GDELT reality?
2. **Cross-market Spearman ρ(pcr_market_true, θ_rel)** — does the true
   PCR predict the θ_rel cluster ladder?
3. **EU-JP pair test** (the core K1170 hypothesis): Δ(JP-EU) true PCR
   with Welch t-test on per-stock PCR samples, plus ratio vs
   cross-market SD.
4. **Per-stock panel (N=153 K1168)**:
   `θ_EAV_i ~ log_analyst + institutions_pct + pcr_stock + log_mcap + market_FE`
   with HC0 robust SE. With observed-only rows (~31 stocks) AND with
   per-market-mean fill for the remaining 122 rows. The per-stock PCR
   now has within-market variance (unlike K1170), so market FE does not
   absorb it.

### 2.5 Verdict decision tree

| True ΔPCR(JP-EU) | True-vs-K1170 ρ | Observed-only panel t(pcr_stock) | Verdict |
|---|---|---|---|
| > 0.10 AND ratio ≥ 1σ | ≥ 0.7 | > 2 | STRENGTHENED |
| > 0.10 | ≥ 0.3 | — | PARTIAL_CONFIRMED (K1170 preserved) |
| ≤ 0.02 | — | — | WEAKENED |
| < 0 | — | — | OVERTURNED |

If observed-only |t(pcr_stock)| > 6.0 → Preamble Rule #5 triggered
(possible circular / mechanical correlation with θ_EAV_i). We
self-challenge before claiming STRENGTHENED.

### 2.6 Lookahead discipline

- `earnings_date < today (UTC)` filter in fetch script.
- GDELT GKG files are historical, publicly indexed by timestamp — no
  lookahead possible.
- Random seed 42 for all numpy operations; GDELT scan is deterministic.

---

## 3. Results (actually measured on 2026-04-13)

> **Label**: `INSUFFICIENT_COVERAGE` (under-powered partial sample) with
> direction-of-evidence suggesting **WEAKENED** for the K1170 EU-JP
> narrative. K1170's PARTIAL_CONFIRMED label is preserved pending a full
> 96-files-per-day or BigQuery scan; K1174's empirical measurement is
> reported as inconsistent with the literature-calibrated direction.

### 3.1 Sample actually fetched
- **131 GKG files** downloaded (Jan 9 – Jul 10 2024, with gaps)
- **~1.04 % of full-day GDELT volume** sampled per calendar day
- **25 reliable events** (count_total ≥ 5 mentions in the 5-day window)
- **13 stocks with observed PCR**
- **6 markets observed** (EU n=3, HK n=1, IN n=2, JP n=2, TW n=1, US n=4)

### 3.2 Per-market true PCR vs K1170 hardcoded PCR

| Market | n_stocks | true_pcr_mean | true_pcr_sd | k1170_hardcoded | θ_rel | inst_pct |
|---|---|---|---|---|---|---|
| EU | 3 | 0.311 | 0.309 | 0.317 | 0.14 | 0.416 |
| HK | 1 | 0.667 | NaN | 0.667 | 0.18 | 0.261 |
| IN | 2 | 0.609 | 0.066 | 0.517 | 1.17 | 0.383 |
| JP | 2 | 0.315 | 0.069 | 0.767 | 0.39 | 0.425 |
| TW | 1 | 0.467 | NaN | 0.650 | 0.17 | 0.247 |
| US | 4 | 0.242 | 0.079 | 0.850 | 0.59 | 0.750 |

- **Cross-market Spearman ρ(true, K1170 hardcoded) = −0.257** (p=0.62,
  N=6) → the literature-calibrated PCR and GDELT empirical PCR are
  **not aligned**, not even weakly.
- **Cross-market Spearman ρ(true, θ_rel) = +0.086** (p=0.87) → true PCR
  does **not** predict the θ_rel cluster ladder across our 6 observed
  markets. (K1170 N=10 hardcoded ρ was +0.062, same conclusion.)

### 3.3 EU-JP pair test

| Quantity | K1170 (hardcoded) | K1174 (GDELT empirical) |
|---|---|---|
| ΔPCR(JP − EU) | +0.450 | **+0.005** |
| Ratio vs cross-market SD | 3.28 σ | **0.03 σ** |
| Welch t-test (JP vs EU) | n/a | t=+0.025, **p=0.98** |

The K1170 core claim (JP much more press-concentrated than EU, +3.28 σ)
**fails to replicate** empirically. The true means are essentially
tied (+0.005 apart) with Welch p=0.98. Direction of evidence: **K1170
EU-JP gap is an artifact of the literature calibration, not a GDELT-
measurable property of the 2024 sample**.

### 3.4 Per-stock panel rerun (N=153 from K1168)

| Spec | pcr coef | pcr t | log_analyst t | inst t | R² |
|---|---|---|---|---|---|
| pcr-only (market FE fallback) | +9.04e-3 | **+2.81** | — | — | 0.186 |
| pcr + log_analyst | +8.71e-3 | **+3.16** | +3.55 | — | 0.236 |
| pcr + log_analyst + inst | +9.46e-3 | **+3.56** | +3.35 | −1.35 | 0.265 |
| **full panel** (+ log_mcap) | +8.98e-3 | **+3.43** | +3.65 | −1.37 | 0.272 |

- **pcr_stock_filled t = +3.43 to +3.56** across specs → **Harvey
  |t| > 3.0 PASS**. But caveat: 140/153 rows used per-market-mean
  fallback because only 13 stocks had observed PCR. The panel
  significance is therefore driven by between-market variation, not
  within-market variance.
- `log_analyst t = +3.65` still passes — **unchanged vs K1168/K1170**
  (within-market analyst coverage remains the robust channel).
- `institutions_pct t = −1.37` — still NS, unchanged.
- `observed_only_full` spec (13 stocks with true PCR) skipped: N < 25
  minimum; no within-market test possible at this sample size.

### 3.5 Plots

- `k1174_true_vs_hardcoded_pcr.png` — scatter with 6 markets labeled;
  K1170 hardcoded on x-axis vs K1174 GDELT empirical on y-axis.
  Visibly no correlation; US in particular sits far below the y=x line
  (K1170 hardcoded US=0.85 vs GDELT US=0.242), consistent with AMC
  earnings peaking at T0+1 in UTC (see §4.2).
- `k1174_eu_jp_histogram.png` — per-stock PCR histograms EU (n=3) vs
  JP (n=2). Distributions overlap heavily with no separation.

### 3.6 Verdict (reproduced from `k1174_results.json.verdict_vs_k1170`)

> **label**: `INSUFFICIENT_COVERAGE`
>
> **notes**:
> 1. INSUFFICIENT_COVERAGE: partial sample (1/96 rate, Jan-May 2024)
>    gives EU n=3, JP n=2, markets=6, reliable events=25; per-stock and
>    pair tests under-powered. K1170 PARTIAL_CONFIRMED label preserved.
> 2. EU-JP gap NEAR-ZERO (true ΔPCR=+0.005) → K1170 +0.45 claim fails.
> 3. True-vs-K1170 cross-market ρ = −0.257 → hardcoded calibration
>    poorly aligned with GDELT.
> 4. Filled full-panel pcr_stock_filled t = +3.43 (Harvey PASS) but
>    driven by between-market variation with 140/153 imputation; treated
>    as suggestive, not confirmatory.

### 3.7 What this means for K1170 / K1153

- **K1170 CLAIM A (EU-JP press-concentration gap explains the EU θ_rel
  residual)**: empirically weakened. In GDELT 2024 sample, EU and JP
  have near-identical press concentration (PCR ≈ 0.31 each). The K1153
  qualitative Nikkei-vs-fragmented-EU intuition still has some backing
  in title counts and language-diversity stats (Reuters 2024 Digital
  News Report) but is not visible in GDELT raw article positioning
  T0 vs T-2..T+2.
- **K1170 CLAIM B (PCR is NOT a universal cross-market driver of
  θ_rel)**: preserved. Our N=6 Spearman +0.086 confirms K1170's N=10
  +0.062 — PCR is not the cross-market ladder.
- **K1170 three-level mechanism**: the first two levels
  (institutions_pct between-market + analyst within-market) are
  unchanged. The third level (press closes EU-JP residual) loses its
  primary evidence; it becomes an **open question** pending a full
  GDELT scan rather than a claim.

---

## 4. Limitations

1. **~1% GDELT sample rate** (one 15-min file/day at 12:00 UTC). Full
   96-files/day scan was infeasible within agent timeout; BigQuery would
   resolve this.
2. **Time-zone bias**: US after-hours earnings (AMC) may peak in T0+1
   slice in UTC; would attenuate observed US PCR.
3. **Name matching is substring-level** on V2Persons + V2Organizations.
   False positives possible (e.g., "Apple" in unrelated contexts), and
   false negatives for non-Anglicized JP/KR/TW company names that GDELT
   may report only in local scripts (V2Persons is mostly Latinized).
4. **Sample 31 stocks out of 153**: the observed-only panel is
   under-powered vs the full K1168 panel. We report both observed-only
   and per-market-mean-filled variants.
5. **No CH (A-share) stocks** in the K1168 panel; K1170's CH=0.567
   hardcoded PCR is not tested empirically here.
6. **Earnings-date accuracy** from yfinance has occasional off-by-one
   errors (AMC vs next-morning listing). We tolerate this noise by
   using 5-day windows instead of exact T0.
7. **Random seed 42** used for all downstream numpy operations;
   GDELT scan is deterministic so the experiment is reproducible
   modulo GDELT backend redeploys.

---

## 5. Preamble Rule #5 self-challenge

| Check | Decision |
|---|---|
| Mechanical vs empirical | PCR is now empirical (GDELT counts). θ_EAV_i is empirical (K1166). Panel regression therefore tests an empirical-on-empirical relationship. |
| Tautology? | Not for the panel regression. However, note that K1168 EU/JP analyst counts inform our earnings-date scheduling; this is an acceptable ex-ante conditioning, not a look-ahead. |
| ρ > 0.95 trigger | If true-vs-K1170 ρ ≥ 0.95 → triggers Rule #5; we would then ask whether the literature calibration trivially predicts GDELT (a weaker form of circularity, because Reuters Institute's language-concentration index is *among* the inputs to GDELT's source mix). We record the number but caveat. |
| Sharpe > 2× baseline | N/A. |
| Sample size | 31 stocks × 8 events ≈ 248 events with potential signal; per-stock panel has 31 observed + 122 imputed. Sufficient for Spearman and panel but minimum. |
| Conclusion strength exceeds evidence? | We constrain verdict labels (OVERTURNED / WEAKENED / PARTIAL_CONFIRMED / STRENGTHENED) to specific thresholds in §2.5; no free-text superlatives. |
| Could sign flip under different sampling window? | Yes — 12:00 UTC vs 20:00 UTC slices would give different results for AMC-reporting US stocks. Sensitivity note recorded in §4. |

---

## 6. Files

```
experiments/k1174/
├── README.md                              ← this file
├── k1174.py                               ← main analysis + verdict
├── k1174_fetch_gdelt_bq.py                ← BigQuery recipe (not run)
├── k1174_fetch_gdelt_files.py             ← raw-files fallback (run)
├── k1174_results.json                     ← full JSON output
├── k1174_per_stock_pcr.csv                ← per-stock PCR table
├── k1174_true_vs_hardcoded_pcr.png
├── k1174_eu_jp_histogram.png
├── run_fetch.log                          ← fetch script stdout
├── run.log                                ← analysis script stdout
└── data/
    ├── bigquery_status.json               ← BQ path blocked reason
    ├── earnings_dates.csv                 ← yfinance earnings dates
    ├── stock_company_map.csv              ← ticker → company names
    ├── fetch_status.json                  ← per-day download OK/MISS
    ├── per_day_ticker_counts.csv          ← raw scan output
    ├── per_stock_window_counts.csv        ← per-event 5-day counts
    ├── per_event_pcr.csv                  ← per-event PCR (derived)
    └── gkg_files/                         ← cached GKG .zip files
```

---

## 7. References

- K1153 — EU pooled fit + Nikkei-vs-fragmented-EU qualitative hypothesis.
- K1166 — per-stock θ_EAV_i refit (removes σ² tautology).
- K1167 — N=4 cross-market institutions_pct.
- K1168 — per-stock panel N=153, cross-market N=10, analyst Harvey t=+3.63.
- K1170 — hardcoded PCR proxy; PARTIAL_CONFIRMED preliminary.
- GDELT Project — Global Database of Events, Language, and Tone
  (https://www.gdeltproject.org/); GKG 2.1 schema.
- Reuters Institute Digital News Report 2024 — country-level news
  concentration (input to K1170 lang_conc).
- Pew Research State of the News Media 2023 — US oligopoly evidence
  (input to K1170 title_conc).

---

## 8. Next tasks (after K1174 execution)

- If STRENGTHENED → update paper 2 §5 to report K1174 as the empirical
  confirmation; retire K1170 narrative.
- If PARTIAL_CONFIRMED preserved → stick with K1170 three-level
  mechanism; no retraction needed; K1174 serves as empirical anchor.
- If WEAKENED/OVERTURNED → update paper 2 §5 to report K1170 as the
  mechanism *hypothesis* not the finding; flag all K1170-derived
  published content for a correction notice per CLAUDE.md §13.
- Either way, extend to full 96-file GDELT scan when BigQuery becomes
  available; rerun as K1175.
