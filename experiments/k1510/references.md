# K1510 References

1. **Chernozhukov, V., Chetverikov, D., Demirer, M., Duflo, E., Hansen, C.,
   Newey, W., & Robins, J. (2018).** *Double/debiased machine learning for
   treatment and structural parameters.* The Econometrics Journal, 21(1),
   C1–C68. https://doi.org/10.1111/ectj.12097
   — Methodological backbone for the DML partialling-out estimator used in
   this experiment (cross-fitting + Neyman-orthogonal moment).

2. **Bernard, V. L., & Thomas, J. K. (1989).** *Post-earnings-announcement
   drift: Delayed price response or risk premium?* Journal of Accounting
   Research, 27, 1–36. https://doi.org/10.2307/2491062
   — Original PEAD evidence motivating SUE as a meaningful surprise metric
   and its persistence over multi-month horizons.

3. **Patell, J. M., & Wolfson, M. A. (1981).** *The ex ante and ex post
   price effects of quarterly earnings announcements reflected in option
   and stock prices.* Journal of Accounting Research, 19(2), 434–458.
   — Classical evidence that earnings announcements coincide with vol
   spikes; informs the choice of pre-announcement RV as IV candidate.

4. **Stock, J. H., & Yogo, M. (2005).** *Testing for weak instruments in
   linear IV regression.* In Andrews & Stock (eds.), Identification and
   Inference for Econometric Models. Cambridge University Press.
   — Source of the F > 10 rule-of-thumb threshold used to flag weak-IV in
   this experiment (all our first-stage F < 10 → IV inference unreliable).

5. **Patton, A. J. (2011).** *Volatility forecast comparison using imperfect
   volatility proxies.* Journal of Econometrics, 160(1), 246–256.
   — Standard reference for realized vol as a noisy proxy for true vol;
   informs the QLIKE / robust-loss perspective when comparing vol forecasts
   (not directly used here since we estimate ATE, not forecast loss).
