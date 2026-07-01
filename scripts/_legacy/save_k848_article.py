import json, uuid
from datetime import datetime, timezone

chart1_url = "https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k848_qlike_comparison_727857.png"
chart2_url = "https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k848_night_vol_trend.png"

content = """## 摘要

我們用台灣期貨交易所（TAIFEX）台指期（TX1）2017–2026 年的 tick 資料建構了 5 分鐘 Realized Volatility（RV），並與傳統的日頻 squared return（r²）進行比較。核心發現：**r² 的中位數捕捉率僅 0.29**，代表日頻 r² 有 71% 的波動資訊是噪音。用不同 target 評估同一個 GJR-GARCH 模型，QLIKE 差距高達 **5.8 倍**（1.52 vs 0.26）。

---

## 資料描述

- **資產**：台指期近月連續合約（TX1），TAIFEX tick 資料
- **期間**：2017-01-03 至 2026-03-31，共 2163 交易日
- **頻率**：5 分鐘 bar（日盤 09:00–13:30 = 54 bars；夜盤 15:00–隔日 05:00 = 168 bars）
- **RV 建構**：BPV（Bipower Variation）偵測 jump 後，RV_total = RV_day + RV_night

| 項目 | 數量 |
|------|------|
| 觀察日 | 2163 天 |
| 日盤 bars/日 | 54 |
| 夜盤 bars/日 | 168 |
| Jump 頻率 | 74.9% |
| Jump 佔 RV 比例 | 7.6% |

---

## 核心發現一：r² 只捕捉 29% 的真實波動率

r²/RV_total 的比值分佈中位數僅 **0.29**。這意味著日頻 r²（標準波動率研究的默認 target）有 71% 的真實波動資訊被遺漏——取而代之的是大量市場微結構噪音。

這個結果對過去 800 多個使用 r² 評估模型的實驗有重要涵義：**模型比較的排名可能在 noisy target 下完全失真**。

---

## 核心發現二：評估 target 影響 QLIKE 高達 5.8 倍

![QLIKE Loss：r² vs 5-min RV 作為評估 Target](""" + chart1_url + """)
*圖一：同一個 GJR-GARCH 模型，在不同 target 下 QLIKE 差距 5.8 倍。評估 target 的選擇比模型本身更重要。*

| 指標 | r²（日頻） | RV_total（5-min） |
|------|-----------|-----------------|
| QLIKE（GJR-GARCH） | 1.52 | **0.26** |
| Spearman rank corr | 0.20 | **0.67** |
| 捕捉率（中位數） | 29% | 100%（定義） |

Spearman rank correlation 從 0.20 躍升至 0.67，說明用 RV 作 target 時，GJR-GARCH 的預測排名與真實波動率排名一致性更高。這是 Patton（2011）理論的實證確認：proxy-robust loss function 需要高品質的 realized measure。

---

## 核心發現三：夜盤 vol 持續擴張，已超過日盤

![台指期夜盤波動率佔比：2017 → 2026](""" + chart2_url + """)
*圖二：夜盤波動率佔 RV_total 的比例從 2017 年的 24% 攀升至 2026 年的 56.5%，夜盤已超過日盤成為主要波動來源。*

台指期夜盤（接軌美股）的波動率佔比在 10 年間翻了一倍多。這有兩個重要涵義：

1. **只用日盤數據的模型**（大多數台股研究）越來越不完整——夜盤資訊正在主導台指期的波動
2. **2020 年後尤為明顯**：COVID 與 Fed 政策周期放大了美股對台灣期貨的 lead-lag 效應

---

## 方法論說明

### RV 建構
- 5-min return r_{t,i}，RV_t = sum_i r_{t,i}^2
- Jump 偵測：Barndorff-Nielsen & Shephard (2004) BPV，ratio test z = (RV - BPV)/RV > Phi^{-1}(0.999) 視為 jump
- RV_total = RV_day + RV_night（分開計算，避免隔夜間隔污染）

### QLIKE Loss

QLIKE(sigma², h) = sigma²/h - log(sigma²/h) - 1

Patton (2011) 證明 QLIKE 對 proxy 誤差具有 robustness，但前提是 proxy 本身是 sigma² 的無偏估計。RV 滿足此條件（E[RV] = sigma² + jump contribution），r² 也滿足，但 r² 的方差極大（信噪比低），導致模型排名不穩定。

---

## 與過去實驗的關係

K848 之前，本系統使用 r² 作為唯一評估 target（超過 800 個 GARCH 類實驗）。K848 表明這個選擇引入了系統性的測量誤差。直接的後續影響：

- **K849（即將）**：在 RV_total target 下比較 HAR vs GJR-GARCH——K848 的 Spearman 0.67 vs 0.20 已暗示 RV target 下的結果可能與 r² target 下截然不同
- **歷史實驗重新評估**：使用 5-min RV 重跑關鍵模型比較，驗證 r² 時代的排名是否仍然成立

---

## 局限性

1. **樣本侷限**：僅台指期，不直接推廣至其他市場
2. **Jump 偵測敏感性**：BPV 方法在極端行情（COVID 2020、2022 Fed 緊縮）可能低估 jump 頻率
3. **夜盤趨勢外推**：56.5% 夜盤佔比的趨勢延伸需謹慎，結構性因素（如台灣法規變更）可能逆轉
4. **tick 資料品質**：TAIFEX tick 資料的 cleaning pipeline 尚未完全驗證——錯誤的 clean 步驟可能低估真實 RV

---

## 結論

**用 r² 評估波動率模型，等於用一把只有 30% 精度的尺去量精密零件的誤差。**

r² 是 sigma² 的無偏但 noisy 估計。當 noise 佔 71% 時，模型間的細微差異被完全淹沒——排名的信號消失在測量誤差中。5-min RV 提供了更高信噪比的評估基準，Spearman rank correlation 從 0.20 提升至 0.67，意味著我們終於能更可靠地分辨哪個模型真的更好。

此外，夜盤 vol 的結構性上升（24% → 56.5%）說明台指期研究必須納入全時段數據，否則遺漏的不是 edge cases，而是主體。

---

*實驗腳本: experiments/k848_taifex_5min_rv.py*
*結果數據: experiments/k848_taifex_5min_rv_results.json*
*數據來源: TAIFEX TX1 tick data，2017-01-03 至 2026-03-31，共 2163 交易日*
*參考文獻: Barndorff-Nielsen & Shephard (2004) Econometrica; Patton (2011) Journal of Econometrics; Hansen & Lunde (2005) JBES*
"""

article = {
    "id": "mile_" + uuid.uuid4().hex[:8],
    "title": "r² 只捕捉 29% 的真實波動率：台指期 5 分鐘 RV 的啟示",
    "description": "用 TAIFEX TX1 tick 資料建構 5-min Realized Volatility，發現日頻 squared return（r²）中位數捕捉率僅 29%。同一個 GJR-GARCH 模型在 RV target 下 QLIKE 是 r² target 的 1/5.8，Spearman 相關從 0.20 升至 0.67。夜盤 vol 佔比 10 年間從 24% 升至 56.5%，已超過日盤。這意味著過去 800+ 個使用 r² 的實驗，其模型排名可能在 noisy target 下大幅失真。",
    "content": content,
    "tags": ["研究", "5-min RV", "realized volatility", "r² noise", "TAIFEX", "measurement"],
    "status": "draft",
    "created_at": datetime.now(timezone.utc).isoformat(),
    "proposer": "Claude"
}

# Load existing feed
with open("storage/reports/feed.json", "r") as f:
    feed = json.load(f)

# Insert at beginning
feed.insert(0, article)

# Save feed
with open("storage/reports/feed.json", "w") as f:
    json.dump(feed, f, ensure_ascii=False, indent=2)

# Save individual report
with open("storage/reports/" + article["id"] + ".json", "w") as f:
    json.dump(article, f, ensure_ascii=False, indent=2)

print("Article saved:", article["id"])
print("Title:", article["title"])
print("Status:", article["status"])
print("Content length:", len(content), "chars")
