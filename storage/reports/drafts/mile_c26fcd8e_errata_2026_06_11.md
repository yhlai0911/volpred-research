# 把六個市場一起看，真的比只看自己更懂波動嗎？

> **[2026-06-11 Errata 摘要]** 本文發佈後，Codex 24h review 發現原版 K189 實作有三個方法論問題：forecast 與 attention weights 混入同日資訊、alpha 用整段 OOS 事後挑選、文末把 attention/EWMA 也寫成固定 500 日 training window。依修正後的 lagged rerun 重新檢查，主結論保留但口徑收斂：**attention 規格對六個資產都沒有穩健打贏單資產 EWMA；在 rolling ex ante selection 裡，0.9 只是 grid 中最常被選到的值，不是全樣本事後確認的唯一最佳值。**

這個想法乍看很有吸引力。

如果市場之間本來就會互相影響，那預測波動時，為什麼只看自己？美股、科技股、黃金、美債、新興市場、小型股，六個市場一起看，照理說應該比單看單一資產更聰明。

這次我們真的把這件事做成模型來驗。

方法很像替每個市場裝一個「注意力系統」：先估每個資產最近的波動，再讓模型決定要不要多看其他市場的訊號。白話講，它不會死板地把六個市場平均混在一起，而是試著替不同資產分配「應該聽誰的」權重。**修正後的版本要求 forecast 與 weights 都只能用 t-1 以前資訊；每個樣本外日期都只用此前 500 個交易日做 ex ante alpha selection。**

聽起來很進步，結果卻非常老派。

![Attention vs EWMA summary](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/attention_vs_ewma_summary.png)

六個資產全數失敗，沒有一個比最簡單的單資產基準模型更好。

這裡的六個資產是：

- SPY
- QQQ
- GLD
- TLT
- EEM
- IWM

在修正後 rerun 的有效樣本外區間 `2023-01-03` 到 `2024-12-31`，attention 版相對最簡單基準 EWMA 的表現變化如下：

- **SPY：+0.34%**
- **QQQ：+0.03%**
- **GLD：+0.28%**
- **TLT：+0.07%**
- **EEM：+0.07%**
- **IWM：+0.04%**

上面這些全都是**正數**，代表的是**全部都變差**。換句話說，修正 lookahead 與事後挑選之後，主結論沒有翻盤。

更耐人尋味的是，在每個樣本外日期各自做 rolling ex ante selection 時，模型最常選到的設定仍然靠近 **0.9**。但這裡更精確的說法是：**在 grid `{0.3, 0.5, 0.7, 0.9}` 裡，0.9 最常勝，不代表存在一個可以對整段 OOS 事後宣告的穩定唯一最適值。**

這個結果很像你想靠看鄰居家的天氣來判斷自己家要不要帶傘。偶爾會有幫助，但大多數時候，你家門口的雨其實還是比隔壁街更重要。

![Attention model comparison](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/attention_dm_comparison.png)

為什麼會這樣？

因為跨市場訊號有兩個很難同時成立的條件。第一，它們要真的和你的資產有關。第二，它們還要提供**你自己那一條價格路徑裡沒有的額外資訊**。很多時候第一點成立，第二點卻不成立。

這次就是典型例子。幾個市場之間的波動相關其實都不低，但那比較像「大家一起緊張」的同步現象，不代表拿別人的波動來加權，就能比你自己過去的波動更早知道下一步。

說得更直白一點：**在這個 attention 規格下，相關沒有轉成對單資產 EWMA 的穩健增量。**

這篇實驗還有一個容易讓人誤判的地方。它拿去跟另一個較重的傳統模型 GJR 相比時，在 6 個資產裡有 5 個方向上贏了；但那不代表 attention 模型很強，而是因為這次真正難打的對手，其實是前面那個最簡單、也最穩定的單資產 EWMA 基準。一旦你拿最硬的對手來比，attention 的優勢立刻消失。

這件事對一般投資人有個很實際的提醒。市場上很常看到「把更多資訊、更多市場、更多因子一起餵進去」就應該更準的想法，但現實常常剛好相反。當主體訊號本來就夠強時，外面的資訊加進來，不一定是補充，也可能只是把雜訊平均進來。

所以這篇研究最值得記住的，是它最後證明了一件很樸素的事：

**在波動率預測裡，很多時候你最該先相信的，還是資產自己的歷史。**

*資料來源：yfinance SPY、QQQ、GLD、TLT、EEM、IWM 日資料。本文依 `experiments/k189/` 的 2026-06-11 corrected rerun 更新：effective OOS `2023-01-03` 至 `2024-12-31`、attention window 252 日、EWMA lambda 0.94、每個 OOS 日期以前 500 個交易日做 ex ante alpha selection、DM 檢定另做 12 comparisons 的 Bonferroni 與 BH-FDR 校正。*
