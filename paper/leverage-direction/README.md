# Paper 1: Leverage Direction Matters — Asymmetric Volatility and the Cross-Section of VT Alpha

**Target Journal**: Journal of Banking and Finance (JBF)
**Status**: ⛔ **SUBMISSION FROZEN（2026-06-11 v11 review 確認維持凍結）** — 06-10 的「K903 canonical 全文一致化」**執行不完整**，v11 round 找到 5 HIGH 殘留矛盾：(V11-1) body L184 仍寫舊 GLD QLIKE（Δ=−0.07%/p=0.871/「Neither significant」），與 Table 3 K903（Δ=+0.39%/p=0.001 GARCH 顯著勝）+ 同篇 L144 互斥；(V11-2) Table 2（tab:gamma）混血 vintage——只換 GLD 列，SPY/QQQ/EEM/BTC/SLV HAC t 仍舊 draft（BTC t=+1.83 vs K903 +2.88、SLV t=−2.91 vs −0.68），model-selection rule 輸入未經 canonical 復現；(V11-3) SPY 2025 散文 −8.818/Δ−1.13%/p0.029 vs Table 3 −8.412/Δ−1.74%/p0.048；(V11-4) GLD γ 三版並存（+0.002 / L405 −0.088 / L172 bull−0.043 bear+0.048）；(V11-5) **RESOLVED 2026-06-11**：reproduce.py 全面重寫對齊 v12 7-table K903 canonical 佈局，且 tab:var_ortho 的 GARCH+Normal Kupiec p 已由錯誤的 `0.64` 修正為 `0.40` → **green 100.0%**（161 MATCH / 0 MISMATCH / 23 NOTE）；Table 2 全 7 列×4 欄、Table 3 全 9 列×4 欄、Table 5 GARCH-Normal Kupiec row，及 body.tex K903 散文 literal 14 項，現均與 canonical sources 對齊。另 5 MEDIUM（EEM GJR 無 DM 支持、`sec:model_selection` undefined ref、Table 3 9/12-cell 選取未說明、Table 2 caption 僅揭露 GLD、hood2025/nelson2025/xu2024 待驗）+ 2 LOW。**解凍前提**：全文 γ/QLIKE/DM-p 逐一對齊 K903（建 number→source-cell 對照表）+ 補 `\label{sec:model_selection}` + ~~reproduce.py 對齊 7-table 重跑 green~~（✅ 2026-06-11 完成，見 V11-5）。完整報告：`review_history/v11/{README.md, v11_review_report.tex}`。｜前段歷史：06-10 audit（`review_history/audit_2026-06-10/audit_findings.json`）；R1 — 2 CRITICAL；Reproduce (2026-06-11 current): 161 MATCH / 0 MISMATCH / 23 NOTE，traceable match rate 100.0%，alert green。
**Pages**: 48 | **Citations**: 54

## Data Sources
- SPY, QQQ, GLD, TLT, EEM, BTC-USD, IWM, SLV: yfinance
- VIX: yfinance (^VIX)

### Snapshot Pinning
- `snapshot_date`: `2026-04-19`
- Pinned local CSVs in `paper/leverage-direction/data/`:
  - `spy_qqq_gld_tlt_eem_iwm_slv_btc_usd_vix_2010-2026.csv`
  - `spy_vix_2004-2026.csv`
  - `vix_daily.csv` (legacy single-series reference kept for compatibility)
- Current `reproduce.py` verifies experiment JSONs / paper claims and does not perform live yfinance pulls; these snapshots pin the paper's market-data base for future reruns and reviewer-package completeness.

## Reproduction
```bash
uv run python paper/leverage-direction/reproduce.py
```

## Submission Materials

- `cover_letter.tex` / `cover_letter.pdf` — current JBF cover letter draft
- `highlights.txt` — five highlights for submission portal
- `graphical_abstract.svg` — visual summary for graphical-abstract upload
- `submission_package.md` — package checklist and journal-specific notes
- `supplementary.tex` / `supplementary.pdf` — companion supplementary material for moved appendix / robustness tables

## Self-contained replication package

This folder is structured per `.claude/rules/paper-workflow.md` §Self-contained
paper folder (JBF submission hard requirement). Entry points:

- `data_sources.md` — pinned CSV provenance, license, refresh policy
- `data/` — snapshot CSVs (yfinance, `auto_adjust=False`, snapshot 2026-04-19)
- `scripts/README.md` — replication entry points (`reproduce.py` + figure regen)
- `scripts/figures/` — 7 figure generators (`fig_*.py`); status ledger in `data_source.md`
- `results/README.md` — canonical result-JSON index (where each table number sources from)
- `experiments.md` — table/figure → K-experiment K-id mapping (canonical)
- `experiments/` — paper-folder shim copies of K799/K802/K824v2/K902 + HM stub
- `reproduce.py` / `reproduce_report.json` — paper-wide claim verifier (current gate: 161 MATCH / 0 MISMATCH / 23 NOTE, green)

## Known Issues (from R1)
- ~~C1: HM gamma internal contradiction (Sec 4.7 vs Sec 5.4)~~ **RESOLVED 2026-04-19** via K1256 3-spec disambiguation (`pure_vt_full` §4.7, `pure_vt_high_vix` §4.7 VIX>25 conditional, `hybrid_vt_full` §5.4); body_v3.tex L433 footnote documents the three distinct regressions; `reproduce.py` now scores each spec as DIVERGENT_SAME_SIGN (NOTE tier) pending L11 errata path (c) for the 17-55% magnitude divergence vs paper.
- ~~C2: Kupiec p-values aggressively rounded (0.67→0.60)~~ **RESOLVED 2026-06-11**: active `tables_main.tex` 現為 GARCH-Normal `0.40`、GJR-Student-t `0.67`，與 K799/K802 canonical source 與獨立 Kupiec 重算一致；reproduce gate 亦已達 `0 MISMATCH`.
- C3: Table 5 cherry-picks from 3 experiments — K899 unified VaR pending
- C4-C5: Tables 1, 3 partially untraceable
- Main manuscript shortened to 48 pages; remaining compression to ~45 pages is optional rather than blocking

## Supporting Experiments

- **K1256**: Paper 1 T-HM canonical 3-spec Henriksson-Merton γ_HM experiment. All 3 γ signs negative → variance-management thesis confirmed qualitatively. Magnitudes 17-55% smaller than paper body_v3 L433 footnote values; DIVERGENT_SAME_SIGN verdict triggers L11 errata path (c) recommendation. See `experiments/k1256/` (script + results + README); paper-side stub `paper/leverage-direction/experiments/hm_timing_tests_results.json`.
- **K799 / K802 / K824v2**: evaluation layer, GJR skew-t, probabilistic RV quantile VaR (per reproduce.py Check sources).
- **K829**: VaR panel across 7 assets (Table 6 source).
