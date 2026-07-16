# Paper 5: Monotone Strategy-Specific Erosion under VT Crowding — Matched-Control Identification via ABM

**Target Journal**: Quantitative Finance (QF; primary) → JEBO (secondary); FRL only as fast-track fallback with heavy cuts
**Status**: 🔶 **VT-only revision in progress（2026-07-14）** — P0-1~P0-4 完成：敘事單一化、scope 收斂 VT-only（family ordering 全面撤回，含 conclusion / knife-edge 節殘留清除）、K1471 TF/MR 誠實補報（tab:tfmr_gate + RR_TF erosion）、reproduce gate 173/173 GREEN + PDF 零內部路徑洩漏、P0-5 機械批次收官（2026-07-16：redesign-layer §2 描述、sims 口徑、Bonferroni 句、Kyle 頁碼、bib 排序、本 README；末批補上 §3.7 液體性歸因方向倒置 52%→48%、§2.1 明寫「不做 common-random-numbers 配對」及其推論後果、README key results 對回 k1471_full_results.json）。剩：v6 跨模型獨立 review（同模型自審不算）→ QF compliance gate。v4 GREEN PASS 已作廢（同模型自審假陽性第三例）。
**Pages**: 34 | **Citations**: 22 bibitems（xelatex 實測，2026-07-16）

## Data Sources
- Agent-based simulation (no external data needed)
- K827v3: Fixed liquidity ABM with 9 OAT parameter variations

## Reproduction
```bash
uv run python paper/vt-crowding-abm/reproduce.py
```

## Key Results (post-K1471 redesign, 2026-06-11)
- **No discrete tipping point**: sup-Wald exogenous detector rejects flatness for VT (p = 0.001 in all 5 microstructure cells) but identifies no internal break; "70% threshold" was a circular Sharpe-only-detector artifact. Survives Bonferroni over the layer's 35 (cell, treatment) detector runs (35 × 0.001 = 0.035 < 0.05).
- **VT Sharpe monotonically erodes**: canonical cell ($\lambda=0.005$, $\gamma=200$) Sharpe 0.510 @ 10% → -0.271 @ 100%; adjacent path-bootstrap 95% CIs separate from 40% onward; max marginal degradation in (70%, 100%].
- **Mechanism = systematic direction of vol-feedback, not crowded flow per se**: turnover-matched random-direction control RR_VT (same footprint, randomized direction) shows zero degradation in all 5 cells (Sharpe actually improves +0.080~+0.098 from 10% to 100%, mean +0.091, against VT's mean −0.722). Cleaner counterfactual than NoiseControl baseline. Scope qualifier: identified at VT's footprint scale — RR_TF erodes at TF's footprint scale (two orders of magnitude larger).
- **Original "70%" survives only as descriptive level-crossing** (relative drop >70%) in 3 of 5 cells (cell1/3/5).
- **TF/MR family-level evidence qualified**: RR_MR matched-control fails in pathological regime (treatment-input gate failure); TF cell2 pathological regime excluded. Family-level claim weaker than v5.

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
