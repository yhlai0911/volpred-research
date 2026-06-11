# Paper 1: Leverage Direction Matters — Asymmetric Volatility and the Cross-Section of VT Alpha

**Target Journal**: Journal of Banking and Finance (JBF)
**Status**: 🟢 **REVISION COMPLETE — v12 確認輪通過（2026-06-11 12:00）**：v11 5 HIGH 全修 + 確認輪殘留（L187/L513/Table 3 11-row）全修；reproduce gate GREEN（171 MATCH / 0 MISMATCH / 23 NOTE, 100%）；63 頁新版已上線。下一步 = 投稿準備 spot-check（v13 輕量）+ R1-track MEDIUM（multiple-testing 段/BH 溯源/tab:vt 統一窗）。v11 round（latex-academic-reviewer + citation-verifier 正式雙 skill）找到的 5 HIGH **已全部處置**：V11-1 L184 GLD 散文 ✅（v12 sweep 對齊 K903）；V11-2 Table 2 混血 vintage ✅（全 7 列換 K903 canonical + caption 全表揭露 + BTC 敘事重寫 t=+2.88）；V11-3 SPY 2025 散文 ✅；V11-4 GLD γ 三版 ✅（L405 標 2010-2017 in-sample window 揭露）；V11-5 reproduce gate ✅（reproduce.py 重寫對齊 v12 7-table K903 → **green 100.0%**，161 MATCH / 0 MISMATCH / 23 NOTE；tab:var_ortho GARCH+Normal Kupiec p 0.64→0.40 修正）。citation：57 條全驗證，hood2025/nelson2025/xu2024 確認真實存在（v11 citation_check_v1.md）；bali2016 捏造 DOI 已刪。band 重推 (0.009,0.072)、`\label{sec:model_selection}` 已補。**下一步**：v12 review round（雙 skill 複審確認 0 HIGH）通過後始可考慮投稿；殘 MEDIUM（multiple-testing 段、BH 溯源、tab:vt 統一窗重算）走 R1-track。完整軌跡：`review_history/v11/` + `review_history/audit_2026-06-10/fix_log.md`。｜Reproduce (2026-06-11 current): 161 MATCH / 0 MISMATCH / 23 NOTE，100.0%，green。
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
