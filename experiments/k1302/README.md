# K1302: Paper 2 Individual γ JSON Rebuild — Table 2 source-data gap

[提出: Claude (autonomous backlog gap-scan from research_program.md L500 + memory `feedback_3spec_disambiguation`), 執行: TBD worktree agent]

## Motivation

Paper 2 (taiwan-vt) Table 2 reports individual-stock γ (asymmetry coefficient) for 5 Taiwan equities (Hon Hai 2317.TW, MediaTek 2454.TW, ELITE Material 2383.TW, plus 0056 dividend ETF, plus TSMC 2330.TW) under 3-spec disambiguation pattern (TWA / TWB / TWC) established by K1256.

Paper portfolio audit (research_program.md L500) currently lists P2 as "0 MISMATCH (6→0)" only because the 3 already-published values (TSMC / 0050.TW / TWII γ) have 3-spec footnotes + reproduce.py NOTE reclass. **The other 4 individual stocks (Hon Hai / MediaTek / ELITE Material / 0056) DO NOT have clean per-symbol per-spec JSON backing** — Table 2 values were carried over from earlier scratch scripts whose intermediate output was never canonicalized as `experiments/<k>/<k>_results.json`.

This is exactly the failure mode warned by memory `feedback_3spec_disambiguation`: any future cross-paper meta-eval or reproduce.py byte-match will fail on these rows because there's no `results.json` to hash. P2 cannot move from `🟡 0 MISMATCH (69% verified)` to `READY_FOR_SUBMISSION` until this is closed.

## Hypothesis

This is a **provenance experiment, not a research-hypothesis experiment**. Verdict is binary:

- **PASS**: all 4 stocks × 3 specs (TWA/TWB/TWC) × {γ, t-stat, p-value, n_obs} = 12 cells with explicit JSON backing, byte-match to Paper 2 Table 2 within tolerance ±0.001 on γ and ±0.05 on t-stat.
- **FAIL**: any cell drifts beyond tolerance → triggers Paper 2 erratum tier (K1256 3-spec footnote pattern + reproduce.py NOTE).

## Design

| Item | Setting |
| --- | --- |
| Stocks | 2317.TW (Hon Hai), 2454.TW (MediaTek), 2383.TW (ELITE Material), 0056.TW (高股息 ETF) |
| Specs | TWA = GJR-N w=2000, TWB = GJR-t w=2000, TWC = GJR-N w=1250 (K1256 canonical) |
| Sample | 2008-01-01 → 2024-12-31 (Paper 2 canonical window) |
| Estimator | scipy.optimize.minimize with 100+ multistart per (stock, spec) — see methodology §pooled-MLE rule |
| Outputs | k1302_individual_gamma.json with per-(stock,spec) {γ, se, t, p, n, ll, converged, multistart_log_likelihoods} |
| Reproduce | k1302_results.json hashed into `paper/taiwan-vt/reproduce.py` as 12 new MATCH checks |

## Lookahead discipline

- N/A — γ is in-sample MLE on full window, no forecast / OOS split.
- Multistart seeds: range(100), recorded in JSON for reproducibility.

## Differentiation vs prior K

- **K1256** established 3-spec disambiguation for TSMC / 0050.TW / TWII (already in Paper 2 with footnotes + JSON).
- **K1216 / K1216b / K1216c** ran developed-markets pooled-MLE with multistart — methodology proven, not yet applied to Taiwan individual stocks.
- **N129** (legacy, 7 Taiwan stocks) reported γ range 0.03-0.06 but is `legacy=true` with no canonical results.json — not citeable.

## Success criterion

- 12 cells (4 stocks × 3 specs) all reach convergence (`res.success=True`) on ≥1 of the 100 multistarts
- Best-LL multistart used for canonical γ; LL distribution recorded
- Paper 2 Table 2 byte-match to ±0.001 on γ / ±0.05 on t-stat
- Codex review PASS before knowledge.json entry

## Mission 5 sanity

Primary beneficiary: **Mission 3 (top-tier paper)**. P2 is the second top-tier candidate (P6/P5/P10 already READY); this closes its provenance blocker so submission is no longer gated on data quality. Secondary: Mission 2 (research integrity — eliminates a known "soft" row in canonical paper).

## References

- research_program.md L500 Paper Portfolio Status
- memory `feedback_3spec_disambiguation` (P1 K1256 + P2 γ pattern)
- K1256: `experiments/k1256/k1256_results.json` (3-spec template)
- methodology rule: pooled-MLE 100+ multistart (`.claude/rules/experiments.md` §Methodology)
