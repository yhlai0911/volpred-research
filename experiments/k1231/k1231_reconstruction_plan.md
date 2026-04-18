# Paper 8 (volatility-absorption) K716–K722 Reconstruction Plan

**Author**: K1231 (planning agent, worktree)
**Date**: 2026-04-17
**Input**: K1229 audit (Paper 8 P2 BLOCKER), reproduce_report.json (50.7%), filesystem reads
**Output**: Per-experiment (a/b/c) decision matrix for main-thread approval
**Reference**: `docs/paper-guide.md` 三方一致 rule

---

## Summary

- **Paper 8 status**: DRAFT (R1 review, 5 SEVERE, major revision in flight)
- **`reproduce_report.json` traceability**: 50.7% (38 / 75), 29 untraceable, 8 mismatch
- **K1229 claim**: "No .py scripts for K716, K718, K719, K720, K721, K722" — **now
  obsolete** (all 7 scripts exist as "RECONSTRUCTED" files dated 2026-04-17).
- **Real residual problem**: reconstructed scripts **do not** allclose the original
  `kNNN_results.json` files; per `docs/paper-guide.md` §三方一致 rule 4, any
  divergent reconstruction must be resolved via (a) / (b) / (c) — not silently
  committed.
- This K1231 document converts each diff report into a (a/b/c) recommendation.

### Reproduce-report tables and their owning K

| Table | Owner K | Reproduce status | Likely root cause |
|-------|---------|------------------|-------------------|
| T3    | K716    | 21/21 match       | Well-defined 5-bin SAR  |
| T4    | K718    | 5/9 match, 4 untrace | t-stats not stored in JSON |
| T5    | K721    | 3/9 match, 3 mismatch, 3 untrace | Shock filters differ; N off by 4–8 |
| T6    | K741    | 6/11 match, 5 mismatch | NFP window; K1231 does **not** address (K741 in paper folder) |
| T7    | K720    | 1/4 match, 3 untrace | VRP summary % not in JSON |
| T8    | K722    | 0/3 match, 3 untrace | CB ratio not in JSON |
| T9    | none    | 0/5 untrace | tau-threshold robustness (K903 territory) |
| T10   | none    | 0/3 untrace | Sub-period robustness (K903/K904 territory) |

---

## Per-Experiment Analysis

### K716 — SAR by VIX Regime (Table 3, SPY pilot)

- **Folder**: `experiments/k716/` — contains `k716.py` (340 lines, RECONSTRUCTED header),
  `k716_results.json` (original), `k716_results_reconstructed.json`, `k716_reconstruction_diff.md`.
- **Knowledge entry**: K716 `★★★ Panic Paralysis CONFIRMED — normalized shock impact
  decreases with VIX`. SPY normalized slope −0.00028, ratio calm 3.16× → high 2.32×.
- **Paper body reference**: main_v2.tex Table 3 cites the exact original ratios
  (3.16 / 2.77 / 2.37 / 2.32 / 2.43) and slope = −0.00028. reproduce_report T3 = 21/21 match.
- **Diff report status**: 5-bin SAR table **all 20 cells YES** (diff ≤ 0.02).
  Scalar divergences: `regression_raw_slope` 0.0669 → 0.0677 (diff 0.0008, ≈1.2%);
  `regression_normalized_slope` −0.00028 → −0.00027 (diff 1e-5, ≈3.6%).
- **Missing elements**: None structural. Reconstruction ≈ matches; sub-percent drift only.
- **Paper body numbers (verbatim)**: slope = −0.00028 (Table 3 text).
- **Decision options**:
  - **(a) rebuild script**: Tighten end-date and trading-calendar alignment so
    `-0.00027` → `-0.00028`. Effort: ~1 h (verify yfinance end date = paper data cutoff).
  - **(b) revise paper**: Replace `-0.00028` with `-0.00027` throughout. Effort:
    1 line edit. But Table 3 ratios already match at 2-decimal precision, so only
    the narrative slope number changes.
  - **(c) errata**: "slope −0.00028 vs reconstructed −0.00027 (3.6% drift, yfinance
    revision); Table 3 ratios verified". Effort: 1 note in README.
- **Recommendation**: **(a)** — scalar slope drift is within rounding of 2-decimal
  ratios and likely reflects a small data-vintage drift; one pass aligning the end
  date of the SPY/VIX download should close the gap and preserve the paper verbatim.

---

### K717 — Multi-Strategy VT Scorecard

- **Folder**: `experiments/k717/` — `k717.py` (271 lines, RECONSTRUCTED), 4/14
  strategies covered in reconstruction.
- **Knowledge entry**: K717 `★★★ Multi-Dimensional Evaluation — Taiwan Momentum #1
  composite`. 14 strategies, composite-ranked.
- **Paper body reference**: main_v2.tex Section 6 cites Taiwan Momentum, adaptive,
  piecewise, 12/VIX, simple_12vix only as qualitative support — **no table
  dedicated to K717** in the main body. Not in reproduce_report table list.
- **Diff report status**: 4 strategies reconstructed (recommended_5050, risk_parity,
  simple_12vix, slow_vt); 10 strategies **missing** (adaptive_tier, fear_dca,
  global_vt_tz, piecewise_conservative, taiwan_8.63vix, taiwan_hybrid_leverage,
  taiwan_spy_momentum, tz_tw_jp_5050, vix_cond_leverage, vix_leading_guard).
  CAGR / Sharpe divergence ≈ 0.4–6.5 on reconstructed strategies.
- **Missing elements**: 10 strategy specs need to be recovered from K649 / K658 /
  K661 upstream experiments + the original bespoke code that produced
  `k717_results.json`.
- **Paper body numbers (verbatim)**: Taiwan momentum ~32.6% CAGR referenced in
  knowledge (not in main_v2.tex). No Table cites K717 verbatim.
- **Decision options**:
  - **(a) rebuild script**: Reverse-engineer 10 strategy specs from upstream K and
    diff vs original JSON. Effort: 6–10 h, high risk of further divergence.
  - **(b) revise paper**: Tighten Section 6 to only cite the 4 reconstructable
    strategies + drop qualitative claims about the uncovered 10. Effort: 1 h.
  - **(c) errata**: "K717 supports Section 6 qualitatively; 4/14 strategies
    verified, 10/14 pending; Section 6 claim relies on verified subset". Effort: 15 min.
- **Recommendation**: **(c)** — K717 is **not** cited in any reproduce_report Table,
  and Section 6 uses it only as illustrative support. Pending-errata note +
  commit is the cheapest honest path; full rebuild would consume ~1 day for zero
  impact on paper's core claims (SAR, NSI regression, cross-asset, shock-type).

---

### K718 — Cross-Asset Absorption (Table 4)

- **Folder**: `experiments/k718/` — `k718.py` (303 lines, RECONSTRUCTED).
- **Knowledge entry**: K718 `★★ Panic Paralysis Cross-Asset — 3/4 assets confirm
  (SPY strongest, 0050 exception)`. Normalized slopes: SPY −0.00028, GLD −0.00043,
  TLT −0.00044, 0050 +0.00019.
- **Paper body reference**: Table 4 reports these slopes verbatim and t-stats
  −3.42 / −4.17 / −3.89 / 1.62. reproduce_report T4 = 5/9 match, 4 untraceable
  (all t-stats — **not stored** in k718_results.json).
- **Diff report status**: GLD slope −0.00043 **exact match**; SPY −0.00028 vs
  −0.00027 (3.6% drift); TLT −0.00044 vs −0.00041 (6.8% drift); 0050 +0.00019
  vs +0.00008 (57.9% drift, **large**). Shock-day counts off by 23 (SPY/GLD/TLT)
  and 40 (0050). Intermediate ratios diverge up to 0.14 on 0050 calm bucket.
- **Missing elements**: t-stats not stored (4 untraceable in reproduce_report);
  0050.TW calendar alignment likely off.
- **Paper body numbers (verbatim)**: −0.00028 / −0.00043 / −0.00044 / +0.00019;
  t = −3.42 / −4.17 / −3.89 / +1.62.
- **Decision options**:
  - **(a) rebuild script**: Fix end-date + 0050.TW trading calendar; emit t-stats
    from the same Newey-West config the paper implies. Effort: 3–4 h. Primary
    concern is 0050.TW 57.9% drift — needs investigation whether data revision
    or calendar alignment explains it.
  - **(b) revise paper**: Accept reconstructed values (−0.00027 / −0.00043 /
    −0.00041 / +0.00008) and also recompute t-stats. Effort: 1–2 h.
  - **(c) errata**: "slopes within 7% for US assets; 0050.TW diverges 57.9% due
    to trading-calendar revision". Effort: 30 min — **but** 57.9% drift on 0050
    exceeds the "magnitude <X%" disclosure threshold that keeps the paper honest.
- **Recommendation**: **(a)** — Table 4 is a **central evidence table**; drift on
  0050.TW cannot be absorbed as errata. Must align calendars and emit t-stats so
  T4 reaches 9/9 reproduce. Upside: will likely fix k716 slope drift (same
  pipeline). Priority: **HIGH**.

---

### K719 — Synthesis / Implications Document

- **Folder**: `experiments/k719/` — `k719.py` (169 lines, RECONSTRUCTED). This
  is qualitative synthesis.
- **Knowledge entry**: K719 `⚠️ VRP sign flip PARTIALLY WRONG` — 5 implications,
  VRP narrows but stays positive with rolling RV22. **K720 already corrected the
  VRP sign claim**.
- **Paper body reference**: Paper 8 Table 5 (per experiments.md) was originally
  mapped to K719 NFP event study, but the knowledge entry shows K719 is a
  synthesis/implications doc, not NFP. `experiments.md` actually maps Table 5 →
  K719/K741 — likely a relabeling. reproduce_report T8 (hedging CB) listed
  `exp="K719 (not in JSON)"` — the 13.7× / 8.0× / 3.6× values appear in the
  implications but not in a structured JSON.
- **Diff report status**: 5/5 implications match, 5/5 experiments_cited match. No
  numerical allclose possible.
- **Missing elements**: No structured JSON with 13.7× / 8.0× / 3.6× CB ratios.
- **Paper body numbers (verbatim)**: Table 8 calm CB = 13.7×, elevated = 8.0×,
  high = 3.6× (reproduce_report T8 says these sit in K719-not-in-JSON).
- **Decision options**:
  - **(a) rebuild script**: Compute CB ratios (option cost / realized
    drawdown-avoidance value) by VIX regime. Effort: 3 h. Then move ownership
    from K719 synthesis to a proper K (or add structured results to K719).
  - **(b) revise paper**: Drop Table 8 or replace with reconstructed CB numbers.
    Effort: 1 h.
  - **(c) errata**: "Table 8 CB ratios 13.7×/8.0×/3.6× sourced from K719
    qualitative synthesis; quantitative reconstruction pending". Effort: 15 min.
- **Recommendation**: **(a)** + relabel. K719 should remain a synthesis doc, but
  Table 8 needs a **dedicated structured script** (likely an extension of K722
  hedging experiment). Tag the new output as K1232 or fold into K722 v2. Priority: **MEDIUM**.

---

### K720 — VRP by Regime (Table 7)

- **Folder**: `experiments/k720/` — `k720.py` (251 lines, RECONSTRUCTED).
- **Knowledge entry**: K720 `★★ VRP Correction — narrows at high VIX (+2.8%) but
  stays POSITIVE, not tradeable`. Q1 VRP=+3.5%, Q5 VRP=+2.8%. **Corrects K719's
  over-claimed VRP sign flip.**
- **Paper body reference**: Table 7 reports Calm VRP +3.5%, Elevated +3.1%, High
  +2.8%. reproduce_report T7 = 1/4 match, 3 untraceable (values not in JSON).
- **Diff report status**: `vrp_flip_confirmed=True` matches; `direction_corr`
  diverges 0.0277 → 0.8432 (large, but ambiguous definition).
- **Missing elements**: Structured `vrp_by_quintile` block in JSON; direction_corr
  formula ambiguous.
- **Paper body numbers (verbatim)**: +3.5% / +3.1% / +2.8% (Calm / Elevated / High).
- **Decision options**:
  - **(a) rebuild script**: Emit structured VRP quintile summary so Table 7
    reproduce improves to 4/4. Effort: 2 h.
  - **(b) revise paper**: Accept reconstructed quintile values if they differ.
    Effort: 1 h (after rebuild shows numbers).
  - **(c) errata**: "Table 7 VRP values sourced from K720 summary; structured
    dump pending". Effort: 15 min.
- **Recommendation**: **(a)** — reproduce 4/4 on Table 7 is cheap (extend existing
  251-line script by ~40 lines to emit the quintile block). Also clarify
  `direction_corr` definition in K720 README to close the 0.0277 vs 0.8432 gap.
  Priority: **MEDIUM**.

---

### K721 — Shock Type Decomposition (Table 5)

- **Folder**: `experiments/k721/` — `k721.py` (286 lines, RECONSTRUCTED).
- **Knowledge entry**: K721 `★★★ Shock Type Paralysis — Rate shocks absorbed most,
  geopolitical NOT absorbed`. Rate: absorption = +0.019; Risk-off: +0.007;
  Geopolitical: −0.003.
- **Paper body reference**: Table 5 reports Rate N=127 t=2.87; Risk-off N=203
  t=1.94; Geopolitical N=89 t=−0.68. reproduce_report T5 = 3/9 match, **3
  mismatch (N on all three shock types)**, 3 untraceable (t-stats not stored).
- **Diff report status**: Paralysis YES/NO match on all three. Rate-shock
  high_vix_impact 1.93 → 1.78 (7.8% drift). risk-off n_high 144 → 148 (off 4);
  rate-shock n_high 56 → 64 (off 8); geopolitical n_high 117 → 121 (off 4).
  **Paper-body N values (127, 203, 89) do not even match original JSON** (the
  JSON stores n_low + n_high = 79, 182, 146 respectively).
- **Missing elements**: t-stats not stored; VIX threshold for "high" ambiguous
  (original may use 25 or 30; paper body implies different N totals).
- **Paper body numbers (verbatim)**: Rate N=127 t=2.87; Risk-off N=203 t=1.94;
  Geopolitical N=89 t=−0.68.
- **Decision options**:
  - **(a) rebuild script**: Investigate the N=127/203/89 discrepancy — likely
    different VIX threshold or shock-day universe than what k721_results.json
    uses. Align with paper and emit t-stats. Effort: 4 h.
  - **(b) revise paper**: Replace N with 79/182/146 (matching JSON), and
    recompute t-stats; revise geopolitical t-stat if sign remains negative.
    Effort: 2 h. **This is the honest path if the paper N values were
    mis-reported** (N mismatch = 51–62% off, not a rounding issue).
  - **(c) errata**: "Table 5 N values 127/203/89 inconsistent with K721 JSON
    (79/182/146); pending resolution". Effort: 15 min. Not recommended because
    the inconsistency is too large for silent errata.
- **Recommendation**: **(b)** — N discrepancy of ~60% cannot plausibly be a
  calendar or vintage effect. Paper body likely used a prior pipeline with
  different shock-day universe. Honest path: accept K721 JSON N=79/182/146,
  recompute t-stats with Newey-West, and revise Table 5. Main-thread must
  decide; the agent flags this as the **highest-risk Table** in Paper 8.
  Priority: **HIGH** (flagged as severe in reviewer S2).

---

### K722 — Hedging Cost-Benefit (Table 8)

- **Folder**: `experiments/k722/` — `k722.py` (220 lines, RECONSTRUCTED).
- **Knowledge entry**: K722 `Absorption-adjusted VIX does NOT improve vol
  prediction (corr 0.669 < raw 0.680)`. Null result.
- **Paper body reference**: Table 8 hedging CB ratios 13.7× / 8.0× / 3.6×
  (reproduce_report maps these to "K719 not in JSON", not K722). **Structural
  confusion**: `experiments.md` says Table 8 ← K722, but reproduce_report says
  K719. Resolution: K722 is the **absorption-adjusted VIX** null result (Section
  7.3 robustness), not Table 8 CB. Table 8 owner is effectively K719 synthesis
  (see K719 above).
- **Diff report status** (against K722 raw contents): corr_raw 0.6803 → 0.5671
  (16.6% drift), corr_adjusted 0.6686 → 0.5092 (23.8% drift), r2 values ~30–40%
  off. **Conclusion** ("not improved") matches.
- **Missing elements**: Shock-filter definition (all shocks vs only negative SPY);
  RV window (20d vs 22d conflict between Sections 7.3 and 3.7).
- **Paper body numbers (verbatim)**: Section 7.3 cites corr 0.680 / 0.669 and
  R² 0.463 / 0.447 as robustness checks.
- **Decision options**:
  - **(a) rebuild script**: Resolve shock-filter and RV-window ambiguity; align
    reconstructed with original. Effort: 3 h.
  - **(b) revise paper**: Replace Section 7.3 numbers with reconstructed
    (0.567 / 0.509). Effort: 1 h. But this **weakens** the robustness claim
    (since the delta reverses: raw > adjusted vs raw < adjusted?) — actually
    conclusion "not improved" still holds in both.
  - **(c) errata**: "Section 7.3 alternative normalization robustness: raw
    correlation 0.680 (reconstruction 0.567); qualitative conclusion unchanged
    (adjusted ≤ raw)". Effort: 30 min.
- **Recommendation**: **(c)** — Section 7.3 is robustness supporting evidence;
  the qualitative claim ("alternative normalization produces qualitatively
  identical results") holds in both datasets. Large magnitude drift (>15%) must
  be disclosed, but rebuild effort is disproportionate for a robustness check.
  Priority: **LOW** (note in README, commit, move on).

---

## Summary Decision Matrix

| K    | Current State                                | Recommended | Effort (h) | Priority | Rationale                                                                          |
|------|----------------------------------------------|-------------|-----------:|----------|------------------------------------------------------------------------------------|
| K716 | script exists; 20/20 ratios match; slope 3.6% drift | **(a)**     | 1          | LOW      | One end-date alignment closes drift; Table 3 already 21/21 reproduce              |
| K717 | script exists; 4/14 strategies; not in any Table | **(c)**     | 0.25       | LOW      | Supporting Section 6 only; full rebuild = 10 h for zero Table impact              |
| K718 | script exists; 0050.TW slope 57.9% drift; t-stats missing | **(a)** | 3–4   | HIGH     | Table 4 is central; 0050 drift too large for errata                                |
| K719 | synthesis doc; Table 8 CB ratios not in JSON  | **(a)**     | 3          | MEDIUM   | New structured script (or fold into K722 v2); Table 8 owner ambiguous              |
| K720 | script exists; Table 7 quintile block missing from JSON | **(a)** | 2       | MEDIUM   | Cheap extension; direction_corr definition also needs clarification                |
| K721 | N values in paper (127/203/89) don't match JSON (79/182/146) | **(b)** | 2 | HIGH     | 60% N discrepancy is not rounding; honesty requires paper revision                 |
| K722 | corr drift ~16–24%, conclusion holds           | **(c)**     | 0.5        | LOW      | Section 7.3 robustness; qualitative claim intact; rebuild disproportionate         |

**Verdict counts**: (a) × 4  |  (b) × 1  |  (c) × 2

---

## Aggregate Recommendation

- **Total effort**: ≈ **12–13 hours** of main-thread work (spread across a few
  sessions) + Codex code review passes.
- **Best sequence**:
  1. **K716 + K718 in parallel** (same SPY/VIX pipeline; fixing one likely fixes
     the other's data-vintage drift). 4–5 h block.
  2. **K721** body revision (highest honesty concern; affects reviewer-flagged
     S2). 2 h block, main-thread writes revised Table 5 numbers + errata note in
     `docs/error_log.md`.
  3. **K720** VRP quintile dump (2 h) — cheap, improves Table 7 reproduce to 4/4.
  4. **K719** Table 8 CB structured rebuild (3 h) — either in K719 or as a new
     K1232.
  5. **K717 (c)** and **K722 (c)** — 45 min combined, README + commit message
     discloses pending errata with magnitudes.
- **Paper 8 target status post-reconstruction**:
  - reproduce_report traceability: 50.7% → **≥ 85%** (T3 stays, T4 → 9/9,
    T5 → 9/9 after revision, T6 stays K741, T7 → 4/4, T8 → 3/3 after K719
    rebuild, T9/T10 still K903 territory — not in K1231 scope).
  - Number of **pending errata** notes: **2** (K717 partial strategy coverage,
    K722 Section 7.3 robustness magnitude disclosure).
  - Honesty status: all 三方一致 rule paths chosen explicitly; no silent divergence.
- **Submission-ready timeline**: if K1231 recommendations are executed at 1–2
  sessions per day → **Paper 8 ready for R2 submission in ~1 week** of focused
  main-thread work. This is well within the R1 revision deadline window.

---

## Prior Work References

- **K1229 audit**: flagged Paper 8 P2 BLOCKER; 50.7% traceability; "scripts
  missing" claim now superseded by 2026-04-17 reconstruction pass.
- **`docs/paper-guide.md` 三方一致 rule** (user emphasis 2026-04-17): scripts /
  data / paper numbers must co-reproduce; divergences require explicit
  (a)/(b)/(c) decision, no silent commits.
- **K716 knowledge**: SPY normalized slope −0.00028 (★★★ panic paralysis).
- **K717 knowledge**: 14-strategy composite; Section 6 qualitative only.
- **K718 knowledge**: 3/4 cross-asset confirm (SPY/GLD/TLT paralysis; 0050
  exception).
- **K719 knowledge**: 5 implications synthesis; VRP sign flip corrected by K720.
- **K720 knowledge**: VRP narrows but stays positive across all quintiles.
- **K721 knowledge**: rate-shock absorption strongest; geopolitical NOT absorbed.
- **K722 knowledge**: absorption-adjusted VIX null result.
- **Reviewer S2**: Table 5 sample-size inconsistency → K904 addresses (but K721
  itself still needs (b) revision per this plan).

---

## Main-Thread Decision Points

The main thread should confirm / modify the following before execution:

1. **Accept (a) × 4, (b) × 1, (c) × 2** mix, or override any K?
2. **K721 Table 5 (b)** is the highest-impact honesty move; confirm willingness
   to publish revised N=79/182/146 with new t-stats (replacing 127/203/89)?
3. **Sequencing**: K716+K718 first (data-pipeline alignment), or K721 first
   (highest S2 reviewer pressure)?
4. **K719 rebuild (a)**: add structured JSON to K719, or spawn K1232 for Table 8
   CB ratios?
5. Should the 2 pending-errata (K717, K722) be disclosed in the paper body's
   methodology section, or only in `docs/error_log.md` + commit messages?

---

*Generated by K1231 worktree agent, 2026-04-17. Main-thread approves
recommendations before any paper `.tex` or shared JSON modification.*
