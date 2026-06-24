# K1545 References

Hand-coded references; no fabricated DOIs. Where DOI unavailable, public URL given.

## EU ETS auction mechanism and primary market

- Trotignon, R., & Solier, B. (2010). *The European carbon allowance auction:
  results of the first phase*. Working paper, Climate Economics Chair (CEC),
  Paris-Dauphine. (Trotignon-Solier ECARES tradition on EU ETS primary auction
  demand depth.)

- Friedrich, M., Mauer, E. M., Pahle, M., & Tietjen, O. (2020). From fundamentals
  to financial assets: the evolution of understanding price formation in the EU
  ETS. *PIK Discussion Paper / SSRN*.
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3640697

- Ellerman, A. D., Marcantonini, C., & Zaklan, A. (2016). The European Union
  Emissions Trading System: ten years and counting. *Review of Environmental
  Economics and Policy*, 10(1), 89-107.
  https://doi.org/10.1093/reep/rev014

## Carbon market price dynamics / event-study methodology

- Mansanet-Bataller, M., & Pardo, A. (2009). Impacts of regulatory announcements
  on CO2 prices. *Journal of Energy Markets*, 2(2), 1-33.

- Conrad, C., Rittler, D., & Rotfuß, W. (2012). Modeling and explaining the
  dynamics of European Union allowance prices at high-frequency. *Energy
  Economics*, 34(1), 316-326. https://doi.org/10.1016/j.eneco.2011.02.011

- Ibikunle, G., & Gregoriou, A. (2018). *Carbon markets: microstructure, pricing
  and policy*. Palgrave Macmillan.

## Carbon ETF / basket-strategy literature

- KraneShares (2024). *KRBN — Global Carbon Strategy ETF prospectus and
  fact sheet*. https://kraneshares.com/krbn/ (official issuer documentation;
  basket composition: EUA, CCA, RGGI).

- Global X (2024). *GRN — Global X EUA ETF fact sheet*.
  https://www.globalxetfs.com/funds/grn/

## Methodology — HAC, event study

- Newey, W. K., & West, K. D. (1987). A simple, positive semi-definite,
  heteroskedasticity and autocorrelation consistent covariance matrix.
  *Econometrica*, 55(3), 703-708. https://doi.org/10.2307/1913610

- MacKinlay, A. C. (1997). Event studies in economics and finance. *Journal of
  Economic Literature*, 35(1), 13-39. https://www.jstor.org/stable/2729691

- Patton, A. J. (2011). Volatility forecast comparison using imperfect volatility
  proxies. *Journal of Econometrics*, 160(1), 246-256.
  https://doi.org/10.1016/j.jeconom.2010.03.034

## Event-list source notes (public news, no DOI required)

- EU Commission press releases on MSR / ETS revision / Fit-for-55
  (https://climate.ec.europa.eu/eu-action/eu-emissions-trading-system-eu-ets_en).
- Reuters / Carbon Pulse coverage of MSR intake adjustments, REPowerEU
  front-load, ETS2 political agreement (Dec 2022), auction calendar publications.
- CARB quarterly auction settlement notices (https://ww2.arb.ca.gov/our-work/
  programs/cap-and-trade-program/auction-information).
- RGGI quarterly auction notices (https://www.rggi.org/auctions/auction-results).

## Related VolPred K

- K1445 (URA/KRBN descriptive vol clustering) — `experiments/k1445/`
  Verdict: CONDITIONAL_PASS (descriptive PoC). K1545 extends with forward
  event-prior framing.

- K1355 (cross-asset pooled inference rule) — `storage/memory/knowledge.json`
  enforces per-date aggregation before HAC for cross-asset tests, complied
  with in `cross_asset_aggregated_test()`.

- K1213 / K1216 (pooled-MLE multistart hard rule) — not applicable (no MLE in
  K1545; pure event study).
