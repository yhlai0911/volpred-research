# Paper 7 (vt-insurance-cost) Reproducibility Audit — Diff Report

**Audit Date**: 2026-04-17
**Auditor**: Claude Sonnet 4.6 (worktree agent-a1343ea9)
**Paper**: "The True Cost of Volatility Targeting: Decomposing the Insurance Premium into Opportunity and Transaction Components"
**Status at audit**: Submission-ready (prior review R3 SEVERE=0)

---

## Verification Summary

| Category | Count |
|---|---|
| Total numbers extracted | 101 |
| Verified OK (exact or standard rounding) | 97 |
| DIVERGE (substantive mismatch) | 1 |
| MINOR (1 bp rounding) | 1 |
| UNVERIFIABLE (no JSON source) | 2 |
| **Coverage rate** | **96.0%** |

---

## Divergent Items (sorted by severity)

### DIV-1 (LOW): "97% at 1 bps" — should be 98%
- **Location**: Section 2.3, Data
- **Paper claim**: "At 1 bps, the opportunity cost share rises to 97%"
- **Computed**: direct@1bp = 0.428/5 = 0.0856%/yr; total = 4.195 + 0.0856 = 4.281%; share = 4.195/4.281 = **98.0%**
- **rtol check**: |97 - 98| = 1 pp > rtol threshold
- **Direction**: Claim is directionally correct (higher than at 5 bps), but magnitude is off by 1 pp
- **Action (a)**: Fix "97%" → "98%" in main.tex
- **Action (b)**: Alternatively, document if a different computation method yields 97% (e.g., using total before including opportunity cost friction)
- **Action (c)**: Flag in next revision, LOW priority

### DIV-2 (MINOR): "54–80 bps" range — upper bound off by 1 bp
- **Location**: Section 3.3, "Structural Advantages of the 50/50 Benchmark"
- **Paper claim**: "approximately 54–80 bps per annum (the rebalancing premium alone plus the diversification benefit)"
- **JSON source**: K846 `part1_theoretical.theoretical_premium_ann_bps = 81.46`; `part1_empirical.premium_cagr_bps = 53.67`
- **Computed**: 53.67 rounds to 54 ✓; 81.46 rounds to **81**, not 80
- **rtol check**: |80 - 81.46| / 81.46 = 1.8% — within rtol=0.02 but not rtol=0.01
- **Direction**: Range direction is correct (empirical lower, theoretical upper)
- **Action (a)**: Change "54–80 bps" → "54–81 bps" in main.tex
- **Action (b)**: Alternatively, note that 80 bps could refer to a net-of-tx adjusted theoretical premium
- **Action (c)**: MINOR — does not affect any conclusions

---

## Unverifiable Items

### UV-1: Footnote 2012–2024 sub-period correlation ρ = 0.04
- **Location**: Footnote in Section 3.3
- **Claim**: "The 2012–2024 sub-period yields ρ = 0.04 and a rebalancing premium of 48 bps"
- **Issue**: K846 covers 2006–2024 only as a full sample; no 2012–2024 sub-period breakdown in JSON
- **Recommendation**: Add sub-period analysis to K846 and record output in JSON; or note this is an unreported sensitivity check

### UV-2: Footnote 2012–2024 rebalancing premium 48 bps
- **Same footnote** as UV-1; 48 bps not in any experiment JSON

---

## Items with Acceptable Rounding

All following items verified with abs(paper - json)/abs(json) < 0.01 or within 0.5 rounding tolerance:

| Item | Paper | JSON | Delta |
|---|---|---|---|
| S1 Ann Vol | 9.33 | 9.325 | +0.005 (ROUND_HALF_UP) |
| S2 Ann Vol | 13.72 | 13.715 | +0.005 (ROUND_HALF_UP) |
| S1 opp share (91%) | 91% | 90.7% | 0.3 pp |
| VoV reduction (74%) | 74% | 73.7% | 0.3 pp |
| S2 Delta -73.6% | -73.6% | -73.66% | 0.06 pp |
| S1 MDD reduction 55% | 55% | 54.7% | 0.3 pp |
| S2 MDD reduction 33% | 33% | 33.2% | 0.2 pp |
| S1 CAGR sacrifice 5.40pp | 5.40 pp | 5.395 pp | 0.005 pp |
| Sens th0.5 opp share 64% | 64% | 64.2% | 0.2 pp |
| Sens th1.5 opp share 65% | 65% | 65.3% | 0.3 pp |
| Sens reduction range 62%-76% | 62%-76% | 61.7%-75.6% | 0.3-0.4 pp |

---

## Direction / Sign Integrity Check

Per audit protocol (Paper 4 DIV-1 pattern prevention):

| # | Claim | Direction | JSON Verified |
|---|---|---|---|
| 1 | Opp cost (4.20%) dominates direct cost (0.43%) | opp > direct | ✓ |
| 2 | S2 total < S1 total (VoV reduces cost) | S2 < S1 | ✓ |
| 3 | S2 opp cost falls from 4.20% to 0.70% | S2_opp < S1_opp | ✓ |
| 4 | S2 direct cost increases from 0.43% to 0.52% | S2_direct > S1_direct | ✓ |
| 5 | S2 has highest Sharpe (0.63) among all strategies | S2 = argmax Sharpe | ✓ |
| 6 | Rebalancing CAGR > BH CAGR (54 bps premium) | rebal > bh | ✓ |
| 7 | S2 Sharpe (0.63) > S4 Sharpe (0.50) | S2 > S4 | ✓ |
| 8 | S3 less effective than S2 (3.31 > 1.22) | S3_total > S2_total | ✓ |
| 9 | S0 CAGR > S1 CAGR (VT reduces returns) | S0 > S1 | ✓ |
| 10 | S1 MDD reduced 55% vs BH | abs(S1_MDD) < abs(S0_MDD) | ✓ |
| 11 | HighVoV_Falling = worst regime (19.95% opp cost) | HVF = max regime | ✓ |
| 12 | S2 fully invested 86% of time | pct_fi ≈ 86 | ✓ |

**ALL 12 DIRECTION/SIGN CHECKS PASS. No Paper 4 DIV-1 type reversal errors detected.**

---

## Script/Figure Coverage

| Component | Status |
|---|---|
| Main experiment K811v2 script | PRESENT (`k811v2_insurance_premium_vov_fixed.py`) |
| K846 rebalancing premium script | PRESENT (`k846_rebalancing_premium.py`) |
| Sensitivity threshold 0.5 script | PRESENT (`k811v2_threshold_0.5.py`) |
| Sensitivity threshold 1.5 script | PRESENT (`k811v2_threshold_1.5.py`) |
| reproduce.py entry point | PRESENT |
| Figure scripts | N/A (paper has no \includegraphics) |
| K860 prospect theory | PRESENT but NOT cited in paper |

---

## Cross-Reference with Prior Audit (reviews/audit_step1_2.md)

Prior audit (2026-04-05) identified the same issues:
- FLAG 1: "97% should be 98%" — confirmed by this audit
- FLAG 2: Sensitivity numbers unverifiable — RESOLVED: threshold files found (k811v2_th0_5, k811v2_th1_5)
- FLAG 3: Cross-period rebalancing premium reference — acknowledged, disclosed in paper
- FLAG 4: Correlation source ambiguity — resolved: 0.057 from K846 (2006-2024), consistent

**Update from this audit**: FLAG 2 is now PARTIALLY RESOLVED. The individual threshold files exist and numbers verify. However, UV-1/UV-2 (2012-2024 sub-period footnote) remain unverifiable.
