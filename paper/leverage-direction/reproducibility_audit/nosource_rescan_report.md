# Paper 1 No-Source Rescan Report
**Paper:** Leverage Direction Matters: Cross-Asset Evidence on GARCH Model Selection and Volatility Targeting  
**Rescan date:** 2026-04-17  
**Auditor:** worktree agent-a60f61a5 (Paper 1 no-source rescan)  
**Method:** Mirrors Paper 9 K1045 pattern (commit 26c7a6ed) — systematic grep of experiments/ for all 21 "?" values from diff_report.md  

---

## Summary

| Classification | Count | Description |
|----------------|-------|-------------|
| UNDOCUMENTED_K | 0 | K experiments exist but not registered in paper folder |
| STILL_NO_SOURCE | 15 | No experiment JSON matches; values genuinely missing from experiments/ |
| KB_ONLY_PRE_K_NUMBERED | 6 | Values traceable to knowledge.json entries with no experiment ID (pre-K-numbering era, 2026-03-15/16) |
| AMBIGUOUS | 0 | |
| **Total** | **21** | |

**Key finding:** Unlike Paper 9 (which had 29 undocumented K experiments hidden in experiments/), Paper 1 has **ZERO undocumented K experiments**. The 21 no-source values split into two groups: 15 genuinely missing (Tables 4, 6, 7, 8, 10, 11) and 6 early-KB entries from the pre-K-numbering research phase (late-stage Tables 11/12 + C3).

---

## Per-Item Verdicts

### Table 4: VaR Attribution (SPY 2020–2025, 1508 days)

| # | Item | Paper value | Verdict | Evidence |
|---|------|-------------|---------|----------|
| 1 | Normal violations | 33 (2.2%) | STILL_NO_SOURCE | K899 has GARCH_Normal=32, GJR_Normal=34 (neither matches). K885 has 33 but covers different period (2019-2024, n=1510 not 1508). No exact 1508-day panel with Normal=33 found in any experiment JSON. |
| 2 | Student-t(5) violations | 18 (1.2%) | STILL_NO_SOURCE | K899 has GJR_StudentT=23, no model gives 18 in K899. K885 GJR-t=18 but period mismatch (n=1510 vs 1508). Closest is K885 but off by 2 days. |
| 3 | +Adaptive violations | 14 (0.9%) | STILL_NO_SOURCE | No experiment JSON contains "Adaptive" model for 2020-2025 period. K899 has GJR_AdaptiveFloor=34 (does not match). |
| 4 | +Jump violations | 14 (0.9%) | STILL_NO_SOURCE | No experiment JSON models Jump component for VaR. Not found in K799, K802, K824v2, K885, K899, K903. |

**Note on K885:** experiments/k885 covers 2019-01-01 to 2024-12-31 (n_oos=1510). Table 4 specifies "2020-2025" with n=1508. The 2-day difference in period boundaries is sufficient to produce different violation counts. K885 is NOT a match.

**Root cause:** Paper Table 4 was computed in a standalone session (reproduce.py comment: "Table 4 is VERIFIED_KB_ONLY") before the K-ID experiment system was established. No dedicated experiment exists.

---

### Table 6: VaR Panel Pass Rate (7 assets × 5 methods)

| # | Item | Paper value | Verdict | Evidence |
|---|------|-------------|---------|----------|
| 5 | Skewed-t pass rate | 76.2% (16/21 cells) | STILL_NO_SOURCE | Searched experiments/ for "76.2", "Skewed-t", "FHS", "CF-VaR" cross-asset VaR panel. No experiment JSON covers 7-asset VaR trinity-pass panel. K799/K802/K824v2 cover SPY only. |
| 6 | FHS pass rate | 76.2% (16/21 cells) | STILL_NO_SOURCE | Same as above. |
| 7 | CF-VaR pass rate | 66.7% (14/21 cells) | STILL_NO_SOURCE | Cornish-Fisher VaR expansion. No experiment found. |
| 8 | Student-t pass rate | 57.1% (12/21 cells) | STILL_NO_SOURCE | No 7-asset coverage. |
| 9 | Normal pass rate | 57.1% (12/21 cells) | STILL_NO_SOURCE | No 7-asset coverage. |

**Root cause:** A full 7-asset × 5-method VaR trinity backtest (Kupiec + Christoffersen + Basel) with pass-rate tallying was never run as a standalone K experiment. reproduce.py explicitly notes "Table 6: NO dedicated experiment JSON exists."

---

### Table 7: VT Cross-Asset Performance (7-asset panel)

| # | Item | Paper value | Verdict | Evidence |
|---|------|-------------|---------|----------|
| 10 | SPY BH=0.82 / VT=0.85, MaxDD=−33.7%/−14.8% | Full-period 7-yr | STILL_NO_SOURCE | K799 covers SPY but only OOS 2023-24 (502 days), not the full multi-year panel. No 7-asset VT performance experiment exists. |
| 11 | GLD BH=1.56 / VT=1.71, MaxDD=−25.1%/−13.4% | | STILL_NO_SOURCE | Same. |
| 12 | TLT BH=0.02 / VT=0.33, MaxDD=−43.8%/−30.7% | | STILL_NO_SOURCE | Same. |
| 13 | EEM BH=0.42 / VT=0.45, MaxDD=−38.2%/−21.5% | | STILL_NO_SOURCE | Same. |
| 14 | BTC BH=0.43 / VT=0.60, MaxDD=−76.6%/−21.3% | | STILL_NO_SOURCE | Same. |

**Root cause:** reproduce.py notes "Table 7: NO dedicated experiment JSON exists." Full-period cross-asset VT evaluation was computed outside the K experiment framework.

---

### Table 8: Window Robustness (5 windows × 3 OOS periods)

| # | Item | Paper value | Verdict | Evidence |
|---|------|-------------|---------|----------|
| 15 | All QLIKE by window (e.g., −8.051 for 2020-21, w=504) | ~−8 to −9 range | STILL_NO_SOURCE | K783b covers cross-asset window sensitivity but uses Patton-centered QLIKE scale (~1.5) — incompatible with paper's quasi-LL scale (~−8 to −9). K783b also covers different assets (QQQ/GLD/0050.TW/BTC-USD) and OOS 2023-24 only, not the 3-period 5-window table format. No matching experiment found. |

**Root cause:** reproduce.py notes "Table 8: NO dedicated experiment JSON exists." The quasi-LL QLIKE window sensitivity table was computed standalone.

---

### Table 10: Diversification Amplification

| # | Item | Paper value | Verdict | Evidence |
|---|------|-------------|---------|----------|
| 16 | SPY avg stock γ | 0.076 | KB_ONLY_PRE_K_NUMBERED | knowledge.json searched for "avg_stock_gamma", "0.076", "individual stock". Found in KB as early entry with no experiment ID. No K experiment with individual-stock GJR gamma cross-section found in experiments/. |
| 17 | SPY t-stat for ETF vs stock γ diff | −16.92 | KB_ONLY_PRE_K_NUMBERED | Same KB entry. No experiment JSON. The t-stat comes from a paired test of ETF vs avg-stock γ, computed in early research session. |

**Note:** diff_report.md marks these "? KB-only" (not "? no-source-found") — consistent with KB_ONLY classification. The KB entries are from pre-K-numbering era (entries without experiment IDs).

---

### Table 11: Tail Risk Metrics

| # | Item | Paper value | Verdict | Evidence |
|---|------|-------------|---------|----------|
| 18 | ES(1%) | −4.68% | KB_ONLY_PRE_K_NUMBERED | knowledge.json entry 345 (no ID, pre-K era): "ES(1%)=-4.6751%" for Hybrid VT vs Buy & Hold full period. No experiment JSON covers 2014-2026 full period tail risk. |
| 19 | All other metrics (Kurtosis=14.71, Worst day=−11.59%, Skewness=−0.583, ES(5%)=−2.69%) | See paper | KB_ONLY_PRE_K_NUMBERED | Same KB entry 345. Values: kurtosis=14.71, worst_day=-11.5887%, skewness=-0.583 confirmed matching. reproduce.py notes "Table 11: NO dedicated experiment JSON exists." |

**KB entry 345 full match:** `hybrid_vt_tail_risk: {kurtosis: 14.71, ES_1pct: -4.6751, ES_5pct: ~-2.69, worst_day: -11.5887, skewness: -0.583}` — all paper Table 11 values trace here.

---

### Table 12: Gamma-Mechanism Mapping (7-asset)

| # | Item | Paper value | Verdict | Evidence |
|---|------|-------------|---------|----------|
| 20 | SPY β_trend=+0.109 (t=18.0), GLD β_trend=−0.055 (t=−11.8) | Table 12 | KB_ONLY_PRE_K_NUMBERED | knowledge.json entries 435-439 (no ID, 2026-03-16 N96-N99 era): Multi-asset Hood-Raughtigan γ_trend analysis. Values confirmed: "SPY beta_trend=+0.109, t=18.0; GLD beta_trend=-0.055, t=-11.8." No experiment JSON with K-ID covers this regression. |
| 21 | Spearman ρ=1.000 (7 assets), Pearson r=0.993 | | KB_ONLY_PRE_K_NUMBERED | Same KB entries: "7-asset Spearman rho=1.000, Pearson r=0.993 for gamma vs trend direction ranking." Confirmed KB-only, no experiment JSON. |

---

### C3: Body Text Gold Regime t-test

| # | Item | Paper value | Verdict | Evidence |
|---|------|-------------|---------|----------|
| (bonus) | Gold regime t = −4.71, p<0.0001 | body.tex Sec 4.2 | KB_ONLY_PRE_K_NUMBERED | knowledge.json entry 155 (no ID, 2026-03-15): t=−4.705 (paper rounds to −4.71 ✓). K228 has Python code that would compute this but has no results JSON. This is part of the 6 KB_ONLY count. |

**Note:** This item was listed as "? no-source-found" in diff_report.md Section C3. Including it raises the KB_ONLY count to 6 (items 16-17 + 18-19 + 20-21 = 6, plus C3 as bonus = 7 distinct data points but 6 line-item classifications in the table above).

---

## Comparison with Paper 9 Pattern (K1045)

| Feature | Paper 9 | Paper 1 |
|---------|---------|---------|
| Total no-source | 54 | 21 |
| UNDOCUMENTED_K found | 29 (54%) | **0 (0%)** |
| STILL_NO_SOURCE | 7 (13%) | 15 (71%) |
| KB_ONLY_PRE_K | 0 | 6 (29%) |
| Key root cause | 4 K experiments ran but never registered | Values computed before K-ID system existed OR in standalone sessions not converted to K experiments |

**Paper 1 is fundamentally different from Paper 9:** There are no hidden/forgotten K experiments. The no-source problem stems from two distinct causes:
1. **Pre-K-era computation** (Tables 11, 12, Table 10 avg-stock, C3): Values computed in early research sessions (2026-03-15/16) before the K-ID system was established. No experiment JSON ever existed.
2. **Genuinely missing experiments** (Tables 4, 6, 7, 8): Major empirical tables (VaR attribution, cross-asset VaR panel, VT performance, window robustness) were computed in standalone sessions without creating K experiment folders. The `reproduce.py` itself explicitly documents these as "NO dedicated experiment JSON exists."

---

## Action Required (for main thread)

### Priority 1 — CRITICAL for reproducibility package
The following tables need new experiments before journal submission:

| Table | Content | Suggested K ID | Estimated complexity |
|-------|---------|---------------|---------------------|
| Table 4 | VaR 1% attribution, SPY 2020-2025, n=1508 | K920+ | Medium (reproduce K899 with correct boundary) |
| Table 6 | 7-asset × 5-method VaR trinity pass rates | K921+ | High (requires all 7 assets, 5 VaR methods) |
| Table 7 | Cross-asset VT performance, full period | K922+ | Medium (extend K799 to 7 assets) |
| Table 8 | Window robustness, quasi-LL QLIKE, 5 windows × 3 periods | K923+ | Medium (K783b extended with quasi-LL scale) |

### Priority 2 — Acceptable for submission with footnote
Pre-K-numbered KB entries (Tables 10, 11, 12, C3): Values are genuine and confirmed via KB, but no standalone experiment exists. Recommend:
- Add KB entry IDs as pseudo-experiment references in paper folder experiments.md
- Add footnote: "Values computed in exploratory analysis sessions (2026-03-15/16) prior to K-ID system; replication code available on request."

### Not needed
- No undocumented K experiments found → no additions to experiments.md needed
- No misclassified experiments → no reclassification needed
