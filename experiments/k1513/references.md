# K1513 References

## Primary commodity momentum / reversal literature

1. **Moskowitz, T. J., Ooi, Y. H., & Pedersen, L. H. (2012). Time series
   momentum. *Journal of Financial Economics*, 104(2), 228–250.**
   DOI: 10.1016/j.jfineco.2011.11.003
   *Relevance*: Canonical paper documenting time-series momentum across asset
   classes including commodity futures over 1-12 month horizons. Establishes
   the unconditional positive autocorrelation that this experiment's
   "low-vol regime → momentum" hypothesis builds on. Our 1-4 week horizon
   sits at the short end of their grid; their evidence is weaker on the
   shortest horizons, motivating the regime-conditional refinement tested
   here.

2. **Bianchi, R. J., Drew, M. E., & Fan, J. H. (2015). Combining momentum
   with reversal in commodity futures. *Journal of Banking and Finance*, 59,
   423–444.**
   DOI: 10.1016/j.jbankfin.2015.07.006
   *Relevance*: Directly addresses the coexistence of momentum and reversal
   in commodity futures using cross-sectional sorts. Documents that combining
   short-term reversal (1 month) with medium-term momentum (12 months)
   delivers Sharpe improvements over either alone — i.e. they exist on
   different horizons. K1513 tests a stronger claim: that they coexist on the
   *same* short horizon and are separable by *vol regime*, not by horizon.
   Bianchi et al. is the closest published null hypothesis to the strand
   K1513 PoC is probing.

3. **Boons, M., & Prado, M. P. (2019). Basis-momentum. *Journal of Finance*,
   74(1), 239–279.**
   DOI: 10.1111/jofi.12738
   *Relevance*: Shows that basis (slope of futures curve) interacts with
   momentum in commodities; high-basis high-momentum commodities deliver
   premia not explained by either signal alone. The ETF proxy used in K1513
   strips out the basis dimension — this is acknowledged in the limitations
   and is the chief reason we cannot reject the JFEM/SSRN thesis on ETF
   evidence alone.

## Methodology references

4. **Diebold, F. X., & Mariano, R. S. (1995). Comparing predictive accuracy.
   *Journal of Business and Economic Statistics*, 13(3), 253–263.**
   DOI: 10.1080/07350015.1995.10524599
   *Relevance*: DM test applied here on `r_rev − r_mom` differential with
   Newey-West HAC standard error (lag = ⌊T^{1/3}⌋). Standard t-statistic
   reported per regime per cell.

5. **Patton, A. J. (2011). Volatility forecast comparison using imperfect
   volatility proxies. *Journal of Econometrics*, 160(1), 246–256.**
   DOI: 10.1016/j.jeconom.2010.03.034
   *Relevance*: Block bootstrap framework cited in the limitations as the
   honest small-sample alternative to normal-approximation DM. K1513 uses
   asymptotic DM for the primary grid; a Patton-style block bootstrap on the
   monthly cells (T_high ~80, T_low ~80) is a natural follow-up.

## Internal prior knowledge

* **K1339** (in-house, CONDITIONAL_PASS): commodity ETF 21d/63d momentum
  regime as backwardation/contango proxy → vol-jump event study. Same
  universe family; complementary outcome variable. Codex review of K1339
  flagged that ETF momentum is not a clean roll-yield proxy — that caveat
  applies here too.
* **K1129 / K1133b** (in-house): BTC GAS-t reversal regime-concentrated by
  period; methodology reference for regime-conditional DM testing.

## Notes on JFEM/SSRN 2025-26 strand

The motivating "coexistence under vol regime" claim is associated with
working-paper-stage commodity-momentum research circulating in 2025-26
(JFEM-positioned). No DOI is cited because the strand is still pre-print at
time of writing and the PoC here is a feasibility check on ETF proxies, not
a replication of a specific manuscript. If a publishable version surfaces,
the references will be updated; the experimental design above is independent
of any specific paper's exact specification.
