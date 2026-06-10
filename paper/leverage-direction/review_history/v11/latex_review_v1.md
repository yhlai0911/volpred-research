# latex-academic-reviewer — v11 Round, Review v1

- **Paper**: `paper/leverage-direction/` (main.tex → body.tex + tables_main.tex), target JBF
- **Review date**: 2026-06-11
- **Scope**: post-K903-canonicalization quality (after 2026-06-10 audit + 6 HIGH fixes per `review_history/audit_2026-06-10/fix_log.md`)
- **Verification basis**: every numeric finding below re-checked against `experiments/k903/tables/k903_table2.csv` and `k903_table3.csv` (canonical source declared in tables_main.tex `% source:` comment)
- **Companion artifacts**: `README.md` + `v11_review_report.tex` (same round, structured 10-section report)

## Verdict: **MAJOR_REVISION** — keep submission frozen

The K903 canonicalization was the right decision but was executed **paragraph-by-paragraph, not number-by-number**. Table 3 (tab:qlike) and the locations the 2026-06-10 editor visited are now canonical; the prose paragraphs and Table 2 rows the editor did *not* visit still carry pre-K903 vintage numbers. The paper currently contradicts its own canonical table in at least four places, including one same-page direct self-contradiction.

Counts (new findings only; known residuals from fix_log excluded): **HIGH 5 / MEDIUM 4 / LOW 3**.

---

## HIGH (blocking)

### H1. GLD QLIKE prose at body.tex:184 directly contradicts body.tex:144 and Table 3
- **Location**: `body.tex:184`
- **Text**: "For GLD … GJR marginally wins in 2023--2024 ($\Delta = -0.07\%$, DM $p = 0.871$) and GARCH marginally wins in 2025 ($\Delta = +0.05\%$, DM $p = 0.350$). Neither approaches significance, confirming that inverted leverage adds no forecasting value for gold."
- **Canonical (K903 table3 + tab:qlike)**: GLD 2023--24 Δ = **+0.39%**, p = **0.001*** (GARCH significantly wins); 2025 Δ = **+1.54%**, p = 0.070.
- **Why blocking**: body.tex:144 (two pages earlier, already fixed) states "symmetric GARCH *significantly outperforms* GJR in 2023--2024 (Δ = +0.39%, p = 0.001)". The same document asserts both "p = 0.001 significant" and "p = 0.871, neither approaches significance" for the same cell. A referee will catch this immediately.
- **Fix**: rewrite the GLD sentence at L184 from K903 table3: GARCH wins both periods, significantly in 2023--24 (Δ=+0.39%, p=0.001), marginally in 2025 (Δ=+1.54%, p=0.070); the "no forecasting value" framing must become "imposing asymmetry actively hurts" (matching L144).

### H2. Table 2 (tab:gamma) is mixed-vintage — only the GLD row was swapped to K903
- **Location**: `tables_main.tex:23-42` (tab:gamma)
- **Verified diff vs `k903_table2.csv`**:

| Asset | Paper (mean γ / HAC t) | K903 (mean γ / HAC t) | Match |
|---|---|---|---|
| SPY | +0.211 / +8.30 | 0.132 / 11.08 | ✗ |
| QQQ | +0.110 / +3.21 | 0.116 / 10.76 | ✗ |
| EEM | +0.180 / +4.12 | 0.087 / 11.88 | ✗ |
| GLD | +0.002 / +0.15 | 0.002 / 0.15 | ✓ (only row swapped) |
| TLT | −0.008 / −0.34 | −0.005 / −0.46 | ✗ |
| BTC | +0.117 / +1.83 | 0.072 / 2.88 | ✗ |
| SLV | −0.041 / −2.91 | −0.009 / −0.68 | ✗ |

- **Knock-on effects (substantive, not cosmetic)**:
  - The t>1.65 rule narrative (Intro `body.tex:11` + `body.tex:198`) labels **BTC "Borderline" because t = +1.83** sits "marginally above 1.65". Under K903 t = +2.88 — not borderline. The entire borderline illustration must be re-derived or re-framed.
  - **SLV "GARCH" prescription** rests on HAC t = −2.91 (significant inverted). Under K903 t = −0.68 — NS, which moves SLV from "significantly inverted" to "γ ≈ 0" class. This changes the taxonomy table and any SLV claims downstream.
  - Magnitude band "|γ| ∈ [0.12, 0.17]" (`body.tex:11`, `body.tex:198`: "between BTC's 0.117 and QQQ-2025's 0.17") is anchored on the old BTC 0.117; K903 BTC = 0.072.
- **Fix**: replace all seven rows from k903_table2.csv, update the caption (currently discloses only the GLD swap — see M4), then re-derive every prose echo of γ means / HAC t / borderline / magnitude band (L11, L143-145, L155 area, L198, L405).

### H3. SPY 2025 QLIKE prose diverges from Table 3
- **Location**: `body.tex:184`
- **Text**: "−8.818 vs −8.719 (2025, Δ = −1.13%, DM p = 0.029)"
- **Canonical**: −8.412 vs −8.268, Δ = **−1.74%**, p = **0.048** (tab:qlike + k903_table3.csv).
- **Fix**: replace the three numbers; note significance survives (p=0.048<0.05) so the qualitative claim is safe.

### H4. GLD γ appears as three mutually exclusive values across the paper
- **Locations**:
  - `tables_main.tex` tab:gamma + Intro `body.tex:11`: **+0.002** (K903 canonical)
  - `body.tex:405` (β-trend mapping): "For GLD ($\gamma = -0.088$), VT is contrarian" — the **discredited pre-K903 sign**, presented as a point estimate with no vintage caveat
  - `body.tex:172` (regime decomposition): bull −0.043 / bear +0.048 — legitimately a different statistical object, but nothing at L405 distinguishes which γ is meant
- **Why blocking**: the paper's own Table 2 caption declares the −0.067-vintage estimate non-relocatable, then §β-trend reuses essentially that vintage (−0.088) as the GLD anchor of the Spearman ρ = 1.000 mapping. If GLD's canonical γ is +0.002 ≈ 0, GLD belongs in the TLT "no directional bias" class, and the perfect rank correlation across seven assets needs re-computation or explicit re-statement of which γ vintage/window feeds Proposition 1.
- **Fix**: either (a) recompute β-trend mapping with K903 γ inputs, or (b) explicitly define the γ used in §β-trend as the in-sample 2010--2017 window estimate (it is per L399 — "γ is estimated over the in-sample period (2010--2017)") and report that window's GLD value with a footnote distinguishing it from the K903 2010--2026 quarterly mean. Currently the reader cannot tell −0.088 is a different window rather than a stale number.

### H5. BTC and TLT QLIKE prose at body.tex:186 is pre-K903 vintage; BTC direction is reversed
- **Location**: `body.tex:186`
- **Text**: "BTC-USD … GARCH slightly outperforms GJR ($\Delta = +0.14\%$, $p = 0.293$)"; "TLT … GJR achieves marginally lower QLIKE ($\Delta = -0.01\%$ to $-0.54\%$)"
- **Canonical (k903_table3.csv)**: BTC 2023--24 Δ = **−0.06%** (GJR marginally wins — opposite direction), p = 0.848; TLT 2023--24 Δ = **+0.20%**, 2025 Δ = **−0.33%** (mixed sign, not "−0.01% to −0.54%").
- **Aggravating**: `body.tex:198` already quotes the K903 BTC cell (Δ=−0.06%, p=0.848) — so BTC's QLIKE result appears with two different signs twelve lines apart.
- **Fix**: rewrite L186 from k903_table3.csv. The qualitative conclusion (indistinguishable for BTC/TLT) survives, but the directional claim "GARCH slightly outperforms" must flip or be neutralized.

---

## MEDIUM

### M1. Undefined reference `sec:model_selection` prints "??"
- **Location**: `body.tex:11` (`Section~\ref{sec:model_selection}`); `main.log:629` confirms "Reference `sec:model_selection' on page 2 undefined".
- **Fix**: add `\label{sec:model_selection}` to the Practical Model Selection Rule subsection (around `body.tex:188-198`) or repoint the ref.

### M2. Table 3 shows 9 of 12 K903 cells with no stated selection rule
- **Location**: `tables_main.tex:44-66` vs `k903_table3.csv` (12 rows). Missing: TLT 2025, EEM 2025, BTC 2025.
- **Why it matters**: the Intro's "never significantly beaten in any of the nine DM comparisons" (`body.tex:11`, `body.tex:198`) is conditioned on the 9-row subset; the three omitted 2025 cells are all NS so including them is harmless and removes any cherry-picking appearance.
- **Fix**: add the three rows (text then says "twelve comparisons"), or state the row-selection rule in the caption.

### M3. EEM "GJR" prescription in Table 2 has no DM support and clashes with K903 γ magnitude logic
- **Location**: `tables_main.tex:35` (EEM & +0.180 & … & GJR). Under K903 EEM γ = 0.087 — *below* the paper's own |γ| ∈ [0.12, 0.17] economic-significance band, while DM shows EEM indistinguishable (p = 0.949 / 0.133). Prescribing "GJR" for a γ below the band, with NS DM cells, is internally inconsistent once H2 is fixed.
- **Fix**: after the K903 row swap, re-derive Model Choice column from the stated rule; EEM likely becomes "GJR/Context" or "Either".

### M4. Table 2 caption discloses only the GLD vintage swap
- **Location**: `tables_main.tex:25` caption. After H2 the caption's framing ("The GLD row reflects the K903 canonical replication … replacing an earlier-draft estimate") is wrong for the other six rows too.
- **Fix**: once all rows are K903, simplify the caption to one provenance sentence covering the whole table (`% source: experiments/k903/tables/k903_table2.csv`).

---

## LOW

### L1. Overfull \hbox (~262pt) in the conclusions summary table region
- **Location**: `body.tex:449-466` area (see main.log). Will be flagged by JBF production.

### L2. Stale `\date{v3.3}` / version metadata in main.tex vs current draft state
- **Fix**: bump on next compile cycle.

### L3. `experiments.md` still maps to the body_v3 14-table layout
- The reproduce/traceability docs reference the obsolete table numbering; harmless for referees but breaks the self-contained replication folder promise.

---

## Known residuals confirmed (fix_log items — listed for completeness, NOT counted above)
- Reproduce gate stale: `reproduce_report.json` timestamp 2026-05-17, `alert_level: amber`, traceable_match_rate 80.9% < 95% — per paper-workflow hard rule #2 this alone blocks review/submit until rerun green. Must rerun **after** H1--H5 fixes (the fixes change tracked numbers).
- Citation verification (hood2025 / nelson2025 / xu2024) — separate citation-verifier agent.
- tab:vt unified-window recompute; §3.1 period summary table; multiple-testing paragraph; BH provenance; unused bibitems.

---

## Review-dimension summary (brief items 1--6)

1. **Logic/narrative**: Intro contribution 1 (regime-dependent downgrade) is internally coherent *as written in the Intro and §Regime sections* — the downgraded claim ("indistinguishable from zero unconditionally; inversion is regime-concentrated") is defensible and consistently stated at L11, L144, L172. It is the **un-swept prose (L184, L186, L405) and Table 2 rows** that break consistency, not the narrative redesign.
2. **Model specification/equations**: GJR-GARCH, HM regression, and DM/QLIKE formal setup are correctly stated; no derivation errors found this round. The overlapping-window HAC treatment (L152-158) correctly cites the Harri-Brorsen problem and the non-overlapping robustness check is appropriately hedged.
3. **Symbol consistency (single-window t vs quarterly-mean HAC t)**: the L198 paragraph distinguishing the two statistics is well written and the distinction is maintained where it appears — but its *numerical anchor* (BTC +1.83) is old-vintage (H2), so the distinction's flagship example fails under canonical numbers.
4. **New problems introduced by the 2026-06-10 edits**: yes — the partial sweep itself created the L144-vs-L184 self-contradiction (H1) and the BTC sign clash between L186 and L198 (H5). Paragraph transitions otherwise read smoothly; no orphaned sentences found.
5. **Structure/layout**: section balance acceptable; one undefined ref (M1); table placement fine; overfull box (L1).
6. **Writing quality**: no new overclaiming found in the swept sections; "confirming that inverted leverage adds no forecasting value" (L184) is simultaneously stale and an overclaim — dies with H1.

## Recommended fix path (ordered)
1. Build a number→K903-cell mapping for every γ / QLIKE / Δ / DM-p in body.tex (grep all numeric literals in §4), fix H1/H3/H5 prose.
2. Swap all Table 2 rows (H2) + caption (M4) + Model Choice column (M3); re-derive borderline/band prose (L11, L198).
3. Resolve GLD γ vintage in §β-trend (H4) — recompute or footnote-disambiguate per the established 3-spec disambiguation pattern.
4. Add missing label (M1) + 3 missing Table 3 rows (M2).
5. Rerun reproduce.py to green, then schedule v12 review.
