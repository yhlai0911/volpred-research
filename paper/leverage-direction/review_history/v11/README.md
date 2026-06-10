# Leverage-Direction Paper — v11 Review Round (2026-06-11)

**Reviewer**: latex-academic-reviewer (main-thread, fresh-context audit of post-2026-06-10-fix state)
**Files reviewed**: `main.tex` (abstract + bibliography), `body.tex` (513 lines), `tables_main.tex` (144 lines)
**Canonical sources cross-checked**: `experiments/k903/k903_vs_paper_diff.md`, `experiments/k903/tables/k903_table3.csv`, `experiments/k903/tables/k903_table2.csv`, `reproduce_report.json`
**Overall verdict**: ⛔ **MAJOR REVISION — keep SUBMISSION FROZEN**

## Context

The 2026-06-10 audit (`review_history/audit_2026-06-10/`) flagged 6 HIGH / 8 MEDIUM / 2 LOW and adopted "K903 canonical 全文一致化". The fix_log marked the 6 HIGH as mostly ✅. This v11 round re-audits the **current** body/tables against the K903 source and finds that the K903 alignment was **applied non-uniformly** — several HIGH-severity self-contradictions survive, plus the reproduce gate is still stale amber. The paper is NOT ready to thaw.

## Headline findings (this round)

| # | Sev | One-liner |
|---|-----|-----------|
| V11-1 | HIGH | body.tex L184 still carries pre-K903 GLD QLIKE (Δ=−0.07%, p=0.871, "Neither approaches significance") — directly contradicts Table 3 (K903: GLD 2023-24 Δ=+0.39%, p=0.001, GARCH sig. wins) AND L144 on the same finding. Same-document, two-page-apart contradiction. |
| V11-2 | HIGH | Table 2 (tab:gamma) is a **mixed vintage**: only GLD row swapped to K903 (+0.002). SPY (+0.211 vs K903 +0.132), QQQ HAC t (+3.21 vs +10.76), EEM (+0.180 vs +0.087), BTC HAC t (+1.83 vs +2.88), SLV HAC t (−2.91 vs −0.68) are all old-draft. The t>1.65 rule's headline inputs (BTC borderline, SLV significant) rest on un-reproduced numbers. |
| V11-3 | HIGH | SPY 2025 numbers diverge body vs table: body L184 = −8.818/−8.719, Δ=−1.13%, p=0.029; Table 3 (K903) = −8.412/−8.268, Δ=−1.74%, p=0.048. Both "canonical" in different places. |
| V11-4 | HIGH | GLD γ appears as **three mutually exclusive values**: +0.002 (Table 2 / Intro / L134), −0.088 (L405 β-trend mapping), −0.043 bull / +0.048 bear (L172). L405's −0.088 is the discredited old-draft sign and feeds the contrarian-VT claim. |
| V11-5 | HIGH | Reproduce gate stale + amber: `reproduce_report.json` dated 2026-05-17, alert_level=amber, traceable_match_rate 80.9% < 95%. Predates the 06-10 table rewrite and still references the obsolete 14-table layout. paper-workflow rule: green required before review/submit. README's "Reproduce gate 0 MISMATCH" is misleading. |
| V11-6 | MED | EEM Model Choice = "GJR" in Table 2, but Table 3 shows EEM 2023-24 Δ=−0.01%, p=0.949 (indistinguishable) and body L144 lumps EEM with TLT/BTC as "fail to reject". The prescribed-model-never-beaten claim holds, but "GJR" prescription for EEM has no DM support in-table — referee will ask why EEM is GJR while BTC (higher t) is "Borderline". |
| V11-7 | MED | Broken cross-ref: `\ref{sec:model_selection}` undefined (main.log "undefined references"); prints "??" in Intro L11 and L198. Label never defined. |
| V11-8 | MED | TLT row in Table 3 has only 2023-24 (no 2025 row), so "nine DM comparisons" = 9 cells shown, but K903 csv has 12 rows (6 assets × 2 periods); table silently drops TLT-2025, EEM-2025, BTC-2025, QQQ rows partially. "nine comparisons" framing needs the selection rule stated. |
| V11-9 | MED | Table 2 caption admits SPY/etc. earlier-draft only via the GLD note; the non-GLD divergences (SPY +0.211 vs +0.132 etc.) are undisclosed. Provenance note is partial. |
| V11-10 | MED | Citations hood2025 (Raughtigan / DOI 10.3905/jpm.2025.1.764), nelson2025 (SSRN 5931154), xu2024 (CFR forthcoming) unverified; hood2025 anchors Contribution 2. (carried from audit, still open) |
| V11-11 | LOW | ~9 unused bibitems in main.tex thebibliography (engle2004, longin2001, mcneil2015, kim2019, bucci2020, araya2024, campbell2017, engleGhyselsSohn2013, pattonSheppard2015). |
| V11-12 | LOW | Overfull \hbox 262pt at body L449-466 (table runs off page); title \date says "v3.3" while folder is v11. |

## Decision

The 06-10 "K903 全文一致化" was **incompletely executed**: the rewrite touched the Intro, the GLD-specific paragraphs (L134, L144), and Table 3 cells, but missed (a) the legacy GLD QLIKE prose at L184, (b) the non-GLD rows of Table 2, (c) the SPY-2025 prose at L184, (d) the GLD β-trend mapping at L405. The result is a paper that contradicts its own canonical table in ≥4 places. Plus the gate never re-ran.

**FROZEN remains correct.** Required before thaw: fix V11-1..4 (full K903 alignment of every γ/QLIKE number in prose), re-run reproduce.py against the 7-table layout to green, then re-review.

See `v11_review_report.tex` for the full structured report.
