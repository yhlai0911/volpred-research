---
title: "K893：VIX 政體加權 Conformal VaR（RWC）vs 歷史模擬法——λ=0.05 值得 3–4% 更緊的區間嗎？"
audience: research
status: draft
tags:
  - K893
  - VaR
  - conformal
  - VIX-regime
  - risk-management
  - HistSim
  - bootstrap
experiment_refs:
  - K893
---

# K893：VIX 政體加權 Conformal VaR（RWC）vs 歷史模擬法——λ=0.05 值得 3–4% 更緊的區間嗎？

[提出: Claude, 執行: Claude]

---

## 摘要

本文報告 K893 的 OOS 驗證結果（2019-01-02 至 2026-04-02，涵蓋 COVID 崩盤、2022 升息循環、2024–2025 AI 行情）。我們在 SPY、QQQ、0050.TW 三個市場測試四種 VaR 規格（Normal、Student-t、HistSim rolling-500 天、以及 VIX 政體加權 Conformal VaR RWC，λ 取 0.05/0.1/0.2），以 Kupiec 覆蓋率檢定 + 條件覆蓋（CC）+ Basel traffic light 三合一（Trinity）為主要門檻，輔以 ES 充分性檢定。

核心發現：**RWC λ=0.05 在全部三個資產都通過 Trinity PASS，同時把 99% VaR interval 壓緊 1.4–4.4%**。λ=0.1 在 SPY 亦通過，λ=0.2 在 SPY 的 Kupiec p=0.020 落在拒絕域，ES 同步失敗。Student-t 在 QQQ 的 Kupiec p=0.0002 崩潰，無法通過 99% 覆蓋率要求。HistSim rolling-500 是全場最穩健的無調參 baseline，三資產均通過 99% Trinity。

結論：RWC λ=0.05 是有價值的 useful refinement，適合願意承受少量模型複雜度換取略緊 interval 的實務用途；但它的收益邊際，不能用來取代 HistSim 的零調參穩健性。λ 越大反而越容易因 effective sample 縮減而失去覆蓋。

---

## 研究背景

VaR 估計面對的核心困難，在過去七年裡被暴露得相當徹底：COVID 2020 的快速崩跌讓許多模型的 effective sample 充滿「低恐慌期」歷史，導致 VaR 估計過度樂觀；2022 升息造成的持續性回檔讓條件覆蓋（conditional coverage）壓力極高；而 2024–2025 AI 行情後市場集中在少數科技標的，肥尾現象在 QQQ 之類成分集中的 ETF 更加顯著。

歷史模擬法（HistSim）的常見批評是：它對所有過去 500 天一視同仁，無法加重「當前市場狀態相似的過去日子」的影響力。這正是 RWC（Regime-Weighted Conformal VaR）的出發點：**用 VIX 政體相似度當作加權函數，把 standardized residuals 的歷史分布重新塑形，藉此產生比 HistSim 更窄但仍能維持覆蓋率的 VaR 區間**。

λ 是 RWC 唯一的調參旋鈕——控制加權的「銳利度」：λ=0 退化回等權 HistSim，λ 越大越集中在 VIX 政體最相似的過去日子，effective sample size 越小，interval 可能更緊但覆蓋風險也越高。

本研究問的問題很直接：**在跨過七年 OOS 的三資產測試下，RWC 的哪個 λ 值能同時通過 Trinity 且帶來統計上可測量的 interval 收緊？**

---

## 方法與數據

| 項目 | 設定 |
|------|------|
| 資產 | SPY（美股大盤 ETF）、QQQ（Nasdaq 100 ETF）、0050.TW（台灣 50） |
| 數據來源 | yfinance（日頻調整後收盤價） |
| SPY/QQQ 全樣本 | 2005-01-04 to 2026-04-02，n=5345 |
| 0050.TW 全樣本 | 2009-01-05 to 2026-04-02，n=4081 |
| OOS 期間 | 2019-01-02 to 2026-04-02 |
| SPY/QQQ OOS 天數 | 1823 / 1822 |
| 0050.TW OOS 天數 | 1697 |
| VIX regime split（SPY）| Low ≤15: 415 天；Medium 15–25: 1059 天；High >25: 349 天 |
| HistSim 視窗 | rolling 500 天 empirical quantile |
| RWC λ 選項 | 0.05 / 0.1 / 0.2（λ=0 等同 HistSim） |
| 模型重估頻率 | 每 63 個交易日重估一次 |
| 評估信心水準 | α=1%（99% VaR）、α=5%（95% VaR） |
| 主要統計門檻 | Trinity PASS = Kupiec PASS + CC PASS + Basel GREEN |
| 輔助統計 | ES 充分性檢定（z 統計量，p<0.05 為 fail） |

**SPY 描述統計**：OOS 期間日報酬平均 0.039%，標準差 1.198%，偏態 −0.302，超額峰度 14.70。VIX 均值 19.16，最高 82.69（2020 COVID 崩盤）。

---

## 核心發現

### 發現一：SPY α=1% Trinity 結果——RWC λ=0.05/0.1 通過，λ=0.2 失守

下表整理 SPY 在 99% VaR（α=1%）的 Trinity 評估：

| 規格 | 違規次數 | 違規率 | Kupiec p | CC p | Basel | Trinity | avg VaR% |
|------|---------|--------|----------|------|-------|---------|----------|
| Normal | 38 | 2.08% | 0.000 | 0.203 | GREEN | **FAIL** | −2.41 |
| Student-t | 27 | 1.48% | 0.054 | 0.367 | GREEN | **PASS** | −2.64 |
| HistSim | 20 | 1.10% | 0.682 | 0.505 | GREEN | **PASS** | −3.25 |
| RWC λ=0.05 | 21 | 1.15% | 0.524 | 0.484 | GREEN | **PASS** | **−3.11** |
| RWC λ=0.1 | 25 | 1.37% | 0.131 | 0.404 | GREEN | **PASS** | −3.15 |
| RWC λ=0.2 | 29 | 1.59% | **0.020** | 0.333 | GREEN | **FAIL** | −3.19 |

幾個需要直接說清楚的數字：

Normal 以 2.08% 違規率遠超 target 1%，Kupiec p 為 0，早在 Basel traffic light 進入 RED 之前就已被拒絕——這是 SPY 近七年的肥尾特性（峰度 14.70）對高斯假設的直接否決。

RWC λ=0.2 的違規率 1.59%，Kupiec p=0.020 剛好落在 0.05 拒絕域，同時 ES 充分性 z=2.54，p=0.011，兩關同時失守。失守原因可以從機制理解：λ=0.2 的加權過度集中在 VIX 相似天，**有效樣本數（effective sample size）縮減到某個臨界值以下**，使估計出的 quantile 在尾端不穩定——在 COVID / 2022 等極端事件的前後，VIX 相似的「過去」本來就很少，hard truncation 式的集中會讓 VaR 估計的隨機誤差暴增。

RWC λ=0.05 的違規率 1.15%，Kupiec p=0.524，ES z=1.69，p=0.092——三關全部通過。avg VaR% 為 −3.11%，相比 HistSim 的 −3.25%，**收緊了 4.3%**。這個收緊幅度在統計上意味著在相同覆蓋率品質下，每天的資本預留可以少 4.3%——在大型機構的 VaR 限額管理下，這個差距並不是小事。

![SPY 99% VaR 各模型違規率（OOS 2019–2026）](experiments/k893/fig1_violation_rate.png)

*圖 1：SPY OOS 2019–2026，99% VaR 六個規格的違規率（%）。綠色 bar 通過 Trinity，紅色 bar 失敗。藍色虛線為目標 1%。Normal（2.08%）與 RWC λ=0.2（1.59%）失敗；Student-t、HistSim、RWC λ=0.05/0.1 通過。*

---

### 發現二：VaR Interval 寬度——RWC 比 HistSim 緊，但幅度不隨 λ 單調增加

![SPY 99% VaR 平均區間寬度比較](experiments/k893/fig2_avg_var.png)

*圖 2：SPY 四個 non-parametric / semi-parametric 規格的 avg VaR%（取絕對值；數值越小代表 interval 越緊）。RWC λ=0.05/0.1/0.2 相比 HistSim 分別緊 4.3%、3.3%、1.9%。*

HistSim avg VaR% 絕對值為 3.251%，各 RWC 規格如下：

| 規格 | avg \|VaR%\| | 相比 HistSim 緊縮幅度 |
|------|-------------|----------------------|
| HistSim | 3.251% | — |
| RWC λ=0.05 | 3.112% | **4.3% tighter** |
| RWC λ=0.1 | 3.148% | 3.3% tighter |
| RWC λ=0.2 | 3.187% | 1.9% tighter |

這個非單調模式值得記錄：**λ 越大，interval 應該更緊（加權更集中），但實際緊縮幅度反而下降**。原因在於：過度集中加權會讓估計出的 quantile 在高 VIX 時間段突然「撐大」——因為極端政體的歷史樣本太少，強制集中反而會讓 empirical quantile 的右尾不穩定。這和 λ=0.2 的覆蓋率失守有相同根源。

λ=0.05 的設計是「溫和的政體傾斜」：在 VIX Medium 政體（1059 天，佔 OOS 58%）時，歷史殘差的相似天仍夠多，加權能有效削減「不像現在的過去」的噪音，同時不會讓 effective sample size 縮減到危險水平。

---

### 發現三：QQQ——Student-t 在 1% 水準崩潰，RWC λ=0.05 通過

QQQ 是最有挑戰性的資產。OOS 1822 天，QQQ 的峰度為 7.64（低於 SPY 的 14.70，但 QQQ 的個別報酬分布在高 VIX 期間更不對稱），加上 2020 COVID 後科技股的劇烈波動放大。

| 規格 | 違規率 | Kupiec p | Trinity | avg VaR% |
|------|--------|----------|---------|----------|
| Normal | 2.41% | 0.000 | FAIL | −3.03 |
| Student-t | 1.97% | **0.0002** | **FAIL** | −3.28 |
| HistSim | 0.82% | 0.433 | PASS | −3.88 |
| RWC λ=0.05 | 1.04% | 0.857 | PASS | **−3.83** |
| RWC λ=0.1 | 1.21% | 0.390 | PASS | −3.83 |
| RWC λ=0.2 | 1.37% | 0.131 | PASS* | −3.85 |

*QQQ RWC λ=0.2 Kupiec PASS，但 ES 失敗（z=2.04，p=0.042）。

Student-t 在 QQQ 的失敗（Kupiec p=0.0002，違規率 1.97%）是一個明確的 parametric mis-specification 信號。Student-t 以固定的對稱厚尾假設來近似 QQQ 的報酬分布——但 QQQ 的尾端不對稱性（左尾更重）在這七年 OOS 被放大：COVID 崩盤的 QQQ 單日跌幅多次超出 Student-t 估計的 99% VaR，導致累積違規次數 36 次（vs target 18 次）。

HistSim 的 0.82% 違規率明顯低於 1%，代表稍微保守；RWC λ=0.05 以 1.04% 貼近 target，Kupiec p=0.857（最接近 H0 下的期望值），avg VaR% 為 −3.826%，比 HistSim 的 −3.879% 緊 1.4%。

---

### 發現四：0050.TW——三資產中唯一 Student-t 通過 Trinity 的市場

0050.TW OOS 1697 天（2019-01-02 to 2026-04-02），VIX regime 比例：Low 394 / Medium 971 / High 332。

| 規格 | 違規率 | Kupiec p | Trinity | avg VaR% |
|------|--------|----------|---------|----------|
| Normal | 1.94% | 0.001 | FAIL | −2.70 |
| Student-t | 1.24% | 0.343 | PASS | −3.02 |
| HistSim | 1.12% | 0.627 | PASS | −3.20 |
| RWC λ=0.05 | 1.24% | 0.343 | PASS | **−3.06** |
| RWC λ=0.1 | 1.24% | 0.343 | PASS | −3.09 |
| RWC λ=0.2 | 1.53% | **0.041** | **FAIL** | −3.16 |

0050.TW 的 Student-t 通過 Trinity（Kupiec p=0.343，違規率 1.24%），與 QQQ 的崩潰形成對比。台灣大型股的報酬分布相對較接近對稱，峰度（17.33）雖高，但對稱厚尾的 Student-t 在此有一定適用空間。

RWC λ=0.05 在 0050.TW 同樣通過（1.24%，Kupiec p=0.343），avg VaR% 為 −3.063%，比 HistSim 的 −3.204% 緊 4.4%。λ=0.2 再次失守（Kupiec p=0.041），與 SPY 的模式一致。

---

## λ 敏感度分析小結

將三資產的 Trinity 通過與否彙整：

| λ 值 | SPY Trinity | QQQ Trinity | 0050.TW Trinity | 三資產全 PASS？ |
|------|------------|------------|----------------|--------------|
| 0.05 | PASS | PASS | PASS | **是** |
| 0.1 | PASS | PASS | PASS | **是** |
| 0.2 | FAIL（Kupiec+ES） | 邊緣（ES fail） | FAIL（Kupiec） | **否** |

λ=0.05 是最穩健的選擇：三資產全部通過，且 interval 收緊幅度（1.4–4.4%）來自加權機制，沒有以犧牲覆蓋率為代價。λ=0.1 在 SPY/QQQ 仍通過，但 0050.TW 的 Kupiec p=0.343 和 SPY 的 1.37% 違規率顯示已開始向邊緣移動。λ=0.2 在三資產中兩個直接失敗，機制上已越過 effective sample 的臨界點。

**規律可歸納為**：在 VIX regime 結構下，「溫和的政體傾斜」能從歷史殘差中提取有效的 state-conditioning 資訊；「過度集中」則會讓模型在少樣本政體（特別是 VIX High 政體，349 天佔 OOS 19%）中承受過大的估計誤差，結果反而比等權 HistSim 更不穩定。

---

## 跨資產比較與 VIX 政體分解

SPY 在 VIX High 政體（349 天）的違規分解：

| 規格 | VIX Low 違規率 | VIX Medium 違規率 | VIX High 違規率 |
|------|--------------|-----------------|----------------|
| Normal | 1.69% | 2.36% | 1.72% |
| Student-t | 0.96% | 1.79% | 1.15% |
| HistSim | 0.96% | 1.32% | **0.57%** |
| RWC λ=0.05 | 0.96% | 1.42% | **0.57%** |
| RWC λ=0.1 | 1.20% | 1.70% | **0.57%** |
| RWC λ=0.2 | 1.69% | 1.89% | **0.57%** |

值得注意：**所有 non-parametric 規格在 VIX High 政體的違規率都是 0.57%（2/349 天）**，明顯低於 1% target。在真正的高恐慌期，HistSim 和 RWC 都傾向於過度保守——因為 500 天視窗裡的 extreme quantile 本來就在高波動期被拉大了。RWC 並未在 High 政體進一步改善，主要作用在 Medium 政體（1059 天，佔 58%）的精確調整。

相反，Normal distribution 在 Medium 政體的 2.36% 違規率最高，顯示 Normal 對中等波動日的肥尾仍然低估——這正是 SPY 峰度 14.70 的直接體現。

---

## 實務意義

**對風控部門的建議**：

1. **HistSim rolling-500 仍是首選 no-tuning baseline**。三資產全部通過 99% Trinity，且在高 VIX 政體下不會欠估。如果沒有資源維護 λ 的動態調整，直接用 HistSim 是合理選擇。

2. **RWC λ=0.05 值得實務考慮**。在接受略高的模型複雜度（需要維護 VIX regime 相似度計算）的前提下，λ=0.05 能在三資產都通過 99% Trinity 的同時，把 VaR interval 壓緊 1.4–4.4%。這個收緊幅度在 VaR 限額管理、資本計提（Basel III Internal Models Approach）或 FRTB 場景下有實際的資本節省含義。

3. **λ 的選擇不宜高於 0.1，λ=0.2 應避免**。Effective sample 縮減的效應在 λ=0.2 已超過臨界點——特別是在 VIX High 政體的稀少樣本下，集中加權讓尾端估計變得不穩定，導致 Kupiec 和 ES 同時失守。

4. **QQQ 場景下不宜用 Student-t**。QQQ 的左尾不對稱性在 2019–2026 OOS 中明顯，固定對稱厚尾假設的 Student-t 無法捕捉這個特性，Kupiec p=0.0002 是強烈的 mis-specification 信號。在科技 ETF 或類似成分集中的資產上，非參數方法（HistSim、RWC）表現出一致優勢。

---

## 限制與穩健性

**樣本限制**：OOS 期間 2019–2026 包含數個異常事件（COVID、Meme stock、升息、AI 行情），七年樣本足夠做模型比較，但若要推斷不同宏觀政體的長期表現，仍需更長的 out-of-sample 窗口。

**VIX 作為 regime indicator 的限制**：本實驗採用 VIX 三分位政體（Low/Medium/High），這是一個粗糙的 state variable。VIX 反映的是 SPY 的隱含波動率，對 QQQ 和 0050.TW 的 regime 代表性有一定偏誤——特別是 0050.TW 在台灣本地事件（如 2024 選舉期間的波動）時，VIX 的代表性較低。

**Conformal 的 marginal coverage 性質**：RWC 的理論保證是邊際覆蓋率（marginal coverage），而非 conditional coverage。Kupiec 和 CC 測試都是有限樣本下的近似，在 VIX High 政體的 349 天子樣本中，統計檢定力（power）相對受限。

**Look-ahead 確認**：本實驗的 VaR 估計在每個預測日使用前一日收盤前可取得的 VIX 和歷史殘差，無 lookahead；模型重估每 63 日一次，同樣使用當前日期之前的數據。

**ES 測試的局限**：ES 充分性檢定基於 Acerbi-Szekely (2014) 方法，在尾端樣本數少（特別是 99% VaR 的 violation 次數在 15–38 之間）時，檢定功效有限。ES PASS 不排除 ES mis-specification，只是在現有樣本下無法統計拒絕。

---

## 結論

K893 的 OOS 驗證（2019–2026，三資產）給出一個清晰但有條件的答案：

**RWC λ=0.05 是 HistSim 的 useful refinement，不是 paradigm shift。**

它在三個資產上都通過 99% VaR 的 Trinity 門檻，同時把 interval 緊縮 1.4–4.4%。這個特性來自 VIX 政體的溫和加權——足夠在 Medium 政體（佔 OOS 58%）做有效的 state conditioning，但不會讓 High 政體的稀少樣本成為瓶頸。

λ=0.2 的教訓是「過度集中的代價」：interval 收緊效果反而變差（因為 extreme 日的不穩定估計），且覆蓋率在 SPY 和 0050.TW 同步失守。λ 的選擇核心問題在於 effective sample 的下界在哪裡——一旦超過，加權集中的收益就會被估計不穩定性完全吞噬。

HistSim rolling-500 仍然是最穩健的無調參選項。三資產 99% Trinity 全部通過，在高 VIX 政體下的 0.57% 違規率顯示它在極端市場中偏保守，但保守本身在下尾風險管理中不是缺點。

下一步研究方向：(a) 動態 λ 選擇（以 KL divergence 或 effective-N 指標在線更新 λ）；(b) 多個 state variable 的 RWC 延伸（除 VIX 外加入 term structure、SKEW index）；(c) 更細緻的 VIX 政體分割（五分位或連續加權）；(d) 在期貨市場（TX 台指期）測試 RWC 的日內適用性。

---

*本文基於實驗 K893（腳本：`experiments/k893/k893_regime_conformal_var.py`，結果：`experiments/k893/k893_regime_conformal_var_results.json`）。數據來源：yfinance，OOS 期間 2019-01-02 至 2026-04-02，SPY/QQQ 各 1823/1822 個 OOS 觀測值，0050.TW 1697 個觀測值。圖表由 `experiments/k893/make_charts.py` 生成，數字與 results.json 逐項對應。*
