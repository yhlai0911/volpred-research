# K1197: Paper 1 GJR vs EWMA Crisis Period Robustness

- **Experiment ID**: `k1197`
- **Status**: completed
- **Created At**: 2026-04-17
- **Worktree**: agent-a73db749
- **Parallel tasks**: K1195, K1196 (independent)

## 問題描述

Paper 1 ("Leverage Direction and Volatility Targeting Alpha") 的 crisis robustness 章節宣稱 GJR-GARCH 在危機期間提供更好的 MDD 保護。KB J6 記錄：「EWMA(0.97) Sharpe 0.828 ≥ GJR 0.782 (5/5 assets), MDD 12.3% ≈ 12.5%」。

本實驗驗證：
1. 三個危機期間（GFC 2008 / COVID 2020 / Rate Hike 2022）GJR vs EWMA(0.97) 的 MDD 保護
2. 五個資產 (SPY, GLD, TLT, BTC-USD, EEM) 的跨資產穩健性
3. 與 KB J6 full-period Sharpe claim 的比對

## 動機

- Paper 1 Section: crisis robustness 需要量化 GJR 危機期 MDD 優勢
- KB J6 是跨資產全期比較，未深入每個危機期的差異
- 前置實驗 gjr_vs_ewma_crisis（stub）設計類似，本實驗正式化並以 Paper 1 三大指定危機為主

## 方法

- **模型**：GJR-GARCH(1,1,1) + Student-t，EWMA(λ=0.94), EWMA(λ=0.97)
- **估計**：Rolling window = 500 天
- **VT 策略**：w_t = σ_target / σ_{t-1}（滯後，無 lookahead），σ_target = 10% annualized，max leverage = 1.5
- **OOS 期間**：2017-01-01 至 2025-12-31（對齊 Paper 1）
- **危機期間**：
  - GFC 2008: 2008-09-15 → 2009-03-09
  - COVID 2020: 2020-02-20 → 2020-03-23
  - Rate Hike 2022: 2022-01-03 → 2022-10-12
- **Metrics**：Sharpe (RF=4%), MDD, VaR 1% violations
- **Seed**: 42

## 結果摘要

### 每危機 GJR 贏 MDD 資產數

| 危機 | GJR 贏 | 總資產 |
|------|--------|--------|
| GFC 2008 | 4/4 (BTC 無資料) | 4 |
| COVID 2020 | 5/5 | 5 |
| Rate Hike 2022 | 3/5 | 5 |

### SPY 危機明細

| 危機 | GJR MDD | EWMA(0.97) MDD | MDD Premium | Avg γ |
|------|---------|----------------|-------------|-------|
| GFC 2008 | -12.3% | -13.4% | +1.14% | 0.184 |
| COVID 2020 | -10.6% | -15.3% | +4.69% | 0.347 |
| Rate Hike 2022 | -13.3% | -14.2% | +0.91% | 0.245 |

### KB J6 比對

| Metric | KB J6 | K1197 (OOS 2017-2025) |
|--------|-------|----------------------|
| EWMA wins Sharpe (out of 5) | 5/5 | 3/5 |
| SPY GJR Sharpe | 0.782 | 0.414 |
| SPY EWMA(0.97) Sharpe | 0.828 | 0.358 |

**KB J6 Verdict**: `(b) EWMA win rate < 4/5 — partial match`

差異原因：KB J6 可能使用不同 OOS 期間 / 不同 window size。本實驗 OOS=2017-2025 含 rate hike 期，TLT/EEM 在此期間 EWMA 反而略優，導致全期 EWMA 未達 5/5。

## 預期

- GJR 在 COVID、GFC 期間 MDD 應明顯優於 EWMA（因 γ 高）
- Rate Hike 2022（緩慢下跌）兩者差異較小

## 結論

1. **GJR 危機 MDD 優勢確立**：COVID(5/5)、GFC(4/4) 一致性高；Rate Hike 2022 較弱(3/5)
2. **機制一致**：COVID 期 SPY avg γ=0.347 最高，MDD premium 也最大(4.69%)，符合 γ驅動保護的預期
3. **KB J6 Partial Match**：全期 Sharpe EWMA wins 3/5，未達 J6 聲稱的 5/5；SPY Sharpe 量值差距較大（0.414 vs 0.782）→ 可能 KB J6 使用不同 OOS 期間
4. **對論文的影響**：危機 MDD 保護結論仍成立；全期 Sharpe 數字不能直接引用 KB J6，需重新確認其 OOS 期間設定

## 資料來源

- yfinance: SPY, GLD, TLT, BTC-USD, EEM
- 期間：2005-01-01 至 2025-12-31
- 樣本數 per asset: 5,281 (SPY/GLD/TLT/EEM), 4,122 (BTC)

## 相關 KB / 實驗

- KB J6: ewma_vs_garch full-period Sharpe comparison
- gjr_vs_ewma_crisis: predecessor stub experiment
- K1185: Paper 1 Table 4 VaR (OOS alignment)
- K902: Paper 1 Tables 1+3 rolling gamma

## 輸出檔案

- `k1197.py` — 主實驗腳本
- `k1197_results.json` — 完整結果
- `k1197_vs_paper1_crisis_diff.md` — Paper 1 差異分析
- `run.log` — 執行日誌
