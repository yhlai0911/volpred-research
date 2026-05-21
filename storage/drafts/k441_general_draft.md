---
title: "Range-Based 估計子作為 GARCH Proxy：哪一個最準？"
audience: general
status: draft
tags: [波動率估計, GARCH, range-based, QLIKE, GJR-GARCH, Yang-Zhang, 方法論]
experiment_refs: [K441]
---

# Range-Based 估計子作為 GARCH Proxy：哪一個最準？

## 一、研究問題：為什麼日內最高最低價如此重要？

評估 GARCH 類波動率模型表現時，最常見的標的（target）就是「日報酬平方」（close-to-close squared return，以下稱 CC r²）。這是教科書默認的 proxy，原因簡單：絕大多數歷史資料庫都記錄收盤價，計算成本最低。

但 CC r² 有一個結構性缺陷——它只用了「收盤」這一個時點的資訊。一日之中股價可能上沖下洗，從低點到高點波動 2%、最後收平，CC r² 會記錄為「幾乎零波動」；但日內振盪實際上代表了真實的不確定性。Parkinson（1980）首先指出：把高低價這個「幅度」資訊納入估計，可以**用更少觀測值得到更準的真實波動率估計**——理論效率約是 CC r² 的 5 倍。

K441 實驗的核心問題是：當我們用 GARCH 類模型做日波動率預測，**選擇哪一種 range-based proxy 來評估模型表現，會不會影響我們對「哪個模型最好」的判斷？**並進一步問：哪一個 proxy 在 SPY 樣本上最能引導我們選對模型？

## 二、五個 Proxy 與三個模型的全因子比較

K441 同時實作了五種波動率 proxy，並交叉測試三種主流 GARCH 變體。Proxy 包含：

- **CC (r²)**：傳統收盤對收盤報酬平方
- **Parkinson (1980)**：用 (log H − log L)² 估計，假設無漂移、連續價格
- **Garman-Klass (1980)**：在 Parkinson 上加入開收盤資訊，理論效率更高
- **Rogers-Satchell (1991)**：對價格漂移 robust，允許非零均值
- **Yang-Zhang (2000)**：分解隔夜報酬與日內波動，理論上 unbiased 且效率最高

模型部分：

- **GARCH(1,1)**：對稱波動傳遞
- **GJR-GARCH(1,1)**：加入槓桿項，allow 利空衝擊放大條件變異
- **EGARCH(1,1)**：對 log(σ²) 建模，自動正性，捕捉非對稱

## 三、資料來源

- **實驗編號**：K441（Range-Based Volatility Estimators as GARCH Proxy）
- **標的**：SPY ETF（追蹤 S&P 500 指數）
- **資料源**：yfinance 日 K 線（OHLC）
- **OOS 期間**：2023-01 至 2024-12（約 500 個交易日）
- **參考文獻**：Parkinson (1980)、Garman & Klass (1980)、Rogers & Satchell (1991)、Yang & Zhang (2000)、Alizadeh, Brandt & Diebold (2002)、Chou (2005)

## 四、Lookahead Audit（誠實聲明）

QLIKE 評估的本質是「比較模型 t 期的預測 σ̂²ₜ vs 真實波動 σ²ₜ」。其中：

- **預測值 σ̂²ₜ**：由 GARCH/GJR/EGARCH 模型在 t-1 收盤後用 t-1 及以前資訊估計
- **Proxy（target）σ²ₜ**：是 t 期的觀測量本身，**必然包含 t 日的 OHLC**

這不是 lookahead bias——proxy 本來就是「我們希望模型預測準的真實值」。Lookahead bias 在於**預測式內部使用了未來資訊**；本實驗的條件變異遞推皆嚴格走 t-1 → t 的時序，並未把當期 OHLC 灌進預測。文章表中報告的 QLIKE 數字皆為樣本外（OOS）。

## 五、結果：QLIKE 矩陣（越低越好）

下表為三個模型 × 五個 proxy 的 OOS QLIKE 完整矩陣：

| Proxy           | GARCH(1,1) | GJR-GARCH(1,1) | EGARCH(1,1) |
|-----------------|-----------:|---------------:|------------:|
| CC (r²)         |     1.3216 |         1.3179 |      1.3450 |
| Parkinson       |     0.4310 |         0.3820 |      0.4035 |
| Garman-Klass    |     0.4083 |         0.3591 |      0.3785 |
| Rogers-Satchell |     0.4692 |         0.4194 |      0.4376 |
| **Yang-Zhang**  | **0.3078** |     **0.2828** |  **0.2899** |

幾個重要觀察：

**第一，CC r² 的 QLIKE 在所有模型下都是最差的（1.32 量級），且與 range-based proxy 差了一個數量級**。同一個 GJR-GARCH 模型，用 CC r² 評估會得到 QLIKE = 1.318；換成 Yang-Zhang 評估則只有 0.283——絕對減幅達 **78.5%**（也就是 best_proxy_for_gjr 對 worst_proxy_for_gjr 的 QLIKE 改善 78.5%）。這意味著 CC r² 的雜訊太大，蓋過了模型的真實預測能力。

**第二，Yang-Zhang 在所有三個 GARCH 變體下都是最佳 proxy**——0.308（GARCH）、0.283（GJR）、0.290（EGARCH）。它整合隔夜跳空與日內波動的設計，明顯優於只用日內 H/L 的 Parkinson 與 Garman-Klass。

**第三，跨 proxy 的模型排名一致**：除了 CC r² 內部對 EGARCH/GARCH 排名因雜訊過大略有不同外，**所有 range-based proxy 都得到同一個結論——GJR-GARCH(1,1) 是最佳模型**（ranking_consistent = true）。這是非常重要的 robustness 證據：你選哪個 range proxy 不會改變「該用哪個模型」這個結論。

## 六、比較檢定：差異是顯著的嗎？

僅比較 QLIKE 數字還不夠，必須做兩模型比較。K441 跑了 GARCH vs GJR、GARCH vs EGARCH 的比較檢定，使用 Yang-Zhang 作為 proxy 時：

- **GARCH vs GJR-GARCH**：統計強度 2.72，達顯著水準（顯著性 p ≈ 0.0066），方向 GJR 較佳
- **GARCH vs EGARCH**：統計強度 1.66，邊際顯著（顯著性 p ≈ 0.097），方向 EGARCH 較佳

換成 Garman-Klass 為 proxy 時，GARCH vs GJR 的統計強度高達 6.23（顯著性 p ≈ 4.6×10⁻¹⁰），差異更明顯。GJR-GARCH 對 GARCH 的優越性是**強統計強度** confirmed（HLZ 2016 嚴格統計門檻）。

## 七、CARR 模型補充比較

K441 還跑了 Conditional Autoregressive Range（CARR；Chou 2005）模型，分 Exponential 與 Weibull 兩個版本。CARR 直接對 log range 建模，理論上跟 range-based proxy 比較會有「同口徑優勢」。

| Proxy           | GJR-GARCH | CARR-Weibull |
|-----------------|----------:|-------------:|
| Garman-Klass    |    0.3591 |       0.3167 |
| Rogers-Satchell |    0.4194 |       0.3604 |
| Yang-Zhang      |    0.2828 |       0.4215 |

結果有意思：CARR-Weibull 在 Garman-Klass 與 Rogers-Satchell proxy 下小幅勝過 GJR；但在 Yang-Zhang proxy 下反而被 GJR 大幅擊敗（兩模型比較顯著，統計強度 −4.66，顯著性 p ≈ 3×10⁻⁶）。原因可能在於 Yang-Zhang 包含了隔夜資訊，而 CARR 只建模日內 range，無法 capture 隔夜跳空。**綜合平均排名：GJR-GARCH 2.0 > CARR-Weibull 2.2 > EGARCH 3.4 ≈ CARR-Exp 3.4 > GARCH 4.0**——GJR 仍是最佳全能選手。

## 八、效率倍數：為什麼 range-based proxy 雜訊小？

K441 計算了各 proxy 估計變異數的相對比例：

| Proxy           | 相對 CC r² 雜訊 | 效率倍數 |
|-----------------|---------------:|---------:|
| CC (r²)         |          1.000 |     1.00 |
| Parkinson       |          0.147 |     6.81 |
| Garman-Klass    |          0.181 |     5.52 |
| Rogers-Satchell |          0.254 |     3.93 |
| Yang-Zhang      |          0.604 |     1.66 |

注意：Parkinson 雜訊最低（效率倍數 6.81，與 Parkinson 1980 理論值 5x 接近且更高），但 QLIKE 表現卻不如 Yang-Zhang。**雜訊低 ≠ proxy 好**——Yang-Zhang 雜訊比 Parkinson 高，是因為它正確包含了隔夜跳空波動，而隔夜部分本身就是 SPY 真實波動的一部分。Parkinson 把這部分濾掉，估計變異雖小，但**系統性低估了真實波動**（年化波動 15.34% vs Yang-Zhang 19.42% 與 CC 19.08%）。在 QLIKE 這個比例尺度下，低估反而拉大誤差。

## 九、診斷與穩健性

GJR-GARCH(1,1) 殘差的 Ljung-Box 平方殘差檢定（lag 10：Q=9.27，顯著性 p≈0.51；lag 20：Q=12.54，顯著性 p≈0.90）—**未拒絕白雜訊假設**，表示模型已 capture 大部分自相關結構。Jarque-Bera 強烈拒絕常態（如預期；金融報酬尾部厚）。

跨 proxy 相關矩陣顯示 Parkinson、Garman-Klass、Rogers-Satchell 三者高度相關（0.88-0.98），三者本質上都用日內 H/L 構造；Yang-Zhang 與三者相關係數約 0.81-0.87，與 CC r² 相關 0.71，反映其獨特的隔夜分量設計。

## 十、實務建議

**結論一**：若你正在評估 GARCH 類模型，**強烈建議改用 Yang-Zhang 作為 QLIKE proxy**，而非預設的 CC r²。同樣的模型、同樣的資料，後者會讓 QLIKE 看起來惡化 4 倍，掩蓋掉真實的模型優劣。

**結論二**：對美股大盤類資產（SPY 等高流動性 ETF），**GJR-GARCH(1,1) 是穩健首選**——跨五種 proxy 一致最優，槓桿項抓住了下跌時波動放大的不對稱性。

**結論三**：CARR 是補充工具而非取代品。在純日內 range 應用上 CARR-Weibull 有競爭力；但若你的應用涉及隔夜風險（隔夜避險、跨時區套利），GJR-GARCH + Yang-Zhang 的組合更全面。

**注意事項**：本實驗只用 SPY 一個標的、2023-2024 兩年 OOS。其他資產類別（個股、加密貨幣、商品、新興市場 ETF）的最佳組合可能不同。不同期間（高波動期 vs 低波動期）也可能改變排名——後續延伸可重跑 2008、2020 等 stress regime。

## 十一、重點整理

1. CC r² 是雜訊最大的 proxy，QLIKE 比 range-based 高 4 倍
2. Yang-Zhang 是 GARCH 類模型的最佳 QLIKE proxy（包含隔夜資訊）
3. GJR-GARCH(1,1) 跨五個 proxy 都是最佳模型（ranking 一致）
4. GJR vs GARCH 的優勢具強統計強度，達顯著水準
5. 雜訊低 ≠ proxy 好：Parkinson 雜訊最低但會系統性低估真實波動

## 圖表


![K441 QLIKE 矩陣（5 模型 × 5 proxies）](experiments/k441/k441_qlike_matrix.png)

![GJR-GARCH 跨 5 個 proxy 的 QLIKE：YZ 0.28 vs CC 1.32](experiments/k441/k441_gjr_proxies.png)

![Range estimator 統計效率對比](experiments/k441/k441_efficiency.png)
