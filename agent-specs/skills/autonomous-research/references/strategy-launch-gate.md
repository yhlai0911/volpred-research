# Strategy Launch Gate

這份文件是 `autonomous-research` 的 runtime reference。

在以下情況先讀這份，再決定是否把研究產出推進到平台層：

- 新策略看起來有顯著 alpha / drawdown 改善
- 想判斷某個策略值不值得上架到 `STRATEGY_REGISTRY`
- 需要把「研究完成」和「平台上架」切開

## Owner 與 handoff

- **owner**：`autonomous-research`
- **平台執行**：`admin-ops`
- **策略文章**：`feed-publisher`

本檔只負責回答一件事：**這個策略是否已達到可上架門檻？**

它**不負責**：

- 實際寫入 DB / 啟用策略
- 文章池與通知
- 部署與 runtime 操作

## Gate 結論格式

每次檢查後，只輸出以下三種結論之一：

- `PASS`：可進入平台上架流程
- `HOLD`：有潛力，但證據不足
- `FAIL`：明確不應上架

結論必須附：

- `strategy_key`
- 使用的樣本期間
- 五項檢驗各自結果
- 主要風險或 blocker
- 下一步建議

## 五項檢驗

### 1. 同期間比較

目的：避免用不同 market regime 的回測期間自我美化。

標準：

- 用 `scripts/evaluate_new_strategy.py`
- 比較區間固定為 `COMMON_START (2023-01-04) ~ today`
- Sharpe 必須 **>= 已上架策略中位數**

若沒有通過：

- 直接 `HOLD` 或 `FAIL`
- 不要因為長樣本好看就跳過同期間比較

### 2. Cross-OOS

目的：避免只在單一 regime 有效。

標準：

- 切成 5 個非重疊 2 年區間
- 勝過 BH 或 `50/50 SPY/GLD` **>= 3/5**

若只在 1-2 個區間有效：

- 視為 regime-specific
- 除非策略定位本來就是特定 regime overlay，否則不進上架

### 3. Codex 審查

目的：先排除 mechanical artifact。

標準：

- 無 HIGH severity bug
- 特別檢查：
  - `signal.shift(1)` / lag
  - same-day lookahead
  - TX roll / transaction cost
  - baseline lag 是否一致

只要這一項有疑點：

- 一律 `HOLD`
- 不能先上架再補審

### 4. Sensitivity

目的：避免參數剛好卡在 lucky point。

標準：

- 關鍵參數做 `+-20%` 變動
- Sharpe 不得下降超過 `30%`

如果稍微改參數就崩：

- 視為 overfit
- 不進上架

### 5. MDD 可接受

目的：避免風險輪廓和網站策略定位不相容。

標準：

- 同期間 MDD 必須 **< -20%**

若策略是高波動槓桿型：

- 必須額外說明其定位不是主推核心配置
- 預設仍不視為一般上架候選

## 進入平台前的最小交付

`PASS` 之前，至少要有：

- 實驗目錄與結果 JSON
- 可追溯的 methodology 與數字
- 一篇對應的 feed 文章或明確文章計畫
- 明確的操作說明與資產權重邏輯

缺任一項都不要直接丟給 `admin-ops`

## 建議流程

1. 研究完成後先跑這份 gate
2. `PASS` 後才：
   - 用 `feed-publisher` 產出策略文章
   - 用 `admin-ops` 做 `strategy-upsert` / activation
3. 實際上架細節再讀：
   - `add-strategy-guide.md`
   - `admin-ops/references/platform-api-manual.md`

## 常見失敗型態

- 長樣本很好看，但 `COMMON_START` 後普通
- Sharpe 高很多，但 lag 寫錯
- 只在單一 crisis window 有效
- 參數稍改就崩
- MDD / turnover / cost 不符合網站定位

## 開工前先查

- `docs/error_log.md`
- `docs/strategy-registry.md`
- `add-strategy-guide.md`
