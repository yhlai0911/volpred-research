# K1193: Paper 3 Split-Sample Robustness Check

- **Experiment ID**: `K1193`
- **Status**: DIVERGED — needs paper revision
- **Created At**: 2026-04-17
- **Worktree**: agent-af7c5b3e

## 問題描述

Paper 3 (body_v2.tex Section 3.3) 聲稱 split-sample robustness check 結果為：
- Pearson r = 0.487 (p = 0.021)
- Bootstrap 95% CI = [0.114, 0.737]
- Spearman ρ = 0.461 (p = 0.031)

其中 gamma 估計自 2007–2016，TSMOM_orth loading 估計自 2017–2026，N=22 資產。

`nosource_rescan_report.md` 確認這些數字為 STILL_NO_SOURCE（無來源 K 實驗）。本實驗為正式再現嘗試。

## 動機

1. 解決 nosource_rescan_report 中 N15–N17 條目標記的 reproducibility gap
2. 確認 paper 中的 split-sample 數字是否可重現
3. 若無法重現，記錄差異與可能原因以便論文修訂

## 方法

- **Gamma 估計期間**: 2007-01-01 至 2016-12-31（約 2518 交易日）
- **TSMOM loading 估計期間**: 2017-01-01 至 2026-03-20（約 2328 交易日）
- **GJR-GARCH**: `arch` library, `arch_model(returns×100, vol='GARCH', p=1, o=1, q=1)`
- **VT 策略**: 日頻 12/VIX，weight = (12/VIX_{t-1}).clip(0,1)，shift(1) 嚴格執行
- **MKT factor**: 資產本身的 B&H excess return（驗證：與 K55 全樣本 R² 吻合）
- **TSMOM factor**: sign(252 日累積 SPY 報酬，lag 1) × SPY 日報酬
- **Newey-West HAC**: 固定 lag=9（與 K55 一致）
- **Bootstrap**: 5000 次，seed=42，np.random.default_rng，百分位法

## 結果

| 指標 | 本實驗 K1193 | Paper 聲稱 | 差異 |
|------|------------|-----------|------|
| Pearson r | **0.793** | 0.487 | +0.306 |
| p-value | 0.000 | 0.021 | — |
| 95% CI | [0.589, 0.919] | [0.114, 0.737] | — |
| Spearman ρ | 0.749 | 0.461 | +0.288 |
| N | 22 | 22 | — |

**狀態: DIVERGED (0/4)**

## 差異分析

### 根本原因

K1193 產生的 r=0.793 遠高於 paper 宣稱的 0.487。主要原因是 2017–2026 期間的 beta_tsmom_orth 模式與全樣本（K55）截然不同：

1. **國際 ETF 翻轉**：K55 全樣本中 EWJ=-0.006、EWU=-0.007、EWA=-0.011、VNQ=-0.094 均為負值；但 2017–2026 期間這些資產的 beta 翻正（EWJ=0.035、EWU=0.051、EWA=0.082、VNQ=0.039）。

2. **GLD、TLT 翻轉**：K55 全樣本 GLD=-0.073、TLT=-0.078（flight-to-safety 特性）；2017–2026 期間兩者接近零（GLD=0.013、TLT=0.005）。

3. **所有 22 個資產在 H2 均有正 beta_tsmom_orth**（最小 USO=-0.006，其餘均正）。這創造了一個非常緊密的正相關，使 r 從 0.564 升至 0.793，而非 paper 聲稱的衰減至 0.487。

### 可能的 Paper 差異來源

1. **較早的資料截止日**：Paper 可能在 2024 年前計算，當時 VIX regime 不同，國際 ETF 的 H2 beta 可能較低或仍為負
2. **不同的 VT 規格**：Paper 原始計算可能使用 monthly rebalancing VT（非 daily），導致不同的 factor regression 結果
3. **不同的 MKT factor**：若使用 SPY VT excess 作為 MKT（而非資產本身的 BH excess），beta 模式會不同
4. **Bootstrap 方法差異**：若 paper 使用 BCa 或 studentized bootstrap 而非 percentile bootstrap

### 計量含義

本實驗的 r=0.793 並非更差的結果；它代表 2017–2026 期間 leverage effect 與 TSMOM loading 之間的相關性**反而更強**。然而，這與 paper 聲稱的「split-sample 顯示衰減（r 從 0.564 降至 0.487）」正好相反——本實驗顯示增強（r 升至 0.793）。

## 結論

- **Paper 中的 r=0.487 無法在目前的 yfinance 資料（截至 2026-03-20）下重現**
- 實際的分 split-sample 結果為 r=0.793（更強，非更弱）
- Paper 需要更新 split-sample 數字或說明使用不同資料截止日

## 輸出檔案

- `k1193.py`：實驗腳本
- `k1193_results.json`：數值結果
- `k1193_vs_paper3_split_diff.md`：與 paper 的詳細差異比較
- `run.log`：執行日誌

## 相關實驗

- K55: `paper/vt-trend-following/experiments/vt_tsmom_final_n22.json` — 全樣本基準 r=0.564
- K901b: 先前 nosource 掃描（stub，無完整結果）
