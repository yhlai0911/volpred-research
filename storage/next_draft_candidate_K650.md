# 1399 筆研究紀錄盤點：被引用 260 次以上的 16 個結論

我們從 1399 筆知識庫條目、271 個獨立 K-experiments 裡，挑出**被引用 ≥3 次**的少數結論——這 16 個就是這個研究系統目前能稱得上 established facts 的全部。

這篇換一個角度：把整套研究的**內部引用熱度**當成可信度指標。一個結論被後續實驗反覆呼叫、反覆當作 baseline 條件、反覆寫進 robustness check——它才算站穩。「哪個策略賺最多」這種 single-number takeaway 留給之前的 K200 文，不重複。

## 為什麼用「引用次數」當篩選器

平台先前已經寫過兩篇 meta：K200 著重「投資最該做的一件事」單一 takeaway；K644 是 24 個近期實驗的橫向 synthesis。K650 換一個角度——把 knowledge.json 全庫掃過，看每一條結論被多少後續 entry 引用。引用次數高 = 在這套研究的內部邏輯裡，這條被當基礎事實使用，不只是某個 K 的 isolated finding。

這個方法的弱點要先講：引用次數會被「熱門研究主題」放大。VIX 相關被引 260 次，部分是因為我們本來就跑很多 VIX 研究。所以下面的數字看「相對排序」比看「絕對次數」更有意義。

## Top 6 established facts

![被引用最多的 6 個結論](https://placeholder-will-be-replaced/k650_established_facts_topN.png)

| 排名 | 結論 | 引用次數 | 一句話說明 |
|---|---|---|---|
| 1 | VIX 作為波動率區間判讀指標 | 260 | VIX 水準是判斷接下來高/低波動環境最穩定的單一變數 |
| 2 | HAR 多時間尺度成分 | 132 | 日/週/月三個 RV 分量組合的預測力極難被取代 |
| 3 | 槓桿效應（下跌時波動放大） | 131 | 負報酬對下一期波動的影響顯著大於同幅度正報酬 |
| 4 | VIX sufficiency | 91 | 美股波動率目標策略上，VIX 一個變數已涵蓋大部分可操作訊息 |
| 5 | 12/VIX 倉位調整法 | 87 | 簡單的 inverse-VIX scaling 在 Sharpe 與 MDD 都打贏複雜模型 |
| 6 | QLIKE ceiling | 62 | 各家波動率模型在 QLIKE 上的最佳值有一個難以突破的上限 |

剩下 10 條（50/50 SPY+GLD 61 次、Cross-OOS validation 60 次、GJR > GARCH 36 次、Contango/Backwardation 33 次、交易成本 22 次、台灣放大效應 13 次、Prediction≠Application 5 次、Multi-start 4 次、VT 在股票上有效 4 次、Sentiment 是弱預測因子 3 次）構成 long tail。引用次數從 260 直接掉到個位數，反映這個研究系統的內部 consensus 是 highly skewed——少數核心事實重複出現，多數結論只在特定情境下使用一次。

## 101 對 10 的 VIX sufficiency 比例

整理過程中跑了一個獨立 audit：到底有多少筆 entry 在說「VIX 一個變數就夠了」、又有多少筆反過來舉出反例？

結果是 **101 筆 confirmation、10 筆 exception**。

10 個 exception 的共同性質：3 個出現在加密貨幣（BTC 的 VIX-spillover 訊號有限）、2 個在台股（夜盤資訊讓 VIX 失靈）、2 個在貴金屬（GLD 的 macro driver 與股票 VIX 脫鉤）、其餘 3 個在極端高 VIX 區間（VIX>40 時訊號飽和反向）。

實務上的意義：**做美股日頻波動率目標**就用 VIX，不用堆 MOVE、STLFSI4、sentiment、macro index 那一堆候選變數——我們已經把這些都跑過了，加進去沒有顯著增量。但**跨資產、跨時區、極端區間**這三條 boundary 要記住，越過就要換工具。

## Prediction ≠ Application：6 次被獨立確認

K650 在彙整時抓出一個跨多個 K 的 pattern，被獨立確認 6 次（K533, K540, K594, K635, K957, plus 一筆早期 hash entry）：

**有些東西能預測，但不能用來操作；有些能操作的東西，其實不必精準預測。**

具體例子：
- **K533**：HAR multi-scale 在 QLIKE 上壓倒 GJR-GARCH（DM=-15.45），但拿同一份預測去跑 VT 策略，HAR 的 Sharpe 反而最差，12/VIX 那個土法煉鋼的 inverse scaling 才勝出。預測準度排序和策略績效排序**完全顛倒**。
- **K548/K551**：VIX-Conditional Leverage 策略不依賴任何「預測波動率」這件事——它只看 VIX 當下水準分區，在低區開槓桿、高區降曝險。沒有預測模型，Sharpe +0.112，Cross-OOS 5/5 全過，Harvey t=7.90。

這條 principle 對研究設計的影響很直接：當 QLIKE 改善不能 translate 成 Sharpe 改善，再優化模型 QLIKE 已經沒有報酬。研究資源該投到**直接 optimize 策略 utility**，而不是繞一圈先 optimize 預測再 hope it transfers。這也是為什麼 16 條 established facts 裡，與「預測準度」相關的只有 HAR 與 QLIKE ceiling 兩條，其餘 14 條都是策略結構、資產配置、條件邏輯——研究路徑早就被資料推離了「預測派」。

## 從 19% null rate 看研究系統的 self-correction

最後一個值得看的數字：1399 筆 entry 中 165 筆明確標 null result，約佔被標籤條目的 **19%**。87 筆是「推翻先前結論」的更正記錄。

這兩個比例的健康程度比想像中重要。如果 null rate 趨近於零，代表研究系統在自我蒙蔽（只發表 PASS、把 FAIL 掃進地毯下）；如果 overturn rate 是零，代表系統失去複查能力。19% null + 6% overturn 不是「研究做不好」的訊號，是「研究做得夠誠實」的 baseline——平台在 Cross-OOS 這條規則導入後，多次抓出單期 OOS PASS、跨期失敗的 false positive，這 60 次 Cross-OOS confirmation 就是這個 self-correction 機制留下的痕跡。

## 接下來會發生什麼

K650 之後三個方向是清楚的：

1. **Long-tail 結論升級或退役**：引用次數 ≤5 的 9 條 established facts 要在未來實驗中要嘛被 cite 鞏固、要嘛被新證據降級。Sentiment（3 次）特別脆弱。
2. **VIX sufficiency 邊界研究**：10 個 exception 各自值得獨立 K——台股夜盤、BTC、GLD、極端 VIX，是接下來把「邊界」變成「替代方案」的入口。
3. **Prediction-Application 通則化**：6 次確認還不夠強，目標是再累積到 15+ 並寫成 standalone methodology paper——研究界對這條 gap 認知不深，是 publishable contribution。

---

**資料來源**：本文所有引用次數與比例來自 `experiments/k650/k650_results.json`，掃描範圍為 `storage/memory/knowledge.json` 截至 2026-03-29 共 1399 筆 entry、271 個 unique K-experiments。VIX-sufficiency exception list 共 10 筆，prediction-application 確認案例 6 筆，皆可在 results JSON 內按 ID 反查。
