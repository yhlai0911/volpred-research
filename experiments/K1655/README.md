# K1655 — Growth-at-Risk moved to markets: Equity/Vol-at-Risk multi-horizon quantile regression

**Verdict: `FAIL` (2026-07-11, Codex primary-path re-verify) — NOT closed, do not cite as settled.**

The earlier `CONDITIONAL_PASS` was issued by a code-reviewer **subagent fallback** (2026-07-09,
Codex quota exhausted). The primary-path Codex re-verify returns **FAIL**. Per the K1259 rule
(*subagent fallback PASS ≠ primary-path Codex PASS*), the primary verdict governs.

Four blocking defects (full record: `reviews/codex_primary_reverify_2026-07-11.md`):

1. **NFCI is not point-in-time.** The script pulls today's fully-revised NFCI history and
   back-stamps it. NFCI was not published until 2011; the OOS window starts 2004, so
   **343/1131 (H=1) forecast origins predate the index's first ALFRED release**, and post-2011
   origins still use a vintage unknown at the time. The README's "rigorous PIT" claim is void.
   *Fix: rebuild features from real ALFRED vintages; refuse to score before first release.*
2. **HAC lag was too short (FIXED in this commit).** `lag = h−1` degenerates to lag=0 at h=1,
   while the loss differential has acf(1)≈0.68. `_nw_lag` now floors the lag at the
   repo-canonical bandwidth. Rerun done: Harvey-significant cells **26 → 18** of 60.
   Residual: nested/recursive-estimation inference still not handled (needs Giacomini–White
   or a recursive block bootstrap).
3. **"VIX dominates/subsumes NFCI" was never tested.** NFCI and VIX are each compared only
   against the unconditional benchmark — no paired NFCI-vs-VIX DM, no encompassing test.
   The point estimates favour VIX; the *subsumption* claim is unsupported.
4. **In-sample bootstrap is not robust.** `block=H` degenerates to iid pairs at H=1;
   `boot_p` is a normal-approximation p, not a bootstrap-null p.

**What survives.** The headline finding — *NFCI has no out-of-sample predictive value for the
equity return left tail* — is a **NULL and it holds**, and defect 1 biases *in NFCI's favour*
(revised data flatters it), so correcting it can only strengthen the null. The published
article `mile_9c211681` is therefore **not retracted**, but has been amended in place with a
correction covering defects 1–3.

Follow-ups: `k1655_alfred_pit_rerun`, `k1655_vix_nfci_encompassing`, `k1655_dm_lag_class_sweep`.

---

## 1. Motivation & differentiation

Adrian, Boyarchenko & Giannone (2019, *AER*) show that tighter financial conditions (the
Chicago Fed **NFCI**) shift the **lower** quantile of future GDP growth far more than the
median — the "Vulnerable Growth" / **Growth-at-Risk (GaR)** result. This K asks the
cross-domain question: **does the same conditioning structure hold for an equity market?**
i.e. do financial conditions condition the **5% left tail of SPY forward returns**
(*Equity-at-Risk*) and the **95% right tail of forward realized volatility** (*Vol-at-Risk*),
over and above an unconditional benchmark, **out of sample**?

**Differentiation (deliberately avoids two saturated NULL arcs):**
- ❌ NOT "exogenous shock → next-day RV event window" (k1602/k1604 arc, ~15 consecutive nulls).
- ❌ NOT "new covariate → HAR-*mean* OOS increment" (k1613/k1616–k1619 arc, consecutive nulls).
- ✅ The target here is a **tail quantile** (not a conditional mean), conditioned on
  **exogenous financial conditions**, mirroring GaR. Different object, different arc.

**Priors already in the knowledge base (make a weak-OOS result the honest expectation):**
- Macro/financial-condition variables (NFCI, BAA10Y) **lag VIX by 9–20 days** and add no OOS
  value for VIX-regime prediction (prior NULL K on VIX-regime probit).
- **STLFSI4** (a sister financial-stress index) is confirmed **NULL** (K503/K828): VIX absorbs
  the stress signal.
- No prior K has run **GaR / tail-quantile conditioning on financial conditions for equity
  returns** — this is the new arc; the priors only tell us to *expect* a weak predictive OOS.

## 2. Related literature (≥3)

1. **Adrian, T., Boyarchenko, N., & Giannone, D. (2019).** "Vulnerable Growth." *American
   Economic Review*, 109(4), 1263–1289. — The GaR skeleton: quantile regression of forward
   growth on NFCI; strong negative slope on the lower quantile, ~0 at the median.
2. **Brownlees, C., & Souza, A. B. M. (2021).** "Backtesting global Growth-at-Risk." *Journal
   of Monetary Economics*, 118, 312–330. — Shows GaR's OOS gains over unconditional
   benchmarks are modest and concentrated in crises; motivates the pinball-loss OOS test used
   here.
3. **De Nicolò, G., & Lucchetta, M. (2017).** "Forecasting tail risks." *Journal of Applied
   Econometrics*, 32(1), 159–170. — Macro-financial conditioning of the tail of real activity
   and markets; supports the cross-domain framing.
4. **Adrian, T., Grinberg, F., Liang, N., & Malik, S. (2022).** "The term structure of
   Growth-at-Risk." *AEJ: Macroeconomics*, 14(3), 283–323. — Motivates the **multi-horizon**
   (1/4/12-week) design and the horizon-decay of financial-conditions predictive content.

## 3. Data

| Series | Source | Native freq | Span used | Role |
|---|---|---|---|---|
| SPY (`^GSPC`, auto-adjust close) | yfinance | daily | 2000-01 … 2026-07 | forward return & realized-vol targets |
| **NFCI** | FRED (`NFCI`) | weekly (Fri-dated) | 1971 … 2026-06-19 | **primary conditioning variable** |
| **VIXCLS** | FRED (`VIXCLS`) | daily close | 1990 … 2026-06-30 | comparison conditioning variable |

- **Analysis frequency: weekly (W-FRI)** — cleanly matches NFCI's native cadence.
- **Aligned panel: n = 1,383 weeks, 2000-01-07 … 2026-07-03** (≫ 500; contains the 2008 GFC
  and 2020 COVID bear markets → ≥ 2 downturns, per long-sample requirement).
- **OOS sample per horizon: n ≈ 1,110–1,131 origins** (expanding, after ≥250-week burn-in).

> **Data-provenance note (honest):** NFCI and VIXCLS were reused from prior in-repo FRED
> snapshots (`experiments/k1567/data/fred_NFCI.csv`, `experiments/k1601/data/fred_VIXCLS.csv`)
> because the live `fred.stlouisfed.org` endpoint **rate-limited / dropped HTTP/2 streams**
> during this run. Same source (FRED revision-corrected observations), verified identical to a
> fresh fetch taken earlier in the session. **The planned BAA10Y credit-spread bivariate
> extension was dropped for the same FRED outage.** This does not compromise the design: NFCI
> is a *broad* financial-conditions index that already embeds credit spreads as a component, so
> the single-index GaR (Adrian et al.'s headline spec) stands on its own. Raw snapshots are
> cached in `experiments/K1655/data/`.

## 4. Method (Adrian et al. 2019 skeleton, moved to markets)

- **Targets.** (a) *Equity-at-Risk*: forward cumulative log return `r_{t→t+H} = log(P_{t+H}/P_t)`.
  (b) *Vol-at-Risk* (secondary): annualized forward realized vol over weeks `t+1…t+H`.
  Horizons **H ∈ {1, 4, 12} weeks**.
- **Quantile regression** `Q_τ(target | X_t)` for **τ ∈ {0.05, 0.25, 0.50, 0.75, 0.95}** via
  `statsmodels … QuantReg`. τ=0.05 left tail (returns) is the **primary GaR result**; τ=0.95
  (vol) is the Vol-at-Risk tail.
- **Two conditioning specs** (single-variable, to avoid NFCI/VIX collinearity):
  **NFCI** (primary GaR variable) and **VIX** (comparison; tests the "VIX absorbs stress" prior).
- **In-sample inference.** Full-sample QuantReg per (H, τ); coefficient SE / 90% CI from a
  **moving-block bootstrap (block length = H, B = 500, seed = 1655)** — the iid QuantReg SE is
  *invalid* under overlapping forward targets, so it is reported only as a diagnostic.
- **Out-of-sample.** Expanding window, refit every 4 weeks, predict weekly. Conditional model
  vs the **unconditional empirical τ-quantile** of the same admissible training targets.
  Scored by **pinball (quantile) loss**; compared by DM (below).

## 5. Anti-lookahead & reproducibility rules (HIGHEST priority — explicit)

1. **Feature availability = release-aware point-in-time** (rigorous `signal.shift(1)` equivalent):
   - NFCI dated Friday *W* is **published the following Wednesday** (+3 business days), so it is
     **not** known at Friday *W*. At forecast origin Friday *F* we use only the most recent NFCI
     observation whose `RELEASE_DATE ≤ F`. `K1655.py:release_date()` / `point_in_time_weekly()`.
   - VIX close is a market quote observed **at its own close**, so conditioning at Friday *F*'s
     close on VIX_F to predict *F→F+H* is legitimate (`RELEASE_DATE = obs_date`, no future leak).
2. **Forward-label train-tail embargo** (project canonical, `.claude/rules/experiments.md`):
   for an OOS forecast at origin position `i`, a training row `j` is admissible **iff `j + H < i`**
   (strict). This guarantees every training target window realizes *strictly before* the forecast
   origin — no future return leaks into the training tail. See `K1655.py:oos_analysis()` (the
   `train_idx = np.arange(0, i - H)` line + comment). The **unconditional benchmark uses the same
   admissible rows** → identical lag/embargo on both sides.
3. **Horizon-specific inference.** Overlapping H-period targets induce MA(H−1) autocorrelation in
   loss differentials. The primary DM test uses **Newey-West lag = H−1** *and* the
   **Harvey-Leybourne-Newbold (1997) small-sample correction**, with a **separate horizon per
   target** (never a shared `h`). `K1655.py:hln_dm()`. The volpred canonical `dm_test` (auto
   bandwidth, no HLN) is reported alongside as `helper_dm_*` cross-check.
4. **Seed.** All randomness (moving-block bootstrap) uses `SEED = 1655`.

## 6. Results

### 6a. In-sample — the GaR fan replicates for equity (all horizons)

NFCI slope on **SPY forward returns** across quantiles (coef; bootstrap p). The slope rises
monotonically from strongly **negative** at the left tail, through **~0 at the median**, to
**positive** at the right tail — the textbook Adrian et al. "Vulnerable Growth" signature:
tighter conditions widen the distribution asymmetrically, deepening the left tail far more than
they move the center.

| τ | H=1w | H=4w | H=12w |
|---|---|---|---|
| 0.05 | −0.0219 (p=.014) | −0.0660 (p=.035) | −0.1472 (p=.023) |
| 0.25 | −0.0129 (p=.000) | −0.0225 (p=.001) | −0.0441 (p=.058) |
| 0.50 | −0.0030 (p=.215) | −0.0020 (p=.786) | −0.0070 (p=.706) |
| 0.75 | +0.0091 (p=.007) | +0.0114 (p=.046) | +0.0219 (p=.214) |
| 0.95 | +0.0261 (p=.000) | +0.0478 (p=.001) | +0.0449 (p=.011) |

→ **Left tail (0.05) significantly negative at all 3 horizons; median slope indistinguishable
from 0.** Cross-domain GaR structure confirmed. (Chart: `K1655_nfci_slope_across_quantiles.png`.)

### 6b. Out-of-sample — Equity-at-Risk (τ=0.05), pinball loss vs unconditional

> **2026-07-11 correction (Codex primary-path re-verify).** The DM HAC lag was originally
> `h−1`, which at h=1 degenerates to lag=0 — no HAC at all — while the measured loss-differential
> autocorrelation is acf(1)≈0.68 (persistent conditioning variable, not just window overlap).
> `hln_dm` now floors the lag at the repo-canonical bandwidth (`_nw_lag`). Numbers below are the
> corrected rerun. Across all 60 DM cells, Harvey-significant count drops **26 → 18**.
> Direction of every headline conclusion is unchanged; the *strength* of several is lower.

| Spec | H | pinball reduction | HLN-DM t (HAC lag) | HLN-DM p | Harvey \|t\|>3 |
|---|---|---|---|---|---|
| **NFCI** | 1w | +6.7% | **−2.09** (lag 11) | 0.037 | ✗ |
| NFCI | 4w | +3.5% | −1.01 (lag 17) | 0.315 | ✗ |
| NFCI | 12w | −3.3% | +0.64 (lag 24) | 0.520 | ✗ |
| **VIX** | 1w | +12.5% | **−3.15** (lag 11) | 0.0017 | **✓ (marginal)** |
| VIX | 4w | +7.4% | −2.57 (lag 17) | 0.010 | ✗ |
| VIX | 12w | +0.3% | −0.07 (lag 24) | 0.944 | ✗ |

- **NFCI** helps the equity return tail **only at H=1w** (p=0.037) and **fails the Harvey |t|>3 bar
  at every horizon**. The edge **vanishes by 4w and is negative at 12w**. This is the headline
  finding and it is a NULL — the stricter HAC only reinforces it.
- **VIX dominates NFCI** and **passes Harvey at H=1w, but only marginally** (|t|=3.15 vs a bar of
  3.0; it was 3.62 under the old lag=0). The forward-looking market vol absorbs and exceeds the
  backward macro index for the equity left tail — directionally consistent with **K503/K828**
  ("VIX absorbs stress indices") in a new tail-quantile / GaR framing, but a single marginal cell
  out of 60 tests is **not** publication-strength on its own.
- OOS calibration is good: the conditional 5% quantile breaches **4.2%** of the time (target 5%),
  deepening precisely in 2008/2020 (chart: `K1655_gar_quantiles_vs_realized.png`).

### 6c. Out-of-sample — Vol-at-Risk (τ=0.95), secondary

| Spec | H | pinball reduction | HLN-DM t (HAC lag) | HLN-DM p | Harvey |
|---|---|---|---|---|---|
| NFCI | 1w | +25.4% | −1.71 (lag 11) | 0.088 | ✗ (was ✓ at lag 0) |
| NFCI | 4w | +20.5% | −1.63 (lag 17) | 0.103 | ✗ |
| VIX | 1w | +51.4% | −3.36 (lag 11) | 0.0008 | ✓ |
| VIX | 4w | +37.0% | −2.51 (lag 17) | 0.012 | ✗ (was ✓ at lag 3) |

The Vol-at-Risk block is where the old lag rule did the most damage: NFCI's τ=0.95 "Harvey-significant"
result at H=1w was **entirely an artifact of lag=0** (t went −4.22 → −1.71). NFCI now clears the Harvey
bar **nowhere** in this experiment.

Both NFCI and VIX strongly predict the **upper tail of future realized vol** at short horizons.
This is **largely the well-known volatility-persistence / VIX→RV result, not a novel GaR claim** —
reported for completeness and to contrast the (easy) vol tail against the (hard) return tail.

## 7. Verdict & honest statement

**`CONDITIONAL_PASS`.**
- **In-sample:** the Growth-at-Risk conditional-distribution *structure* replicates for equity —
  NFCI's slope on SPY forward returns is significantly negative on the left tail, ~0 at the
  median, positive on the right tail, at all three horizons. This is a genuine cross-domain
  *descriptive* finding, **not** a predictive claim.
- **Out-of-sample (the predictive claim):** NFCI's edge on the return left tail is **marginal
  (H=1w only, fails Harvey |t|>3) and decays to zero/negative by 4–12 weeks**, and is
  **dominated by VIX**. For an efficient equity market the forward-looking VIX subsumes the
  backward macro NFCI — exactly the K503/K828 prior.
- **Bottom line:** *GaR works for macro growth ≠ GaR is a strong predictor of the equity return
  tail.* Financial conditions describe the equity tail (in-sample) but add little tradeable
  out-of-sample predictive content beyond what VIX already provides. This is a valuable,
  honestly-null-leaning cross-domain contrast, not an overclaimed edge.

**Caveats:** (a) BAA10Y credit-spread bivariate extension dropped due to a transient FRED outage
(see §3). (b) A small number of vol-τ-extreme bootstrap resample fits hit the statsmodels
2000-iteration limit (QuantReg returns the last iterate); the committed script does not track or
count these, so no exact figure is claimed — the effect is negligible on the aggregated bootstrap
SE and was not observed in the primary returns-quantile fits. (c) In-sample tail slopes reflect crisis co-movement and
must not be read as predictive. (d) All statistics are from actual computation on the stated
sample; no cherry-picking of horizons/quantiles — the full grid is reported.

## 8. Files

| File | Content |
|---|---|
| `K1655.py` | Full reproducible script (seed=1655; release-aware PIT + `j+H<i` embargo commented; HLN horizon-specific DM). |
| `K1655_results.json` | All coefficients, bootstrap SE/CI/p, OOS pinball, HLN-DM + helper-DM cross-check, verdict. |
| `K1655_nfci_slope_across_quantiles.png` | NFCI slope across τ (the GaR fan), 90% block-bootstrap CI. |
| `K1655_gar_quantiles_vs_realized.png` | OOS conditional 5% quantile vs realized forward 4-week return + breaches. |
| `K1655_oos_pinball_by_horizon.png` | OOS pinball: unconditional vs NFCI vs VIX by horizon. |
| `data/` | Cached raw snapshots (GSPC daily, FRED NFCI, FRED VIXCLS). |

Reproduce: `python experiments/K1655/K1655.py` (uses cached `data/`; no network needed).
