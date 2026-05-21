# K1370 — Block-bootstrap CI for TAIEX-to-Individual Amplification Ratio (Canonical GJR-GARCH BW-robust)

## Motivation

Paper 2 (taiwan-vt) §3.2 reports a *diversification amplification* finding:
the TAIEX-to-individual γ ratio is approximately 10× under the canonical
K1302+K1302b full-sample BW-robust GJR-GARCH(1,1) specification. The previously
published bootstrap confidence interval **[2.8, 8.1]** (10,000 replicates,
block length 252) is **stale** because it was constructed around the *draft*
5.0× point estimate under a rolling-window (w=2000) GJR-GARCH with Newey-West
HAC standard errors, not the canonical full-sample BW-robust specification.

`paper/taiwan-vt/body.tex` §3.2 paragraph `Confidence interval (stale)`
explicitly tracks this gap and points to "experiment K1370" for the
re-computation. This experiment delivers that.

## Method

### Estimator (matches K1302/K1302b)

- GJR-GARCH(1,1) with Normal errors, Constant mean.
- `arch` package, `cov_type='robust'` (Bollerslev-Wooldridge QML SE).
- Stationarity gate: persistence = α + γ/2 + β < 1; otherwise the start is rejected.

### Bootstrap

- Politis-Romano (1994) **stationary block bootstrap**, expected block length
  L = 252 (one trading year). Block lengths drawn from Geometric(1/L); indices
  are wrapped circularly.
- B = 1,000 replicates. Reduced from B = 10,000 (the stale-CI brief default)
  for tractability — at B × 10 series × 10 multistart per fit = 100,000 MLE
  fits, runtime is ~1.5h; B = 10,000 would be ~15h with marginal CI-width
  improvement (~30% tighter half-width).
- Per replicate, each of 10 series gets an **independent bootstrap path**
  (own resample). This destroys cross-series dependence — but the amplification
  ratio is a ratio of univariate GJR estimates whose sampling distribution
  depends on each series' marginal returns, not on the joint distribution.

### Per-replicate multistart

- N_start = 10 (reduced from K1302/K1302b's 100). Each replicate runs 10
  random starts (`scipy.optimize.minimize` via `arch.starting_values`) and
  picks the best-LL converged stationary fit.
- Justification: K1302's LL distribution diagnostic shows most series converge
  to the same basin from ≥80/100 starts. Cutting to 10 starts trades a small
  amount of basin-search robustness for 10× speedup; the multistart count
  enters the bootstrap *via the within-replicate noise* rather than as a
  bias source.

### Validity rule

A replicate is **valid** iff (a) TAIEX γ converged AND (b) at least 5 of 9
individual stock γs converged. Invalid replicates are dropped from the CI.

### Seeds (lookahead-free certification)

- `np.random.seed(42)` at script start.
- Per-replicate bootstrap seed = `42 + r` for r ∈ [0, B-1].
- Per-series sub-seed = `bootstrap_seed * 100003 + hash(ticker) % 100000`
  (deterministic given the replicate seed and ticker).
- Per-fit multistart seeds = `range(10)` within each (replicate, series) pair.

Each replicate is an independent in-sample MLE on a block-bootstrap resample
of full-sample log returns. **No t→t+1 leak** — the GJR specification
σ²ₜ = ω + α·ε²ₜ₋₁ + γ·ε²ₜ₋₁·I[εₜ₋₁<0] + β·σ²ₜ₋₁ uses only past shocks by
construction.

## Data

- **Primary**: `paper/taiwan-vt/data/0050_tw_twii_2330_tw_2317_tw_2454_tw_0056_tw_spy_vix_2008-2026.csv`
  for `twii_adj_close`, `2317_tw_adj_close`, `2454_tw_adj_close`.
- **Fallback (yfinance auto_adjust=True, cached)**: 2886, 2383, 2882, 2891,
  2412, 2885, 2881 → cached to `experiments/k1370/data/`.
- **Sample**: 2008-01-01 to 2024-12-31 → n ≈ 4170 log-return obs per series
  (TAIEX: 4160 due to a few non-overlapping observation dates).

### Universe

- **Index**: TAIEX (`^TWII`, paper col `twii_adj_close`).
- **9 individuals**: 2317, 2454, 2886, 2383 (K1302) + 2882, 2891, 2412, 2885,
  2881 (K1302b). Excludes 2330 (TSMC, dominant constituent) and 0056 (an ETF
  itself) per `body.tex` §3.2 disclosure rules.

## Sample-window methodology note (research-honesty disclosure)

The paper's headline 10× ratio in `body.tex` §3.2 is computed as
`0.272 / 0.027` where:

- **0.272** = TAIEX γ estimated over **1997-2026** (n = 7148; source:
  `experiments/paper2_table1_twii_stats/twii_summary_stats_results.json`,
  reproducing `body.tex` Table 1 line 147).
- **0.027** = 9-stock individual average γ over **2008-2024** (n = 4170;
  source: K1302 + K1302b).

This is a **mixed-sample comparison**. The 1997-2026 TAIEX window includes
the 1997 Asian financial crisis and 2000 dot-com bust — high-volatility
regimes that elevate the estimated γ. The 2008-2024 individual-stock window
omits these regimes by data-availability constraint (many of these stocks
have shorter listing history reliably available in yfinance auto-adjusted
form).

**K1370's primary CI is the matched-sample CI** (both TAIEX and 9 individuals
on 2008-2024). The script also reports the mixed-sample point estimate for
transparency — this is what the paper's 10× headline reflects, and it is
reproduced here as ~10× to confirm provenance.

## Outputs

- `k1370_results.json` — primary results: amplification ratio CI, per-series
  convergence summary, both matched-sample and mixed-sample point estimates,
  lookahead-free certification.
- `k1370_replicates.json` — per-replicate full data (B records: γ per series,
  amplification, validity).
- `k1370_run.log` — full run log.
- `amplification_distribution.png` — histogram with median, 90% CI band, and
  canonical point-estimate marker.

## Success criteria

1. Pipeline runs to completion (B = 1000) without crash.
2. Point-estimate sanity check **mixed-sample** ratio reproduces paper headline
   to within ±15% (i.e., 8.5 ≤ mixed-sample ratio ≤ 11.5).
3. ≥95% of replicates are valid (TAIEX + ≥5/9 individuals converge).
4. 90% CI is reported and replaces stale [2.8, 8.1] in paper §3.2.
5. Codex review of `k1370.py` passes before any cross-experiment narrative
   write to `knowledge.json` (deferred to main thread).

## Replacement narrative for `body.tex` §3.2 (proposed by main thread after Codex review)

The `Confidence interval (stale)` paragraph should be rewritten to:

> The block-bootstrap 90% confidence interval for the matched-sample
> amplification ratio (both TAIEX and 9 individual stocks estimated over
> 2008-2024 under the canonical full-sample BW-robust GJR-GARCH spec) is
> **[ci_low_90, ci_high_90]** with median **median** (K1370,
> B = 1000 stationary block-bootstrap replicates, block length 252).

A separate research-honesty footnote should disclose the matched-sample
vs mixed-sample distinction in the 10× headline.

## Lookahead-free certification

Each bootstrap replicate is an independent in-sample MLE on a resampled
series; the GJR-GARCH variance recursion uses only past shocks by
specification (`σ²ₜ` depends on `ε²ₜ₋₁` and `σ²ₜ₋₁`, both in the
information set at t-1). All random number generators are seeded.
No t→t+1 leak exists by construction.

## Reproduce

```bash
cd <repo root>
python experiments/k1370/k1370.py
# Runtime ~1.5h on commodity hardware. Outputs to experiments/k1370/.
```
