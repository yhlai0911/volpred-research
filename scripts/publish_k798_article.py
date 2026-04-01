"""
K798 Decision-Focused Policy Learning — General reader article.
跳過預測直接學交易？聽起來聰明但沒用
"""
import sys
import os
sys.path.insert(0, '/Users/yhlai0911/Desktop/volpred-research')

from volpred.charts import generate_bar_chart, upload_chart, embed_chart
from src.volpred.publisher.publisher import Publisher

# ─── 1. Generate bar chart ────────────────────────────────────
labels = [
    "直接最優化\n(DF-OLS)",
    "特徵條件策略\n(FC-Policy)",
    "情境強盜\n(Bandit)",
    "基準: 12/VIX",
    "基準: BH 50/50",
]
values = [2.20, 2.26, 2.01, 1.51, 2.24]

chart_path = generate_bar_chart(
    labels=labels,
    values=values,
    title="K798：各策略 Sharpe Ratio 比較（2006–2025）",
    ylabel="Sharpe Ratio（越高越好）",
    filename="k798_sharpe_comparison",
    figsize=(10, 6),
    highlight_best=True,
)

chart_url = upload_chart(chart_path)
print(f"Chart uploaded: {chart_url}")

# ─── 2. Article content ───────────────────────────────────────
content = """\
[提出: 用戶, 執行: Claude]

## 摘要

如果你跳過「預測波動率」這個步驟，直接用機器學習「學」交易動作，結果會更好嗎？我們測試了三種這樣的方法，發現它們表面上看起來「贏了」——但仔細一看，根本是鑽了多頭市場的漏洞，不是真正的擇時能力。

---

## 你有沒有聽過這個說法：「預測完再行動，太慢了」

傳統的量化策略流程是這樣的：

1. 預測明天波動率
2. 根據波動率決定今天該持有多少股票
3. 執行交易

這個流程有個顯而易見的批評：「你為什麼要多一個中間步驟？預測波動率只是手段，**賺錢才是目的**。為什麼不直接讓機器學習『什麼時候該持有多少』，跳過預測這一步？」

聽起來很有道理，對吧？這個概念在學術上叫做「決策導向學習（Decision-Focused Learning）」，近年在機器學習領域非常流行。我們的研究（K798）就是來測試：**在投資策略上，直接學交易動作真的比先預測再行動更好嗎？**

## 我們測試了三種「跳過預測」的方法

**方法一：直接最優化（DF-OLS）**
讓模型直接計算「在過去的數據下，什麼樣的 SPY 持倉比例能最大化報酬」，然後把這個比例套用到未來。不預測波動率，直接給出數字。

**方法二：特徵條件策略（FC-Policy）**
更進一步——讓模型學習「當 VIX 是 X、市場動能是 Y 的時候，應該持有 Z% 的 SPY」。類似一個很小的神經網路，根據當下特徵直接輸出交易決策。

**方法三：情境強盜（Contextual Bandit）**
借用強化學習的概念。把持倉比例分成幾個「動作選項」（低、中、高），讓模型在不同市場情境下「試錯」，逐漸學習哪個選項最好。

三種方法各有巧思，都號稱「不預測、直接學習最優動作」。

## 結果看起來很亮眼——直到你仔細看

| 策略 | Sharpe Ratio |
|------|:---:|
| 特徵條件策略（FC-Policy） | **2.26** |
| 直接最優化（DF-OLS） | 2.20 |
| BH 50/50（SPY+GLD，不動腦） | 2.24 |
| 情境強盜（Bandit） | 2.01 |
| 傳統 12/VIX 策略 | 1.51 |

第一眼看，FC-Policy 的 Sharpe 2.26 確實「贏了」所有對手。如果你在這裡停下來，你會說「機器學習直接決策法有效！」

但我們沒有停。我們做了一件很關鍵的事：**用嚴格的統計方法（Harvey t>3.0 門檻）檢驗這個差異是否真實存在**。

結果是：**所有三種方法都沒有通過統計顯著性檢驗。**

換句話說，FC-Policy 比 BH 50/50 「贏」那一點點（2.26 vs 2.24），完全可能只是隨機運氣。不是真正的技術優勢。

## 「贏了」的背後：其實是在押注多頭市場

我們進一步分析 FC-Policy 的實際行為，發現了問題的根源：

這個模型在測試期間（2006–2025）平均持有 **64% 的 SPY**（股票比例）。

2006–2025 這段期間，美股整體是牛市——持有更多股票，自然報酬更好。FC-Policy 「學」到的不是真正的擇時技巧，而是「多頭時期多買股票」這個非常簡單的規律。

這就是所謂的**「在牛市中吃掉風險溢酬」**，不是擇時能力。如果把這個策略放到熊市期間單獨測試，它的「優勢」會立刻消失。

## 真正的對手：什麼都不做的 50/50

這個測試裡最耐人尋味的結果是：**BH 50/50（買入並持有 50% SPY + 50% GLD）的 Sharpe 是 2.24**，幾乎和那個精心設計的 FC-Policy（2.26）一樣好。

而且 BH 50/50 通過了一個更嚴苛的測試——**CRRA 效用（考慮風險厭惡的情況下）**，BH 50/50 是最佳選擇。

意思是：如果你像一般投資人一樣在意下跌風險，**什麼都不調整、固定 50/50 持有，反而比那些複雜的機器學習策略更好**。

## 為什麼「直接學動作」在投資上特別難奏效？

這個結果呼應了我們之前的發現（K697）：**VIX 能預測波動率的大小，但不能預測報酬的方向**。

「方向」才是每日賺錢的關鍵。如果你不能預測明天是漲還是跌，那不管你用什麼方法「學習交易動作」，你都沒有辦法贏得每日 alpha。

決策導向學習是個聰明的概念，在有真實預測信號的問題上（比如天氣預報改進能源調度、醫療診斷改進治療方案）很有用。但在股市裡，**問題不是「預測到行動的映射太複雜」，而是根本就沒有穩定可用的預測信號**。

聰明的方法，遇到錯誤的問題，還是沒用。

## 那投資人該怎麼辦？

這是我們七次確認「12/VIX 難以突破」後，最一致的建議：

1. **波動率策略的價值在於降低風險，不是增加報酬**。當你用 VIX 調整持倉，你買的是「大跌時少虧一點」，不是「多頭時多賺一點」。

2. **固定比例配置（50/50）是極難打敗的基準**。如果你沒有確切的理由相信某個策略真的更好（統計顯著），不如就用它。

3. **看到漂亮的 Sharpe 數字先別衝動**。2.26 vs 2.24 的差異，在統計上根本不顯著。市場數據裡的「微小優勢」大多數都是噪音。

---

*本文基於 K798 實驗（數據：yfinance SPY/GLD/VIX，2006-2025）*
"""

# Embed chart after the summary section
content = embed_chart(content, chart_url, "K798：各策略 Sharpe Ratio 比較（2006–2025）", position="after_summary")

# ─── 3. Publish as draft ──────────────────────────────────────
pub = Publisher(storage_dir='/Users/yhlai0911/Desktop/volpred-research/storage')
pub_id = pub.publish_milestone(
    title="跳過預測直接學交易？聽起來聰明但沒用",
    description=content,
    phase="K798",
    tags=[
        "一般讀者",
        "機器學習",
        "決策導向學習",
        "SPY",
        "GLD",
        "VIX",
        "投資策略",
        "波動率預測",
        "12/VIX",
    ],
    status="draft",
    audience="general",
    category="general",
)

print(f"Published (draft): {pub_id}")
