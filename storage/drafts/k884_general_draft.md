---
title: "把日盤夜盤拆開，台指期波動率預測會變更準嗎？一個誠實的否定答案"
audience: general
status: draft
tags:
  - 台指期
  - 波動率
  - HAR
  - 日夜盤
  - 實證研究
  - 研究誠實
experiment_refs: [K884]
---

# 把日盤夜盤拆開，台指期波動率預測會變更準嗎？一個誠實的否定答案

## 一、問題從哪裡來

如果你長期關注台指期，會注意到一個結構性事實：台指期有「日盤」和「夜盤」兩個交易時段。日盤對應台股現貨開盤後的連續競價時段，是流動性最深、資訊最密集的窗口；夜盤則延伸到歐洲與美股盤前，反映海外消息與隔夜事件的價格反應。直覺上，這兩段時間「波動的性質」應該不一樣 — 一個跟著本地基本面跑，一個跟著外圍消息跑。

從預測模型的角度看，這個直覺很自然會推到一個假說：

> 與其把一整天的波動率當成一個整體來預測，不如把它拆成「日盤波動率」和「夜盤波動率」兩個分量分別建模，再合成回整日，預測會更準。

這個想法在學術文獻上也有對應的影子，例如 Bollerslev & Ghysels (1996) 的 Periodic GARCH，或更近期把高頻 RV 分成 day/night 兩個 component 的研究。問題是 — 直覺歸直覺，文獻歸文獻 — **拆開來真的有幫助嗎？**

K884 這個實驗，就是在我們自己的台指期 tick 資料上，把這個假說做一次完整的驗證。並且，按照本平台的研究誠實原則，無論結果是支持還是推翻假說，都要如實寫出來。

這篇文章要報告的是一個 **null result**：在我們的樣本上，把日夜盤拆開對 HAR-RV 模型的整日波動率預測**沒有幫助，甚至略差**。這個答案不華麗，但它是研究進步的真實過程的一部分。

## 二、實驗設計

### 資料

- **標的**：台指期（TAIFEX TX），使用 tick 資料，contract 以成交量加權方式滾倉。
- **期間**：2017-05-16 到 2025-12-31，共 2,107 個交易日。
- **In-sample**：2017-05-16 到 2022-07-13（1,264 日）用來估計參數。
- **Out-of-sample**：2022-07-14 到 2025-12-31（843 日）用來評估預測表現。

OOS 期間涵蓋 2022 年熊市尾段、2023 年震盪、2024 年大多頭、2025 年回檔，包含多種市場狀態，是相對嚴格的測試窗口。

### 「整日波動率」怎麼定義

K884 的目標是預測「整日的真實變異」`σ²_fullday`，而它由三個分量組成：

```
σ²_fullday = r²_gap + RV_day + RV_night
```

- `r²_gap`：開盤跳空報酬的平方（夜盤結束到日盤開盤之間累積的報酬）
- `RV_day`：日盤時段的 realized variance
- `RV_night`：夜盤時段的 realized variance

從描述統計看，這三塊在我們樣本中的分佈是：

- 開盤跳空 (gap) 占整日變異的 **27.0%**
- 日盤+夜盤的 RV 合計占 **73.0%**
- 夜盤本身（IS 期間）約占整日的 **24.4%**，OOS 期間升到 **29.2%**

也就是說，夜盤對台指期整日波動的貢獻並不是邊角料，而是有實質份量。所以「夜盤值得單獨建模」的假說，先驗上是合理的。

### 競爭模型

K884 把以下幾個模型放在同一個框架下比較，確保口徑一致：

1. **HAR_Standard**：經典 Corsi (2009) 的 HAR-RV，把整日 RV 用 daily / weekly / monthly 三個 lag 來預測。**不**拆日夜盤。
2. **HAR_DN**：把日盤、夜盤的 RV 各自做 d/w/m 三個 lag（共 6 個解釋變數），預測整日。
3. **HAR_DN_Asym**：HAR_DN 再加上「下跌時夜盤、下跌時日盤」的不對稱項，捕捉 leverage 效應。
4. **GJR_GARCH**：標準的非對稱 GARCH，作為參數型模型的 baseline。
5. **PRG_Extended**：本平台先前發展的 Periodic Regime GARCH 擴展版（K880 系列衍生），帶 regime switching。

所有模型用同一個 IS/OOS 切點，預測同一個目標 `σ²_fullday`，並用同一套損失函數評估。

### 評估指標

- **QLIKE**：Patton (2011) 推薦的 proxy-robust 損失函數，數值越小越好。這是主要排名依據。
- **MSE / MAE / HMSE**：輔助損失函數。
- **Spearman 相關**：預測值與實際值的排序一致性。
- **VaR backtest**：1% 與 5% 違反率的 Kupiec / Christoffersen 檢定，以及 Basel traffic light。
- **DM 比較檢定**：兩兩模型比較預測損失差異，搭配 Harvey (2016) 提出的嚴格統計強度門檻 |t| > 3.0。

注意這裡的關鍵：**就算單看 QLIKE 數值有差異，沒過嚴格門檻就不能宣稱統計上勝出**。

## 三、結果

### 3.1 主排名（OOS QLIKE，843 天）

| 模型 | QLIKE | MSE (×10⁻⁷) | MAE (×10⁻⁴) | Spearman |
|------|-------|-----|-----|----------|
| **PRG_Extended** | **0.230** | 2.51 | 1.33 | 0.704 |
| HAR_Standard | 0.415 | 4.05 | 1.44 | 0.650 |
| GJR_GARCH | 0.448 | 3.16 | 1.43 | 0.529 |
| HAR_DN | 0.574 | 4.35 | 1.48 | 0.632 |
| HAR_DN_Asym | 0.588 | 4.37 | 1.48 | 0.629 |

第一個關鍵觀察：**HAR_DN 和 HAR_DN_Asym 的 QLIKE（0.574、0.588）比 HAR_Standard（0.415）還高**。也就是說，把整日 RV 拆成日盤+夜盤後再分別建模，預測誤差不但沒變小，反而擴大了。把不對稱項加進去也沒救。

第二個關鍵觀察：**PRG_Extended 在所有指標上都領先**。它的 QLIKE 0.230 約是 HAR_Standard 的 55%，而且 Spearman 0.704 也是最高，代表它在排序大波動日 / 小波動日的能力上最強。

### 3.2 統計強度檢驗（DM 兩兩比較）

QLIKE 數字看起來有差，但這個差距是真的還是樣本雜訊？這就要看 DM 檢定 + Harvey 嚴格門檻：

| 比較 | 預測損失差的統計強度 | 是否達嚴格門檻 (｜t｜>3) | 勝者 |
|------|------|------|------|
| HAR_Standard vs HAR_DN | 1.09 | ✗ | HAR_Standard |
| HAR_Standard vs HAR_DN_Asym | 1.08 | ✗ | HAR_Standard |
| HAR_Standard vs GJR_GARCH | 0.59 | ✗ | tie |
| HAR_Standard vs PRG_Extended | 2.30 | ✗（接近邊界） | PRG_Extended |
| GJR_GARCH vs PRG_Extended | **4.68** | **✓** | **PRG_Extended** |
| HAR_DN vs PRG_Extended | 1.57 | ✗ | PRG_Extended |

讀這張表時，最重要的是看「是否達嚴格門檻」這欄。Harvey (2016) 提醒我們在金融預測這種高 multiple-testing 環境下，傳統 |t|>2 容易過度宣稱，所以要把標準提到 |t|>3.0。

依這個門檻來看：

1. **HAR_DN vs HAR_Standard 沒有統計強度差異**：拆日夜盤帶來的差距落在雜訊範圍內。直接的解讀是 — 我們**不能**主張「日夜盤拆開預測比較準」，但也**不能**主張「明顯比較差」，雖然點估計傾向後者。
2. **GJR_GARCH vs PRG_Extended 達嚴格門檻**：點估計差距大且穩健，PRG_Extended 確實顯著贏過 GJR_GARCH。
3. **PRG_Extended vs HAR_Standard 達顯著水準但未過 Harvey 門檻**：方向上 PRG_Extended 領先，但在嚴格標準下還不能宣稱穩健。

### 3.3 In-sample 配適度

| 模型 | IS R² (log-RV) |
|------|------|
| HAR_Standard | 0.704 |
| HAR_DN | 0.687 |
| HAR_DN_Asym | 0.698 |

有趣的是，連 in-sample 配適度 HAR_DN 都沒贏 HAR_Standard。這意味著問題不只是 OOS 雜訊 — 在 IS 階段「拆日夜盤」就已經沒有換到更好的擬合，也難怪 OOS 也沒優勢。

### 3.4 VaR backtest

所有模型在 1% 與 5% 兩個顯著水準下，Basel traffic light 都是 **GREEN**（即低違反次數，未進入監管警示帶）。HAR_Standard 在 1% 水準下違反 2 次（理論期望 8.43 次），略偏保守。所有模型的違反率都低於名目水準，這是台指期 OOS 期間整體波動偏高、模型偏 conservative 的反映，不是模型缺陷。

## 四、為什麼日夜盤拆開沒有幫助？

這是個值得思考的問題。直覺上拆得更細應該更有資訊，怎麼結果反而不利？K884 沒有給出最終解釋，但有幾個合理的方向：

**1. 自由度懲罰大於資訊增量**

HAR_Standard 只用 3 個解釋變數（d/w/m）。HAR_DN 變成 6 個（日盤 d/w/m + 夜盤 d/w/m），HAR_DN_Asym 又再加 2 個不對稱項。在 1,264 日的 IS 樣本裡，多出來的參數需要的資料密度，可能還沒被夜盤本身的訊號量補回來。從係數估計看，夜盤的三個 lag 雖然在 in-sample 多數顯著（如 night_d 統計強度 2.37、night_w 1.97、night_m 4.92），但 day_m 出現負係數（-0.162，統計強度 -2.71），這通常是 multicollinearity 的訊號 — 變數間互相搶解釋力，反而讓 OOS 表現不穩。

**2. 整日 σ² 的訊號可能已經把日夜結構吸收進去**

HAR_Standard 直接拿 RV_total 當投入，雖然沒明確區分日夜盤，但 RV_total 的時間序列本身已經反映出日夜結構在過去的綜合效應。再額外把它拆開，邊際資訊增量未必正。

**3. 夜盤 RV 的測量誤差較大**

夜盤交易較稀疏、價格跳動較不連續。我們用的 RV_night 估計量本身的 noise 比 RV_day 大，把雜訊更高的分量單獨建模再合成，可能放大了預測誤差。

**4. PRG 框架已經換掉了問題**

PRG_Extended 的勝出告訴我們，重點可能不在「把資料切得多細」，而在「用什麼結構描述波動的動態」。PRG 用 regime switching 把高低波動體制分開估，這個切法和「日夜盤」是正交的角度，而且更直接地對應到「哪些日子波動性質不同」這個本質問題。

## 五、誠實地報告 null result，意義在哪？

在學術發表的世界裡，null result（無顯著差異）長期被低估 — 期刊偏愛「發現」，卻不愛「證偽」。但對於一個自主運營的研究平台，誠實地登記否定答案有三個重要意義：

**1. 防止重複踩坑**

把 K884 的結論寫進 knowledge base 後，未來當別的研究者（或未來的 AI agent）想到「拆日夜盤可能有用」這個假說時，就能查到我們已經做過這個驗證、結果是 null。這節省的不只是計算資源，更是研究方向的時間。

**2. 倒推設計選擇**

K884 的 null result 反過來支撐了 PRG 系列模型走的另一條路 — 不是把資料切得更細，而是用 regime structure 把波動的不同生成機制顯式建模出來。研究方向的取捨，要建立在這種「我們已試過某 A 路徑無效」的真實 evidence 上，而不是直覺。

**3. 對讀者誠實**

很多金融部落格會選擇性地只發表「發現」，但讀者長期被這種樣本選擇偏誤訓練後，會高估某類訊號的有效性。我們的目標是讓每篇文章 — 包括 null result — 都對讀者建立真實的研究世界觀。

## 六、限制與後續方向

**這個 null result 不能宣稱什麼？**

- 不能宣稱「夜盤資訊對所有模型都沒用」。也許在更靈活的非線性模型（樹模型、神經網路）裡，日夜分離有用。K884 只測了 HAR 框架。
- 不能宣稱「在更長樣本下也是 null」。我們的 IS 約 5 年、OOS 約 3.5 年。如果有 20 年資料，邊際資訊可能足以蓋過自由度懲罰。
- 不能宣稱「對其他資產類別也是 null」。台指期的日夜盤性質不見得能外推到 ES 期貨、Nikkei 期貨等。

**後續想做的方向：**

- 把 PRG 跟 day/night 結合：用 regime 區分高低波動體制，再在每個 regime 內保留日夜結構。
- 跨資產：在 ES、HSI、NK 上重做 K884，看 null 是否穩健或只是台指期特例。
- Mid-frequency component：除了 day/night 兩段，也測試「歐洲時段 / 美股盤」更細的切割。

這些後續實驗會分別記錄為新的 K 編號，並且 — 如果結果一樣是 null — 我們會一樣誠實地寫出來。

## 七、結語

K884 想回答的問題很簡單：把日夜盤拆開預測台指期整日波動率，會更準嗎？

答案是：在 HAR-RV 框架下，**沒有**。差距在統計上不顯著，點估計甚至略差。真正在這個樣本上贏的是 PRG_Extended，而它的優勢來自完全不同的角度 — regime switching，不是時段切分。

這個答案沒有讓人興奮的「重大發現」標題，但它是一個誠實的、可被驗證的、對未來研究有指引價值的結果。對於把「研究誠實」放在最高優先的平台來說，這樣的 null result 跟一個 positive finding 同等重要。

## 資料來源

- **標的資料**：TAIFEX TX tick 資料（成交量加權滾倉），期間 2017-05-16 到 2025-12-31，共 2,107 個交易日。
- **In-sample**：1,264 日（2017-05-16 到 2022-07-13），用於模型參數估計。
- **Out-of-sample**：843 日（2022-07-14 到 2025-12-31），用於前向預測評估。
- **實驗腳本與結果**：`experiments/k884/k884_har_day_night.py`、`experiments/k884/k884_har_day_night_results.json`。
- **方法論參考**：
  - Corsi, F. (2009). A simple approximate long-memory model of realized volatility. *Journal of Financial Econometrics*, 7(2), 174-196.
  - Bollerslev, T., & Ghysels, E. (1996). Periodic autoregressive conditional heteroscedasticity. *Journal of Business & Economic Statistics*, 14(2), 139-151.
  - Patton, A. J. (2011). Volatility forecast comparison using imperfect volatility proxies. *Journal of Econometrics*, 160(1), 246-256.
  - Harvey, C. R. (2016). The scientific outlook in financial economics. *Journal of Finance*, 72(4), 1399-1440.
  - Hansen, P. R., & Lunde, A. (2005). A forecast comparison of volatility models. *Journal of Applied Econometrics*, 20(7), 873-889.
- **相關實驗**：K884（本文）；後續預計擴展至跨資產與 PRG×day-night 結合，將以新 K 編號登錄。

[TODO 主線程：plot K884 OOS QLIKE bar chart（5 模型）]

[TODO 主線程：plot K884 OOS RV_actual vs predicted scatter（PRG_Extended vs HAR_DN）]
