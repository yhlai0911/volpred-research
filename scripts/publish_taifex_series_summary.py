"""
TAIFEX 期貨研究系列總結文章（一般讀者）
K838-K845 系列實驗完整故事
"""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

from volpred.charts import upload_chart

# ─── 字體設定 ─────────────────────────────────────────────────
plt.rcParams["font.sans-serif"] = ["PingFang HK", "Heiti TC", "STHeiti", "Arial Unicode MS", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["figure.facecolor"] = "white"
plt.rcParams["axes.facecolor"] = "white"
plt.rcParams["axes.grid"] = True
plt.rcParams["grid.alpha"] = 0.3

_CHART_DIR = Path("/tmp/volpred_charts")
_CHART_DIR.mkdir(exist_ok=True)
_DPI = 150


# ─── 圖表 1：Return Decomposition ─────────────────────────────
fig1, ax1 = plt.subplots(figsize=(8, 5))
labels1 = ["夜盤（隔夜）", "開盤跳空", "日盤（盤中）"]
values1 = [73.7, 15.6, 10.5]
colors1 = ["#2196F3", "#FF9800", "#9E9E9E"]
bars1 = ax1.bar(labels1, values1, color=colors1, edgecolor="white", linewidth=0.5, width=0.6)
for bar, val in zip(bars1, values1):
    ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.8,
             f"{val:.1f}%", ha="center", va="bottom", fontsize=12, fontweight="bold")
ax1.set_ylabel("佔總報酬比例 (%)", fontsize=12)
ax1.set_title("台股每日報酬來源分解（TX 期貨 2017-2026）", fontsize=14, fontweight="bold", pad=15)
ax1.set_ylim(0, 88)
fig1.tight_layout()
uid1 = uuid.uuid4().hex[:6]
decomp_path = str(_CHART_DIR / f"taifex_return_decomp_{uid1}.png")
fig1.savefig(decomp_path, dpi=_DPI, bbox_inches="tight", facecolor="white")
plt.close(fig1)
url_decomp = upload_chart(decomp_path)
print(f"圖表1上傳完成: {url_decomp}")


# ─── 圖表 2：研究旅程 Sharpe 演進 ──────────────────────────────
fig2, ax2 = plt.subplots(figsize=(10, 5))
labels2 = ["K838\n夜盤動量", "K841\nVIX避險", "K842\nSPY信號",
           "K843\n夜盤drift", "K843 S4\nA-C對齊", "K844\nTX VT"]
values2_display = [0.05, 0.03, 0.04, 0.788, 0.788, 1.465]
values2_real = [0.0, 0.0, 0.0, 0.788, 0.788, 1.465]
colors2 = ["#EF5350", "#EF5350", "#EF5350", "#66BB6A", "#66BB6A", "#2196F3"]
bars2 = ax2.bar(labels2, values2_display, color=colors2, edgecolor="white", linewidth=0.5, width=0.6)
for bar, val, orig in zip(bars2, values2_display, values2_real):
    label = "NULL" if orig == 0.0 else f"{orig:.3f}"
    ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.03,
             label, ha="center", va="bottom", fontsize=10, fontweight="bold")
ax2.set_ylabel("Sharpe Ratio（年化）", fontsize=12)
ax2.set_title("TAIFEX 研究旅程：從三次失敗到 Sharpe 1.465", fontsize=14, fontweight="bold", pad=15)
ax2.set_ylim(0, 1.8)
red_patch = mpatches.Patch(color="#EF5350", label="NULL result（信號無效）")
green_patch = mpatches.Patch(color="#66BB6A", label="有效 drift 策略")
blue_patch = mpatches.Patch(color="#2196F3", label="完整 TX VT 策略")
ax2.legend(handles=[red_patch, green_patch, blue_patch], loc="upper left", fontsize=10)
fig2.tight_layout()
uid2 = uuid.uuid4().hex[:6]
journey_path = str(_CHART_DIR / f"taifex_journey_{uid2}.png")
fig2.savefig(journey_path, dpi=_DPI, bbox_inches="tight", facecolor="white")
plt.close(fig2)
url_journey = upload_chart(journey_path)
print(f"圖表2上傳完成: {url_journey}")


# ─── 組合文章內容 ─────────────────────────────────────────────
title = "三次失敗、一個頓悟——我們在台指期找到的秘密"

description = (
    "連續三個實驗全軍覆沒後，VolPred 研究團隊改變了思路：與其用外部信號猜測市場，"
    "不如讓數據自己開口說話。這一轉念，揭開了台股最反直覺的事實：日盤時間只有 10.5% 的報酬，"
    "73.7% 的行情在你睡覺時已經結束了。K838-K845 系列實驗完整故事。"
)

content = f"""# 三次失敗、一個頓悟——我們在台指期找到的秘密

[提出: 用戶 (方向), Claude (execution)]

## 故事的開始：一個看似合理的想法

2026 年初，VolPred 研究團隊開始了一系列台灣期貨市場的系統性探索。

出發點很直觀：台指期貨（TX）有夜盤，可以感知美股動向；VIX 是全球公認的恐慌指標；SPY 代表美股整體方向。如果這些信號能提前預測台指期貨的走勢，就能建立一套有利可圖的策略。

**聽起來很合理，對嗎？**

讓我們從第一次嘗試說起。

---

## 第一章：三次撞牆

### K838——夜盤動量失效

研究團隊首先測試了最直覺的想法：夜盤如果漲了，明天繼續漲的機率更高嗎？

結果是一個平淡的 NULL。

問題在哪？夜盤的動量信號，同商品自己在盤中就已經消化完了。你在夜盤收盤看到的漲跌，到了早上 8:45 開盤時市場早就重新定價了。這個信號不是假的——只是已經過期了。

### K841——VIX 避險太慢

第二個想法：VIX 衝高代表市場恐慌，這時候應該減碼。

同樣是 NULL。

致命的問題：信號是「T-2」，也就是兩天前的 VIX 才能當信號。等你意識到市場恐慌、調整部位，該發生的已經發生了。VIX 不是水晶球，它告訴你昨天有多恐慌，不是明天會怎樣。

### K842——SPY 信號消化太快

第三次嘗試：美股 SPY 的漲跌可以預測台股嗎？

依然是 NULL。

原因：台灣的機構投資人早就在夜盤把美股信號消化進台指期貨了。等你早上看到 SPY 昨晚大漲，台指期貨夜盤早就反映完了。你永遠在追一個已經跑掉的影子。

---

![TAIFEX 研究旅程：從三次失敗到 Sharpe 1.465]({url_journey})

三次失敗，不是運氣不好——是思路根本方向錯了。

---

## 第二章：轉折點——讓數據自己說話

在三連敗之後，研究團隊做了一個根本性的思路轉換：

**與其用外部信號猜測市場，不如先搞清楚市場本身的結構是什麼。**

### K843——逐筆 tick 的秘密

K843 實驗對 TAIFEX 的逐筆成交數據進行了深度分析，把每一天的報酬拆解成更細的時間片段，看哪個時段的「drift」（趨勢性）最穩定。

發現令人意外：**夜盤本身就有正的 drift**，不需要任何外部信號。

夜盤 drift 策略的 Sharpe Ratio 達到 **0.788**，而且在 10 年的數據中，**9/10 年都是正的**。這不是隨機波動，這是一個穩定的結構性機會。

更進一步，K843 的 Slot A-C 對齊分析（在最佳時段進場）把最大回撤（MDD）降低了 **78%**。

---

## 第三章：根本發現

K843 的結果讓研究團隊提出了一個更大的問題：台股的報酬到底是從哪裡來的？

### K844——73.7% 的真相

K844 實驗對 TX 期貨 2017-2026 年的 2158 個交易日進行了完整的 Return Decomposition 分析：

![台股報酬來源分解：夜盤 73.7%、跳空 15.6%、日盤僅 10.5%]({url_decomp})

數字清楚得讓人驚訝：

| 時段 | 報酬佔比 | 說明 |
|------|---------|------|
| **夜盤** | **73.7%** | 昨收盤 → 今早開盤（跨夜 15 小時） |
| **開盤跳空** | **15.6%** | 期貨夜盤 vs 現貨開盤之間的跳空 |
| **日盤** | **10.5%** | 上午 9:00 → 下午 1:30（4.5 小時） |

**結論只有一個：你每天盯著看盤軟體的 4.5 小時，只包含了台股約 10.5% 的報酬機會。**

另外 89.5% 的行情，在你睡覺時已經結束了。

### 為什麼夜盤這麼重要？

這不是偶然現象，而是市場結構決定的：

1. **全球聯動**：台股與美股高度相關。美股的漲跌（台灣時間晚上 9:30 到早上 4:00）直接影響台指期貨夜盤，隔天一開盤就反映進現貨。

2. **機構定價**：外資和大型機構在夜盤就對全球信息進行定價，散戶到早上 9 點才能進場，早就晚了。

3. **結構性套利**：正是因為夜盤信息如此重要，機構才不斷在夜盤定價——這形成了穩定的 drift 結構，而不是隨機噪聲。

### TX VT vs 0050 VT——誰更適合保護你的財富？

K844 同時比較了台指期貨 VT 策略（TX VT，Sharpe **1.465**）和現貨 ETF VT 策略（0050 VT，Sharpe **1.370**）：

最關鍵的發現在空頭市場：**TX 在 3/3 次空頭期間全勝 0050**。

| 市場環境 | TX VT Sharpe | 0050 VT Sharpe | 結果 |
|---------|-------------|---------------|------|
| 2018-19 中美貿易戰 | **1.43** | 1.08 | TX 贏 +0.35 |
| 2020 COVID 崩盤 | **1.57** | 1.26 | TX 贏 +0.31 |
| 2022-23 升息空頭 | **0.71** | 0.37 | TX 贏 +0.34 |
| 2024-25 多頭行情 | 1.51 | **1.99** | 0050 贏 +0.48 |

道理很直接：空頭市場的跌勢往往集中在夜盤（美股暴跌 → 隔天台股 Gap Down）。持有期貨 VT 策略的投資人能在信息反映最快的時段調整部位；現貨投資人只能等到早上 9 點才能操作，已經晚了。

另一個隱藏優勢：**交易成本**。TX 期貨的年化交易成本約 0.57%，0050 現貨約 19.2%——期貨節省了 **97%** 的成本。在頻繁再平衡的 VT 策略中，成本差異是決定性因素。

---

## 結局：不上架，但有真實價值

K845 進行了正式的上架評估。結果是 Test 1 FAIL——在同期間比較中，TX VT 策略沒有達到上架門檻，不會被單獨列為推薦策略。

但這不代表研究沒有價值。

### 三個帶走的核心洞見

**洞見一：大多數外部信號太慢**

VIX、SPY、夜盤動量——在台指期貨市場，這些信號到你能使用的時候早就被市場消化了。如果你想用外部信號交易，需要比機構更快，這幾乎不可能。

**洞見二：台股 90% 的行情在盤外發生**

這個事實改變了我們對「台股投資」的理解。持有 0050 的長期投資人，實際上只參與了台股每日 10.5% 的報酬機會，另外 89.5% 發生在你無法觸及的時段。這不是問題——而是你必須知道的事實。

**洞見三：空頭市場是分野**

在多頭市場，現貨的股息優勢會讓 0050 勝出。但在空頭市場，能夠在夜盤調整部位的期貨 VT 策略才是真正的保護盾。如果你最擔心的是「市場崩盤怎麼辦」，期貨工具值得認真理解。

---

## 寫在最後

K838 到 K845，這段研究旅程的最大收穫不是一個可以立刻執行的策略，而是**一個更真實的市場認識**：

- 台股的市場結構決定了信息流向——夜盤先，日盤後
- 外部信號的有效性取決於你能多快使用它，而不是它本身有多準確
- 空頭期間的保護，比多頭期間的追漲更有價值

下次當你看到台股早盤大跌，不要急著在 9:05 恐慌賣出。那個跌勢，很可能是夜盤早就跌完、正在尋底的尾聲。

**真正的市場判斷，從理解它的結構開始。**

---

*本文基於 K838-K845 系列實驗（TAIFEX TX 逐筆成交 2017-2026，2158 天）*
*數據來源：台灣期貨交易所（TAIFEX）TX 日/夜盤 OHLCV 數據*
*實驗腳本：experiments/k838.py, k841.py, k842.py, k843.py, k844.py, k845.py*
"""

# ─── 建立 article ──────────────────────────────────────────────
article = {
    "id": f"mile_{uuid.uuid4().hex[:8]}",
    "title": title,
    "description": description,
    "content": content,
    "tags": ["一般讀者", "TAIFEX", "台指期", "夜盤", "期貨策略", "研究歷程"],
    "status": "draft",
    "created_at": datetime.now(timezone.utc).isoformat(),
    "published_at": None,
    "proposer": "用戶 (方向), Claude (execution)",
}

# ─── 存入 feed.json ────────────────────────────────────────────
feed_path = Path("storage/reports/feed.json")
with open(feed_path, "r", encoding="utf-8") as f:
    feed = json.load(f)

feed.insert(0, article)

with open(feed_path, "w", encoding="utf-8") as f:
    json.dump(feed, f, ensure_ascii=False, indent=2)

# ─── 存個別 JSON ────────────────────────────────────────────────
individual_path = Path(f"storage/reports/{article['id']}.json")
with open(individual_path, "w", encoding="utf-8") as f:
    json.dump(article, f, ensure_ascii=False, indent=2)

print(f"\n文章已存為 draft")
print(f"  ID: {article['id']}")
print(f"  標題: {title}")
print(f"  檔案: storage/reports/{article['id']}.json")
print(f"  字數約: {len(content)} 字元")
