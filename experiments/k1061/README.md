# K1061: TWSE 50 Portfolio-Level EAV Binomial Test (T+1 Window)

## 摘要

K1060（10 支個股）已發現台灣財報公告日 T+1 的異常波動率效應（mean ratio_t1=1.466，one-sample p=0.034），但二項式檢定因樣本數不足（6/10，binom p=0.377）而無法支持。本實驗擴展至 TWSE 50 成份股（N=50），以組合層級二項式檢定正式確認此效應。

## 核心結果

| 指標 | 數值 |
|------|------|
| 有效股票數 (N_valid) | 50 |
| ratio_t1 > 1 的股票數 | 37 / 50 |
| 比例 (proportion) | **0.740** |
| 二項式檢定 p（H0: p=0.5，one-sided） | **0.0005** |
| 組合平均 ratio_t1 | **1.2938** |
| One-sample t-stat | **+5.616** |
| One-sample p（one-sided） | **4.55e-07** |
| **判定（VERDICT）** | **SUPPORT** |

## 主要假說

**H_K1061**：在 TWSE 50 成份股中，財報公告日 T+1 的 |return| 顯著大於非事件日基準（ratio > 1）。

- 二項式檢定：proportion=0.740 > 0.6，binom p=0.0005 < 0.05 → **SUPPORT**
- 組合 t 檢定：t=+5.616，p=4.55e-07 → **高度顯著**

## K1060 → K1061 進展

| 指標 | K1060 (N=10) | K1061 (N=50) |
|------|-------------|-------------|
| 樣本股票數 | 10 | 50 |
| 波動率代理 | r²（日報酬平方）| \|r\|（絕對報酬）|
| Mean ratio_t1 | 1.466 | 1.294 |
| Proportion > 1 | 6/10 = 0.60 | 37/50 = 0.74 |
| Binomial p | 0.377 (underpowered) | **0.0005** |
| One-sample p | 0.034 | **4.55e-07** |
| Verdict | WEAK | **SUPPORT** |

K1060 的 T+1 效應在 TWSE 50 組合層級得到強力確認。

## 實驗設計

### 資料來源
- **財報公告日.txt**：Big5 編碼，2,411 家公司，158,674 筆，1986-2025
  - 匹配 TWSE 50 成份股代碼（不含 `.TW` 後綴）
  - 篩選 2010-01-01 至 2025-12-31
- **yfinance**：50 支 `.TW` 股票日頻收盤價（auto_adjust=True）

### 方法論

1. **波動率代理**：`|r_t| = |log(close_t / close_{t-1})|`
2. **事件日定義**：
   - T+0 = 財報公告日（台灣通常盤後公告，不可交易）
   - **T+1 = T+0 的下一個交易日**（公告後首個可反應日）
3. **非事件基準**：排除 [T-5, T+5] 窗口的所有一般交易日
4. **Ratio**：`ratio_t1 = mean(|r|_{T+1}) / mean(|r|_{non-event days})`
5. **個股 t-test**：Welch 兩樣本 t-test（H0: event|r| = non-event|r|）
6. **組合二項式檢定**：H0: p(ratio_t1 > 1) = 0.5，one-sided alternative

### Lookahead 確認

- `event_date`（T+0）= 公告日，**不**用於計算任何收益
- T+1 收盤價 = 公告日後的隔日收盤，符合可交易時序，無 lookahead
- 基準期間排除 [T-5, T+5]，確保乾淨比較

### 最低樣本要求
- 每支股票至少 10 個公告事件 → 全部 50 支均符合
- N_valid ≥ 30 → 實際 N_valid = 50 ✓

### Random Seed
- 全部隨機程序使用 seed=42（本實驗無 bootstrap，僅統計檢定）

## 資料摘要

- 財報公告總筆數：153,875
- TWSE 50 對應筆數（2010-2025）：3,132
- 有效公告公司數：50 / 50
- 下載成功股票：50 / 50

## 圖表

| 檔案 | 說明 |
|------|------|
| `k1061_per_stock_ratio_t1.png` | 50 支個股 ratio_t1 橫截面分佈（含 Welch t-stat），藍色 = ratio>1，紅色 = ratio≤1 |
| `k1061_binomial_distribution.png` | (a) 二項式分佈 PMF + 觀測值；(b) ratio_t1 跨股票分佈直方圖 |

## 文獻

- Patell & Wolfson (1984) J Accounting Research — 個股財報公告日波動率上升
- Beaver (1968) J Accounting Research — 財報公告提升波動率與成交量
- Savor & Wilson (2016) JFQA — 財報公告作為系統性風險事件
- Ball & Kothari (1991) Accounting Review — 事件研究方法論
- K1059：TSMC → 0050.TW ETF NULL（T+0 ratio=1.007）
- K1060：10 支個股 EAV（T+1 ratio=1.466，binom underpowered 6/10）

## 結論

TWSE 50 成份股在財報公告後隔日（T+1）呈現統計顯著的異常波動率上升：
- 74% 的股票（37/50）呈現 ratio_t1 > 1
- 二項式檢定 p = 0.0005（高度顯著）
- 組合平均 ratio_t1 = 1.29，one-sample t = +5.62，p = 4.55e-07

此結果確認了台灣財報公告效應的核心機制：公告在盤後發布，vol shock 延後到 T+1 才顯現。K1060 的 T+1 假說在更大樣本下得到強力支持。

## 限制與注意事項

1. **存活者偏差（Survivorship Bias）**：本實驗使用「當前」TWSE 50 成份股清單（50 支），未追蹤 2010-2025 年間的指數成份股異動。歷史上曾被剔除的成份股（通常因績效不佳）未納入樣本，可能造成 EAV 效應被適度高估。
2. **日曆效應未控制**：未排除 Q-season 集中公告（如每年 3 月、8 月）或市場整體高波動期對基準的干擾。
3. **公告時間精度**：`財報公告日.txt` 記錄的是公告日期（非時間），台灣盤後公告假設統一適用，但部分盤中發布的公告未區分。
4. **yfinance 資料**：使用調整後收盤價（auto_adjust=True），股息調整可能在特定日期引入人為波動。

## 實驗路徑

- 腳本：`experiments/k1061/k1061.py`
- 結果：`experiments/k1061/k1061_results.json`
- 圖表：`experiments/k1061/k1061_per_stock_ratio_t1.png`, `k1061_binomial_distribution.png`
- 承接自：K1059（ETF 層級）→ K1060（10 股個股）→ **K1061（TWSE 50 組合）**
