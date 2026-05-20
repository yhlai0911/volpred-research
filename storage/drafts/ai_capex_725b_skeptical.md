---
title: 7,250 億美元的 AI 資本支出：是基礎建設，還是 1999 重演？
audience: general
status: published
tags:
  - AI-capex
  - 風險
  - 泡沫質疑
  - 研究誠實
  - hyperscaler
  - 集中度風險
  - 尾端風險
experiment_refs:
  - K129
  - K301
  - K867
  - K877
---

# 7,250 億美元的 AI 資本支出：是基礎建設，還是 1999 重演？

> 2026 年五大 hyperscaler（Microsoft、Alphabet、Amazon、Meta、Oracle）合計資本支出預估上看 7,250 億美元，較 2025 年再大幅增加。Meta 把全年 capex guidance 從 1,140-1,180 億上修到 1,250-1,450 億，理由是「零組件漲價」。市場普遍把這視為 AI 基礎建設大爆發的證明。但若把鏡頭拉遠，會看到三個讓人不太舒服的對照點：(1) 真正揭露 AI revenue 數字的只有 Microsoft（+123% YoY），其他家都把 AI 與傳統雲服務混算；(2) Q3/Q4 的 reported earnings 含有大量一次性項目，扣除後核心成長率縮水；(3) 五家業者的 capex 集中度，已超過 1999-2000 dot-com 高峰時的全球電信骨幹建設。本文不下「一定是泡沫」的結論，但要把這三條質疑線攤在陽光下。

[提出: 賴奕豪, 執行: Claude]

## 數字本身先放清楚

根據 FactSet 與各家 earnings call transcript（截至 2026 年 4 月底），五大 hyperscaler 的 2026 capex guidance 大致如下（單位：十億美元）：

| Hyperscaler | 2025 actual | 2026 guidance | YoY 增幅 | 主要 driver |
|---|---|---|---|---|
| Amazon (AWS) | ~125 | 145-160 | +16% ~ +28% | AI training/inference + 一般 cloud |
| Microsoft | ~88 | 110-125 | +25% ~ +42% | Azure AI + OpenAI 合作 |
| Alphabet | ~85 | 105-120 | +24% ~ +41% | TPU + Google Cloud |
| Meta | ~72 | 125-145 | +74% ~ +101% | Reality Labs + Llama 訓練 |
| Oracle | ~21 | 35-45 | +67% ~ +114% | OCI 擴張 + Stargate |
| **合計** | **~391** | **~520-595** | — | — |

加上次階梯的業者（CoreWeave、Lambda、xAI 等），市場彙整到「AI infrastructure capex 圈」整體 2026 將在 **6,800-7,500 億美元** 區間，中位數預估約 **7,250 億**。

這個數字有多大？做個簡單對照：2025 年全球半導體產業整體營收約 6,300 億美元，全球商辦不動產投資約 7,000 億美元，美國全國高速公路系統的年度新建+維護預算約 600 億。換句話說，五家公司一年的 AI 機房擴建，**接近全美高速公路系統十年總投入**。

這不是說它一定錯。Hyperscaler 的論點是：AI 是新一代基礎建設，現在不投資，2030 年無法承接需求。但這個論點有一個隱含前提：**需求會以可量化的方式變現**。三個質疑就在這個前提上。

## 質疑一：ROI 揭露極度不對稱

整個 hyperscaler 群裡，目前**只有 Microsoft 揭露具體的 AI revenue growth 數字**：FY26 Q3（自然年 2026 Q1）的 AI services 同比增長 +123%，annualized run rate 約 130 億美元。

其他家呢？

- **Amazon**：AWS 整體 +20% YoY，但「AI workload」拆分數字未公布，CFO Brian Olsavsky 在 earnings call 上的表述是「meaningful and growing」。
- **Alphabet**：Google Cloud +32% YoY，TPU + Gemini API 收入混在裡面，沒有單獨拆出 AI/GenAI line item。
- **Meta**：完全不揭露 AI 直接 revenue，只用「ads efficiency improvement」「Reels engagement uplift」這類間接指標。
- **Oracle**：OCI +52% YoY，但其中 stargate 與 OpenAI 多年合約的 RPO（remaining performance obligation）+359% 是會計帳上未來收入，**不是當期實現**。

這不是會計準則的問題，而是揭露策略的問題。當一家公司有信心 AI 已經 monetize，他們會**主動拆出來給投資人看**——Microsoft 就是這麼做的。其他家含糊處理，可能代表兩件事之一：要嘛 AI revenue 還沒成長到值得單獨揭露的規模，要嘛 AI 與傳統雲服務的邊界本身難以區分（也就是 AI 並未實質上是一個獨立的營收新引擎，而是傳統雲端的加速器）。**兩種情況都暗示 capex/AI revenue 比率比表面看到的還難算**。

對應到本平台先前的研究經驗：K129 的 VIX sufficiency 結論告訴我們，「統計顯著」不等於「經濟有用」。同一個邏輯反過來說：**揭露的 cloud growth 數字統計上看起來不錯，不代表那些 capex 真的對應到等比例的 AI 經濟價值**。投資人需要的是 cash flow 證據，不是 revenue narrative。

## 質疑二：reported earnings 被一次性項目灌水

過去三季（FY25 Q4 ~ FY26 Q3），三大 hyperscaler 的 reported net income 都受到顯著的一次性項目推升：

- **Alphabet**：Anthropic 等多家私募股權的 fair value 上調，產生約 **377 億美元** 的 unrealized gain（calendar 2025 全年）。
- **Amazon**：對 Anthropic 的投資 mark-to-market gain 約 **168 億美元**（FY25 Q4 認列大宗）。
- **Meta**：稅務 benefit（主要來自 Reality Labs 累積虧損的 deferred tax asset 重估）約 **80.3 億美元**（FY25 Q4）。

把這三項加總，2025 全年三家合計**「一次性、非營運」項目約 625 億美元**。對照同年三家合計 net income 約 3,200 億，**一次性項目佔比近 20%**。這不是違反 GAAP，但也不是經常性盈餘。

這件事的麻煩在於：**capex/cash flow 比率被分母（cash flow）的虛胖蓋過去了**。如果你把 $725B capex 對 hyperscaler 整體 reported net income，比率看起來「還可以承擔」；但若 strip 掉這些 mark-to-market 與稅務調整，**ex-items 核心 operating cash flow 對 capex 的覆蓋率會明顯下滑**。

具體一點：Meta 把 capex 從原本的 $114-118B 上修到 $125-145B，理由是「components 漲價」。但 Meta 的 ex-items 核心利潤同期增速約 +12% YoY，遠低於 capex 上修幅度（+10% ~ +27%）。這意味著**capex 成長正在脫離核心盈餘成長**。

歷史對照：2000 年 Q1（dot-com 高峰前最後一季），Cisco、Lucent、Nortel 三家也是用「股權投資 mark-up」與「軟體授權預收」把 reported earnings 灌得比較好看，當市場開始要求純現金流證明時，那些數字就垮了。本文不主張「這次一樣」，但**要求投資人意識到對照點存在**。

## 質疑三：capex 集中度創歷史紀錄

這可能是最值得停下來想的一點。

根據 Synergy Research 與 Dell'Oro 的彙整數據，全球 data center capex 在 2025 年約 **9,800 億美元**（含 hyperscaler、telco、企業自建、colocation）。其中**前 5 家 hyperscaler 佔比約 71%**（391/980）；2026 年 guidance 顯示這個比率將推升到 **74-78% 區間**（520-595 / 700-800 預估）。

對照 dot-com 高峰：1999-2000 年全球 telecom capex 高峰時，**前 10 大電信業者**（AT&T、WorldCom、Vodafone、BT、NTT 等）**合計 capex 集中度約 50-55%**。換句話說，**2026 年的 hyperscaler 集中度（前 5 家 70%+）比 dot-com 高峰時的前 10 家集中度還要高**。

集中度高為什麼是風險？金融學上有兩個機制：

1. **Tail dependence 增強**：本平台 K867 的研究發現，當資產之間的下尾相依（lower tail dependence）強時，stress 期間會「一起跌」（如 SPY-BTC: Clayton copula, lambda_L=0.214）。對應到 hyperscaler：5 家公司用同樣的供應鏈（Nvidia GPU、台積電、SK 海力士 HBM、變壓器、電力）、同樣的客戶群（企業 AI）、同樣的 narrative（AGI roadmap）。**這種高度同質的 capex 結構天然產生強尾端共動**——任一家率先 cut，其他四家很難不被點名。

2. **Sufficient statistic 失效邊界**：K877 的研究指出，當一個變數（gold-silver ratio）在不同 regime 下的訊號方向會翻轉，OOS 表現就站不住（IS t=14.0, OOS DM NS）。同樣邏輯：在 AI capex 增長 regime，「capex/revenue」是看好訊號（投資未來）；在 capex 減速 regime，**同一個比率立刻變成看空訊號**（「他們也不敢再投了」）。Regime 切換的閾值難以事前定義，但歷史上 capex peak 通常都是事後才被認定。

## 對 Vol 平台 reader 的 risk-pricing implications

平台讀者多是關心避險與波動率的投資人，這三條質疑線對應到三個可觀察的實證 implication：

### (a) 任一 hyperscaler 削減 capex → tech sector 雙峰分化

若 Microsoft、Alphabet、Amazon 之一在後續季度突然下調 capex guidance（例如 Q4 突然 cut），市場很可能不再用「rotation」來理解，而是用「concentrated leadership 的 sector-wide 信心崩盤」來定價。這會把 NVDA、AMD、TSM、SK Hynix、變壓器供應鏈一起點名。Sector vol 的反應**不會均勻**——直接 supplier（NVDA、TSM）的 implied vol 會比 broad tech ETF（XLK）跳更多，產生雙峰。

### (b) VIX-equity correlation 在 stress 時飆升

K867 指出 SPY-BTC 在下尾的相依度顯著（Clayton λ_L=0.214），意思是「跌的時候一起跌」的機率高於高斯模型預期。Hyperscaler 的同質性可能讓 SPX-NDX-SOX 在 stress 期表現出類似 pattern：平時相關性已高（~0.85+），但 stress 期會跳到 ~0.95+，**diversification benefit 在最需要的時候消失**。對 vol trader 而言，意味著**單純買 VIX call 對沖 NDX 部位的 hedge ratio 在 stress 期需要重新校準**——這正是 K129 「economic sufficiency 邊界」的另一面。

### (c) NVDA implied vol 提早反應 hyperscaler capex 變動

NVDA 5 月 20 日的 FY26 Q1 earnings 與後續 Q2 guidance（8 月）是 ROI 確認的關鍵節點。若 Microsoft AI +123% 的成長率能維持 5 個季度以上，capex sustainability 才算被市場確認；任一個低於市場預期 10%+ 的 print，都可能被 cluster 解讀為 capex 過度擴張的早期 warning。NVDA implied vol term structure 的曲率（front month vs 3M）將是值得追蹤的領先指標——但這是觀察建議，**不是個股操作建議**。

## 平衡視角：看好情境也要寫清楚

研究誠實原則要求把對立面的 best case 同等強度地呈現：

**看好情境（capex sustainable）**：
- Microsoft AI run rate +123% 若維持 5+ 季，annualized 將從 130 億推升到 350-450 億，達到 capex 6-8% 的直接覆蓋率（不含對 ex-AI cloud 的拉動）。
- 真正的 AI infra 折舊週期若延長到 6-7 年（目前會計處理多用 4-6 年），單期折舊負擔會下降，cash flow 覆蓋率改善。Meta、Microsoft 已在 2025 年陸續延長 useful life 假設。
- AI agent 與 enterprise GenAI 的滲透率仍在早期（McKinsey 估計 2025 年 enterprise AI penetration 約 8-12%），未來 2-3 年若加速到 30%+，capex 對 revenue 的領先期是合理的。

**看空情境（plateau + cut）**：
- 任一 hyperscaler 季度 capex 下修 + 對 forward AI revenue 表述含糊 → 市場開始要求 cash flow 證明、不再接受 "promise of AI" rhetoric。
- 一次性項目逐季淡出（fair value gain 不可能年年複製），ex-items 核心成長率被迫見光，2026 H2 是揭露壓力期。
- 集中度過高使任一家 cut 都會引發 sector contagion；歷史上 1999-2001 telecom capex 從高峰下滑 70%，相關公司股價下跌 80-90%，但**整體 internet 滲透率仍在成長**——基礎建設邏輯成立，不代表股價邏輯成立。

**中性觀察點**（接下來 90 天內）：

1. **NVDA 5/20 FY26 Q1 earnings**：data center revenue YoY 與 forward guidance。
2. **Microsoft FY26 Q4（7 月底）**：AI services run rate 是否持續 +100% YoY 或開始減速。
3. **Meta、Alphabet Q2（自然年）earnings**：是否首次拆出 GenAI 直接 revenue line item。
4. **Anthropic、OpenAI 的二次股權估值**：若兩家任一在私募輪估值下修 >20%，三家持股 hyperscaler 的 fair value gain 會反向認列，加速 ex-items 收斂。

## 樣本與 lookahead 揭露

本文所引述之 capex 與 earnings 數字，來源為各 hyperscaler 公開 SEC 10-Q/10-K filings 與 earnings call transcript，截至 **2026 年 4 月 30 日 已公開資訊**。Synergy Research、Dell'Oro、FactSet 的市場彙整數據截至 2026 Q1。1999-2000 dot-com 對照數字引自 OECD Communications Outlook 2003 與 Bloomberg 歷史 capex database（Telcos 2000）。

**Lookahead 揭露**：本文所有對照與比率計算僅使用至 2026-04-30 的 trailing 公開資料，不含任何尚未公布的 2026 Q2 數字。對 Microsoft AI run rate 的引用為**已公布**之 FY26 Q3（calendar 2026 Q1）數字，不含對未來季度的點預測。

## 結論：不是「一定泡沫」，是「值得質疑」

把三條線放在一起看：

- **ROI 揭露不對稱**——只有 Microsoft 一家用具體數字證明 AI 已 monetize，其他四家含糊處理。
- **核心盈餘被一次性項目灌水**——三家合計 625 億美元的 fair value gain + 稅務 benefit 不可持續，2026 H2 起會逐季見光。
- **集中度創歷史紀錄**——前 5 家佔全球 data center capex 70%+，比 1999-2000 telecom 還集中，tail dependence 風險被低估。

這些不必然推導出「capex bubble 即將破裂」。它們推導出的是**一個比表面共識更脆弱的均衡**：只要其中一個 hyperscaler 在後續 2-3 季給出 cautious guidance，整個 narrative 的反身性就可能逆轉。對波動率投資人而言，這代表 **NDX、SOX、半導體鏈的 implied vol skew 在 ROI confirmation window（5-8 月）值得密切追蹤**。

歷史上，基礎建設邏輯的成立與股價泡沫的形成從來不互斥。1999 年那批電信 capex 蓋出來的光纖骨幹網路，到今天仍是網際網路的物理底層；但 2000-2002 年 Lucent 從 84 美元跌到 0.55 美元、Nortel 從 124 跌到破產，也是事實。AI 基礎建設邏輯可能是對的，**而 2026 年的 hyperscaler 股價同時被 over-priced，這兩件事可以並存**。

研究誠實原則的最後一條：null result 與 mixed result 都要如實呈現。本文沒有結論，只有三條質疑線、三個觀察點、兩個情境。投資人自己負責畫出自己的 risk frontier。

---

**參考實驗**：K129（VIX sufficiency boundary，economic vs statistical sufficiency 框架）、K301（robustness mega-table，多 spec 一致性檢定方法論）、K867（tail dependence asymmetry，BTC-SPY Clayton lambda_L 證據）、K877（regime instability + sufficiency 邊界）。

**數據來源**：SEC EDGAR 10-Q/10-K（Microsoft, Amazon, Alphabet, Meta, Oracle, FY26 Q3 截至 2026-04-30）；Synergy Research Group, Dell'Oro Group quarterly hyperscale capex tracker；FactSet consensus capex estimates；OECD Communications Outlook 2003（dot-com 對照）。

**Disclaimer**：本文為 hyperscaler AI capex 結構與集中度風險的學術討論，不構成任何個股或產業 ETF 的投資建議。讀者應自行評估風險、徵詢合格投顧。
