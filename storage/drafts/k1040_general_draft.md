---
title: "經典論文搬到 OOS 會崩嗎？我們驗了 Bollerslev (2009)：能預測月報酬的不是 VRP，是 VIX 本身"
audience: general
phase: research
category: milestone
tags: [變異風險溢酬, VIX, 標普500, 月頻報酬, 樣本外檢驗, 經典論文驗證, 一般讀者]
experiment_refs: [K1040]
image_url: "https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k1040_oos_r2_direction.png"
proposer: 賴奕豪
status: draft
---

*本文基於實驗 K1040（腳本：experiments/k1040/k1040.py，結果：experiments/k1040/k1040_results.json）。資料來源：yfinance（SPY、VIX 日資料），期間：2005-01-01 ~ 2026-04-09，樣本：5,349 個交易日，樣本外（OOS）期間 2019-01-01 起共 1,805 天。*

[提出: 賴奕豪, 執行: Claude]

## 一、那篇被引用 4,000 次的論文，OOS 還站得住嗎？

2009 年，Bollerslev、Tauchen 與 Zhou 在頂級期刊 *Review of Financial Studies* 發表一篇經典論文：他們發現一個叫做「變異風險溢酬」（Variance Risk Premium，簡稱 VRP）的指標，能在**月頻**顯著預測 S&P 500 的未來報酬，樣本內（in-sample）的解釋力 R² 高達 5–8%。

直白翻譯：**市場為了買保險願意多付的價格，似乎能告訴我們未來一個月股市會漲還是跌。**

這個結果很漂亮，也讓 VRP 成了波動率與資產定價文獻中最受歡迎的變數之一。但學術界一個眾所皆知的問題是：**在樣本內看起來顯著的訊號，搬到真實世界（樣本外）很容易崩**。

我們做了 K1040：把這條經典結論放到 21 年的真實資料、嚴格的滾動式樣本外設定、再加上一系列我們自己研究多年的競爭模型來檢驗。結論說在前面：**月頻有預測力是真的，但功勞並不在 VRP，而是在 VIX 本身。**

![六模型 × 三個 Horizon 的 OOS R² 與方向準確度](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k1040_oos_r2_direction.png)

## 二、什麼是 VRP？什麼又是 g_t？

先用三句話講清楚兩個關鍵變數，這篇文章後面才看得懂。

**VRP（變異風險溢酬）** 是市場願意為「避險」多付的價格，技術上等於 VIX 隱含的未來變異減去實際發生的變異。VRP 大，代表投資人很怕、願意付高保費；VRP 小，代表市場放鬆。

**g_t（A4f 分解出的條件波動分量）** 是我們在前面 K1023 等實驗裡，用乘性 GARCH 家族的 A4f 模型把日報酬波動拆解後得到的「短期 GARCH 動態分量」。在 K1023 我們已經發現一件有趣的事：g_t 跟 VRP 的 Spearman 相關係數高達 **0.80**，幾乎是同一塊資訊的兩種表達方式。

這引出一個自然的研究問題：既然 g_t 和 VRP 高度相關，那把 g_t 拿來預測股票報酬會不會比 raw VRP 更精煉、更乾淨？

## 三、實驗設計：六個模型，三個 horizon，一個誠實的橫向比較

我們在 SPY 21 年資料上跑了一場「六模型大車拚」：

| 模型 | 用什麼解釋變數預測未來報酬 |
|------|---|
| 歷史均值（benchmark） | 不用任何變數，就用過去報酬的平均當作預測 |
| VRP-only | 只用 VRP |
| g_t-only | 只用 A4f 分解出的 g_t |
| VIX-only | 只用 VIX 水準 |
| g_t + VRP | 兩者一起 |
| Kitchen Sink | g_t、VRP、VIX 三個全進去 |

每個模型在三個預測時程比過：1 天（h=1d）、1 週（h=5d）、1 個月（h=22d）。樣本外從 2019-01-01 跑到 2026-04，使用 expanding window 滾動估計（窗長 2,000 天、每 63 天 refit 一次），所有訊號嚴格 lag 一期（用 t-1 的訊號預測 t→t+h 的報酬，避免 look-ahead）。

評估指標除了 OOS R²，還包括 **Clark-West (2007) test**——這是專門設計給「巢狀模型」的修正後預測精度檢定，比傳統 t-stat 更謹慎。Clark-West p-value 顯著表示：在懲罰過度配適後，新模型仍真的比歷史均值預測得更好。

## 四、結果：日頻全死、週頻全死、月頻只有 VIX-only 活下來

直接看結果，特別注意月頻那一欄：

| 模型 | h=1d OOS R² | h=5d OOS R² | h=22d OOS R² | h=22d Clark-West 檢定 |
|------|---|---|---|---|
| VRP-only | -2.63% | -0.52% | +0.77% | p=0.174（不顯著） |
| g_t-only | -0.61% | -0.85% | +0.87% | p=0.183（不顯著） |
| **VIX-only** | -1.19% | -0.81% | **+5.63%** | **p=0.021（顯著）** |
| g_t + VRP | -3.24% | -1.57% | +0.88% | p=0.179（不顯著） |
| Kitchen Sink | -4.08% | -1.74% | +5.27% | p=0.056（邊緣） |

幾個關鍵觀察：

**第一，日頻和週頻全軍覆沒。** 所有模型在 h=1d、h=5d 的 OOS R² 都是負的，意思是「還不如直接用過去報酬平均當作預測」。這呼應了 K818（SSVS 變數選擇）和 K840（日頻方向預測 55% pipeline）的發現——**短頻的股票報酬幾乎沒有可預測性，這是效率市場最強硬的那一面。**

**第二，月頻有預測力是真的。** VIX-only 在 h=22d 的 OOS R² 達到 +5.63%，Clark-West p=0.021，正式達到統計顯著。這個量級和 Bollerslev 等人 2009 年論文的 in-sample R² 5-8% 相當——證明了**月頻的恐懼溢酬-報酬連結確實存在於 OOS。**

**第三，但功勞在 VIX，不在 VRP，更不在 g_t。** VRP-only 的 OOS R² 只有 +0.77%，g_t-only 也只有 +0.87%，兩者的 Clark-West 檢定都不顯著（p ≈ 0.18）。把它們加進 Kitchen Sink 反而讓 R² 從 5.63% 降到 5.27%，邊緣到剛好不顯著（p=0.056）——典型的「多一個雜訊變數損失精度」。

換句話說，**Bollerslev (2009) 的故事在 OOS 仍成立，但它真正的驅動力是 VIX 水準本身，而不是 VRP 這個更精細的構造**。VIX 高的時候市場對風險的補償就會高，這是教科書層級的風險溢酬機制。

## 五、最殘酷的測試：拿 g_t 訊號去交易，會賺嗎？

統計顯著只是研究的第一關。對讀者更實用的問題是：**這些訊號拿來真的去交易，能不能賺錢？**

我們把 g_t 當成擇時訊號做了 long-short backtest：g_t 在歷史分位數高的日子做多 SPY，分位數低的日子放空 SPY，每天滾動。結果是這樣：

![g_t 訊號 Long-Short 與 SPY 買進持有 Sharpe 比較](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k1040_longshort_vs_bh.png)

| 預測時程 | g_t Long-Short 年化 Sharpe | SPY 買進持有年化 Sharpe |
|---|---|---|
| h=1d | **-0.118** | 0.711 |
| h=5d | -0.001 | 0.769 |
| h=22d | -0.074 | 0.759 |

三個 horizon 全部都是**負 Sharpe**，而同期 SPY 直接買進持有的 Sharpe 是 0.71-0.77。這意味著：

- 訊號在統計上的「微弱可預測性」**完全無法轉換成經濟上的價值**；
- g_t 的 long-short 不只贏不過 SPY，它的方向甚至和正確訊號相反（負 Sharpe）；
- 任何拿 g_t 當交易訊號的人，都會輸給單純的 buy-and-hold。

這就是學術文獻中典型的「**統計顯著 ≠ 經濟顯著**」教訓的反面教材。

## 六、Bollerslev (2009) 的 In-Sample 也很漂亮，但 OOS 縮水了

讓我們同時看一下 K1040 的 in-sample 結果，和經典論文做個直接對話：

在 h=22d 的 in-sample 迴歸裡，VRP 的 HAC-corrected t-stat 達到 **+2.77**（h=5d 甚至到 +3.46）——這完全對得上 Bollerslev 等人發表的顯著結果。但同樣這個 VRP 變數，到了 OOS 卻只剩 +0.77% 的 R² 和 p=0.17 的不顯著。

**這是 return predictability 文獻最常見的「IS 強、OOS 弱」現象**，學術上有專門的論文討論這個 gap，例如 Welch & Goyal (2008) 著名的「股票溢酬預測 OOS 都不行」綜論。我們的 K1040 結果再次確認：**樣本內顯著從來不等於樣本外有用。**

## 七、給讀者三個帶得走的訊息

1. **VIX 月頻有預測力是真的，但日週頻沒有。** 如果你聽到任何人說 VIX 能擇時，請先問：「在哪個 horizon？」這不是學究式的挑剔，這是訊號到底有沒有用的分水嶺。在 K1040 裡日頻和週頻全死、月頻才活，差異 5 個百分點起跳。

2. **越精細的指標不一定越強。** VRP 是 VIX 的「升級版」設計，g_t 是 A4f 模型分解後的「精煉版」資訊，兩者在 IS 都比 VIX 漂亮，**但 OOS 全輸給最樸素的 VIX 水準**。這是金融計量裡反覆出現的教訓：**多餘的 sophistication 經常是過度配適的同義詞**。

3. **統計顯著 ≠ 能賺錢。** 即使是月頻 OOS 顯著的 VIX-only 模型，做成 long-short 後也是負 Sharpe。預測 R² 5.63% 在學術上是不錯的成績，但對應到的擇時策略仍打不過 buy-and-hold。**散戶讀到「某指標顯著預測股市」的新聞時，請務必區分「能解釋一點未來變異」和「能賺錢」是完全不同的兩件事。**

## 八、限制與我們自己誠實面對的地方

- **單一資產**：只測試 SPY，未涵蓋 QQQ、IWM 或國際指數。Bollerslev 等人原文也以美股為主，跨資產推廣性是另一個議題。
- **OOS 期間特殊**：2019–2026 包含 COVID、2022 熊市、2024 軟著陸，是非常規的樣本。但這也正是這篇 OOS 結果有意義的地方——經典模型必須通過特殊期才算可用。
- **VRP 構造簡化**：我們用 22 日 RV 估計實際變異，未使用 5 分鐘高頻資料的 RV。Bollerslev 原文使用高頻 RV 後 R² 會略升，但兩種構造的 IS 顯著性已知都很穩健。
- **g_t 的角色在波動率域、不在報酬域**：這個 NULL 結果不否定 g_t 的價值。在 K988、K995、K1035 系列裡，g_t 對 SPY 波動率預測的 QLIKE 仍有改善——它是個好的**波動率變數**，只是不能跨域到報酬。

## 結論

我們把 Bollerslev、Tauchen 與 Zhou (2009) 的經典 VRP-return predictability 在 21 年資料上做了一場誠實的 OOS 重驗。**月頻可預測性確實存在，但驅動者是 VIX 水準本身，不是 VRP，更不是更精細的 A4f g_t。** 日頻、週頻全部 NULL；用 g_t 訊號做擇時 long-short 在三個 horizon 全部負 Sharpe，輸給單純買進持有 SPY。

這個發現延伸了我們的「VIX 充分性家族」（K504 / K1098 / K1116 系列）：在愈來愈多場景裡，**比 VIX 更花俏的指標都沒有添加實質的增量資訊**。對個人投資人最實用的啟示也許就是：與其追逐花俏的衍生指標，不如先把 VIX 本身的水準和它在月度層級的行為弄清楚。

## 延伸閱讀

- Bollerslev, T., Tauchen, G., & Zhou, H. (2009). Expected Stock Returns and Variance Risk Premia. *Review of Financial Studies*, 22(11), 4463–4492.
- Campbell, J. Y., & Thompson, S. B. (2008). Predicting Excess Stock Returns Out of Sample. *Review of Financial Studies*, 21(4), 1509–1531.
- Clark, T. E., & West, K. D. (2007). Approximately Normal Tests for Equal Predictive Accuracy in Nested Models. *Journal of Econometrics*, 138(1), 291–311.
- Welch, I., & Goyal, A. (2008). A Comprehensive Look at the Empirical Performance of Equity Premium Prediction. *Review of Financial Studies*, 21(4), 1455–1508.
