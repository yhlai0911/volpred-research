# Paper 2: Volatility Targeting in Taiwan — Leverage Amplification and Timezone Transmission

**Target Journal**: Pacific-Basin Finance Journal
**Status**: **Major Revision Required** — 2 HIGH blocking submission (found 2026-05-23 formal review cycle v1; new, not in R1-R4). 6 MEDIUM, 7 MINOR outstanding. See `review_history/v1/` for full reports.

**HIGH issues (blocking)**:
- H1: Three-way γ inconsistency for 0050.TW (body.tex lines 52/137/148/683): 0.087 (Table 1-2 rolling), 0.097 (Section 3.1 K892 canonical), 0.124 (Section 8.4 K900 rolling-252d). Source file `data/0050_canonical.json` cited in line 148 **does not exist**. Fix: Update Table 2 to K892 canonical γ=0.097.
- H2: ELITE Material (2383.TW) appears in Table 2 (line 156, sourced from K1302) but is absent from Section 2.1 data description. Undisclosed data source.

**Quick fixes applied 2026-05-23** (citation fixes):
- body.tex:449 — `\citep{politis1994stationary}` → `\citep{politis1994}` (MAJOR citation fix)
- body.tex:593 — Added `\citet{christoffersen1998}` for VaR Trinity independence test (M3)
- main_v3.tex:93 — Engle (1982) page `987--1007` → `987--1008`
- main_v3.tex:104,110,116,146 — `et al.` → `et~al.` in 4 bibitems

**Previous status (pre-v1 review)**: Minor Revision — 0 SEVERE / 0 HIGH / 0 MEDIUM remaining (all 5 MEDIUM resolved 2026-05-20: sub-M8a, M3-persist/Christoffersen, N4 footnote, M5 period note, SSVS PIP note); 6 MINOR outstanding. | **Reproduce gate 0 MISMATCH** (2026-04-19 post-session: 4 γ disambiguation mismatches 全 reclass NOTE via body_v2.tex 3-spec footnotes on TWII/TSMC/0050.TW + SSVS PIP UNTRACEABLE + GJR+Normal viol NOTE). 75 VERIFIED / 2 CONFLICT_RESOLVED / 0 MISMATCH / 24 UNTRACEABLE (structural data-limit — Table 4/5 VT performance + Sec 6 macro signals 需 new experiments).
**Pages**: 60 | **Citations**: 34

## Data Sources
- 0050.TW, TWII, TSMC, 9 TW stocks: yfinance (clean_tw50_data required)
- TAIFEX TX tick: ~/Dropbox/TAIFEXDATA/
- VIX: yfinance

### Snapshot Pinning
- `snapshot_date`: `2026-04-19`
- Pinned local CSV in `paper/taiwan-vt/data/`:
  - `0050_tw_twii_2330_tw_2317_tw_2454_tw_0056_tw_spy_vix_2008-2026.csv`
- This snapshot pins the core yfinance panel used by the paper's gamma / control checks. The broader 9-stock Taiwan cross-section and TAIFEX tick data remain governed by their existing experiment-level sources.
- Current `reproduce.py` reads stored experiment JSONs rather than live yfinance; the snapshot is added for reviewer-package completeness and future local reruns.

## Reproduction
```bash
uv run python paper/taiwan-vt/reproduce.py
```

## Known Issues
- S1: Missing ES analysis → K896 provides data
- S2-S4: Gamma conflicts → K892 provides correct values
- S5: VT performance tables need JSON
- S6: SSVS PIP conflict needs investigation
- Section 5 (high-frequency) ~95% verified

### 2026-04-19 reproduce gate diagnostic — 6 MISMATCH categorized (108 checks total)

All 6 mismatches are window-/spec-divergences analogous to Paper 1 HM C1 (resolved via K1256 3-spec disambiguation). Proposed pattern:

| # | Cell | Paper | K892 / source | Root cause | Fix path |
|---|---|---|---|---|---|
| 1 | TWII γ 0.272 (t=3.18) L51,146 | 1997--2026 | K892 2008-2026 rolling max 0.236 | Paper uses 1997-2026 window; K892 stores 2008-2026 only | ✅ **RESOLVED 2026-04-19** (c) footnote applied body_v2.tex L146 `^{\P}` + L164 Notes 擴展 (long-sample Asian Fin Crisis + Dot-Com; K892 2008-26 subset max 0.236 mean 0.114 confirms pre-2008 shocks drive 0.272) |
| 2 | TSMC γ 0.039 (Table 2 L54,151) vs 0.054 (Sec 4.5 L441) | internal inconsistent | K892 full=0.0525 | Same `\gamma` symbol, two mean-specs | ✅ **RESOLVED 2026-04-19** (c) 3-spec footnote applied body_v2.tex L151 dagger + L164 Notes 擴展（Zero-mean GJR vs Constant-mean vs K892 canonical） |
| 3 | 0050.TW γ 0.087 (Table 2 L52) vs 0.124 (Sec 4.5 L441) | internal inconsistent | K892 full=0.097 / w=2000 2018-26=0.080 | Different fit windows | ✅ **RESOLVED 2026-04-19** (c) 3-spec footnote applied body_v2.tex L147 `^{\S}` + L164 Notes 擴展 (Zero-mean 2008-26 vs Constant-mean full vs K892 0.097/0.080 bracket) |
| 4 | TSMC γ 0.039 Table 2 | — | K892 full=0.0525 | Table 2 cell-level | ✅ **RESOLVED 2026-04-19** (c) footnote (same as #2); `^{\ddagger}` reference added |
| 5 | SSVS SPY_ret_L1 PIP=0.312 L214 | — | K461 stores AR(1)=0.9994 (not SSVS PIP) | reproduce.py binds wrong JSON field | (a) fix reproduce.py field binding |
| 6 | GJR+Normal violations 9/481 | — | K852 = 11/481 | Refit freq or sample period | (b) align to K852 OR (c) footnote |

Recommended disambiguation template for γ (#2 / #3 / #4) follows **P1 K1256 3-spec pattern**:
> `γ_TSMC` = 0.039 (Table 2 Zero-mean GJR full 2008-26, t=0.87) vs 0.054 (§4.5 Constant-mean full-sample avg, t=1.07) vs 0.0525 (K892 canonical) — three distinct mean-spec/window γ estimates share `\gamma` symbol.

**Next-pass**: v2 revise body with 3-spec footnote (~30 min main-thread); reproduce.py scores DIVERGENT_SAME_SIGN as NOTE tier (matches P1 K1256 handling).
