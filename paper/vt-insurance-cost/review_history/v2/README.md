# Review Round v2 — vt-insurance-cost

**Date**: 2026-07-06
**Triggered by**: First full formal review round (per paper-review-cycle SOP). Prior `review_history/` entries were partial: `v1/` = citation-only diagnostic (2026-07-05); `audit_2026-06-10/` = targeted footnote/spec fixes; `diagnosis_v1/` = reproduce-divergence resolution. **This is the first round that pairs a full latex structural/methodology review with a citation check.**
**Manuscript**: `main.tex` (mtime 2026-07-01 18:37, 279 lines)
**Reviewers**:
- latex-academic-reviewer — `codex exec` (GPT-5.4) independent deep review, code-verified by main thread (Claude opus)
- citation-verifier — main thread, consolidating the byte-identical-file v1 web-verified findings

## Overall Assessment

| Reviewer | Verdict | Rating |
|---|---|---|
| LaTeX / methodology | 需大改 (Major revision) | 2.5 / 5 ★ |
| Citation | ⚠️ Requires correction (1 MAJOR / 8 MEDIUM / 2 minor) | ⚠️ |

**Combined verdict: 需大改 (Major revision).** Not submittable to JFE/RFS/JoE at current state; a credible **FRL / IJF / JPM** submission after the 3 SEVERE fixes. Suggested tier after revision: FRL/IJF (~3.5★).

## Issues Summary

### SEVERE (3) — blocking submission
1. **S-01 (code drift, CONFIRMED)**: S4 "50/50" is implemented as a *daily constant-weight* portfolio (`0.5*spy + 0.5*gld`, no cost), but Table 1 labels it "monthly rebalancing." Undercuts the headline S2 0.63 vs 50/50 0.50 comparison (true monthly 50/50 Sharpe ≈ 0.59). Touches abstract, Table 1, §4.4, Discussion, Conclusion.
2. **S-02 (evidence)**: Cross-OOS covers only 4/6 windows, S2 wins 1/4; omitted windows (2017–18, 2021–22) are the decisive ones. Insufficient to frame S2 cost-reduction as a deployable design principle.
3. **S-03 (code drift, CONFIRMED)**: S3 (Smooth VoV) is a *continuous* `clip(z,0,1)` blend in code, but the paper's equation is a *binary 0.5* blend — mathematically different functions. 0.3/0.7 sensitivity claim has no output in the package.

### MEDIUM (latex 7 + citation 8)
- latex: Eq.(3) unit/`N` conflict (M-01); Table 2 rounding note (M-02); threshold cherry-pick risk (M-03); apples-to-apples caveat (M-04); DM inference scope (M-05); 54 vs 63 bps / 2006–2024 vs 2012–2024 disclosure (M-06); gold crisis-alpha table missing (M-07).
- citation: DOI/APA completeness (C-02); 12/VIX over-attribution (C-03); perchet year (C-04); cboe2014 unverifiable (C-05); harvey2018 turnover claim (C-06); harvey2016 DM scope (C-07); liu2019 overstated (C-08); fleming2001 left-tail (C-09).
- **MAJOR citation**: hasbrouck2009 does not directly support the 1–2 bps SPY spread underpinning the TX-cost assumption (C-01).

### MINOR (latex 4 + citation 2)
- latex: lag notation (m-01); CRRA header (m-02); CRSP-precision claim unsupported (m-03); contribution over-ambitious (m-04).
- citation: moreira "formalized" priority wording (C-10); huang2015 key hygiene (C-11).

## Verified clean (not issues)
- **Lookahead**: verified clean (z_t uses same-day VVIX but shifted before next-day return; code uses `*_lag` features; corroborated by error_log 2026-05-06 K547 audit). Only the LaTeX *notation* should show the lag (m-01).
- **Decomposition identity** `IP_total = IP_opp + IP_direct`: holds under net/gross definitions in code.
- **Orphan/undefined citations**: none (17↔17 machine match).

## Action Plan for v3
**Main-thread must-fix (priority)**:
1. S-01 — fix or relabel 50/50 benchmark, re-run all dependent numbers.
2. S-03 — reconcile S3 equation with code (or re-run to match paper).
3. S-02 — run 2017–18 + 2021–22 windows (needs compute; can queue), report 6/6, downgrade S2 framing if weak.
4. C-01 — fix Hasbrouck SPY-spread support.
5. M-01/M-05/m-01 + C-02..C-09 — equation/notation/inference clarifications + citation corrections.

**Deferrable to v4**: m-02/m-03/m-04, C-10/C-11, gold-regime table (M-07).

**Prediction**: S-01/S-02/S-03 + C-01 resolved and M-01/M-05 clarified → credible FRL/IJF submission (~3.5★). JBF+ needs cross-asset external validation + formal inference (m-04).

## Files in this round
- `latex_review_report.md`
- `citation_check_report.md`
- `README.md` (this file)

## Reviewer source notes
- latex review: `codex exec` (GPT-5.4, ChatGPT auth) — no fallback needed (codex-cli 0.142.3 healthy). The two SEVERE code-drift findings (S-01, S-03) were independently re-verified by main-thread `grep` of `experiments/k811v2_*.py`.
- citation review: consolidated from v1 web-verified diagnostic (main.tex byte-identical since 2026-07-01); must re-run web verification when v3 text changes.

## Next round trigger
After main thread completes v3 revision (S-01/S-02/S-03 at minimum) → new round → `review_history/v3/`.
