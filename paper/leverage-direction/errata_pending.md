# Paper 1 (leverage-direction) Errata Pending

**Last updated**: 2026-05-17 (batch-3 added: K1198 errata applied — Table 10 t-stat, Table 11 footnote, body_v3.tex t=-4.71→-3.79 ×3)
**Status**: pre-resubmission errata items, no public erratum filed yet

---

## Source: K1198 reproducibility recheck (verdict (b) MODIFY_PAPER)

Run: 2026-05-17, elapsed 77.85s, seed=42, data=yfinance (auto_adjust default)
Reference article: `mile_1fde450d` (general audience disclosure)

### 4 items requiring update (3/6 DIVERGED in K1198 check)

**Applied 2026-05-17 (batch-3 hourly dispatch)**

| # | Location | Original value | Recomputed value | Recommended action | Status |
|---|---|---|---|---|---|
| 1 | Table 10 SPY constituent avg γ | 0.076 | 0.0939 | Footnote: "N=20 公開 API 可得；原 paper N=50" | ✅ APPLIED — footnote `†` added to tables.tex |
| 2 | Table 10 t-stat (ETF vs avg stock γ) | -16.92 | -10.53 | Update table number; amplification direction + significance preserved | ✅ APPLIED — tables.tex updated |
| 3 | Appendix C3 gold bull vs bear t-stat | -4.71 | -3.79 | Update text; same direction, p<0.001 still strong significance | ✅ APPLIED — body_v3.tex ×3 (L12, L168, L208) |
| 4 | Table 11 VT ES / kurtosis | -1.35% / 0.46 | -2.74% / 3.76 | Footnote: VT spec = Hybrid VT (12/VIX), not pure GARCH VT | ✅ APPLIED — Notes section added to tables.tex |

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

**Status (2026-05-17)**: Steps 1 applied (batch-3). Steps 3-4 pending.

1. ~~Apply 4 footnote/value updates above~~ ✅ DONE (batch-3)
2. ~~Add reproducibility note~~ — done via errata footnotes in tables.tex
3. ~~Run reproduce.py post-update~~ ✅ DONE — gate_status=pass_with_untraceable, MISMATCH=0 (amber pre-existing)
4. **PENDING**: Sync via `uv run volpred ops paper-update --paper-id leverage-direction`

---

## Source: K1186/K1206 canonical replication (errata-batch-2, Table 6)

Applied: 2026-05-17 (main thread hourly dispatch)
Task: `Paper1_Table6_errata` (next_tasks.json → succeeded)

### 3 rows updated in `tables.tex` Table 6 (var_panel)

| Method | Location | Original | K1186 canonical | Action |
|---|---|---|---|---|
| Student-$t$(5) | Row + pass rate | 57.1% (12/21), checkmarks: SPY✓ QQQ✓ GLD✗ TLT✗ EEM✓ BTC✓ IWM✗ | 76.2% (16/21), checkmarks: SPY✗ QQQ✗ GLD✓ TLT✓ EEM✗ BTC✓ IWM✓ | Updated row + errata footnote |
| Skewed-t | Row + pass rate | 76.2% (16/21), checkmarks: SPY✓ QQQ✓ GLD✓ TLT✗ EEM✓ BTC✓ IWM✓ | 90.5% (19/21), checkmarks: SPY✓ QQQ✓ GLD✗ TLT✓ EEM✓ BTC✗ IWM✓ | Updated row + errata footnote |
| CF-VaR | Row + pass rate | 66.7% (14/21), checkmarks: SPY✓ QQQ✓ GLD✗ TLT✗ EEM✓ BTC✓ IWM✓ | 76.2% (16/21), checkmarks: SPY✗ QQQ✓ GLD✗ TLT✓ EEM✓ BTC✗ IWM✓ | Updated row + errata footnote |

### Forensic basis

- **K1206**: tested 3 reconstruction hypotheses (data-vintage truncation, bisection-based skewed-t, CF-VaR spec variants). All 3 divergent methods returned `verdict=neither_reconstructs` / `no_variant_reconstructs`. Original values unrecoverable.
- **K1186**: canonical replication (GJR-GARCH(1,1), roll w=504, seed=42, OOS 2020–2025, yfinance 2000–2026). n_targets_matched=2 (Normal + FHS correct; 3 others updated).
- Main conclusions unchanged: distribution-family hierarchy (Skewed-t best) and VaR pass-rate ordering preserved.

### Errata footnote added to Table 6 in tables.tex

Inline footnote appended to `\textit{Notes:}` block in tables.tex.

---
