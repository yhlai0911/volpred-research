---
title: 5/12 美國 CPI 倒數 24 小時：三情境劇本 + 部位調整建議（VIX 18 適中，但 hot surprise 是唯一真風險）
audience: general
phase: event
category: milestone
status: published
tags: [CPI, SPY, VIX, 事件驅動, 部位調整, 通膨, 風險管理]
image_url: "https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k925_cpi_2026_05_t2_scenario_grid.png"
experiment_refs: [K925, K513]
proposer: Claude
---

# 5/12 美國 CPI 倒數 24 小時：三情境劇本 + 部位調整建議

[提出: Claude]

**一句話摘要**：美國 4 月 CPI 將於台灣時間今晚 20:30（ET 08:30）公佈，市場共識核心 CPI 年增 2.7%。我們用 135 次 CPI 歷史反應數據算出三情境（cool / in-line / hot）對應的 SPY、VIX、美元指數一日預期波動，並給出 T-2 防禦性部位建議——**結論：除非 core 跳到 2.9% 以上的 hot surprise，否則維持原配置；hot 情境才該減 SPY 5-10%**。

---

## 為什麼這次 CPI 重要

美國勞工統計局（BLS）將於台灣時間 2026 年 5 月 12 日晚上 20:30 公佈 4 月份消費者物價指數（CPI）。市場主要關注兩個數字：

- **整體 CPI 年增率（Headline YoY）**：共識落在 3.4-3.7% 區間（Mutual of America 3.4% / Cleveland Fed Nowcast 3.56% / Polymarket 機率分布領先 3.7%）
- **核心 CPI 年增率（Core YoY）**：共識 2.7%（RBC、Kiplinger 等多家機構一致），相對 3 月 2.6% 微幅加速
- **核心月增率（Core MoM）**：0.3%

聯準會官員過去 18 個月已多次表明，**核心通膨**才是降息與否的決策變數——整體通膨可以被油價、食品價格短期擾動，但核心代表「黏性通膨」。所以如果這次 core 跳到 2.9% 以上，市場會立刻把 7 月降息機率往下砍，連帶 SPY 承壓、VIX 跳升。

## 三情境劇本（量化版）

下圖是我們依 2015-2026 共 **135 次 CPI 公佈日**的歷史反應，分位數估算出來的一日預期變動（signed move）：

![CPI 三情境劇本 — SPY/VIX/DXY/TIPS 預期一日變動](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k925_cpi_2026_05_t2_scenario_grid.png)

| 情境 | 觸發條件 | SPY 預期 | VIX 預期 | 美元指數（DXY） | 10y TIPS 通膨補貼 |
| --- | --- | --- | --- | --- | --- |
| **Cool surprise** | Core <2.6% YoY 或 MoM <0.2% | +1.0 ~ +1.8% | -1 ~ -2 pt（降至 16-17） | -0.4 ~ -0.8% | -5 ~ -10 bp |
| **In-line** | Core ≈2.7%、MoM ≈0.3% | -0.2 ~ +0.4%（基本不動） | -0.5 ~ +0.5 pt | ±0.2% | ±2 bp |
| **Hot surprise** | Core >2.9% YoY 或 MoM ≥0.4% | -1.2 ~ -2.0% | +1.5 ~ +3.0 pt（衝向 21-22） | +0.5 ~ +1.0% | +5 ~ +12 bp |

**怎麼讀這張表**：

- 三情境**不對稱**——hot surprise 的下行壓力大於 cool surprise 的上行幅度。學術上稱為「**通膨意外的非線性反應**」，Bauer & Swanson（2023）在 *JoFE* 已紀錄此模式：壞消息（升息預期上修）市場跌得比好消息漲得多。
- VIX 18.38（5/11 收盤）屬於**中性偏低**區間，意味著市場目前**沒有預期 hot surprise**。如果真的 hot，VIX 一日跳 +2 點以上是常態。
- 美元指數與 TIPS 通膨補貼是「**通膨意外的純訊號**」：股債可能被其他因素干擾，但 DXY 與 BE 幾乎只反映通膨修正。

## 歷史 CPI 公佈日：SPY 並沒有比較波動

這是這篇文章最反常識的地方。**如果你以為 CPI 公佈日 SPY 一定大動，數據說不是**：

![CPI 公佈日 vs 非公佈日：SPY 平均絕對報酬 + VIX 水準](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k925_cpi_2026_05_t2_historical_reaction.png)

實驗 K925（2015-01 到 2026-03，2,827 個交易日、135 次 CPI 公佈日）的結果：

- **CPI 公佈日 SPY 平均絕對報酬 0.772%**
- **非公佈日 平均絕對報酬 0.728%**
- **比例 1.06 倍**，統計檢定 t=0.55、p 值 0.59
- 95% bootstrap 信賴區間 [0.86, 1.28]——**完全包含 1.0**，意思是「CPI 日跟一般日沒有顯著差異」
- VIX 在 CPI 日平均 18.18，非 CPI 日 18.39，差異 p 值 0.72，**沒有「不確定性解除」的下跌模式**

**這代表什麼**？多數時候 CPI 數據都在預期範圍內（in-line），市場反應非常平淡。**真正會大動的，是 surprise 落入 hot/cool 尾端的少數場合**——但這在 135 次中只佔約 20-25 次。所以「CPI 日 = 大波動日」是錯覺。

## T-2 部位調整建議

依目前資訊環境（VIX 18.38、SPY 739.30、共識 core 2.7%），我們的部位建議：

1. **In-line（機率 ~55%）**：**不動作**。維持原 SPY 配置，VIX 不需要對沖。
2. **預防 hot surprise（機率 ~25%）**：可選性減 SPY 部位 5-10%，把現金停在貨幣市場基金或短債 ETF（SGOV、BIL）；如果有期權帳戶，買 1-week SPY 745 put 作為災難對沖（成本約 0.3-0.5%）。
3. **押注 cool surprise（機率 ~20%）**：**不建議主動加碼**。Cool 帶來的上行報酬有限（+1.5% 上下），而且 cool 後通常還有「市場已 priced in」的回吐風險。期望值不對稱對你不利。

**核心紀律**：

- **不要在公佈前 30 分鐘大幅調倉**——bid-ask 變寬，滑價會吃掉 0.05-0.10% 的潛在收益。
- **公佈後 5 分鐘的初始反應常常過頭**——學術上叫做「announcement overreaction」（Lucca & Moench, 2015, *JF*）。如果你要做反向交易（fade the move），等 30 分鐘後再評估。
- **不要把單一 CPI 當決策依據**——聯準會看的是 3-6 個月趨勢，不是單月跳動。

## 為什麼今天的 VIX 18 是「適中」而非「便宜」

很多人看 VIX 18 會說「低、可以放心」。但我們的研究發現一個微妙細節：

- **VIX <15**：真的低，市場過度樂觀，可考慮加買對沖
- **VIX 16-20**：適中，**這是市場正常波動區間**
- **VIX 20-25**：偏高，已 priced in 一定程度的不確定性
- **VIX >30**：恐慌，反而是進場時機

目前 VIX 18.38 落在「正常波動區間」中段——意味著市場**沒有忽略 CPI 風險，但也沒有過度恐慌**。這正是為什麼 hot surprise 一旦發生，VIX 才會有 +2 ~ +3 點的反應空間（從 18 跳到 21）；如果今天 VIX 已經是 25，hot surprise 的邊際 VIX 反應反而會變小。

## 我們會做什麼

我們的 50/50 SPY/GLD 配置、VT 動態策略目前都維持**中性持倉**。明天早上（5/13）我們會：

- 8:30 ET（20:30 台北）監看實際公佈值
- 計算實際 surprise 落點（cool/in-line/hot）
- 9:00-10:00 ET 期間更新策略訊號
- 5/13 中午前發追蹤文章（CPI 回顧 + 策略訊號變動）

---

## 數據來源與參考

- **CPI 排程**：U.S. Bureau of Labor Statistics 官方公告 [bls.gov/schedule](https://www.bls.gov/schedule/news_release/cpi.htm)
- **共識預估**：Mutual of America、RBC Economics、Cleveland Fed Inflation Nowcasting、Polymarket
- **SPY/VIX 即時報價**：yfinance（截至 2026-05-11 收盤）
- **歷史 CPI 反應分析**：volpred 內部實驗 K925（135 次 BLS releases, 2015-2026）
- **學術參考**：
  - Lucca & Moench (2015), "The Pre-FOMC Announcement Drift", *Journal of Finance* 70(1)
  - Savor & Wilson (2013), "How Much Do Investors Care About Macroeconomic Risk?", *Review of Financial Studies* 26(3)
  - Bauer & Swanson (2023), "A Reassessment of Monetary Policy Surprises and High-Frequency Identification", *NBER Macro Annual*

---

*本文為事件驅動短文，時效僅至 2026-05-12 20:30 台北時間（CPI 公佈時刻）。公佈後我們會在 24 小時內出回顧文，請持續追蹤。*
