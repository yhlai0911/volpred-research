# K1500 — Treasury auction bid-to-cover ratio as MOVE vol leading signal

## Motivation

The ICE BofA MOVE Index is the rates-market analog of VIX, measuring 1-month
implied volatility of Treasury options across 2y/5y/10y/30y tenors. Practitioner
intuition: when a US Treasury auction prints a **weak** bid-to-cover ratio (BTC =
total tendered / total accepted, low value = soft demand), primary dealers absorb
the residual supply, and secondary-market liquidity tightens — pushing MOVE up
in the following days.

This experiment tests whether realized auction-demand weakness contains
**leading information** for MOVE log-changes at horizons h ∈ {1, 5, 10} trading
days.

## Hypothesis

H1: weakness_signal_{t-1} (= -z_score(BTC_{t-1})) is **positively predictive**
of log-MOVE change at t..t+5.

Null: weakness has no incremental predictive power over a naive AR(1) on
MOVE or the historical-mean baseline.

## Data

- **Treasury auctions**: US Treasury Fiscal Data API `auctions_query`
  (https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/od/auctions_query),
  filtered to `security_type in (Note, Bond, TIPS)` with maturity ≥ 5 years
  and a parseable bid-to-cover ratio. **1,028 events** between 2010-01-11 and
  2026-06-11.
- **MOVE Index**: yfinance ticker `^MOVE` (ICE BofA MOVE), daily Close,
  2010-01-04 → 2026-06-12, **4,053 trading days**.
- Both pulls cached under `data/` (parquet) so reruns are deterministic.

## Method

### Phase 1 — Descriptive
- BTC pooled distribution (mean=2.53, std=0.23, p25=2.38, p75=2.64, max=3.72)
- MOVE log-difference distribution (mean ≈ −1e-4, std=0.0445, skew=0.55,
  kurt=5.5 — typical fat-tailed vol-change distribution)
- Quintile breakdown of forward MOVE change by `weakness` (-z(BTC))

### Phase 2 — Event study
- "Weak" event: weakness_z ≥ +1 (BTC ≥1 std below trailing 60-event mean)
- "Strong" event: weakness_z ≤ −1
- Random control: equal-size sample from non-auction days
- Estimation window [t−30, t−5], event window [t−5, t+10], cumulative
  abnormal log-MOVE change
- Bootstrap mean & 95% CI (n=5,000, seed=42) on CAR(t..t+5)
- Welch t-test between weak vs random-control distributions

### Phase 3 — Predictive regression with OOS rolling forecast
- Target: y_{t+h} = log(MOVE_{t+h}) − log(MOVE_t), h ∈ {1, 5, 10}
- Predictors: weakness_{t−1}, sig_active_{t−1} indicator, AR(1) lag of
  dlog_move
- Baselines: AR(1) on MOVE only; historical-mean constant
- OOS: rolling fit window = **504 trading days (~2y)**, step = 21 days
- Tests: in-sample HAC-naive OLS (intercept t-stat reported but std error
  is iid-OLS, not Newey-West — see Limitations), DM test with HLN small-sample
  adjustment for h-step forecast horizons, Mincer–Zarnowitz joint α=0 β=1

## Lookahead controls (research-honesty section)

1. **Signal at auction day t is only used to predict MOVE at t+1 onward**
   (`signal.shift(1)` in `daily_panel`). Auction results post ~1pm ET; we
   conservatively forfeit same-day MOVE info to avoid endogeneity.
2. **Rolling z-score uses `.shift(1).rolling(60)`** — current observation
   is **excluded** from its own normalization window.
3. **AR(1) baseline uses the same t−1 information set** (`dlog_lag1 =
   dlog_move.shift(1)`).
4. **Forward returns** are `move_log.shift(-h) - move_log` — does not enter
   any predictor.
5. **OOS train-test split**: rolling window `[start:train_end]` fits;
   predict block `[train_end:test_end]` strictly after fit window.
6. **Event-study estimation vs event windows do not overlap**: mu_est from
   `[idx-30, idx-5)`, event ±[-5, +10] from idx.
7. **Random control sampled from `idx ≥ 30` to `idx ≤ len-15`** with the
   same RNG seed; no overlap with auction days because filter is
   `~weakness_event`.
8. **seed=42** for all bootstraps, controls, and shuffles.

## Headline results

| metric | value | interpretation |
|---|---|---|
| Sample (auctions ≥5y) | 1,028 | meets ≥100-event bar |
| MOVE trading days | 4,053 | 16y window |
| Weak events (z ≥ 1) | 180 | event-study power adequate |
| CAR(t..t+5) weak | −0.0025 (95% CI −0.016, +0.011) | indistinguishable from 0 |
| CAR(t..t+5) random | −0.0075 (95% CI −0.021, +0.007) | similar to weak |
| Welch t (weak − random) | t=0.49, p=0.625 | **NULL** |
| OOS RMSE h=5 full | 0.0940 | |
| OOS RMSE h=5 AR(1) | 0.0938 | AR(1) marginally better |
| OOS RMSE h=5 hist-mean | 0.0939 | |
| DM (full vs AR1, h=5, HLN) | stat=+1.71, p=0.088 | full **worse** than AR(1), marginal |
| DM (full vs AR1, h=10, HLN) | stat=+2.74, p=0.006 | full **significantly worse** than AR(1) |
| IS regression β on weakness_{t−1} (h=5) | +0.00068, t=0.23 | indistinguishable from 0 |
| IS regression R² (h=5) | 0.0073 | trivial |

## Conclusion

**NULL result.** Treasury auction bid-to-cover ratio does not contain robust
incremental information for predicting ^MOVE log-changes at the 1, 5, or 10
trading-day horizon beyond what an AR(1) on MOVE itself captures. Across:

- Event study (weak − random CAR insignificant, p=0.63)
- In-sample regression (β ≈ 0, t < 0.25, R² ≈ 0.007)
- OOS rolling forecast (full model **worse** than AR(1) at h=10 with p=0.006)

the data do not support the proposition that auction-demand weakness is a
leading indicator for rates implied volatility at daily-to-2-week horizons.

The non-monotonic quintile pattern (Q1 lowest weakness → most-negative MOVE
change, Q2 and Q4 both positive) confirms there is **no monotone
weakness-to-vol gradient**, ruling out a simple linear relationship.

### Why might this be NULL?

Several plausible explanations (not tested here, candidates for follow-ups):

1. **Auction results may be efficiently priced same-day**: by close of the
   auction date, MOVE may already reflect the outcome, so a t+1 forecast
   captures only the residual surprise (which our z-score normalization
   partially proxies but does not isolate).
2. **Cross-tenor aggregation**: pooling 5y/7y/10y/20y/30y events may dilute
   tenor-specific dynamics. MOVE weights 2y/5y/10y/30y differently; a
   tenor-matched event signal could fare better.
3. **Demand vs supply mix**: BTC conflates direct + indirect + dealer
   allocations. Indirect-bidder share collapse (proxy for foreign demand
   withdrawal) is a more targeted stress signal — left for K15xx follow-up.
4. **Regime conditioning**: weakness may matter only during tightening
   cycles or when SOMA is not active QE buyer; unconditional regression
   averages over heterogeneous regimes.
5. **MOVE is itself a forward-looking measure**: predicting changes in an
   expectations-based vol index is structurally harder than predicting
   realized vol or returns.

## Limitations (honest)

- IS regression standard errors are iid-OLS, not Newey-West HAC; given
  overlapping forward returns at h=5/10, true t-stats are likely smaller in
  magnitude (i.e., even more null). Conclusion does not change.
- Bootstrap n=5,000 (not 10,000) for speed; CI widths are stable empirically.
- Auctions before 2010 excluded due to MOVE coverage; full
  Treasury-auction series goes back to the 1970s in fiscaldata.
- Same-day MOVE move from auction is intentionally discarded — this is the
  correct conservative choice for a *leading*-signal test but means an
  intraday-event study around auction close (e.g., MOVE-implied movement in
  the 2-hour window post-auction) is a separate research question.
- Quintile/event thresholds (z ≥ 1) are pre-registered conventions; we did
  not sweep thresholds to mine for significance.

## Files

| file | purpose |
|---|---|
| `k1500.py` | full pipeline (data fetch → signal → event study → OOS regression → plots) |
| `k1500_results.json` | machine-readable numerical results |
| `fig_event_study_car.png` | CAR curves for weak / strong / random events |
| `fig_scatter_weakness_vs_movefwd.png` | scatter + OLS line of weakness vs forward MOVE chg |
| `fig_quintile_bar.png` | quintile means of forward MOVE chg by weakness |
| `fig_oos_rmse.png` | OOS RMSE comparison across horizons |
| `data/auctions_raw.parquet` | cached Treasury auction pull |
| `data/move.parquet` | cached ^MOVE daily Close |
| `codex_review.md` | Codex code-review verdict |

## Reproducibility

```bash
cd <repo_root>
uv run python experiments/k1500_treasury_auction_move_vol/k1500.py
```

Deterministic: seed=42 across numpy RNG + bootstrap + random control sample.
First run downloads (~5s for FRED-style fiscaldata + ~3s for yfinance).
Cached reruns ~25s wall-clock.

## Knowledge ledger

- verdict: `CONDITIONAL_PASS` (subject to Codex review verification)
- finding: NULL result. weakness signal does not predict MOVE log-change at
  h=1, 5, or 10; full model is significantly *worse* than AR(1) at h=10.
- Mission contribution: closes a candidate signal — saves future research
  cycles from re-investigating this channel without conditioning. Documents
  a rates-vol predictor null for paper portfolio (rates-vol section can cite
  this as motivation for moving to indirect-bidder-share, tenor-matched
  signals, or regime-conditional approaches).
- Follow-up candidates:
  - K-next-a: indirect-bidder-share collapse as targeted foreign-demand
    stress signal (matched to tenor)
  - K-next-b: regime-conditional weakness signal (Fed tightening vs easing)
  - K-next-c: intraday MOVE move in 2-hour window post-auction-result release
