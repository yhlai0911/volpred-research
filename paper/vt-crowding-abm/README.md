# Paper 5: When Volatility Targeting Crowds — Quantifying the Tipping Point via ABM

**Target Journal**: Finance Research Letters (FRL)
**Status**: 🔶 **decision_made_awaiting_body_rewrite（2026-06-11 boss confirmed: tipping→monotone erosion）** — K1471 resimulation 完成（Codex CONDITIONAL_PASS）；原 blocked-on-resimulation 解除。前狀態：MAJOR_REVISION — blocked on ABM resimulation（2026-06-10 全組合審查確認 v5 雙審稿人 5 blocking 未修）**。早先「Submission-ready / 4.3★」口徑撤回：v5 Codex+Antigravity 標的 5 methodology blocking 全在——(1) Sharpe-only detector 循環校準（先知 70% 閾值 → 需外生結構斷點檢定）；(2) NoiseControl 固定 0.5 = strawman（需 turnover-matched 隨機方向 active control）；(3) CI 口徑矛盾（Table 1 iid bootstrap vs Fig 1 MC sim → 統一 path-level bootstrap）；(4) cell1 閾值不可再現（M=500 20% vs M=200 70% → K1262b 重跑 M=500 + 加密 grid）；(5) cell3 MR null rank 方向反（→ detector-not-applicable + 主張降 4/5）。全需重跑 ABM，無文字層可改。重跑任務 `experiment_vt_crowding_resimulation_2026_06_11`（P1，走 compute_queue）。findings：`review_history/audit_2026-06-10/audit_findings.json`。｜前段歷史（已被 audit 推翻）：R3 SEVERE=0；v2 revise 2026-04-19。
**Pages**: 15 | **Citations**: 16 (13 original + 3 new: barroso2021, cederburg2020, liu2019)

## Data Sources
- Agent-based simulation (no external data needed)
- K827v3: Fixed liquidity ABM with 9 OAT parameter variations

## Reproduction
```bash
uv run python paper/vt-crowding-abm/reproduce.py
```

## Key Results
- Tipping point: 50-70% VT adoption
- 10-20% adoption: safe (Sharpe ~0.50)
- 50%+: collapse (Sharpe negative, flash crashes)

## Self-Contained Index (2026-04-17)

| File | Status |
|------|--------|
| `data_sources.md` | ✅ Pure simulation — no external data |
| `scripts/README.md` | ✅ Reproduction guide for all ABM experiments |
| `results/README.md` | ✅ Table → JSON source mapping |
| `figures/` | ✅ Directory created (no figures in current draft) |
| `experiments.md` | ✅ Full K-number index (K827–K864) |

## Supporting Experiments (K Index)

| K | Title | Key Result |
|---|-------|-----------|
| K827 | ABM VT Crowding (base) | Original simulation baseline |
| K827v2 | ABM Sensitivity | OAT 9-parameter sweep (Table 3) |
| K827v3 | ABM Fixed Liquidity | Main results: tipping point 50–70% |
| K864 | Heterogeneous ABM | Microstructure effects (Table 2) |
