# K1116b Audit Report: FRED Publication Delay Handling in K1116 & K1118

**Date**: 2026-04-13
**Purpose**: Check whether K1116 (SPY weekly alt-data) and K1118 (GLD/TLT/BTC weekly alt-data) have latent lookahead due to FRED publication delays.

## 1. FRED Series Publication Schedule

| Series | Observation cadence | Official release lag | Action-ready for agent |
|--------|--------------------|--------------------|----------------------|
| USEPUINDXD (Baker-Bloom-Davis daily EPU) | Daily (X) | ~1 day after X | X+1 (trading day) |
| WLEMUINDXD (World EPU daily) | Daily (X) | ~1 day after X | X+1 |
| NFCI (Chicago Fed) | Weekly, observed Friday | Published following Wednesday | Fri + 5 calendar days |
| ANFCI (Adjusted NFCI) | Weekly, observed Friday | Same Wed as NFCI | Fri + 5 calendar days |
| STLFSI4 (St. Louis Fed) | Weekly, observed Friday | Published following Thursday | Fri + 6 calendar days |

Source: FRED release calendar; BBD paper (Baker, Bloom, Davis 2016 QJE); Chicago Fed NFCI documentation.

## 2. K1116 (SPY) Timing Handling Audit

### 2.1 What the code does

`experiments/k1116/k1116.py` lines 80-152:
1. Downloads daily FRED series `USEPUINDXD`, `WLEMUINDXD`, `NFCI`, `ANFCI`, `STLFSI4`.
2. Aggregates to **weekly W-FRI** using `groupby("week").mean()`.
3. Applies `ffill(limit=2)` (forward-fill max 2 weeks of NaN).
4. Merges with SPY weekly RV at W-FRI frequency.
5. In `make_X`, applies `.shift(1)` (1-week lag) to each regressor, e.g., `USEPU_lag1 = df_sub["USEPU"].shift(1)`.

### 2.2 Alignment analysis

**Prediction target**: Weekly realized vol for week W (Monday of W to Friday of W).
**Signal**: Values aggregated at W-FRI label for previous week, shifted by 1 → predictor for week W is the **aggregate for week W-1** (labeled W-1's Friday).

Now consider each series:

**USEPU / WLEMU (daily)**:
- Week W-1 aggregate mean uses observations X = Monday..Friday of W-1.
- USEPU is published next-day. USEPU[Friday W-1] is released Monday of W.
- Since W-1's week aggregate label is W-1's Friday and we use it to predict W's RV, the full aggregate is known by Monday W (including the Friday value released Mon W).
- **Weekly RV for W is computed Mon-Fri of W → prediction must be made before Mon open of W.**
- **BUG**: The Friday W-1 value of USEPU is not released until Monday W, so strictly speaking by Sunday evening (before Mon W open) we only have USEPU values through Thursday W-1. The code uses the full Mon-Fri W-1 mean.
- Severity: **MILD**. Only 1 day of the 5-day mean is unavailable → dilution effect. Weekly mean is insensitive to 20% of input.

**NFCI / ANFCI (weekly, observed Fri, published following Wed)**:
- Week W-1 aggregate for NFCI = mean of values dated in W-1's calendar. FRED dates NFCI observations at the **Friday observation date**. So the single NFCI data point for W-1 has `date = Friday W-1`.
- NFCI[Friday W-1] is **published Wednesday of W** (5 calendar days later).
- The code uses NFCI[Friday W-1] to predict RV[W]. RV[W] is computed Mon-Fri of W.
- By the time NFCI[Friday W-1] is released (Wed W), 3 days of week W have already occurred.
- **BUG (MODERATE)**: If we are using NFCI[W-1] to predict RV[W], we are using information not yet released when the prediction window starts. This is latent lookahead.
- Fix: NFCI must be used with at least 1 more week's delay → `NFCI.shift(2)` (i.e., NFCI[W-2] to predict RV[W]).

**STLFSI4 (weekly, observed Fri, published following Thu)**:
- Same logic as NFCI but with 6-day delay.
- NFCI[Friday W-1] = `observation_date = Friday W-1`; publication = Thursday of W.
- Using STLFSI[W-1] to predict RV[W] means entire Mon-Wed of W is a forecast window where the regressor is unknown.
- **BUG (MODERATE)**: Same as NFCI. Needs `STLFSI.shift(2)`.

**ffill(limit=2)**:
- Weekly merge uses `outer join` then ffill up to 2 weeks. Since NFCI is weekly (1 point/week already) this mostly affects boundary alignment but does not fix the fundamental lag issue.

### 2.3 Verdict for K1116

K1116 has **latent lookahead** in NFCI, ANFCI, STLFSI4 (3 of 5 alt-data series). The shift(1) week lag gives only 2-4 trading days of margin, but NFCI requires 5 calendar days and STLFSI requires 6. Hence the weekly regressor for week W-1 is **partially (Wed-Thu-Fri of W) still forward-looking** at the time prediction is needed.

**But note**: K1116 conclusion was **NULL (alt-data worsens vs VIX)**. So the lookahead would have **helped** alt-data if it existed. Fixing it should make alt-data look **even worse** — which strengthens the original null conclusion. This is a **favorable direction of bias** for the published result.

### 2.4 K1118 (GLD/TLT/BTC)

Identical aggregation logic to K1116 (copied `fetch_fred_altdata` structure). Same publication-delay exposure on NFCI/ANFCI/STLFSI for all 3 assets.

**Special concern for TLT**: `M2_AR1_IV_vs_M4_AR1_FinStress: t=+3.7434` — the **only positive-and-significant** result across the entire K1118 study (TLT's M4 with NFCI+ANFCI+STLFSI beats MOVE baseline).
- If this is real → alt-data niche for Treasuries.
- If this is publication-delay artifact → spurious positive.
- **This is the single most important cell to re-verify.**

## 3. Corrections to Apply

### 3.1 NFCI, ANFCI, STLFSI (weekly)
- Original: `.shift(1)` at weekly frequency
- Corrected: `.shift(2)` at weekly frequency (add 1 more week lag = 7 days extra margin)

Rationale: At weekly W-FRI frequency, shift(2) means "use NFCI aggregated from week W-2 (labeled Friday W-2) to predict RV[W]". Friday W-2's NFCI is released Wednesday W-1, giving full 7+ days of settling margin before Mon W.

### 3.2 USEPU, WLEMU (daily)
- Original: `.shift(1)` at weekly frequency
- Corrected: **Keep `.shift(1)` weekly but truncate aggregation to Mon-Thu only** (drop Friday from the mean) — or equivalently `.shift(1)` is safe at weekly frequency because:
  - USEPU publication delay is 1 day.
  - By Monday of W open, only Friday W-1's value is missing; 4 out of 5 days are available.
  - Weekly mean bias from missing 20% of data is ~20% of the true Friday->Thursday change → small.
- For robustness, we **also test with `shift(2)` weekly** (use W-2 mean) to confirm results unchanged.

### 3.3 Implementation
Two re-runs:
1. **Corrected-Weekly**: `.shift(2)` for NFCI/ANFCI/STLFSI, `.shift(1)` for USEPU/WLEMU (as in original)
2. **Conservative-Weekly**: `.shift(2)` for ALL alt-data regressors (uniform 2-week lag)

If both agree with original → robust. If either differs materially → investigate.

## 4. Expected Outcomes (prior)

- **H1 (lucky, most likely)**: Original conclusions unchanged.
  - Rationale: Weekly aggregation already dilutes publication-delay bias (4/5 days are kosher for USEPU; NFCI's single weekly value is at most off by ~2 days of usage margin).
  - If the original t-stats are driven mostly by the correct 3-4 days, the fix should only marginally shift them.
- **H2 (concerning)**: 1-2 DM t-stats cross the ±2 threshold.
  - Most suspect: TLT M4 (original t=+3.74, the only positive-significant). If corrected t drops below +2, the only "alt-data wins" cell becomes "null".
- **H3 (disastrous)**: Multiple conclusions flip.
  - Would be surprising given weekly aggregation, but possible if NFCI at week-W boundary happened to be strongly correlated with RV[W] (i.e., the latent lookahead was the main driver).

## 5. References
- Baker, Bloom, Davis (2016) QJE 131(4) — EPU construction and daily release
- Brave, Butters (2011) Fed Letter 286 — NFCI construction, Wed-release-of-Fri-observation
- Kliesen, Smith (2010) STL Fed Economic Synopses — STLFSI weekly cadence
- E062 (docs/error_log.md 2026-04-13) — K1121 NFCI/EPU publication-delay fix precedent
- Paper 4 compendium — depends on K1116/K1118/K1121 being internally consistent
