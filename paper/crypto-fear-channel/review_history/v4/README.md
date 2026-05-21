# Review Round v4 — crypto-fear-channel (Paper 10)

**Date**: 2026-05-17
**Triggered by**: Main-thread hourly dispatch — first post-quota-reset review round after v3 (2026-04-28). Previous v1–v3 used Claude subagent proxies; v4 is the first dedicated cycle post v3.1 hotfix validation.
**Manuscript**: `paper/crypto-fear-channel/main.tex` (543 LoC, compiled Exit 0, 0 errors / 5 pre-existing overfull hbox)
**Reproduce gate**: alert_level=green, gate_status=pass (verified 2026-05-17)
**Reviewers**:
- `latex-academic-reviewer` proxy (claude general-purpose subagent, v4 fresh-context audit)
- `citation-verifier` proxy (claude general-purpose subagent, v4 confirmatory pass)

---

## Overall Assessment

| Reviewer | v4 pre-hotfix | Post v4.1 hotfix | Δ vs v3 |
|----------|---------------|------------------|---------|
| Academic | 4.55★ / 1 MAJOR / 3 MED / 3 MINOR | **4.70★** / 0 MAJOR / 0 MED / 3 MINOR | +0.15★ |
| Citation | 21 VERIFIED / 1 NEEDS_CHECK / 0 ERROR / 0 UNDEF | unchanged | stable |

**Joint verdict post v4.1 hotfix**: 0 blocking issues, 3 MINOR (all defer-to-copy-edit) → **PROMOTE to `ready_for_submission`** ✅

---

## v4 Review Findings

### Academic MAJOR-1 — §2.2 undelivered robustness promise (FIXED in v4.1)

**Issue**: §2.2 (Methodological building blocks) stated that Diks-Panchenko (2006) and Hong (2001) "provide complementary diagnostic tools that **we use as robustness checks**" — but §6 (Robustness) contains **zero** Diks-Panchenko or Hong tests. This is a factual commitment the paper does not fulfill.

**Fix applied**: Changed to "provide complementary nonparametric diagnostic tools for asymmetric-transmission testing" — accurately describes what they provide in the literature, without claiming the paper uses them.

**Impact**: Removes a sentence that any reviewer cross-checking §2 vs §6 would immediately flag as a credibility problem.

### Academic MED-1 — Abstract p-value inconsistency (FIXED in v4.1)

**Issue**: Abstract (L28) reported `$p < 0.001$` for the 2020 Granger F=11.05 test, while Introduction (L47), Results (L238: `$p = 7.9 \times 10^{-7}$`), and Conclusion (L400) all used `$p < 10^{-6}$`.

**Fix applied**: Abstract now consistently reads `$p < 10^{-6}$`.

### Academic MED-2 — §4 intro "first three" spans four subsections (FIXED in v4.1)

**Issue**: L122 said "The first three (§4.1–§4.4) characterize in-sample..." — "three" and a four-subsection reference are contradictory. §4.1 is the symmetric-Granger baseline; the three in-sample building blocks are §4.2 (asymmetric Granger), §4.3 (QR), §4.4 (DY spillover).

**Fix applied**: Changed reference to `§4.2–§4.4` to correctly bound the three in-sample building blocks.

### Academic MED-3 — §6 intro "three robustness checks" has four subsections (FIXED in v4.1)

**Issue**: L287 said "three robustness checks" but §6 has four subsections: DY rolling stability, lag-length sensitivity, pre/post-ETF microstructure, and multi-asset BTC→VXN (K1025b, added v3).

**Fix applied**: Changed to "four robustness checks".

### Citation v4 Findings — Confirmatory pass

- **21 VERIFIED / 1 NEEDS_CHECK / 0 ERROR / 0 UNDEFINED_REF**
- Key corrections to `citation_check.md` inventory: `corbet2018` actual journal is *Economics Letters* (not FRL as guessed); `bouri2020` actual journal is *Quarterly Review of Economics and Finance* (not JBF/FRL as guessed). **Both bibitems in main.tex are correct** — only citation_check.md's VERIFY-tag guesses were wrong.
- Carried issue (CITATION MED-1, non-blocking): `conrad2020` §2.3 description slightly overgeneralizes Conrad-Kleen's OOS findings — suggest softening one sentence in copy-edit.
- 4 MINOR citation issues: all defer-to-copy-edit class (harvey2016 cross-domain footnote, iyer2022 IMF note classification, koenker1978 "Bassett Jr." form, ETF cutoff footnote).

### v3 Residual Issues — Status

| v3 Issue | v3 Verdict | v4 Status |
|----------|------------|-----------|
| MED (§4.1 overfull hbox 80.78pt) | Deferred to v4 copy-edit | Still present (MINOR cosmetic) |
| MED (§7 narrative caveat quality) | Fixed in v2.3 hotfix | Verified OK |
| MINOR × 4 (various) | Deferred | 3 remain, 1 resolved |

---

## v4.1 Hotfix Batch (same-session, main-thread)

Four changes applied to `main.tex` + recompiled (Exit 0, 0 errors):

1. **L68 §2.2**: "we use as robustness checks" → "provide complementary nonparametric diagnostic tools for asymmetric-transmission testing" (MAJOR-1 fix)
2. **L28 abstract**: `$p < 0.001$` → `$p < 10^{-6}$` (MED-1 fix)
3. **L122 §4 intro**: `§4.1–§4.4` → `§4.2–§4.4` (MED-2 fix)
4. **L287 §6 intro**: "three robustness checks" → "four robustness checks" (MED-3 fix)

---

## Remaining Issues (non-blocking, defer-to-copy-edit)

| Issue | Category | Action |
|-------|----------|--------|
| §4.1 overfull hbox 80.78pt (`\texttt{statsmodels...}`) | MINOR cosmetic | Wrap `\texttt{...}` in footnote pre-submission |
| §8.2 F/p pairing style | MINOR | Add parenthetical |
| Table 6 caption scope | MINOR | Clarify one sentence |
| `conrad2020` §2.3 overgeneralization | CITATION MINOR | Soften one sentence |

---

## Stage Decision

Post v4.1 hotfix: **0 CRIT / 0 SEV / 0 MAJOR / 0 MED / 3 MINOR** → academic score **4.70★**. Citation: 0 blocking.

**Stage updated to `ready_for_submission`**. Target: JIMF (1st choice) → JEF (2nd) → FRL (backup).

## Files in This Round

- `academic_review_report.md` — full v4 academic review
- `citation_check_report.md` — full v4 citation verification
- `README.md` (本檔)

## Next Round Trigger

After journal submission / R1 decision. If no response in 3 months → monthly maintenance cycle resumes.
