# Paper 2 R1 SEVERE 2 Fix — VIXTWN/VIX 1.39 Linearity Check

**Date**: 2026-05-12
**Author**: VolPred Research System (Yi-Hao Lai)
**Paper**: `paper/taiwan-vt/` (target: Pacific-Basin Finance Journal)
**Triggering review**: `paper/taiwan-vt/gemini_review_v1.md` SEVERE 2
**Status**: Stand-alone robustness analysis; ready for main-thread body integration
**Codex review**: Queued for 2026-05-13 02:46 UTC (quota reset). Primary-path
Codex review pending; subagent fallback may be invoked if Codex stays blocked
per `.claude/rules/experiments.md` § Codex CLI fallback policy.

---

## 1. Context

Gemini R1 review flagged SEVERE 2 (line 12 of `gemini_review_v1.md`):

> "Linear scaling: 1.39 amplification assumed static/linear — breaks in tail events"

In the paper, the figure of **1.39** appears as the **VIXTWN-to-VIX level
ratio** (body.tex lines 16, 114, 120-121, 296, 318) and underpins the
calibration constant K = 12 / 1.39 = **8.63** in the 8.63/VIX
volatility-targeting strategy. The reviewer's concern is that the *single*
1.39 number assumes the ratio is **regime-invariant** — i.e., that VIXTWN
moves linearly with VIX at a constant slope. If this assumption breaks during
US vol shocks (e.g., Mar 2020 COVID, Feb 2018 vol-mageddon, 2008 GFC), then
K = 8.63 will systematically misallocate during precisely the periods VT
strategies most need to be correctly sized.

This experiment provides the regime-conditional decomposition the reviewer
requested.

## 2. Methodology

### 2.1 Data

| Series | Source | Period | n |
|---|---|---|---|
| VIXTWN | TAIFEX official Dropbox (K1098 canonical parse) | 2007-01-02 → 2021-12-30 | 3,701 raw / 3,327 paired |
| VIX    | Paper canonical snapshot (`paper/taiwan-vt/data/...vix..`) | 2008-01-02 → 2026-05-08 | inner-join on VIXTWN dates |

Note: VIXTWN data ends 2021-12-30 (K1098 official series). The paper's body
text reference to "VIXTWN/VIX ratio of 1.39" is computed from a 76-obs
recent window (Dec 2025 - Apr 2026, K1181), which we treat as an external
prior. The K1098 long-history series gives the **true regime-spanning
estimate** the reviewer demands.

### 2.2 Ratio definition

$$\text{ratio}_t = \frac{\text{VIXTWN}_t}{\text{VIX}_t}$$

Both observed at calendar date *t* (contemporaneous level relationship; this
is not a trading-strategy signal, so `signal.shift(1)` is not applicable —
the test asks whether *the level ratio itself* is regime-stable).

### 2.3 Expanding-window bucket assignment (no lookahead)

For each day *t* (with *t* ≥ 252 warmup), compute three quantile thresholds
$q_{25}(t)$, $q_{50}(t)$, $q_{75}(t)$ of the VIX series over $\{1, ..., t-1\}$
(strictly excluding *t*). Day *t* is assigned to one of:

* **Q1**: VIX_t ≤ q_{25}(t)
* **Q2**: q_{25} < VIX_t ≤ q_{50}
* **Q3**: q_{50} < VIX_t ≤ q_{75}
* **Q4**: VIX_t > q_{75}

A separate **Tail** flag is set when |Δlog(VIX_t)| > 2·σ_{t-1} where σ_{t-1}
is the expanding std of log-VIX changes through *t-1* (US-vol shock days;
overlaps Q3/Q4 by construction).

### 2.4 Stationary block bootstrap

We compute the bootstrap distribution of the bucket-conditional mean ratio
using Politis-Romano (1994) stationary block bootstrap with:

* B = 500 replications
* Mean block length L = 21 trading days (~1 month, geometric distribution)
* seed = 42 (global, fixed via `np.random.default_rng(42)`)
* Resampling: random circular blocks from the full paired series; bucket
  membership preserved from original indices (so bucket-conditional bootstrap
  respects the data-generating process; no naive iid resampling).

### 2.5 Verdict rule

* **linearity_HOLDS** if (a) every bucket mean is within ±10% of 1.39 *and*
  (b) every bucket's 95% bootstrap CI contains 1.39.
* **linearity_BREAKS** otherwise.

## 3. Results

### 3.1 Headline numbers (K1098 long-history sample, 2008-2021, n=3,075 post-warmup)

| Bucket | n | mean ratio | median | std | VIX mean | dev. from 1.39 | 95% CI | contains 1.39? |
|---|---:|---:|---:|---:|---:|---:|---|:-:|
| Overall   | 3,075 | 0.981 | 0.985 | 0.180 | — | -29.4% | [0.953, 1.009] | No |
| Q1 (low)  | 1,533 | 1.018 | 1.018 | 0.141 | 14.34 | -26.8% | [0.987, 1.046] | No |
| Q2        |   634 | 1.007 | 0.990 | 0.180 | 18.44 | -27.6% | [0.955, 1.054] | No |
| Q3        |   574 | 0.947 | 0.919 | 0.176 | 23.77 | -31.9% | [0.897, 0.995] | No |
| Q4 (high) |   334 | 0.824 | 0.824 | 0.133 | 33.63 | -40.7% | [0.785, 0.862] | No |
| **Tail**  |   183 | 0.877 | 0.877 | 0.202 | 23.95 | -36.9% | [0.832, 0.919] | No |

Source: `results.json::amplification_per_quantile` and `bootstrap_ci.per_bucket`.

### 3.2 KS 2-sample (Tail vs non-Tail)

D = 0.274, p ≈ 0.000 (n_tail = 183, n_nontail = 2,892). The ratio distribution
in tail-vol days is significantly different from the ratio distribution on
non-tail days — concretely, the ratio **falls** during US-vol shocks (mean
0.877 in Tail vs 0.999 in non-Tail), implying VIXTWN under-reacts in absolute
terms to US-vol spikes.

### 3.3 Verdict

`linearity_BREAKS`. The ratio exhibits a clear monotone decline in VIX
quantile: 1.018 → 1.007 → 0.947 → 0.824 (Q1 → Q4), a 19% relative drop.
The tail bucket also shows a ratio of 0.877, distinctly below the canonical
1.39. The long-history overall mean is **0.994** — substantially below the
1.39 figure cited in body.tex, which is computed from a 76-obs recent
window (Dec 2025 – Apr 2026, K1181).

## 4. Interpretation

Three things to be careful about:

1. **The reviewer is partly right and partly miscalibrated.** The 1.39 figure
   is not a long-run constant; it is a recent-period mean (K1181, n=76,
   Dec 2025 – Apr 2026). Over the K1098 long-history sample (2008-2021),
   the mean ratio is 0.981 (post-warmup, n=3,075). So "1.39 assumed static" is correct (it *is*
   static in body.tex), but the more accurate critique is that **the entire
   1.39 number is regime-dependent**, including its baseline level, not just
   its tail behavior.

2. **The 8.63/VIX strategy is largely robust to this.** As body.tex line 313
   notes, Sharpe(K·r) = Sharpe(r) — the calibration constant K only affects
   the *risk level* (and thus MDD), not the risk-adjusted return. The
   linearity break therefore matters for the *interpretation* of K, not the
   *Sharpe ranking*.

3. **The structural break in 2020-2021.** K1181 reports the recent ratio at
   1.39 (CV=10%) while K1098 reports the 2008-2021 ratio at 0.981 (CV≈18%).
   This implies a regime change. The paper should disclose this rather than
   reporting a single 1.39 figure with no caveat.

## 5. Recommended body changes (main-thread approval needed)

See `body_addition_proposal.tex`. Summary:

* Add a `\subsection` "Linearity Robustness of the VIX-to-VIXTWN Ratio" in
  §3 (data) or end of §4 (VT strategies), reporting the regime-conditional
  table.
* Add a footnote at body.tex line 120 disclosing the regime-conditional
  decomposition and clarifying that K = 8.63 is calibrated to the recent
  (post-2020) mean and may understate the appropriate K during 2008-2019
  episodes when the ratio averaged ≈0.98.
* Note that the **Sharpe** ranking of 8.63/VIX is invariant to K (line 313),
  so the substantive conclusion is unchanged; only the **MDD** target and
  the qualitative narrative around "Taiwan's structurally higher vol" need
  hedging language.

## 6. Reproducibility

```
uv run python experiments/paper2_R1_linear_scaling_fix/linear_scaling_check.py
# Writes: experiments/paper2_R1_linear_scaling_fix/results.json
```

Run-time: ~3 sec on M1. Deterministic given `seed=42`.

## 7. Lookahead audit

| Risk | Mitigation |
|---|---|
| Quantile threshold leakage | `expanding_quantile_threshold(x, q)` uses `x[:t]` (strictly excludes day *t*); first 252 obs dropped. |
| Tail filter leakage | `expanding_mean_std` accumulates cumulative sums and divides by `t` (mean over *0..t-1*, excludes day *t*). |
| Full-sample percentile contamination | Never computed; verified by grep — no `pd.qcut`, no `df['vix'].quantile()` outside warmup logic. |
| Bootstrap reproducibility | `np.random.default_rng(42)` set globally; geometric block lengths sampled from the same RNG. |

## 8. Codex review queue note

* Quota reset: 2026-05-13 02:46 UTC
* Review focus: (a) quantile partition lookahead safety, (b) stationary block
  bootstrap implementation correctness, (c) tail filter does not leak
  ex-post information.
* If Codex remains blocked, fallback to `feature-dev:code-reviewer` subagent
  per `.claude/rules/experiments.md`. Knowledge entry will note the reviewer
  source explicitly.

## 9. Cross-references

* `experiments/k1098/` — VIXTWN official TAIFEX 2007-2021 source
* `experiments/k1181/` — recent (2025-2026) VIXTWN/VIX ratio of 1.39 source
* `paper/taiwan-vt/body.tex` lines 16, 114, 120-121, 296, 318 — all "1.39"
  references requiring footnote or text revision
* `paper/taiwan-vt/gemini_review_v1.md` line 12 — SEVERE 2 source

## 10. Out of scope

* SEVERE 3 (endogeneity: Taiwan VT vs leveraged US tech / TSMC) — separate fix
* Optimisation of K via GARCH-MIDAS or grid (Gemini "Suggestions" §3) —
  belongs to a future revision round
