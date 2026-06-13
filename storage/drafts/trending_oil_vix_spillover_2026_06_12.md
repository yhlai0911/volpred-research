---
title: "中東風險還在，OVX/VIX 卻從 4.17 降到 2.90：油市恐慌怎麼外溢？"
audience: general
status: published
tags:
  - OVX
  - VIX
  - crude-oil
  - geopolitics
  - spillover
  - trending
description: "5/20 之後，OVX 從 72.77 降到 56.30，VIX 從 17.44 升到 19.44，OVX/VIX 比值從 4.17 壓到 2.90。這篇用 2007-2026 的 OVX/VIX/油價資料檢查中東風險如何外溢到股市波動率。"
task_type: trending_repost
experiment_refs:
  - trending_2026_06_12_oil_vix_spillover
phase: event_driven
category: market-analysis
image_url: https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/fig_1_oil_vix_2026_path.png
---

# 中東風險還在，OVX/VIX 卻從 4.17 降到 2.90：油市恐慌怎麼外溢？

5/20 我們看過一次 Iran war 下的 OVX/VIX 斷裂：OVX 72.77，VIX 17.44，OVX/VIX 比值 4.17。當時的重點是油市恐慌比股市恐慌高很多。

三週後，數字變了。2026-06-11 收盤，OVX 降到 56.30，VIX 升到 19.44，OVX/VIX 比值剩 2.90。原油端還很緊，Brent 89.45、WTI 86.86；但初期那種「油市單邊恐慌、股市相對平靜」的形狀已經收斂。

這篇只問一件事：油市波動率到底有沒有外溢到 VIX？

## 從 5/20 到 6/11，收斂怎麼發生

| 指標 | 2026-05-20 | 2026-06-11 | 變化 | 6/11 歷史位置 |
|---|---:|---:|---:|---:|
| OVX | 72.77 | 56.30 | -22.63% | 2007 以來 P91 |
| VIX | 17.44 | 19.44 | +11.47% | 2007 以來 P60 |
| OVX/VIX | 4.17 | 2.90 | -30.59% | 2007 以來 P90 |
| WTI | 98.26 | 86.86 | -11.60% | 2007 以來 P71 |
| Brent | 105.02 | 89.45 | -14.83% | 2007 以來 P69 |
| SPY | 741.25 | 737.76 | -0.47% | 價格接近高位 |

這不是油市風險消失。OVX 56.30 還在 2007 年以來第 91 百分位，OVX/VIX 比值 2.90 也在第 90 百分位。油市保費仍高。

真正改變的是方向。5/20 之後，OVX 跌 22.63%，VIX 反而升 11.47%。外溢如果存在，現在更像是「油市極端保費回落，股市端補上一些事件保費」，不是 OVX 繼續把 VIX 往上拉。

![2026 年 OVX、VIX、WTI、Brent 標準化走勢](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/fig_1_oil_vix_2026_path.png)

圖上最重要的是 5/20 之後那段。油價與 OVX 往下，VIX 在 6/5 與 6/10 兩次跳升。這表示股市恐慌的近期上升，不能只用原油價格或原油選擇權波動率解釋。

## 外溢比較像同日風險調整，不像隔日預測訊號

如果原油波動率真的穩定外溢到股市，最簡單的檢查是相關係數。結果很克制。

| 視窗 | OVX 與 VIX 同日相關 | WTI 與 VIX 同日相關 | OVX_t 對 VIX_t+1 | WTI_t 對 SPY_t+1 |
|---|---:|---:|---:|---:|
| 20 日 | 0.10 | 0.09 | 0.00 | 0.10 |
| 60 日 | 0.40 | 0.33 | -0.08 | 0.08 |
| 120 日 | 0.39 | 0.33 | -0.00 | 0.01 |
| 252 日 | 0.39 | 0.24 | -0.05 | 0.02 |

60 日同日相關有 0.40，代表同一天的 risk-off 交易會讓 OVX 與 VIX 一起動。這個部分合理：地緣政治升溫時，油市、股市、利率、美元都會同時重定價。

隔日關係就很弱。60 日的 `OVX_t → VIX_t+1` 相關是 -0.08，`WTI_t → SPY_t+1` 是 0.08。這組數字不支持「今天油市波動率上升，明天股市波動率會跟著上升」的簡單規則。

![油市到股市的同日與隔日相關](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/fig_2_spillover_correlations.png)

## 目前比較像三條路徑同時存在

第一條是油市本身。OVX 仍在 P91，代表原油選擇權市場還在替供應中斷付高保費。中東風險沒有被市場關掉。

第二條是股市事件保費。VIX 19.44 在 P60，五個交易日上升 26.23%。但同一段時間 OVX 跌 5.84%，WTI 跌 6.64%，Brent 跌 5.87%。這個 VIX 上升比較像股市自己的事件組合，不是油價單獨推動。

第三條是通膨與利率通道。油價若再往上衝，會先打到通膨預期，再進入央行反應函數，最後才影響股市折現率與獲利預期。這條路徑比較慢，也比較依賴持續性。單日油價跳動不夠，市場要看到供應中斷變成通膨壓力。

所以現在的讀法是：油市風險仍然高，但對股市的即時外溢已經弱化。真正要盯的是 OVX 能不能重新站回 70 以上，以及 WTI/Brent 是否回到 5 月高點附近。如果兩者都沒有，VIX 的下一段上升更可能來自股市自己的風險，而不是原油單一路徑。

## 樣本限制與資料來源

這篇是描述性 spillover 檢查，不是因果模型，也不是交易訊號。相關係數只用來避免過度宣稱。`^OVX` 是 Cboe Crude Oil ETF Volatility Index proxy，定義可參考 [FRED OVXCLS](https://fred.stlouisfed.org/series/OVXCLS) 與 [Cboe OVX dashboard](https://www.cboe.com/us/indices/dashboard/ovx/)。油價與地緣風險背景可參考 [CME WTI 2026-06-10 市場說明](https://www.cmegroup.com/videos/2026/06/10/wti-crude-oil-futures-climbed-past-91-amid-middle-east-conflict.html)。

資料來自 yfinance：`^OVX`、`^VIX`、`CL=F`、`BZ=F`、`USO`、`XLE`、`SPY`、`^TNX`、`DX-Y.NYB`。樣本從 2007-07-30 到 2026-06-11，共 4,693 個共同交易日。完整腳本、CSV、結果 JSON 與兩張圖在 `experiments/trending_2026_06_12_oil_vix_spillover/`。
