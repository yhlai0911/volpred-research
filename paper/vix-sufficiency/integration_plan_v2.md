# Integration Plan v2 — vix-sufficiency paper

**Date**: 2026-04-13
**Author**: Claude (research coordinator, not worktree)
**Target file**: `paper/vix-sufficiency/main_v2.tex` (current 989 LoC, 40 pages after step 1+2, 43 citations)
**Status**: IN PROGRESS — Steps 1+2 of 15 executed 2026-06-03 02:30 台灣時間 (hourly-02 fire). Steps 3-15 pending.

**Progress log**:
- 2026-06-03 02:30 — Step 1 (Table 1 extended to 13 rows: +Family 12 EPU, +Family 13 FinStress) + Step 2 (§3.2.12 + §3.2.13 description prose, 2 paragraphs each) + bib entries baker2016 / brave2011 / kliesen2010 added. Compile passes 40 pages. No `\citet` undefined warnings.

This plan integrates **six new pieces of evidence (K1116, K1116b, K1118, K1121, K504, K1098)**
into the existing "Can Anything Beat VIX?" manuscript, upgrading the contribution from a
SPY-specific horse race to a **cross-asset universal sufficiency compendium** with
application-boundary clarification (forecasting AND allocation, both NULL).

---

## Section 1 — Current paper summary

### 1.1 Structure (`main_v2.tex`, 9 top-level sections / 30 subsections)

| # | Section | LoC range | Est. pages | Core content |
|---|---------|-----------|------------|--------------|
| 1 | Introduction | 64–103 | ~3 | Motivation, headline null claim, contribution list |
| 2 | Why VIX is the Benchmark | 104–147 | ~3 | Theory + prior horse-race literature |
| 3 | Data and the Eleven Signal Families | 148–245 | ~5 | Table 1 + Families 1–11 descriptions |
| 4 | Forecast Design and Benchmark Models | 246–313 | ~4 | Pipeline, VIX benchmark, incremental-info test, QLIKE, OOS R² |
| 5 | Statistical Evaluation / Multiple Testing | 314–363 | ~4 | DM, Holm-Bonferroni, MCS, cross-era validation |
| 6 | Volatility-Timing Strategy Design | 364–397 | ~3 | 12/VIX, 50/50 baseline, TX cost |
| 7 | Main Results and Robustness | 398–677 | ~12 | 7 subsections: forecasting / strategy / multi-asset / eras / competing signals / criterion-dependent / era-stratified 12/VIX |
| 8 | Why the Null is Informative | 678–799 | ~4 | Information aggregation, what might break VIX, econ significance, drawdown insurance, simplicity premium |
| 9 | Conclusion | 800–820 | ~1 | 3-bullet practitioner wrap-up + broader null-result observation |
|   | References | 820+ | ~4 | 40 items |

**Total**: ~39 printed pages, 40 citations.

### 1.2 What the paper already covers

- **Assets**: SPY only (with GLD/TLT used *as signals* in Family 1 cross-asset momentum, and 9-asset universe used in Family 5 portfolio optimization only).
- **Asset class scope**: US equity single-asset.
- **Alt-data tested**: Google Trends fear (Family 9); **USEPU / WLEMU / NFCI / STLFSI are not in the paper** despite being the most academically-canonical alt-data for uncertainty/stress.
- **Bitcoin**: treated only as Family 7 via Granger causality on BTC→VIX; not as a separate prediction target with its own native IV.
- **Publication-delay robustness**: NOT addressed. Paper currently says "signals available at market close on day $t-1$ and applied to day $t$" without distinguishing FRED release calendars.
- **Application domains tested**: forecasting (OOS R², QLIKE, DM); volatility-timing strategy (12/VIX and variants); multi-asset portfolio optimization (8 methods × 7 asset subsets).
- **Economic-significance framing**: CRRA γ≥4.5 investor, drawdown insurance thesis.
- **Eras**: 5 non-overlapping eras 1993–2026, CV(R²) = 0.33.

### 1.3 Page distribution (approximate, from .tex inspection)

Abstract + intro + literature = 6p; data/design/stat-eval = 13p; results = 12p; discussion/conclusion = 5p; refs = 3p.
(Total ≈ 39p matches README claim.)

---

## Section 2 — New evidence to integrate

### 2.1 Inventory of six new pieces

| ID | One-line | Asset(s) | Application | Verdict | Key stat |
|----|----------|----------|-------------|---------|----------|
| **K1116** | SPY weekly RV, EPU + NFCI + STLFSI alt-data vs VIX | SPY (in paper) | Forecasting (in paper) | NULL (active harm) | M4 DM t=−3.00, M3 DM t=−2.55 (both lose to VIX baseline at \|t\|>2) |
| **K1116b** | Publication-delay re-verification of K1116 + K1118 | SPY, GLD, TLT, BTC | Forecasting (methodology) | Robustness confirms NULL; TLT niche collapses | TLT M4: t=+3.74 → **+1.96** under corrected shift(2); SPY M4 strengthens −3.00 → −3.61 |
| **K1118** | Cross-asset alt-data sufficiency (GLD, TLT, BTC) | GLD (new), TLT (new), BTC (new) | Forecasting | NULL 3/3 triple-gate | GLD M5 improvement −0.02%; TLT M4 QLIKE +0.50% (<5% gate); BTC EPU actively harmful (t=−5.04) |
| **K1121** | Alt-data for allocation (daily SPY+GLD regime rules) | SPY, GLD | **Allocation (new application)** | NULL (S5 NFCI ties S1 50/50, p=0.966) | All 5 alt-data strategies p>0.26 on Sharpe diff vs 50/50 baseline |
| **K504** | FRED STLFSI4 regime strategy — historical null | SPY | Strategy | NULL ("24th confirmation") | Earlier null consistent with K1116 direction |
| **K1098** | VIXTWN on 0050.TW — Taiwan native IV sufficiency | 0050.TW (new) | Forecasting | NULL for A4f framework | VIXTWN DM t=+1.86 fails Harvey; cross-asset matrix GLD+GVZ +4.46 ✓, USO+OVX +4.48 ✓, 0050+VIXTWN +1.86 ✗ |

### 2.2 Insertion table (where each piece goes + estimated page additions)

| Exp | Existing or New Asset? | Existing or New Application? | Insertion Point | Est. +pages |
|-----|---------------------|---------------------------|-----------------|-------------|
| **K1116** (SPY EPU+NFCI+STLFSI) | SPY (existing) | Forecasting (existing) | Add **Family 12 (EPU)** and **Family 13 (Financial Stress: NFCI/STLFSI)** to Table 1; append rows to Table 2 (main results); cite in §7.1 as "active harm" finding strengthening the null | **+1.5** |
| **K1118** (GLD/TLT/BTC native-IV vs alt-data) | **NEW** (GLD, TLT, BTC as prediction targets) | Forecasting (existing) | **NEW Section 7.x: Cross-Asset Universal Sufficiency** — Table showing each asset × (native IV vs alt-data) DM results; short discussion per asset | **+3** |
| **K1116b** (publication-delay verification) | SPY + all K1118 assets | Methodology/robustness | **NEW §4.x or §7.x: Publication-Delay Robustness** — short dedicated subsection with before/after table showing all 16 cells; TLT M4 collapse featured | **+1.5** |
| **K1121** (alt-data for allocation) | SPY+GLD (existing) | **NEW application: regime-based allocation** | **NEW Section 7.x: Alt-Data Fails a Second Paradigm — Allocation** — 6-strategy table, bootstrap p-values vs 50/50, stress-episode wSPY table, "NFCI MDD property but zero Sharpe edge" discussion | **+2** |
| **K504** (STLFSI4 historical) | SPY (existing) | Strategy (existing) | **Merge into K1116 footnote / literature** — cite as prior confirmation to show K1116 is not the first STLFSI null; light insertion | **+0.2** |
| **K1098** (VIXTWN on 0050.TW) | **NEW** (0050.TW TW equity) | Forecasting (existing) | **Insert into NEW §7.x (Cross-Asset Universal Sufficiency)** as the 5th asset class row; discuss as boundary case (VIXTWN t=+1.86 "fails Harvey but direction consistent"); link to Paper 9 ancillary finding on currency/TSMC concentration | **+1** |

**Net projected additions**: **+9.2 pages**, bringing paper from 39p → **~48 pages**. (4 new tables, 2 new figures suggested in §5.)

---

## Section 3 — Restructured outline

Proposed updated structure (changes highlighted as **NEW** or **MODIFIED**):

```
1. Introduction
   - Rewrite ¶2 of intro to flag universal cross-asset scope + 2 applications.
   - Add 1 paragraph foreshadowing publication-delay robustness.

2. Why VIX is the Benchmark
   - Unchanged (no new lit).

3. Data and the Eleven  THIRTEEN  Signal Families            [MODIFIED]
   3.1 Core Data
       - Add FRED series (USEPUINDXD, WLEMUINDXD, NFCI, ANFCI, STLFSI4) to data section
       - Add GVZ, MOVE, VIXTWN as asset-specific native IV measures
       - Add cross-asset return data: GLD, TLT, BTC-USD, 0050.TW
   3.2 The Thirteen Signal Families (was Eleven)
       - Existing Families 1-11 unchanged
       + Family 12: Economic Policy Uncertainty (USEPU + WLEMU)
       + Family 13: Financial-Stress Indices (NFCI + ANFCI + STLFSI4)
       - Family 9 (Google Trends) retains current coverage; cross-reference K473/K750 null history

4. Forecast Design and Benchmark Models
   - Unchanged, EXCEPT:
   + ADD §4.5: Publication-Delay Convention
     - Explicit release-schedule table (daily FRED: t+1 release; weekly FRED: Wed-Thu of t+1 release)
     - Explain shift(2) for USEPU/WLEMU and shift(5) for NFCI/STLFSI at daily frequency; shift(1) for weekly aggregated series with correction-variant shift(2) reported alongside

5. Statistical Evaluation and Multiple-Testing Control
   - Unchanged

6. Volatility-Timing Strategy Design
   - Unchanged

7. Main Results and Robustness                              [MODIFIED — expanded]
   7.1 Volatility Forecasting: No Signal Beats VIX (SPY)    [MODIFIED]
       - Append K1116 rows to Table 2 (M3_EPU, M4_FinStress, M5_All results)
       - Add 2 sentences on "active harm" finding (K1116 vs prior null studies)
   7.2 Strategy Comparison: No Signal-Based Strategy Beats Benchmarks
       - Unchanged

   + 7.3 NEW: Cross-Asset Universal Sufficiency             [K1118 + K1098]
       7.3.1 GLD and GVZ (commodity)
       7.3.2 TLT and MOVE (bonds) — incl. original-vs-corrected t-stat note
       7.3.3 BTC and RV30 proxy (crypto) — incl. EPU-harmful finding
       7.3.4 0050.TW and VIXTWN (TW equity) — boundary-case discussion
       - Table: 5-asset-class × alt-data NULL matrix

   + 7.4 NEW: Publication-Delay Robustness                  [K1116b]
       - Before/after t-stat table (the 16-cell comparison)
       - Explicit note that TLT M4 from K1118 collapses from +3.74 to +1.96
       - "Sensitivity under `conservative` shift(2) everywhere" paragraph

   + 7.5 NEW: Alt-Data Fails a Second Paradigm — Allocation [K1121]
       - 6-strategy table (Sharpe / Sortino / MDD / Calmar / avg wSPY)
       - Bootstrap Sharpe-difference p-values vs 50/50
       - Stress-episode wSPY table (COVID, 2022 rate-shock, SVB)
       - NFCI's MDD-reduction property discussion (risk-management niche but zero alpha)

   7.6 (was 7.3) Multi-Asset Portfolio Optimization
   7.7 (was 7.4) Era Stability of VIX Sufficiency
   7.8 (was 7.5) Competing Signals by Era
   7.9 (was 7.6) Criterion-Dependent Model Rankings
   7.10 (was 7.7) 12/VIX Strategy by Era

8. Why the Null is Informative                              [LIGHTLY MODIFIED]
   8.1 The Information Aggregation Explanation
       - Extend argument: aggregation holds across asset classes (not just SPY) given
         §7.3 evidence
   8.2 What Might Break VIX Sufficiency?
       - Update speculation paragraph: rule out (a) alt-data uncertainty (K1116+K1118+K1121
         now refuted), (b) cross-asset vol spillovers (K1118), (c) regime gating (K1121)
   8.3 Economic Significance
   8.4 The Drawdown Insurance Framework
       - Add NFCI MDD observation (S5 achieves −17.9% MDD tied with S3)
   8.5 The Simplicity Premium
       - Unchanged

9. Conclusion                                               [MODIFIED]
   - Bullet 1 (researchers): add "universal across SPY/GLD/TLT/BTC/0050.TW"
   - Bullet 2 (practitioners): clarify "no regime-allocation rule using EPU or NFCI
     beats 50/50 after publication-calendar correction"
   - Bullet 3 (regulators): unchanged
   - Closing paragraph: update "36 null results" → count to include the six new pieces
     (≈42 independent confirmations)
```

### 3.1 Alternative simpler restructuring (fallback if +9p is too large)

If page budget matters (Journal of Forecasting ~40p comfortable limit):
- Keep 7.3/7.4/7.5 as one compressed §7.3 "Cross-Asset and Allocation Extensions" (+4–5p total instead of +6)
- Move K1116b before/after table to appendix (saves ~1p in main text)
- Absorb K1098 TW equity into a footnote/paragraph rather than own subsubsection

Final range: **minimum +5p, target +9p**.

---

## Section 4 — Title and framing suggestion

### 4.1 Current title

> "Can Anything Beat VIX? A Systematic Out-of-Sample Evaluation of Eleven Signal Families for Equity Volatility Forecasting and Volatility Timing"

### 4.2 Issue with current title post-integration

The title still scopes to "equity" (singular, SPY) and "eleven signal families." After integrating K1116/K1118/K1121, the paper covers:
- **5 asset classes** (US equity, commodity, bond, crypto, TW equity)
- **13 signal families** (added EPU, FinStress)
- **2 applications** (forecasting + allocation)
- **Publication-delay robustness** (methodological contribution)

### 4.3 Recommended options

**Option A — strongest contribution claim (recommended)**:
> "Native Implied Volatility Is Sufficient: A Cross-Asset Compendium of Thirteen Signal Families for Forecasting and Allocation"

**Option B — keep "Can Anything Beat VIX?" branding + universal subtitle**:
> "Can Anything Beat VIX? Cross-Asset Evidence from Thirteen Signal Families, Two Applications, and Publication-Delay Correction"

**Option C — minimal change (conservative)**:
> "Can Anything Beat VIX? A Systematic Out-of-Sample Evaluation of Thirteen Signal Families Across Five Asset Classes for Volatility Forecasting and Allocation"

**Recommendation**: Option B. It preserves citability of current title/identity while signaling the broader contribution in the subtitle. Option A is strictly stronger on contribution framing but sacrifices the catchy primary question.

### 4.4 Abstract rewrite outline (one paragraph)

Add to existing abstract (after "calendar anomalies"):
> "...and extend the horse race to two newly-canonical alt-data families—Economic Policy Uncertainty and Financial Stress Indices—while replicating the design across five asset classes (US equity, commodity, bond, crypto, Taiwan equity), two applications (forecasting and regime-based portfolio allocation), and under a publication-calendar-corrected timing convention that eliminates a 1.78 drop in one previously-apparent cross-asset niche (TLT financial-stress)."

Adjust the "main finding" paragraph: "not a single signal family produces a statistically significant improvement" → add phrase "across any of the five asset classes or either application, with all results surviving both Holm-Bonferroni multiple-testing correction and publication-delay robustness checks."

---

## Section 5 — Concrete next-step list for main thread

Execute in this order. Each item is atomic and testable.

1. **Update Table 1 (Signal Families) to 13 rows**
   - Add Family 12 (EPU) and Family 13 (FinStress) with sample windows, N, construction
   - Target: `main_v2.tex` L171–191, extend tabular from 11 to 13 rows

2. **Add §3.2.12 and §3.2.13 descriptions for new families**
   - Family 12 EPU: cite Baker/Bloom/Davis (2016), describe USEPU+WLEMU composite
   - Family 13 FinStress: cite Brave/Butters (2011), Kliesen/Smith (2010); describe NFCI+ANFCI+STLFSI
   - Target: `main_v2.tex` insert at L239 (after Family 11 block)

3. **Add §4.5 Publication-Delay Convention**
   - Release-calendar table (daily FRED vs weekly FRED release timing)
   - Equations for daily shift(2)/shift(5) and weekly shift(1)/shift(2) variants
   - Cite K1116b as verification; reference E062 in error log
   - Target: insert at L313 (end of Section 4)

4. **Extend Table 2 (Main Forecasting Results) to 13 rows**
   - Insert rows 12 (EPU) and 13 (FinStress) with DM t-stats from K1116
   - Note: family 13 should report corrected t-stat as primary (−3.61), original (−3.00) as footnote
   - Target: `main_v2.tex` L411–430

5. **Write §7.3 Cross-Asset Universal Sufficiency** (NEW, ~3 pages)
   - 5-asset-class × alt-data table using K1118 + K1098 results
   - Per-asset narrative paragraph (GLD, TLT, BTC, 0050.TW)
   - Features: TLT M4 split result + its K1116b collapse; BTC EPU active harm; Taiwan boundary case
   - Target: insert between current §7.2 (strategy comparison) and §7.3 (multi-asset)

6. **Write §7.4 Publication-Delay Robustness** (NEW, ~1.5 pages)
   - Before/after 16-cell DM t-stat table (K1116b §3.2 results)
   - Paragraph on TLT M4 collapse (+3.74 → +1.96)
   - Note on conservative variant sensitivity (M5 brittle; other cells stable)
   - Target: insert after §7.3 (new)

7. **Write §7.5 Alt-Data Fails a Second Paradigm — Allocation** (NEW, ~2 pages)
   - 6-strategy Sharpe/MDD table
   - Bootstrap p-value table (all vs 50/50)
   - Stress-episode wSPY table (3 episodes × 6 strategies)
   - "NFCI MDD-reduction is risk management not alpha" tie-in to existing §8.4 drawdown-insurance
   - Target: insert after new §7.4

8. **Update §8.2 "What Might Break VIX Sufficiency?"**
   - Cross off alt-data uncertainty (K1116+K1118 refute)
   - Cross off regime-based allocation (K1121 refutes at the allocation level)
   - Keep: higher-frequency realized measures (Section 8's existing escape hatch)
   - Target: revise paragraph at L698–707

9. **Update Conclusion §9**
   - Update null count from "36" → "≈42" (36 + K1116 + K1118 × 3 assets + K1121 + K1098 − overlap with K504/K473 already counted = +6 net)
   - Extend Bullet 1 (researchers) "universal across SPY/GLD/TLT/BTC/0050.TW"
   - Target: L802–819

10. **Update abstract**
    - Add "thirteen signal families" (from eleven), "five asset classes," "two applications," "publication-delay corrected"
    - Target: L46–57

11. **Update title (if adopting Option B)**
    - New title string at L35

12. **Add references** (est. +4 new citations)
    - Baker, Bloom, Davis (2016) — EPU (may already be in bib? verify)
    - Brave, Butters (2011) — NFCI
    - Kliesen, Smith (2010) — STLFSI
    - Politis, Romano (1994) — stationary bootstrap (for K1121 bootstrap attribution)
    - Opdyke (2007) — Sharpe inference (for K1121 bootstrap attribution)
    - Harvey, Leybourne, Newbold (1997) — HLN DM correction (may already be in bib; verify)
    - Target: append to `thebibliography` at L820+

13. **Add figures** (suggested, 2 new)
    - Figure A: 5-asset-class forecasting-sufficiency heatmap (assets × signal families, color = DM t-stat)
    - Figure B: K1121 bootstrap distribution of Sharpe differences vs 50/50 (6 curves)
    - Target: produce from K1118 + K1121 JSON; place in §7.3 and §7.5 respectively

14. **Update README.md**
    - Pages: 39 → ~48 | Citations: 40 → ~46
    - Add K1116/K1118/K1116b/K1121/K1098 to experiments list
    - Update "Key Finding" paragraph to reflect universal claim

15. **Post-edit validation**
    - Run `xelatex main_v2.tex` twice (for TOC)
    - Verify all new \citet{...} resolve (citation_check.md update)
    - Run latex-academic-reviewer skill on new sections
    - Run citation-verifier on K1118/K1121 references
    - Run `paper-update` CLI to push to Supabase (per CLAUDE.md paper update procedure)

---

## Section 6 — Risk register (items to flag at review)

1. **Page budget**: +9p brings the paper to ~48 pages. Journal of Forecasting typically accepts 35–45 pages. Need to either trim existing sections (e.g., merge §7.6/7.7/7.8 subsections) or adopt fallback (4.1 above) to compress K1116b into appendix.

2. **Title change risk**: Changing the title loses SSO/Google-Scholar continuity if the paper is already indexed. If the paper has been uploaded anywhere public, prefer Option C (minimal change).

3. **Bibliography bloat**: +6 citations pushes from 40 → 46. Still well within norms.

4. **Self-citation chain**: The paper currently does not cite internal K-experiments directly; it frames everything as pre-specified families. Keep this style — refer to K1116/K1118/K1121 only in footnotes / as "Experiment ID" in the data section, not as primary citations.

5. **"Eleven" in current title is hard-coded**: If we keep Option C title (with "Thirteen"), the abstract must also change from "eleven" to "thirteen" (L46, L62, L86, L106, L154, L163 — all need sync).

6. **Publication-delay content could be contentious**: Reviewers may push back on whether shift(2)/shift(5) is over-conservative. Pre-empt by showing both variants in the table (done in K1116b results already) and arguing that even the generous variant (original `shift(1)`) does not reach Harvey significance for SPY — so the universal null is robust to timing choice.

7. **K504 is the lightest touch**: Just a footnote / one-line literature citation. If main thread is short on time, items 1–9 above are essential; K504 insertion (item in 2.2) can be deferred.

---

## End of integration plan v2

**Deliverable**: Integration plan ready for main-thread execution. No .tex edited. No git commit.

---

## Addendum 2026-05-11 — K1116d (7th piece): True ALFRED first-release vintage retest

### Why this strengthens the integration story

K1116/K1116b/K1118/K1121 demonstrated NULL using **revised** FRED data (today's snapshot of historical series). A natural reviewer pushback: "perhaps revisions wash out the signal that was visible in real time." K1116d removes this objection by retesting with **first-release vintage** — the data a forecaster would actually have seen on the publication date.

### K1116d 1-liner (to add to §2.1 inventory)

| ID | One-line | Asset(s) | Application | Verdict | Key stat |
|----|----------|----------|-------------|---------|----------|
| **K1116d** | True ALFRED first-release vintage retest of K1116c PIT NULL | SPY | Forecasting (methodology robustness) | **H2_ROBUST_NULL_VINTAGE_CONFIRMED** | 6×5 grid: 0/24 cells pass both vintage + revised cycles. Worst pit_shift1×all DM t=−5.21 (alt-data + VIX strictly WORSE than VIX-only baseline). |

### Insertion point

Slot into the **§4.x or §7.x Publication-Delay Robustness** subsection (already planned for K1116b). Extend the subsection from a 2-table layout to a 3-table layout:

1. K1116b table — same-snapshot publication-delay shift (shift(1) vs shift(2) vs shift(5))
2. **NEW**: K1116d table — first-release vintage vs revised-snapshot, for the 6 lag/PIT variants × 5 specs grid
3. Combined verdict statement: "The alt-data NULL is robust to both publication-delay convention AND revision content. No combination of timing choice and data vintage produces statistically significant improvement over the VIX-only baseline."

### Page budget impact

+0.5 page (1 new compact table + 1 paragraph). Total projected paper length: 39 → 48.5 pages → still within Section 6.1 risk note (need to trim or compress K1116b to appendix).

### Sensitivity check already done in K1116d

Drop-STLFSI sensitivity (chain vs backfill artifact concern): NULL holds in both vintage and revised cycles after STLFSI exclusion. Addresses Codex MINOR re STLFSI/2/3/4 splice timing.

### Citation status

K1116d uses no new external references beyond ALFRED (already cited via FRED data section). No bibliography expansion needed.

### Recommendation

Promote K1116d alongside K1116b in the publication-delay robustness subsection; do NOT downgrade to footnote — first-release vintage retest is methodologically distinctive enough to warrant a named result.

### Dependency for execution

K1116d data files are in `experiments/k1116d/`:
- `k1116d_results.json` — main 6×5 battery
- `k1116d_sensitivity_no_stlfsi.json` — sensitivity
- `data/gap_validation_v2.json` — chunk-boundary fix audit (USEPU/WLEMU 3046→3056 obs each)

Knowledge entry: `storage/memory/knowledge.json` id=K1116d (written 2026-05-11 by main thread post-Codex CONDITIONAL PASS).

Commits: `5c94a2e1` (fetch fix) + `b3967920` (main results).

