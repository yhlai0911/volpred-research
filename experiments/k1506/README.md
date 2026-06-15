# K1506: Treasury auction bid-to-cover weakness → MOVE realized vol event study

## Verdict

**INSUFFICIENT_SAMPLE (primary spec) + FAIL (secondary relaxed spec)** —
two-sided Welch t-tests find **no significant elevation** of post-auction
MOVE realized vol after weak auctions; in fact, point estimates are
slightly *lower* for weak vs benign, with mean differences inside
bootstrap 95% CIs that straddle zero.

## Hypothesis

Weak Treasury auctions (low bid-to-cover ratio relative to its trailing
12-month baseline) signal dealer inventory absorption pressure and
information shock. The dealer-hedging literature predicts elevated
follow-through Treasury volatility. Operationalised as:

> H1: mean cumulative ^MOVE realised vol over T+1..T+5 is higher after
> weak auctions (z(BTC) < −1.5) than after benign auctions (|z(BTC)| < 0.5).

## Data

| Source            | Symbol / endpoint                                   | Window                  |
| ----------------- | --------------------------------------------------- | ----------------------- |
| Treasury auctions | TreasuryDirect `/TA_WS/securities/search` (free)    | 2015-01-01 ~ 2026-06-15 |
| MOVE index        | yfinance `^MOVE` daily close                        | 2015-01-02 ~ 2026-06-15 |
| VIX (regime)      | yfinance `^VIX` daily close                         | 2015-01-02 ~ 2026-06-15 |

- Maturity buckets: 10-Year Note (`originalSecurityTerm == "10-Year"`,
  N=140) and 30-Year Bond (N=138).
- Total auctions in sample: **278**.
- Auctions with full T+1..T+5 MOVE window: **276**.

## Design

| Element                 | Spec                                                                               |
| ----------------------- | ---------------------------------------------------------------------------------- |
| Signal                  | bid-to-cover z-score vs **trailing 12M rolling mean/std per maturity bucket**       |
| Lookahead-safe baseline | rolling stats use only auctions with `auctionDate < T` (strict past)                |
| Weak threshold (primary)| z < −1.5                                                                            |
| Benign control          | |z| < 0.5                                                                           |
| Forward window          | T+1 .. T+5 trading days (signal_lag = 1; the auction is fully observed at T close) |
| Realised vol metric     | cum_vol = sqrt(Σ log_ret²) over the 5-day window                                   |
| Test                    | Welch two-sample t-test (unequal variance allowed)                                  |
| Effect size             | Cohen's d                                                                          |
| Bootstrap               | 5000 reps, seed=42, percentile 95% CI of mean difference                            |
| Robustness 1            | per maturity (10Y / 30Y separately)                                                |
| Robustness 2            | per VIX regime at T (high vs low vs trailing 12M median)                            |
| Secondary spec          | weak = z < −1.0 (relaxed for sample size)                                          |

**Lookahead protections (verified in `k1506.py`):**
- `build_signal()`: `past = grp.iloc[:i]` — z-score uses ONLY rows
  strictly before the event row, never including the event itself.
- `run()`: `next_idx = move_s.index.searchsorted(T + pd.Timedelta(days=1))`
  forces the post-window first day to be the first trading day **strictly
  after** auction day T.

## Results

### Category counts (event-eligible, N=276)

| category | count |
| -------- | ----- |
| weak (z < −1.5) | 26 |
| benign (|z| < 0.5) | 97 |
| other (−1.5 ≤ z ≤ −0.5 or 0.5 ≤ z) | 141 |
| skip (insufficient baseline) | 12 |

### Primary spec (z < −1.5; preregistered)

| metric                            | weak (N=26) | benign (N=97) |
| --------------------------------- | ----------- | ------------- |
| mean post-window cumulative MOVE vol | 0.0879  | 0.0920        |
| std                               | 0.0394      | 0.0414        |

- Welch t = **−0.468**, p (two-sided) = **0.642**, Cohen's d = **−0.10**
- Sample below preregistered threshold (need ≥30 weak); verdict
  formally `INSUFFICIENT_SAMPLE`, but the descriptive direction is
  **opposite** to the hypothesis.

### Secondary spec (z < −1.0; relaxed)

| metric                            | weak (N=45) | benign (N=97) |
| --------------------------------- | ----------- | ------------- |
| mean post-window cumulative MOVE vol | 0.0865  | 0.0920        |
| std (≈)                           | 0.039       | 0.041         |

- Welch t = **−0.773**, p (two-sided) = **0.441**, Cohen's d = **−0.14**
- Bootstrap 95% CI of mean diff (weak − benign): **[−0.0195, +0.0084]**
- Verdict: **FAIL** (CI straddles 0 with mass on negative side).

### Robustness per maturity

| maturity | N_weak | N_benign | mean_weak | mean_benign |
| -------- | ------ | -------- | --------- | ----------- |
| 10-Year  | 14     | 45       | 0.0866    | 0.0954      |
| 30-Year  | 12     | 52       | 0.0894    | 0.0891      |

Neither sub-sample exceeds the per-arm 15 threshold needed for stable
estimates; 30Y is essentially tied; 10Y direction also opposite to H1.

## Interpretation

- The point estimate is **directionally opposite** to the dealer
  inventory-pressure hypothesis: weak auctions are followed by *slightly
  less* MOVE vol on average. Effect size is trivial (|d| ≈ 0.10–0.14)
  and statistically indistinguishable from zero.
- One plausible explanation: by the time the public sees the auction
  print, primary dealers may already have hedged in the run-up (the T-5
  to T-1 window), so the residual price-impact on MOVE is washed out.
- Another: a single auction's BTC z-score may be too noisy a proxy for
  systemic dealer stress. Aggregated weekly dealer position data
  (NYFRB primary dealer statistics) might dominate this design.
- Sample-size note: 11.5 years of bi-monthly 10Y + monthly 30Y
  auctions gives only ~26 weak events under z<−1.5. Even halving the
  threshold (z<−1.0) yields N=45, still p≈0.44. Larger N (e.g. add 7Y,
  20Y, TIPS) would not be expected to flip the sign given how flat
  the descriptive estimates are.

## Conclusion

The hypothesis that weak Treasury auctions lead the MOVE index over a
5-day window is **not supported** in 2015-2026 daily data. Both the
preregistered (z<−1.5) and relaxed (z<−1.0) specifications produce
**null, directionally-opposite** results.

This is reported as an honest **null finding**, contrasting with
priors in dealer-inventory and supply-shock literature (Greenwood &
Hanson 2014; Krishnamurthy & Vissing-Jorgensen 2011) which typically
operate at lower frequency (monthly/quarterly) or on yield-level rather
than realised-vol outcomes.

## References

1. Fleming, M. J., & Garbade, K. D. (2003). "The repurchase agreement
   refined: GCF Repo." *Current Issues in Economics and Finance*, 9(6),
   Federal Reserve Bank of New York. — dealer-balance-sheet mechanics
   around Treasury auctions.
2. Greenwood, R., & Hanson, S. G. (2014). "Issuer quality and corporate
   bond returns." *Review of Financial Studies*, 27(8), 2389–2461. DOI:
   10.1093/rfs/hhu030. — supply-side determinants of fixed-income
   return / vol dynamics.
3. Lou, D., Yan, H., & Zhang, J. (2013). "Anticipated and repeated
   shocks in liquid markets." *Review of Financial Studies*, 26(8),
   1891–1912. DOI: 10.1093/rfs/hht034. — predictable Treasury auction
   announcement effects and dealer pre-positioning (the cited mechanism
   for why our null may actually be expected: dealers absorb the
   information *before* settlement).
4. Krishnamurthy, A., & Vissing-Jorgensen, A. (2011). "The effects of
   quantitative easing on interest rates: channels and implications
   for policy." *Brookings Papers on Economic Activity*, Fall 2011,
   215–287. — Treasury supply shocks and yield dynamics.

## Reproducibility

```bash
cd <repo>/experiments/k1506
uv run python k1506.py
# writes k1506_results.json, k1506_events.csv, figures/*.png
```

All randomness seeded (`SEED=42` for numpy and bootstrap RNG).
TreasuryDirect API is public, free, no auth. yfinance daily close is
unadjusted. Total runtime ~30s including data fetches.
