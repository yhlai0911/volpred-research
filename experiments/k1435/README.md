# K1435: GLD-DXY DCC-GARCH FOMC Event Study (2010-2026)

## Hypothesis

FOMC announcement days (≈8 scheduled per year) exhibit **elevated dynamic
correlation** between GLD (gold ETF) and UUP (USD index ETF) returns compared
to non-FOMC trading days. Mechanism: monetary policy surprises jointly shock
both real-rate (gold) and FX (USD) channels, inducing temporary co-movement
spike beyond the steady-state DCC level.

## Data

- Source: `yfinance` Adj Close, auto_adjust=True
- Tickers: **GLD** (SPDR Gold), **UUP** (Invesco DB USD Bullish, DXY proxy)
- Period: 2010-01-05 → 2026-06-08
- N obs (returns): **4,131 trading days**
- Returns: log close-to-close × 100 (pct scale for GARCH stability)
- FOMC dates: 131 official FOMC announcement days from Federal Reserve
  calendar 2010-2026 (hard-coded; includes 2020 emergency cuts 03-03, 03-15);
  131 of these matched trading days in sample.

## Method

1. Univariate **GARCH(1,1) normal** on each return series via `arch.arch_model`
   → conditional volatility σ_t, standardized residuals z_t.
2. **DCC(1,1)** on bivariate z via custom MLE (`scipy.optimize.minimize`,
   L-BFGS-B, 8-start with `seed=42`), recovering dynamic correlation ρ_t.
3. **Two-sample Welch t-test**: ρ_t on FOMC days vs other days.
4. **Event window [-2, +2]** robustness test.
5. **Hedge effectiveness**: HE = 1 − Var(GLD − h·UUP) / Var(GLD).
   - DCC dynamic: h_t = ρ_t · σ_GLD_t / σ_UUP_t (signal.shift(1) for OOS realism)
   - Naive: constant OLS β from in-sample (2010-01 → 2019-12)
   - In-sample window: 2010-01 → 2019-12; OOS: 2020-01 → 2026-06.

## Lookahead protection

- FOMC dates are public calendar — no leakage.
- DCC ρ_t at time t uses Q_t (built from t−1 info per standard DCC convention),
  so ρ_t / σ_t indexed at t hedge r_t directly with no extra lag (Codex review
  2026-06-09 fixed earlier over-shift artifact).
- Log returns are strictly close-to-close (no intraday peeking).
- All random init / multistart seeded with `seed=42`.

## Interpretation caveat: ex-ante conditional, not announcement reaction

The DCC ρ_t at FOMC day t is the **pre-announcement conditional correlation**
formed from information up to t−1. This test asks: "Does the ex-ante
conditional correlation differ on days that *will* host an FOMC
announcement?" — *not* "Does the FOMC announcement itself induce a realized
correlation jump?". A genuine announcement-impact study would use
intraday windows around the 2:00 PM ET release, or realized covariance
computed from intraday returns spanning the announcement. The ex-ante
NULL here is consistent with the forward-guidance era pre-pricing
hypothesis but does not rule out short-horizon announcement-window
effects on realized comovement.

## Key Results

### GARCH(1,1) marginal

| Series | α     | β     | Persist |
|--------|-------|-------|---------|
| GLD    | 0.071 | 0.908 | 0.979   |
| UUP    | 0.049 | 0.943 | 0.992   |

### DCC(1,1)

- a = 0.0514, b = 0.9202, persistence = 0.972
- log-likelihood = 505.44
- Mean ρ_t = **−0.433** (consistent with well-known gold/USD inverse relation)
- Range: see results JSON

### FOMC test (primary)

| Metric                 | Value     |
|------------------------|-----------|
| n FOMC days (matched)  | 131       |
| n other days           | 4,000     |
| ρ_FOMC mean            | −0.4201   |
| ρ_other mean           | −0.4338   |
| diff (FOMC − other)    | +0.0137   |
| Welch t-stat           | 0.954     |
| **p-value**            | **0.341** |

### Event window [−2, +2]

- p = 0.659 (no effect at wider window)

### Hedge effectiveness (OOS 2020-2026)

| Hedge        | HE (OOS) |
|--------------|----------|
| Naive const  | 0.170    |
| DCC dynamic  | 0.200    |
| Δ (DCC−naive)| +0.030   |

## Verdict: **NULL**

No statistical evidence that FOMC announcement days alter the GLD-UUP dynamic
correlation. Mean difference is in the hypothesized direction (FOMC ρ slightly
less negative ⇒ weaker inverse co-movement on FOMC days, opposite of "spike"
intuition; if anything FOMC days are mildly less inversely correlated) but
nowhere near significance (p = 0.34 primary; p = 0.66 ±2 window).

### Interpretation

- Steady-state inverse relationship (ρ̄ ≈ −0.43) dominates. FOMC days do not
  meaningfully perturb this conditional correlation in either direction.
- DCC dynamic hedging still outperforms naive constant hedge OOS (+3.0 pp HE),
  but the gain is driven by time-varying volatility scaling, not by FOMC-day
  regime shifts.
- Result is consistent with literature finding most FOMC information is
  pre-priced via fed-funds futures by announcement date (post-2010 forward
  guidance era).

### Diff vs related K

- **K903** (gold inventory vol): univariate gold vol — orthogonal target.
- **K1437** (USD/TWD-TWII VAR-GARCH): different asset pair, different method
  (VAR-GARCH vs DCC), different event channel — orthogonal.
- **No prior K** covers cross-asset DCC × FOMC × gold/USD pair.

## Files

- `k1435.py` — full reproducible script (seed = 42)
- `k1435_results.json` — all numbers
- `figures/rho_fomc_timeseries.png` — DCC ρ_t with FOMC days marked
- `figures/hedge_effectiveness.png` — DCC vs naive HE bars

## Reproduce

```bash
cd <repo>
uv run python experiments/k1435/k1435.py
```

Expected runtime: ~30s (GARCH ~1s × 2 + DCC MLE ~10s with 8 multistart).

## Reviewer status

- **Codex CLI (gpt-5.4) CONDITIONAL_PASS** — 2026-06-09. Verdict NULL upheld.
  Fixes applied:
  1. Removed `h_dyn.shift(1)` over-lag at line 306 (rho/sigma at t already
     t-conditional from t−1 info).
  2. Clarified ex-ante vs announcement-reaction in README interpretation.
  Follow-up (not blocking NULL verdict):
  - t-distribution marginal GARCH robustness (run as K1435a if pursued).
