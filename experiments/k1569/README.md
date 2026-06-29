# K1569: Legacy-asset overhang public proxy and transition-shock ETF volatility

**Verdict**: `NULL` for the proposed legacy-overhang amplification claim. The primary tests find no positive high-legacy-minus-low-legacy response after transition or credit shocks. The only family-corrected survivors are **negative** RV responses, meaning the high-legacy group has lower relative forward RV after transition-shock episodes in this proxy design.

## Motivation

Backlog question: when green-tech / automation / transition shocks arrive, do sectors with more legacy physical assets show higher RV persistence, downside semivariance, volume shock, or credit-spread beta?

This experiment is intentionally a public-disclosure proxy screen. It does not observe true stranded assets, plant redeployability, transformation capex, private credit spreads, loan-level exposure, or management transition plans.

## Data

- SEC CompanyFacts / XBRL:
  - Company ticker map from `https://www.sec.gov/files/company_tickers.json`.
  - CompanyFacts endpoint `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json`.
  - 50 representative company filings across sector/ETF baskets.
  - Annual 10-K facts only.
- XBRL proxy:
  - `legacy_asset_score = PP&E/assets - (goodwill + intangibles)/assets`
  - annual facts are available only after filing date + 1 calendar day, aligned to the first following ETF trading date.
- yfinance adjusted OHLCV:
  - Sector / thematic ETF targets with XBRL scores: `XLE`, `KRE`, `KBE`, `XLF`, `XLI`, `XLY`, `XLK`, `ICLN`, `TAN`, `BOTZ`, `ROBO`.
  - Green/automation market-shock basket: `ICLN`, `TAN`, `BOTZ`, `ROBO`.
  - Legacy-market basket for spread shocks: `XLE`, `KRE`, `KBE`, `XLI`, `XLY`.
  - Controls: `SPY`, `^VIX`, `HYG`, `LQD`.
- Sample: 2018-01-02 to 2026-06-26, 2,132 trading rows.

Latest XBRL legacy scores rank `XLE`, `XLY`, and `XLI` as the high-legacy group; `ROBO`, `BOTZ`, and `XLK` are the low-legacy group near the end of the sample.

## Method

- Build daily sector legacy scores from available annual CompanyFacts.
- At each date, sort sector ETF proxies by legacy score.
- Primary outcome is date-level `high legacy group minus low legacy group`.
  - This avoids treating stacked sector-day observations as iid.
- Transition shock:
  - z-score of absolute green-minus-legacy 5d return,
  - z-score of absolute green/automation 5d return,
  - z-score of green/automation 21d RV.
- Credit stress:
  - z-score of negative `HYG-LQD` 5d return spread.
- Tested signals:
  - `transition_shock_lag1`
  - `credit_stress_lag1`
  - `transition_credit_stress_lag1`
- Outcomes:
  - high-minus-low forward 5d / 21d log RV,
  - high-minus-low forward 5d / 21d log downside semivariance,
  - high-minus-low forward 5d / 21d volume shock.
- Primary regression:
  - `HL_forward_outcome ~ signal_lag1 + SPY_log_RV21_lag1 + VIX_level_lag1 + credit_stress_lag1`
  - when the tested signal is `credit_stress`, the duplicate credit control is removed.
- HAC maxlags equals horizon `H`.
- Spearman CI uses moving-block bootstrap with block=`H`, `B=1000`, seed=42.

## Multiple Testing

Primary family:

`2 horizons x 3 outcomes x 3 signals = 18 controlled-HAC tests`

Bonferroni alpha is `0.00278`. PASS would require a positive high-minus-low controlled-HAC coefficient to survive Bonferroni or Holm correction.

## Results

No positive primary cell is raw-significant. No positive cell survives Bonferroni or Holm.

The strongest cells are reversed:

| Cell | Controlled coef | HAC t | p | Spearman rho / CI | Status |
|---|---:|---:|---:|---:|---|
| HL 5d RV, `transition_shock` | -0.112 | -4.20 | 0.000026 | -0.085 [-0.152, -0.018] | negative survivor |
| HL 21d RV, `transition_shock` | -0.115 | -3.68 | 0.000230 | -0.118 [-0.238, +0.021] | negative survivor |
| HL 21d downside, `transition_shock` | -0.118 | -2.87 | 0.00413 | -0.028 [-0.141, +0.104] | negative raw only |
| HL 5d RV, `credit_stress` | -0.028 | -1.55 | 0.121 | -0.028 [-0.089, +0.037] | null |

Interpretation: with this public proxy, transition-market shocks are more associated with RV in low-legacy green/automation/tech baskets than in high-legacy physical-asset sectors. That is the opposite of the proposed "legacy-heavy sector fragility" mechanism and should not be reframed as support.

## Literature / Source Context

- SEC CompanyFacts API: <https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json>
- SEC company ticker map: <https://www.sec.gov/files/company_tickers.json>
- Peters and Taylor (2017), "Intangible capital and the investment-q relation", *Journal of Financial Economics*.
- Bolton and Kacperczyk (2021), "Do investors care about carbon risk?", *Journal of Financial Economics*.
- Pástor, Stambaugh, and Taylor (2021), "Sustainable investing in equilibrium", *Journal of Financial Economics*.

## Outputs

- `k1569.py` — reproducible script.
- `k1569_results.json` — all primary tests, diagnostics, hashes, verdict.
- `k1569_analysis_dataset.csv` — merged daily panel.
- `k1569_sector_legacy_scores.csv` — daily sector legacy scores.
- `data/company_legacy_xbrl_table.csv` — annual company-level XBRL ratios.
- `data/sec_companyfacts/` — cached CompanyFacts JSON files.
- `fig1_sector_legacy_scores.png`
- `fig2_transition_credit_signals.png`
- `fig3_primary_hac_heatmap.png`
- `codex_review.md` — source-level review.

## Lookahead Policy

- XBRL data is not usable until filing date + 1 calendar day, then aligned to the first following ETF trading date.
- Rolling z-score baselines use means/std ending at `t-1`.
- Every tested market signal has explicit `signal.shift(1)`.
- Forward labels use `[t+1, t+H]` via `shift(-i)` for `i=1..H`.
- Primary inference is date-level high-minus-low, not pooled sector-day inference.

## Limitations

- Current representative company baskets are not historical ETF holdings.
- CompanyFacts tag availability varies across issuers; banks and thematic ETFs can have noisy PP&E/intangible ratios.
- The green/automation shock is a market-price proxy, not a verified news taxonomy.
- `HYG-LQD` is a public ETF credit proxy, not firm-level credit spread or private debt data.
- Negative survivor cells likely reflect volatile low-legacy green/automation ETF exposure, not a causal protective effect of physical legacy assets.
