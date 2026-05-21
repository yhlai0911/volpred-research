---
title: "盤點 270 場實驗：哪些發現真正是新的？"
audience: general
status: draft
tags: [研究地圖, 波動率目標, VIX, 知識盤點, 黃金, VT, 元分析]
experiment_refs: [K274]
---

# 盤點 270 場實驗：哪些發現真正是新的？

## 為什麼要做這場「研究自我盤點」

研究團隊累積到一定規模時，最容易出現的問題不是「沒有發現」，而是「不知道哪些發現是真的新的」。一個自主運營的研究系統如果不定期回頭整理，就會掉進「不斷重新發現別人已知結論」的陷阱。本實驗 K274 的目的，正是把累積到 2026 年 3 月 24 日為止的 **978 條知識記錄、橫跨 270 個實驗** 系統性地對照學術文獻，挑出 **Top 20 最重要的發現**，逐一判斷它是「全新貢獻」、「延伸既有文獻」、「再次確認已知結果」，還是「推翻既有理論」。這種 self-audit 在學術界稱為 contribution mapping，它能避免後續論文寫作時把 confirmation 當 novel claim 來叫賣，也能讓投稿時的差異化論述有真材實料的支撐。

## 結果一句話：四五成新發現、四五成延伸、一成確認、零推翻

K274 的結論清楚而保守：在 Top 20 個最具代表性的發現中，**9 個（45%）屬於 NOVEL（無直接前例）、9 個（45%）屬於 EXTENSION（延伸既有文獻）、2 個（10%）屬於 CONFIRMATION（再確認已知結論）、0 個 CONTRADICTION（推翻舊理論）**。零個 contradiction 是個誠實但不亮眼的數字，但這也代表本研究計劃並非靠戲劇性翻案撐場面，而是靠多個獨立 novel finding 與大量 incremental extension 累積出版面。

| 類別 | 數量 | 比例 | 含義 |
| --- | --- | --- | --- |
| NOVEL（全新貢獻） | 9 | 45% | 文獻中無直接前例，可作論文核心 contribution |
| EXTENSION（延伸） | 9 | 45% | 在既有文獻基礎上補資產、補頻率、補方法 |
| CONFIRMATION（確認） | 2 | 10% | 用新資料重做已知結論，僅作 supporting evidence |
| CONTRADICTION（推翻） | 0 | 0% | 沒有實驗結果直接推翻過去主要文獻 |

## 五個最受看好的「真新發現」

K274 從 9 個 novel findings 中再點出 5 個最有力的核心貢獻，這些將成為論文集投稿時的差異化主張。

**第一，槓桿方向分類學（Leverage Direction Taxonomy）**：傳統 Black（1976）、Christie（1982）的槓桿效應只談股票，但本研究用 GJR-GARCH 在 26 個跨資產（股、債、商品、貨幣）上發現槓桿方向不是定論——股票呈標準槓桿（gamma 為正）、黃金呈倒置槓桿（gamma 為負，恐慌買盤推高波動）、債券近乎對稱。更精彩的是黃金的 gamma 還會隨牛熊反轉：牛市 gamma=−0.043（t=−4.7, p<0.0001）為倒置，熊市 gamma=+0.048 變回標準。這是文獻上沒有人正式提出過的 stylized fact。

**第二，Gamma 預測 VT 是不是隱性趨勢策略**：Hood & Raughtigan（2025 JPM）發現波動率目標策略（VT）的 alpha 大半被 TSMOM（時間序列動量）吸收，但他們沒回答「為什麼有些 VT 會變趨勢，有些不會？」本研究在 22 檔資產上算出 GJR gamma 與 TSMOM 載荷的相關係數 r=0.564（p=0.006），明確指出 gamma 越大、VT 越像隱性趨勢；股票次樣本（N=6）的 Spearman rho 更高達 0.886（p=0.019）。

**第三，VT 的 MDD 保護獨立於趨勢**：把 TSMOM 暴露對沖掉之後，VT 仍保留 90–97% 的最大回撤保護（SPY 93%、50/50 SPY/GLD 96%、DIA 91%、QQQ 90%、IWM 97%），但 Sharpe 改善只貢獻約 1.4%。換句話說，VT 的真正價值是「回撤保險」，不是「賺超額報酬」。這個雙通道分解（Sharpe vs MDD）在文獻上是新的。

**第四，VIX 是 VT 配置的充分統計量**：本研究累積 21 個獨立 null result，從 GARCH 預測值、市場情緒（AAII、SKEW）、信用利差、殖利率曲線、VVIX、宏觀因子、DCC 動態相關、流動性指標到 MOVE-VECM，逐一檢測「在 VIX 之外，這些訊號是否還能改善月度 VT 配置」。答案幾乎一致：在控制 VIX 之後，所有額外訊號的 partial R² 都低於 0.03。Bozovic（2024 IRFA）證明 VIX-managed 比 realized-vol-managed 好，但沒人系統性測試過「VIX 是否 dominate 全部 21 種替代訊號」。

**第五，VIX 為 carry trade 計時也成立**：在 AUD/JPY carry trade 上加 12/VIX 倉位調整，最大回撤從 −40% 縮到 −14%（bootstrap p=0.001），Sharpe 從 0.146 升到 0.426（p=0.001），且 5 個子期間穩定。重要的是，用「自身波動率（own-vol）」做 EWMA targeting 反而失敗（Sharpe 只有 0.085）——因為 carry crash 是全球風險偏好（VIX）驅動，不是貨幣對自身波動驅動。這個機制差異在文獻沒人直接測過。

## 三本論文的版面分配

K274 同時把這 20 個發現對照到目前正在審改的三本論文，並評估每本的 novel 含量：

| 論文 | 目標期刊 | NOVEL 比例 | 核心貢獻 | publication_readiness |
| --- | --- | --- | --- | --- |
| Paper 1（JBF） | Journal of Banking & Finance | 70% | 槓桿方向分類學、gamma 模型選擇、複雜度天花板 | 0.75 |
| Paper 2（PBFJ） | Pacific-Basin Finance Journal | 30% | 台股 4.6× 槓桿放大、TZ 資訊傳遞、台股 VT 實作 | 0.70 |
| Paper 3（VT vs Trend） | JFE / JFQA / JBF（待定） | 60% | gamma–TSMOM 機制、MDD 雙通道分解、13 國 VIX | 0.65 |

Paper 1 是 novel 含量最高的旗艦稿，但 Codex 在前一輪審查只給 32/100，主要批評是「以 7 檔資產的證據撐 too broad 的 claim」。K274 的策略建議是收斂到 2 個 contribution（槓桿分類 + gamma 模型選擇），把複雜度天花板（complexity ceiling）降為 supporting evidence。Paper 2 雖然 novel 比例只有 30%，但「台股 VT + 跨時區資訊傳遞 + 槓桿放大」的組合在區域期刊有獨特賣點。Paper 3 直接回應 Hood & Raughtigan（2025 JPM）這篇剛出爐的高曝光度文章，時效性最強，但需要先用期貨資料補做精確對照。

## 第四篇論文：4 個機會中只有「保險論文」站得住

K274 也評估了「Paper 4」這一個尚未動筆的潛在標的，列出 4 個候選方向並打分：

| 候選 | 主題 | viability | 結論 |
| --- | --- | --- | --- |
| 4A | GLD 自我修復 + 等權重穩健性 | 0.45 | 不獨立可行，併入 Paper 1/3 或寫實務 note |
| 4B | QLIKE 天花板：日頻波動預測的不可能定理 | 0.60 | 需補形式化理論界限才有戲 |
| 4C | VT 即回撤保險：定價、機制、生命週期 | 0.70 | 最可行，可投 JFQA / JPM / FAJ |
| 4D | 為什麼 50/50 不可被打敗 | 0.50 | 邊緣可行，較適合實務派期刊 |

4C「保險論文」的核心是把 VT 重新定位為一份保單：年化代價約 4% 的 Sharpe drag，換來的是在所有測試 horizon（1 年到 32 年）都成立的 100% MDD 保護。它整合了 K41（保險定價）、K32（VT 沒通過古典擇時檢定）、K28（行為偏誤模擬）、K39/K40（生命週期悖論）。要走這條路還需要補上正式的精算定價框架、跟期權 / VIX 期貨等明確避險工具的成本對照，以及帶損失趨避（loss aversion）的效用分析。

## 兩個保守的 confirmation 也值得寫進論文

不是所有 confirmation 都該丟進垃圾桶。K274 的 2 個 confirmation 各有用處：第一，**月度 12/VIX 再平衡（Sharpe 0.792）優於每日（0.679）**——這跟 Fleming et al. (2003) 與 Harvey et al. (2018) 的 rebalancing frequency 文獻一致，但配上「VIX 慢訊號要月度、GARCH 快訊號要日頻」的對比，能作為實作章節的核心建議。第二，**4 種 ML/DL 方法（LSTM、GRU、XGBoost、GARCH-LSTM hybrid）在日頻波動預測都打不贏 GARCH**——這跟 Hansen & Lunde（2005）的結論一致，但本研究補上了現代架構（GRU、XGBoost）以及一個理論解釋：日頻 GARCH 殘差近乎 iid，深度學習沒有可學的結構。

## 防錯與限制：這份盤點本身怎麼證偽？

研究誠實原則要求作者主動列出自己的限制。本實驗的潛在問題有四：第一，**Top 20 是研究者自選**，不是隨機抽樣，可能高估 novel 比例；後續可用一個外部 reviewer 對 978 條 knowledge 做盲分類來校驗。第二，**novelty 判定依賴文獻搜尋的覆蓋度**——若搜得不夠廣，「無直接前例」可能是「沒搜到」而非「真不存在」。本研究已對 8 篇 anchor paper（Hansen-Lunde 2005、Hood-Raughtigan 2025、Moreira-Muir 2017、DeMiguel 2009、Rapach 2013、Cederburg 2020、Black-Christie 1976/1982、Bozovic 2024）做了 explicit comparison，但 reviewer 在 R1 階段一定還會丟出更多沒查到的前例。第三，**樣本資產與期間集中於美股 ETF（2004 起）+ 部分國際 ETF + 台股**，跨期間穩健性還需要補充更早的期貨資料。第四，**所有策略結論都遵守 lookahead audit**：訊號使用 t-1 資訊產生 t 期決策，bootstrap、MC、抽樣與 train-test split 都使用固定 seed，避免前視偏誤；任何後續延伸實驗也應守同一條線。

## 對讀者的三個 takeaway

第一，VT 不是擇時也不是趨勢，**VT 是一份回撤保單**——它收 4% 左右的 Sharpe drag、給你不論 horizon 都有效的最大回撤保護。第二，**VIX 在月度 VT 上是個好得驚人的「萬用訊號」**：21 個替代信號加進去都沒贏，連跨 13 個國際市場都成立。第三，**模型複雜度有天花板**：14 個波動模型在 3 檔資產上的 QLIKE 差距只有 0.31%，4 個 ML/DL 嘗試打 GARCH 都失敗——這對個人投資者是好消息，因為一條 EWMA(0.97) 的 Excel 公式就能達到 GJR-GARCH 的 Sharpe 水準（DM 檢定 p=0.943，完全無法分辨）。

## 資料來源

- 研究實驗：K274（Paper Contribution Mapping），執行於 2026-03-24
- 來源庫：knowledge.json 978 條記錄、experiments 270 個 K
- 涵蓋資產：26 檔（包含美股 ETF、國際 ETF、黃金、台股 0050.TW / TAIEX、AUD/JPY 等）
- 對照文獻：Hansen & Lunde (2005)、Hood & Raughtigan (2025 JPM)、Moreira & Muir (2017 JF)、DeMiguel et al. (2009 RFS)、Rapach et al. (2013 JF)、Cederburg et al. (2020)、Black (1976) / Christie (1982)、Bozovic (2024 IRFA) 等 8 篇 anchor paper
- 詳細結果：見 `experiments/k274/k274_paper_mapping_results.json`
- Lookahead 審計：本研究所引用的所有策略結果都採用 t-1 訊號 → t 期決策的標準延遲（`signal.shift(1)` 或等效 lag），bootstrap / Monte Carlo / 抽樣 / train-test split 全部固定 seed，跨資產比較使用同 lag 慣例避免前視偏誤

## 圖表

![K274 新穎度分佈：9 NOVEL、9 EXTENSION、2 CONFIRMATION、0 CONTRADICTION](experiments/k274/figures/k274_novelty_distribution.png)

![Paper 4 寫作可行性評分：4C 保險論文 0.70 居首](experiments/k274/figures/k274_paper_4_viability.png)

![3 本論文的投稿就緒度：Paper 1 (JBF) 0.75、Paper 2 (PBFJ) 0.70、Paper 3 (VT vs Trend) 0.65](experiments/k274/figures/k274_paper_readiness.png)
