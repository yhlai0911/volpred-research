# K1811 — Extreme-weather physical events and insurance/utility ETF volatility: event study + dose-response

**Status:** MIXED / mostly NULL, one *fragile* suggestive result. Descriptive event study — not a trading signal.
**Owner:** hourly-slot-3 (pool task K1722). **Seed:** 42. **Reviewer:** pending (main-thread Codex review at collection).

---

## 1. Motivation and literature anchoring

The 2025 climate-finance literature (PLOS One 2025; *Journal of Investment & Financial Management* 2025) converges
on the view that **physical climate risk dominates transition risk** for the *immediate* volatility impact of climate
events on financial assets. This experiment tests, with primary-source physical-event data, whether extreme-weather
**physical** events produce an abnormal-volatility response in the ETFs most directly exposed to their balance-sheet
consequences — property-&-casualty **insurers** (KIE, KBWP) and **utilities** (XLU) — and whether that response scales
with the **physical intensity** of the event (a *dose-response*).

**Hypothesis.** After a US hurricane landfall / major national heat wave, realized volatility of KIE / KBWP / XLU shows
a positive abnormal response, larger for more intense events (higher Saffir-Simpson category / larger heat scale).
SPY is the market control: if the sector abnormal vol exceeds SPY's, the effect is sector-specific rather than market-wide.

### Relation to prior VolPred knowledge (differentiation is explicit)
Two prior K's already found that *contemporaneous* climate-event vol is largely absorbed by the market/VIX:
- **K117** (Climate/Weather Event Vol Impact): market-proxy events, VIX-controlled → NULL, "VIX sufficient statistic".
- **K148** (Climate Volatility): 32 *named* billion-dollar disasters 2010-2024, event study [-5,+20] + GJR-GARCH-X
  climate **dummy** + VIX-controlled partial corr → NULL (GARCH-X 0/5 pass Harvey; VIX absorbs).

**What K1811 does that K117/K148 did not:**
1. **Continuous physical DOSE, not an event dummy.** The core novel test regresses cumulative abnormal vol on the
   **Saffir-Simpson category** (hurricanes) and a **heat-intensity scale** (heat waves). K117/K148 used on/off dummies.
2. **Primary-database provenance.** Events are derived mechanically from **NOAA HURDAT2** (best-track landfalls) and the
   **NOAA Storm Events Database** (Excessive Heat), not a curated named-disaster list.
3. **Sector-specificity framing** (insurance + utility vs SPY control), not a VIX-sufficiency framing.

The K117/K148 prior means the *honest expectation* is that raw abnormal vol may be positive but market-driven; the
dose-response slope and the SPY-differenced response are the genuinely new tests. **A NULL result is fully expected and
acceptable.** (And it largely is NULL — see §6.)

---

## 2. Data and provenance (all free, byte-traceable)

Exact download URLs, byte counts and **md5** of every source file are recorded in
[`data/provenance_manifest.json`](data/provenance_manifest.json) (regenerated on every run). Raw downloads are cached
under `data/raw/` (not committed; re-downloadable from the manifest URLs).

### 2a. Hurricanes — NOAA/NHC HURDAT2 (Atlantic best-track)
- Source: `https://www.nhc.noaa.gov/data/hurdat/hurdat2-1851-2025-02272026.txt` (md5 `6c80cbc4bdfdd0ea59c53b9ec8d54e90`).
- **US-landfall rule (purely geographic, reproducible):** take best-track records flagged `L` (landfall) with status
  `HU` (hurricane strength); keep points inside the CONUS Atlantic/Gulf box `24≤lat≤47.5N, 98≤lon≤66W`, **excluding**
  NW Bahamas (`lat≤27.5 & lon≥79.3W`) and NE Mexico/Tamaulipas (`lat≤26 & lon≤97W`); Cuba is excluded by the lat≥24 floor.
- **Dose = Saffir-Simpson category (1–5)** from the max wind (kt) over the storm's US landfall records
  (64/83/96/113/137 kt thresholds). Event date = first US landfall date.
- Yield: **28 US-landfalling hurricanes, 2011–2024**, category distribution {Cat1:13, Cat2:5, Cat3:3, Cat4:6, Cat5:1}.
  Cross-checked against known ground truth (Michael Cat5; Harvey/Irma/Laura/Ida/Ian/Helene Cat4). **Sandy (2012) is
  correctly excluded** — it was extratropical (`EX`, post-tropical) at its NJ landfall, so it has no Saffir category;
  this is a documented limitation, not a bug. Alex (2010) excluded (Mexico landfall). See `data/events_hurricanes.csv`.

### 2b. Heat waves — NOAA Storm Events Database (`Excessive Heat`)
- Source: `https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/StormEvents_details-ftp_v1.0_d{YEAR}_c{REV}.csv.gz`,
  one file per year 2010–2024 (creation-date revisions pinned in the manifest; md5 per file).
- Filter `EVENT_TYPE == "Excessive Heat"` (18,238 county/zone records). Build a daily national intensity
  `N(d)` = count of Excessive-Heat events beginning on day `d`. Detect discrete heat waves by **greedy peak-detection**
  on the 7-day centered rolling event-count `R(d)`: repeatedly take the highest-`R` day ≥21 days from any already-selected
  peak, stopping at `R<200`. This yields **15 well-separated major heat waves, 2010–2024** (peak-scale 260–905).
- **Dose = `R(d*)`** (7-day national event-count scale = geographic-temporal breadth) — primary. Robustness doses:
  Excessive-Heat direct deaths over [-3,+7] (`dose_alt`), duration. See `data/events_heatwaves.csv`.
- ⚠️ Nationwide Excessive Heat is near-continuous in summer, so naive gap-clustering merges whole summers
  (e.g. the 2023 heat dome → a 34–48-day blob). Greedy peak-detection with a 21-day guard is the reproducible fix.

### 2c. ETF volatility — yfinance daily OHLC
- `KIE` (SPDR S&P Insurance), `KBWP` (Invesco KBW P&C Insurance; inception Dec-2010 → 2010 heat events lack KBWP,
  handled by availability checks, KBWP heat n=14), `XLU` (Utilities Select Sector), `SPY` (market control).
- Cached to `data/ohlc_*.csv` with md5. Range-based vol uses **unadjusted OHLC** — Parkinson/GK are invariant to
  split/dividend scaling because they depend only on `ln(H/L)` and `ln(C/O)` ratios.

---

## 3. Method (classic event study + dose-response)

- **Vol proxy (primary):** Parkinson range RV, `σ²ₚ = ln(H/L)² / (4 ln2)`; work in daily **log-vol** `0.5·ln σ²ₚ`.
  Robustness: Garman–Klass and `|log return|²`.
- **Estimation window `[-60,-11]`** (50 trading days, strictly pre-event): baseline `μ_est, σ_est` of log-vol.
- **Event window `[-5,+10]`** (no overlap with estimation window).
- **Abnormal volatility** `AVₜ = (logvolₜ − μ_est)/σ_est` (standardized). Market-adjusted variant: regress ETF log-vol
  on SPY log-vol over the estimation window, standardize the residual over the event window (removes market-wide vol).
- **CAAV** = mean AV across events at each relative day; **CAV** per event = Σ AV over `[0,+5]` and `[0,+10]`.
- **Significance:** (a) cross-sectional t-test on CAVᵢ; (b) **SEED=42 month-matched placebo** — relocate each event's
  t₀ to a random trading day in the *same calendar month* ≥20 days from any real event (controls seasonal vol), 2000 reps,
  two-sided p on |CAAV|.
- **Sector-specificity:** paired (sector − SPY) CAV difference test.
- **Dose-response (core novel test):** OLS of CAV[0,+10] on dose, **per sector** (avoids the K1355 cross-asset-iid
  pitfall); plus pooled sector-FE with **event-clustered SE** (secondary). Robustness: Spearman rank correlation,
  market-adjusted OLS, **Cook's-distance influence jackknife** (refit after dropping the most influential events),
  drop-max-dose stratum, and non-overlapping-event subset.

---

## 4. Lookahead / honesty policy (highest priority)

This is a **descriptive** event study, **not** a predictive/trading study. No feature is used to forecast next-day vol,
so no `signal.shift(1)` is required; the only regression explains *realized* post-event abnormal vol with the event's
*realized* physical dose (the standard event-study "CAR on severity" regression). The relevant guards, all grep-able in
`k1811.py`:
- `EST=(-60,-11)` is **strictly before** t₀; `EVT=(-5,10)`; the two windows do not overlap (gap between −11 and −5).
- `t0 = first trading day on/after the event calendar date` (`_t0_index`) — the market reacts from t₀ forward; CAV[0,+10]
  uses **post-event days only**.
- Event **detection** (hurricane landfall, heat peak) uses **physical data only** — never ETF vol — so event dates are
  exogenous to markets.
- All randomness fixed at `SEED=42` (`RNG = np.random.default_rng(42)`): placebo relocation, OLS bootstrap CI, jackknife.
- Sign convention verified: positive AV = elevated vol (Hurricane Michael CAV KIE = +36.4). No QLIKE-style inversion
  (there is no QLIKE here — AV is a standardized log-vol deviation).

If this were ever re-framed as "predict next-day vol from an event indicator", the indicator would need `.shift(1)` and
the baseline the same lag — **not done here because there is no prediction.**

---

## 5. Success criteria (from brief) — all met; NULL acceptable

| Criterion | Target | Result |
|---|---|---|
| (a) reproducible physical events with dose | ≥15 | **43** (28 hurricanes + 15 heat), each byte-traceable with dose ✅ |
| (b) event-study AV, correct windows, 3 sectors + SPY | all | KIE/KBWP/XLU + SPY, est `[-60,-11]`, evt `[-5,+10]` ✅ |
| (c) ≥1 significance test on CAAV | t + placebo | cross-sectional t **and** 2000-rep month-matched placebo ✅ |
| (d) dose-response coefficient + CI | yes | per-sector OLS + Spearman + pooled-FE + influence jackknife ✅ |

---

## 6. Results (honest summary — mostly NULL, one fragile signal)

### 6.1 Hurricanes — mean abnormal vol is NULL
CAAV[0,+10] (standardized): KIE +0.64 (t=0.35, p=0.73), KBWP +1.59 (p=0.25), XLU +0.43 (p=0.74), SPY +0.01 (p≈1.0).
Month-matched placebo p ≥ 0.12 for all; (sector − SPY) differences NS. **No significant mean vol response** — because
the majority (13/28) are Cat-1 storms that barely move vol. Consistent with K117/K148.

### 6.2 Hurricanes — dose-response: *suggestive but FRAGILE and partly market-wide*
A positive category → abnormal-vol gradient does appear in the raw OLS:

| ETF | OLS slope (p) | Spearman ρ (p) | drop Cat-5 (p) | market-adj OLS (p) |
|---|---|---|---|---|
| KIE  | +3.78 (0.005) | +0.36 (0.062) | +1.94 (0.078) | +2.96 (0.009) |
| KBWP | +2.46 (0.014) | +0.40 (0.037) | +1.99 (0.051) | +1.84 (0.067) |
| XLU  | +2.29 (0.017) | +0.31 (0.108) | +1.94 (0.089) | +2.18 (0.013) |

**Why this is not a clean win (the "too-good-to-be-true → find the confound" check):**
- **The gradient is also present in SPY** (slope +2.89, p=0.067) → it is substantially **market-wide**, not
  insurance-specific.
- **One event dominates.** Hurricane **Michael (Cat-5, 2018-10-10)** has Cook's distance **1.36 — ~10× the next point
  (0.12)**. Its KIE CAV (+36.4) ≈ its SPY CAV (+35.5): Michael's "abnormal vol" is the **October-2018 market correction**
  it coincided with, **not** an insurance-specific shock. Removing the Cat-5 stratum pushes every OLS to p≈0.05–0.09;
  removing Michael **and** the overlapping 2017 Harvey/Irma Cat-4 cluster collapses all specs to p=0.2–0.9.
- Rank-based Spearman (robust to the outlier) is only **marginal** and significant solely for KBWP (p=0.037).

**Verdict:** there is a *weak, insurance-leaning* physical-intensity gradient in post-landfall abnormal vol, but it is
**fragile** (hinges on the single Cat-5, which is market-confounded) and only partly sector-specific. This does **not**
overturn the K117/K148 "market absorbs climate-event vol" prior; it refines it: the *strongest* events (Cat 4–5) do lift
sector vol, but those episodes are exactly when the whole market is already stressed. **Reported as suggestive, not
confirmed.**

### 6.3 Heat waves — fully NULL
CAAV[0,+10] is *negative* (KIE −3.01 p=0.096, KBWP −2.01 p=0.073, XLU −0.06, SPY −1.47) — a **summer low-vol seasonal
artifact** shared with the market: month-matched placebo is NS (KIE p=0.20), (sector − SPY) is NS, and SPY is also
negative. Dose-response is flat for every ETF (all p ≥ 0.37; Spearman NS; SPY gradient NS; pooled-FE p=0.93).
**No abnormal-vol response and no dose-response to heat-wave intensity.**

### Figures
`figures/caav_hurricane.png`, `figures/caav_heat.png` (event-window AAV curves, 4 ETFs);
`figures/dose_hurricane.png`, `figures/dose_heat.png` (CAV[0,+10] vs dose scatter + fit).
All headline numbers are in [`k1811_results.json`](k1811_results.json).

---

## 7. Limitations
- **Small samples** (28 hurricanes, 15 heat waves) → single influential events (Michael) swing OLS; hence the emphasis
  on rank tests and influence jackknives.
- **Overlapping event windows** within hurricane seasons (Harvey/Irma/Nate 2017) violate cross-event independence; the
  placebo and non-overlap-subset robustness partly address this but cannot fully separate co-occurring market shocks.
- **Market confounding is intrinsic**: peak-hurricane and market-stress periods overlap (Oct-2018), so raw abnormal vol
  is not cleanly attributable to the physical event. Market-adjustment helps but does not fully remove it (Michael's
  market-adjusted CAV is still +31.9).
- **Heat dose** (event count / deaths) is a reporting-dependent severity proxy, not a physical temperature-anomaly
  metric; a station-level heat-index dose (GHCN) would be a cleaner follow-up.
- Sandy (2012) and other post-tropical / territory (PR/USVI) landfalls are excluded by the objective Saffir/CONUS rule.

## 8. Reproduce
```bash
uv run python experiments/k1811/k1811.py          # downloads (cached) + full analysis + figures + JSON
uv run python scripts/experiment_gates.py run --path experiments/k1811   # integrity gate
```
Deterministic given `SEED=42` and the pinned source md5s in `data/provenance_manifest.json`.
