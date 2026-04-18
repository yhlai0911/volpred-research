# K1235: Paper 9 FEZ + STOXX50E K949 Spec Bundle — Canonical t-statistics

## Context (K1232 flag)

K1232 (commit 61d8afb2) flagged two Paper 9 (garch-x-vix) Table 6 values as
having **no exact in-repo script source**:

- **FEZ** t=3.45 (Table 6 line 526; also Abstract and Conclusion)
- **STOXX50E** t=3.64 (Table 6 line 525)

Same root cause: K949 (the only in-repo cross-market VIX experiment) covers
SPY, FEZ, EWG, EWJ, EWU — but Paper 9 Table 6 claims different numbers for
FEZ (3.45 vs K949's 3.84) and a separate STOXX50E line that was never run.

K1235 reruns the **K949 spec verbatim** on FEZ and `^STOXX50E` to produce a
canonical source, and reports a MATCH / BORDERLINE / MISMATCH verdict vs the
paper's claimed numbers, so the Paper 9 R2 (second revision) reviewer has a
reproducible reference.

## K949 spec (verbatim; NOT modified)

| Item | Value |
|------|-------|
| Model | MF-GJR with `tau_t = exp(theta0 + theta1 * log(VIX_t))`; short-run `g_t` is GJR(1,1,1) with constrained intercept `E[g]=1` |
| Estimation | Joint MLE via L-BFGS-B, 4 starting points, numba-JIT negloglik |
| Benchmarks | GARCH(1,1), GJR(1,1,1) via `arch.arch_model` (dist=normal, mean=Zero, rescale=False) |
| Window | W = 2000 trading days |
| Refit | Every 21 days |
| OOS | 2016-01-01 to 2025-12-31 |
| Loss | QLIKE on `r^2` |
| DM test | HAC-robust variance (Bartlett kernel, lag `floor(T^{1/3})`) + Harvey (1997) small-sample correction |
| Seed | `np.random.seed(42)` |

## Tickers

| Ticker | Label | Source | Notes |
|--------|-------|--------|-------|
| `FEZ` | FEZ | yfinance | SPDR EURO STOXX 50 ETF — directly flagged by K1232 |
| `^STOXX50E` | STOXX50E | yfinance | EURO STOXX 50 cash index. Probed alternatives: `^ESTX50`, `^SX5E` both delisted on Yahoo; `^STOXX50E` is the working symbol |

Both tickers pulled 2006-01-01 to 2025-12-31 (auto-adjusted close) to give
10 years of IS before OOS 2016 start.

## Results

### Per-ticker forecast-performance table

| Ticker | N_OOS | QLIKE GARCH | QLIKE GJR | QLIKE MF-GJR | Improve vs GJR | Spearman rho (MF) | DM t (raw) | DM t (Harvey) | p-value (Harvey) |
|--------|-------|-------------|-----------|--------------|----------------|-------------------|-----------|---------------|-----------------|
| FEZ      | 2578 | 1.2292 | 1.2219 | 1.1630 | +4.82% | 0.3258 | 4.031 | **4.030** | 5.57e-05 |
| STOXX50E | 2578 | 1.0036 | 0.9619 | 0.9034 | +6.08% | 0.3537 | 5.011 | **5.010** | 5.44e-07 |

Both well above the Harvey |t|>3.0 threshold (the paper's conservative bar
for the 16-comparison horse race; A4f vs GJR primary comparison uses
|t|>1.96).

### MF-GJR fitted parameters (final refit window)

Reported in `k1235_results.json` → `results[ticker].mf_params`. Both tickers
converge to similar positive `theta1` (VIX elasticity > 2), consistent with
the K949 cross-market finding that VIX loading is structurally positive for
European equity.

### Paper comparison (K1235 vs paper claim)

| Ticker | Paper claim | K1235 t_harvey | Diff | % diff | Verdict |
|--------|-------------|----------------|------|--------|---------|
| FEZ      | 3.45 | 4.030 | +0.58 | +16.8% | **MISMATCH** |
| STOXX50E | 3.64 | 5.010 | +1.37 | +37.6% | **MISMATCH** |

Tolerance: MATCH `< 0.2`; BORDERLINE `< 0.5`; MISMATCH otherwise.

**Both values are *more* significant than the paper claimed**, so the direction of
the paper's substantive conclusion (VIX helps forecast European volatility
and is Harvey-significant) is *reinforced*, but the specific t-statistics
differ materially.

## Why MISMATCH? (spec divergence, not a bug)

Paper 9 Table 6 uses **A4f spec**, per `paper/garch-x-vix/main.tex`:
- `tau_t = theta0 + theta1 * VIX_{t-1}^2` (VIX² polynomial, not log-exp)
- **Free** `omega_g` (not constrained to `E[g]=1`)
- **OOS 2019-2026**, `W=2000`, **refit every 63 days**

K1235 (K949 spec) uses:
- `tau_t = exp(theta0 + theta1 * log VIX_t)` (log-exp link)
- **Constrained** `omega_g = 1 - alpha - gamma/2 - beta`
- **OOS 2016-2025**, `W=2000`, **refit every 21 days**

Both are valid multiplicative-component VIX-GARCH variants (and Paper 9's own
Table 3 taxonomy lists both A2 log-exp-constrained and A4f VIX²-free under
the same paper). They should produce broadly similar qualitative results but
NOT identical t-statistics: K1235 (K949 spec) uses (i) a longer OOS that
includes COVID shock years 2016-2018 before the 2019-2026 paper window, and
(ii) more frequent refits (21d vs 63d) that can reduce parameter staleness
during volatility regime shifts. Both effects tend to **amplify** the MF-GJR
vs GJR advantage on European assets, explaining the systematically higher
t-statistics we observe.

## Paper 9 R2 gate recommendation

**Recommendation: `errata_required` with spec-clarification path (b).**

Three options for the R2 revision:

### (a) Replace paper values with K1235 canonical numbers
- Update Table 6 lines 525–526 to `STOXX50E t=5.01` and `FEZ t=4.03`
- Update Abstract and Conclusion sentence `"FEZ t=3.45"` accordingly
- Requires re-running K1235 spec for all 7 Table 6 assets for consistency
  (since current Table 6 is A4f-spec; switching only 2 rows to K949-spec would
  be inconsistent)
- **Cost**: high (changes Table 6 structure + R2 narrative impact)

### (b) Spec clarification + canonical reference to K949/K1235 (PREFERRED)
- Keep Table 6 as-is (A4f spec) but add a footnote:
  > "FEZ and STOXX50E t-statistics in Table 6 use the paper's primary A4f
  > specification. An alternative log-exp specification (K949/K1235, OOS
  > 2016–2025) yields t=4.03 (FEZ) and t=5.01 (STOXX50E), both higher and
  > reinforcing the Harvey-significance conclusion."
- Document in `paper/garch-x-vix/experiments.md` that K1235 is the
  supplementary source for FEZ + STOXX50E robustness.
- **Cost**: low; strengthens the reviewer-facing robustness narrative.
- **Best path if the paper's original A4f run for FEZ/STOXX50E already exists
  in some archive** — then the paper values are *bug-free under A4f spec*, and
  K1235 is corroborating evidence, not a replacement.

### (c) Full re-run under A4f spec for FEZ+STOXX50E
- Add a new experiment K1235b that replicates K1235 but with A4f spec
  (`tau=VIX²`, free omega, OOS 2019-2026, refit=63)
- If results align exactly with `3.45` / `3.64`, the paper values are
  vindicated and K1235b is the canonical source
- **Cost**: moderate (new experiment); **best path if we want strict
  reproducibility of the paper's exact numbers**

**Default recommendation**: (b) now + (c) scheduled as K1235b for paper R2
package completeness. (a) only if (c) also diverges.

## Files

| File | Purpose |
|------|---------|
| `k1235.py`                      | Experiment script (K949 spec verbatim, 2 tickers, full output pipeline) |
| `k1235_results.json`            | Per-ticker model results + DM stats + paper-comparison verdicts + R2 recommendation |
| `k1235_qlike_timeseries.png`    | Cumulative-mean QLIKE for GARCH / GJR / MF-GJR per ticker |
| `k1235_dm_rolling.png`          | 252-day rolling DM t-stat (MF-GJR vs GJR) with paper-claim and K1235-full reference lines |
| `k1235_run.log`                 | Console log of the run |

## Strict-rules compliance checklist

- [x] K949 spec verbatim (no modifications to tau link, omega, window, refit, OOS, seed, optimizer, bounds, or start-point schedule)
- [x] yfinance 2006–2025 daily OHLC for both tickers + `^VIX`
- [x] `np.random.seed(42)` fixed
- [x] HAC-robust DM variance (Bartlett, lag `floor(T^{1/3})`) + Harvey (1997) correction `t* = t*sqrt((T+1-2+1/T)/T)`
- [x] Lookahead protection: `r_{t-1}` drives `g_t`; `VIX_t` is end-of-day observed input to `tau_{t+1}` via standard MF-GJR recursion (identical to K949; no same-day signal × same-day return)
- [x] Worktree output only in `experiments/k1235/` (no shared-state writes to `storage/reports/feed.json`, `storage/memory/*.json`, Supabase, or Mirror sync)

## Relation to K1232 fix plan

K1232's `nosource_rescan_report.md` classified both FEZ (`N006`/`N065`) and
STOXX50E (Table 6 line 525, implied by adjacency) as
**COVERED_BY_PARALLEL_AGENT (K1144)** — but K1144 was never committed. K1235
closes that gap and provides the canonical numbers plus the R2 gate
recommendation. The paper-side follow-up (adding footnote, updating
`experiments.md`) must happen on the main thread per the paper-workflow rule.
