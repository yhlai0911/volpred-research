# K1728 — Free macro-attention / news-sentiment vs HAR-RV for US-equity realized variance

- Experiment ID: `k1728`
- Status: complete
- Verdict: **NULL** (for free attention/sentiment) — on the primary criterion (Clark-West + Campbell-Thompson OOS R² on log-RV), robust across assets, OOS starts, schemes and regimes (see the QLIKE caveat under Results)
- Created: 2026-07-27
- Model/effort: opus / xhigh (per model_router)

## Motivation (grounded in literature)

Recent work (J. Forecasting; arXiv 2025 macro-attention & sentiment-vol; JPM *The Impact
of Volatility Targeting*; Man Group 2025) argues that **macro attention** (investor/media
attention) and **news sentiment** lead realized volatility (RV) in high-uncertainty
periods. HAR-RV (Corsi 2009) is a strong RV baseline but uses only RV's own
daily/weekly/monthly components. This experiment tests whether adding a **free**
attention / uncertainty / sentiment regressor to HAR yields a **statistically significant
incremental out-of-sample forecast** of US-equity RV.

**Core question**: with the HAR-RV daily/weekly/monthly terms already in the model, does a
free attention/sentiment regressor produce incremental OOS R² > 0 that is significant by
the Clark-West nested test? Is any gain larger in high-EPU / high-VIX regimes?

## Data (all free; see `.claude/skills/external-data-sources`)

Fetched once by `fetch_data.py` into `data/` (analysis reads only these cached CSVs, so it
is fully offline & deterministic). `data/provenance.json` records every source.

| Role | Series | Source | Freq | Coverage (downloaded) |
|---|---|---|---|---|
| RV target | SPY, QQQ daily OHLC | yfinance | daily | 2005-01-03 .. 2026-07-27 (n=5424) |
| Uncertainty / attention | `USEPUINDXD` Daily Economic Policy Uncertainty (Baker-Bloom-Davis) | FRED official API | daily | 1990-01-01 .. 2026-07-26 (n=13356) |
| Attention / risk (control) | `VIXCLS` VIX close | FRED official API | daily | 1990-01-02 .. 2026-07-24 (n=9237) |
| News sentiment | SF Fed Daily News Sentiment Index (Buckman-Shapiro-Sudhof-Wilson) | FRBSF xlsx | daily | 1980-01-01 .. **2023-11-26** (n=16017) |
| Attention (attempted) | Google Trends "recession"/"inflation"/"crash" | pytrends | weekly | **UNAVAILABLE** — HTTP 429 rate-limited 2026-07-27 |

- **Google Trends fallback**: pytrends returned HTTP 429 (rate limited). Per the brief we
  fell back to FRED-based attention/uncertainty proxies (EPU, VIX). No paid API used.
- **FRED access**: the public `fredgraph.csv` scraping endpoint is bot-blocked (repo
  error_log 2026-05-29); we use the official API with `FRED_API_KEY` from the main
  checkout's git-ignored `.env.local`.
- **RV is a proxy**: no stable free long-history intraday source exists (yfinance intraday
  is capped at 60 days), so RV is the **Garman-Klass** range-based daily variance estimator
  from OHLC. This is a proxy for true realized variance; results are stated under that
  caveat. Target is log-RV (standard vol-forecasting convention).
- **Primary sample** = the all-series intersection on SPY trading days. Because SF Fed news
  sentiment ends 2023-11-26, the primary sample is **2005-02-03 .. 2023-12-04, n=4741 rows**
  (OOS **2015-01-02 .. 2023-12-04, n=2246**). All specs are compared on identical rows.

## Method

1. **RV**: log Garman-Klass daily variance. Descriptive stats + ACF observed before estimation
   (log-RV mean −10.17, sd 1.24; ACF(1/5/22)=0.69/0.58/0.43 — persistent, as expected).
2. **Baseline HAR-RV** (Corsi 2009): `y_t ~ const + RV_d(t-1) + RV_w(t-1) + RV_m(t-1)` (OLS).
3. **Augmented specs** (each exogenous predictor `.shift(1)`): `HAR+EPU`, `HAR+News`,
   `HAR+VIX`, `HAR+EPU+News` (the pure free-text combo), `HAR+EPU+News+VIX` (all).
4. **OOS evaluation** (expanding window, one-step, coefficients re-fit at every origin):
   - **Clark-West (2007)** MSPE-adjusted nested test — **primary criterion** (canonical
     `volpred.stats.model_evaluation.clark_west_test`).
   - **Campbell-Thompson incremental OOS R²** vs HAR.
   - **Diebold-Mariano** (HLN HAC, canonical `dm_test`) on log-RV squared error and on QLIKE.
   - Two loss functions reported: **MSE** (log-RV) and **QLIKE** (variance level, with a
     consistent per-spec log-normal bias correction).
5. **Regime analysis**: split OOS days by the **t-1** VIX and EPU regime (thresholds fixed
   from the pre-OOS block only → no lookahead), plus a fixed VIX>20 cut.
6. **Robustness**: OOS start ∈ {2013, 2015, 2018, 2020-06}; rolling (1000d) vs expanding;
   QQQ replication; predictor subsets (the six specs); DM HAC-lag sensitivity {1,5,10,22}.

## Lookahead policy

- **Every predictor enters at t-1 via an explicit `.shift(1)`** in `build_frame`:
  - HAR daily `= y.shift(1)`, weekly `= y.rolling(5).mean().shift(1)`, monthly
    `= y.rolling(22).mean().shift(1)`.
  - EPU/VIX/News: reindexed onto trading days, **bounded** forward-fill (limit 5 days, to
    bridge holidays only — never to fabricate a stale run past a series' true last obs; the
    cap is what forces the sample to honestly end at the news series' 2023-11-26 coverage),
    then `.shift(1)`.
- **Baseline and augmented use identical lags and identical sample rows** → fair nested
  comparison.
- **True OOS**: at each origin `t`, OLS is re-fit only on rows with position `< t`; forecasts
  use only ≤ t-1 information. Target `y_t` (day-t realized variance) is realized after every
  training row.
- **Real-time caveat (per K1655 hard rule)**: EPU uses a **final-vintage** download and
  carries minor revision risk, so the OOS is a **final-vintage pseudo-OOS**, *not* certified
  PIT real-time. This only strengthens a NULL (any revision bias would help, not hurt, the
  predictor). VIX and price-based RV are effectively unrevised; the SF Fed news score is a
  mechanical text measure.

## Success criteria (pre-registered)

- **PASS**: at least one augmented spec has Clark-West one-sided p < 0.05 **and** incremental
  OOS R² > 0, robust to OOS start.
- **NULL**: incremental OOS R² ≤ 0 or CW not significant — reported honestly as a valuable
  result (free daily attention/sentiment does not beat HAR for US-equity RV).
- **Free-signal scope**: the headline verdict is judged on the **free-text** specs
  (`HAR+EPU`, `HAR+News`, `HAR+EPU+News`). VIX is an options-**implied** vol forecast, not a
  free attention/text signal; it is included as a strong control, not as a headline claim.

## Results

**SPY, OOS 2015-01-02 .. 2023-12-04, n=2246. Primary criterion = Clark-West one-sided p.**

| Spec | Incremental OOS R² vs HAR | CW t | CW p (1-sided) | DM(log-RV) t | QLIKE | Verdict |
|---|---|---|---|---|---|---|
| HAR (baseline) | 0.000% | — | — | — | 0.3982 | — |
| HAR+EPU | **−0.217%** | +0.676 | 0.249 | +0.777 | 0.3956 | NULL |
| HAR+News | **−0.180%** | −0.206 | 0.582 | +1.023 | 0.3976 | NULL |
| HAR+EPU+News | **−0.277%** | +0.430 | 0.334 | +0.973 | 0.3958 | NULL |
| HAR+VIX *(control)* | **+8.026%** | +9.556 | <1e-4 | −5.498 | 0.3470 | (implied-vol, beats HAR) |

- **DM(log-RV) t is positive for all free specs** (positive ⇒ augmented has *higher* loss),
  i.e. the free-text signals mildly *hurt*. VIX's DM t=−5.5 (better).
- **Robust NULL**: free-text specs are ≤0 incremental R² with CW p≫0.05 at **every** OOS
  start (2013/2015/2018/2020-06), both expanding & rolling, and on **QQQ** (HAR+EPU+News
  −0.04%, CW p=0.25; HAR+VIX +4.98%, CW p<1e-4). DM HAC-lag sensitivity {1,5,10,22} leaves
  HAR+EPU+News t≈0.97–1.09 (p≈0.28–0.33) — the null is not a HAC artifact.
- **QLIKE caveat (per review)**: the NULL verdict is on the **primary** criterion (CW +
  OOS R² on log-RV, the model's native target). On the secondary **variance-level QLIKE**,
  the free specs' point estimates are marginally *lower* (better) than HAR (HAR 0.3982 vs
  EPU 0.3956, News 0.3976, EPU+News 0.3958), and the diagnostic `dm_qlike` for HAR+EPU is
  ≈ one-sided 0.045. This is **not** valid nested inference (`dm_qlike` is diagnostic-only)
  and is plausibly a log-normal **bias-correction level-shift artifact** — a larger model has
  a smaller train residual variance `s²`, lowering `exp(f+0.5 s²)`, and asymmetric QLIKE
  rewards that level shift independent of predictive content. QLIKE is therefore **not** cited
  as null-supporting robustness (see `methodology_notes.qlike_direction_caveat` in results.json).
- **Regime analysis**: in **no** regime do the free-text signals help. On the fixed **VIX>20**
  cut (n=737 high): HAR+EPU+News −0.59% (CW p=0.58); on the **pre-OOS 70th-pct EPU** cut
  (n=713 high): HAR+EPU+News −0.94% (CW p=0.67). The only sub-0.10 cell is HAR+EPU in the
  *low*-EPU regime (CW p=0.055, +0.18%) — opposite the hypothesized direction and not
  significant. VIX's gain **concentrates in high-vol regimes** — on the **pre-OOS 70th-pct VIX**
  cut, 13.5% (high) vs 6.0% (low) incremental OOS R² — as expected for an implied-vol measure.

**Headline**: For daily US-equity realized variance, **free macro-attention / news-sentiment
indices (EPU, SF-Fed news sentiment) add no significant incremental OOS forecast power over
HAR-RV** — the incremental OOS R² is slightly negative and Clark-West is far from significant,
robustly. The only regressor that beats HAR is **VIX** (options-implied, +8% OOS R²,
CW p<1e-4), which is not a free text/attention signal.

Figures: `figures/fig1_incremental_oos_r2_by_spec.png`, `fig2_incremental_oos_r2_by_regime.png`,
`fig3_predictors_vs_rv.png`.

## Verification checklist (for the receiving main thread)

1. **Reproduce**: `uv run python experiments/k1728/k1728.py` → prints `verdict=NULL`,
   `SPY sample 2005-02-03..2023-12-04 n=4741 oos=2246`, and the four headline lines above.
   (Data are cached; no network needed. `fetch_data.py` is the one-time fetcher.)
2. **Lookahead**: confirm `build_frame` shifts every predictor (`har_d/w/m` via
   `rolling().shift(1)`; `epu/vix/news` via bounded-ffill `.shift(1)`). Baseline HAR shares
   the same regressor columns as every augmented spec (see `SPECS`).
3. **Sample honesty**: the primary sample ends 2023-12-04 because the bounded ffill (`FFILL_LIMIT=5`)
   refuses to extend news sentiment past its 2023-11-26 coverage — verify by removing the
   limit and seeing the sample wrongly extend to 2026 with a frozen-constant news column.
4. **Primary test is canonical**: CW/DM come from
   `src/volpred/stats/model_evaluation.py` (not a local reimplementation).
5. **Numbers are byte-traceable** in `k1728_results.json`
   (`headline`, `primary_SPY.specs`, `robustness_SPY`, `robustness_QQQ`, `data_provenance`).
6. **Gates**: `python3 scripts/check_experiment_artifacts.py check --path experiments/k1728`
   and `uv run python scripts/experiment_gates.py run --path experiments/k1728` both PASS.

## Codex review points

- **Lookahead**: is any predictor readable at time t (not t-1)? Check `.shift(1)` on all of
  `har_d/w/m/epu/vix/news`, and that the OOS training slice is `< i` (strictly past).
- **Baseline lag parity**: HAR terms identical in baseline and augmented specs.
- **ffill cap**: does `FFILL_LIMIT=5` correctly prevent stale-constant fabrication past a
  series' last obs (the news-2023 trap)?
- **Nested test correctness**: CW small=HAR, large=augmented, actual=log-RV_t; direction and
  HAC lag from canonical.
- **QLIKE**: variance-level QLIKE uses `actual/predicted` (canonical `qlike`), with a
  consistent per-spec log-normal bias correction `exp(f + 0.5·s²_train)`.
- **NULL honesty**: no overclaim; VIX explicitly framed as options-implied control, not a
  free-text signal.

## Proposed knowledge summary (main thread writes knowledge.json; agent does NOT)

- **Finding**: Free daily macro-attention / news-sentiment indices (Baker-Bloom-Davis EPU;
  SF-Fed Daily News Sentiment) provide **no significant incremental OOS predictive power**
  for US-equity daily realized variance over a HAR-RV baseline — incremental OOS R² slightly
  negative, Clark-West p≫0.05 — robust across SPY & QQQ, four OOS starts, expanding/rolling,
  and all VIX/EPU regimes, on the primary criterion (CW + Campbell-Thompson OOS R² on log-RV,
  the model's native target). The only regressor that beats HAR is **options-implied VIX**
  (+8% OOS R², CW p<1e-4; gain concentrated in high-vol regimes), which is not a free
  text/attention signal.
- **Verdict**: NULL (free attention/sentiment); PASS-equivalent only for the VIX control.
- **Caveats**: RV is a Garman-Klass range proxy (no free long intraday source); EPU OOS is
  final-vintage pseudo-OOS (minor revision risk, only helps the predictor); news sentiment
  coverage ends 2023-11-26 so the intersection sample ends there; Google Trends attention was
  rate-limited (429) and unavailable. On the secondary variance-level QLIKE the free specs'
  point estimates are marginally better than HAR, but that is diagnostic-only (invalid under
  the nested null) and plausibly a bias-correction level-shift artifact — not counted toward
  the NULL.
- **Interpretation**: HAR already absorbs the low-frequency, persistent information that daily
  attention/sentiment indices carry (unconditional corr with log-RV: news −0.47, EPU +0.31),
  so they add nothing *incrementally*; only the forward-looking options signal (VIX) does.
