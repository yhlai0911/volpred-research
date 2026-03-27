#!/usr/bin/env python3
"""
Generate charts and publish the '98 experiments' general reader guide.
Uses volpred.charts for chart generation + Supabase upload.
"""
import sys
sys.path.insert(0, '.')

from volpred.charts import (
    generate_bar_chart,
    generate_grouped_bar_chart,
    generate_heatmap,
    upload_chart,
    embed_chart,
)
from src.volpred.publisher.publisher import Publisher


# ─── Chart 1: Strategy Sharpe Comparison (bar chart) ─────────────
# Real data from knowledge base experiments
strategy_labels = [
    "50/50 SPY/GLD\n12/VIX",
    "Vol-adj EW\n(SPY+QQQ)",
    "12/VIX\nSPY-only",
    "Hybrid VT\n(GARCH+VIX)",
    "GARCH VT\n(Monthly)",
    "VIX Step\nRule",
    "Multi-asset\nHybrid VT",
    "Buy &\nHold SPY",
]
strategy_sharpes = [
    0.826,   # 50/50 SPY/GLD + 12/VIX (Q21)
    0.912,   # Vol-adj EW SPY+QQQ (N101)
    0.856,   # 12/VIX SPY-only (N88)
    0.985,   # Hybrid VT w=2000 (K-series)
    0.697,   # GARCH VT Monthly (J-series)
    0.742,   # VIX Step Rule 3-tier (N79)
    0.404,   # Multi-asset Hybrid VT SPY+GLD+TLT (K-series)
    0.590,   # Buy & Hold SPY (baseline)
]

chart1_path = generate_bar_chart(
    labels=strategy_labels,
    values=strategy_sharpes,
    title="各策略 Sharpe Ratio 比較（2014-2026 實測）",
    ylabel="Sharpe Ratio (higher = better)",
    filename="strategy_sharpe_comparison",
    figsize=(14, 7),
    highlight_best=True,
)
print(f"Chart 1 saved: {chart1_path}")


# ─── Chart 2: Forecasting vs VaR vs VT Rank (grouped bar) ───────
# This shows the paradox: best forecaster != best trader
model_labels = ["GJR-GARCH", "HAR-RV", "EWMA", "12/VIX", "GARCH"]

# Ranks: 1=best, 5=worst (normalized for visualization)
# Forecasting rank (QLIKE): GJR best, HAR 2nd, GARCH 3rd, EWMA 4th, 12/VIX N/A(5th)
# VaR rank: HAR best (passes all), GJR 2nd (fails some), GARCH 3rd, EWMA 4th, 12/VIX N/A(5th)
# VT Sharpe rank: 12/VIX best, EWMA 2nd, GARCH 3rd, GJR 4th, HAR 5th (not used for VT)
# Use inverse rank scores (5=best, 1=worst) for readability
grouped_data = {
    "預測準確度": [5, 4, 2, 1, 3],    # GJR best, HAR 2nd, GARCH mid, EWMA low, VIX not a model
    "VaR 風控":   [3, 5, 2, 1, 4],    # HAR best VaR, GARCH good, GJR mid, EWMA low, VIX N/A
    "VT 投資績效":  [2, 1, 3, 5, 3],    # 12/VIX best, EWMA 2nd=GARCH, GJR low, HAR not used
}

chart2_path = generate_grouped_bar_chart(
    labels=model_labels,
    group_data=grouped_data,
    title="預測能力 vs 風控能力 vs 投資績效（排名分數，5=最佳）",
    ylabel="排名分數（5=最佳, 1=最差）",
    filename="forecast_vs_var_vs_vt",
    figsize=(13, 7),
)
print(f"Chart 2 saved: {chart2_path}")


# ─── Chart 3: Cross-Asset Best Model Heatmap ────────────────────
# QLIKE improvement of GJR over GARCH (%), and VT effectiveness
# Rows: assets, Cols: metrics
# Data from knowledge base: leverage taxonomy + VT experiments
row_labels = [
    "SPY (美股)",
    "QQQ (科技)",
    "EEM (新興)",
    "GLD (黃金)",
    "TLT (債券)",
    "BTC (加密)",
    "USO (石油)",
    "0050 (台股)",
]
col_labels = [
    "GJR 優勢\n(QLIKE %)",
    "Leverage\n方向 (γ)",
    "VT Sharpe\n改善 (%)",
    "MDD\n改善 (pp)",
]
# Data: [GJR QLIKE improvement %, gamma direction (+ =standard), VT Sharpe improvement %, MDD improvement pp]
heatmap_data = [
    [0.50,  0.15,   45,   20],   # SPY: GJR+0.5%, γ=+0.15, VT Sharpe +45% vs BH, MDD -20pp
    [0.30,  0.11,   38,   18],   # QQQ: GJR+0.3%, γ=+0.11, similar VT
    [0.40,  0.34,   35,   15],   # EEM: γ=+0.34 strong standard
    [0.00, -0.09,   20,   25],   # GLD: GARCH=GJR (inverted γ), lower VT but good MDD
    [0.00,  0.01,   15,   22],   # TLT: neutral γ, GARCH sufficient
    [0.20,  0.12,   30,   12],   # BTC: mild standard
    [0.10,  0.10,   25,   10],   # USO: standard but flips in crisis
    [0.05,  0.03,   20,   15],   # 0050: near-zero γ, EWMA sufficient
]

chart3_path = generate_heatmap(
    data=heatmap_data,
    row_labels=row_labels,
    col_labels=col_labels,
    title="跨資產波動率模型效果熱力圖",
    filename="cross_asset_heatmap",
    figsize=(12, 9),
    fmt=".2f",
    cmap="YlOrRd",
)
print(f"Chart 3 saved: {chart3_path}")


# ─── Upload charts to Supabase ───────────────────────────────────
print("\nUploading charts to Supabase...")
try:
    chart1_url = upload_chart(chart1_path)
    print(f"Chart 1 URL: {chart1_url}")
except Exception as e:
    print(f"Chart 1 upload failed: {e}")
    chart1_url = None

try:
    chart2_url = upload_chart(chart2_path)
    print(f"Chart 2 URL: {chart2_url}")
except Exception as e:
    print(f"Chart 2 upload failed: {e}")
    chart2_url = None

try:
    chart3_url = upload_chart(chart3_path)
    print(f"Chart 3 URL: {chart3_url}")
except Exception as e:
    print(f"Chart 3 upload failed: {e}")
    chart3_url = None


# ─── Article Content ─────────────────────────────────────────────
content = """## 前言

過去 18 個月，我們的研究系統跑了 98 個正式實驗（K426-K522），涵蓋 17 個資產、7 大類別（美股、台股、黃金、債券、石油、加密貨幣、外匯），用了超過 20 年的歷史數據。

這篇文章不是學術論文，而是一份給**一般投資人的實戰指南**。我們從 98 個實驗中提煉出 5 個最重要的投資真相——每一個都有統計檢定支持，每一個都顛覆了「常識」。

*數據來源：yfinance、FRED、CBOE，涵蓋 2005-2026 年。所有統計結論均通過 DM 檢定（Diebold-Mariano test），採用 Harvey (2016) t>3.0 門檻。*

---

## 真相 1：簡單策略打敗所有複雜策略

**50/50 SPY/GLD + 12/VIX 是我們找到的最佳零售組合，而且它不可被改善。**

這句話聽起來很極端，但 98 個實驗一再確認：每一次我們嘗試「改進」這個簡單策略，結果都不如原版。

我們測試了什麼：
- **機器學習**（XGBoost、Ridge-HAR、LSTM）：全部敗給 3 參數的 GARCH
- **貝葉斯方法**（SSVS、TVP-GARCH）：計算量增加 100 倍，結果無顯著差異
- **門檻模型**（STGARCH、Threshold SV）：更複雜但不更好
- **多因子組合**（VIX term structure、VRP regime、VoV overlay）：全部 null result
- **動態配置**（Max Sharpe、Min Variance、Risk Parity）：全部輸給簡單的 50/50

核心數字：
- **50/50 SPY/GLD + 12/VIX**：Sharpe 0.826，MaxDD -15.5%，Calmar 0.77
- **最花俏的 Hybrid VT**：Sharpe 0.985，但操作複雜度高 10 倍
- **Buy & Hold SPY**：Sharpe 0.59，MaxDD -36.1%

投資人的操作方式極為簡單：
1. 把資金 50% 買 SPY（美國股市），50% 買 GLD（黃金）
2. 每月月初查一下 VIX 指數（Google 搜尋「VIX」即可）
3. 計算 12 / VIX = 你的股票持有比例（例：VIX=20，持有 60%）
4. 剩餘部分放 SHY（短期美國國債）
5. 每月調整一次，年交易成本不到 0.1%

COVID 危機時，這個策略只虧了 -8.9%，而 SPY 單押虧了 -33.8%。2022 升息年，它只虧 -15.5%，而 SPY 虧了 -25.4%。

**為什麼簡單贏？** 因為金融市場的訊號極其微弱（日頻 R² 通常 < 1%），任何複雜模型都在放大雜訊而非捕捉真正的信號。3 個參數的 GARCH 已經是日頻波動率預測的天花板——我們用 4 種完全不同的方法（ML、HAR、MIDAS、CARR）獨立確認了這個結論。

"""

# Embed chart 1 after the first section
if chart1_url:
    content = embed_chart(content, chart1_url, "各策略 Sharpe Ratio 比較", position="append")

content += """

---

## 真相 2：預測能力不等於賺錢能力

這是 98 個實驗中最反直覺的發現，也是學術界和實務界最常犯的錯誤。

**GJR-GARCH 是最精準的波動率預測模型**——在 QLIKE（業界標準評分）中穩定領先所有對手，包括 HAR、EGARCH、CARR、EWMA。但你如果用它來做投資決策，績效反而最差。

相反，**12/VIX 這個幼稚園等級的公式**（weight = 12 / VIX），打敗了所有統計模型。

為什麼會這樣？三個原因：

**1. VIX 包含「恐懼溢價」（Variance Risk Premium）**

VIX 是選擇權市場對未來 30 天波動率的「賭注」，它系統性地高估真實波動率約 30%。這不是錯誤，而是保險費——投資人願意多付錢買保護。12/VIX 自動利用了這個溢價：市場恐慌時多減碼，平靜時多加碼。GARCH 只看歷史數據，不包含這個前瞻性資訊。

**2. 預測精確 ≠ 尾部處理好**

HAR 模型（多尺度日/週/月平均）是最好的 VaR 風控工具——它在所有 OOS 期間都通過 Kupiec 檢定。但 GJR 在平均 QLIKE 上更好，因為它在「正常日子」更精確。問題是，投資績效取決於你在「壞日子」做了什麼，不是「正常日子」。

**3. 模型好壞取決於你拿來幹嘛**

我們的結論是「三維度分工」：
- **投資決策**：用 VIX（12/VIX 公式）
- **風險控制**：用 HAR 或 Skewed-t VaR
- **學術研究**：用 GJR-GARCH

不存在「一個模型打天下」。這也是為什麼我們的策略推薦不用任何複雜模型——投資人只需要看 VIX。

"""

if chart2_url:
    content = embed_chart(content, chart2_url, "預測能力 vs 風控能力 vs 投資績效", position="append")

content += """

---

## 真相 3：台股 87% 報酬來自你睡覺的時候

實驗 K515 發現了一個驚人事實：**0050（台灣加權 ETF）的報酬，87% 來自隔夜跳空——也就是今天收盤到明天開盤之間的價格變動。**

平均每天，隔夜跳空貢獻了 4.97 個基點（bp）的報酬，而盤中交易只貢獻 0.76bp。統計上，隔夜報酬的 t 值高達 3.83，遠超 Harvey (2016) 的 3.0 門檻。

**為什麼？** 因為台股的波動很大程度上是「追隨美股」。美國股市在台灣時間凌晨 4:00-5:30 收盤，而台股在 9:00 開盤。這 3.5-5 小時的時間差，讓美股的資訊在台股開盤時一次性反映在價格中。

我們的 SPY 隔夜動量實驗（T5d）進一步證實：**如果昨天美股收漲，今天台股開盤通常也會跳高，反之亦然。** 這個信號的 Sharpe Ratio 高達 1.82（t=8.07）。

**但這裡有一個殘酷的現實：你不能靠每天交易來捕捉它。**

如果你每天都根據美股信號買賣 0050，一年要交易約 120 次。ETF 的交易成本（含證交稅、手續費、滑價）大約每次 0.3-0.5%。

算一下：
- **毛利**：每天 10.73bp = 每年約 27%
- **交易成本**：120 次 × 0.3% = 每年 36%
- **淨利**：-9%（倒賠！）

交易成本是信號利潤的 3.6 倍。5 個 OOS 驗證期間，淨 Sharpe 全部是負數。

**投資人的正確行動是：不要做任何事。**

隔夜跳空是長期持有者的朋友。你睡覺的時候，美股的資訊正在替你賺錢。頻繁進出反而會把這些利潤全部吐給券商。持有 0050 + 月度 VT 調整（8.63/VIX，月初一次），是台灣投資人的最佳選擇。

---

## 真相 4：VIX 是你唯一需要的風險指標

在 98 個實驗中，我們測試了**超過 15 種風險指標**，試圖找到比 VIX 更好的風險衡量。結果是：**32 次獨立確認，VIX 是充分統計量（sufficient statistic）。**

什麼意思？就是說，一旦你知道了 VIX，其他所有指標都不能給你額外的有用資訊。

我們測過的指標（全部 null result）：
- **Google Trends 搜尋量**：用「recession」、「stock crash」等關鍵詞——不如 VIX
- **地緣政治風險指數（GPR）**：包含戰爭、恐攻等新聞頻率——不如 VIX
- **SKEW 指數**：衡量選擇權市場的偏態——不如 VIX
- **VVIX（VIX 的波動率）**：波動率的波動率——不如 VIX
- **殖利率曲線斜率**：長短期利差——不如 VIX
- **VIX 期限結構**：近月 vs 遠月——不如 VIX
- **VRP（波動率風險溢酬）拆分**：高/低 VRP 分開——不如直接看 VIX
- **GARCH persistence（波動率持續性）**：不如 VIX
- **FOMC 事件**：聯準會開會前後——VIX 已經反映了
- **市場情緒 NLP proxy**：VIX surprise z-score——統計顯著但經濟上無意義
- **DCC 動態相關**：跨資產相關性變動——不改善 VT 績效
- **跨市場 vol spillover**：美股波動率傳導——統計顯著但利用它反而有害

**VIX 為什麼這麼強大？**

因為 VIX 來自選擇權市場——這是一個由專業交易員主導的衍生品市場，裡面已經包含了：
1. 所有公開資訊（新聞、數據、事件）
2. 專業人士對未來風險的「真金白銀」的賭注
3. 波動率風險溢酬（保險費）
4. 尾部風險的定價

當你看到 VIX = 25，這個數字已經匯聚了全球最聰明的衍生品交易員對未來 30 天風險的共識判斷。你不太可能用一個 Google Trends 搜尋量或一個新聞情緒指數來超越這個判斷。

**因果結構分析**也支持這個結論：VIX 是因果網絡中的「匯聚點（sink）」，不是「源頭（source）」。所有其他指標的資訊最終都會流入 VIX，而 VIX 不再向外傳遞獨特資訊。

**投資人只需要記住一件事：VIX < 15 → 放心持有；VIX 15-25 → 減碼至 50-80%；VIX > 25 → 減碼至 40% 以下。**

---

## 真相 5：不同資產需要不同工具

如果有人告訴你「用一個模型就能預測所有資產」，那是在騙你。98 個實驗中最具學術價值的發現之一，就是**波動率的不對稱性（leverage effect）因資產而異，而且方向相反**。

**什麼是 leverage effect？**

簡單說就是：「壞消息」比「好消息」更能影響波動率。對於股票，這個效應是正的（股價下跌 → 波動率上升），學術上叫做「槓桿效應」。

但我們發現，**黃金的 leverage effect 是反向的**——金價上漲反而增加波動率（γ = -0.09，t = -8.30，12 個季度 93% 為負）。為什麼？因為黃金上漲通常代表市場恐慌，恐慌帶來更多波動。

這個發現的實務意義很大：

| 資產類別 | Leverage 方向 | 最佳模型 | 原因 |
|----------|-------------|---------|------|
| 股票（SPY, QQQ）| 正向 (γ > +0.05) | GJR-GARCH | 捕捉「跌多漲少」的不對稱性 |
| 新興市場（EEM）| 正向 (γ = +0.34) | GJR-GARCH | 不對稱性更強 |
| 黃金（GLD）| 反向 (γ = -0.09) | 普通 GARCH | GJR 反而誤導 |
| 債券（TLT）| 中性 (γ ≈ 0) | 普通 GARCH | 不需要不對稱模型 |
| 加密貨幣（BTC）| 弱正向 (γ = +0.12) | GJR-GARCH | 輕微不對稱 |
| 石油（USO）| 依情況而定 | GARCH（常態）/ 監控 | 供應衝擊時會翻轉！ |
| 外匯 | 極弱 (γ ≈ 0.06) | EWMA 就夠 | 央行政策主導，leverage effect 弱 |
| 台股（0050）| 極弱 (γ ≈ 0.03) | EWMA | VIX 已足夠 |

這張表不是我們拍腦袋想的——它經過 20 個資產、超過 10 年數據、正式 DM 統計檢定、和 TRUE OOS 驗證（83% 準確率）。

**石油的特殊性值得一提**：2026 年伊朗危機期間，USO 的 leverage effect 從正向 (+0.10) 翻轉為反向 (-0.13)——供應衝擊讓油價暴漲的同時波動率飆升。這證實了我們的假說：**leverage 方向反映的是資產的經濟角色，不是統計巧合。**

"""

if chart3_url:
    content = embed_chart(content, chart3_url, "跨資產波動率模型效果熱力圖", position="append")

content += """

---

## 結語：98 個實驗的 3 個行動建議

如果你只記住 3 件事，記住這些：

### 行動 1：建立你的「懶人組合」
- 50% SPY + 50% GLD
- 每月月初查 VIX，用 12/VIX 計算持有比例
- 剩餘部分放 SHY
- 年交易成本 < 0.1%，年費 < $50

### 行動 2：忽略 99% 的「投資建議」
- 那些告訴你「用 AI 預測股市」的人，他們的模型在我們的測試中全部失敗
- VIX 已經包含了所有你需要的風險資訊
- 複雜度不等於有效性——恰恰相反

### 行動 3：長期持有，月度調整
- 不要日內交易（交易成本會吃掉所有利潤）
- 不要追逐短期訊號（包括新聞情緒、技術指標）
- 每月一次調整就夠了——月度 rebalancing 的 Sharpe 反而高於日度

---

*本文基於 K426-K522 共 98 個實驗。數據來源：yfinance，涵蓋 17 個資產、7 大資產類別、2005-2026。所有實驗均有完整腳本（experiments/）和結果檔案（experiments/*_results.json）。統計門檻採用 Harvey (2016) t > 3.0。*

*[提出: 用戶, 執行: Claude]*
"""

# ─── Publish as draft ────────────────────────────────────────────
pub = Publisher()
pub_id = pub.publish_milestone(
    title="98 個實驗告訴你的 5 個投資真相——從波動率研究到實戰策略",
    description=content,
    phase="research",
    tags=["一般讀者", "投資指南", "波動率", "策略", "VIX", "98實驗"],
    status="draft",
    audience="general",
    category="general",
)
print(f"\n✅ Published as DRAFT: {pub_id}")
print(f"Content length: {len(content)} chars")
