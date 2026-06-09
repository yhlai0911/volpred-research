# K1444 — Vol-of-vol Spillover: Oil → Equity?

**Verdict:** PRELIMINARY (mixed-signal — Granger 4/4 pass; DY spillover direction
inconsistent with hypothesis).

**Run:** 2026-06-09 / 2026-06-10 (台灣時間), worktree-agent-a02a9ef4f244d4425

---

## 1. Motivation & Differentiation

### Hypothesis
The **second-order vol** (vol-of-vol; vov) of crude oil instruments (CL=F WTI
futures, USO ETF) Granger-causes the vol-of-vol of broad equity (SPY) and
energy equity (XLE), beyond their own past.

### Why it matters (monetization angle)
- First-order oil → equity vol transmission is well documented (Maghyereh
  et al., 2016; Du & Tepper, 2014; K861 in this lab).
- A **second-order** lead would mean **uncertainty of uncertainty**: VIX/OVX
  options pricing front-runs a regime change.
- A confirmed lead-lag would feed directly into a **VIX–OVX options spread**
  strategy or a **straddle-on-equity-when-oil-vov-spikes** signal.

### Why this is not a duplicate
- **K861** — `oil drops → equity-vol level` (first-order, asymmetric;
  found t=5.82 in the existing line-of-work referenced by the task brief).
  K1444 looks at **vol of vol**, a strictly higher-order moment.
- **K1088** — multi-asset class realised-vol forecasting (cross-asset RV
  level, not vov).
- **K144** — bond futures cross-spillover, unrelated mechanism.
- **K1443** — BTC/ETH ↔ SPY spillover, different asset universe.

### Literature consulted
1. **Diebold & Yilmaz (2012)**, *Better to give than to receive: Predictive
   directional measurement of volatility spillovers*. IJF 28(1), 57–66.
   Source of the generalized-FEVD spillover index used in Stage B.
2. **Maghyereh, Awartani & Bouri (2016)**, *The directional volatility
   connectedness between crude oil and equity markets: New evidence from
   implied volatility indexes*. Energy Economics 57, 78–93.
3. **Du & Tepper (2014)**, *Cross-market dynamics in spillovers between
   crude oil and equity market volatilities*. NBER WP 19998 / Energy
   Economics 55, 1–14.
4. (Background) **Bollerslev, Tauchen & Zhou (2009)**, *Expected stock
   returns and variance risk premia*. RFS 22(11), 4463–4492. — defines
   the variance risk premium and motivates vol-of-vol as a risk factor.

None of the four explicitly tests **vol-of-vol transmission across oil ↔
equity**; existing work is on (a) implied-vol level connectedness (Maghyereh)
or (b) realized-vol connectedness (Du & Tepper). K1444 fills that gap.

---

## 2. Data

| | |
|---|---|
| Source | yfinance `download(auto_adjust=True)` daily Close |
| Tickers | `CL=F` (WTI front-month future), `USO` (ETF), `SPY`, `XLE` |
| Range | 2012-01-01 → 2026-06-09 (end exclusive) |
| Raw rows | 3 631 |
| Aligned rows (post vov) | **3 398** (2012-03-02 → 2026-06-09) |
| RV window | 21 trading days (sum-of-squared log returns, sqrt) |
| Vol-of-vol window | 21 trading days (rolling std of RV) |
| Seed | 42 (`np.random.seed(42)`) |

Vol-of-vol descriptive (selected):

| ticker | mean | std | median | max |
|---|---|---|---|---|
| CL=F | 0.0123 | 0.0145 | 0.0079 | 0.168 |
| USO  | 0.0108 | 0.0121 | 0.0075 | 0.135 |
| SPY  | 0.0028 | 0.0029 | 0.0019 | 0.026 |
| XLE  | 0.0040 | 0.0042 | 0.0028 | 0.036 |

Note magnitude difference: oil vov is ~3–4× equity vov, as expected.

ADF on **levels** (constant, AIC lag-selection):

| ticker | ADF p (level) | ADF p (Δ) | Used in primary |
|---|---|---|---|
| CL=F | 3.0e-12 | < 1e-10 | both reported |
| USO  | 3.0e-09 | < 1e-10 | both reported |
| SPY  | 5.1e-10 | < 1e-10 | both reported |
| XLE  | 1.9e-07 | < 1e-10 | both reported |

All series are stationary in levels at 5% but highly persistent. Because
levels-Granger on persistent series is easily inflated by shared trend
co-movement, **the verdict uses first-difference Granger as the primary
spec.**

---

## 3. Method

### Stage A — Granger causality (4 pairs × levels + diff)
- Bivariate Granger via `statsmodels.tsa.stattools.grangercausalitytests`
  (`ssr_ftest`), max lag = 21 (best lag picked from grid {1, 2, 5, 10, 21}
  by minimum p, all lags 1..21 evaluated internally).
- Pairs: `CL=F→SPY`, `CL=F→XLE`, `USO→SPY`, `USO→XLE`.
- Bonferroni α = 0.05 / 4 = **0.0125** per spec.
- Reports **both** levels and first-differences; verdict uses diff.

### Stage B — Diebold-Yilmaz (2012) spillover index
- 4-variable VAR(2) on first-differenced vov (since levels are persistent).
- Generalized FEVD (Pesaran-Shin 1998 / DY 2012), forecast horizon h=10.
- Row-normalized θ̃, total spillover index, net (to-others − from-others)
  per variable.
- Rolling: 250-day window, 5-day step.

### Stage C — Asymmetry
- For each (source → target) pair, split sample by lagged sign of
  `Δsource_vov` (rising vs falling).
- OLS `target_t = a + b · source_{t-1} + c · target_{t-1}` per regime,
  HC0 robust SE.
- Reports β on source between regimes.

### Honesty controls
- **Lookahead**: VAR / Granger use only lagged regressors by construction.
  Stage C uses explicit `signal.shift(1)`. No code path uses contemporaneous
  source as predictor.
- **Seed**: `np.random.seed(42)` set at module load.
- **Multiple testing**: Bonferroni m=4 within each spec.
- **Persistence guard**: primary spec is first-difference; levels reported
  only for robustness.

---

## 4. Results

### Stage A — Granger (both specs pass Bonferroni, all 4 pairs)

| pair | levels min-p | levels lag | diff min-p | diff lag | Bonf (diff) |
|---|---|---|---|---|---|
| CL=F → SPY | 7.2e-65 | 2 | 2.5e-57 | 1 | **PASS** |
| CL=F → XLE | 4.8e-60 | 2 | 5.0e-55 | 1 | **PASS** |
| USO → SPY  | 1.9e-42 | 10 | 1.7e-42 | 9 | **PASS** |
| USO → XLE  | 1.1e-08 | 14 | 1.8e-10 | 21 | **PASS** |

Bonferroni α = 0.0125. All four pass under both specifications. CL=F → equity
peaks at the shortest lag (1–2 days); USO → equity is meaningfully slower
(9–21 days), consistent with USO being a contango-eroded ETF wrapper that
lags the underlying futures.

### Stage B — Diebold-Yilmaz spillover (VAR(2), h=10, diff-vov, n=3 397)

| variable | from-others (%) | to-others (%) | **net (%)** |
|---|---|---|---|
| CL=F | 56.8 | 0.7 | **−56.1** |
| USO  | 46.5 | 86.9 | **+40.3** |
| SPY  | 53.6 | 48.2 | **−5.5** |
| XLE  | 38.2 | 59.4 | **+21.2** |
| **Total spillover** | | | **48.84%** |

**Direction does NOT match the hypothesis.** USO is the dominant net
transmitter of vol-of-vol; CL=F is the dominant net receiver. This is the
opposite of what a clean "oil futures → equity vov" story would predict and
forces the verdict down to PRELIMINARY despite a clean Granger sweep.

Rolling spillover (250-day, 5-day step, n=630 windows): mean total
spillover ≈ 50% (sample-wide), peaking during the 2014 oil collapse,
2020 COVID, and 2022 Russia-Ukraine episodes.

### Stage C — Asymmetry (HC0 SE)

| pair | rising β (source) | falling β (source) | comment |
|---|---|---|---|
| CL=F → SPY | (see results.json) | (see results.json) | sign symmetry vs K861's asymmetric oil-drop result |
| CL=F → XLE | | | |
| USO → SPY  | | | |
| USO → XLE  | | | |

Full numerical table in `k1444_results.json::stage_c_asymmetry`. The point
estimates suggest mild asymmetry, but the magnitudes are not large enough
to override the headline Stage B finding.

---

## 5. Honest Conclusion

- **Granger Stage A**: 4/4 pairs significant at Bonferroni 0.0125 under
  both levels and first-difference specs. There is a robust **statistical
  lead-lag** from oil vov to equity vov.
- **Diebold-Yilmaz Stage B**: but the **directional spillover index goes
  the wrong way**. USO is a net **transmitter** (+40%) and CL=F is a net
  **receiver** (−56%) of vol-of-vol forecast variance.
- **Verdict = PRELIMINARY**. The Granger lead is real but the DY direction
  contradicts the hypothesized oil → equity channel. The two metrics
  measure different things — Granger tests improvement in conditional mean
  predictability, DY tests forecast-error variance share — and a variable
  can plausibly lead another's mean while being a net receiver of variance
  shocks. But until we can reconcile the two, **no monetization signal
  should be deployed**.
- **NULL on the trading hypothesis** as currently framed: the cleanest
  reading is that the oil ↔ equity vov system is **bidirectionally
  connected at high intensity** (~49% total spillover) rather than
  unidirectionally led by oil. A VIX–OVX options spread strategy keyed on
  "OVX vov leads → buy VIX gamma" is **not supported**.

### Caveats
1. **CL=F roll effect not modelled.** yfinance `auto_adjust=True` does not
   roll futures contracts; the 21-day rolling RV may absorb roll-induced
   spikes and inflate CL=F vov noise — this could mechanically push CL=F
   into the "net receiver" bucket in DY. Robustness via a continuous
   front-month contract or a USO-only spec is the obvious next step.
2. **Daily frequency**: vov transmission may operate at intraday frequency
   (options gamma trades) and be invisible in daily close-to-close data.
3. **Codex review timed out** (background process returned empty after 5
   min). Self-audit performed against `.claude/rules/experiments.md`
   checklist; lookahead, seed, Bonferroni, symmetric lag grid, persistent-
   series guard all confirmed. Main thread should re-verify before any
   knowledge.json entry.
4. **Single regime**: 2012–2026 spans both the 2014–2020 low-vol era and
   the 2020–2022 high-vol era; structural breaks not formally tested.

---

## 6. Reproducibility

```bash
cd <repo-root>
uv run python experiments/k1444/k1444.py
# produces k1444_results.json + 3 PNGs
```

Outputs in this directory:
- `k1444.py` — main script (single-file, ~430 LOC)
- `k1444_results.json` — full numerical record
- `fig_a_volvol_levels.png` — vov time series (oil panel + equity panel)
- `fig_b_spillover.png` — DY rolling 250d total spillover
- `fig_c_asymmetry.png` — Stage C β by regime, all 4 pairs

Runtime: ~12 s on M-series Mac.

---

## 7. Next steps (for main thread / future K)

- **K-followup-1**: Re-run Stage B on a continuous front-month CL=F series
  built from CME settlement files (eliminate yfinance roll artefact).
- **K-followup-2**: Intraday vol-of-vol (5-min or 15-min realized) — the
  daily-close window may be too coarse for the actual transmission timescale.
- **K-followup-3**: Add VIX and OVX implied-vol vov as a 6-variable system;
  if implied-vov leads realized-vov in oil, the trade may live in **VIX/OVX
  options surface dynamics**, not in CL=F/SPY futures.
- **Knowledge.json verdict**: defer to main thread; suggested entry is
  `verdict=PRELIMINARY` with reviewer-source caveat (Codex empty, self-audit
  only).
