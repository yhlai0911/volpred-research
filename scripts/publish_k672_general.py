"""Publish K672 general-audience meta-synthesis article (draft).

Differentiation from existing research-audience version (mile_c15c7b98):
- Tone: plain Chinese, no t-stat / Harvey / DM-test / K-id jargon in body
- Frame: narrative survey "什麼穩了 / 什麼還在驗 / 什麼還沒答案"
- Audience: general (vs research)
- Same 7+6+5+7 substance, reader-friendly translation
- Charts: NEW (4-bucket evidence map + topic landscape) — different from research version's
  category distribution + evidence hierarchy charts
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.volpred.charts.article_charts import upload_chart
from src.volpred.publisher.publisher import Publisher

CHART1_LOCAL = "experiments/k672/charts/k672_general_evidence_map.png"
CHART2_LOCAL = "experiments/k672/charts/k672_general_topic_landscape.png"

print("Uploading charts to Supabase Storage...")
chart1_url = upload_chart(CHART1_LOCAL)
chart2_url = upload_chart(CHART2_LOCAL)
print(f"  chart1: {chart1_url}")
print(f"  chart2: {chart2_url}")

TITLE = "兩年研究、25 個結論：波動率投資的這些事，現在「穩了」、「快穩了」、「還沒答案」"

CONTENT = f"""## 摘要

[提出: Claude]

我們花了兩年多的時間，跑了將近四百個實驗，累積一千多條研究筆記，想回答一個簡單的問題：**面對股市的波動，散戶該怎麼自保、又該怎麼進場？**

這篇文章不講新發現，而是做一次**盤點**：把所有累積的結論按「證據強度」分成四層——

- **7 條已被證實**（多次獨立驗證、可放心使用）
- **6 條強證據**（高度可信、還在繼續觀察）
- **5 條新興發現**（看起來有效、樣本還不夠大）
- **7 個尚未解答**（重要、但目前我們也不知道答案）

如果你只是想知道「現在到底什麼結論可以拿來用、什麼還在實驗階段」，這篇就是給你的地圖。

![四層證據地圖](${{CHART1}})

---

## 一、什麼已經「穩了」——7 條可放心使用的結論

這些都是經過**至少十次以上、跨不同市場與不同時期**獨立驗證的結論。換句話說，不是我們做一次實驗看到、而是反覆換資料、換方法、換人重做都還是同一個答案。

### 1. 想做「波動目標化」策略，看 VIX 一個指標就夠

「波動目標化」（Volatility Targeting，簡稱 VT）是專業機構常用的風險管理方法：**市場越平靜就放越多倉、市場越亂就把倉位往下砍**。我們嘗試把超過十種額外指標加進來——VIX 期貨、信用利差、殖利率曲線、製造業景氣、投資人情緒、選擇權偏度——結果統統沒用。VIX 自己已經把該有的訊號都壓縮進去了。

### 2.「12÷VIX」是最簡單也最有效的調倉公式

倉位 = 12 ÷ 當前 VIX，最多滿倉 100%。VIX 在 12 以下就滿倉、20 時 60%、30 時 40%。簡單到一張紙就能寫完。我們試過搬出移動平均、雙動能、組合預測、機制切換——**沒有一個能在統計顯著的程度上打贏這條三行公式**。長期 Sharpe 約 0.7，最大回撤從買進持有的 −80% 縮到 −13% ~ −33%。

### 3. 預測得準 ≠ 賺得多（這是整個研究最反直覺的發現）

我們訓練了非常多的「波動率預測模型」，有些確實預測得**比 GARCH 準很多**。但奇怪的是，**用更準的預測去做策略，賺的錢沒比較多、有時還更少**。

為什麼？因為波動率策略的成敗不在「預測未來幾天的波動數字」，而在「**遇到大事件時你有沒有把倉位降下來**」。預測精度的小數點後三位不重要，重要的是恐慌指數一飆你有沒有反應。

### 4. 用「日線資料」改進波動率預測，已經到天花板了

我們試過把幾十種額外資料丟進日線 GARCH——景氣指標、月頻巨觀、低頻基本面、深度學習網路——**幾乎沒有一個能讓預測誤差再降一截**。GARCH(1,1) 已經把日頻收盤資料能擠出來的訊號擠光了。要繼續突破，得換資料：去抓 5 分鐘高頻、選擇權隱含資訊、或盤中即時訊號。

### 5. 黃金跟股票不一樣，要用不同模型

股票有「壞消息會放大波動、好消息不會」的不對稱現象（學界叫「槓桿效應」），所以股票要用 GJR-GARCH。但**黃金、白銀、原油這些大宗商品沒有這個現象**，硬套同一套模型反而失準。我們在 17 個資產上反覆驗證，這條規則 100% 成立——**先看資產類別，再選模型**。

### 6. 對「美國股市日線」而言，GJR-GARCH 已經是天花板

我們把所有號稱更先進的波動率模型——FIGARCH、CGARCH、EGARCH、HAR、長記憶模型、混頻、深度學習——全部丟去打 GJR-GARCH。**沒有一個贏**。如果你只看 SPY 日線、要做風險預測，GJR-GARCH 就是答案。

### 7. VT 在每一次危機都有效

2008 金融海嘯、2011 歐債危機、2015 中國熊市、2018 Q4、2020 COVID、2022 升息熊市——**每一次大跌中 VT 的回撤都比買進持有少超過 20 個百分點**。這不是偶然，這是「波動上升通常伴隨大跌」這個股市結構性事實的直接後果。

---

## 二、什麼是「快穩了」——6 條強證據

這些結論已經看到 5–9 次一致確認，但還沒到「定論」程度。可以用，但建議搭配其他訊號：

| # | 結論 | 一句話解讀 |
|---|------|------|
| 1 | 50/50 股債（或股金）+ VT 是穩健配置 | 簡單分散 + VT 風控，已經很難打贏 |
| 2 | 月再平衡優於日再平衡 | 日頻會被噪音拖累，月頻夠用 |
| 3 | 你想瞄準的「目標波動率」設多少其實沒差 | 設 10% 跟 15% 結果幾乎一樣 |
| 4 | EGARCH 在實務上常常算不出來 | 數值不穩定，不建議當主力 |
| 5 | VIX 有「禮拜幾效應」 | 週一 VIX 偏高、週五偏低 |
| 6 | VT 在台股 0050 上一樣有效 | 不是只有美股才能用 |

---

## 三、什麼是「新興發現」——5 條看起來有效但還在驗證

這些只看到 2–4 次驗證，可能是真結論，也可能是巧合。**不建議當策略核心，可以當輔助觀察**：

- **GARCH 用固定參數可能比天天重估還好**：天天重估會被短期雜訊干擾，固定參數反而穩
- **「恐慌定期定額」分段加碼**：VIX 在不同水位用不同加碼幅度，似乎有效
- **VT 報酬可以拆成「主動報酬 + 保險成本」兩部分**：這個視角讓績效歸因更清楚
- **直接用 VIX 對應波動率的查表法可能勝過 GARCH**：簡單到不像會贏，但似乎贏
- **辛普森悖論：分組看跟合起來看會得到相反結論**：解釋為什麼某些指標在子市場有效、合起來看就消失

---

## 四、還沒答案的 7 個問題——研究前沿

這是我們自己也還在卡關的地方。**列出來不是因為失敗，是因為這些問題重要而我們不想假裝知道答案**：

![研究主題分佈](${{CHART2}})

1. **5 分鐘高頻資料能不能突破日線天花板？** 41 天的試跑看到 −18% 改善，但需要更長樣本
2. **遇到真正的惡性通膨（像 1970 年代）時 VT 還有效嗎？** 我們的樣本期間還沒包含這種極端
3. **美股 VIX 領先台股的關係，在不同市場狀態下穩定嗎？** 有時看起來不太穩
4. **機器學習能不能讓 VT 策略真的賺更多？** 目前所有 ML 嘗試都沒明顯改善
5. **用 VIX 來決定要不要開槓桿，長期是不是真的可行？** 短期看起來可以，長期不確定
6. **盤後跳空的資訊能不能用來做 VaR 風控？** 早盤跳空看起來有資訊，但怎麼用還沒想通
7. **跨市場的波動率傳染網絡，能不能預測下一次危機？** 大家都這樣說，但統計上還沒被嚴格證明

---

## 五、給散戶讀者的三個重點

如果你只記得三件事：

**第一，不要再迷信『更複雜的模型』。** 對日線資料而言，GJR-GARCH 已經到頂；對 VT 策略而言，「12÷VIX」三行公式已經到頂。多數試圖打敗它們的方法是**讓你看起來在做事**，不是真的賺更多。

**第二，VT 是目前最穩定的「自動煞車」。** 它不會幫你抓多頭高點，但每一次大跌都會幫你少賠 20% 以上。如果你的目標是「不被市場洗下車」，VT 比擇時、比動能、比技術分析都更可靠。

**第三，這 25 個結論不是終點。** 我們會繼續驗證新興發現、繼續挑戰開放問題。研究是一個**累積證據**的過程，不是一次定生死。今天列在「還沒答案」的問題，可能下個月就會有新進展。

---

*本文整理自 K672 知識庫盤點實驗（腳本：`experiments/k672/k672_definitive_conclusions.py`，結果：`experiments/k672/k672_results.json`）。資料來源：1,421 條研究筆記、389 個編號實驗，整理時點為 2026-03-29（目前資料庫已成長至 2,043 條）。所有數字皆可在 `experiments/` 目錄下逐一追溯。本文為一般讀者導讀版；同主題的學術完整版見「波動率預測研究的定論與開放問題：K672 對 1,421 條知識條目的四層證據地圖」。*
""".replace("${CHART1}", chart1_url).replace("${CHART2}", chart2_url)

print(f"\nContent length: {len(CONTENT)} chars")

pub = Publisher()
pub_id = pub.publish_milestone(
    title=TITLE,
    description=CONTENT,
    phase='research',
    category='milestone',
    audience='general',
    tags=['波動率', 'VT策略', 'VIX', 'GARCH', '研究綜述', '風險管理', '證據地圖'],
    proposer='Claude',
    status='draft',
    details={
        'experiment_refs': ['K672'],
        'audience_axis': 'general',
        'companion_research_article': 'mile_c15c7b98',
    }
)

print(f"\n=== PUBLISHED ===")
print(f"pub_id: {pub_id}")
print(f"status: draft")
print(f"audience: general")
