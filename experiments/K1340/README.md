# K1340: Gamma-Squeeze Candidate Retail-Pressure Event Study

**Status:** Completed
**Verdict:** NULL_INVERSE_VOL_COMPRESSION
**Run date:** 2026-06-15

## Motivation

K1340 tests whether high-volume, high-return shocks in meme/gamma candidate
stocks predict elevated subsequent realized volatility and asymmetric follow-on
returns. The target is intentionally narrow: with free daily yfinance data, can a
transparent retail-pressure proxy recover any event-study footprint similar to
the gamma-squeeze literature?

## Literature

- Binsbergen, Bryzgalova, Mukhopadhyay, Sharma, "Seeking Gamma: Lessons from
  the Meme Frenzy", AFA/SSRN 2025-2026:
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5959235
- SEC Staff Report, "Equity and Options Market Structure Conditions in Early
  2021", 2021:
  https://www.sec.gov/files/staff-report-equity-options-market-struction-conditions-early-2021.pdf
- "Squeezing Shorts Through Social Media Platforms", Management Science, 2026:
  https://pubsonline.informs.org/doi/10.1287/mnsc.2023.02887
- Brogaard, Han, Won and related 0DTE volatility literature, summarized in:
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4426358
- Cboe research note on gamma-squeeze and 0DTE volatility impact:
  https://cdn.cboe.com/resources/education/research_publications/gammasqueezes.pdf

## Differentiation From Prior K

Prior VolPred work has documented a 2021-2026 structural decline in individual
stock GJR gamma and linked it to possible retail/0DTE/meme effects. K1340 is a
different unit of analysis: discrete daily events in known retail/gamma
candidates, not a cross-sectional GARCH parameter study.

## Data

- Source: yfinance daily adjusted close and volume.
- Period requested: 2024-01-01 to 2026-06-14.
- Candidate tickers: GME, AMC, KOSS, BB, OPEN, KSS, BYND, GPRO, DNUT, HOOD,
  CHWY, LCID, RIVN, PLTR, SOFI.
- Market control: SPY.

These are public-price proxies. The experiment does not observe option open
interest, customer buy/sell direction, market-maker inventory, or true dealer
gamma exposure.

## Method

For each stock, compute daily log return and a prior-only 60-day volume z-score:

```python
volume_z_t = (volume_t - mean(volume_{t-60:t-1})) / std(volume_{t-60:t-1})
pressure_t = return_t * volume_z_t
```

Positive retail/gamma-pressure shocks require:

- `volume_z >= 2.0`
- `return >= +5%`
- `pressure >= 0.12`

Negative pressure shocks use the symmetric negative-return rule. Events are
cooldown-filtered to at most one event per symbol per 21 trading days.

For each event and horizon H in {5, 10, 21}, the experiment measures:

- Forward CAR from the tradable event day.
- SPY-excess forward CAR.
- Forward realized-volatility jump versus the prior H-day window.
- Reversal rate: positive events reverse if forward CAR < 0; negative events
  reverse if forward CAR > 0.

Matched controls are same-symbol, same-year non-event days when available,
excluding dates too close to selected events.

## Lookahead Policy

The raw shock on day t is only known after that close. The tradable event signal
is therefore explicitly lagged:

```python
positive_event_signal = positive_raw_event.shift(1)
negative_event_signal = negative_raw_event.shift(1)
```

Forward windows begin on the next trading day. No same-day pressure signal is
used to explain same-day returns.

## Statistical Tests

The primary family has 12 tests:

- 2 event types: positive and negative pressure.
- 3 horizons: 5, 10, 21 days.
- 2 primary metrics: matched CAR difference and matched RV-jump difference.

Each event-level matched difference is tested with a deterministic sign-flip
bootstrap (`B=5000`, seed 42). The README and results report raw p-values and
Bonferroni correction at family alpha 0.10.

## Success Criteria

The experiment earns `PASS` only if the ex-ante primary test, positive-pressure
H=21 matched CAR, is positive and survives the 12-test Bonferroni threshold.

It earns `CONDITIONAL_PASS` if another family-adjusted cell survives but the
primary test does not.

It is `WEAK_UNADJUSTED_SIGNAL` if only raw p<0.10 cells exist, and `NULL` if no
raw p<0.10 cells exist.

## Reproduce

```bash
uv run python experiments/K1340/K1340.py
```

Primary artifacts:

- `K1340_results.json`
- `K1340_event_counts.png`
- `K1340_matched_effects.png`

## Failure Modes

- Proxy validity: daily price-volume pressure is not true gamma exposure.
- Sample length: 2024-2026 may produce few events after cooldown filtering.
- Event dependence: same market-wide retail episodes can hit several tickers
  close together; overlap diagnostics are reported.
- Multiple testing: only Bonferroni-adjusted results should be treated as
  confirmatory.

## Results

The run downloaded all 15 requested candidate tickers plus SPY. Effective sample
is 2024-01-02 to 2026-06-12, with 614 daily rows per ticker. The filter produced
172 cooldown-filtered events:

- 103 positive-pressure events.
- 69 negative-pressure events.

Primary test:

- Positive-pressure H=21 matched CAR difference: +1.88% on a date-clustered
  basis, p=0.5322, 85 event-date clusters and 103 events.

Supportive tests:

- 0/12 tests have direction-supportive raw p<0.10.
- 0/12 tests have direction-supportive Bonferroni significance.

Inverse results:

- Positive-pressure H=5 matched RV-jump difference: -0.3413, p=0.0000.
- Negative-pressure H=5 matched RV-jump difference: -0.4868, p=0.0000.
- Negative-pressure H=10 matched RV-jump difference: -0.2254, p=0.0026.

These three inverse RV-compression cells survive the 12-test Bonferroni threshold
but run against the stated elevated-volatility hypothesis.

## Conclusion

K1340 does not replicate a free-data version of "squeeze then one-month
continuation" in 2024-2026 meme/gamma candidates. Once the signal is made
tradable by shifting it one day, positive pressure does not predict significant
H=21 CAR, and there is no supportive evidence of elevated forward realized
volatility. The robust pattern is the opposite at short horizons: after the
large shock day is excluded, forward 5-10 day realized volatility is lower than
matched non-event windows. Treat this as evidence that daily price-volume data
captures the shock after it has happened, not a usable gamma-squeeze early
warning signal.
