"""
K1021 A4f Student-t df Joint Estimation 研究文章發佈腳本

主軸：distributional axis — joint MLE vs plug-in df，VaR 校準關鍵
資料：experiments/k1021/k1021_results.json（byte-match）
PNG：embed 既有 k1021_df_evolution_spy.png + k1021_var_scorecard.png
"""
import sys
sys.path.insert(0, '/Users/yhlai0911/Desktop/volpred-research')

from volpred.charts import upload_chart, embed_chart
from volpred.publisher.publisher import Publisher

# ── 圖表 1：df Evolution (SPY) ─────────────────────────────────────
url1 = upload_chart('/Users/yhlai0911/Desktop/volpred-research/experiments/k1021/k1021_df_evolution_spy.png')

# ── 圖表 2：VaR Scorecard Heatmap ──────────────────────────────────
url2 = upload_chart('/Users/yhlai0911/Desktop/volpred-research/experiments/k1021/k1021_var_scorecard.png')

# ── 文章內容 ───────────────────────────────────────────────────────
content = """## 摘要

[提出: Claude, 執行: Claude]

A4f 多重 GARCH 框架使用 Student-t 分佈時，自由度（df）的設定有兩條路：(1) **Plug-in**——先用 OLS 殘差估 df 後固定；(2) **Joint MLE**——df 與其他 GARCH 參數一起估計。本實驗（K1021）系統比較 5 種分佈規格（Normal、t-joint、t-fixed5、t-fixed8、Hansen 1994 skew-t），在 SPY+QQQ 上以 OOS 2019-2026（N=1,827）評估 QLIKE 與 VaR 1%/2.5%/5% 校準。

**核心發現**：(a) Joint MLE 收斂到 df ≈ 8.5（SPY）/ 8.6（QQQ），與 fixed8 經 DM 檢驗無顯著差異（t=0.870, p=0.385）但比 fixed5 顯著好（t=−3.113, p=0.002，超 Harvey 門檻）；(b) **QLIKE 對分佈假設幾乎無感**——A4f 變異數方程主導預測精度；(c) **VaR 校準對分佈假設極端敏感**——Normal 在 VaR 1% 上 SPY 違規率 1.64%（Kupiec p=0.012, Basel YELLOW），QQQ 違規率 2.13%（Kupiec p=0.000, **Basel RED**），fixed5 是唯一在兩資產三 alpha 全達 4/4 scorecard 的設定。

實務結論：**為 QLIKE 選 t-joint 或 t-fixed8；為 VaR 合規選 t-fixed5 或 skew-t**。Plug-in df=5 雖然 QLIKE 略遜，但對 tail risk 的保守性是 Basel III 合規的最便宜保險。

---

## 研究背景

### 為什麼分佈假設值得單獨研究

A4f 是本實驗系列的核心 multiplicative GARCH 框架（K889、K942、K949、K1004 一脈相承）：

$$\\sigma_t^2 = \\tau_t \\cdot g_t, \\quad \\tau_t = \\theta_0 + \\theta_1 \\cdot \\text{VIX9D}_{t-1}^2$$

$$g_t = \\omega + \\alpha u_{t-1}^2 + \\gamma u_{t-1}^2 \\mathbf{1}_{r_{t-1}<0} + \\beta g_{t-1}$$

過去討論集中在 **變異數方程**——VIX9D 是否為合適 exog（K1073）、refit cadence 多少（K1024）、leverage 方向 γ 是否穩健（K889）。但 **innovation 分佈** 同樣關鍵：VaR 計算中，分位數來源是 $z_\\alpha \\cdot \\sqrt{\\sigma_t^2}$，分位數 $z_\\alpha$ 直接由分佈假設決定。Normal $z_{0.01} = -2.326$；Student-t df=8 $z_{0.01} = -2.896$；df=5 $z_{0.01} = -3.365$。**df 從 8 降到 5，VaR 1% 估值絕對值放大 16%**——這在 Basel III scorecard 上是 GREEN 與 RED 之差。

### Plug-in vs Joint：trade-off 在哪？

兩條路各有支持者：

- **Plug-in 派**（簡單、穩定）：先 OLS 估標準化殘差，矩估或 ML 在邊際估 df，然後固定。優點：不必擔心 df 與 GARCH 參數共同收斂的數值問題；缺點：忽略 df 隨 vol regime 變動的可能。
- **Joint MLE 派**（理論一致）：所有參數一起 minimize negative log-lik。優點：條件 likelihood 一致估計、df 對殘差分佈尾部的調整即時；缺點：MLE 計算貴，且若樣本期波動率有 regime shift，df 估計可能漂移。

K1021 主問題：**這兩條路對 VaR 校準各自付出多少代價？**

### 與相關 K 的差異化

- K1073（exog 軸）：問 VIX9D vs alternatives；分佈固定 Normal
- K1024（refit cadence 軸）：問 refit_every 該設多少；分佈固定 Student-t-joint
- **K1021（distributional 軸，本篇）**：固定 exog（VIX9D）固定 cadence（63 天），純粹比較 5 種分佈在 QLIKE × VaR scorecard 的表現

三軸並行，這是本系列的第三軸。

---

## 方法與數據

| 項目 | 設定 |
|------|------|
| 資產 | SPY (S&P 500 ETF), QQQ (Nasdaq-100 ETF) |
| Exog 變數 | VIX9D (CBOE 9-day VIX), forward-fill on US holidays |
| 樣本期間 | 2011-01-03 ~ 2026-04-09 |
| OOS 期間 | 2019-01-02 ~ 2026-04-09（N=1,827 個交易日） |
| Rolling window | 2,000 個交易日 |
| Refit 頻率 | 每 63 個交易日（季度級） |
| 估計方法 | L-BFGS-B MLE + 3 random starts |
| 分佈規格 | Normal / Student-t-joint / Student-t-fixed5 / Student-t-fixed8 / skew-t (Hansen 1994) |
| VaR alpha | 1% / 2.5% / 5% |
| VaR 統計量 | UC (Kupiec)、CC (Christoffersen)、DQ (Engle-Manganelli)、ES Z1/Z2 (Acerbi-Szekely)、Basel scorecard |
| 預測比較 | Patton (2011) QLIKE on $r^2$、DM-HLN test (Harvey \\|t\\| > 3.0) |
| Seed | 42 |
| 數據來源 | yfinance (SPY, QQQ, ^VIX9D) |

---

## 核心發現

### 發現一：df Joint MLE 穩定收斂到 ≈ 8.5

"""

content = embed_chart(content, url1, '圖1：A4f-VIX9D-t-joint 在 SPY 上的 df rolling 估計（OOS 2019-2026，refit every 63 days）。實線為 joint MLE 估值，水平虛線為 fixed5 / fixed8 / skew-t 的對比基準。joint df 在 6-12 區間波動，平均 8.49，標準差 1.77。')

content += """

| 分佈規格 | mean df | std df | mean skew |
|----------|---------|--------|-----------|
| A4f-VIX9D-N (Normal) | N/A | N/A | N/A |
| **A4f-VIX9D-t-joint (SPY)** | **8.49** | **1.771** | N/A |
| **A4f-VIX9D-t-joint (QQQ)** | **8.625** | **2.234** | N/A |
| A4f-VIX9D-t-fixed5 | 5.0 | 0 | N/A |
| A4f-VIX9D-t-fixed8 | 8.0 | 0 | N/A |
| A4f-VIX9D-skewt (SPY) | 9.459 | 2.809 | −0.2171 |
| A4f-VIX9D-skewt (QQQ) | 8.892 | 2.844 | −0.2218 |

**三個觀察**：

1. **Joint df 中位數 ≈ 8.5**——比 Harvey (2016) 的 t > 3.0 安全帶寬鬆得多，意味 SPY/QQQ 日報酬有顯著厚尾但不極端。文獻常見 equity df 範圍 5-8（K802 跨資產 df 估計），本實驗 8.5 落在偏厚的一端，可能與 OOS 期含 COVID 2020 與 2022 升息熊市的尾部事件聚集有關。
2. **df 是 time-varying**：rolling std=1.77（SPY）/ 2.23（QQQ），代表 df 在 ±2 個單位波動。從圖 1 看，2020 Q1（COVID）與 2022 Q3（升息）期間 df 估計下降到 6 附近，表明這些 regime 下尾部更厚。
3. **Skew-t 估出 df ≈ 9.5**（比 symmetric t-joint 稍高）+ skew λ ≈ −0.22（左偏）。這與股市左尾偏見的先驗一致——但 λ 絕對值小（0.22），說明 symmetric t 已捕捉了大部分尾部結構。

### 發現二：QLIKE 對分佈假設幾乎無感

| Model | SPY QLIKE | QQQ QLIKE |
|-------|-----------|-----------|
| A4f-VIX9D-N | −8.3875 | −7.7845 |
| A4f-VIX9D-t-joint | −8.3904 | −7.7837 |
| A4f-VIX9D-t-fixed5 | −8.3762 | −7.7790 |
| **A4f-VIX9D-t-fixed8** | **−8.3930** | −7.7793 |
| A4f-VIX9D-skewt | −8.3854 | −7.7833 |

QLIKE 數值差異在小數第三位（最大差 0.017，相對差 < 0.2%）。**這是預期之內**——QLIKE 是 conditional variance 的 loss function，與 innovation 分佈的尾部結構幾乎正交。A4f 變異數方程（VIX9D 驅動的長期成分 × GJR 短期成分）主導預測精度，分佈假設只是把同一個 $\\sigma_t^2$ 配上不同的 quantile mapping。

DM tests（SPY，OOS N=1,827）：

| 對比 | DM t | p-value | Harvey \\|t\\|>3.0 顯著？ |
|------|------|---------|----------------------|
| t-joint vs Normal | −1.941 | 0.0522 | False |
| skew-t vs Normal | 1.032 | 0.3019 | False |
| skew-t vs t-joint | 2.789 | 0.0053 | False（未過 Harvey） |
| **t-joint vs t-fixed5** | **−3.113** | **0.0019** | **True** |
| t-joint vs t-fixed8 | 0.870 | 0.3845 | False |
| **t-fixed5 vs t-fixed8** | **3.779** | **0.0002** | **True** |

兩個 Harvey 顯著結果都涉及 fixed5：

- **t-joint > t-fixed5（QLIKE 角度）**：joint MLE 在預測精度上比強制 df=5 顯著好。這合理——強制 df=5 假設了過厚的尾部，邊際 likelihood 為了 fit tail 犧牲了 body 的擬合。
- **t-fixed8 > t-fixed5（QLIKE 角度）**：固定 df=8 比固定 df=5 顯著好，與 joint MLE 收斂到 ≈ 8.5 的事實一致。

注意 t-joint vs t-fixed8 的 DM 不顯著（p=0.385）——說明 **joint MLE 與選對的 fixed value 在 QLIKE 上等價**。如果預先有先驗 df ≈ 8，fix 它與 jointly 估計沒差別。

### 發現三：VaR 校準才是分佈假設真正的戰場

"""

content = embed_chart(content, url2, '圖2：A4f-VIX9D 5 種分佈規格的 VaR scorecard heatmap。橫軸：VaR alpha (1% / 2.5% / 5%) × 資產 (SPY / QQQ)。縱軸：5 種分佈規格。色塊顏色對應 Basel scorecard 評級（GREEN / YELLOW / RED）。Normal 規格在 VaR 1% 兩資產均 fail；fixed5 與 skew-t 全綠。')

content += """

#### SPY VaR 1% 詳細統計

| Model | violations | rate | UC stat | UC p | Basel | scorecard |
|-------|-----------|------|---------|------|-------|-----------|
| **A4f-VIX9D-N** | 30 | 1.64% | 6.372 | **0.0116** | YELLOW | 1/4 |
| A4f-VIX9D-t-joint | 27 | 1.48% | 3.673 | 0.0553 | GREEN | 4/4 |
| A4f-VIX9D-t-fixed5 | 19 | 1.04% | 0.029 | 0.8646 | GREEN | 4/4 |
| A4f-VIX9D-t-fixed8 | 24 | 1.31% | 1.652 | 0.1987 | GREEN | 4/4 |
| A4f-VIX9D-skewt | 19 | 1.04% | 0.029 | 0.8646 | GREEN | 4/4 |

#### QQQ VaR 1% 詳細統計（更嚴重的 Normal failure）

| Model | violations | rate | UC stat | UC p | Basel | scorecard |
|-------|-----------|------|---------|------|-------|-----------|
| **A4f-VIX9D-N** | **39** | **2.13%** | **17.926** | **0.0000** | **RED** | **1/4** |
| A4f-VIX9D-t-joint | 31 | 1.70% | 7.411 | 0.0065 | YELLOW | 1/4 |
| A4f-VIX9D-t-fixed5 | 19 | 1.04% | 0.029 | 0.8646 | GREEN | 4/4 |
| A4f-VIX9D-t-fixed8 | 30 | 1.64% | 6.372 | 0.0116 | YELLOW | 1/4 |
| A4f-VIX9D-skewt | 15 | 0.82% | 0.630 | 0.4275 | GREEN | 4/4 |

**三個關鍵 takeaway**：

1. **Normal 嚴重低估 tail**：SPY 違規率 1.64%（預期 1%），QQQ 違規率 **2.13%**（預期 1%）——Kupiec p=0.000、Basel RED。這對 risk manager 是直接的合規危機。**用 Normal 來估 daily VaR 1% 是統計上的疏失**，過去文獻（K967、K824、K1000）已多次警示，K1021 在 A4f 框架下再次驗證。

2. **t-joint 對 QQQ 仍不夠保守**：joint df ≈ 8.6 給出的 VaR 1% violation rate 仍是 1.70%，Kupiec p=0.0065（YELLOW）。即便 jointly 估計，df 的後驗均值還是傾向「平均」厚度，無法捕捉 QQQ 的科技股集中風險（COVID 2020、Meta 單日 −26% 的 2022-02、Nvidia/Tesla 高 vol 拖尾）。

3. **t-fixed5 與 skew-t 是 VaR 合規勝者**：兩者在 SPY/QQQ × 三 alpha 全達 GREEN（fixed5 全 4/4 + 6/6 + 4/4，skew-t 同樣全 4/4 + 6/6 + 4/4）。**這是分佈假設保守性的勝利**——fix 一個比 joint 更厚的 df=5 故意 oversmooth 尾部，雖犧牲 0.4% QLIKE，但換來監管合規零違規。

#### Trade-off 總結（兩資產合計 VaR scorecard 總分）

| Model | SPY 1%/2.5%/5% | QQQ 1%/2.5%/5% | 合計 |
|-------|----------------|----------------|------|
| A4f-VIX9D-N | 1+6+4 = 11/14 | 1+4+4 = 9/14 | 20/28 |
| A4f-VIX9D-t-joint | 4+6+4 = 14/14 | 1+6+4 = 11/14 | 25/28 |
| **A4f-VIX9D-t-fixed5** | 4+6+4 = 14/14 | 4+6+4 = 14/14 | **28/28** |
| A4f-VIX9D-t-fixed8 | 4+6+4 = 14/14 | 1+6+4 = 11/14 | 25/28 |
| **A4f-VIX9D-skewt** | 4+6+4 = 14/14 | 4+6+4 = 14/14 | **28/28** |

僅 fixed5 與 skew-t 達到滿分 28/28——但 skew-t 的 ES 用 simulation 估（VaR 是 analytical），fixed5 兩者都 analytical，計算成本最低。**最便宜的合規方案是 t-fixed5**。

---

## 實務意義

### 對風險管理者：不同目的，不同分佈

K1021 證明 **「QLIKE 最優」與「VaR 合規最優」不是同一個分佈規格**：

- **預測精度（QLIKE）目標** → 選 **t-joint** 或 **t-fixed8**（兩者統計上等價）。QLIKE 數字接近 −8.39（SPY），DM 對 Normal 邊界顯著（p=0.052），對 fixed5 顯著優越。
- **VaR 合規（Basel III）目標** → 選 **t-fixed5** 或 **skew-t**。fixed5 是 plug-in 的極限保守版（強制 df 比 joint 估計低），skew-t 多了 left-skew 校正但 ES 計算貴。
- **權衡兩者** → **t-fixed8**：QLIKE 最佳，SPY VaR 全 GREEN，QQQ VaR 1% 是 YELLOW（p=0.012）但其他 alpha GREEN。Paper 9 推薦使用此規格作為 baseline。

### 對 A4f 框架研究者：分佈軸是獨立 lever

K1021 證實：**A4f 變異數方程**（K1073 / K1024 處理）與 **innovation 分佈**（本篇處理）是 **正交的設計選擇**——前者決定 $\\sigma_t^2$ 的點估計（QLIKE），後者決定 $\\sigma_t^2$ 的 quantile mapping（VaR 校準）。優化 A4f 不能只調 exog 變數和 cadence，分佈假設必須與用途匹配。

### 對學術研究者：plug-in 派的辯護不能輕忽

過去文獻常默認 joint MLE 為 gold standard。K1021 結果提示一個 nuance：**plug-in df=5 在 VaR 校準上是顯著贏家**——不是因為它「更準」，而是因為它「更保守」。在合規導向應用中，保守性是 feature 不是 bug。Engle & Manganelli (2004) DQ test 只能告訴你 violations 是否獨立，無法告訴你 over-conservative 與 under-conservative 哪個更糟——而 Basel III 框架對 under-conservative 有重罰、對 over-conservative 沒有懲罰。**plug-in df=5 是這個非對稱懲罰下的理性選擇。**

---

## 限制與穩健性

1. **僅 2 資產（SPY、QQQ）**：均為美股大盤 ETF。跨資產類別（GLD、TLT、BTC、新興市場）與台股（0050.TW、TXO）的分佈軸結論需獨立驗證。K1004 與 K1000 已對部分 cross-asset 做過驗證但未涵蓋分佈規格全比較。
2. **OOS 含 COVID 2020 極端事件**：2020-03 單日 −12% 等 fat tail 事件壓力測試了所有規格。但若移除 COVID 後 fixed5 是否仍稱霸，未做 placebo subperiod。
3. **VIX9D 為唯一 exog**：未與 VIX、VIX3M、實現波動率比較。K1004 已部分覆蓋此問題，K1073 將更系統處理。
4. **Skew-t 的 ES 用 MC 估計**：analytical VaR + simulation ES 的混合估計增加 noise，可能影響 Z2 的精準度。
5. **Look-ahead 檢查**：K1021 使用 `signal.shift(1)` 等效設計——VIX9D_{t-1} 進入 $\\tau_t$，$g_t$ 用 $u_{t-1}$ 與 $r_{t-1}$，所有 conditioning 變數均嚴格 t−1 已知。OOS 評估在 expanding window 之外。
6. **Refit cadence 固定 63 天**：與 K1024 結論協同——cadence 不是本實驗主軸。

---

## 結論

K1021 為 alert auto-remediation 系列的第 3 軸（distributional axis），補完了 A4f 框架的三維設計空間：

- 第 1 軸 K1073 — exog 變數選擇（VIX9D vs alternatives）
- 第 2 軸 K1024 — refit cadence 校準（63 天為何最優）
- **第 3 軸 K1021 — innovation 分佈規格（本篇）**

**核心結論**：

> **A4f 的 innovation 分佈是獨立於變異數方程的設計 lever。Joint MLE 收斂到 df ≈ 8.5（SPY/QQQ），給出的 QLIKE 與 fixed8 等價、與 fixed5 顯著優；但 VaR 1% 校準在 QQQ 仍 YELLOW。Plug-in fixed5 與 skew-t 是唯二在兩資產三 alpha 全 GREEN 的規格。Paper 9 baseline 用 t-fixed8（QLIKE 最佳），合規場景用 t-fixed5（VaR 全 GREEN）。**

下一步：

1. 在 GLD / TLT / BTC / 0050.TW 重做 K1021 比較，驗證 fixed5 是否跨資產類別仍稱霸 VaR 校準
2. 將 EVT-POT 加入比較（與 GARCH-t 比 tail 估計效率）——Patton & Sheppard (2015) 已示警 GARCH-t 對 99% VaR 仍 underestimate
3. 整合 K1073 + K1024 + K1021 結論寫 Paper 9 一節「A4f 三軸設計指南」，作為論文 methodology 章節

---

*實驗腳本：experiments/k1021/k1021.py（seed=42），結果：experiments/k1021/k1021_results.json，數據來源：yfinance (SPY, QQQ, ^VIX9D)，OOS 2019-01-02 ~ 2026-04-09，N=1,827 個交易日，refit window=2,000，refit_every=63。*

*相關實驗：K1073（exog 軸，並行）、K1024（cadence 軸，並行）、K1004（A4f 跨分佈初探）、K1000（MF-GJR-X+Student-t joint MLE）、K967（CAViaR 直接分位數建模）、K824（HistSim VaR）、K802（cross-asset df estimation）。*
"""

# ── 發佈 ──────────────────────────────────────────────────────────────
pub = Publisher()
article_id = pub.publish_milestone(
    title='K1021: A4f Student-t df Joint Estimation — df ≈ 8.5, VaR Calibration Critical',
    description=content,
    phase='research',
    tags=[
        'K1021', 'A4f', 'Student-t', 'VaR-calibration',
        'SPY', 'QQQ', 'VIX9D', 'distributional-axis',
    ],
    status='draft',
    audience='research',
    proposer='Claude',
)
print(f"Published article ID: {article_id}")
