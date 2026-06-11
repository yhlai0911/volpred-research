# K1467 References

## Primary benchmark

1. **JPMorgan / Goldman Sachs (2024-2025)** — "The true cost of tail hedging" / "Cost of crash insurance"  
   Industry research notes (reported widely in Bloomberg, FT, Risk.net) quoting **~-355 bps/yr long-run drag** for systematic VIX call / VXX-overlay tail-hedge programs.  
   (No academic DOI; used here as headline industry benchmark for the 10% VXX overlay sample-equivalent drag of -335 bps/yr.)

## Tail hedging literature

2. **Bhansali, V. (2014)** — "Tail Risk Hedging: Creating Robust Portfolios for Volatile Markets", McGraw-Hill.  
   Canonical reference for the drag-vs-crisis-alpha trade-off framework; explicit treatment of why long-vol hedges have expected negative carry that is recouped only in tail events.

3. **Israelov, R. (2017)** — "Pathetic Protection: The Elusive Benefits of Protective Puts", AQR working paper.  
   Argues that protective-put / VIX-call programs systematically destroy value over long horizons because the implied-vs-realized vol risk premium dominates the convex payoff; the present experiment empirically tests an ETF-implementable analog (5%/10% VXX overlay) and finds drag (-157 to -335 bps) consistent with Israelov's prediction but with Sharpe / MDD improvement (-13 ppt MDD reduction).

## Methodology

4. **Newey, W. K., & West, K. D. (1987)** — "A Simple, Positive Semi-Definite, Heteroskedasticity and Autocorrelation Consistent Covariance Matrix", *Econometrica* 55(3), 703-708. DOI: 10.2307/1913610.  
   HAC standard errors used for the SPY-on-strategy regression (`lags=5`, daily data).

5. **Patton, A. J. (2011)** — "Volatility forecast comparison using imperfect volatility proxies", *Journal of Econometrics* 160(1), 246-256. DOI: 10.1016/j.jeconom.2010.03.034.  
   Pre-registered crisis-window selection methodology (avoid data-mined ex-post sample splits) — implemented here as 4 windows hard-coded in `CRISES` constant.

## Prior K-experiments in this lab

- **K544**: 12/VIX target-vol overlay rejection (double-hedge redundancy) — re-run as benchmark in K1467, confirmed.
- **K657**: synthetic tail hedge PASS — K1467 replaces synthetic with real VXX and finds the trade-off is much closer to break-even.
