# K1607: Mega-Cap Options-Market Crowding Gauge for the AI-Capex Bull Case

**Task type**: `trending_repost`
**Verdict**: Descriptive cross-sectional snapshot — no forecast, no hypothesis test, no OOS claim (by design)
**Reviewer**: Codex CLI — CONDITIONAL_PASS on v1 (2 CRITICAL: no delta-selection quality check, no
liquidity filter) → fixes applied (OTM-constrained + liquidity-filtered 25-delta selection,
`delta_error`/`quality_flag` reporting) → Codex re-confirmation requested on v2 (see `codex_review.md`)
**Date**: 2026-07-03

## Motivation

Q1/Q2 2026 hyperscaler earnings pushed combined AI-capex guidance toward
$650-700B for 2026 (Meta raised FY26 capex guidance to $125-145B; Microsoft
Q3 FY capex +84% YoY; Amazon ~$44.2B/quarter; Alphabet Q1 capex $35.67B, more
than doubling YoY — public press aggregating primary 10-Q/8-K disclosures,
see References). The financial press debate is almost entirely about whether
this capex will pay off in revenue. That debate is not something this repo
can settle with one afternoon's data pull.

What we *can* independently compute and verify: **is the options market on
these same names currently pricing extra crash protection, and how does that
compare across the group?** This is the VolPred angle — quantifying crowding
in downside protection via the options market, not repeating the capex
payoff debate.

## Differentiation vs Existing K

- Repo has no prior single-name equity options-skew cross-section experiment.
  `grep -ri "skew\|crowd\|capex\|25.delta" storage/memory/knowledge.json`
  (June–July 2026 window) returns no matching K — this is a new axis, not a
  variable-swap of an existing arc.
- Distinct from the repo's dominant VIX/VT/GARCH clusters: no volatility
  *forecasting* model is fit here; this is a single-date cross-sectional
  *positioning* read, closer to a market-microstructure snapshot than a
  time-series experiment.

## Data

- **Source**: yfinance, live pull, run at `2026-07-02T22:18:02Z` (embedded in
  `k1607_results.json.run_at`; single snapshot, not a repeatable historical
  series — re-running the script on a different date will give different
  numbers because options prices move, not because of any randomness).
- **Universe**: MAG7 — AAPL, MSFT, NVDA, GOOGL, AMZN, META, TSLA.
- **n_succeeded = 7/7** (no tickers dropped; failures list is empty).
- **Options chain**: single expiry per ticker, chosen closest to 35 calendar
  days-to-expiry within an 18-65 day window (all 7 landed on **2026-08-07,
  DTE=36** — same expiry across the board, so the cross-sectional comparison
  is horizon-matched by construction).
- **Risk-free proxy**: `^IRX` (13-week T-bill discount yield) = 3.67% at run
  time, used only for Black-Scholes delta computation (not material to which
  contract gets picked — delta selection is far more sensitive to the smile
  itself than to a few bps of `r`).

## Method

1. **25-delta put-call IV skew** = IV(25-delta put) − IV(25-delta call), in
   vol points. Delta computed via Black-Scholes (`q=0` dividend-yield
   simplification, disclosed as a limitation) since yfinance does not return
   delta. **Codex-review fix**: contract selection is now (a) restricted to
   the OTM side (calls: strike ≥ spot; puts: strike ≤ spot) and (b)
   restricted to quotes with `bid>0 or ask>0` when available, with
   `delta_error = |realized_delta − 0.25|` reported per contract and a
   `quality_flag` at `delta_error > 0.07`. **All 14 selected contracts
   (7 tickers × 2 sides) came in at `delta_error < 0.025`, zero
   `quality_flag` hits** — the MAG7 chains are dense/liquid enough that this
   is not a data-quality caveat in practice, but the check is now load-bearing
   code, not an assumption.
2. **ATM IV − RV21 gap** (vol risk premium proxy): ATM IV = mean of the
   call/put IV at the strike nearest spot on the same expiry chain; RV21 =
   annualized (×√252) stdev of the trailing 21 daily log returns strictly at
   or before the run date. This is a same-timestamp descriptive comparison —
   **no forecasting model is fit and no train/test split exists**, so the
   repo's lookahead rule (experiments.md) does not apply in the usual
   forward-label sense; RV21 by construction only uses already-realized
   closes.
3. **Put/Call volume ratio** (and open-interest ratio as a robustness check)
   on the same expiry chain.
4. **Cross-sectional composite**: mean of the per-metric z-scores (skew,
   IV-RV gap, P/C volume ratio) across the 7 names — **explicitly labeled
   `composite_crowding_score`** (Codex-review rename from
   `composite_crowding_z`, since a mean-of-z-scores is not itself a formal
   z-score) — plus raw cross-sectional correlations. **n=7 → these
   correlations and the ranking are reported as descriptive statistics only;
   no significance or causal claim is made** (`cross_section.inference_note`
   states this explicitly in the results JSON).

## Anti-Error Compliance

- **Lookahead**: not applicable in the forward-label sense (no forecasting
  model, no OOS split) — RV21 uses only trailing, already-realized closes;
  IV is read directly from the live chain at run time. Documented in
  `k1607_results.json.methodology.lookahead_note`.
- **Seed**: no stochastic step exists (every number is a direct closed-form
  BS/RV/ratio calculation on live market data); reproducibility is of
  *method*, not of *value* (values will differ on a re-run because the
  market moved, not due to unseeded randomness) — disclosed explicitly in the
  script docstring.
- **Small-sample honesty**: n=7 cross-section; correlations (`corr_skew_vs_
  pc_ratio=0.618`, `corr_skew_vs_iv_rv_gap=-0.244`) and the composite ranking
  are descriptive only, stated as such in the results JSON and in the
  article draft — not treated as hypothesis-test evidence.
- **No capex-figure fabrication**: capex guidance figures ($650-700B
  combined, per-company numbers) are **not computed by this script** — they
  are cited from named secondary press (Yahoo Finance, heygotrade)
  aggregating primary 10-Q/8-K disclosures, and are disclosed as such
  (`k1607_results.json.capex_context_note_NOT_computed_by_script`). The
  script-computed, independently-reproducible numbers are the options-panel
  only.

## Results (run 2026-07-02, single snapshot; expiry 2026-08-07, DTE=36 for all 7)

| Ticker | Spot | 25Δ Skew (put−call, vol pts) | ATM IV % | RV21 % | IV−RV Gap (vol pts) | P/C Vol Ratio | P/C OI Ratio |
|---|---|---|---|---|---|---|---|
| NVDA | 194.83 | **+2.49** | 39.81 | 41.48 | −1.67 | **2.93** | 0.88 |
| AAPL | 308.63 | +1.35 | 29.51 | 38.08 | −8.57 | 0.18 | 0.99 |
| GOOGL | 359.91 | −0.52 | 39.78 | 34.29 | +5.49 | 0.55 | 0.64 |
| TSLA | 393.45 | −0.60 | 45.86 | 60.995 | **−15.14** | 0.21 | 0.35 |
| AMZN | 242.67 | −1.64 | 42.71 | 37.26 | +5.45 | 0.40 | 0.34 |
| META | 582.90 | −2.12 | 46.07 | 53.94 | −7.87 | 0.67 | 0.53 |
| MSFT | 390.49 | −3.12 | 42.09 | 38.93 | +3.17 | 0.36 | 0.48 |

Cross-section (n=7, descriptive only): mean skew = −0.593 vol pts (std 1.961);
mean IV-RV gap = −2.735 vol pts; corr(skew, P/C volume ratio) = **+0.618**;
corr(skew, IV-RV gap) = −0.244.

**Composite crowding ranking** (mean z-score of skew + IV-RV gap + P/C ratio,
descriptive, n=7): **NVDA (+1.31) > GOOGL (+0.28) > AMZN (+0.04) > AAPL
(−0.11) > MSFT (−0.32) > META (−0.50) > TSLA (−0.70)**.

## Honest Reading

1. **The four heaviest 2026 AI-capex spenders (MSFT/GOOGL/AMZN/META) do NOT
   show the highest downside-protection crowding.** NVDA — the chip
   *supplier*, not a capex spender in this narrative — has both the highest
   25-delta skew (+2.49 vol pts, only single-name here with a genuine
   equity-index-style put-skew) and by far the highest P/C volume ratio
   (2.93, put volume ~2.9× call volume on the same chain), driving the top
   composite-crowding rank. If the "AI capex bust" fear were being hedged
   uniformly across the spenders, we would expect MSFT/GOOGL/AMZN/META to
   cluster at the top — they do not; GOOGL and AMZN sit mid-pack, MSFT and
   META sit near the bottom.
2. **Single-name skew is much flatter (and 4/7 names inverted) versus the
   textbook equity-index smirk.** Only NVDA and AAPL show a positive
   (put-rich) 25-delta skew; MSFT, GOOGL, AMZN, META, TSLA all print a
   *negative* skew (call IV priced above put IV at the same delta) — a
   reminder that single-name mega-cap skew does not automatically inherit
   the index-level "crash insurance is expensive" shape; earnings-driven
   upside convexity can flip the sign.
3. **The IV-RV gap is not uniformly rich or cheap** — GOOGL and AMZN print a
   positive gap (options priced above trailing realized vol, the textbook
   vol-risk-premium sign), while AAPL, META and especially TSLA (−15.14 vol
   pts) show ATM IV running *below* trailing RV21, i.e. the market is not
   fully re-pricing forward risk up to the level of what just realized
   (consistent with sharp post-earnings realized-vol spikes — e.g. Meta's
   ~6% single-day drop after raising 2026 capex guidance — that options
   pricing has not fully chased).
4. **This is a single-date snapshot, not a trend claim.** No time-series
   history of this metric exists yet in the repo; a follow-up K should track
   this panel across the next several weeks/earnings cycles before any
   claim about a *trend* in crowding can be made.

## Files

- `k1607.py` — reproducible script (options-chain pull, BS delta, 25-delta
  contract selection with OTM+liquidity filter and quality flagging, RV21,
  cross-sectional composite, 2 chart outputs)
- `k1607_results.json` — full per-ticker panel + cross-section stats +
  provenance (`run_at`, data source, methodology, capex-context disclosure)
- `figures/k1607_skew_and_gap.png` — dual bar chart: 25-delta skew and
  IV-RV gap per ticker
- `figures/k1607_skew_vs_pcratio.png` — scatter: skew vs P/C volume ratio
  (illustrates the `+0.618` cross-sectional correlation)
- `codex_review.md` — Codex code review (v1 CONDITIONAL_PASS + fixes applied
  + v2 re-confirmation)

## References

- Meta FY2026 capex guidance raised to $125-145B; Microsoft Q3 FY capex +84%
  YoY (~$30.9B in-quarter); Amazon ~$44.2B quarterly capex; Alphabet Q1 capex
  $35.67B (>2x YoY); combined hyperscaler 2026 capex tracking $650-700B —
  aggregated from company Q1/Q2 2026 earnings disclosures via Yahoo Finance
  ("Big Tech AI Capex Tops $650 Billion as Q1 Earnings Beats Pressure Bitcoin
  Risk Trade") and heygotrade ("Big Tech Q1 2026 Earnings Power $700B AI
  Capex Spree"). Cited as narrative context only — not computed by this
  script.
- Standard 25-delta risk-reversal / skew construction: CBOE / OCC options
  literature; Black-Scholes delta formula (Black & Scholes 1973; Merton
  1973).
