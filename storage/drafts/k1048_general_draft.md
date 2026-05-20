---
title: "高低恐慌兩個世界：門檻型 GARCH-X 模型可行嗎"
audience: general
status: draft
tags: [波動率, GARCH, VIX, 門檻模型, 風險管理, 變數選擇, OOS]
experiment_refs: [K1048]
---

# 高低恐慌兩個世界：門檻型 GARCH-X 模型可行嗎

## 一、問題的起點：市場真的只有一張臉嗎

如果我們把過去二十年的 SPY 日報酬攤開來看，會立刻發現一件事：恐慌指數 VIX 在 12 的時候，市場波動的「個性」跟 VIX 在 35 的時候完全不一樣。低 VIX 的日子裡，價格會在窄區間內慢慢漂移，偶有跳動，但訊息消化得很快；高 VIX 的日子，新聞像火上澆油，一個利空可以延燒好幾天，槓桿效應（leverage effect，下跌比上漲更容易誘發更大的波動）也明顯放大。

那麼，一個直觀的問題是：傳統 GARCH 類模型（包含我們在這個平台上反覆驗證的 A4f：GJR-GARCH 加 VIX² 外生項）用同一組參數去描繪這兩個世界，是不是太勉強？如果我們允許參數在「VIX 高」與「VIX 低」兩個 regime 之間切換，並且讓最佳的外生變數也跟著切換，模型會不會更貼近現實？K1048 這支實驗就是在回答這個問題。

但我必須先把結論說在前面，否則文章會誤導讀者：**樣本內 regime 切換確實顯著到不能忽視；OOS（樣本外）QLIKE 雖然數值最佳，卻沒有任何 DM 檢定通過 Harvey (2016) 的 \|t\| ≥ 3.0 門檻**。亮點在於 VaR 5% 的 Kupiec 通過率，而不是點預測準度。這是一個「樣本內巨幅顯著、OOS 點預測不顯著、但風險校準有實用價值」的混合結果。

## 二、實驗設計：把 VIX=15 當作市場心情的分水嶺

K1048 的核心設計可以拆成三層：

第一層是 **門檻 GJR-GARCH**：把整個變異數方程依「前一日 VIX 水準」切成兩條 — VIX ≤ 門檻走低 regime 參數，VIX > 門檻走高 regime 參數。所有 regime 切換都用 t-1 訊號（昨日的 VIX），所以即時可實作，沒有 lookahead。

第二層是 **每個 regime 各自做變數選擇**。候選池有 5 個外生變數：VIX²、VIX 水準、log(VIX)、VIX 變化、VIX 百分位（相對於過去 252 日）。每個 regime 用 BIC 各選一個最佳。

第三層是 **門檻校準**：候選門檻為 VIX = {15, 20, 25, 30, 35}，在樣本內（2004–2018）以 BIC 比較，再固定下來用於 OOS（2019–2026）。OOS 採 rolling window 2,000 日、每 63 日重新估計一次，seed 固定 42。

「門檻在樣本內估、固定到 OOS」是一個保守做法，雖然失去了 adaptive threshold 的彈性，但避開了門檻自身在 OOS 飄移帶來的 lookahead 風險。這是門檻類模型的常見取捨。

## 三、樣本內：兩個世界的差異真的很大

最佳門檻是 **VIX = 15**，遠低於 25 或 30 那種「明顯系統性風險」的水位。這個結果有點意外但合理 — 因為平靜市場的時間佔比夠大（樣本內 1,667 日 ≤ 15、2,044 日 > 15），低門檻才能讓兩個 regime 都有足夠樣本估計。

LR 檢定統計量 = **135.23，p < 0.001**（卡方 6 自由度），BIC 從 pooled 的 −24,737.5 改善到 threshold 的 −24,823.4，**改善幅度 85.9**。這代表 regime 切換不是在挖噪訊，是真的捕捉到結構差異。

兩個 regime 的關鍵參數：

| 參數 | Pooled | 低 VIX (≤15) | 高 VIX (>15) |
|------|--------|--------------|--------------|
| α (近期衝擊) | 0.053 | 0.038 | ≈ 0.000 |
| γ (槓桿效應) | 0.085 | 0.038 | **0.168** |
| β (持續性) | 0.882 | 0.718 | 0.879 |
| 持續性 (α+γ/2+β) | 0.978 | 0.775 | 0.964 |

幾個重點：

**槓桿效應 γ 在高 VIX regime 是低 VIX regime 的 4.5 倍**（0.168 vs 0.038）。這證實了一個直覺 — 當市場已經緊張的時候，新的負面衝擊會被放大反應，跌一根 K 棒造成的波動上修，遠大於同樣幅度上漲帶來的下修。

**高 VIX regime 的 α 趨近於零**，意思是「對稱性衝擊（不分漲跌的瞬間振幅）已經沒在貢獻」，所有的條件變異數動能都從不對稱項（γ）來。這是一個很乾淨的特徵化：恐慌時，市場只對壞消息有記憶。

**持續性差異也很大**。低 VIX 的 0.775 表示衝擊大約 4–5 日就消散，高 VIX 的 0.964 則是衝擊半衰期變成數週甚至更久。這跟我們在 K1019（MS(2)-GJR）看到的 regime dynamics 相符 — 高波動 regime 不只是振幅放大，連記憶都拉長了。

## 四、變數選擇：兩個 regime 喜歡不同的訊號

這是 K1048 最有趣的部分。兩個 regime 各自做 BIC 變數選擇後：

- **低 VIX regime 偏好 VIX_change**（VIX 變化），BIC 改善 20.3
- **高 VIX regime 偏好 VIX_percentile**（VIX 百分位），BIC 改善 6.0

直覺解讀：在平靜的市場裡，VIX 從 12 跳到 14 是一個訊號 — 變化（動能）才是線索，因為水準本身還沒到任何「高」的閾值。在恐慌的市場裡，VIX 在 30、35 一帶震盪，變化已經失去資訊量，反而是「相對於過去 252 日的位階」可以告訴你回歸均值的壓力有多大。

這也呼應了我們在 K1031（Bayesian SSVS for GARCH-X）的發現 — 不同候選變數在不同期間的 PIP（後驗包含機率）會跳動。K1048 的貢獻在於把「為什麼會跳動」具體化成「regime 不同所以最佳變數不同」。

## 五、OOS：QLIKE 最低，但顯著性沒過

接下來是真正考驗的部分 — 樣本外 2019–2026 這 1,828 個交易日，模型表現如何？

![QLIKE OOS 比較](../../experiments/k1048/k1048_qlike_comparison.png)

| 模型 | OOS QLIKE | DM vs GJR | DM vs A4f |
|------|-----------|-----------|-----------|
| GJR (baseline) | −8.2586 | — | — |
| GJR + VIX² (A4f) | −8.2788 | t = −0.995 NS | — |
| Threshold GJR | −8.2817 | t = −1.016 NS | t = −0.211 NS |
| **Threshold GJR-X** | **−8.2831** | t = −0.900 NS | t = −0.246 NS |

所有 \|t\| 全部小於 1.1，遠遠不到 Harvey (2016) 建議的 \|t\| ≥ 3.0 嚴格門檻（嚴格門檻是因為這個平台同時跑超過 50 條策略，必須對 multiple testing 保守）。

換句話說，**門檻 GJR-X 在 OOS QLIKE 數值上確實是 4 個模型裡最低的**（−8.2831 比 baseline GJR 的 −8.2586 改善約 0.3%），**但這個差距完全可能是隨機波動**，沒有統計意義上的優越性。

這個結果再次印證 K813（Smooth Transition GARCH）的教訓：樣本內 LR 檢定多顯著都好，OOS 點預測能不能贏過簡單模型，是另一回事。K813 用了 11 個參數，OOS DM 只有 −0.11；K1048 雖然把參數結構縮到 10–12 個，OOS DM 也只爬到 −0.246。**結構複雜度增加並沒有等比例兌現成 OOS 改善**。

## 六、亮點所在：VaR 5% 的 Kupiec 通過率

但 K1048 不是空手而回 — 它在風險管理應用上有具體價值。

| 模型 | VaR 5% Kupiec | VaR 1% Kupiec |
|------|---------------|---------------|
| GJR | FAIL (p=0.015) | FAIL (p<0.001) |
| GJR + VIX² | FAIL (p=0.002) | FAIL (p<0.001) |
| **Threshold GJR** | **PASS (p=0.864)** | FAIL (p<0.001) |
| Threshold GJR-X | PASS (p=0.154) | FAIL (p<0.001) |

VaR 5% Kupiec 檢定的標準是「實際違反次數應該接近 5%」。OOS 期望違反次數 91.4 次（5% × 1,828 日）：

- GJR 違反 115 次（6.3%）— 風險低估
- A4f 違反 122 次（6.7%）— 風險低估更嚴重
- **Threshold GJR 違反 93 次（5.1%）— 幾乎完美貼近期望**
- Threshold GJR-X 違反 105 次（5.7%）— 略微低估但通過

這是 K1048 的真正貢獻：**只有 regime 切換的模型，在 OOS 把 VaR 5% 的尾部校準做對了**。為什麼？因為高 VIX regime 的高槓桿、高持續性參數，會在市場壓力上升時自動把預測波動拉高，從而擴大 VaR 區間，少漏掉真實的尾部事件。Pooled 模型用一組「平均」參數，在恐慌期就會系統性低估。

VaR 1% 全部 FAIL，這是因為實驗用 Normal distribution 做尾部假設，1% 尾部在常態下嚴重低估 SPY 的真實尾風險。K1066（A4f microstructure 延伸）跟 K1067 之後的工作會把 Student-t 尾部納入，預期能補上這塊。

## 七、Lookahead 與隨機性檢查

身為一個高度槓桿模型結構的研究，必須說清楚防錯：

1. **變數選擇 lookahead**：K1048 的變數選擇用 in-sample 期（2004–2018）一次決定，固定到 OOS。理想做法是 walk-forward selection（每次重估時重選變數），但實作成本高。固定變數選擇雖然不算 walk-forward，但**至少沒有用 OOS 資料來選變數**，所以不違反 lookahead。已在 limitations 中標明。

2. **門檻 lookahead**：門檻 VIX=15 用 in-sample 估，固定到 OOS。同樣保守。

3. **Regime 切換訊號**：所有切換用 t-1 的 VIX，產生 t 的 σ̂_t。沒有用到 t 當天的 VIX。

4. **Seed 固定**：seed=42，可復現。

5. **Refit 頻率**：每 63 日重新估計參數一次，這是 K1024 校準頻率實驗驗證過的合理頻率。

## 八、結論：什麼結果可以信、什麼不能信

**可以信的**：
- 樣本內 regime 切換顯著（LR=135.23）
- 高 VIX regime 槓桿效應顯著大於低 VIX
- 不同 regime 偏好不同的外生變數
- 門檻 GJR 在 OOS VaR 5% 校準上明顯優於 pooled 模型

**不能信的**：
- 「Threshold GJR-X 是最好的點預測模型」 — DM 檢定 t=−0.246，沒過顯著門檻
- 「樣本內顯著性會自動換來 OOS 改善」 — 跟 K813 一樣的反例

**研究意涵**：對交易策略而言（追求 alpha），threshold 模型 OOS QLIKE 改善太小、不顯著，加複雜度不划算；對風險管理而言（避免低估尾部），threshold 結構是值得採用的。這兩件事可以分開決策，這也是 K1048 的真實價值。

## 資料來源

- **K1048**：Threshold GARCH-X with Variable Selection（`experiments/k1048/`）
- **資產**：SPY 日報酬，N = 5,540
- **樣本期**：2004-04-02 至 2026-04-10
  - 樣本內：2004–2018，N = 3,712
  - OOS：2019–2026，N = 1,828
- **資料來源**：yfinance（SPY、^VIX、^VIX9D）
- **參數估計**：rolling window=2000，refit_every=63，seed=42
- **相關實驗**：K1024（refit 頻率校準）、K1066（A4f microstructure 延伸）、K1031（SSVS 變數選擇）、K813（STGARCH 反例）、K1019（MS(2)-GJR regime dynamics）

![Regime parameters comparison](../../experiments/k1048/k1048_regime_parameters.png)

## 參考文獻

- Gonzalez-Rivera, G. (1998). "Smooth-transition GARCH models." *Journal of Business & Economic Statistics*.
- Chen, C. W. S., & So, M. K. P. (2006). "On a threshold heteroscedastic model." *International Journal of Forecasting*.
- So, M. K. P., Chen, C. W. S., & Liu, F. C. (2006). "Best subset selection of autoregressive models with exogenous variables and Student-t error terms." *Journal of the Royal Statistical Society Series C*.
- Patton, A. J. (2011). "Volatility forecast comparison using imperfect volatility proxies." *Journal of Econometrics*.
- Harvey, C. R. (2016). "...and the cross-section of expected returns." *Review of Financial Studies* — \|t\| ≥ 3.0 多重檢定門檻建議。
