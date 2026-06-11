# Fix Log — audit_2026-06-10 HIGH findings

**Paper**: eav-universal-magnitude
**Main file**: `paper/eav-universal-magnitude/body.tex`
**Fix session**: 2026-06-11 10:16–10:20 (台灣時間)
**Scope**: 5 HIGH findings, processed in three classes (A=text/口徑 done now; B=narrative decision flagged; C=compute flagged + K list). MEDIUM/LOW findings NOT addressed in this pass.
**Compile**: `xelatex body.tex` exit 0, 27 pages, `body.pdf` regenerated.
**Did NOT** run `paper-update` / upload (B-class narrative pending) and did NOT commit (main thread收尾).

---

## Class A — done (text / 口徑 layer)

### HIGH #3 — [CITATION NEEDED] placeholder (body.tex §1.3, was line 196–198) — **DONE**
- **Action**: Removed the `[CITATION NEEDED: international cross-market EAV anchor...]` placeholder.
- **Decision**: Checked `lit_review.md` A5 — it contains only **candidate searches** (Landsman & Maydew 2002; Cohen-Lou-Malloy 2014; DeFond et al. 2015) flagged as "needs NotebookLM RAG pass before drafting", NOT a verified cross-market EAV anchor. None are in `references.bib`. Their topics (international earnings *information content* / *acquisition*) are not a directly comparable EAV-magnitude anchor.
- **Per task instruction (若無 → 降級為誠實表述)**: Rewrote the third-contribution sentence to honest framing: "we contribute... by documenting, **to our knowledge, the first directly comparable cross-market estimate** of earnings-announcement volatility amplification under a single unified model specification... we are not aware of a prior study that estimates the EAV magnitude jointly across multiple international equity markets with a common pooled-MLE design." Anchored the well-established within-market EAV claim to existing verified cites `\citep{beaver1968,patell1976,patell_wolfson1979,ball_kothari1991}` (all present in references.bib).
- **Result**: No placeholder remains; no dependence on a non-existent anchor; no fabricated citation.

### HIGH #4 — θ̂_rel contradiction (body.tex §6.6 K1173 para vs tab:multistart_lr) — **DONE (footnote disambiguation)**
- **Verified both sources before editing**:
  - K1163 four-market normalization (`k1163_results.json`): tw=0.167, eu=0.194, jp=0.388, us=0.586 → this is the "developed range [0.17, 0.59]" referenced in the K1173 paragraph.
  - K1216c pooled-joint refit (`k1216c_results.json` → `per_market.{TW,US,JP}.canonical_theta_rel`): TW=0.31397, US=0.41482, JP=1.66751 → this is the multistart table (tab:multistart_lr).
- **These are genuinely DIFFERENT normalizations** (different pooled-MLE specs / normalization bases), not a single quantity with two values — so the correct fix is **footnote disambiguation, not unification** (unifying would misrepresent two distinct estimation setups).
- **Action**: Added a footnote at the K1173 "TW = 0.17 through US = 0.59" line that (a) names both systems explicitly, (b) states they share a symbol but differ in normalization base and absolute scale, (c) clarifies the "[0.17, 0.59] developed range" refers **exclusively** to K1163 four-market normalization where JP=0.388 sits *inside* the developed range (consistent with the EM-vs-developed contrast), and (d) states the larger JP=1.668 in tab:multistart_lr is a K1216c-normalization estimate **not directly comparable** to the [0.17, 0.59] range. Added `% source:` lines for both JSON provenances.
- **§6.6 θ_rel consistency re-checked**: All other θ_rel uses (Spearman trajectory ρ=0.379/+0.441 at K1216c, EU low-cluster 0.137→0.194, multistart table) are internally consistent with their respective sources. The low/high-cluster classification (≤0.25 vs ≥0.30) is a separate axis from the normalization ambiguity and remains internally consistent.

---

## Class B — flagged (narrative-scope decision, NOT self-decided)

### HIGH #2 — abstract/conclusion 3-market vs §6.6 13-market panel — **FLAGGED**
- **Action**: Added a clearly-marked `% NARRATIVE-DECISION-PENDING (audit_2026-06-10 HIGH #2)` editor note at the head of §6.6 (`sec:cross_market_panel`). Did **NOT** rewrite abstract/conclusion (reserved for main thread / boss per CLAUDE.md narrative state machine).
- **Two options (detailed in the note + below)**:
  - **Option A** — Expand abstract + intro contributions + conclusion to make the 12/13-market panel and the three structural drivers (analyst attention; sector FE F=689.5; ownership ladder ρ=0.379) part of the paper's MAIN narrative; **delete the stale conclusion future-work bullets** ("extending to UK, HK, or Eurozone") that §6.6 already covers (HK and EU are already in the panel → current self-contradiction).
  - **Option B** — Demote the 12/13-market panel to a ROBUSTNESS APPENDIX; keep abstract/conclusion as a focused 3-market paper; reframe §6.6 as supporting evidence.
- **Agent recommendation**: **Option A**. The panel materially strengthens the headline cross-market regularity + magnitude-ordering thesis and is too central to relegate to an appendix. But the abstract/conclusion rewrite is a main-thread narrative task; flagged, not executed.

---

## Class C — flagged + compute K list (heavy compute, NOT self-run)

### HIGH #1 — multistart FRAGILE undermines main Table 1 — **FLAGGED + caveat footnote added**
- **Action**: Added a caveat footnote to the Table 1 (`tab:main_results`) caption stating the headline K1145/K1147/K1150 estimates are single-init L-BFGS-B, NOT yet re-estimated under the 100-multistart protocol; points to §6.6.4 / tab:multistart_lr two-basin evidence; flags that whether the θ̂_EAV point estimates, significance, and US>JP>TW ordering survive a matched 100-multistart re-estimation is an open verification item.
- **Compute needed (main thread to dispatch)**: Re-run the **main three-market spec under matched 100-multistart protocol** —
  - **K1145** (Taiwan, θ_EAV=6.36e-5)
  - **K1147** (United States, θ_EAV=1.91e-4)
  - **K1150** (Japan, θ_EAV=1.41e-4)
  - Protocol = same as the §6.6.4 audit: ≥100 random inits (seeds 43…142), DE seed 49, K-means seed 42, LR test canonical-vs-refined, report whether magnitude ordering US>JP>TW holds. Update Table 1 + abstract numbers after re-estimation.

### HIGH #5 — reproduce gate stale (only Tables 1–3, §6.6 uncovered) — **FLAGGED + K list**
- **Action**: Did NOT rewrite reproduce.py (量大). Flagged for compute dispatch.
- **K list to add to reproduce.py coverage** (§6.6 cells currently outside the gate): **k1163, k1165, k1166, k1168, k1171, k1172, k1207, k1213, k1216, k1216b, k1216c, k1173**.
  - Specific cells to bind: eq:analyst_trajectory (3.236→3.808; k1165/k1166/k1168/k1172/k1171), K1207 sector FE F=689.5 / incR²=0.148, K1216c ρ=0.379/p=0.201/Harvey t=1.36 (N=13), K1163 θ_rel=0.194 / boot t=4.81 / CI / placebo z=22.27, tab:multistart_lr all 10 rows (k1213/k1216/k1216b/k1216c canonical+refined θ_rel + LR stats), Figures 5A–5E, K1173 Δρ=-0.056.
  - **Also**: re-bind the 4 `% source: k1222b_revision_guide.md` pointers (body.tex ~lines 804, 926, 985, 1064 in pre-edit numbering) to actual results-JSON fields (revision_guide is a markdown修訂指南, violates Table-row→JSON binding hard rule).
  - Re-run gate to green before next review round.

---

## Compile verification
- `xelatex -interaction=nonstopmode -halt-on-error body.tex` → **exit 0**, 27 pages, `body.pdf` written.
- One transient fix during this session: an unescaped `_` in the new Table 1 footnote ("audit_2026-06-10") triggered a Missing-$ error; removed it → clean build.
- **Pre-existing (out of scope)**: `\bibliographystyle{jfe}` references a missing `jfe.bst` → bibtex fails → citations show as undefined in the live build. This is pre-existing (body.tex line 1316 already comments "For compilation/review: replace with \bibliographystyle{plainnat} temporarily") and unrelated to these fixes. Verified on a temp copy with `\bibliographystyle{plainnat}`: bibtex exit 0, **0 undefined citations** — all newly-added \citep keys resolve correctly against references.bib.

---

## 2026-06-11 follow-up: HIGH #2 Option A narrative rewrite (boss-confirmed) — RESOLVED

**Trigger**: Task `paper_body_eav_optionA_narrative_2026_06_11` (P2, claimed by hourly-13 at 2026-06-11 13:07 台灣時間). Depends on `experiment_eav_multistart_reestimate_2026_06_11` (K1470, completed 2026-06-11 12:14 with CONDITIONAL_PASS).

**K1470 100-multistart on main 3-market spec** (`experiments/k1470_eav_multistart_main_spec/k1470_results.json`):
- Canonical θ_EAV: TW=6.36e-5, US=1.91e-4, JP=1.41e-4 (matches existing Table 1 / abstract; no Table 1 number change).
- Refined θ_EAV: TW=6.84e-4, US=5.34e-3, JP=2.88e-3 (10–28× canonical).
- LR: TW 1.43 (< χ²(1)=3.84, STABLE-FLAT_RIDGE); US 40.56, JP 10.78 (FRAGILE).
- Ordering check: `ordering_preserved=true` — canonical US>JP>TW preserved under refined basin.

**Narrative edits applied to body.tex** (Option A):
1. **Abstract**: Added closing block (after the within-market null) describing the 13-market institutional panel, three structural drivers (analyst attention 3.236→3.808; sector FE F=689.5, p=7.9e-14; institutional ownership refined Spearman ρ=+0.379, N=13), and the K1470 multistart-preservation result for the headline ordering.
2. **§1 Introduction — central-finding paragraph**: Extended to acknowledge the 3-market core + 13-market panel + multistart pathology as one unified contribution arc.
3. **§1.3 Relation to the Literature**: Added paragraphs (4) and (5) — (4) 13-market panel + 3 structural drivers as a primary mechanism contribution; (5) ≥100-multistart protocol as a methodological contribution for small-S shared-MIDAS+stock-FE-GJR specifications.
4. **§1.4 Paper Outline**: Reframed §5/§6/§6.6 transition to flag the 13-market panel + multistart contribution explicitly as part of the main narrative.
5. **§6.6 NARRATIVE-DECISION-PENDING comment block**: Replaced with a "RESOLVED 2026-06-11" provenance block citing boss confirmation + K1470. No surrounding § text changed.
6. **§7 Conclusion**: Replaced the "Three open directions" closing block — the prior axis (c) ("12-market panel as future deepening") is rewritten as a paragraph of *primary* findings (three structural drivers + multistart preservation of US>JP>TW); the new "Open directions" axis (c) replaces it with CA/HK/KR multistart audit completion + EU disaggregation + UK addition, plus the K1216c pre-registration band ρ ∈ [+0.30, +0.50]. The stale "extending to HK/Eurozone" future-work bullet that contradicted §6.6's panel is removed.

**Table 1 / abstract headline magnitudes UNCHANGED**: K1470 reconfirmed canonical 6.36e-5 / 1.91e-4 / 1.41e-4. No Table 1 cell rewrite required. The Table 1 caveat footnote added in the 2026-06-10 audit remains valid (TW STABLE; US/JP FRAGILE with refined point estimate 10–28× canonical but US>JP>TW ordering preserved) — caveat language in tab:main_results stays as-is; the §1 Intro / Abstract / Conclusion now also state the preservation result so readers see it without flipping to the footnote.

**Compile verification (2026-06-11 13:12)**:
- `xelatex -interaction=nonstopmode -halt-on-error body.tex` → **exit 0**, 30 pages (was 27 in 2026-06-10 audit; +3 pages from Abstract block + Intro paragraphs + Conclusion paragraph), `body.pdf` 289,973 bytes.
- Two compile passes (label resolution); no `LaTeX Error` / no Emergency stop. Pre-existing overfull-hbox warnings on lines 945/1030/1098/1228 unchanged (pre-existing typography, out of this edit's scope).
- Pre-existing `\bibliographystyle{jfe}` bibtex issue unchanged (out of scope; bibliography is body.bbl from prior bibtex pass).

**Follow-up not done in this task (deferred)**:
- HIGH #1 / HIGH #5 reproduce.py § coverage extension remains FLAGGED (K list: k1163/k1165/k1166/k1168/k1171/k1172/k1207/k1213/k1216/k1216b/k1216c/k1173/k1470). Out of scope for this narrative-rewrite task; covered by a separate paper_review / paper_body follow-up task.
- K1470's `verdict` field is null in the per-market dict structure (only `lr_test.lr_stat` populated); narrative cites the LR magnitudes + STABLE/FRAGILE classification from the K1470 knowledge.json entry (item_id=4d6e91ad) summary string and the matched §6.6.4 LR test convention. A subsequent K1470 results.json schema enrichment task (add explicit `verdict` strings) would let reproduce.py bind these cells directly.
