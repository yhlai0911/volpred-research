# K1308: VIXTWN/VIX Ratio 穩定性驗證（Q6）

**Date:** 2026-05-22  
**Status:** COMPLETE  
**Research Question:** Q6 — VIXTWN 數據累積到更多天數後，ratio 是否維持穩定？

## 動機

K1181（2026-04-17）以官方 TAIFEX VIXTWN Dec 2025–Apr 2026（n=76）計算
VIXTWN/VIX ratio = 1.3906, CV = 0.098，寫入 Paper 2 Sec 2.5。

但 76 天樣本小，paper 數字可能隨新資料漂移。Q6 是追蹤任務：
每當 VIXTWN 累積到 252 天（≈1年）前先做中間檢查，確認 ratio 是否穩定。

本實驗以截至 2026-05-20 的 110 天官方資料（vs. K1181 的 76 天）做第一次穩定性更新。

## 方法

1. 載入 `data/vixtwn/vixtwn_daily.csv`（去重，按日期排序）
2. 載入 VIX 日收盤價（`paper/taiwan-vt/data/…_vix_2008-2026.csv`）
3. 合併，計算 ratio = VIXTWN / VIX（每日）
4. 整體統計：mean、median、CV、std、min/max
5. 穩定性分析：
   - 30-day rolling mean / std
   - OLS trend (β on time index, t-test for significance)
   - Breakpoint check (Chow test 60-day mid-point)
6. 與 K1181 基準比較（N=76, mean=1.3906, CV=0.098）
7. 報告累積天數 / 距離 252 天的進度

## Lookahead 政策

無預測模型，全為回顧性描述統計 — 無 lookahead 問題。

## 成功標準

- ratio 全期 mean 在 [1.30, 1.50] 內 → 與 K1181 基準一致，STABLE
- CV ≤ 0.15 → 低離散
- OLS trend β p-value > 0.05 → 無顯著漂移趨勢

## 結果（2026-05-22，N=119 天）

| 指標 | K1181 基準（N=76） | K1308 更新（N=119） |
|---|---|---|
| mean ratio | 1.3906 | **1.5737** |
| median ratio | — | 1.4639 |
| CV | 0.098 | **0.204** |
| period | Dec 2025–Apr 2026 | Dec 2025–May 2026 |

### 穩定性測試
- **OLS trend**: β=0.0073/day, R²=0.620, **p≈0** → 顯著上升趨勢
- **Midpoint mean shift** (Welch t-test): 前半 mean=1.38, 後半 mean=1.76, **p≈0**
- **最近 30 日 rolling mean**: 2.0643（VIXTWN ~38-40, VIX ~17-18）
- **整體穩定性判定: UNSTABLE**

### 詮釋

K1181 的 ratio=1.39 在 Dec 2025–Feb 2026 期間基本成立，但 May 2026 起
VIXTWN 飆升至 37-40（台灣恐慌指數爆發），而 VIX 僅維持 17-18，
造成比值高達 2.1-2.3。Ratio 並非結構常數，具有顯著時間變動性。

### Paper 2 Sec 2.5 影響

Paper 2 的 "VIXTWN/VIX = 1.393, CV=10%" 需要修訂：
- 加明確樣本期間（Dec 2025–Apr 2026）
- 說明 ratio 為時變量，非穩定結構參數
- 可升級為研究亮點：台灣特有風險溢酬超出美股 VIX 捕捉範圍的量化證據

### 進度

- 目前：119/252 天（47.2%）
- 預計達 252 天：～2026 年 12 月

## 資料來源

- VIXTWN: `data/vixtwn/vixtwn_daily.csv`（官方 TAIFEX，Dec 2025 起）
- VIX: `paper/taiwan-vt/data/0050_tw_twii_2330_tw_2317_tw_2454_tw_0056_tw_spy_vix_2008-2026.csv`（vix_close 欄位）

## 已知限制（Codex CONDITIONAL_PASS K1308）

1. Baseline 比較以 K1181 固定常數 1.3906 為準，非雙樣本正式檢定
2. 日期合併：台灣 VIXTWN（台灣盤）與 VIX（美國盤）以同一日期標籤對齊，無時區修正
3. Midpoint break test 為 Welch t-test，非正式 Chow/CUSUM 結構性斷點
4. 去重以 first row 保留，無跨列值一致性驗證
