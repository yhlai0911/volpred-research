# research_bhc_ai_loss_disclosure_rv

## Question

Does AI, model-risk, and operational-loss language in large U.S. bank holding company 10-K filings predict next-month realized volatility for bank stocks or bank-sector ETFs?

The motivating channel is not AI capex or broad technology adoption. It is the operational-risk channel suggested by McLemore and Mihov (2026): BHCs with larger AI investment may face higher operational losses, especially where risk management is weaker. This experiment asks whether a public-disclosure proxy for that channel contains ex-ante volatility information.

## Literature And Source Check

- McLemore and Mihov (2026), "AI and Operational Losses: Evidence from U.S. Bank Holding Companies", Review of Corporate Finance Studies, DOI: https://doi.org/10.1093/rcfs/cfag003.
- Federal Reserve / OCC / FDIC supervisory guidance on model risk management: https://www.federalreserve.gov/frrs/guidance/supervisory-guidance-on-model-risk-management.htm.
- NIST AI Risk Management Framework overview: https://www.nist.gov/itl/ai-risk-management-framework.
- SEC EDGAR API documentation for submissions and filing metadata: https://www.sec.gov/search-filings/edgar-application-programming-interfaces.

## Data

- SEC source: `data.sec.gov` submissions metadata plus SEC Archives primary 10-K HTML documents.
- Price source: `yfinance` adjusted close.
- Banks: JPM, BAC, WFC, C, GS, MS, USB, PNC, TFC, COF.
- ETFs: KBE, KRE, XLF, SPY.
- Filing sample: 70 10-Ks, one per bank-year from report years 2019-2025.
- Price sample: 2019-01-02 to 2026-06-23.
- Monthly panel: 738 bank-month observations from 2020-03-31 to 2026-04-30.
- The final observed price month is dropped before constructing next-month targets, so the experiment does not use partial-month realized volatility as a target.

## Design

For each 10-K, the script strips HTML and counts three term groups per 10,000 words:

- AI terms: artificial intelligence, generative AI, machine learning, large language model, algorithmic, automated decisioning.
- Model-risk terms: model risk, model governance, model validation, model controls, model risk management.
- Operational-loss/risk terms: operational loss, operational risk, technology risk, third-party risk, cybersecurity risk, vendor risk.

The filing disclosure state is expanded into a monthly bank panel. The predictor is explicitly lagged by one month:

```python
active[f"{col}_lag1"] = active.groupby("ticker")[col].shift(1)
```

The target is next-month annualized realized volatility computed from daily returns.

Main tests:

- Bank panel OLS with bank fixed effects, year fixed effects, current bank RV, absolute current return, and KBE/XLF/SPY current RV controls; standard errors clustered by month.
- ETF aggregate OLS for KBE, KRE, and XLF using the cross-bank average lagged disclosure proxy plus current ETF RV; HAC standard errors with `maxlags=3`.
- Harvey-style hurdle is `abs(t) > 3.0`.

## Results

Verdict: `MIXED_DISCLOSURE_SIGNAL`.

Primary bank-panel tests:

| model | coef | t | Harvey pass |
| --- | ---: | ---: | --- |
| ai_only | 0.000768 | 0.188 | no |
| model_risk_only | -0.017660 | -0.976 | no |
| operational_only | -0.002417 | -0.394 | no |
| combined | -0.003344 | -0.446 | no |

ETF aggregate tests:

| target | model | coef | t | Harvey pass |
| --- | --- | ---: | ---: | --- |
| KBE | aggregate_ai | -0.016553 | -1.990 | no |
| KBE | aggregate_model_risk | 0.027512 | 2.896 | no |
| KBE | aggregate_operational | -0.015878 | -1.918 | no |
| KBE | aggregate_combined | -0.015551 | -1.895 | no |
| KRE | aggregate_ai | -0.019742 | -1.975 | no |
| KRE | aggregate_model_risk | 0.028649 | 2.585 | no |
| KRE | aggregate_operational | -0.018778 | -1.882 | no |
| KRE | aggregate_combined | -0.018578 | -1.879 | no |
| XLF | aggregate_ai | -0.010263 | -1.476 | no |
| XLF | aggregate_model_risk | 0.024174 | 3.650 | yes |
| XLF | aggregate_operational | -0.011309 | -1.689 | no |
| XLF | aggregate_combined | -0.010559 | -1.550 | no |

The only `abs(t) > 3` result is the XLF aggregate model-risk proxy. It is positive and survives the local hurdle, but it is not supported by the bank-stock panel and does not appear in the broader combined proxy.

## Interpretation

The public 10-K disclosure proxy is not a robust bank-stock RV predictor in this specification. The XLF model-risk result is worth tracking as a governance / sector-risk feature candidate, but the evidence is too narrow for promotion into an active strategy or paper narrative.

The disclosure trend plot shows that operational-risk language rises sharply after 2022, while AI terms rise more gradually. That time trend makes year controls and out-of-sample validation important before treating the proxy as economically stable.

## Limitations

- Disclosure language is a noisy proxy for actual AI investment, internal model inventory, and realized operational losses.
- The panel has only 10 banks and seven filing years.
- 10-K text is low frequency; the monthly expansion assumes the latest filing remains the active public disclosure state.
- ETF aggregate regressions have modest time-series sample size and are vulnerable to common post-2022 sector regime effects.
- This does not use supervisory operational-loss data, which is not public.

## Files

- `research_bhc_ai_loss_disclosure_rv.py` - full experiment script.
- `research_bhc_ai_loss_disclosure_rv_results.json` - machine-readable result summary.
- `data/filing_counts.csv` - SEC 10-K term counts.
- `data/bank_monthly_panel.csv` - monthly bank panel used in regressions.
- `data/bank_panel_regressions.csv` - bank-panel coefficient table.
- `data/etf_aggregate_regressions.csv` - ETF aggregate coefficient table.
- `data/filing_event_windows.csv` - pre/post filing realized-volatility windows.
- `figures/primary_coefficients.png` - primary coefficient intervals.
- `figures/disclosure_trends.png` - yearly disclosure intensity.
