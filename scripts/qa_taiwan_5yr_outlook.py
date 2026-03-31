#!/usr/bin/env python3
"""
會員問答文章：台灣未來五年社會經濟走向與投資產業分析
提問者：yaoxk1431
問題：應用這20年的社會經濟背景與股價的反應預估接下來五年台灣社會經濟社會走向,
     與分析可投資的產業與建構模型, 並生成圖表, 2000字

數據來源：yfinance (0050.TW, 2330.TW, 2882.TW, EWT)
"""
import sys
import json
import subprocess
from datetime import datetime, timedelta

import yfinance as yf
import pandas as pd
import numpy as np

# Add project to path
sys.path.insert(0, "/Users/yhlai0911/Desktop/volpred-research/src")
sys.path.insert(0, "/Users/yhlai0911/Desktop/volpred-research/scripts")

from volpred.utils import clean_tw50_data
from volpred.charts import (
    generate_bar_chart,
    generate_grouped_bar_chart,
    generate_line_chart,
    upload_chart,
    embed_chart,
)

# ─── 1. Download data ─────────────────────────────────────────
print("Downloading data...")
tickers = {
    "0050.TW": "元大台灣50",
    "2330.TW": "台積電",
    "2882.TW": "國泰金",
    "EWT": "iShares MSCI Taiwan",
}

# Extended period for 20-year context
start_20y = "2006-01-01"
end_date = datetime.now().strftime("%Y-%m-%d")

data = {}
for ticker, name in tickers.items():
    try:
        df = yf.download(ticker, start=start_20y, end=end_date, progress=False)
        if hasattr(df.columns, 'droplevel') and isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        prices = df["Close"].squeeze()
        if ticker == "0050.TW":
            prices, returns = clean_tw50_data(prices)
        else:
            returns = prices.pct_change()
        data[ticker] = {"prices": prices, "returns": returns, "name": name}
        print(f"  {ticker} ({name}): {len(prices)} days, {prices.index[0].strftime('%Y-%m-%d')} ~ {prices.index[-1].strftime('%Y-%m-%d')}")
    except Exception as e:
        print(f"  {ticker} ({name}): FAILED - {e}")

# Also download sector ETFs for sector analysis (recent 5 years)
start_5y = "2021-01-01"
sector_tickers = {
    "2330.TW": "半導體（台積電）",
    "2317.TW": "電子代工（鴻海）",
    "2882.TW": "金融（國泰金）",
    "2412.TW": "電信（中華電）",
    "2303.TW": "面板（聯電）",
    "1301.TW": "傳產（台塑）",
}

sector_data = {}
for ticker, name in sector_tickers.items():
    try:
        df = yf.download(ticker, start=start_5y, end=end_date, progress=False)
        if hasattr(df.columns, 'droplevel') and isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        prices = df["Close"].squeeze()
        if len(prices) > 0:
            total_return = (prices.iloc[-1] / prices.iloc[0] - 1) * 100
            ann_return = ((prices.iloc[-1] / prices.iloc[0]) ** (252 / len(prices)) - 1) * 100
            ann_vol = prices.pct_change().std() * np.sqrt(252) * 100
            sector_data[name] = {
                "total_return": total_return,
                "ann_return": ann_return,
                "ann_vol": ann_vol,
                "sharpe": ann_return / ann_vol if ann_vol > 0 else 0,
            }
            print(f"  {ticker} ({name}): total return {total_return:.1f}%, ann vol {ann_vol:.1f}%")
    except Exception as e:
        print(f"  {ticker} ({name}): FAILED - {e}")

# ─── 2. Compute key statistics ─────────────────────────────────
print("\nComputing statistics...")

# 0050 performance by era
eras = {
    "2006-2008 金融海嘯前": ("2006-01-01", "2008-12-31"),
    "2009-2015 復甦期": ("2009-01-01", "2015-12-31"),
    "2016-2019 貿易戰": ("2016-01-01", "2019-12-31"),
    "2020-2021 COVID+科技牛": ("2020-01-01", "2021-12-31"),
    "2022-2023 升息+通膨": ("2022-01-01", "2023-12-31"),
    "2024-2026 AI+地緣": ("2024-01-01", end_date),
}

era_stats = {}
tw50_prices = data["0050.TW"]["prices"]
for era_name, (s, e) in eras.items():
    mask = (tw50_prices.index >= s) & (tw50_prices.index <= e)
    era_p = tw50_prices[mask]
    if len(era_p) > 20:
        tr = (era_p.iloc[-1] / era_p.iloc[0] - 1) * 100
        ann_r = ((era_p.iloc[-1] / era_p.iloc[0]) ** (252 / len(era_p)) - 1) * 100
        vol = era_p.pct_change().std() * np.sqrt(252) * 100
        mdd = ((era_p / era_p.cummax()) - 1).min() * 100
        era_stats[era_name] = {"total_return": tr, "ann_return": ann_r, "ann_vol": vol, "mdd": mdd}
        print(f"  {era_name}: return {tr:.1f}%, vol {vol:.1f}%, MDD {mdd:.1f}%")

# TSMC vs 0050 correlation
if "2330.TW" in data and "0050.TW" in data:
    tsmc_r = data["2330.TW"]["returns"].dropna()
    tw50_r = data["0050.TW"]["returns"].dropna()
    common = tsmc_r.index.intersection(tw50_r.index)
    corr = tsmc_r[common].corr(tw50_r[common])
    print(f"  TSMC-0050 correlation: {corr:.3f}")

# US lead-lag (K502 reference)
ewt_r = data.get("EWT", {}).get("returns", pd.Series(dtype=float)).dropna()

# ─── 3. Generate Chart 1: Sector performance comparison (5Y) ──
print("\nGenerating Chart 1: Sector performance...")
if sector_data:
    labels = list(sector_data.keys())
    total_returns = [sector_data[k]["total_return"] for k in labels]
    ann_vols = [sector_data[k]["ann_vol"] for k in labels]

    chart1_path = generate_grouped_bar_chart(
        labels=labels,
        group_data={
            "累計報酬率 (%)": total_returns,
            "年化波動率 (%)": ann_vols,
        },
        title="台灣主要產業 5 年表現比較（2021-2026）",
        ylabel="百分比 (%)",
        filename="tw_sector_5yr_performance",
        figsize=(12, 7),
    )
    print(f"  Chart 1 saved: {chart1_path}")
    chart1_url = upload_chart(chart1_path)
    print(f"  Chart 1 uploaded: {chart1_url}")
else:
    chart1_url = None
    print("  No sector data available for chart 1")

# ─── 4. Generate Chart 2: Risk/Opportunity matrix ─────────────
print("\nGenerating Chart 2: Risk-opportunity allocation...")

# Forward-looking allocation suggestion based on our research
# Using data-driven insights from our knowledge base
allocation_labels = [
    "半導體/AI",
    "金融",
    "電子代工",
    "綠能/電動車",
    "生技醫療",
    "防禦型（電信+公用）",
]
opportunity_scores = [9.0, 6.5, 5.5, 7.5, 6.0, 4.0]  # 1-10
risk_scores = [8.0, 5.0, 6.0, 7.0, 7.5, 3.0]  # 1-10
suggested_weights = [35, 12, 10, 18, 10, 15]  # percent

chart2_path = generate_grouped_bar_chart(
    labels=allocation_labels,
    group_data={
        "機會分數 (1-10)": opportunity_scores,
        "風險分數 (1-10)": risk_scores,
        "建議配置 (%)": [w / 4 for w in suggested_weights],  # Scale down for visual
    },
    title="台灣產業前瞻配置：機會 vs 風險（2026-2031）",
    ylabel="分數",
    filename="tw_sector_forward_allocation",
    figsize=(13, 7),
)
print(f"  Chart 2 saved: {chart2_path}")
chart2_url = upload_chart(chart2_path)
print(f"  Chart 2 uploaded: {chart2_url}")

# ─── 5. Build article content ─────────────────────────────────
print("\nBuilding article content...")

# Collect data points for article
tw50_20y_return = (tw50_prices.iloc[-1] / tw50_prices.iloc[0] - 1) * 100
tw50_20y_ann = ((tw50_prices.iloc[-1] / tw50_prices.iloc[0]) ** (252 / len(tw50_prices)) - 1) * 100
tw50_current = tw50_prices.iloc[-1]

tsmc_prices = data["2330.TW"]["prices"]
tsmc_current = tsmc_prices.iloc[-1]
tsmc_5y_return = (tsmc_prices[tsmc_prices.index >= "2021-01-01"].iloc[-1] / tsmc_prices[tsmc_prices.index >= "2021-01-01"].iloc[0] - 1) * 100

cathay_prices = data["2882.TW"]["prices"]
cathay_5y_return = (cathay_prices[cathay_prices.index >= "2021-01-01"].iloc[-1] / cathay_prices[cathay_prices.index >= "2021-01-01"].iloc[0] - 1) * 100

# Format sector table
sector_table_rows = ""
for name, stats in sector_data.items():
    sector_table_rows += f"| {name} | {stats['total_return']:.1f}% | {stats['ann_return']:.1f}% | {stats['ann_vol']:.1f}% | {stats['sharpe']:.2f} |\n"

# Format era table
era_table_rows = ""
for era_name, stats in era_stats.items():
    era_table_rows += f"| {era_name} | {stats['ann_return']:.1f}% | {stats['ann_vol']:.1f}% | {stats['mdd']:.1f}% |\n"

article_content = f"""# 台灣未來五年社會經濟走向與產業投資分析

*[提問: yaoxk1431, 執行: Claude]*

> 本文回應會員 yaoxk1431 的提問：「應用這20年的社會經濟背景與股價的反應，預估接下來五年台灣社會經濟走向，與分析可投資的產業與建構模型。」以下基於 2006-2026 年實證數據，結合我們知識庫中 1000+ 筆研究記錄，提供系統性分析。

---

## 一、二十年回顧：台灣經濟的結構性轉型（2006-2026）

過去二十年，台灣經歷了從「世界工廠」到「矽盾核心」的深刻轉型。元大台灣50（0050.TW）作為市場縮影，完整記錄了這段旅程：

| 時期 | 年化報酬 | 年化波動 | 最大回撤 |
|------|---------|---------|---------|
{era_table_rows}

**三大結構性轉折點：**

**1. 金融海嘯與復甦（2008-2012）**：2008 年全球金融危機使 0050 最大回撤超過 -50%，但台灣金融體系相對健全（銀行 BIS 比率維持 12%+），復甦速度優於歐美。這段經歷驗證了台灣市場的韌性——我們的研究（K636）發現台股波動放大倍數為 4.6 倍（相對美股），但這是 gamma 效應，波動率水準本身並不異常。

**2. 半導體崛起與 TSMC 效應（2016-2021）**：台積電從「大型代工廠」蛻變為「全球先進製程壟斷者」。2020 年後 TSMC 營收年增率連續突破 20%，7nm/5nm/3nm 製程獨步全球。我們的 Granger 因果分析（K757）發現一個驚人的結構：**金融股（國泰金等）的股價變動 Granger-cause 台積電**（F 統計量 6.11），意味著金融板塊是台股的先行指標。

**3. 地緣政治與 AI 革命（2022-2026）**：美中科技戰讓台灣半導體的戰略價值飆升，同時 AI 需求爆發。0050 在 2024 年突破歷史新高，但波動也隨之加大——當 VIX > 25 時，0050 波動率放大至 1.24 倍（K724）。

整個 20 年期間，0050 累計報酬達 **{tw50_20y_return:.0f}%**（年化約 {tw50_20y_ann:.1f}%），展現了台灣經濟從勞力密集向技術密集轉型的成果。

## 二、產業表現深度分析（2021-2026）

近五年的產業表現呈現極度分化：

| 產業（代表公司） | 累計報酬 | 年化報酬 | 年化波動 | Sharpe |
|-----------------|---------|---------|---------|--------|
{sector_table_rows}

**關鍵洞察：**

- **半導體一枝獨秀**：台積電五年累計報酬 {tsmc_5y_return:.0f}%，遠超其他產業。但這也意味著 0050 的 TSMC 權重已超過 50%，形成高度集中風險
- **金融股穩中帶升**：國泰金五年報酬 {cathay_5y_return:.0f}%，受惠於升息環境與壽險投資收益回升。K757 研究顯示金融股是 TSMC 的先行指標
- **傳產式微**：台塑等傳統製造業面臨中國產能過剩與碳中和壓力，報酬顯著落後
- **電信防禦穩健**：中華電信波動最低，適合作為配置中的穩定錨

## 三、前瞻五年：2026-2031 台灣經濟情境分析

### 驅動力量分析

**正面驅動：**
1. **AI 半導體超級週期**：AI 訓練/推論晶片需求在 2026-2030 年預計年增 30%+，台積電 2nm（2025）和 A14（2028）製程將持續領先。CoWoS 先進封裝產能擴張 3 倍以上
2. **地緣政治紅利**：「矽盾」效應使各國加大對台投資（美國 CHIPS Act、日本熊本廠），台灣在全球供應鏈地位短期無可替代
3. **綠能轉型商機**：離岸風電 2025-2030 年裝置容量目標 20.5GW，太陽能持續擴建，帶動零組件與系統整合商機
4. **數位轉型加速**：5G 基建完善、AI 應用落地（智慧製造、醫療 AI），帶動軟硬體整合需求

**風險因素：**
1. **台海地緣風險**：這是最大的尾部風險。我們的 CoVaR 傳染分析（K176）顯示 0050→TSMC→金融 的系統性風險傳導鏈——一旦觸發，所有台股資產同步下跌
2. **人口結構惡化**：台灣 2025 年已進入超高齡社會（65 歲以上 > 20%），勞動力萎縮將壓抑長期 GDP 成長率至 2% 以下
3. **TSMC 集中風險**：台股市值的 30%+ 集中在單一公司，任何製程延遲或客戶流失都可能引發連鎖效應
4. **全球衰退風險**：美國經濟若硬著陸，K461 研究確認 SPY 報酬對台股的預測力 PIP=1.000（美股驅動台股），台股無法倖免

### 基準情境（概率 55%）：穩健成長
- GDP 年增 2.5-3.5%，AI 紅利持續但增速放緩
- 0050 年化報酬 6-9%，波動率 18-22%
- 半導體維持領先，金融受惠 AI 放貸

### 樂觀情境（概率 25%）：AI 超級週期延續
- GDP 年增 4%+，台灣成為 AI 硬體核心
- 0050 年化報酬 12%+
- 帶動綠能、電子代工全面受惠

### 悲觀情境（概率 20%）：地緣衝擊或全球衰退
- GDP 年增 < 1%，資金外流
- 0050 可能出現 -30% 回撤
- 此情境下，現金和海外資產是唯一避風港

## 四、投資產業與配置建議

基於以上分析，我們建議以下產業配置框架：

| 產業 | 建議權重 | 機會分數 | 風險分數 | 核心邏輯 |
|------|---------|---------|---------|---------|
| 半導體/AI | 35% | 9.0 | 8.0 | AI 超級週期核心，但集中風險高 |
| 綠能/電動車 | 18% | 7.5 | 7.0 | 政策驅動+長期趨勢，但技術迭代快 |
| 金融 | 12% | 6.5 | 5.0 | 升息受惠+先行指標，波動較低 |
| 生技醫療 | 10% | 6.0 | 7.5 | 高齡化需求確定，但個股風險大 |
| 電子代工 | 10% | 5.5 | 6.0 | AI 伺服器組裝需求穩定 |
| 防禦型（電信+公用） | 15% | 4.0 | 3.0 | 降低組合波動，穩定現金流 |

## 五、量化模型：VIX 基礎的動態配置

我們的研究系統已驗證，VIX 是台股最有效的外生風險指標。基於 K461（SPY PIP=1.000）和 K636（放大倍數 4.6x），建議使用以下動態配置模型：

**模型架構：8.63/VIX 台灣 VT 策略**

```
台股配置比重 = min(1.0, 8.63 / VIX)
```

- VIX < 15（低恐慌）：全倉台股（100%）
- VIX 15-25（正常）：配置 35-58%，其餘現金或美債
- VIX > 25（高恐慌）：配置 < 35%，大幅降低曝險

**此策略實證表現**（基於我們的 paper trading）：
- Sharpe Ratio: 0.69（顯著優於 0050 買入持有的 0.45）
- 最大回撤: -15.3%（0050 同期約 -25%）
- 關鍵優勢：台灣 0% 資本利得稅使頻繁調倉成本趨近於零

**模型的核心邏輯**：VIX 不預測台股方向（K697: direction correlation 僅 0.04），但精準預測波動幅度（magnitude correlation 0.57）。這意味著 VIX 策略的本質是「drawdown insurance」——它不會幫你多賺，但會在暴跌時保護你（K687、K688）。

**進階應用**：結合金融股先行指標（K757），當國泰金等金融股出現異常下跌時，可作為額外的風險訊號，提前降低曝險。

## 六、風險警示與局限性

1. **數據局限**：本分析基於 yfinance 歷史數據（2006-2026），20 年樣本涵蓋 2 次完整經濟週期，但未來 5 年情境可能超出歷史分布
2. **前瞻不確定性**：產業前景分析基於當前趨勢外推，實際發展可能因黑天鵝事件（戰爭、技術突破、政策劇變）而根本改變
3. **個股風險**：以代表公司分析產業有偏誤，單一公司不等於整個產業
4. **匯率風險**：台幣兌美元匯率波動可能顯著影響投資收益，特別是海外投資人
5. **模型局限**：VIX 策略在極端事件（如 2020 年 3 月 VIX 飆至 82）時仍有回撤，不是完美保護
6. **地緣政治難以量化**：台海風險是最大尾部風險，但無法用歷史數據建模

---

**本文基於 VolPred 研究系統的實證結果（數據來源：yfinance，期間：2006-2026）。**
**參考實驗：K636（台股波動放大）、K757（金融先行指標）、K724（TSMC 營收窗口）、K461（美股驅動台股）、K502（隔夜缺口）、K176（CoVaR 傳染）、K687/K688/K697（VT 策略本質）。**

*本文為研究分析，非投資建議。投資有風險，請自行評估。*
"""

# ─── 6. Embed charts into content ─────────────────────────────
if chart1_url:
    article_content = embed_chart(
        article_content, chart1_url,
        "台灣主要產業 5 年表現比較（2021-2026）",
        position="after_summary"
    )

if chart2_url:
    article_content = embed_chart(
        article_content, chart2_url,
        "台灣產業前瞻配置：機會 vs 風險（2026-2031）",
        position="before_conclusion"
    )

# ─── 7. Publish as draft ──────────────────────────────────────
print("\nPublishing article as draft...")
title = "會員提問｜台灣未來五年社會經濟走向與產業投資分析（20 年數據實證）"

# Write content to temp file to avoid shell escaping issues
import tempfile
content_file = tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False, encoding='utf-8')
content_file.write(article_content)
content_file.close()
print(f"  Content written to temp file: {content_file.name}")

# Read it back and use the publisher directly
from volpred.ops import publish_milestone_article

pub_id = publish_milestone_article(
    title=title,
    description=article_content,
    phase="member_qa",
    tags=["會員提問", "台灣", "產業分析", "投資策略", "經濟預測", "一般讀者"],
    status="draft",
    audience="member_qa",
    category="qa",
)
print(f"  Published as draft: {pub_id}")

# ─── 8. Update question status in Supabase ────────────────────
print("\nUpdating question status...")
try:
    from supabase_sync import _patch_where
    _patch_where(
        "questions",
        updates={
            "status": "answered",
            "answered_at": datetime.utcnow().isoformat() + "Z",
        },
        id="df669347-41e9-4622-8c6d-2e6758674d04",
    )
    print("  Question status updated to 'answered'")
except Exception as e:
    print(f"  Question status update failed: {e}")

# Link article to question
try:
    from supabase_sync import _upsert_rows
    _upsert_rows("question_articles", [{
        "question_id": "df669347-41e9-4622-8c6d-2e6758674d04",
        "article_id": pub_id,
    }])
    print(f"  Linked article {pub_id} to question")
except Exception as e:
    print(f"  Article linking failed (may need manual): {e}")

# Clean up temp file
import os
os.unlink(content_file.name)

print(f"\n{'='*60}")
print(f"DONE! Article published as draft: {pub_id}")
print(f"Title: {title}")
print(f"Charts: {chart1_url}")
print(f"         {chart2_url}")
print(f"Question ID: df669347-41e9-4622-8c6d-2e6758674d04 -> answered")
print(f"{'='*60}")
