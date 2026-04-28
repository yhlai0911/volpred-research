# P10 Crypto Fear Channel — v3 Academic Review Report

**Reviewer**: latex-academic-reviewer (Claude main thread, subagent run)
**Date**: 2026-04-28
**File reviewed**: `paper/crypto-fear-channel/main.tex` (542 lines, 17 pages, 7 tables, 22 bibitems, ~5,500+ body words)
**Source experiments**: K1025 (BTC→VIX, primary) + K1025b (BTC→VXN, multi-asset robustness fork)
**Reproduce status**: 29/29 byte-match GREEN, alert_level=green, gate_status=pass (verifies K1025 only)
**Compile status**: clean (17p, 0 errors, 0 undefined refs, 1 underfull + 5 overfull hbox warnings — see §3 below)
**Target journals**: IJFMIM (1st) / JEF (2nd) / FRL (backup)
**Round context**: v3 = v2.3 hotfix (78593750) + v2.4 cross-paper meta-eval (07e53e81) + K1025b multi-asset (6a41fc40). v2 closed 0 CRIT / 0 SEV / 0 MAJOR; v3 must hold the line and verify the 4 commits' regression-free quality.

---

## 1. Overall Assessment (10-dimension scoring, 1–5★)

| # | Dimension | v2 | v3 | Δ | Comment |
|---|-----------|----|----|---|---------|
| 1 | Logic flow (abstract→§9) | 4.5 | 4.5 | 0 | §6.4 (multi-asset) inserts cleanly into Robustness; §1→§2→§4 four-blocks framing intact |
| 2 | Argument quality / honest reporting | 4.5 | 4.5 | 0 | v2.3 γ qualitative footnote is honest; "follow-up extension" framing avoids over-claim. K1025b §6.4 honestly notes "consistent with empirical variation expected" not "identical replication" |
| 3 | Methodology self-containedness | 4.5 | 4.5 | 0 | §3.2 + §4.1–§4.5 unchanged. K1025b §6.4 references K1025 building blocks rather than re-stating them — efficient, no redundancy |
| 4 | Equation correctness & clarity | 4.0 | 4.0 | 0 | No new equations; §6.4 uses Table 7 to summarize parameter shifts (good choice — would have been bloat to re-derive) |
| 5 | Symbol consistency (§1–§9) | 3.5 | 3.5 | 0 | RV^{(20)} vs RV^{btc} unchanged (carried over from v2). K1025b shorthand "BTC$^-$ best F" introduces a new column header convention but is internally consistent within Table 7 |
| 6 | Citation grounding | 4.5 | 4.5 | 0 | 22 bibitems unchanged; alphabetical fix (Andrews/Akyildirim swap in v2.4) maintains citation order |
| 7 | Structure / sequencing | 4.0 | 4.0 | 0 | §6 expands 3 → 4 subsections; §6.4 placed last in Robustness which is the right slot. §6 internal flow: spillover-stability → lag-sensitivity → ETF-microstructure → multi-asset reads naturally |
| 8 | Honest reporting (§7 OOS, §8.2 reconciliation, §8.4 limits) | 4.5 | 4.7 | +0.2 | v2.3 γ footnote is a *strict improvement* over v2.2 paragraph: drops unverifiable specific claims (median t below 1.5; "roughly half windows"), adds explicit "left to a follow-up extension" disclosure, and forward-refs to §8.2. Reviewer-facing transparency increased. |
| 9 | Tables (T1–T7 self-containedness) | 4.0 | 3.7 | -0.3 | T1–T6 unchanged. **NEW T7 has two numerical errors** (see NEW MAJOR-1 below): K1025b "BTC$^-$ best F ~15" should be 24.31; K1025b "QR upper-tail amplification ~11×" should be 5.75×. These are *not* covered by the 29-check reproduce.py gate (which is K1025-only) |
| 10 | First-time-paper fundamentals | 4.0 | 4.0 | 0 | Multi-asset robustness materially raises the IJFMIM/JEF acceptance probability; 17-page length still within IJFMIM norms |

**Weighted overall**: ★★★★½ (**4.30 / 5**, vs v2 4.40, **−0.10**) — the K1025b multi-asset extension closes the cross-paper meta-eval top-tier blocker and substantially raises Dimension 8 (honest reporting), but the new Table 7 carries two numerical errors in the K1025b column that drag Dimension 9 down by 0.3. **Net is negative** because the errors are in numbers a reviewer will spot in 30 seconds (Table 7 is short, only 9 rows, and the amplification ratio is the paper's signature finding). After fixing NEW MAJOR-1 the score would rise to **4.55 / 5** and the recommendation flips to advance.

---

## 2. Verdict Summary

| Severity | v2 | v3 | Δ |
|----------|----|----|---|
| CRITICAL | 0 | **0** | 0 |
| SEVERE   | 0 | **0** | 0 |
| MAJOR    | 0 | **1** | +1 (NEW MAJOR-1: Table 7 K1025b numerical errors) |
| MED      | 3 | **3** | 0 (NEW MED-1 §6.4 column-ordering; v2 NEW MED-2 §4.1 53pt overfull *fixed in v2.4*; v2 NEW MED-3 §5.1 inset paragraph carried-over; NEW MED-2 53pt-overfull regression-free; NEW MED-3 §6.4 narrative tightening) |
| MINOR    | 5 | **4** | -1 (γ rolling-window claims now in qualitative footnote, reduces from MED to MIN-class concern; one v2 MIN closed; one v3 new) |

**v3 issue count**: 8 total (vs 8 in v2; one MAJOR new offsets one MED closure). **One review-blocker (MAJOR) introduced**: Table 7 numerical errors must be fixed before submission.

---

## 3. v2 → v3 Fix Verification (4 commits)

### Commit 78593750 — v2.3 hotfix (research-honesty + overfull + alphabetical)

Three changes verified:

1. **§7 γ paragraph → qualitative footnote (research-honesty fix)**: ✓ EXCELLENT FIX. The v2 NEW MED-1 critique flagged that "median |t| below 1.5" and "γ positive in roughly half the windows" had no JSON backing. v2.3 removed those specific claims and replaced them with a footnote (line 345): *"The Online-replication archive reports the single rolling DM statistic and pooled MSE/MAE/QLIKE losses (Table~\ref{tab:oos}); diagnostics on the rolling-window in-sample $\hat\gamma$ path (sign stability, $t$-statistic distribution across re-estimations) are left to a follow-up extension. The pooled DM null does not by itself rule out a stable, sign-conditional $\gamma$; what we report is a discipline-level no-improvement result on average loss, not a structural rejection of the underlying $\gamma$."* This is **textbook honest acknowledgement**: drops unverifiable specifics, names the gap explicitly ("left to a follow-up extension"), distinguishes pooled-DM result from a structural γ claim. A JIMFIM/JEF referee will read this and either (a) accept it as a methodological boundary, or (b) push for the rolling γ path in R&R round — but will not regard it as a research-integrity issue. **Quality: A+.**

2. **Overfull \hbox 53pt at §4.1 → split into two sentences**: ✓ FIXED. Diff confirms line 132 split (was: "...of \citet{andrews1991}, the default specification..."; now: "...of \citet{andrews1991}. We use the Newey-West kernel...the default specification of..."). v3 main.log shows line 131-133 box reduced from 53.10pt → 80.78pt — **WAIT, log says 80.78pt overfull at line 131-133**. Let me re-check.

   Looking at main.log: `Overfull \hbox (80.78117pt too wide) in paragraph at lines 131--133`. This is *worse* than v2's 53.10pt. The split improved sentence structure but the new paragraph still overflows. Recommend: re-flow the second sentence "We use the Newey-West kernel..." to break further (e.g., split before "the default specification"), or wrap `\texttt{statsmodels.tsa.stattools.grangercausalitytests}` into a footnote. **Verdict: PARTIAL FIX. NEW MED-2 carries to v3.**

3. **andrews1991 alphabetical fix**: ✓ FIXED. v2.4 swapped andrews1991/akyildirim2020 to put Akyildirim first (alphabetically correct). Bibitem order now consistent with author surnames A→Y. **Quality: A.**

### Commit 07e53e81 — v2.4 cross-paper meta-eval Highest-impact

Three changes verified:

1. **§1 contribution paragraph rewrite — lead with empirical novelty**: ✓ EXCELLENT FIX (the single most consequential v3 change for journal placement). Diff confirms full rewrite: v2 first sentence was "by combining asymmetric Granger causality, quantile regression for tail dependence, Diebold-Yilmaz spillover direction, and an honest out-of-sample forecasting test in a single framework, we show that each dimension tells a distinct story" (method enumeration). v3 first sentence is "we document a new empirical pattern in the BTC-to-VIX channel: the conditional response of equity fear to Bitcoin realized variance *reverses sign* between the lower and upper halves of the VIX distribution and amplifies by approximately $8.5\times$ from the median to the 95th percentile." (empirical-novelty lead). Three contributions now read:
   - **C1**: sign-reversal + 8.5× amplification (new empirical pattern, |t|>5 in every quantile, "to our knowledge not previously documented in the cryptocurrency-equity spillover literature") — **strong publishable contribution**.
   - **C2**: COVID-2020 structural watershed + DY net-receiver −77 pp (regime + directional finding combined) — **strong publishable contribution**.
   - **C3**: joint reporting discipline (in-sample structure + Harvey-threshold OOS) — **methodological-discipline contribution**, not a standalone empirical lever but credibly framed as "supplies a methodological template".
   
   The closing sentence ("Each contribution rests on the four methodological building blocks ... developed in §4; the novelty lies in their joint application") subordinates the methods to the empirical claims — exactly the inversion the cross-paper meta-eval recommended. **Word count check**: v2 contribution paragraph was ~135 words; v3 is ~330 words. The cross-paper meta-eval suggested 80–150 words. v3 *exceeds* the recommendation by ~2×, but the additional length is justified because each contribution now carries a quantitative anchor (8.5× / -77 pp / |t|=-0.98 vs |t|>3) — the over-budget is more *signal* than *bloat*. A JIMFIM submission can carry this length comfortably. **Quality: A**, would be A+ if compressed by ~30%.

2. **§7 forward-ref to §8.2**: ✓ SMOOTH. Line 345 now reads "We return to the methodological reconciliation of this OOS null with the strong in-sample asymmetric and tail-conditional structure documented in §5 in the discussion of Granger causality versus forecastability (§8.2)." This is the cross-paper meta-eval Section 4 fix request and is *well-integrated*: the sentence appears immediately after the DM result is stated, anchoring the OOS null with the reconciliation argument before §7 develops the regime-stratified subsample. A reader who skims §7 will not interpret the null as a paper failure. **Quality: A.**

3. **§8.3 complementary-not-duplicative phrasing**: ✓ WELL-INTEGRATED. v3 line 389 prepends a new opening sentence: "The crisis-conditional spillover has direct policy implications that are complementary to, rather than duplicative of, the systemic-risk literature on within-equity crowding strategies (e.g., volatility targeting, trend-following). Where systemic-risk frameworks for positive-feedback equity strategies focus on *intra-equity* concentration of correlated trading flow during stress, the present paper adds an *external-market amplification* channel..." This addresses the cross-paper meta-eval Section 6 Issue 2 (P5 policy claim potential overlap). The two-sentence enhancement reads as a natural framing of the §8.3 contribution rather than a defensive footnote. **Quality: A**.

### Commit 6a41fc40 — K1025b multi-asset OOS + §6.4 + Table 7

Three sub-checks below in §4 (NEW issues / quality assessment).

---

## 4. K1025b §6.4 + Table 7 Quality Assessment (the load-bearing v3 addition)

### 4.1. §6.4 narrative quality

✓ **CLEAR rationale**. Line 309 opens: "The headline analysis pairs BTC realized volatility with the S&P 500 fear gauge (VIX) and the corresponding equity ETF (SPY). To probe whether the asymmetric / tail-conditional / regime-dependent structure is specific to the S&P 500 index or generalizes across U.S. equity-fear gauges, we re-run the four core building blocks on a parallel asset pair: the NASDAQ-100 fear gauge VXN and the corresponding NASDAQ-100 ETF QQQ." This is a legitimate robustness motivation — the cross-paper meta-eval Section 6 Issue 3 explicitly named "BTC→VXN (NASDAQ fear)" as one of three acceptable extensions. The "ticker swaps SPY → QQQ and ^VIX → ^VXN" framing is precise.

✓ **Honest no-extension framing**. Line 338: "We do not extend the analysis further to non-U.S. equity-fear gauges (e.g., Euro Stoxx VSTOXX, Nikkei VXJ) here, primarily because the BTC trading day overlaps less cleanly with overseas equity sessions and the dataset alignment introduces additional joint-stationarity concerns; this is a natural extension we leave to future work." This is *defensible* — a JIMFIM/JEF referee could push back ("why not VSTOXX?") but the trading-day alignment argument is technically valid (VSTOXX trades 9:00–17:30 CET, BTC is 24/7, the within-day BTC-to-Euro-overnight return alignment introduces non-trivial joint-stationarity issues). The single-region scope is reasonable for a 17-page paper. A referee who insists on VSTOXX is asking for an R&R-class extension, not a desk-reject-class blocker. **Acceptance: yes, defensible.**

### 4.2. Table 7 numerical accuracy — **CRITICAL ISSUE FOUND**

I cross-checked all 9 rows of Table 7 against `experiments/k1025b/k1025b_results.json`. **Two rows have errors**:

| Row | K1025 (paper) | K1025b (paper) | K1025b (JSON actual) | Verdict |
|-----|---------------|----------------|----------------------|---------|
| Asymmetric Granger BTC$^-$ best $F$ (lags 1–5) | 18.96 | **~15** | **24.31** (lag 1; min 11.16 at lag 5) | **WRONG** |
| Asymmetric Granger BTC$^+$ p (all lags 1–5) | 0.16–0.95 | 0.14+ | 0.144 / 0.723 / 0.724 / 0.837 / 0.855 | OK (shorthand acceptable) |
| QR $\beta_{0.05}$ | $-2.86$ | $-1.46$ | $-1.4628$ | OK |
| QR $\beta_{0.95}$ | $+22.31$ | $+16.29$ | $+16.2926$ | OK |
| QR upper-tail amplification ($\beta_{0.95}/\beta_{0.5}$) | $8.5\times$ | **$\sim 11\times$** | **5.75× (16.29/2.83)** | **WRONG** |
| Sub-period 2020 Granger $F$ | 11.05 | 13.41 | 13.41 | OK |
| DY total spillover (\%) | 90.11 | 90.09 | 90.09 | OK |
| DY net BTC (pp) | $-76.89$ | $-76.64$ | $-76.64$ | OK |
| OOS DM stat (Harvey) | $-0.98$ (NS) | $-0.43$ (NS) | $-0.4324$ | OK |

**Two errors to fix** (NEW MAJOR-1, see §6 below for full triage):

- **Row 1 (BTC$^-$ best F)**: K1025b best F is 24.31 (lag 1), not "~15". The K1025 column reports "18.96" which is the lag-1 value (best). Symmetric reporting requires K1025b also report 24.31. The "~15" appears to be an eyeballed median or the lag-3 value (16.85). Definitely wrong relative to the K1025 convention.

- **Row 5 (QR upper-tail amplification)**: K1025b $\beta_{0.95}/\beta_{0.5} = 16.29/2.83 = 5.75\times$, **not** "~11×". The "~11×" claim is repeated in the §6.4 narrative (line 312: *"the upper-tail amplification ratio is $8.5\times$ for VIX vs roughly $11\times$ for VXN"*), so it appears in *two places*. Possible source of the error: the paper-author may have mistakenly used $\beta_{0.75}/\beta_{0.5} = 11.34/2.83 = 4.0\times$ — no, that's 4×, not 11×. Or maybe mistook $\beta_{0.75}$ value (11.34) as the amplification ratio itself. Whatever the slip, the claim is wrong.

The amplification ratio is the paper's *signature finding* — every reviewer will compute it from $\beta_{0.95}$ and $\beta_{0.5}$ themselves to check the headline number. Discovering that the K1025b column claims "~11×" but a 30-second arithmetic check yields 5.75× will damage referee trust *materially* — not just for the K1025b row but for the whole §5 amplification narrative.

**Reproduce.py gate did not catch this** because the 29 byte-match checks cover K1025 only (per the task brief: *"reproduce.py only verify K1025 main results"*). This is exactly the kind of error the gate is designed to prevent, but K1025b is outside its coverage. **Recommendation for fix**: extend reproduce.py with a small K1025b verification block (5–7 byte-match checks for Table 7 K1025b column) before submission, or at minimum manually byte-match Table 7 against `k1025b_results.json` once.

### 4.3. K1025 vs K1025b magnitude framing

The §6.4 narrative claims "Quantitative magnitudes shift modestly: the upper-tail amplification ratio is $8.5\times$ for VIX vs roughly $11\times$ for VXN, the OOS DM statistic is $-0.98$ vs $-0.43$ (both non-significant)..." 

**With the corrected 5.75× number** (K1025b is *less* amplification than K1025), the narrative direction reverses: VIX has *stronger* upper-tail amplification (8.5×) than VXN (5.75×). This is *interesting* in itself — it suggests the BTC-to-equity-fear amplification is more pronounced in the broad-market VIX than the tech-concentrated VXN — but the current paper text reads the opposite (claiming VXN has *stronger* amplification at 11×). **Once corrected, the narrative will need revision** from "shifts modestly" to "directional shift: VXN has weaker amplification than VIX, consistent with the broad-market mean-reversion of VIX relative to the more momentum-driven tech-concentrated VXN" — this is actually a *richer* finding than what the paper currently claims. The fix improves the paper's substance.

**On the OOS DM**: K1025 t = -0.98 vs K1025b t = -0.43. Both NS. The framing "(both non-significant)" is honest. The fact that K1025b is closer to zero is also informative — the BTC→VXN OOS predictability null is even stronger than BTC→VIX. **Honest acknowledgement: yes**.

### 4.4. Does §6.4 close the cross-paper meta-eval Section 6 Issue 3 blocker?

The cross-paper meta-eval (`cross_paper_meta_eval_2026_04_28.md` line 229) named the multi-asset OOS extension as a "**blocker for review-stage → ready_for_submission promotion** if the goal is IJFMIM/JEF placement". The K1025b extension addresses this directly:

- ✓ Adds a second crypto-equity-fear pair (BTC→VXN/QQQ).
- ✓ Demonstrates the qualitative pattern survives the index swap (5/5 lags downside causality, sign reversal QR, 2020-only regime, DY net-receiver, OOS null).
- ✓ Honest acknowledgement of remaining scope limit (no non-U.S. extension).

**Once the Table 7 numerical errors are fixed**, this would close the cross-paper meta-eval blocker. **Pre-fix**, however, the blocker is *not* closed — a reviewer who spots the "~11×" error will read it as "the multi-asset extension was rushed, the headline magnitude in the new table is wrong". This converts what should have been a positive (multi-asset robustness) into a negative (rushed addition with arithmetic errors). **Verdict: Issue 3 *will be* closed once NEW MAJOR-1 is fixed; not closed in v3 as-shipped**.

### 4.5. "Honest acknowledge" non-extension framing defensibility

Line 338: "We do not extend the analysis further to non-U.S. equity-fear gauges (e.g., Euro Stoxx VSTOXX, Nikkei VXJ) here, primarily because the BTC trading day overlaps less cleanly with overseas equity sessions and the dataset alignment introduces additional joint-stationarity concerns; this is a natural extension we leave to future work."

This is **defensible** for a 17-page short-form paper targeting IJFMIM. The trading-day alignment concern is technically valid. A persistent reviewer might still push for VSTOXX in R&R (the German equity / U.S. equity correlation literature has standard solutions for the daily-vs-overnight alignment problem), but that is an R&R-class request, not a desk-reject blocker. **Defensibility: yes**.

---

## 5. v3 New Issue Detection (Regression Check)

### NEW MAJOR-1 — Table 7 K1025b column has two numerical errors

**Severity**: MAJOR (review-blocker for top-tier; would fail an IJFMIM/JEF desk-check arithmetic verification)
**Location**: Table 7 line 322 (BTC$^-$ best F = "~15") and line 326 (QR amplification = "~11×"), plus §6.4 narrative line 312 ("roughly 11× for VXN")
**Problem**: 
- BTC$^-$ best F should be **24.31** (lag 1), not ~15.
- QR upper-tail amplification ($\beta_{0.95}/\beta_{0.5}$) should be **5.75×**, not ~11×.

**Why MAJOR**: 
1. The amplification ratio is the paper's signature empirical finding. Numerical error in the new robustness column undermines the credibility of the K1025 8.5× headline (a referee who finds the K1025b column wrong will start re-checking the K1025 column).
2. Reproduce.py 29-check gate does not cover K1025b → error went undetected through the v3 commit pipeline.
3. The narrative claim "VXN amplification *stronger* than VIX" reverses with the correct 5.75× number; current §6.4 wording must also be updated.

**Suggested fix**:
1. Update Table 7 line 322: K1025b BTC$^-$ best $F$ = **24.31** (with note in caption: "best $F$ = lag-1 value").
2. Update Table 7 line 326: K1025b amplification = **5.8×** or **$\sim 5.75\times$**.
3. Update §6.4 line 312 narrative: rewrite from "$8.5\times$ for VIX vs roughly $11\times$ for VXN" to "$8.5\times$ for VIX vs $\sim 5.75\times$ for VXN — a *weaker* amplification in the tech-concentrated VXN compared with the broad-market VIX, consistent with VIX's higher sensitivity to S&P 500 mean-reversion dynamics."
4. Add 5–7 K1025b byte-match checks to `reproduce.py` to extend the gate coverage.

**Estimated effort**: 30 minutes (Edit Table 7 + §6.4 sentence + extend reproduce.py).

### NEW MED-1 — Table 7 column-ordering and "best F" convention asymmetric

**Location**: Table 7 line 320 (column header "K1025 (S\&P 500) | K1025b (NASDAQ-100)") and rows 1, 5
**Problem**: 
- Row 1 reports K1025 "best F" as 18.96 (the lag-1 value), but the corresponding K1025b "best F" is mistakenly approximated as ~15. After the NEW MAJOR-1 fix to 24.31, the convention is consistent.
- The Table 7 caption ("Multi-asset OOS robustness") implies the table is OOS-focused, but the table contains both in-sample (Granger F, QR β) and OOS (DM stat) metrics. Either the caption should be broader ("Multi-asset robustness") or the in-sample rows should be moved to a separate Table 7a.

**Why MED**: Caption-content mismatch is a copy-edit class issue but a JIMFIM editor will flag it.
**Suggested fix**: Rename Table 7 caption to "Multi-asset robustness: K1025 (BTC$\to$VIX, SPY) versus K1025b (BTC$\to$VXN, QQQ) across in-sample and OOS specifications." 
**Estimated effort**: 5 minutes.

### NEW MED-2 — §4.1 53pt overfull \hbox not fully fixed (regression of v2 NEW MED-2)

**Location**: line 131-133, main.log line 288: `Overfull \hbox (80.78117pt too wide) in paragraph at lines 131-133`.
**Problem**: v2.3 hotfix split the original 53pt-overfull sentence into two, but the *resulting* line still overflows by 80.78pt (worse than v2's 53.10pt). The split happened mid-sentence at "...errors. We use the Newey-West kernel..." but the second sentence inherited the long compound clause "...the default specification of the \texttt{statsmodels.tsa.stattools.grangercausalitytests} routine that generates our $F$-statistics" which is the actual source of the overflow.
**Why MED (not MAJOR)**: 80pt overfull is visually disruptive (will produce a noticeably stretched line in the PDF) but does not affect content correctness.
**Suggested fix**: Wrap the long `\texttt{statsmodels.tsa.stattools.grangercausalitytests}` reference into a footnote: "...the default specification of the routine that generates our $F$-statistics.\footnote{We use \texttt{statsmodels.tsa.stattools.grangercausalitytests} from statsmodels v0.14.}"
**Estimated effort**: 5 minutes.

### NEW MED-3 — §6 structural balance after K1025b expansion

**Location**: §6 (Robustness), now 4 subsections (was 3 in v2)
**Problem**: §6.4 (multi-asset, ~30 lines incl. Table 7) is materially longer than §6.1 (~6 lines), §6.2 (~5 lines), §6.3 (~5 lines). The Robustness section's center-of-gravity is now §6.4. This is *not* a defect — multi-asset is genuinely more substantive than the other three robustness checks — but the imbalance is visible.
**Why MED (not MINOR)**: A JIMFIM/JEF reviewer may suggest promoting §6.4 to its own section between §6 and §7 (e.g., "§6.5 Multi-asset OOS Robustness" → "§7 Multi-asset OOS Robustness", renumbering current §7 as §8). Current placement under "Robustness" is defensible because the multi-asset is fundamentally a robustness check, but the length asymmetry invites the question.
**Suggested fix (any of three)**:
1. **Leave as-is** (defensible for v3; document rationale in cover letter as "scope-appropriate single-section robustness").
2. Promote §6.4 to standalone §7 (renumbering §7 OOS → §8, §8 → §9, §9 → §10) — adds 3 sections to renumber, risk of cross-ref drift.
3. Compress §6.4 narrative by ~30% (move Table 7 detail rows into appendix, keep abstract-style summary in §6.4 body).

**Recommendation**: Option 1 for v3 → submission; reconsider after first peer-review feedback.

### NEW MIN-1 — §6.4 line 322 K1025b BTC$^-$ entry needs lag-explicit

**Location**: line 322 ("Asymmetric Granger BTC$^-$ best $F$ (lags 1–5)")
**Problem**: After NEW MAJOR-1 fix to 24.31, the table will show K1025 = 18.96 and K1025b = 24.31, both at lag 1. Currently the column header just says "(lags 1–5)" — adding "(lag 1, best)" or "(best across lags 1–5)" would help clarity.
**Suggested fix**: Add lag specifier in the row label or caption.

---

## 6. Stage Gate Criteria Check

| Gate | Threshold | v2 status | v3 status | Pass? |
|------|-----------|-----------|-----------|-------|
| latex score | ≥ 4★ | 4.40 | **4.30** (post-error; would be 4.55 post-fix) | **borderline / FAIL** |
| CRITICAL count | 0 | 0 | 0 | ✓ |
| SEVERE count | 0 | 0 | 0 | ✓ |
| MAJOR count | 0 (per cross-paper feedback pattern: 0) | 0 | **1** (NEW MAJOR-1 Table 7) | **FAIL** |
| MED count | ≤ 3 | 3 | 3 | ✓ |
| Reproduce gate | green + ≥95% match | 100% match, alert green | 100% match, alert green (K1025 only) | ✓ (caveat: K1025b not covered) |
| Compile clean | 0 errors | 0 errors, 5 hbox | 0 errors, 1 underfull + 5 overfull (1 box regressed from 53pt → 80pt) | ✓ borderline |
| Cross-paper meta-eval blocker | Issue 3 closed | open | **conditionally closed** (closed *after* MAJOR fix) | **FAIL pre-fix; PASS post-fix** |

**Pre-fix verdict**: 6/8 gates pass. **Two gates fail**: MAJOR count (1, must be 0) and cross-paper meta-eval blocker (Table 7 errors prevent the K1025b extension from successfully closing the multi-asset blocker).

**Post-fix verdict** (after Table 7 + §6.4 narrative correction): 8/8 gates pass; latex score rises to ~4.55; advance recommendation flips to YES.

---

## 7. Stage Recommendation

**Recommendation**: **STAY AT `review` STAGE**. Do NOT advance to `ready_for_submission` until NEW MAJOR-1 is fixed.

**Justification**:
1. The cross-paper meta-eval feedback pattern (`feedback_paper_cross_paper_meta_eval`) explicitly requires 0 MAJOR for stage-gate advancement. v3 introduced 1 MAJOR (Table 7 numerical errors). One round of v3.1 hotfix is required to close this and re-enter the stage gate.
2. The error is in the paper's signature numerical claim (upper-tail amplification ratio), reported in *two places* (Table 7 row 5 + §6.4 narrative line 312). A JIMFIM/JEF reviewer will catch this in a 30-second arithmetic check and the discovery damages credibility for the entire amplification narrative. Submitting without fix would risk a desk-reject on the K1025b multi-asset extension despite it otherwise being well-designed.
3. The Reproduce.py 29-check gate does not currently cover K1025b. Recommended to extend with 5–7 K1025b byte-match checks (e.g., qr_beta_05, qr_beta_95, dy_net_btc, dm_stat, granger_2020_F, asymmetric_neg_lag1_F, qr_amplification_ratio) before the v3.1 commit.
4. Once the fix is applied (estimated 30–60 minutes for table edit + narrative correction + reproduce.py extension + recompile), v3.1 will pass all 8 gates with score ~4.55 and the advance recommendation flips to YES.

**Next-round work suggested (v3.1)**:
- **Priority 1 (mandatory)**: Fix Table 7 row 1 (BTC$^-$ best F: ~15 → 24.31) and row 5 (amplification: ~11× → ~5.75× or 5.8×); update §6.4 line 312 narrative to reflect the *weaker* VXN amplification framing.
- **Priority 2 (mandatory)**: Extend `reproduce.py` with K1025b verification block (5-7 checks).
- **Priority 3 (recommended)**: Wrap §4.1 long `\texttt{statsmodels...}` into footnote to fix 80pt overfull.
- **Priority 4 (optional)**: Update Table 7 caption to clarify in-sample + OOS scope.
- **Priority 5 (optional)**: Compress §1 contribution paragraph from ~330 → ~250 words.

**Estimated effort to ready_for_submission**: 1 main-thread slot for v3.1 fix-batch (~1 hour). Cycle: v1 → v2 → v3 → v3.1 → submission. Total 4 review-revision rounds.

---

## 8. Predicted Journal Outcomes

| Journal | Tier | v2 prediction | v3 prediction (post-fix v3.1) | v3 prediction (as-shipped, pre-fix) | Δ vs v2 |
|---------|------|---------------|-------------------------------|-------------------------------------|---------|
| **IJFMIM** (1st target) | A- | R&R high probability, accept after one revision | **R&R very high probability**, accept after one revision; multi-asset extension closes the most likely referee pushback ("why only S&P?") | **R&R medium**, with one revision dedicated to fixing Table 7 K1025b errors before substantive review begins | post-fix +; pre-fix unchanged |
| **JEF** (2nd) | A | R&R high probability, 1–2 revisions | **R&R high probability**, multi-asset DM null robustness reads as discipline strength | **R&R medium-low**; JEF's forecasting-focused readership is more likely to drill into Table 7 numbers and catch the error | post-fix +; pre-fix − |
| **FRL** (backup) | B+ | Accept high (loses §8.2 reconciliation if condensed) | **Accept very high**; multi-asset extension actually fits FRL's "concise robustness check" preference | **Accept medium**; FRL would catch the Table 7 error but is more forgiving in R&R | post-fix +; pre-fix unchanged |

**v2 baseline cited in task brief: 90% IJFMIM/JEF acceptance probability**. 
- **v3.1 post-fix**: **94–95%** (multi-asset robustness raises probability by ~4-5pp; cross-paper meta-eval Issue 3 resolved cleanly).
- **v3 as-shipped (pre-fix)**: **78–82%** (Table 7 errors lower probability by ~8-12pp because they directly undermine the K1025b column's credibility and indirectly question K1025 column too).

**Strategic submission recommendation**: Do **NOT** submit v3 as-shipped. Run v3.1 hotfix, re-verify Table 7, then submit to IJFMIM. The 1-hour v3.1 fix preserves the full +4-5pp benefit of the K1025b extension; submitting pre-fix forfeits the benefit and adds a credibility risk.

---

## 9. Cross-Cutting Observations on the v2 → v3 Process

### Strengths

1. **v2.3 γ qualitative footnote is exemplary research-honesty**. The fix replaced unverifiable specific claims with explicit "left to a follow-up extension" + footnote forward-ref. This sets a template for future paper-update workflow when an in-sample diagnostic is added that lacks JSON traceability: "soften to qualitative" is now a documented Option-2 fix from the v2 NEW MED-1 critique, and v2.3 demonstrates it works cleanly.

2. **v2.4 §1 contribution rewrite is the highest-impact non-experimental change in the v1→v3 cycle**. Reordering "lead with empirical novelty, supporting methods" reframes the paper's contribution lever from "synthesis" (weakest top-tier lever) to "new empirical pattern + structural-watershed regime + discipline" (strong top-tier lever). The cross-paper meta-eval correctly identified this as "the single most consequential revision for journal placement"; v3 delivered it.

3. **K1025b multi-asset OOS extension closes a real top-tier blocker**. Cross-paper meta-eval Section 6 Issue 3 explicitly named single-asset OOS as a blocker; v3 §6.4 + Table 7 directly address it. Once the table errors are fixed, this is a clean closure.

### Weaknesses to address in v3 → v3.1

1. **K1025b numbers were not byte-match-verified before commit**. The Table 7 errors (~15 should be 24.31; ~11× should be 5.75×) are exactly the kind of error that pre-commit reproduce.py extension would have caught. **Lesson**: when adding a new experiment to a paper, *extend reproduce.py first* to cover the new JSON, *then* write the table. This is a generalizable workflow rule for paper-update agents.

2. **Overfull \hbox at §4.1 regressed from 53pt → 80pt**. The v2.3 split-into-two-sentences fix improved sentence structure but inherited the long `\texttt{statsmodels...}` clause into the second sentence. **Lesson**: when fixing an overfull box by sentence split, the *long content phrase* is often the actual culprit, not the sentence structure; wrap the phrase into a footnote or short ref instead of just adding a period.

3. **The §6.4 narrative claim "VXN amplification stronger than VIX" reverses with the correct numbers**. The fix is *substantive*, not just numerical: VIX has *stronger* amplification (8.5×) than VXN (5.75×), which is itself an interesting finding to incorporate. **Lesson**: when verifying numerical errors, also verify the directional narrative claims that depend on those numbers; an error correction can change the qualitative story.

---

**Reviewer signature**: latex-academic-reviewer (Claude main thread, subagent run, 2026-04-28)
**Round**: v3, third-pass post-K1025b-multi-asset review
**Next round trigger**: after main thread implements v3.1 hotfix (Table 7 row 1 + 5 + §6.4 narrative + reproduce.py K1025b extension + §4.1 footnote). v3.1 should be a single-commit fix batch with re-verified compile-clean and reproduce-green output.

**Verdict**: **0 CRITICAL / 0 SEVERE / 1 MAJOR / 3 MED / 4 MINOR; score 4.30 / 5; stage rec: STAY at `review` (do NOT advance to `ready_for_submission` until v3.1 fixes Table 7 numerical errors).**

**Post-fix projected verdict (v3.1)**: 0 CRITICAL / 0 SEVERE / 0 MAJOR / 2 MED / 4 MINOR; score 4.55 / 5; stage rec advance to `ready_for_submission`.
