# K1551 - Bond ETF AP-Fragility Proxy

## Research Question

Do bond ETFs with higher authorized-participant fragility have larger stress-day price/NAV dislocations and higher next-5-day realized volatility?

K1551 can only answer a narrower proxy version. Public yfinance data does not expose ETF-level authorized-participant activity, AP market share, or 13F AP concentration for the tested funds. The experiment therefore separates:

- **Data audit**: yfinance `institutional_holders` is empty/404 for all eight bond ETFs.
- **Diagnostic proxy test**: a free-data AP-fragility proxy is compared with stress-day fair-value residuals and next-5-day RV.

The result must not be cited as evidence about actual AP concentration.

## Literature Basis

- Bank of Canada Staff Analytical Note 2020-27, "Concentration in the market of authorized participants of US fixed-income ETFs": fixed-income ETF AP activity is more concentrated than equity ETF AP activity; the top three APs performed 82% of gross creations/redemptions in 2019. Source: https://www.bankofcanada.ca/2020/11/staff-analytical-note-2020-27/
- BIS Quarterly Review, "The anatomy of bond ETF arbitrage": bond ETF baskets differ materially from holdings and the arbitrage mechanism can weaken during stress. Source: https://www.bis.org/publ/qtrpdf/r_qt2103d.htm
- "Stress-Tested: Municipal Bond ETFs During Market Turmoil": municipal bond ETFs showed large and persistent NAV dislocations during the COVID-19 stress period. Source: https://afajof.org/management/viewp.php?n=192668
- ICI, "The Role and Activities of Authorized Participants of Exchange-Traded Funds": institutional background on the AP creation/redemption mechanism. Source: https://www.ici.org/pubfile_pdf/ppr_15_aps_etfs.pdf

Related project context: K1538 found only weak directional evidence for free bond-fund run-pressure proxies; K1499 found that a BIZD-HYG NAV-discount-style proxy partly survived for HYG 5d but BDC-RV stress largely collapsed after SPY-vol controls. K1551 is a bond ETF structure diagnostic, not a credit beta result.

## Data

- Price source: yfinance daily OHLCV.
- Fund metadata source: yfinance `funds_data` snapshot.
- Sample: 2015-01-01 to 2026-06-25 download window.
- Tested ETFs: `AGG`, `BND`, `LQD`, `HYG`, `MUB`, `EMB`, `TLT`, `IEF`.
- Factor ETFs for fair-value model: `SHY`, `IEI`, `TLT`, `LQD`, `HYG`, `SPY`.
- Stress definition: `VIX > 25` or `MOVE > 120` on date `t`.
- Panel rows: 23,088.
- Valid stress dates in market panel: 584; after rolling residual availability, per-ETF stress observations are 570.

Data availability audit:

- `institutional_holders` rows are zero for all eight tested bond ETFs.
- yfinance emits ETF fundamentals 404 responses for institutional-holder modules.
- No ETF-level AP identity, AP creation/redemption share, borrowable AP capacity, or 13F AP concentration is observed.

## Method

The AP-fragility proxy is the cross-sectional mean z-score of:

- credit complexity: `BB + B + below-B + BBB` rating share;
- category complexity: corporate / high-yield / emerging-market / municipal category flag;
- annual holdings turnover;
- daily high-low spread proxy;
- inverse median dollar-volume depth.

The price/NAV dislocation proxy is not actual NAV premium/discount. It is the absolute residual from a rolling fair-value model:

```text
r_ETF,t = alpha + beta * r_factor,t + residual_t
```

OLS coefficients are estimated only on observations before date `t` using a rolling 504-day window and at least 252 observations. Same-day factor returns are used to proxy same-day fair-value moves; only prior data determine coefficients.

Forward volatility target:

```text
fwd5_rv_t = sum(ret_{t+1}^2 ... ret_{t+5}^2)
```

Lookahead controls:

- Rolling OLS coefficients use data through `t-1`.
- Stress indicator is observed on date `t`.
- Forward RV starts at `t+1`.
- The experiment never multiplies a same-day signal by same-day future return.
- Bootstrap procedures use `SEED = 1551`.

Formal tests:

- Date-level high-fragility minus low-fragility group spread on normal vs stress days.
- Welch t-test for the stress-vs-normal group spread.
- 5000-rep date bootstrap CI for the stress group spread net of the normal mean.
- Cross-sectional Spearman correlation between ETF fragility score and each ETF's stress lift.

## Results

Verdict: `PARTIAL_GROUP_SUPPORT_MIXED_ETF_RANKING`.

Group-level evidence:

| Metric | Normal high-minus-low | Stress high-minus-low | Stress DID | Welch t | Bootstrap 95% CI |
|---|---:|---:|---:|---:|---:|
| Abs fair-value residual | 0.000386 | 0.001246 | 0.000860 | 8.34 | [0.000672, 0.001069] |
| Forward 5d RV | -0.000055 | 0.000052 | 0.000107 | 4.88 | [0.000067, 0.000153] |

High-fragility group: `EMB`, `HYG`, `LQD`, `MUB`.

Low-fragility group: `AGG`, `BND`, `IEF`, `TLT`.

The group split supports the stress-fragility channel: credit/EM/muni/corporate bond ETFs have larger stress-day fair-value residuals and higher forward 5-day RV relative to government/core bond ETFs.

However, ETF-level ranking is mixed:

- Spearman fragility score vs abs-residual stress lift: rho = 0.262, p = 0.531.
- Spearman fragility score vs forward-5d RV stress lift: rho = 0.214, p = 0.610.
- `TLT` is a low-fragility government ETF under this proxy but still has a large stress lift because duration shocks dominate some stress windows.

Interpretation: K1551 supports a narrow group-level diagnostic that bond ETF structure/liquidity proxies matter on stress days. It does not validate a precise ETF-level AP concentration ranking and does not prove that actual AP concentration caused the dislocations.

## Figures

- `figures/k1551_fragility_scores.png`
- `figures/k1551_stress_lifts.png`
- `figures/k1551_group_spreads.png`

## Reproduction

```bash
uv run python experiments/k1551/k1551.py
```

Main artifacts:

- `k1551.py`
- `k1551_results.json`
- `data/prices.parquet`
- `data/fund_metadata.csv`
- `data/fragility_scores.csv`
- `data/data_availability_audit.json`
- `data/panel.parquet`
- `data/panel_preview.csv`
- `figures/*.png`
- `codex_review.md`

## Limitations

- This is not a true AP concentration test; ETF-level AP market shares are not observed.
- The dislocation proxy is a rolling fair-value residual, not actual ETF price minus NAV.
- yfinance fund metadata is a current snapshot and may not match historical characteristics.
- The eight-ETF cross-section has low power; group results should not be overfit into ticker rankings.
- `TLT` shows that duration stress can produce large residual/RV lifts even outside the high-fragility credit/EM/muni group.
- No creation/redemption basket data, primary-market AP flow, TRACE bond liquidity, ETF NAV time series, or CRSP ETF premium/discount data are included.
- Knowledge promotion is deferred to the main K1259 writer gate; this Codex experiment does not write `storage/memory/knowledge.json`.
