# K1413 — AI 五層產業鏈的波動率 / 跨層相關性視角

## 動機

熱門財經自媒體在講「AI 五層蛋糕」（能源→晶片→基礎設施→模型→應用）的資本支出
產業鏈。VolPred 的差異化不是再講一次產業故事，而是用真數據回答：這五層的代表
類股，在**波動率**與**跨層相關性**上過去 / 現在怎麼互動？哪一層是波動源頭、相關性
regime 怎麼變、有沒有 lead-lag 套利空間。

## 資料

- 來源：yfinance 日線 **adjusted close**（`auto_adjust=True`，含股息調整）
- 期間：2023-01-04 ~ 2026-06-02，855 個交易日
- snapshot 已 pin 至 `k1413_prices.csv`（yfinance 不可回溯，依 error_log 2026-04-19/05-06 教訓）

五層等權籃子（依公開的 AI 五層框架歸類；先算個股日報酬再等權平均）：

| 層 | 代表股 |
|---|---|
| L1 能源/電力基建 | VST, CEG, VRT, ETN |
| L2 晶片 | NVDA, TSM, AVGO, MRVL, MU |
| L3 基礎設施/伺服器/網通 | SMCI, DELL, ANET |
| L4/L5 模型/應用 (hyperscaler) | MSFT, GOOGL, AMZN, META |
| 基準 | SPY |

## 方法（描述統計為主，固定 seed=1413，無 lookahead）

1. **年化已實現波動率**：rolling 63 交易日 std × √252（回看窗口，無前視）→ 圖一
2. **跨層相關性矩陣**：分三段期間（2023 / 2024 / 2025-至今）對比 daily return 相關 → 圖二
3. **lead-lag**：各層 daily return 對晶片層 lag±5 的 cross-correlation，找 |corr| 最大的 lag
4. **AI 主題集中度**：每段期間五層（不含 SPY）的平均跨層相關

## 關鍵結果

**全期間年化波動率**（高到低）：

| 層 | 年化波動率 |
|---|---|
| L3 基礎設施 | 51.7% |
| L1 能源電力 | 41.2% |
| L2 晶片 | 40.9% |
| L4/L5 模型應用 | 25.1% |
| SPY | 15.1% |

- 波動最高的是**基礎設施層**（51.7%，SMCI 拉動），非晶片；hyperscaler 最穩（25.1%）。
- 四層滾動波動率同步觸頂於 **2025-04-25**（關稅衝擊）：L1 85.1% / L3 81.0% / L2 74.3%。
- 截至 2026-06-02：L2 42.4% / L1 39.0% / L4/L5 24.9%（已自 4 月高點冷卻）。

**跨層相關性 regime 上升**（平均跨層相關）：

| 期間 | 平均跨層相關 |
|---|---|
| 2023 | 0.494 |
| 2024 | 0.531 |
| 2025-至今 | 0.645 |

- L1 能源電力 vs L2 晶片相關：0.51（2023）→ 0.61（2024）→ 0.79（2025），AI 主題集中度顯著上升。

**lead-lag（vs 晶片層）= null result**：

- 四層對晶片的最強相關全部落在 **lag 0（同日）**，無穩定領先/落後。
- 同日相關：L1 0.69 / L3 0.69 / L4/L5 0.58。
- 日線資料下，靠層間時間差套利無空間（對配對交易者是重要負面情報）。

## 檔案

- `k1413.py` — 主程式（抓資料、算波動率/相關性/lead-lag、產圖、寫 JSON）
- `k1413_results.json` — 全部數字
- `k1413_prices.csv` — pin 住的價格 snapshot
- `k1413_vol_timeseries.png` — 圖一：各層滾動年化波動率時序
- `k1413_corr_regime.png` — 圖二：三段期間相關性矩陣
- `draft.md` — 讀者向繁中文章草稿（anti-ai-style 自查過）

## 限制（caveats）

- 籃子等權而非市值加權，個股權重影響結果。
- 樣本期間僅涵蓋 AI 資本支出上行週期，未含完整空頭。
- 相關性與 lead-lag 為描述統計，未做正式統計檢定（DM / bootstrap）。
- yfinance adjusted close 隨股息與企業行動回溯調整，本次已存檔 pin 住。
- 非投資建議。

## 復現

```bash
cd experiments/k1413 && python3 k1413.py
```

需要 yfinance, pandas, numpy, matplotlib，及 CJK 字型（macOS：Arial Unicode MS）。
seed=1413 固定；資料若因 yfinance 回溯調整而與 snapshot 不符，以 `k1413_prices.csv` 為準。
