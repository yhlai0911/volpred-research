# K1624 — Volatility "long memory": true fractional integration vs spurious (level-shift-induced)

**Verdict (one line):** The apparent long memory (`d̂ ≈ 0.4–0.6`) in daily volatility proxies is **predominantly SPURIOUS — an artefact of occasional mean/level shifts (vol regimes), not genuine fractional integration** (5 of 6 asset×proxy cells "spurious", 1 "mixed"). It is *cleanly* spurious for the `|r|` proxy (replicating Granger–Hyung 2004 across SPY, ^GSPC, 0050.TW) and *mostly* spurious for the smoother Garman–Klass range proxy, which retains only a weak genuine-LM component (SPY = the single "mixed" case).

---

## 1. Motivation

Daily volatility proxies show slowly-decaying autocorrelations and log-periodogram estimates of the fractional-integration order routinely land at `d ≈ 0.4`. Two observationally-similar generating mechanisms produce this:

1. **True long memory** — genuine fractional integration `I(d)`, `0 < d < 0.5` (long-range dependence, ACF `∝ k^{2d-1}`).
2. **Spurious long memory** — a **short-memory** process contaminated by **occasional level shifts / structural breaks** in its mean, which mimics slow ACF decay and inflates `d̂` (Granger & Hyung 2004 JEF; Diebold & Inoue 2001 JoE; Mikosch & Stărică 2004; Perron & Qu 2010; Qu 2011 JBES).

The distinction matters commercially and scientifically: it dictates whether ARFIMA-type models (which *impose* fractional integration) are the right forecasting tool, or whether a **short-memory + adaptive-level** model is more honest and more robust.

## 2. Differentiation from existing K (what is genuinely new)

| K | What it did | Why this is NOT a repeat |
|---|---|---|
| **K442** | Estimated FIGARCH `d = 0.61` on vol | Estimated `d` but **never asked whether that `d` is real or a break artefact.** K1624 supplies exactly the missing identification. |
| **K529 / K806 / K936 / K1423 / K1424 / fae873b0** | Rough volatility, `H ≈ 0.1`, ARRV, Hurst `< 0.5` | Those concern **path roughness** (local, high-frequency, anti-persistent) — a **different, often opposite** concept from **long memory** (low-frequency, long-range dependence, `d > 0`). **K1624 does NOT re-run rough vol**; it works strictly on the long-memory (low-frequency) side and asks *true vs level-shift-induced*. |

Novel contribution = a **formal, self-calibrating identification** of true-vs-spurious long memory in the platform's core vol proxies + its **forecasting consequence**. Never done on this platform before.

## 3. Data

- **Source:** `yfinance` daily OHLC, `auto_adjust=False`, close-to-close log returns. (yfinance succeeded first try; no fallback needed.)
- **Assets / periods / N:**
  - **SPY** 1993-01-29 → 2026-07-02, **N = 8,413**
  - **^GSPC** 1985-01-02 → 2026-07-02, **N = 10,455** (longest history, robustness)
  - **0050.TW** 2009-01-02 → 2026-07-03, **N = 4,282** (yfinance's 0050.TW history begins 2009, not 2003)
- **Two vol proxies per asset** (mutual robustness), analysed as **log-vol** `y_t = 0.5·log(V_t)`:
  1. **`range`** — Garman–Klass daily variance `σ²_GK = 0.5(ln H/L)² − (2ln2−1)(ln C/O)²` (≥ 0 for valid OHLC).
  2. **`absret`** — squared daily log-return `r²` (i.e. the `|r|` proxy Granger–Hyung 2004 used, for direct literature comparison).
- Zero-move days (exact-zero returns / zero-range) floored at a **fixed, data-independent** constant `VAR_FLOOR = 1e-8 ≈ (1 bp)²` — see §7 (removes a lookahead point Codex flagged; results robust to it). Floored counts: SPY range 0, SPY `|r|` 62; TW0050 range 21, `|r|` 182; GSPC range 0, `|r|` 9.

## 4. Method

### Part 1 — Identification (core)

1. **Estimate `d`** on log-vol at bandwidths `m = T^0.5, T^0.6, T^0.7` with two estimators:
   - **GPH** log-periodogram regression (Geweke–Porter-Hudak 1983), `se = √((π²/6)/Σ(X−X̄)²)`.
   - **Local Whittle** (Robinson 1995), `se = 1/(2√m)`.
   *Spurious LM signature:* `d̂` unstable / decreasing across `m`.
2. **Level-shift detection** — `ruptures` PELT, `l2` cost = Bai–Perron-style least-squares multiple **mean** breaks; BIC-type penalty; penalty-sensitivity reported (×0.5/×1/×2/×3).
3. **Decisive diagnostic — demean-then-reestimate `d`:** subtract detected segment means and re-estimate `d` (`d_post`). Spurious ⇒ `d_post → 0` (persistence lived in the level shifts); true LM ⇒ `d_post` stays high.
4. **Formal test — Shimotsu (2006)** split-sample `d`-homogeneity Wald (`b = 2, 4`): `W = 4·m_block·Σ(d̂_a − d̄)² ~ χ²_{b-1}`. Reported (asymptotic) but *not* trusted at face value — see next.
5. **⚠️ Size-distortion problem, and the fix (the methodological core).** Standard break tests, the demean-reestimate, **and** Shimotsu **all over-reject "no break" / collapse `d_post` / inflate `W` under GENUINE long memory** — a true `I(d)` path wanders and gets over-segmented (we *demonstrate* this: on simulated true `I(0.35)/I(0.45)`, PELT finds 35–57 spurious "breaks" and demeaning drives `d_post` negative). **So the raw drop is NOT self-sufficient.** We therefore run a **true-LM parametric bootstrap**: fit `ARFIMA(0, d_pre, 0)` (the true-LM null), simulate `B = 200` paths, push each through the *identical* pipeline, and compare the **observed** statistics to their **null distribution**. One-sided bootstrap p-values in the *spurious* direction:
   - `d_post`: spurious ⇒ observed `d_post` **higher** than the true-LM null (which over-differences to `≈ −0.49`). `p = P(null ≥ obs)`.
   - Shimotsu `W`: spurious ⇒ **larger** `W`. `p = P(null ≥ obs)` (self-calibrates Shimotsu's size distortion).
   - `d_full − d_bar`: level shifts inflate full-sample `d` above subsample `d`.
   - **Verdict rule:** # significant (p < 0.05) among `{d_post, W4, d_full−d_bar}` → ≥2 = spurious, 0 = true LM, 1 = mixed.
   - **Method validation** (before touching real data): now landed as a re-runnable Monte-Carlo harness `k1624_validation.py` (`--full` = 40 reps/DGP, B=200, n=4000; seeded; imports the *identical* `bootstrap_identification` pipeline). Full-run misjudgment rates (`k1624_validation_results_full.json`): simulated true `I(0.4)` → **82.5% correctly "true LM", 5.0% false-positive** (2/40 finite-sample false rejects — the smoke run's 0.0 was small-N luck); short-memory AR(0.3) + level shifts → **100% correctly "spurious"** (mean `p_dpost≈W4≈gap≈0.000`). The property the real-data verdict depends on — power to reject *spurious* long memory — is 100% at N=40; the 5% false-positive on genuine LM is an honest finite-sample Type-I-like rate that does not weaken the "spurious" call on real data (when the pipeline says spurious, it rarely mislabels true LM).

### Part 2 — Forecasting implication

Single fixed OOS window (**expanding**, monthly refit, train tail ≥ 1,200, **OOS = 1,000**), 1-day-ahead forecast of log-vol proxy, three models:
- **(a) ARFIMA(0,d,0)** — assumes true long memory; `d` from Local Whittle on the training window; AR(∞) forecast `ŷ*_{t} = −Σ π_k y*_{t−k}`.
- **(b) HAR** (Corsi 2009) — short-memory baseline (daily/weekly/monthly lagged averages).
- **(c) break-robust HAR** — HAR on deviations from a **causal rolling 252-day local mean** (adaptive intercept): the "if persistence is level shifts, an adaptive mean should win" hypothesis.

Evaluation: **QLIKE** (canonical `actual/predicted − log(actual/predicted) − 1` via `volpred.stats.model_evaluation.qlike/qlike_pointwise`, on variance scale with a **consistent** per-model lognormal bias correction `exp(2ŷ + 2s²)`) + **Diebold–Mariano** with **Harvey–Leybourne–Newbold (1997)** small-sample correction (t from `t_{n-1}`; Harvey 2016 `|t| > 3` multiple-testing bar flagged). Outlier-robust **MSE on log-vol** reported alongside.

## 5. Results

### 5.1 Identification (Local Whittle at `T^0.6`; full `d̂` across bandwidths in `_results.json`)

| Asset | Proxy | `d_pre` (T^0.5/0.6/0.7) | breaks | `d_post` (T^0.6) | boot p [dpost, W4, gap] | sig/3 | **Verdict** |
|---|---|---|---|---|---|---|---|
| SPY | range (GK) | 0.531 / **0.558** / 0.517 | 67 | −0.334 | [**0.000**, 0.260, 0.135] | 1 | **mixed** |
| SPY | absret (`|r|`) | 0.467 / **0.412** / 0.330 | 18 | +0.035 | [**0.000**, 0.555, **0.005**] | 2 | **spurious** |
| ^GSPC | range (GK) | 0.508 / **0.536** / 0.506 | 72 | −0.334 | [**0.000**, 0.770, **0.025**] | 2 | **spurious** |
| ^GSPC | absret (`|r|`) | 0.490 / **0.443** / 0.335 | 22 | +0.077 | [**0.000**, **0.040**, **0.000**] | 3 | **spurious** |
| 0050.TW | range (GK) | 0.650 / **0.533** / 0.428 | 26 | −0.187 | [**0.005**, 0.080, **0.040**] | 2 | **spurious** |
| 0050.TW | absret (`|r|`) | 0.407 / **0.352** / 0.237 | 5 | +0.212 | [**0.000**, **0.020**, **0.000**] | 3 | **spurious** |

Reading:
- **`|r|` proxy is unambiguously spurious in all 3 markets** — `d̂` **falls with bandwidth** (SPY 0.47→0.41→0.33; the classic spurious signature), break-adjustment drives `d_post ≈ 0` (way above the true-LM null band `[−0.49,−0.17]`), and 2–3/3 bootstrap statistics reject. This **replicates Granger–Hyung (2004)** on their exact proxy, out-of-sample in time and across markets.
- **Range/GK proxy** is smoother (`d̂` more stable across `m`) and retains *some* genuine persistence, but break-adjustment + the bootstrap still flag it: **spurious for GSPC and 0050.TW**, and only **SPY range is "mixed"** (its `d_post = −0.334` is significantly above the true-LM null → real shifts present, but Shimotsu `W4`/`gap` don't confirm → not fully explained by shifts either).
- **Shimotsu asymptotic χ² is internally inconsistent** (e.g. SPY range b2 p=0.050 vs b4 p=0.144; GSPC absret b2 p=0.217 vs b4 p=0.019) — exactly the size distortion that motivates the bootstrap calibration; we therefore report it for reference only and base verdicts on the bootstrap.
- **Detected mean shifts map onto real vol regimes** (descriptive): breaks cluster at 2000 (dot-com), **2007-07 / 2008-01 / 2008-09 / 2008-12 (GFC)**, **2011-08 / 2011-11 (EU crisis)**, **2020-02 / 2020-05 / 2020-11 (COVID onset / crash / vaccine)**, **2022-01 / 2022-11 (bear market)** — consistent across SPY, ^GSPC and 0050.TW. Full break lists in `_results.json`.

### 5.2 Forecasting (OOS = 1,000, expanding, monthly refit)

| Asset | Proxy | QLIKE (arfima / har / brk) | MSE-logvol (arfima / har / brk) | DM arfima−har `t_hln (p)` | DM brk−har `t_hln (p)` |
|---|---|---|---|---|---|
| SPY | range | 0.360 / **0.342** / 0.343 | 0.164 / 0.158 / **0.158** | +2.07 (0.039) | +0.46 (0.644) |
| SPY | absret | 2.340 / **2.014** / 2.041 | 1.565 / 1.320 / **1.320** | **+10.72 (0.000)** | +2.10 (0.036) |
| ^GSPC | range | 0.378 / **0.361** / 0.363 | 0.172 / **0.166** / 0.166 | +1.50 (0.135) | +0.86 (0.392) |
| ^GSPC | absret | 2.613 / **2.065** / 2.106 | 1.744 / **1.444** / 1.445 | **+13.22 (0.000)** | **+3.04 (0.002)** |
| 0050.TW | range | 5.094 / **0.594** / 0.596 | 0.346 / **0.312** / 0.312 | +1.37 (0.172) | +0.15 (0.878) |
| 0050.TW | absret | 2.559 / **1.999** / 2.128 | 1.390 / 1.230 / **1.199** | **+13.32 (0.000)** | **+8.66 (0.000)** |

*(positive `t_hln` for `arfima−har` ⇒ ARFIMA **worse** than HAR; positive `brk−har` ⇒ break-robust **worse** than HAR on QLIKE. Harvey `|t|>3` bolded. Note QLIKE vs MSE-logvol can disagree on the noisiest cells because QLIKE is tail-sensitive on the variance scale.)*

Reading:
- **ARFIMA (assuming true LM) never wins** — it is worse than or tied with HAR in every cell on both metrics, and **significantly worse (Harvey `|t|>3`) on all three `|r|` proxies**. On the noisiest cell it also **blows up numerically** (0050.TW/range QLIKE = 5.09 vs HAR 0.59) — naive `ARFIMA(0,d,0)` point forecasts near the `d→0.5` boundary produce occasional catastrophic variance forecasts (robust MSE-logvol confirms the blow-up is tail-driven: 0.346 vs 0.312, only mildly worse).
- **Plain short-memory HAR is the robust winner** — at least as good as ARFIMA everywhere, decisively better on the break-contaminated `|r|` proxy. **The forecasting evidence corroborates the identification verdict:** imposing fractional integration buys nothing and can hurt.
- **The fancy break-robust HAR does NOT systematically beat plain HAR.** On QLIKE it is tied-to-slightly-worse in every cell (positive `brk−har`, Harvey-significant only for the two most break-driven cells GSPC/0050.TW `|r|`); on the outlier-robust MSE-logvol it merely *ties* HAR except on **0050.TW `|r|`** (the single most level-shift-driven cell), where the adaptive rolling-mean intercept genuinely helps (MSE 1.199 vs 1.230). Takeaway: HAR's own daily/weekly/monthly components already absorb the level shifts almost everywhere, so a crude rolling-mean regime tracker adds value only in the most shift-dominated series — again consistent with the identification map.

### 5.3 Figures (all real matplotlib; SPY + 0050.TW, both proxies)

- `fig_breaks_<asset>_<proxy>.png` — log-vol series with detected level shifts + segment means.
- `fig_d_bandwidth_<asset>_<proxy>.png` — `d̂` vs bandwidth, pre- vs post-break-adjust (with CIs).
- `fig_periodogram_<asset>_<proxy>.png` — log-log periodogram, raw vs break-adjusted (low-frequency power removed by demean).
- `fig_null_dpost_<asset>_<proxy>.png` — **the decisive plot**: observed break-adjusted `d` vs the true-LM bootstrap null distribution.
- `fig_oos_cumloss_<asset>_<proxy>.png` — OOS cumulative QLIKE loss differences.

## 6. Conclusion

**The high persistence of daily volatility proxies is largely a level-shift artefact, not genuine long memory.** For the Granger–Hyung `|r|` proxy this is unambiguous across SPY, ^GSPC and 0050.TW (bootstrap-calibrated rejection + the tell-tale bandwidth-decreasing `d̂` + `d_post ≈ 0`). For the smoother Garman–Klass range proxy the persistence is *mostly* level-shift-driven too (spurious for GSPC and 0050.TW), with only **SPY range** retaining enough genuine persistence to read "mixed". The forecasting exercise agrees: **ARFIMA never beats a short-memory HAR and is fragile**, and an adaptive-mean (break-robust) HAR only helps where shifts most clearly dominate. This is a **null-leaning, honestly-reported** result exactly in line with the identification literature — apparent volatility long memory should be treated as (mostly) spurious, and short-memory-with-regime-shifts is the more defensible modelling stance.

## 7. Anti-error checklist

- [x] **Lookahead** — every OOS predictor for `y_t` uses info dated ≤ `t−1` (ARFIMA `ys[t-1::-1]` + `μ_t = mean(y[:t])`; HAR rows `y[t-1]`, `mean(y[t-5:t])`, `mean(y[t-22:t])`; break-robust `lm[t] = mean(y[t-252:t])`); refits use `y[:t]` only. **Codex-verified.** The one residual lookahead Codex found (zero-move floor computed from full-sample median) was fixed to a **fixed data-independent constant** and the experiment **re-run** — verdicts unchanged.
- [x] **Baseline same lag** — all three models share the identical lag convention.
- [x] **Seeds fixed** — `np.random.seed(42)`; bootstrap paths `default_rng(SEED+1+b)`; forecasting deterministic.
- [x] **QLIKE direction** — canonical `actual/predicted − log(actual/predicted) − 1` via volpred helper (Codex-verified not inverted); bias correction applied **consistently** to all 3 models.
- [x] **No conclusions from eyeballing** — every verdict backed by a bootstrap-calibrated p-value; every forecast claim by HLN-corrected DM.
- [x] **Package-limitation ≠ model-invalidity (K1213)** — GPH/LW/Shimotsu/fractional weights hand-coded (scipy/numpy), validated on simulated ground truth.
- [x] **Method validated via re-runnable harness** (`k1624_validation.py --full`, results in `k1624_validation_results_full.json`): simulated true-`I(d)` → 82.5% correct, **5.0% finite-sample false-positive** (2/40, not "no reject" — corrected 2026-07-08 after full Monte-Carlo); short-memory+shift → **100% correct reject** (the property the real-data "spurious" verdict relies on). Closes Codex 24h-review (mile_c538af9e) reproducibility residual #1.
- [x] **Null / mixed reported honestly**, strength not overstated; SPY-range "mixed" and the ARFIMA blow-up disclosed rather than hidden.

## 8. Limitations

1. **Break-test size distortion under true LM is real** — we mitigate it with the parametric-bootstrap calibration (the whole point of §4.5), but the bootstrap null is itself `ARFIMA(0,d_pre,0)`; a richer true-LM DGP (e.g. LM-in-vol *with* fat-tailed innovations) could shift the null band. The `|r|` verdicts are far inside the rejection region, so robust; the range verdicts (esp. SPY "mixed") are closer to the boundary.
2. **Level shifts vs slowly-varying trends** are not separately identified — PELT models abrupt mean shifts; a smoothly time-varying unconditional variance would also inflate `d̂` and is observationally similar (Mikosch–Stărică). Either way the conclusion "not pure fractional integration" holds.
3. **`d` in the near-nonstationary region** (`d̂ → 0.5`, esp. range proxy) stresses Local Whittle (bias) and the ARFIMA forecast (the blow-up). Exact/robust LW variants (Shimotsu–Phillips 2005) could tighten range-proxy `d̂`; not pursued here.
4. **0050.TW `|r|` has 182 floored zero-move days** (thin-trading / limit days); although floored causally and results are robust, that proxy is the noisiest.
5. **Forecasting used one fixed OOS window** per cell (per scope); no rolling-origin robustness or MCS across many windows.
6. **Formal test = Shimotsu-via-bootstrap**; a from-scratch Qu (2011) sup-Wald or Ohanissian–Russell–Bhansali temporal-aggregation test would be complementary but was deprioritised for reliable implementation (the bootstrap already self-calibrates the size distortion those tests target).

## 9. Review

- **Codex CLI review** (gpt-5.5, xhigh reasoning, 2026-07-04): 7/8 sections **confirmed correct** — lookahead, QLIKE direction + consistent bias correction, GPH, Local Whittle, Shimotsu Wald df/scaling, HLN correction, bootstrap one-sided directions, fractional-diff/MA weight signs, seed determinism. One **HIGH** finding (full-sample floor → lookahead) **fixed and re-run**; verdicts unchanged.

## Files

- `k1624_rv_long_memory_vs_level_shifts.py` — reproducible script (seeds, explicit lags, hand-coded estimators, bootstrap identification, forecasting).
- `k1624_rv_long_memory_vs_level_shifts_results.json` — all numbers (per asset×proxy: `d̂` at every bandwidth pre/post, break dates, penalty-sensitivity, Shimotsu, bootstrap p-values + null bands, OOS QLIKE/MSE/DM).
- `fig_*.png` — 20 figures (SPY + 0050.TW × 2 proxies × {breaks, d-vs-bandwidth, periodogram, null-dpost, oos-cumloss}).

**Reproduce:** `uv run python experiments/k1624_rv_long_memory_vs_level_shifts/k1624_rv_long_memory_vs_level_shifts.py` (needs network for yfinance; `ruptures` installed via `uv pip install ruptures`). Runtime ≈ 4 min.
