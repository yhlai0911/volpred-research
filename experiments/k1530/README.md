# K1530 — Thematic ETF Coherence Decay as Crash Precursor

**Verdict: FAIL** (hypothesis rejected; 0/7 themes pass; 2 themes show
*opposite-sign* effects at |t|>3).

## Motivation

Thematic ETFs (AI / robotics / clean energy / cybersecurity / aerospace /
uranium / innovation) are sold as exposure to a single narrative. If the
narrative is "real," holdings should co-move strongly via a single common
factor. **If component coherence (PC1 share of variance) collapses**, the
fund is no longer carried by one story — leadership is fragmenting, narrative
is rotating, dispersion is rising. Conventional wisdom (e.g. Pollet & Wilson
2010; Christoffersen et al. 2012) treats *higher* average correlation as a
crash signal at the market level. We test the **theme-level corollary in the
opposite direction**: does **coherence decay** (a drop in PC1 share) predict
forward stress in the *theme* ETF itself?

## Differentiation vs prior K-work

- **K151 / K164 (sectoral vol-dispersion)** — measures dispersion *across*
  sector ETFs, not coherence *within* a theme.
- **K425 / K534 / Network Topology Pilot** — cross-asset correlation
  dynamics, not theme-internal component coherence.
- **K1418 (concentration vs dispersion 2026)** — market-cap concentration
  HHI, not common-factor share.
- **K1423 (time-varying Hurst)** — persistence at single-asset level.

K1530's contribution: shifts the lens from market-wide co-movement to
**fund-internal common-factor share** as a forward-looking thematic-stress
signal.

## Data

- **Themes (7)**: AIQ, BOTZ, ARKK, ICLN, CIBR, ITA, URA
- **Components**: top 8-10 holdings per theme (public factsheet, hardcoded)
- **Sample**: 2018-01-01 → 2026-06-17, daily adj close from yfinance
- **Baseline**: SPY (same window)
- **Sample sizes per theme** (post-cleaning):

| Theme | n components | n dates (coherence valid) | n decay events |
|-------|-------------:|--------------------------:|---------------:|
| AIQ   | 10           | 1,940 | 9  |
| BOTZ  | 8            | 2,033 | 13 |
| ARKK  | 10           | 1,641 | 8  |
| ICLN  | 10           | 2,033 | 19 |
| CIBR  | 10           | 2,033 | 14 |
| ITA   | 10           | 2,034 | 13 |
| URA   | 10           | 2,034 | 8  |
| **total** | 68 | 13,748 obs | 84 events |

Two components dropped after delisting (ABB, IRBT — BOTZ keeps 8).

## Method

**Coherence measures**, 90d rolling window per theme:
1. `pc1_share` — variance share of first principal component
2. `avg_corr` — mean pairwise component return correlation
3. `dispersion` — average cross-sectional std of daily component returns

**Lookahead guard**: `pc_share_lag = coh["pc1_share"].shift(1)` before any
event detection or outcome alignment (SIGNAL_SHIFT_1 marker, line 296 of
`k1530.py`). Forward outcomes use `.shift(-H)` with H=21d/63d.

**Event definition**: rising-edge crossing where lagged PC1 share drops
**>1.5 SD below its 252d rolling mean** (z-score < −1.5).

**Forward outcomes** (H = 21d, 63d):
- `rv_H` — annualized realized vol over (t+1, …, t+H)
- `mdd_H` — max drawdown over (t+1, …, t+H), with initial wealth = 1.0
  (Codex review caught and fixed a bug where wealth started at the first
  forward return, masking t+1 drops)
- `rel_H` — theme ETF return minus SPY return over (t+1, …, t+H)

**Stats**: Harvey (2016) HAC t-stat, lag = ⌊N^(1/3)⌋; bootstrap 95% CI on
mean event diff (1000 reps, `default_rng(seed=42)`); require n_events ≥ 10
for HAC t (else reported as NaN — exploratory only).

**OOS split**: in-sample 2018-01-01 → 2021-12-31 vs out-of-sample 2022+.

**Hypothesis-right sign**: rv positive, mdd negative, rel negative.

## Results

| Theme  | Top |t| outcome  | Harvey t  | Direction        | Pass? |
|--------|------------------|----------:|-------------------|-------|
| AIQ    | n_events < 10    | n/a       | exploratory       | no    |
| BOTZ   | rv_21            | **−4.97** | **WRONG-sign**    | no    |
| ARKK   | n_events < 10    | n/a       | exploratory       | no    |
| ICLN   | rel_21           | +1.41     | wrong-sign, n.s.  | no    |
| CIBR   | rel_63           | **+3.01** | **WRONG-sign**    | no    |
| ITA    | rel_21           | −1.01     | n.s.              | no    |
| URA    | n_events < 10    | n/a       | exploratory       | no    |

**Headline numbers**:
- `n_themes_pass_harvey_full = 0` of 7
- Maximum |Harvey t| = 4.97 (BOTZ rv_21) — **opposite sign**
- A second |t|>3 effect (CIBR rel_63 = 3.01) — also **opposite sign**

Two of seven themes thus show **statistically significant evidence in the
direction opposite** to the crash-precursor hypothesis: after a PC1 share
decline, BOTZ realized vol *falls*, and CIBR *outperforms* SPY at 63d. The
remaining five themes are non-significant or under-powered.

**OOS replication**: not applicable — no theme passes IS to begin with.

## Honest interpretation

**The crash-precursor hypothesis is rejected.** Theme-internal coherence
decay does **not** predict higher theme-ETF vol, deeper drawdowns, or
underperformance vs SPY. Where any significant signal exists, the sign is
**opposite** to the hypothesis (BOTZ: lower vol after decay; CIBR:
outperforms SPY after decay).

A coherent alternative reading: PC1 share decline reflects **idiosyncratic
divergence** within a basket of names that share macro / factor exposures.
After divergence, the basket's *variance share captured by a single factor*
falls — but total ETF variance may also fall as the idiosyncratic
components partly offset. This is consistent with diversification mechanics,
not crash dynamics.

The standard market-level finding (correlation *rises* before crashes)
therefore does **not** carry over to theme-internal coherence, at least with
this measurement.

## Verdict logic

Per task spec:
- PASS: ≥3 themes with Harvey |t|>3 and right sign + OOS replicate — not met
- CONDITIONAL_PASS: 2 themes pass — not met
- FAIL: <2 themes pass OR direction reverses OOS — **met** (0 themes pass;
  two themes show significant wrong-sign effects)
- NULL: all |t|<2 — not met (BOTZ rv_21 |t|=4.97 violates the null guard)

Final classification: **FAIL**.

## Codex review (pre-finalization)

Reviewer: `codex-cli 0.139.0 / gpt-5.4` (ChatGPT auth).
Verdict: CONDITIONAL_PASS after the following fixes:

1. **MDD initial-peak bug** — `_maxdd()` started cumulative wealth at the
   first forward return, masking a t+1 drop. Fixed by prepending wealth=1.0
   to the wealth series.
2. **Verdict-classifier latent issue** — OOS replication only required
   sign-consistency between IS and OOS, not hypothesis-right sign in both.
   Tightened to require `_hypothesis_sign_diff(col, diff)` in both windows.

Verified no lookahead leakage: rolling coherence uses past-only window, then
`.shift(1)` before event detection; the 252d rolling baseline operates on
the *already-lagged* PC1 series.

Static top-10 holdings flagged as acceptable for a pilot, not for
publication-grade claims.

## Limitations

1. ETF holdings hardcoded as static top-10; ignores rebalances and weight
   drift over 2018-2026.
2. Some components have short histories (PLTR 2020+, COIN 2021+, U 2020+),
   biasing early-sample coherence toward fewer effective names.
3. Event threshold fixed at 1.5 SD; not all (window × threshold) cells
   swept.
4. Single OOS split (pre/post 2022); no rolling-origin or block-bootstrap
   OOS test.
5. Component returns not winsorized; preserves drawdown realism but lets
   single-day extremes drive coherence dips.
6. No forward-vol regime control (e.g. VIX, term structure); a regime-
   conditional analysis is the natural follow-up.

## Next follow-ups

1. **Time-varying holdings** — replace static top-10 with NPORT-P filings
   or ETF.holdings API; many themes (ARKK in particular) rotate >40% per
   year.
2. **Alternative coherence measures** — Brownian distance correlation,
   graph-Laplacian connectivity, or rank-correlation kernels for nonlinear
   regimes.
3. **Sign-flipped tradable test** — given the empirical (wrong-sign) result,
   test whether coherence *decay* is a **long signal** for theme ETFs
   relative to SPY at 63d, with appropriate transaction costs and bootstrap
   p-values.
4. **VIX-regime conditioning** — does the wrong-sign result hold in high-VIX
   sub-samples (where K1423 found |t|>16 for VIX × Hurst), or invert?
5. **Cross-asset extension** — same test for sector ETFs (XLK, XLE, XLF) as
   a non-thematic control; would establish whether the null is theme-
   specific or generic.

## Files

- `k1530.py` — full reproducible script (seed=42, MPL Agg, yfinance with
  on-disk csv cache under `data/`)
- `k1530_results.json` — structured results + codex_review provenance
- `fig_coherence_timeseries.png` — PC1 share per theme over time
- `fig_event_study.png` — Harvey t-stat per (theme × outcome); red bars
  flag |t|>3
- `fig_oos.png` — IS vs OOS Harvey t scatter
- `data/*.csv` — yfinance close-price cache

## Reproducibility

```bash
uv run python experiments/k1530/k1530.py
```

Cached CSVs in `data/` will be reused; delete to force re-download.
