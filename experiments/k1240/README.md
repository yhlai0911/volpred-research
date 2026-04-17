# K1240 — Paper 10 §5 Data Description + §6 Main Results Skeleton

**Paper**: Paper 10 — The Crypto Fear Channel: Asymmetric BTC–Equity Volatility Spillover
**Parent task**: K1234 kickoff writing sequence (§3 → §4 → §5 → §6 → …)
**Predecessors**: K1238 (§3 Data), K1239 (§4 Methodology)
**Successor (required)**: K1241 (fear-channel GARCH-X estimation, TBD)
**Status**: §5 draft complete; §6 skeleton with pending-experiment flags
**Date**: 2026-04-17
**Agent**: worktree agent-aa4b5296
**Seed**: 42

## Purpose

K1240 advances the Paper 10 drafting sequence by producing:

1. **§5 Data Description** — a ~400-word, complete descriptive-statistics draft whose numbers are sourced verbatim from `experiments/k1025/k1025_results.json`. Covers summary statistics (§5.1), correlation patterns including DCC regime breakdown (§5.2), and stationarity / autocorrelation diagnostics (§5.3).
2. **§6 Main Results Skeleton** — a ~600-word 4-subsection skeleton covering the primary fear-channel finding (§6.1), alternative fear proxies (§6.2), pre- and post-ETF regime split (§6.3), and Granger-causality direction (§6.4). All results cells that depend on the unexecuted K1241 fear-channel GARCH-X estimation are explicitly marked **[PENDING EXPERIMENT — K1241]** and **TBD**; no numbers are fabricated.

## Files

| File | Description |
|------|-------------|
| `README.md` | This document |
| `k1240_s5_s6_draft.md` | Markdown drafts of §5 (complete) and §6 (skeleton with TBD cells) |
| `k1240_outline.json` | Structured outline: word counts, subsections, table placeholders, K-source mapping, pending-experiment flags |

## Supporting K-sources (verified exist)

- `experiments/k1025/k1025_results.json` — full framework (asymmetric Granger + QR + DY + DCC + subperiod + DM); descriptive statistics canonical source
- `experiments/k746b/k746b_bitcoin_vix_fixed_results.json` — asymmetric Granger BTC$^{-}$ $\to$ VIX
- `experiments/k639/` — BTC $\to$ SPY RV Granger (sample start 2015-02 confirmation)
- K949 (via `storage/memory/knowledge.json`) — cross-market MF-GJR(VIX) precedent, $\theta_1 \approx 2.1$
- K1133b (via `storage/memory/knowledge.json`) — structural-break / ETF-era precedent motivating §6.3

## Pending experiments (main-thread action required)

1. **K1241 — Fear-channel GARCH-X regression** *(critical, blocks §6 numerical population)*:
   - Estimate MF-GJR(1,1,1)-X with Student-$t$ innovations on BTC-USD daily log returns, using VIX$^2$ lag 1 as the fear regressor.
   - Baseline specs: GARCH(1,1), GJR-GARCH(1,1,1), GARCH(1,1)-X(VIX$^2$).
   - Report $\hat{\phi}$, Bollerslev-Wooldridge SE, Harvey-adjusted $t$-statistic, LRT vs. GJR, Patton QLIKE (in-sample and OOS).
   - Alternative fear-proxy robustness: VIX level, $\log(\text{VIX})$, CFIX (Table 4).
   - Sub-sample split: pre-ETF 2015-02-02 to 2023-12-31, post-ETF 2024-01-01 to 2026-04-08 (Table 5).
   - Seed 42; lookahead discipline via `signal.shift(1)` on all fear regressors.
   - Expected runtime: ~0.5 day on a single worktree agent (no new data download; reuse K1025 data pull or equivalent `yfinance` cache).

2. **Figure 1 (Granger-causality flow diagram)** *(non-critical, can be built from K1025 JSON)*:
   - Three-node diagram (VIX, BTC-RV20, SPY-RV20) with directional edges labelled with $F$-statistics at lag 5.
   - Edge (BTC$^{-}$ $\to$ VIX) annotated separately to visualise asymmetry.
   - Can be produced as a utility/visualization script output rather than a numbered K experiment.

## Main-thread adoption checklist

- [ ] Review §5 wording and table-2 layout; decide whether to keep Ljung-Box / Jarque-Bera in body or push to Online Appendix.
- [ ] Commission K1241 (GARCH-X fear-channel) worktree agent.
- [ ] After K1241 completes, populate §6.1–§6.3 numerical cells (four tables' TBD cells).
- [ ] Produce Figure 1 from K1025 JSON.
- [ ] Decide §4/§6 sub-ordering: does the GARCH-X block sit at §4.1 / §6.1, or later?
- [ ] Transcribe §5 + §6 into `paper/crypto-fear-channel/body.tex` only after K1241 numbers land (per CLAUDE.md narrative state-machine rule — single experiment must not trigger body rewrites; §5 alone is safe to transcribe once K1238/K1239 are also in).
- [ ] Cross-check: `reproduce.py` produces the §5 Table 2 numbers verbatim from the K1025 JSON chain.

## Compliance notes

- **Research-honesty principle 1 (不可造假)**: no §6 fear-channel $\hat{\phi}$ value is fabricated or estimated from a non-run model. All TBD cells are explicitly marked.
- **Research-honesty principle 9 (Null result 如實報告)**: §6.1 opening lines warn readers that in-sample causality does not imply out-of-sample forecastability; §7 (future draft) will report the K1025 honest NULL ($t = -0.98$).
- **Research-honesty principle 11 (Lookahead bias)**: all §5 and §6 specifications inherit the `signal.shift(1)` discipline established in K1238 §3.2 and K1239 §4.1.
- **Worktree rule**: K1240 only produced files under `experiments/k1240/`; no shared-state writes to `storage/memory/` or `storage/reports/`.
- **Paper narrative state-machine rule**: K1240 does not modify `paper/crypto-fear-channel/body.tex`; produces `.md` draft for main-thread transcription only.
