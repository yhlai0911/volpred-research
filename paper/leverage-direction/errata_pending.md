# Paper 1 (leverage-direction) Errata Pending

**Last updated**: 2026-05-17 (created from K1198 MODIFY_PAPER verdict)
**Status**: pre-resubmission errata items, no public erratum filed yet

---

## Source: K1198 reproducibility recheck (verdict (b) MODIFY_PAPER)

Run: 2026-05-17, elapsed 77.85s, seed=42, data=yfinance (auto_adjust default)
Reference article: `mile_1fde450d` (general audience disclosure)

### 4 items requiring update (3/6 DIVERGED in K1198 check)

| # | Location | Original value | Recomputed value | Recommended action |
|---|---|---|---|---|
| 1 | Table 10 SPY constituent avg γ | 0.076 | 0.0939 | Footnote: "N=20 公開 API 可得；原 paper N=50" |
| 2 | Table 10 t-stat (ETF vs avg stock γ) | -16.92 | -10.53 | Update table number; amplification direction + significance preserved |
| 3 | Appendix C3 gold bull vs bear t-stat | -4.71 | -3.79 | Update text; same direction, p<0.001 still strong significance |
| 4 | Table 11 VT ES / kurtosis | -1.35% / 0.46 | -2.74% / 3.76 | Footnote: VT spec = Hybrid VT (12/VIX), not pure GARCH VT |

### 3 items MATCHED (no action needed)

| Location | Original | Recomputed | Status |
|---|---|---|---|
| Table 11 BH ES | -4.68% | -4.53% | MATCHED (within tol) |
| Table 11 BH kurtosis | 14.71 | 14.51 | MATCHED |
| Table 12 Spearman ρ | 1.000 | 1.000 | MATCHED |

### Verdict rationale (MODIFY vs RETRACT vs KEEP)

Main conclusions all preserved:
- ETF γ > constituent average γ amplification: direction + significance
- Gold inverse leverage pattern: same direction, still p<0.001
- VT beats BH on tail metrics: same conclusion

Divergences are magnitude / sample composition / spec-detail driven:
- SPY constituent N=20 (API-available) vs paper N=50 → different cohort
- yfinance auto_adjust default vs paper's adjustment policy
- Hybrid VT vs pure GARCH VT footnote disambiguation needed

Threshold: errata-level (footnote / table value update), NOT retraction.

### Resubmission integration plan

When next opening Paper 1 main_v?.tex for revision:
1. Apply 4 footnote/value updates above
2. Add reproducibility note section citing K1198 commit (current main HEAD when applied)
3. Run reproduce.py post-update to confirm new gate
4. Sync via `uv run volpred ops paper-update --paper-id leverage-direction`

---

## Prior items (none yet)

This is the first errata batch for Paper 1 — file created 2026-05-17.
