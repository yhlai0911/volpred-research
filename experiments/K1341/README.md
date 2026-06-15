# K1341: Index Reconstitution Day Volatility Event Study

**Status:** In progress
**Verdict:** TBD
**Run date:** 2026-06-15

## Motivation

Annual Russell 1000/2000 reconstitution and quarterly S&P 500 index rebalances
concentrate enormous closing-auction order flow into a single trading session.
BMLL Technologies' 2025 closing-auction report documents that closing-auction
share of daily volume rises from a typical ~9% baseline to ~20% on Russell
reconstitution Friday (the last Friday of June). The mechanical re-weighting
order flow is large and (largely) one-directional within minutes.

K1341 asks two empirical questions:

1. **Intraday dislocation**: Do reconstitution days exhibit elevated
   intraday-range realized volatility (Parkinson estimator from daily H/L)
   versus a same-month baseline?
2. **Mean reversion**: If yes, does close-to-close return-squared on day t+1
   revert to the pre-event baseline (i.e., the shock is transient, not
   persistent)?

If both hold, this is a tradable "dislocate-then-revert" pattern at a known
calendar date — exactly the kind of structural anomaly that motivates the
VolPred platform's calendar-event vol modeling.

## Literature / Source motivation

- BMLL Technologies, "Closing Auctions: A 2025 Update", 2025
  (Russell reconstitution closing-auction share 9% -> 20%).
- Traders Magazine coverage of BMLL 2025 closing-auction trends.
- Madhavan & Ming (2003), "The Hidden Costs of Index Rebalancing", JoF —
  classic study of index-recon price impact (intraday).
- Chen, Noronha, Singal (2004), "The Price Response to S&P 500 Index Additions
  and Deletions: Evidence of Asymmetry and a New Explanation", JoF.
- Cai (2007), "What's in the News? Information Content of S&P 500
  Additions", FAJ.

## Differentiation from prior K

Prior K283 (archived as "Rebalance Day = pure noise") tested **portfolio
rebalance** day effects on a generic strategy — a different mechanism. K1341
targets **index reconstitution events** (Russell annual June, S&P quarterly
March/June/September/December third Friday) — externally imposed mandatory
trading by passive funds, not discretionary portfolio choice. The mechanism,
universe, and event dates are distinct.

## Data

- Source: yfinance daily OHLCV.
- Universe:
  - IWM (Russell 2000 ETF) — most exposed to annual reconstitution.
  - IWB (Russell 1000 ETF) — same annual recon Friday.
  - SPY (S&P 500 ETF) — quarterly recon (third Friday Mar/Jun/Sep/Dec).
  - QQQ (Nasdaq-100 ETF) — control; rebalances quarterly but on a
    different schedule and with smaller passive footprint.
- Period: 2014-01-01 to 2026-06-14.

## Event dates

- **Russell reconstitution day**: last Friday of June, 2014-2025 (12 events).
  Hard-coded per FTSE Russell published schedule.
- **S&P 500 quarterly rebalance**: third Friday of March / June / September /
  December, 2014Q1-2026Q1 (~49 events). Note Russell reconstitution Friday
  often coincides with S&P June rebalance; we keep them distinct per ticker.

## Method

For each ticker × event-date set:

1. Compute three volatility measures on the full daily series:
   - `r2_cc = (ln(C_t / C_{t-1}))^2` — close-to-close return squared.
   - `parkinson = 0.361 * (ln(H_t / L_t))^2` — Parkinson intraday-range
     estimator (the "dislocation" proxy).
   - `r2_co = (ln(C_t / O_t))^2` — close-to-open squared (overnight gap;
     reported but secondary).
2. For each event date t_e, extract window [t_e - 5, t_e + 5] of each measure.
3. Baseline = mean of measure over the SAME calendar month, excluding the
   event window itself. This controls for monthly seasonality.
4. **Tests**:
   - Wilcoxon signed-rank (paired): event-day measure vs baseline mean over
     all events (n = 12 Russell / 49 S&P).
   - Block bootstrap p-value (block size = 5, B = 1000, seed = 42) on the
     paired difference — robust to autocorrelation.
5. **Mean reversion check**: z-score of t+1 measure against the
   (pre-event-window) baseline. |z| < 1 = reverted; |z| > 2 = persistent
   shock.

## Lookahead policy

- This is an event study aligned to known calendar events. The event date is
  publicly known weeks in advance. There is no traditional signal-shift
  required for tradability, BUT:
- **Strict rule**: when computing the baseline mean for event t_e, we exclude
  all dates in [t_e - 5, t_e + 5] from the same-month sample so the baseline
  doesn't absorb the event itself.
- Event-window measures are computed only from data on or before each day
  inside the window (no forward smoothing). All measures use only H, L, C, O
  on the same day t — no rolling estimator that peeks ahead.
- Bootstrap resampling uses `np.random.default_rng(seed=42)`.

## Success criteria

- Results JSON contains at least 3 tickers × 3 vol measures × 4 metrics
  (event_mean, baseline_mean, p_value, t+1_z_score, n_events) — already
  written by the script.
- At least 1 figure showing event-window mean profile.
- Codex review verdict: CONDITIONAL_PASS or better.

## Outputs

- `K1341.py` — runnable, seed = 42, lookahead notes inline.
- `K1341_results.json` — per ticker × measure × metric.
- `figures/event_window_parkinson.png`
- `figures/event_window_r2cc.png`
