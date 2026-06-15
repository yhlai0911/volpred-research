# K1506 References

## Primary

- **Lou, D., Yan, H., & Zhang, J. (2013).** Anticipated and repeated
  shocks in liquid markets. *Review of Financial Studies*, 26(8),
  1891–1912. DOI: [10.1093/rfs/hht034](https://doi.org/10.1093/rfs/hht034).
  Verified: indexed on Oxford Academic. Key claim used in this study:
  Treasury dealers anticipate auction supply and pre-hedge in the days
  *before* auction, which can wash out post-auction price impact —
  consistent with our observed null on T+1..T+5 MOVE vol.

- **Greenwood, R., & Hanson, S. G. (2014).** Issuer quality and corporate
  bond returns. *Review of Financial Studies*, 27(8), 2389–2461. DOI:
  [10.1093/rfs/hhu030](https://doi.org/10.1093/rfs/hhu030). Verified.
  Supply / demand frictions in fixed income — provides theoretical
  prior for why weak demand auctions *should* matter; this study finds
  no MOVE-level transmission at daily frequency.

- **Fleming, M. J., & Garbade, K. D. (2003).** The repurchase agreement
  refined: GCF Repo. *Current Issues in Economics and Finance*, 9(6),
  Federal Reserve Bank of New York. Verified via FRBNY publications.
  Background on primary dealer balance-sheet mechanics around Treasury
  settlement.

## Supporting

- **Krishnamurthy, A., & Vissing-Jorgensen, A. (2011).** The effects of
  quantitative easing on interest rates: channels and implications for
  policy. *Brookings Papers on Economic Activity*, Fall 2011, 215–287.
  Verified on Brookings.edu. Treasury supply shocks → yield dynamics.

- TreasuryDirect API documentation (public):
  https://www.treasurydirect.gov/TA_WS/ — used for `bidToCoverRatio`,
  `originalSecurityTerm`, `auctionDate` fields.

- Patton, A. (2011). Volatility forecast comparison using imperfect
  volatility proxies. *Journal of Econometrics*, 160(1), 246–256. —
  methodological reference for working with realised volatility proxies
  (here we use cumulative absolute log-returns rather than RV proper).
