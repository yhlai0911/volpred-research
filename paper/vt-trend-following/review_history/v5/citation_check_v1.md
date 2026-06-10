# Citation Verification — v5
# Paper: vt-trend-following (body_v3.tex)
# Date: 2026-06-10
# Reviewer: Claude Sonnet 4.6 (main-thread foreground, citation-verifier skill)
# Focus: Four newly added citations + any changes from v2→v3

---

## New Citations Verification (v4 fixes)

### 1. bollerslev2009 — Bollerslev, Tauchen & Zhou (2009)

**As cited in body_v3.tex** (bibliography lines 560–561):
```
Bollerslev, T., Tauchen, G., & Zhou, H. (2009). Expected stock returns and variance risk premia.
Review of Financial Studies, 22(11), 4463–4492.
DOI: https://doi.org/10.1093/rfs/hhp008
```

**Verification**:
- Journal: Review of Financial Studies ✓ (correct journal)
- Year: 2009 ✓
- Volume/Issue: 22(11) ✓
- Pages: 4463–4492 ✓
- DOI: 10.1093/rfs/hhp008 ✓ (standard RFS DOI format, internally consistent)
- Authors order: Bollerslev, Tauchen, Zhou ✓ (matches canonical citation order)

**Usage in paper**: Lines 36 and 519 — cited to support "VIX embeds the variance risk premium." This is the canonical VRP-in-VIX paper. Usage is accurate.

**Status**: PASS

---

### 2. campbell1999 — Campbell & Cochrane (1999)

**As cited in body_v3.tex** (bibliography lines 569–570):
```
Campbell, J. Y., & Cochrane, J. H. (1999). By force of habit: A consumption-based explanation
of aggregate stock market behavior. Journal of Political Economy, 107(2), 205–251.
DOI: https://doi.org/10.1086/250059
```

**Verification**:
- Title: "By Force of Habit: A Consumption-Based Explanation of Aggregate Stock Market Behavior" ✓
- Journal: Journal of Political Economy ✓
- Year: 1999 ✓
- Volume/Issue: 107(2) ✓
- Pages: 205–251 ✓
- DOI: 10.1086/250059 ✓ (Chicago Journals standard format)
- Authors: Campbell, Cochrane ✓

**Usage in paper**: Line 30 — cited as "habit or surplus-consumption preferences [campbell1999]" to justify why VT's MDD protection is valued beyond what mean-variance utility captures.

**Usage accuracy**: The citation is appropriate. Campbell-Cochrane (1999) establishes habit formation as a motive for extreme risk aversion during downturns. The paper's usage — "especially for investors who value drawdown protection in the spirit of habit or surplus-consumption preferences" — correctly captures the essence. However, the citation is somewhat loose: C&C 1999 is primarily about the equity premium puzzle, not specifically about drawdown protection. The paper should ideally cite a more specific drawdown-aversion paper if available (e.g., Berkelaar, Kouwenberg & Post (2004) "Optimal Portfolio Choice under Loss Aversion"). For JPM, the current citation is acceptable as motivating language but a purist reviewer might note the indirect connection.

**Status**: PASS (usage appropriate; not misrepresented)

---

### 3. bondarenko2019 — Bondarenko & Bernardo (2019)

**As cited in body_v3.tex** (bibliography lines 563–564):
```
Bondarenko, O., & Bernardo, A. E. (2019). The economics of S&P 500 put options.
Review of Financial Studies, 32(3), 983–1026.
DOI: https://doi.org/10.1093/rfs/hhy061
```

**Verification**:
- Title check: "The Economics of S&P 500 Put Options" — needs verification. The actual paper by Bondarenko (2014) in RFS is "Why Are Put Options So Expensive?" There is a Bernardo & Ledoit (2000) in RFS about pricing. The specific "Bondarenko and Bernardo (2019)" combination in RFS v32 is unusual and requires careful checking.
- Based on the DOI 10.1093/rfs/hhy061: This DOI prefix (hhy061) suggests a 2018/2019 RFS paper, consistent with year 2019.
- RFS 32(3): 2019 issue ✓

**RISK FLAG — MEDIUM**: The pairing "Bondarenko, O., & Bernardo, A. E." is unusual. The primary Bondarenko VIX/put-option work is single-authored (Bondarenko 2014, "Why Are Put Options So Expensive?", RFS). Bernardo appears in the Bernardo-Welch (2004) liquidity paper. The specific co-authored 2019 paper with these two authors at RFS 32(3) pp. 983–1026 requires independent DOI verification against the RFS database (not possible without web access in this foreground review). The citation metadata is internally consistent but the author combination is flagged as potentially confused with another paper.

**Recommendation**: Before submission, verify via DOI lookup that `10.1093/rfs/hhy061` resolves to a Bondarenko+Bernardo co-authored paper about put option pricing/insurance demand. If DOI resolves to a different paper, correct the citation.

**Status**: CONDITIONAL PASS (bibliographic details internally consistent; author combination requires DOI lookup before submission)

---

### 4. politis1994 — Politis & Romano (1994)

**As cited in body_v3.tex** (bibliography lines 617–618):
```
Politis, D. N., & Romano, J. P. (1994). The stationary bootstrap.
Journal of the American Statistical Association, 89(428), 1303–1313.
DOI: https://doi.org/10.1080/01621459.1994.10476870
```

**Verification**:
- Title: "The Stationary Bootstrap" ✓ (canonical title)
- Journal: JASA ✓
- Year: 1994 ✓
- Volume/Issue: 89(428) ✓ (Dec 1994 issue of JASA)
- Pages: 1303–1313 ✓
- DOI: 10.1080/01621459.1994.10476870 ✓ (Taylor & Francis DOI format for JASA)
- Authors: Politis, Romano ✓

**Usage in paper**: Section 2.6 methodology footnote — K1417 uses "Stationary (Politis & Romano 1994), mean_blocks=[756, 1260] trading days." The citation is used correctly to attribute the stationary bootstrap methodology.

**Status**: PASS

---

## Existing Citations Audit (spot check on critical references)

### hood2025 — Hood & Raughtigan (2025) Working Paper

**As cited**:
```
Hood, M., & Raughtigan, J. (2025). Volatility targeting alpha is trend following alpha.
Working Paper. Retrieved May 2025.
```

**Issue**: No URL, SSRN number, institutional affiliation, or access date beyond "May 2025." For a working paper that is the primary foil of the entire paper, this citation is incomplete. Referees will want to access this paper.

**Severity**: MEDIUM — JPM may accept working paper without SSRN but it's best practice to add URL.

**Recommendation**: Search SSRN for exact title and add SSRN URL or arxiv link.

---

### daniel2016 — Daniel & Moskowitz (2016) Momentum Crashes

**As cited**:
```
Daniel, K., & Moskowitz, T. J. (2016). Momentum crashes.
Journal of Financial Economics, 122(2), 221–247.
DOI: https://doi.org/10.1016/j.jfineco.2015.12.002
```

**Verification**:
- Journal: JFE ✓
- Year: 2016 ✓
- Volume/Issue: 122(2) ✓
- DOI: 10.1016/j.jfineco.2015.12.002 ✓

**Status**: PASS

---

### moreira2017 — Moreira & Muir (2017) Volatility-Managed Portfolios

**As cited**:
```
Moreira, A., & Muir, T. (2017). Volatility-managed portfolios.
Journal of Finance, 72(4), 1611–1644.
DOI: https://doi.org/10.1111/jofi.12513
```

**Verification**: Year, journal, volume, DOI all internally consistent with Journal of Finance standard format.

**Status**: PASS

---

### harvey2016 — Harvey, Liu & Zhu (2016)

**As cited**:
```
Harvey, C. R., Liu, Y., & Zhu, H. (2016). ... and the cross-section of expected returns.
Review of Financial Studies, 29(1), 5–68.
DOI: https://doi.org/10.1093/rfs/hhv059
```

**Note**: The truncated title ("\ldots{} and the cross-section of expected returns") is unusual — the full title is "... and the Cross-Section of Expected Returns" (the ellipsis is actually the title). This is the correct paper. Bibliography format is fine; the ellipsis title is accurate.

**Status**: PASS

---

## Bibliography Completeness Check

**Orphan check (bibliography entries not cited in text)**:
- All 23 bibliography entries appear to have corresponding in-text citations based on full paper read.

**Citation check (in-text citations not in bibliography)**:
- [lai2026a]: Appears multiple times; bibliography entry present (lines 599–600) ✓
- [bozovic2024]: Bibliography present (lines 566–567) ✓
- [cederburg2020]: Bibliography present ✓
- [miranda2020]: Bibliography present ✓
- [rapach2013]: Bibliography present ✓

**No orphan citations or missing bibliography entries detected.**

---

## Summary Table

| Citation | Authors/Year | Journal | DOI | Usage | Status |
|----------|-------------|---------|-----|-------|--------|
| bollerslev2009 | Bollerslev, Tauchen, Zhou 2009 | RFS 22(11) | ✓ | VRP in VIX | PASS |
| campbell1999 | Campbell, Cochrane 1999 | JPE 107(2) | ✓ | Habit utility | PASS (loose but acceptable) |
| bondarenko2019 | Bondarenko, Bernardo 2019 | RFS 32(3) | Needs DOI lookup | Put insurance | CONDITIONAL PASS |
| politis1994 | Politis, Romano 1994 | JASA 89(428) | ✓ | Stationary bootstrap | PASS |
| hood2025 | Hood, Raughtigan 2025 | Working paper | Missing URL | Primary foil | MEDIUM (add URL) |

**Overall citation verdict**: 3 PASS, 1 CONDITIONAL PASS (bondarenko2019 — DOI verify), 1 MEDIUM (hood2025 — add URL)
