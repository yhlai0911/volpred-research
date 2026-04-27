# K1261 Baseline Verification — K827v3 Source Confirmed

**Date**: 2026-04-27
**Purpose**: 確認 K1261 fork 的 baseline source，避免 K1261 README 之前的 cross-link 錯誤再犯

## Canonical baseline = K827v3

**Path**: `paper/vt-crowding-abm/experiments/k827v3_abm_fixed_liquidity.py`
**Results**: `paper/vt-crowding-abm/experiments/k827v3_abm_fixed_liquidity_results.json`
**Bundled in**: P5 paper folder（per `paper/vt-crowding-abm/reproduce.py` 跑此 script）

K827v3 = **K827 v3 fixed-liquidity** = P5 paper §3 ABM final implementation。**不是** `experiments/vt_crowding_simulation/`（status=draft, metrics={}, placeholder 從未跑）。

## Byte-match Verification: K827v3 vs P5 paper Table 2

| Adoption | Paper main.tex (Table 2) | K827v3 JSON (`vt_sharpe.mean`) | Match |
|---|---|---|---|
| 10% | 0.47 | 0.4674796... | ✅ |
| 20% | 0.50 | 0.4955816... | ✅ |
| 30% | 0.47 | 0.4664402... | ✅ |
| 50% | 0.34 | 0.3356729... | ✅ |
| 70% | 0.08 | 0.0843565... | ✅ |
| 100% | -0.27 | -0.2670369... | ✅ |

Kurtosis at 100%: paper says ~61, K827v3 JSON `kurtosis.mean = 61.35` ✅。

## K1261 Implications

**之前 K1261 README cross-link 錯誤** (commit b013b35e initial → d804892b 改為 vt_crowding_simulation, 仍錯)：應指 K827v3。本 slot 修正。

**K1261 fork blueprint**:
1. Copy `paper/vt-crowding-abm/experiments/k827v3_abm_fixed_liquidity.py` → `experiments/k1261/k1261_non_vt_ablation.py`
2. Replace VT agent class with TF / MR / pure-noise agent classes（保持 ABM core engine + Kyle market maker + VIX endogenous evolution）
3. Run 3 treatments × 7 adoption × 500 MC = 10,500 sims（per K1261 README Phase 1 plan）
4. Verify TF/MR baseline at 0% adoption matches K827v3 0% (both 全 noise traders) — sanity check

## Q3 VIX Feedback Resolution（per K1261 README open Q3）

K827v3 source 確認 VIX 演化是 endogenous（依 ΔΣ realized vol），不依賴 VT 策略 specifically。換 TF/MR 之後 VIX 演化 mechanism 不變（buy/sell pressure 改變 σ_real → VIX 隨之 evolve）。

**K1261 採 γ=200 across all 3 treatments + control**（K1261 README Q3 tentative resolution confirmed）。Sensitivity check (γ=0 disabled subset) 仍是 phase 2 candidate，確認 threshold IS strategy-driven 不是 γ-driven。

## Cross-link

- `paper/vt-crowding-abm/experiments/k827v3_abm_fixed_liquidity.py` (canonical source)
- `paper/vt-crowding-abm/experiments/k827v3_abm_fixed_liquidity_results.json` (verified 數值 byte-match paper Table 2)
- `experiments/k1261/README.md` (本 slot 同步修 cross-link)
- `paper/vt-crowding-abm/main.tex` (P5 paper, Table 2 數字)
- `paper/vt-crowding-abm/reproduce.py` (跑 K827v3, 確認 reproduce gate green)
