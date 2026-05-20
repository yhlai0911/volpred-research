# K1382: Multi-Horizon VaR — GARCH-Sim vs Square-Root-T (SPY 2015-2025)

## 動機

Paper 1（leverage-direction）已驗證 1-day VaR 框架（K1185/K1186）。業界普遍使用「平方根時間法」(Square-Root-of-Time, SRT) 做多期風險估計：`VaR_h = VaR_1 × sqrt(h)`。然而：

- SRT 假設報酬 i.i.d.，GARCH 效應存在時此假設違反
- Basel III 規定銀行使用 10-day VaR；許多機構仍用 SRT 簡化計算
- 正確做法：GARCH 蒙地卡羅模擬 h 步路徑

本實驗量化 GARCH-Sim vs SRT 在不同時間期間（h=1,5,10,21）和市場環境（平穩/COVID/升息）下的 coverage 差異，以 Kupiec LR test 統計檢定兩種方法的準確性。

此實驗對應 `research_program.md` open question（line 56）：「Multi-step VaR（proper GARCH h-step formula）」。

## 方法

### 模型

GJR-GARCH(1,1) + Student-t 分佈（Paper 1 最佳參數配置），使用 `arch 8.0.0`。

### 三種 VaR 方法

1. **GARCH-Sim**：arch 套件的蒙地卡羅模擬（10,000 條路徑），累積 h 天報酬的分位數
2. **SRT**：`VaR_h = VaR_1 × sqrt(h)`，VaR_1 用 GARCH 預測波動率 + Student-t 分位數
3. **HistSim**（基準）：rolling 250 天的 h-day 累積報酬歷史分位數

### 時間期間與信心水準

- Horizons：h = 1, 5, 10, 21 天
- 信心水準：α = 1%, 5%（左尾）

### OOS 設定

- In-sample（初始估計）：2000-01-04 ~ 2014-12-31（~3772 天）
- OOS 驗證：2015-01-02 ~ 2025-12-31（~2750 天）
- Rolling refit：每 21 個交易日重估一次模型（降低計算成本）

## Lookahead Policy

- **絕對無前視偏差**：第 t 天的 VaR 估計使用截至第 t-1 天的資料（即 `last_obs=t-1`）
- 實際損失計算：第 t 天到第 t+h-1 天的累積報酬（`returns[t:t+h].sum()`）
- HistSim 同樣只用 t-250 到 t-1 的歷史 h-day 累積報酬

## 評估指標

- **Kupiec LR test**（Unconditional Coverage）：檢定實際超出率是否等於名義水準
- **Exception ratio**：`(實際超出次數 / OOS 天數) / α`（理想值 = 1.0）
- **Sub-period breakdown**：2015-2019（平穩）、2020-2021（COVID）、2022-2025（升息/回正常）

## 成功標準

1. GARCH-Sim 在 h=5, 10, 21 時 Kupiec p > 0.05（coverage 正確）
2. SRT 在 h=10, 21 時 Kupiec p < 0.05（coverage 失敗）或 exception ratio 明顯偏離 1.0
3. 結論清晰量化 SRT 在多期下的偏差方向與幅度

## 資料來源

`paper/garch-x-vix/data/spy_vix_qqq_eem_fez_2000-2026.csv`，SPY 調整收盤價，CRSP/Yahoo Finance。

## 執行

```bash
cd /path/to/volpred-research
uv run python experiments/k1382/k1382.py
```

## 輸出

- `k1382_results.json`：完整 Kupiec test 結果、exception ratio、sub-period 分析
- `k1382_var_comparison.png`：多期 VaR 方法比較圖（如 matplotlib 可用）
