"""
K949 Cross-Market MF-GJR 研究文章發佈腳本
"""
import sys
sys.path.insert(0, '/Users/yhlai0911/Desktop/volpred-research')

from volpred.charts import (
    generate_bar_chart, generate_grouped_bar_chart, generate_line_chart,
    upload_chart, embed_chart
)
from volpred.publisher.publisher import Publisher

# ── 圖表 1：各市場 QLIKE 比較（三模型） ──────────────────────────────
markets = ['SPY', 'FEZ', 'EWG', 'EWJ', 'EWU']

# QLIKE 數值
qlike_garch = [0.7606, 1.2510, 1.2491, 0.9806, 0.9648]
qlike_gjr   = [0.7371, 1.2445, 1.2368, 0.9739, 0.9575]
qlike_mf    = [0.6551, 1.1898, 1.1857, 0.9287, 0.8840]

path1 = generate_grouped_bar_chart(
    labels=markets,
    group_data={
        'GARCH(1,1)': qlike_garch,
        'GJR(1,1,1)': qlike_gjr,
        'MF-GJR(VIX)': qlike_mf,
    },
    title='K949: 各市場 QLIKE（越低越好）— MF-GJR(VIX) 跨市場全勝',
    ylabel='QLIKE (on r²)',
    filename='k949_qlike_comparison',
    figsize=(13, 6),
)
url1 = upload_chart(path1)

# ── 圖表 2：VIX Elasticity (θ₁) 跨市場 ──────────────────────────────
theta1_values = [1.794, 2.278, 2.143, 1.977, 2.285]

path2 = generate_bar_chart(
    labels=markets,
    values=theta1_values,
    title='K949: VIX Elasticity θ₁ 跨市場（mean=2.10, std=0.19）',
    ylabel='θ₁（VIX 彈性係數）',
    filename='k949_theta1',
    figsize=(10, 6),
    highlight_best=False,
)
url2 = upload_chart(path2)

# ── 圖表 3：DM t-statistic 與 Harvey 門檻 ──────────────────────────
dm_t = [3.44, 3.84, 3.48, 4.22, 2.40]
sig  = ['✓ 顯著', '✓ 顯著', '✓ 顯著', '✓ 顯著', '✗ 邊界']

path3 = generate_bar_chart(
    labels=markets,
    values=dm_t,
    title='K949: DM t-statistic (Harvey |t|>3.0 門檻)  — 4/5 市場顯著',
    ylabel='DM |t-statistic|',
    filename='k949_dm_tstat',
    figsize=(10, 6),
    highlight_best=False,
)
url3 = upload_chart(path3)

# ── 文章內容 ──────────────────────────────────────────────────────────
content = """## 摘要

[提出: Claude, 執行: Claude]

本實驗（K949）將 MF-GJR(VIX) 模型從美國市場延伸至全球五大股市：SPY（美國）、FEZ（歐元區）、EWG（德國）、EWJ（日本）、EWU（英國）。結果顯示，VIX 在 **4/5 個市場**達到 Harvey $|t|>3.0$ 顯著門檻，且 VIX 彈性係數 $\\theta_1$ 跨市場高度穩定（mean=2.10, std=0.19）。這表明 **VIX 是真正的全球風險因子**，而非僅反映美國本土市場情緒。

---

## 研究背景

### 前序實驗

- **K889**：MF-GJR(VIX) 在 SPY 上 DM t=−4.42，首次確認 VIX 對美股波動率預測的長期增益
- **K942**：13/13 子樣本滾動 OOS 全勝，跨越不同市場 regime（金融危機後/量化寬鬆/COVID/升息）
- **K916**：跨資產測試確認股票型 ETF 有效，加密貨幣市場失敗（VIX 不足以捕捉 crypto regime）

關鍵問題：**VIX 是美國的本土指標，為什麼它對歐洲和日本市場也有預測力？**

### MF-GJR(VIX) 模型架構

MF-GJR 將條件波動率分解為長期成分與短期成分的乘積：

$$\\sigma_t^2 = \\tau_t \\times g_t$$

其中長期成分由 VIX 驅動：

$$\\tau_t = \\exp(\\theta_0 + \\theta_1 \\log \\text{VIX}_{t-1})$$

短期成分 $g_t$ 遵循 GJR-GARCH 動態（捕捉槓桿效應）：

$$g_t = (1 - \\alpha - \\gamma/2 - \\beta) + \\alpha \\frac{r_{t-1}^2}{\\tau_{t-1}} + \\gamma \\frac{r_{t-1}^2 \\mathbf{1}_{r_{t-1}<0}}{\\tau_{t-1}} + \\beta g_{t-1}$$

參數 $\\theta_1$ 即為 **VIX 彈性係數**：$\\theta_1 > 0$ 表示 VIX 上升時長期波動率水準上移，體現 VIX 的全球恐慌傳導機制。

---

## 方法與數據

| 項目 | 設定 |
|------|------|
| 資產 | SPY (US), FEZ (Eurozone STOXX 50), EWG (Germany), EWJ (Japan), EWU (UK) |
| VIX | CBOE ^VIX，非美市場假日使用 forward-fill |
| 訓練窗口 | 2000 個交易日（rolling） |
| Refit 頻率 | 每 21 個交易日（約 1 個月） |
| OOS 期間 | 2016-01-01 ~ 2025-12-31（2,513 個交易日） |
| 評估指標 | QLIKE on $r^2$（Patton 2011 proxy-robust）、Spearman $\\rho$、DM test |
| 顯著性門檻 | Harvey $|t|>3.0$ |
| 數據來源 | yfinance |

---

## 核心發現

### 發現一：QLIKE — MF-GJR(VIX) 跨市場全勝

"""

content = embed_chart(content, url1, '圖1：各市場三模型 QLIKE 比較（越低越好）。MF-GJR(VIX) 在所有五個市場均優於 GARCH 和 GJR。')

content += """

| 市場 | GARCH QLIKE | GJR QLIKE | MF-GJR QLIKE | 改善幅度（vs GJR） |
|------|------------|-----------|--------------|------------------|
| SPY（美國） | 0.761 | 0.737 | **0.655** | −11.1% |
| FEZ（歐元區） | 1.251 | 1.245 | **1.190** | −4.4% |
| EWG（德國） | 1.249 | 1.237 | **1.186** | −4.1% |
| EWJ（日本） | 0.981 | 0.974 | **0.929** | −4.6% |
| EWU（英國） | 0.965 | 0.958 | **0.884** | −7.7% |

SPY 的 QLIKE 改善最大（−11.1%），一方面因為 VIX 是基於美股選擇權構建的，對美市具有天然優勢；另一方面也確認了 VIX 對歐日英市場的跨境傳導能力（4-8% 改善幅度，非美市場並非偶然）。

### 發現二：DM 統計量 — 4/5 市場 Harvey 顯著

"""

content = embed_chart(content, url3, '圖2：各市場 DM |t-statistic|。紅色虛線為 Harvey (2016) |t|>3.0 門檻。EWU（英國）以 t=2.40 未達門檻，屬於邊界案例。')

content += """

| 市場 | DM |t| (Harvey) | Harvey 顯著 |
|------|-----------------|------------|
| SPY | 3.44 | ✓ |
| FEZ | 3.84 | ✓ |
| EWG | 3.48 | ✓ |
| EWJ | **4.22** | ✓ |
| EWU | 2.40 | ✗（邊界） |

**日本（EWJ）的 DM t=4.22 是五個市場中最高的。** 這可能反映兩個機制：(1) 日本股市對美國風險情緒的高敏感度（US-Japan 財務整合），(2) 日圓避險需求在全球不確定性上升時集中出現，形成 VIX 與 EWJ 波動率之間更強的非線性連動。

英國（EWU）的 t=2.40 未達 Harvey 門檻，但 QLIKE 改善幅度（7.7%）仍屬全市場第二高。可能原因是英國市場受 Brexit 後的特殊結構因素干擾，或樣本期間英國本地事件的不確定性在 VIX 之外製造了額外的波動率（英磅匯率、BoE 利率路徑等）。

### 發現三：VIX Elasticity θ₁ 跨市場穩定

"""

content = embed_chart(content, url2, '圖3：VIX 彈性係數 θ₁ 跨市場分佈。注意非美市場的 θ₁ 普遍高於 SPY（1.794），這意味著 VIX 對非美市場的長期波動率驅動力甚至更強。')

content += """

| 市場 | $\\theta_1$（VIX 彈性係數） |
|------|------------------------|
| SPY | 1.794 |
| FEZ | 2.278 |
| EWG | 2.143 |
| EWJ | 1.977 |
| EWU | 2.285 |
| **Mean** | **2.096** |
| **Std** | **0.188** |

兩個關鍵觀察：

1. **方向一致**：所有市場 $\\theta_1 > 0$，VIX 對長期波動率的驅動方向無一例外
2. **非美市場 $\\theta_1$ 更高**：FEZ/EWG/EWU 的彈性係數（2.1-2.3）高於 SPY（1.794）。解讀：美股本身就是 VIX 的定義域，部分波動率已在短期成分 $g_t$ 被 GJR 項捕捉；非美市場則更依賴 VIX 的「全球恐慌溫度計」角色——一旦 VIX 上升，長期波動率水準上移的幅度更大

這個 $\\theta_1$ 的跨市場穩定性（std=0.19，約為 mean 的 9%）本身就是強有力的證據，說明 VIX 信號不是噪音，而是捕捉了真實的全球風險傳導機制。

---

## 模型估計關鍵參數

| 市場 | $\\omega_g$ | $\\alpha$ | $\\gamma$（槓桿） | $\\beta$ | $\\theta_0$ | $\\theta_1$ |
|------|-----------|---------|----------------|---------|-----------|-----------|
| SPY | 1.216 | 0.005 | 0.344 | 0.823 | −0.030 | 1.794 |
| FEZ | 0.255 | 0.013 | 0.072 | 0.914 | −5.000 | 2.278 |
| EWG | 0.377 | 0.013 | 0.047 | 0.938 | −5.000 | 2.143 |
| EWJ | 0.480 | 0.026 | 0.011 | 0.956 | −5.000 | 1.977 |
| EWU | 0.171 | 0.024 | 0.053 | 0.890 | −5.000 | 2.285 |

注意 SPY 的槓桿效應 $\\gamma=0.344$ 遠高於其他市場（0.01-0.07），這與美股的非對稱波動特性（壞消息 → 波動率爆炸）一致。歐日英 ETF 的 $\\gamma$ 較低，部分原因是它們在美國交易所計算的 close-to-close return 本身已平滑了部分本地市場微結構。

---

## 實務意義

### 對風險管理者

VIX 不只是美股的恐懼指數——它可以被整合進全球投資組合的波動率預測模型。在構建多市場 VaR/ES 模型時，**以 VIX 驅動各市場長期波動率成分** 是統計上有保證的做法（4/5 市場 Harvey 顯著），比各市場獨立使用本地 GARCH 更有效。

### 對模型選擇

MF-GJR(VIX) 對非美 ETF 的改善幅度（4-8%）雖小於美股（11%），但 DM 統計量仍高度顯著，說明這是**真實的統計改善**而非偶然差異。在模型選擇時，應考慮 MF-GJR(VIX) 作為所有股票型 ETF 的標準基線。

### 局限（必須誠實說明）

- **ETF vs 本地指數**：FEZ/EWG/EWJ/EWU 在美國交易所上市，其 return 計算包含了匯率影響和美國市場微結構。更嚴格的測試需要使用 STOXX50、DAX、TOPIX、FTSE100 本地指數及對應的 VSTOXX、JNIV 等本地隱含波動率
- **COVID 效應**：OOS 期間（2016-2025）包含 2020 年 COVID 危機，全球市場相關性短暫接近 1。這可能放大了 VIX 對非美市場的表觀預測力
- **匯率未控制**：美元強弱會同時影響 VIX（risk-off = USD 強）和非美 ETF（USD 計價報酬受匯率壓縮）。未來應加入 USD index 作為控制變數

---

## 結論

K949 提供了 **VIX 作為全球風險因子** 的首個跨五市場系統性驗證。

核心結論：

> **VIX 是全球風險因子。** MF-GJR(VIX) 在 4/5 個國際市場（美國、歐元區、德國、日本）達到 Harvey $|t|>3.0$，$\\theta_1$ 跨市場穩定（2.10 ± 0.19），非美市場彈性係數甚至更高（2.1-2.3 vs SPY 1.794）。

這個發現對 Paper 7「VIX Sufficiency」提供了跨境驗證——VIX 的預測力不僅在美股多個子樣本中穩健（K942），在地理上也具有全球性。未來研究方向包括：

1. 以本地指數（DAX, TOPIX, FTSE100）取代 ETF，使用 VSTOXX/JNIV 取代 VIX，測試在「剝離美國因子暴露」後結果是否維持
2. 加入 VVIX（VIX of VIX）作為第二長期驅動變數，測試是否能捕捉 VIX regime shift 的預告信號
3. 在台灣市場（0050.TW）測試本地 VIX 替代品（TXO 隱含波動率）的效果

---

*實驗腳本: experiments/k949/k949.py，數據來源：yfinance (SPY, FEZ, EWG, EWJ, EWU, ^VIX)，OOS 2016-2025，N=2,513 交易日/市場*
"""

# ── 發佈 ──────────────────────────────────────────────────────────────
pub = Publisher()
article_id = pub.publish_milestone(
    title='K949: VIX 跨市場驗證 — 美國恐慌指數預測全球 5 大市場波動率',
    description=content,
    phase='research',
    tags=[
        '研究',
        'MF-GJR', 'GARCH', 'VIX',
        'SPY', 'FEZ', 'EWG', 'EWJ', 'EWU',
        '波動率預測', '跨市場', '全球風險因子',
        'DM test', 'QLIKE', 'Harvey',
    ],
    status='draft',
    audience='research',
    proposer='Claude',
)
print(f"Published article ID: {article_id}")
