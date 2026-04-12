# K1062: T+1 Event Window for 0050.TW — Resolves the K1059 vs K1060 Gap

**Proposer / Executor**: Claude (follow-up from K1060) / Claude
**Sample**: 2009-01-05 – 2025-12-30 (N = 4,161 trading days for 0050.TW)
**Data sources**: `財報公告日.txt` (Big5, 153,875 dated records, 2,409 firms); yfinance 0050.TW daily + ^VIX daily (`volpred.utils.clean_tw50_data` applied)
**Random seed**: 42 (bootstrap 5,000 reps)
**Runtime**: ~237 s on M1 Max

---

## 1. Motivation — the K1059 vs K1060 puzzle

| Experiment | Window | Subject        | Main stat                 | Verdict |
|------------|--------|----------------|---------------------------|---------|
| K1059      | T+0    | TSMC → 0050.TW | ratio = **1.007**, p = 0.986 | NULL    |
| K1060      | T+0    | 10 individual stocks | mean ratio = 0.936 | NULL    |
| K1060      | **T+1** | 10 individual stocks | mean ratio = **1.466**, t = 2.075, p = 0.034 | **Supported** |

K1060 revealed the mechanism — Taiwan listed firms usually disclose **after the cash-market close**, so the price shock cannot fully appear until T+1. This experiment asks the natural follow-up:

> **H1 (pure timing)**: if the ETF was simply mistimed, 0050.TW should *also* exhibit EAV at T+1.
> **H2 (diversification wash-out)**: individual-stock EAV exists but gets diluted by the other 49 constituents, so even T+1 ratio ≈ 1.

Note that K1059 Part A already showed, in its offset-by-offset table, an `offset = +1` abnormal-vol mean of **1.313** — but it was never isolated or tested. K1062 formalises that test.

---

## 2. Method

**Event-window construction.** Each TSMC announcement date (n = 94 raw, 64 after trading-day mapping & in-sample filter) is mapped forward to the first trading day ≥ announcement date (= **T+0**). Offsets shift that anchor. For the non-event baseline we remove **±5 days around every T+0** (n = 3,457 days, mean r² = 1.85 bp). All t-statistics are Welch's (unequal-variance). Bootstrap p-values use 5,000 resamples of the ratio of means (one-sided p(ratio ≤ 1)).

**Part D (model comparison).** Re-runs the K1058 custom-MLE GJR and A4f (multiplicative GARCH-X with VIX² as the long-run component), OOS 2010-01-04 onward, WINDOW = 2,000, quarterly refit (every 63 days), 63 refits total, 3,913 valid forecasts.

---

## 3. Results

### Part A — event-window ratios (TSMC → 0050.TW)

| Window | n event-days | mean r² (bp) | ratio | Welch t | p | bootstrap 95 % CI |
|--------|--------------|--------------|-------|---------|---|-------------------|
| T+0 only | 64 | 1.799 | 0.973 | −0.07 | 0.948 | [0.416, 1.904] |
| **T+1 only** | **64** | **2.094** | **1.132** | **+0.31** | **0.757** | **[0.496, 2.104]** |
| T+2 only | 64 | 1.324 | 0.716 | −1.31 | 0.193 | [0.379, 1.187] |
| [−5, −1] pre-event | 320 | 1.532 | 0.829 | −1.11 | 0.269 | [0.583, 1.154] |
| [+1, +5] post-event | 320 | 1.361 | 0.736 | −1.98 | **0.049** | [0.528, 1.001] |
| [T+1, T+3] window | 192 | 1.359 | 0.735 | −1.50 | 0.136 | [0.460, 1.113] |

Key observations:

1. **T+1 is the only window with ratio > 1** (1.132), and it sits above both T+0 (0.973) and K1059's published figure (1.007). That is consistent with K1060: the announcement's vol shock does propagate to the next session.
2. The effect is **economically modest and statistically weak**. 95 % bootstrap CI [0.50, 2.10] straddles 1, and Welch-t = +0.31. With only 64 events, the ETF test has low power.
3. Days **+2 onward and the [+1, +5] averaged window** are actually **below** non-event vol — the post-event window as a whole shows mean-reversion. The shock is effectively confined to T+1.

### Part B — clustering × T+1

Defining a "dense" day as 90th-percentile announce count (≥ 122 firms):

| Group | n | mean r² (bp) | ratio vs none | Welch t | p |
|-------|---|--------------|---------------|---------|---|
| No announce (baseline) | 1,336 | 2.00 | 1.000 | — | — |
| Dense at T+0, **same-day vol** | 285 | 1.78 | 0.890 | −0.41 | 0.679 |
| Dense at T+0, **next-day vol (T+1)** | 285 | 1.45 | **0.725** | **−1.46** | **0.146** |
| Any-announce → next-day vol | 2,825 | 1.61 | 0.807 | −1.30 | 0.194 |

The sign persists from K1059 Part B: **clustering does not amplify ETF vol**, even when evaluated on T+1. Mechanically this is because the dense-announcement weeks fall in pre-scheduled reporting windows (May, August, November) during quieter macro regimes, so the calendar effect dominates. This is a **confounder**, not evidence against individual-stock EAV (which K1060 still finds at T+1).

### Part C — multi-firm T+1 regression

`r²[T+1] (bp) = α + β·n_announce[T+0] + γ·VIX[T+0] + ε`, N = 4,160.

| coef | value | t-stat |
|------|-------|--------|
| α | −4.35 | −13.82 |
| **β_n (announce count at T+0 → next-day vol)** | **−0.0003** | **−1.05** |
| γ_VIX | +0.32 | +20.92 |

R² = 0.095, driven almost entirely by VIX.

The T+1 regression still produces **β_n < 0 but not significant**. The T+0 replicate in the same dataset gives β_n = +0.0035 (t = +13.85), but that is the mechanical correlation of "busy announcement days fall in higher-activity calendar weeks". Neither sign survives once VIX is netted out on a forward basis, confirming Part B.

### Part D — A4f vs GJR conditional QLIKE (OOS 2010-2025, N = 3,913)

| Group | N | GJR QLIKE | A4f QLIKE | Diff (GJR−A4f) | DM t | DM p |
|-------|---|-----------|-----------|----------------|------|------|
| Overall | 3,913 | 2.108 | 2.080 | +0.028 | **+2.35** | **0.019** |
| Non-event | 3,793 | 2.115 | 2.090 | +0.025 | +2.06 | 0.039 |
| T+0 (TSMC) | 60 | 1.619 | 1.508 | +0.111 | +1.68 | 0.092 |
| T+1 (TSMC) | 60 | 2.148 | 2.017 | +0.130 | +1.31 | 0.189 |

- Overall and non-event QLIKE advantage of A4f is significant at 5 % (not yet crossing Harvey 2016's |t| > 3 threshold — consistent with K1058).
- **A4f's advantage is largest in absolute terms on TSMC-event days** (both T+0 and T+1: +0.11 and +0.13 vs +0.03 on non-event days, i.e. ~4-5× larger), but the 60-obs samples are too thin to reach the Harvey threshold.
- Directionally this is the expected pattern: the VIX² long-run component lets A4f adapt faster when the macro regime is tilting — and earnings-event days sample a subset of such regimes.

---

## 4. Verdict — H1 vs H2

Evaluating H1 against three conditions:

| Condition | Met? | Evidence |
|-----------|------|----------|
| T+1 ratio > 1 | **Yes** | 1.132 |
| T+1 ratio > T+0 ratio | **Yes** | 1.132 > 0.973 (Δ = +0.16) |
| Statistical evidence (t or bootstrap p < 0.10) | **No** | Welch p = 0.757; bootstrap one-sided p(ratio ≤ 1) = 0.34 |

**Verdict: H1 PARTIAL** — consistent with *timing + diversification*:

- The **timing story** is right: T+1 is where the ETF-level ratio is highest, matching K1060's individual-stock result.
- But **diversification wash-out is also real**: even on the correct day, the ETF ratio (1.13) is far smaller than the individual-stock ratio (1.47 in K1060), and the remaining signal is not statistically distinguishable from 1.

**Implication for A4f / VolPred**: there is no meaningful EAV-timing alpha to be captured at the ETF level through a TSMC-event dummy. Any useful earnings-day modelling must operate on individual names (K1060) and then be aggregated up — not on 0050.TW directly.

---

## 5. Cross-study summary

| Study | Object | Window | Ratio | n | p |
|-------|--------|--------|-------|---|---|
| K1059 | 0050.TW | T+0 | 1.007 | 64 | 0.986 |
| **K1062** | **0050.TW** | **T+1** | **1.132** | **64** | **0.757** |
| K1060 | 10 individual stocks | T+0 | 0.936 | ~370 | — |
| K1060 | 10 individual stocks | T+1 | 1.466 | ~370 | 0.034 |

---

## 6. Limitations

1. **Event count (n = 64)** is the binding constraint. With a standard deviation of single-day r² ≈ 2 bp, detecting a 13 % ratio shift at α = 5 % needs well over 100 events. Extending the sample to all Taiwan blue-chip announcements (not just TSMC) would increase power — but then Part C's clustering confound reappears.
2. **TSMC-only**: we did not aggregate individual-stock EAV up to an ETF-weighted synthetic return. Doing so is the next logical experiment (K1063 candidate).
3. **QLIKE scale** (~2.1) is larger than K1058 (~1.45) because K1062 uses an earlier OOS window (2010+ vs 2019+ in K1058), which includes higher-vol regimes (Fukushima, Taper Tantrum, 2015 China). The DM sign and overall A4f-better ordering replicate.
4. **Robustness not tested**: bandwidth to non-event baseline (we used ±5d exclusion), alternative RV proxies, t-distribution residuals.

---

## 7. Files

| File | Purpose |
|------|---------|
| `k1062.py` | Complete script (Parts A-D + charts + JSON) |
| `k1062_results.json` | All numbers (matched to this README) |
| `k1062_window_comparison.png` | Part A — six-window bar chart |
| `k1062_clustering_t1.png` | Part B — dense/any/none × T+0/T+1 |
| `k1062_a4f_conditional.png` | Part D — QLIKE + DM t-stats |
| `README.md` | This file |

## 8. References

- Patell & Wolfson (1984), *Journal of Accounting Research* — earnings-day vol.
- Beaver (1968), *Journal of Accounting Research* — vol/volume around earnings.
- Savor & Wilson (2016), *JFQA* — earnings as a systematic risk factor.
- Patton (2011), *Journal of Econometrics* — QLIKE for model ranking.
- K1058 — A4f on 0050.TW (DM NS, VaR Trinity A4f PASS).
- K1059 — TSMC → 0050.TW T+0 event study (ratio = 1.007, NULL).
- K1060 — Individual-stock EAV, mean T+1 ratio = 1.466, t = 2.075.
