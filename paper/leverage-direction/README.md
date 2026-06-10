# Paper 1: Leverage Direction Matters — Asymmetric Volatility and the Cross-Section of VT Alpha

**Target Journal**: Journal of Banking and Finance (JBF)
**Status**: ⛔ **SUBMISSION FROZEN（2026-06-10 全組合學術審查）** — 6 HIGH blocking：核心結果（GLD γ=−0.067/t=−5.79/93%）已被 K903 canonical replication 推翻（+0.002/NS/67%，SIGN REVERSED），Table 2 已換 K903 但 Intro/§4.2/§5/§6 殘留舊敘事；Table 3 八列 legacy 與 K903 衝突（GLD 顯著反向）；BTC 分類規則自相矛盾（9/9 需重算）；ρ=0.944 的 p<0.001 錯一個數量級（實 p≈0.016，5 處）；reproduce gate amber 80.9% 且過期。**決策（2026-06-10）：採 K903 canonical 全文一致化**（abstract 已是此版）。修正清單：`review_history/audit_2026-06-10/audit_findings.json`。修完 + reproduce green 才解凍。｜前段歷史：R1 review — 2 CRITICAL (C3/C4/C5 subsets)；Reproduce (2026-05-17，已過期): 28 MATCH / 0 MISMATCH / 9 NOTE / 19 UNTRACEABLE.
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
- `reproduce.py` / `reproduce_report.json` — paper-wide claim verifier (0 MISMATCH gate)

## Known Issues (from R1)
- ~~C1: HM gamma internal contradiction (Sec 4.7 vs Sec 5.4)~~ **RESOLVED 2026-04-19** via K1256 3-spec disambiguation (`pure_vt_full` §4.7, `pure_vt_high_vix` §4.7 VIX>25 conditional, `hybrid_vt_full` §5.4); body_v3.tex L433 footnote documents the three distinct regressions; `reproduce.py` now scores each spec as DIVERGENT_SAME_SIGN (NOTE tier) pending L11 errata path (c) for the 17-55% magnitude divergence vs paper.
- ~~C2: Kupiec p-values aggressively rounded (0.67→0.60)~~ **RESOLVED 2026-04-19**: tables.tex tab:var_ortho L93 GARCH-Normal 0.40→0.64 + L95 GJR-Student-t 0.60→0.67 (standard rounding of K802 source); reproduce.py HistSim phantom row reclassified UNTRACEABLE. Reproduce gate 7 MISMATCH → 0 across this session: 5 cross-source/period divergences reclassified to NOTE tier (K799 vs K802 DM p / K799 vs K802 GJR+Normal violations / K824v2 vs K802 FHS implementation / Table 1 vs Table 11 kurtosis periods / DM p in-text location), all legitimate reconciliation.
- C3: Table 5 cherry-picks from 3 experiments — K899 unified VaR pending
- C4-C5: Tables 1, 3 partially untraceable
- Main manuscript shortened to 48 pages; remaining compression to ~45 pages is optional rather than blocking

## Supporting Experiments

- **K1256**: Paper 1 T-HM canonical 3-spec Henriksson-Merton γ_HM experiment. All 3 γ signs negative → variance-management thesis confirmed qualitatively. Magnitudes 17-55% smaller than paper body_v3 L433 footnote values; DIVERGENT_SAME_SIGN verdict triggers L11 errata path (c) recommendation. See `experiments/k1256/` (script + results + README); paper-side stub `paper/leverage-direction/experiments/hm_timing_tests_results.json`.
- **K799 / K802 / K824v2**: evaluation layer, GJR skew-t, probabilistic RV quantile VaR (per reproduce.py Check sources).
- **K829**: VaR panel across 7 assets (Table 6 source).
