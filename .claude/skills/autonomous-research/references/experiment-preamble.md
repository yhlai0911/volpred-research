# Experiment Agent Preamble（實驗 Agent 必讀）

**此文件必須附加在每個實驗 agent prompt 的開頭。不可省略。**

## 1. 模型-Target 匹配規則（最重要）

不同波動率模型預測不同的東西，評估必須在各自的原生 target 上進行：

| 模型類型 | 預測標的 | 正確評估 target | 不可用的 target |
|---------|---------|----------------|----------------|
| GARCH/GJR/EGARCH | close-to-close σ²（全日，含隔夜）| r²（squared daily return）| 日內 RV |
| HAR-RV | 日內 realized variance（僅交易時段）| 5-min RV | r² |
| MEM | |r| 或 r² | 各自原生 | 混用 |
| Range (Parkinson/GK/RS) | 日內 high-low range | range-based vol | r² |

**跨模型公平比較的唯一正確方式**：
1. Patton (2011): QLIKE on r²（proxy-robust，排名一致性有理論保證）
2. Hansen & Lunde (2005): 最優加權 RV_total = w₁×RV_intraday + w₂×r²_overnight
3. Spearman rank correlation（分配無關）

**絕對禁止**：
- 用 RV target 評估 GARCH 然後說 HAR 贏（HAR 本來就預測 RV）
- 用 r² target 評估 HAR 然後說 GARCH 贏（GARCH 本來就預測 σ²）
- 把「模型在自己 target 上贏」宣稱為「發現」——這是設計的必然，不是實證結果

## 2. Mechanical vs Empirical 區分

如果結果可以從模型定義直接推導，它是 **mechanical result**，不是 empirical finding：
- Mechanical: HAR 在 RV 上贏 GARCH（定義使然）
- Empirical: HAR-RV 經 Hansen & Lunde 調整後在全日 vol 上仍勝 GARCH（需要實證驗證）
- Mechanical: gamma > 0 implies VT de-levers after negative returns（GJR 方程式使然）
- Empirical: cross-sectional gamma-VT correlation exceeds mechanical prediction（需要數據）

**不可把 mechanical result 宣稱為 contribution 或 discovery。**

## 3. 統計門檻

| 檢定 | 門檻 | 依據 |
|------|------|------|
| DM test | Harvey (2016) \|t\| > 3.0 | 多重檢定校正 |
| Sharpe 差異 | SE ≈ 1/√N_years | 19 年 SE=0.23 |
| Cross-sectional | N ≥ 7 | Spearman 穩定性 |
| Bootstrap | ≥ 1000 reps | CI 精確度 |
| GARCH window | ≥ 500（建議 2000）| Hwang & Valls Pereira (2006) |
| OOS 期間 | ≥ 252 天 | 至少涵蓋 1 年 |

**Sharpe > 2x baseline = 幾乎一定有 bug，先停下來檢查。**

## 3b. 風險管理評估標準（VaR + ES）

模型比較必須涵蓋 VaR 和 ES 兩個維度：

| 評估 | 方法 | 門檻 | 依據 |
|------|------|------|------|
| **VaR unconditional** | Kupiec (1995) LR test | p > 0.05 | 違約率是否符合目標 |
| **VaR conditional** | Christoffersen (1998) CC test | p > 0.05 | 違約是否獨立 |
| **VaR Basel** | Traffic light (Green/Yellow/Red) | Green | 250天內違約次數 |
| **Trinity** | Kupiec + CC + Basel 全過 | 全 PASS | 三重把關 |
| **ES backtest** | Acerbi & Szekely (2014) Z-test | p > 0.05 | ES 是否充分覆蓋尾部 |
| **Joint VaR-ES** | Fissler & Ziegel (2016) scoring | 越低越好 | 唯一 strictly consistent joint loss |

**VaR 和 ES 必須同時在 1% 和 5% 信心水準評估。只測 1% 不夠。**
**VaR/ES 評估必須分 In-Sample 和 Out-of-Sample 分別報告。** IS PASS + OOS PASS = 可信；IS PASS + OOS FAIL = overfitting。只報一種沒有說服力。

## 4. 防錯規則

- **DM test**：用 `from volpred.stats.model_evaluation import strategy_dm_test`，不自己寫
- **0050.TW**：必須 `from volpred.utils import clean_tw50_data`
- **Lookahead**：`signal = signal.shift(1)` 寫在代碼裡，不靠記憶
- **GARCH OOS**：逐日遞迴 h[t]=f(h[t-1],r²[t-1])，不用 stale variance
- **Student-t**：考慮 scale term sqrt((df-2)/df)
- **Basel/統計檢定**：用標準實作，不自定義閾值
- **TAIFEX 期貨轉倉**：不要直接用 TX1（近月），要用 **TX（全合約）數據，每日按成交量選最活躍的合約月份**。結算日（每月第三個週三）TX1 自動切換合約月份會有 roll gap（~0.5-1.0%）。正確做法：讀 TX 檔案 → 按「到期月份」分組計算成交量 → 選當日成交量最大的合約 → 只用該合約的 tick 計算 return/RV。這樣在流動性自然轉移時平滑切換，不會有假波動

## 5. 結果自我質疑（實驗完成後必做）

在記錄結論前，問自己：
1. 這個結果是 mechanical 還是 empirical？
2. 這跟 research_program.md 已有的方法論標準矛盾嗎？
3. 如果用不同的 target/proxy，結論會改變嗎？
4. Sharpe > 2x baseline 嗎？（如果是，90% 有 bug）
5. 這個結論的強度是否超過證據支持的範圍？

## 6. Periodic Model Robustness（PRG/PRS 專用）

- **Session 收盤價可交易性**：session 收盤價可能無法即時交易。Robustness check 應使用收盤前 n 分鐘（n=1,5,10）的價格重算 session return 和 RV，確認結果穩健。
- **Information set 說明**：PRG/PRS 使用「前一 session 已實現的資訊」預測「下一 session」。這不是 lookahead——隔夜 session 在日盤開盤前已結束，日盤 session 在夜盤開盤前已結束。論文必須明確標註每個模型的 information set。
- **公平比較**：PRG 在 session 邊界有更多資訊（剛完成的 session）。與 GJR（日頻）比較時，PRG 的優勢包含「模型結構」+「資訊即時性」兩個成分。要隔離純模型結構價值，可比 PRG vs GJR-X(r²_overnight)。

## 7. Worktree 保存規則（必做）

**在完成所有工作後，必須執行以下命令保存檔案：**
```bash
git add -A && git commit -m "K9XX: description"
```
不 commit = 檔案在 worktree 清理時永久遺失。K923/K924/K932 都因此遺失過腳本。
