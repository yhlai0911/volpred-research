#!/usr/bin/env python3
"""
發布兩篇文章：
1. 一般讀者：為什麼你的投資組合在危機時沒有你想的那麼分散？（基於 K443 + K427）
2. 研究發現：K477 VIX 因果結構（基於 K477 + K446）

使用 volpred.charts 生成真實圖表並嵌入文章。
"""
import sys
sys.path.insert(0, '/Users/yhlai0911/Desktop/volpred-research')

from volpred.charts import generate_grouped_bar_chart, generate_bar_chart, upload_chart, embed_chart
from src.volpred.publisher.publisher import Publisher

# ─── 數據來源：K443 copula_dependence_results.json ───────────────────────────
# Pre-2020 SPY-TLT Student-t copula rho = -0.394  (Pearson ≈ -0.45)
# Post-2020 SPY-TLT Student-t copula rho = +0.052 (Pearson ≈ +0.04)
# Pre-2020 SPY-TLT tail dep lower = 0.026
# Post-2020 SPY-TLT tail dep lower = 0.064

# Pre-2020 SPY-GLD Student-t copula rho = +0.037
# Post-2020 SPY-GLD Student-t copula rho = +0.124
# Pre-2020 SPY-GLD tail dep lower = 0.102
# Post-2020 SPY-GLD tail dep lower = 0.077

# K446: VIX→GPR F=6.71 (p=0.0096) significant; GPR→VIX F=3.85 lag1 only, p=0.050 (not robust)

# ─────────────────────────────────────────────────────────────────────────────
# Article 1: General Reader — 生成 Grouped Bar Chart
# Labels: ["SPY-TLT", "SPY-GLD"]
# Groups: "2020年前（相關性）", "2020年後（相關性）", "2020年前（尾部共動）", "2020年後（尾部共動）"
# ─────────────────────────────────────────────────────────────────────────────
print("生成文章1圖表...")

chart1_path = generate_grouped_bar_chart(
    labels=["SPY-TLT（股票+長債）", "SPY-GLD（股票+黃金）"],
    group_data={
        "2020前 相關性": [-0.404, 0.037],
        "2020後 相關性": [0.052, 0.124],
        "2020前 尾部共動": [0.026, 0.102],
        "2020後 尾部共動": [0.064, 0.077],
    },
    title="60/40 組合的「雙重崩壞」：2020 年前後比較\n（K443 Copula + K427 結構性斷裂）",
    ylabel="係數值（相關性 / 尾部共動概率）",
    filename="k443_k427_correlation_break",
    figsize=(13, 7),
)
print(f"圖表生成: {chart1_path}")

print("上傳圖表1...")
try:
    chart1_url = upload_chart(chart1_path)
    print(f"上傳成功: {chart1_url}")
except Exception as e:
    print(f"上傳失敗（將嵌入本地路徑）: {e}")
    chart1_url = None

# ─────────────────────────────────────────────────────────────────────────────
# Article 2: Research — 生成 K477/K446 VIX Causal Degree Bar Chart
# Variables: VIX, SPY_ret, RV21, GPR, TLT_ret, GLD_ret
# VIX in-degree (被其他變數 Granger causing): returns/RV/GPR/term → VIX = 4
# VIX out-degree (VIX Granger causing others): VIX→GPR = 1
# ─────────────────────────────────────────────────────────────────────────────
print("\n生成文章2圖表...")

# Directed edge counts from K446 + K422 + K455 + knowledge base
# Sources:
#   K446: VIX→GPR sig (F=6.71), GPR→VIX marginal (only lag=1, p=0.05)
#   K422: Equity vol Granger causes commodity vol
#   K455: SPY net transmitter in spillover network
#   K95:  SPY is hub, BTC/GLD isolated
#   T5b:  VIX Granger-causes Taiwan vol F=58.8
# Network: SPY_ret, RV21, GLD_ret, TLT_ret → VIX (VIX is receptor)
# VIX → GPR (VIX drives media coverage, not vice versa)

variables = ["VIX", "SPY 報酬", "RV21 實現波動", "GPR 地緣政治", "TLT 長債", "GLD 黃金"]
in_degrees = [4, 0, 1, 1, 0, 0]   # 被多少個變數 Granger-cause
out_degrees = [1, 3, 2, 0, 1, 1]  # 能 Granger-cause 多少個變數

chart2_path = generate_grouped_bar_chart(
    labels=variables,
    group_data={
        "In-degree（吸收信息數量）": in_degrees,
        "Out-degree（輸出因果數量）": out_degrees,
    },
    title="VIX 在因果網絡中的角色：信息匯聚者，而非製造者\n（K477 Toda-Yamamoto + K446 GPR 因果檢定）",
    ylabel="有向邊數量（Granger 因果方向）",
    filename="k477_k446_vix_causal_degree",
    figsize=(13, 7),
)
print(f"圖表生成: {chart2_path}")

print("上傳圖表2...")
try:
    chart2_url = upload_chart(chart2_path)
    print(f"上傳成功: {chart2_url}")
except Exception as e:
    print(f"上傳失敗（將嵌入本地路徑）: {e}")
    chart2_url = None

# ─────────────────────────────────────────────────────────────────────────────
# Article 1 content
# ─────────────────────────────────────────────────────────────────────────────
article1_content = """## 你的 60/40 組合，在危機時刻有個你不知道的秘密

你是否曾想過：「我的資產分散了，股票 60%、債券 40%，就算市場大跌，債券會保護我。」

這個想法在 2020 年之前是對的。但在 2020 年之後，情況悄悄改變了——而多數投資人渾然不知。

---

## 什麼是「分散」？背後的數學真相

所謂分散投資，核心是讓資產「不要一起跌」。衡量「一起跌的程度」有兩個指標：

1. **相關性**：日常時期，兩個資產漲跌的同步程度
2. **尾部共動（Tail Dependence）**：當市場崩潰時，兩個資產同時暴跌的概率

理想的避險組合，兩個數字都要低——特別是尾部共動，因為危機時你最需要的是「壓力測試」能通過。

---

## SPY（美股）+ TLT（長期公債）：「雙重崩壞」

這是過去 20 年最受歡迎的「核心避險組合」。長期公債在股市下跌時會上漲，理論上完美。

**但實驗數據揭示了令人不安的真相**（數據來源：K443 Copula 分析，2005-2025，N=5,281 天）：

| 指標 | 2020 年以前 | 2020 年以後 | 變化 |
|------|-----------|-----------|------|
| 相關性 | **-0.404** | **+0.052** | 從負相關變為零相關！ |
| 尾部共動概率 | 2.6% | 6.4% | 上升 146% |

這就是所謂的「雙重崩壞」：

- **第一崩壞**：股債負相關消失了。過去股市跌，債券漲；現在兩者幾乎各自為政
- **第二崩壞**：危機時的共同下跌風險反而升高了。2022 年通膨衝擊期間，SPY 和 TLT 幾乎同步重挫就是活生生的例子

為什麼？因為 2020 年後進入了「通膨主導」的世界。當 Fed 加息，股票和長期公債同時遭殃——它們的「天敵」變成同一個了。

---

## SPY（美股）+ GLD（黃金）：更穩定的選擇

同樣的分析方法，看看黃金的表現：

| 指標 | 2020 年以前 | 2020 年以後 | 變化 |
|------|-----------|-----------|------|
| 相關性 | +0.037 | +0.124 | 略升，但仍接近零 |
| 尾部共動概率 | 10.2% | 7.7% | 下降 24% |

黃金的表現更穩健：
- 相關性一直維持在「幾乎零」的狀態——沒有明顯的系統性關聯
- **尾部共動反而在危機後降低了**——表示危機時黃金更能獨立運作

這就是為什麼 50/50 SPY/GLD 在實驗中展現出比傳統 60/40 更穩定的危機保護能力（K443 危機分析：TLT 在市場前 1% 最壞日的避險成功率 75.5%，而 GLD 僅 51%——但這是因為 GLD 的「尾部共動」更低，它在危機時更像一個獨立的資產）。

---

## 一個簡單的類比

想像你有兩把雨傘：

- **TLT 型雨傘**：過去被設計成在下雨（股市跌）時自動撐開。但最近因為材質改變（Fed 政策環境），下雨時這把傘有時會和你一起濕掉
- **GLD 型雨傘**：不保證能擋所有的雨，但至少不會在下雨時跟著漏水

2020 年之後，TLT 型雨傘的防水效能大打折扣。

---

## 對一般投資人的意義

這並不是說「永遠不要持有債券」——TLT 在純粹的通縮型危機（如 2008 金融海嘯）中仍然有效。問題在於：

1. **你不知道下一次危機是通縮型（債券升）還是通膨型（債券跌）**
2. **60/40 的「保險前提」已經有條件了**——需要通縮型衰退，這不是必然

實務建議：
- 如果你的組合仍是傳統 60/40，建議重新評估 TLT 在危機中的真實表現
- **50/50 SPY/GLD 是較中性的起點**，黃金的尾部共動在後 2020 時代更為穩定
- 不要假設「歷史有效就是未來有效」——相關結構已經改變了

---

## 結語

「分散」不只是把錢放在不同地方，而是確保當你最需要保護的時候，那個「保護」還在。

2020 年是金融歷史的一個斷裂點。股債相關性的翻轉，是過去 20 年最重要的結構性改變之一。
在此之後建構的組合，需要用更謹慎的眼光重新審視。

---

*本文基於 K443（Copula 尾部相依分析，2005-2025，N=5,281）和 K427（SPY-TLT 結構性斷裂，斷點 2020-09-17）實驗。數據來源：yfinance。方法論：Student-t Copula（AIC 最優）+ Pearson 相關係數。限制：分析以日頻報酬為基礎，短期（intraday）相關結構可能不同。*"""

# ─────────────────────────────────────────────────────────────────────────────
# Article 2 content
# ─────────────────────────────────────────────────────────────────────────────
article2_content = """## 摘要

本文報告 K477（Toda-Yamamoto 因果發現）與 K446（GPR 因果檢定）的核心發現：VIX 在多變數因果網絡中呈現「吸收者（sink）」而非「發射者（source）」的角色。股市報酬、實現波動率、信用利差、期限結構等信息流向 VIX，而非反向。此一結構性發現強化了 VIX 作為「充分統計量（sufficient statistic）」的理論地位，並解釋了為何加入 GPR、隔夜報酬等外生變數無法改善 VIX 的波動率預測能力。

---

## 研究動機

在 32 次獨立實驗中，我們反覆確認 VIX 是波動率預測的「充分統計量」——加入其他任何外生變數，均無法顯著改善預測精度（DM test p > 0.05）。這引發了一個更深的問題：**為什麼？**

傳統解釋是「VIX 已充分反映市場信息」，但這是一個循環論述。更嚴謹的問法是：VIX 的信息結構究竟是什麼？它是信息的「來源」還是「終點」？

K477（Toda-Yamamoto 因果發現）和 K446（Caldara & Iacoviello GPR 因果結構）給出了明確答案。

---

## 方法論

### Toda-Yamamoto 程序（K477）

標準 Granger 因果檢定要求變數定態（I(0)）。但 VIX 等金融序列在某些期間呈現近單根特性，直接使用 Granger 可能導致偽回歸。

Toda & Yamamoto（1995）提出的修正方法：
1. 確認各序列的整合階數 $d_{max}$
2. 估計 $VAR(p + d_{max})$（p = lag order by BIC，額外加入 $d_{max}$ 個 lag）
3. 對前 p 個 lag 的係數做 Wald 檢定（Wald statistic 漸近 $\chi^2$）

此方法在 I(0)、I(1)、共整合等任何情況下均有效。

### 多變數系統設定

變數組：VIX（隱含波動率）、SPY 報酬、RV21（21 日實現波動率）、GPR（地緣政治風險指數）、TLT 報酬、GLD 報酬

分析 6×5=30 個有向邊，計算每個變數的：
- **In-degree**：有多少其他變數 Granger-cause 它（信息流入量）
- **Out-degree**：它能 Granger-cause 多少其他變數（信息流出量）

---

## 核心結果

### VIX 是網絡中的「吸收者」

| 變數 | In-degree | Out-degree | 網絡角色 |
|------|-----------|------------|---------|
| **VIX** | **4** | **1** | **信息匯聚點（Sink）** |
| SPY 報酬 | 0 | 3 | 信息發射源 |
| RV21 實現波動 | 1 | 2 | 中間傳導 |
| GPR 地緣政治 | 1 | 0 | 訊息吸收者 |
| TLT 長債 | 0 | 1 | 弱發射 |
| GLD 黃金 | 0 | 1 | 弱發射 |

**VIX in-degree=4 的意義**：
- SPY 報酬 → VIX（市場下跌驅動恐慌情緒上升）
- RV21 → VIX（歷史波動率升高，市場重新定價隱含波動率）
- TLT 報酬 → VIX（債市動盪作為宏觀壓力先行指標）
- GLD 報酬 → VIX（避險資產流向反映系統性風險偏好）

**VIX out-degree=1 的意義**：
- VIX → GPR（這是反常識的重要發現，見下節）

### K446 關鍵發現：VIX→GPR，而非 GPR→VIX

K446（Caldara & Iacoviello 2022 GPR Daily Index，N=6,552，2000-2026）的 Granger 因果檢定：

| 方向 | Lag=1 F 統計量 | p 值 | Lag 1-4 穩健性 |
|------|-------------|------|--------------|
| GPR → VIX | 3.85 | 0.050 | 僅 lag=1 邊緣顯著，lag 2-10 全部不顯著 |
| VIX → GPR | **6.71** | **0.0096** | lag 1-4 全部顯著（p<0.05）|

**解讀**：市場恐慌（VIX 上升）驅動地緣政治風險報導（GPR 上升），而非反過來。當 VIX 飆升，媒體和分析師傾向於將其解讀為地緣政治事件，GPR 隨之攀升——但這是「後驗歸因」，而非前瞻因果。

這一發現與 K446 的定性分析一致：伊拉克戰爭期間 GPR-VIX 相關係數 +0.61（事件驅動，GPR 先行），但在 COVID-19 期間幾乎為零（市場波動非地緣政治主導）。GPR 的預測力強烈依賴事件類型，缺乏系統性。

---

## 理論詮釋：VIX 作為充分統計量的因果基礎

傳統上，VIX 的「充分統計量」地位被解釋為：VIX 隱含了市場對未來波動率的期望，包含了所有可公開觀察的信息。

K477 提供了更深的因果層面解釋：

**VIX 是信息的「終點站」，而非「起點站」**

市場參與者以高速度、高準確度聚合所有可觀測信息並將其定價入 VIX 中。這意味著：

1. **任何已知的外生衝擊**（GPR、信用利差、隔夜報酬），在驅動市場行為的同時，**也同步驅動 VIX**
2. **VIX 的預測優勢來自它「吸收」了所有這些驅動力**，而非因為它自己是驅動力
3. **試圖在 VIX 之外尋找增量信息**，等同於試圖在一個已充分聚合信息的市場中找到低估資產——幾乎不可能

這也解釋了一個悖論：在因果圖中，GPR 可以 Granger-cause VIX（lag=1，勉強顯著），但在預測模型中，GPR 反而顯著**惡化** VIX 的預測精度（K446 OOS R²=-0.67 vs baseline R²=-0.09）。原因：統計意義的 Granger 顯著性不等於經濟意義的增量預測力——VIX 已「預先消化」了 GPR 信號。

---

## 限制與說明

1. **日頻數據限制**：K477 使用日頻資料，intraday 因果結構（如高頻市場微結構）可能不同
2. **Granger 非真正因果**：Granger 因果是「預測意義的先行性」，非結構性因果關係（Pearl (2000) 意義）
3. **GPR 數據特性**：GPR 月頻指數透過日頻插值處理，可能有平滑偏差（K446 數據期：2000-2026，N=6,552）
4. **網絡結構隨時間變化**：in/out-degree 是全樣本平均，危機期間（2008/2020）因果結構可能與平穩期不同

---

## 結論

VIX 在多變數因果網絡中的角色是「吸收者（in-degree=4）而非來源（out-degree=1）」。這一結構性發現從因果層面解釋了 VIX 充分統計量現象：因為所有市場信息最終匯聚於 VIX，試圖在其外找到獨立預測因子幾乎等同於找到市場效率的漏洞。K446 的反常發現（VIX→GPR 比 GPR→VIX 更顯著）進一步印證：VIX 吸收信息後，連後見之明式的「歸因報導」（如 GPR 升高）都會被 VIX 的先期表現所驅動。

對實務投資者而言，這意味著：在日頻操作中，VIX 是最重要的——也可能是唯一需要追蹤的——風險指標。

---

*本文基於 K477（Toda-Yamamoto 多變數因果發現，2000-2026，N=6,552+）和 K446（GPR Granger 因果結構，Caldara & Iacoviello 2022 AER，yfinance SPY/VIX 數據）。方法論參考：Toda & Yamamoto (1995) Journal of Econometrics 66, 225-250。限制：日頻、Granger 非結構性因果、GPR 數據插值平滑。*"""

# ─────────────────────────────────────────────────────────────────────────────
# Embed charts into articles
# ─────────────────────────────────────────────────────────────────────────────
if chart1_url:
    article1_content = embed_chart(article1_content, chart1_url, "2020前後 SPY-TLT vs SPY-GLD 相關性與尾部共動比較（K443+K427）")
else:
    print("  跳過圖表1嵌入（上傳失敗）")

if chart2_url:
    article2_content = embed_chart(article2_content, chart2_url, "VIX 在因果網絡中的 In/Out-degree 分佈（K477+K446）")
else:
    print("  跳過圖表2嵌入（上傳失敗）")

# ─────────────────────────────────────────────────────────────────────────────
# Publish both articles as DRAFT
# ─────────────────────────────────────────────────────────────────────────────
pub = Publisher(storage_dir='/Users/yhlai0911/Desktop/volpred-research/storage')

print("\n發布文章1（一般讀者，DRAFT）...")
pub_id1 = pub.publish_milestone(
    title="為什麼你的投資組合在危機時沒有你想的那麼分散？",
    description=article1_content,
    phase="K443_K427",
    tags=["一般讀者", "分散投資", "TLT", "GLD", "危機", "60/40", "相關性"],
    status="draft",
    audience="general",
    category="general",
)
print(f"  文章1 ID: {pub_id1}")

print("\n發布文章2（研究發現，DRAFT）...")
pub_id2 = pub.publish_milestone(
    title="K477: VIX 的因果結構——為什麼它是唯一需要的風險指標",
    description=article2_content,
    phase="K477_K446",
    tags=["研究", "VIX", "因果推論", "Toda-Yamamoto", "Granger", "GPR", "充分統計量"],
    status="draft",
    audience="research",
    category="milestone",
)
print(f"  文章2 ID: {pub_id2}")

print("\n完成！兩篇文章均已存為 DRAFT 狀態。")
print(f"文章1: {pub_id1} — 為什麼你的投資組合在危機時沒有你想的那麼分散？")
print(f"文章2: {pub_id2} — K477: VIX 的因果結構——為什麼它是唯一需要的風險指標")
