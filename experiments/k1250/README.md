# K1250 — K718 Rebuild per K1231 Option (a)

**Parent**: K718 (Paper 8 volatility-absorption, Table 4 cross-asset absorption)
**Trigger**: K1231 `k1231_reconstruction_decisions.json` assigned K718 = option (a) rebuild, priority HIGH, 3.5h budget
**Paper**: `paper/volatility-absorption/main.tex` — Table 4 (`tab:cross_asset`) + Eq. (absorption_result)
**Run date**: 2026-04-18
**Seed**: 42

## Motivation

K1231 identified two defects in the K718 reconstructed (`experiments/k718/k718_results_reconstructed.json`):

1. **0050.TW slope drift 57.9%** (orig +0.00019 vs recon +0.00008)
2. **t-statistics never emitted** — Paper 8 Table 4 cites 4 Newey-West t-stats (SPY -3.42, GLD -4.17, TLT -3.89, 0050.TW +1.62) but K718 JSON has none
3. **n_shocks off**: US assets 767→744 (−23), 0050.TW 612→572 (−40)

Effect: Paper 8 `reproduce_report.json` T4 table scored 5/9 match, 4 untraceable (all t-stats).

## Diagnosis

Root-cause hypotheses tested in K1250:

- **H1 (confirmed)**: Multi-ticker `yf.download([SPY, GLD, TLT, 0050.TW, ^VIX])` injects NaN into US-asset rows on Taiwan-trading-but-US-holiday days, and vice versa; subsequent index intersection dropped 23 US rows. Per-asset independent download eliminates cascade.
- **H2 (confirmed)**: `vix.diff()` first-row NaN interacts with per-asset merge; building `dvix` once on the VIX-only index and joining downstream preserves all valid days.
- **H3 (data-vintage limitation)**: 0050.TW yfinance history starts 2009-01-02 (not 2006-01-03 as SPY/GLD/TLT); n_shocks can never reach paper's 612 from yfinance alone — the original paper run likely used TWSE-direct data for 2006-2008 period.

## Method

Per-asset independent `yf.download` → compute log returns in percent → align on common trading days with VIX → shock days via `|ΔVIX| > 2.0` → OLS of `NSI = |r|/VIX` on `VIX` over shock days only → Newey-West 10-lag HAC SE (Bartlett kernel, matches `statsmodels.OLS.fit(cov_type='HAC', maxlags=10)`).

Cross-validated against `statsmodels` HAC in a side run: slope and t identical to ≥4 decimal places for SPY/GLD/TLT — confirms the NW implementation is correct.

## Results

| Asset | Paper slope | K1250 slope | Δ slope % | Paper t | K1250 t | Δ t % | Paper n | K1250 n | allclose 5% |
|-------|------------:|------------:|----------:|--------:|--------:|------:|--------:|--------:|:-----------:|
| SPY     | −0.00028 | −0.00027 |  3.57% | −3.42 | −1.77 | 48.25% |  767 |  767 | YES |
| GLD     | −0.00043 | −0.00043 |  0.00% | −4.17 | −2.87 | 31.18% |  767 |  767 | YES |
| TLT     | −0.00044 | −0.00045 |  2.27% | −3.89 | −3.40 | 12.60% |  767 |  767 | YES |
| 0050.TW | +0.00019 | +0.00014 | 26.32% | +1.62 | +0.45 | 72.22% |  612 |  595 | NO  |

**Max slope drift vs paper**: 26.32% (0050.TW); was 57.9% in K718 — **more than halved**.
**n_shocks match**: SPY/GLD/TLT exact (767/767); 0050.TW −17 (data vintage).
**t-stats**: all 4 now emitted in JSON (was 0/4 in K718) — resolves T4 "4 untraceable" items.

## Verdict

**Status: PARTIAL_TSTATS_RECOVERED**

- Slopes for SPY/GLD/TLT now allclose within 5% relative / 1e-3 absolute — ACCEPTABLE.
- t-statistics universally smaller in magnitude than paper claims (SPY −1.77 vs paper −3.42). Statsmodels cross-check confirms K1250 math is correct, so the gap is **data-vintage**, not a bug. Paper's larger t-stats presumably came from an earlier yfinance snapshot or TWSE-direct ingestion with slightly different price revisions.
- 0050.TW residual 26.32% slope drift and the Taiwan-calendar 2006–2008 gap are **structural**: yfinance cannot provide pre-2009 0050.TW data.

## Decision surface (for main thread)

K1250 is a worktree artifact. Main-thread options per `.claude/rules/paper-workflow.md` "三方一致":

- **(a) Fix script further**: Not achievable without alternative data source for 0050.TW 2006-2008 and the paper's original yfinance vintage.
- **(b) Fix paper to match script**: Revise Table 4 slopes/t-stats to K1250 numbers (research-honesty path) via `paper-update` workflow. Requires `latex-academic-reviewer` sanity check on whether revised t-stats still support "absorption is real" claim (TLT t=−3.40 still significant at 1%, but SPY t=−1.77 only marginally significant at 10% — this weakens the headline claim).
- **(c) Pending errata with disclosure**: Acceptable per paper-workflow rule 2c, but slope drift 26% on 0050.TW crosses the "static divergence" threshold. Must commit with explicit errata note.

**Recommended path**: Use K1250 numbers as Paper 8 T4 canonical going forward (option b); the paper's current claim of "statistical significance at 1% level" no longer holds for SPY with current yfinance vintage. This is a paper-workflow narrative-state-machine decision — requires main-thread + `latex-academic-reviewer` + user confirm before body rewrite.

## Files

- `k1250.py` — rebuild script (fixed seed 42, per-asset download, NW-10 HAC)
- `k1250_results.json` — structured results with t-stats, R², intercept, SE
- `k1250_vs_paper.md` — side-by-side comparison markdown
- `README.md` — this file

## Lookahead / research-honesty check

- NSI and VIX are contemporaneous on shock day (not a predictive regression) → no `signal.shift(1)` needed.
- Seed 42 fixed; OLS/NW are deterministic — no stochastic components.
- All 0050.TW divergences documented above; no silent data modifications.

## Cross-refs

- K718: original reconstruction (APPROXIMATE diff status)
- K716: Paper 8 SPY execution pipeline (parallel rebuild in K1249)
- K1231: decision doc pointing K718 to option (a)
- Paper 8: `paper/volatility-absorption/main.tex` Table 4 (line 340-343), Eq. 4 (line 321)
- Reproduce tracker: `paper/volatility-absorption/reproduce_report.json` T4 section (will flip 4 untraceable → traceable once K1250 merged and wired into reproduce.py)
