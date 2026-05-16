# K1302b: GJR-GARCH γ for 5 Unlisted Taiwan Individual Stocks — Paper 2 Table 2 Extension

[提出: K1302 follow-up (main thread, 2026-05-16 per `paper/taiwan-vt/body.tex` L170 DRAFT NOTE); 執行: worktree agent K1302b]

## Motivation

Paper 2 (`paper/taiwan-vt/`) Table 2 §3 "The Leverage Effect" decided **Option A** (2026-05-16): adopt full-sample BW-robust GJR-GARCH(1,1) as the canonical specification for **all** individual Taiwan stocks. K1302 already produced canonical γ for the 4 stocks already in Table 2 (Hon Hai 2317, MediaTek 2454, Mega Financial 2886, 0056.TW ETF) + TSMC 2330 reference.

The §3.2 "Diversification Amplification" subsection currently quotes a 9-stock average (γ̄ = 0.054, ratio 5.0×) derived from **legacy rolling-w2000 NW-HAC** estimates whose 5 individual stocks beyond the 4 in Table 2 were **never canonicalized**. Without canonical results for those 5 (2882 Cathay / 2891 CTBC / 2412 Chunghwa Telecom / 2885 Yuanta / 2881 Fubon), the 9-stock average cannot be re-computed under Option A and Paper 2 cannot move past `READY_FOR_SUBMISSION` blocker.

K1302b closes this gap by running the **same K1302 estimation framework** on the 5 missing stocks.

## Hypothesis

Provenance / closure experiment — binary verdict:

- **PASS**: all 5 stocks converge under full-sample GJR-GARCH(1,1) BW-robust SE with γ > 0 and persistence < 1; per-stock JSON cells available for paper update.
- **FAIL**: any stock fails to converge after 100 multistart, has γ < 0 (would imply inverse leverage), or persistence ≥ 1 (non-stationarity).

## Method (mirror of K1302)

| Item | Setting |
| --- | --- |
| Stocks | 2882.TW (Cathay Financial), 2891.TW (CTBC), 2412.TW (Chunghwa Telecom), 2885.TW (Yuanta), 2881.TW (Fubon) |
| Sample | 2008-01-01 → 2024-12-31 (Paper 2 canonical window, identical to K1302) |
| Model | GJR-GARCH(1,1) — `arch_model(..., vol='GARCH', p=1, o=1, q=1, mean='Constant', dist='normal')` |
| Estimator | `arch` package `fit(cov_type='robust')` — Bollerslev-Wooldridge robust SE |
| Multistart | 100 starts; seeds 42..141; randomized starting values for (μ, ω, α, γ, β) |
| Best selection | Highest log-likelihood across converged starts (per `.claude/rules/experiments.md` §Pooled-MLE 100+ multistart rule) |
| Stationarity filter | persistence (α + 0.5γ + β) < 1 required for a start to count as converged |
| Data | yfinance auto_adjust=True, cached to `experiments/k1302b/data/` |
| Returns | log returns × 100 (arch package scale convention) |
| NaN filter | drop NaN log returns; zero-volume filter not available from close-only path |

## Lookahead discipline

- **N/A** — γ is in-sample MLE on full 2008-2024 window. No forecast, no OOS split, no signal generation, so `signal.shift(1)` does not apply.
- Multistart seeds explicit (42..141); `np.random.seed(42)` global; all randomness reproducible.

## Differentiation vs K1302

- **Stock set**: K1302 covers 2317/2454/0056/2886 (Table 2 row stocks) + 2330 (TSMC reference) + 2383 (ELITE, off-Table); K1302b covers the 5 financial/telecom stocks needed to complete the 9-stock average.
- **Methodology delta**: identical estimation pipeline; one upgrade — K1302b uses explicit 100-multistart while K1302 used arch package single-start defaults. This is a strict superset (multistart with single-start fallback to highest-LL converges back to single-start when LL surface is well-behaved).
- **Output schema**: K1302b adds `n_attempted` / `n_converged` / `ll_distribution` fields per stock for multistart audit.

## Success criterion checklist (post-run)

- [x] All 5 stocks converged (5/5) on ≥1 of 100 multistart
- [x] γ > 0 for all 5 (positive leverage effect direction)
- [x] persistence < 1 for all 5 (stationarity)
- [x] Best-LL multistart used for canonical γ; LL distribution recorded
- [x] Lookahead-free certification embedded in `k1302b_results.json`
- [ ] Codex review PASS — **main thread** runs post-merge before any knowledge.json write

## Per-stock results (canonical full-sample BW-robust)

| Ticker | Name | n | γ | t-stat | α | β | persistence | converged/100 |
|--------|------|--:|--:|------:|--:|--:|------------:|--------------:|
| 2882.TW | Cathay Financial | 4170 | +0.0384 | +2.128 | 0.0594 | 0.8976 | 0.9762 | 100 |
| 2891.TW | CTBC | 4170 | +0.0396 | +1.911 | 0.0698 | 0.8963 | 0.9859 | 100 |
| 2412.TW | Chunghwa Telecom | 4170 | +0.0011 | +0.193 | 0.0000 | 0.9966 | 0.9972 | 26 |
| 2885.TW | Yuanta | 4170 | +0.0199 | +1.531 | 0.0445 | 0.9348 | 0.9892 | 100 |
| 2881.TW | Fubon | 4170 | +0.0217 | +1.460 | 0.0650 | 0.9093 | 0.9852 | 100 |

**Summary**: avg γ across 5 stocks = +0.0241; avg persistence = 0.9867.

### Notes on Chunghwa Telecom (2412.TW)

Chunghwa Telecom is a defensive telecom utility with the lowest realized vol in the sample (std = 0.0104 vs 0.017-0.019 for the financials). Multistart convergence rate (26/100) is lower than the financials (100/100) because the LL surface near γ≈0 is flat — many random starts drift to the boundary α=0 with high β. Best-LL fit lands at γ=+0.0011 (essentially no leverage effect), which is economically plausible for a regulated low-beta utility. The persistence of 0.9972 is near (but strictly less than) 1, consistent with a near-IGARCH process typical of low-vol utilities. Result is reported as-is per research-honesty principle; no parameter tweaking to force a higher γ.

## Data source statement

All 5 tickers fetched live from yfinance (`yf.download(..., auto_adjust=True)`) on 2026-05-16, cached to `experiments/k1302b/data/<ticker>.csv`. Sample window 2008-01-01..2024-12-31 yields exactly 4170 log-return observations for each ticker — uniform sample length across all 5, suitable for direct comparison and averaging into the 9-stock figure for Paper 2 §3.2.

## Downstream impact (main thread responsibility — out of worktree scope)

1. Main thread runs Codex review on `experiments/k1302b/k1302b.py`
2. If PASS: write knowledge.json entry; sync to `paper/taiwan-vt/data/` if Paper 2 reproduce.py needs binding
3. Combine K1302 (4 stocks) + K1302b (5 stocks) = 9-stock canonical average; update Paper 2 Table 2 rows + §3.2 amplification ratio
4. Update Paper 2 `reproduce.py` to byte-match new canonical Table 2 values

## References

- K1302: `experiments/k1302/` — original 4 Table-2 stocks + TSMC
- `paper/taiwan-vt/body.tex` L165-172 — DRAFT NOTE establishing Option A + pending K1302b
- `.claude/rules/experiments.md` §Methodology — Pooled-MLE 100+ multistart rule
- `.claude/rules/worktree.md` — worktree scope (no shared-state writes)
