# K1678: Public Saliency and Post-Manipulation Crash Risk

## Research question

Do abnormal public-attention shocks amplify next-day or next-five-day crash risk after dates that a later SEC complaint labels as manipulative trading?

K1678 is an empirical **retrospective proxy diagnostic**, not a causal replication and not a live manipulation detector. The SEC label was filed in 2026, after every event date, and Wikimedia topic pageviews are market-wide attention proxies rather than ticker-specific search, social-post, news, order-flow, or investor data.

## Why this differs from prior work

- K1554's public Stocktwits history was too shallow: 22 events from only KOSS and KSS.
- K1340 used price-volume pressure rather than an observed public-attention measure and found no directional crash-risk pass.
- K1487 found no OOS RV value from coarse GDELT topic intensity.
- The anti-stockholder-identity Wikimedia experiment found a raw 22-day retail/meme RV association, but it failed Holm and OOS gates.

K1678 instead combines a full official SEC complaint attachment with a past-only Wikimedia attention shock, exact t+1/t+5 targets, same-ticker matched controls, and a predeclared eight-cell multiple-testing family.

## Data and methodology

### SEC weak label

- Source: [SEC Litigation Release 26532](https://www.sec.gov/enforcement-litigation/litigation-releases/lr-26532) and its [complaint](https://www.sec.gov/files/litigation/complaints/2026/comp26532.pdf), filed 2026-04-20.
- Attachment A explicitly lists ticker symbols and "Dates of Manipulative Trading" alleged in *SEC v. Harsh V. Patel*.
- The parser walks all 17 attachment pages, removes option identifiers, and enforces exact full-population invariants: 439 table rows, 412 plain equity tickers, 1,083 date occurrences, and 1,079 unique ticker-date pairs (2021: 474; 2022: 225; 2023: 378; 2024: 2).
- Legal/status caveat: these are complaint allegations, not convictions. They are known only retrospectively.
- Mechanism caveat: the complaint alleges rapid odd-lot price ramps and non-bona-fide limit orders. It is not a social-media-manipulation sample; therefore it can only test whether broad public saliency co-varies with post-event risk.

### Public saliency proxy

- Source: official [Wikimedia Analytics Pageviews API](https://doc.wikimedia.org/generated-data-platform/aqs/analytics-api/reference/page-views.html), daily, 2020-01-01 through 2024-02-15.
- Primary stable topic pages: `Pump_and_dump`, `WallStreetBets`, `Short_squeeze`, `Day_trading`, and `Robinhood_Markets`.
- Denominator pages: `Stock_market`, `S&P_500`, `Nasdaq_Composite`, `Dow_Jones_Industrial_Average`, and `Investment`.
- Raw shock: past-only 126-day z-score of

  ```text
  log(1 + 7-day topic views) - log(1 + 7-day broad-finance views)
  ```

  The rolling mean and standard deviation end at t-1. Secondary sensitivities use `Pump_and_dump` alone and a broader 21-day topic composite.

### Market data and targets

- Source: yfinance daily OHLCV, requested 2020-01-01 through 2024-02-15.
- OHLC is adjusted with the `Adj Close / Close` factor; current data availability determines which historical SEC tickers remain accessible. Missing/delisted symbols are disclosed as attrition, not replaced.
- Targets start after the formation day and cover H=1 or H=5:

  - RV: mean squared close-to-close log return × 10,000.
  - DSV: mean squared negative close-to-close log return × 10,000.
  - Left-tail loss: maximum downside close-to-close loss in percent.
  - Downside gap: maximum downside open-versus-prior-close gap in percent.

## Lookahead policy

At event/formation day t, the complaint event indicator and raw Wikimedia shock are known only for retrospective analysis. The code explicitly applies:

```python
sec_event_lag1 = sec_event.shift(1)
saliency_z_lag1 = saliency_raw_z.shift(1)
```

The row receiving those signals starts its target on the next observed trading day. Thus H=1 is t+1, and H=5 is t+1 through t+5. Matching features (lagged returns, RV, volume, SPY, and VIX) are also formed only through t.

This timing prevents outcome leakage, but it does **not** make the 2026 complaint label point-in-time information.

## Matched-event design

For each usable SEC-labelled event:

1. De-cluster labelled events within ticker by H trading rows so forward windows do not overlap.
2. Exclude any candidate control within `max(10, H)` trading rows of every labelled event.
3. Select three nearest same-ticker controls within 252 trading rows, preferring the same calendar year.
4. Match on lagged 1-day/5-day returns, lagged 21-day RV, abnormal volume, SPY return, and VIX.
5. Compute event-minus-control outcome and saliency differences.
6. Average multiple tickers sharing an event date before inference.

A no-label control is not proven clean: it only means this complaint did not label that ticker-date.

## Inference and predeclared gate

The primary family is fixed at m=8: four outcomes × two horizons.

- OLS on event-date aggregates, with the matched saliency difference standardized to one sample standard deviation.
- HAC lag is horizon-specific: 0 for H=1 and 4 for H=5.
- Harvey directional strength requires t ≥ 3.
- Bonferroni and Benjamini-Hochberg are both computed over exactly m=8.
- Moving-block bootstrap uses base seed 42, 2,000 replications, and block length `max(10, H)`. To keep cells independent but reproducible, the recorded cell seed is `42 + 100 × H + outcome_index`, where the outcome index is RV=0, DSV=1, left-tail=2, and gap=3.

Cell pass requires a positive coefficient, HAC t ≥ 3, Bonferroni p < 0.05, BH q < 0.05, and a positive bootstrap 95% lower bound. A broad positive conclusion requires at least two strict cells; one strict cell is reported as weak single-cell evidence.

## References

- Li, Z., Liu, J., Liu, J., Liu, X., and Wu, C. (2025), “Investor attention and stock price manipulation: Evidence from daily quasi-natural experiments,” *Journal of Banking & Finance*, 179, 107528. [DOI](https://doi.org/10.1016/j.jbankfin.2025.107528)
- Chen, Z., Li, Z., Liu, J., and Liu, X. (2026), “Information salience, investor attention, and stock price crash risk,” *Journal of Empirical Finance*, 85, 101670. [DOI](https://doi.org/10.1016/j.jempfin.2025.101670)
- Hong, Z., Liu, Q., Tse, Y., and Wang, Z. (2023), “Black mouth, investor attention, and stock return,” *International Review of Financial Analysis*, 90, 102921. [DOI](https://doi.org/10.1016/j.irfa.2023.102921)
- Cheng, F., Wang, C., Chiao, C., Yao, S., and Fang, Z. (2021), “Retail attention, retail trades, and stock price crash risk,” *Emerging Markets Review*, 49, 100821. [DOI](https://doi.org/10.1016/j.ememar.2021.100821)
- Da, Z., Engelberg, J., and Gao, P. (2011), “In Search of Attention,” *Journal of Finance*, 66(5), 1461–1499. [DOI](https://doi.org/10.1111/j.1540-6261.2011.01679.x)

## HAC bandwidth: known deviation from the repo rule, and why the verdict survives it

`K1678.py:872` sets `maxlags = horizon - 1` for every date-clustered HAC fit. At H=1 that is
`maxlags = 0`, which truncates the Bartlett kernel at zero lags and leaves White
heteroskedasticity-robust standard errors — robust to heteroskedasticity, but carrying **no
serial-correlation correction whatsoever**. The repo's canonical bandwidth rule (`.claude/rules/experiments.md`, from the K1655 lesson) is
`lag = max(h-1, ceil(h^(1/3) * n^(1/3)))` and names `h-1` at `h=1` as a degenerate case to catch on
sight. That rule was mechanised on 2026-07-11, one day after this experiment ran, and its ratchet
(`scripts/tests/test_dm_hac_lag_ratchet.py`) classifies hand-written DM loops rather than a
statsmodels `cov_type="HAC"` call, so nothing flagged this site.

Omitting the correction is a two-sided misspecification, not a one-way inflation: positive residual
autocorrelation inflates `|t|`, but negative autocorrelation deflates it, so a null cannot be
assumed safe without measuring. `hac_bandwidth_check.py` therefore re-fits all eight predeclared
cells from the cached matched-event panel across `maxlags ∈ {as-run, canonical, 4, 8, 12, 20}`
(canonical = 7 at H=1 with n=302 clusters, 11 at H=5 with n=242).

- The as-run bandwidth replicates the stored cells to a maximum `|t|` discrepancy of `2.16e-15`.
- Residual first-order autocorrelation is small in every cell: `-0.079` to `+0.292`.
- Maximum `|t|` over all eight cells **and every bandwidth** is `1.258` (downside gap, H=5, as-run),
  against a Harvey gate of `t ≥ 3`; 0/8 cells reach the strict gate at any bandwidth, and the
  smallest Bonferroni-adjusted p at the canonical bandwidth is `1.0`.

Every fit that went through `fit_date_hac` inherited the same bandwidth, so all three families are
swept rather than argued away from their as-run `|t|`:

The grid is discrete, not continuous: `maxlags ∈ {as-run, canonical, 4, 8, 12, 20}` per cell, so
every statement below is scoped to the **tested** bandwidths and claims nothing about the values in
between.

| Family | Cells | Max \|t\| over tested bandwidths | Reaches Harvey t ≥ 3 |
|---|---:|---:|---|
| Primary `saliency_diff` (predeclared, defines the verdict) | 8 | 1.258 | 0/8 at every tested bandwidth |
| Sensitivity `pump_diff` / `saliency21_diff` | 16 | 1.672 | 0/16 at every tested bandwidth |
| Direct event-minus-control diagnostic (intercept-only, secondary) | 8 | 4.129 | 4/8 at every tested bandwidth |

The sensitivity family is worth the sweep rather than an appeal to its stored `|t| = 1.536`: the
maximum rises to `1.672` once bandwidth varies. It stays far from the gate, but that is a measured
result, not an assumption — assuming it would repeat the exact reasoning error this check exists to
catch.

The direct diagnostic is the one place where `|t|` sits above 3, and this is **not** a discovery of
the sweep: the four cells concerned (left-tail and downside gap, both horizons) already carry those
values in `K1678_results.json` at the as-run bandwidth. What the sweep adds is that they stay above
the gate at every tested bandwidth, spanning `3.305` to `4.129`.
This diagnostic is intercept-only, is not part of the predeclared family, and carries no
multiple-testing correction, so it cannot be promoted to a headline claim — but it is the reason
this experiment's null is narrow. SEC-labelled dates are followed by materially worse tails than
their matched same-ticker controls (H=5 left-tail loss: 16.399% on labelled dates versus 10.391% on
controls). What fails is the attempt to explain **which** labelled events turn out worse using a
free market-wide attention proxy — not the proposition that the labelled dates are risky.

The bandwidth deviation is real methodology debt and is recorded as such, but it does not move this
experiment's verdict: `NULL_NO_ROBUST_SALIENCY_AMPLIFICATION` holds under the canonical rule.
Results are in `K1678_hac_bandwidth_check.json`.

## Reproduction

```bash
uv run python experiments/K1678/K1678.py
uv run python experiments/K1678/hac_bandwidth_check.py   # closeout robustness check, cached panel only
```

Artifacts:

- `K1678.py`
- `K1678_results.json`
- `K1678_primary_results.csv`
- `K1678_matched_events.csv.gz`
- `K1678_saliency_crash_risk.png`
- `hac_bandwidth_check.py` / `K1678_hac_bandwidth_check.json`
- `data/` source snapshots, parser output, and analysis panel

## Result

Verdict: `NULL_NO_ROBUST_SALIENCY_AMPLIFICATION`.

Coverage after current-data attrition:

- SEC attachment: 412 tickers / 1,079 unique alleged ticker-dates.
- yfinance: 252 labelled tickers had some price history; 250 had enough data for the analysis panel.
- Exact labelled ticker-dates observed in the price panel: 657.
- H=1: 525 matched event rows, 205 tickers, 302 event-date clusters.
- H=5: 345 de-clustered matched event rows, 204 tickers, 242 event-date clusters.

Primary saliency-amplification results:

| Target | H | β per 1-SD matched saliency difference | HAC t | Two-sided p | BH q |
|---|---:|---:|---:|---:|---:|
| RV | 1 | +57.634 | +0.557 | 0.578 | 0.772 |
| DSV | 1 | +71.565 | +0.754 | 0.451 | 0.772 |
| Left-tail loss | 1 | -0.359 | -0.473 | 0.636 | 0.772 |
| Downside gap | 1 | -0.211 | -0.684 | 0.494 | 0.772 |
| RV | 5 | +33.721 | +0.710 | 0.478 | 0.772 |
| DSV | 5 | +13.857 | +0.419 | 0.675 | 0.772 |
| Left-tail loss | 5 | -0.126 | -0.106 | 0.915 | 0.915 |
| Downside gap | 5 | -0.798 | -1.258 | 0.208 | 0.772 |

All Bonferroni p-values equal 1.0, all eight 2,000-rep moving-block bootstrap confidence intervals cross zero, no cell reaches Harvey t=3, and no positive cell survives even BH alone. `Pump_and_dump`-only and broader 21-day saliency sensitivities also stay below |t|=1.54.

The SEC-labelled dates themselves have higher matched left-tail and downside-gap point estimates in the secondary direct-event diagnostic. That makes the null more specific: the broad Wikimedia proxy fails to explain **which** labelled events have worse subsequent risk; the result is not evidence that the labelled events were benign.

Interpretation: free market-wide topic pageviews are too coarse to support a saliency-driven manipulation/crash-risk claim in this retrospective U.S. sample. This does not reject the JBF/JEF mechanism identified with exogenous China-specific salience or the possibility that ticker-specific historical search, Reddit, Stocktwits, news, or order-flow data would work.

Verification:

- Independent recomputation matched all eight HAC coefficients, t-statistics, and p-values to numerical error below 1e-12.
- Every matched target and saliency difference was recomputed from the analysis panel; maximum target discrepancy was 7.3e-12.
- The nearest selected control was 11 trading rows from every labelled event, satisfying the `max(10,H)` exclusion.
- A second complete cached run reproduced byte-identical CSV, deterministic gzip, PNG, and canonical JSON (excluding `generated_at`).
