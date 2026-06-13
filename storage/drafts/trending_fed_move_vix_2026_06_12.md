---
title: "降息交易退了，MOVE 也退了：為什麼 VIX 還停在 19？"
audience: general
status: published
tags:
  - Fed
  - MOVE
  - VIX
  - rates
  - cross-asset
  - trending
description: "2026-06-11 收盤，MOVE 69.45 只在 2003 年以來 P34，VIX 19.44 卻在 P65；MOVE/VIX 比值 3.57，落在歷史 P19。這篇用短端 Fed Funds 期貨、債市波動率與股市波動率拆解降息交易撤退後的跨資產不同步。"
task_type: trending_repost
experiment_refs:
  - trending_2026_06_12_fed_move_vix
phase: event_driven
category: market-analysis
image_url: experiments/trending_2026_06_12_fed_move_vix/fig_1_move_vix_normalized_1y.png
---

# 降息交易退了，MOVE 也退了：為什麼 VIX 還停在 19？

2026-06-11 收盤，近月 Fed Funds 期貨 `ZQ=F` 隱含利率約 3.65%，五個交易日前是 3.62%。這不是完整的 CME FedWatch 機率表，只能當作短端利率定價方向。但方向很清楚：市場沒有在替近期大幅降息定價。

照直覺，降息交易退場，債市波動率應該維持高檔。實際數字剛好相反。MOVE 收 69.45，落在 2003 年以來第 34 百分位；VIX 收 19.44，落在第 65 百分位。債市恐慌已經退到偏低位置，股市端還沒有。

## 先看四個數字

| 指標 | 2026-06-11 收盤 | 5 日變化 | 歷史位置 |
|---|---:|---:|---:|
| VIX | 19.44 | +26.23% | 2003 以來 P65 |
| MOVE | 69.45 | -2.41% | 2003 以來 P34 |
| MOVE/VIX | 3.57 | -22.69% | 2003 以來 P19 |
| 近月 Fed Funds 期貨隱含利率 | 3.65% | +3.25 bp | 僅作短端方向參考 |
| SPY | 737.76 | -2.55% | 價格指標 |
| TLT | 85.98 | +0.56% | 價格指標 |

同一週內，VIX 漲了 26.23%，MOVE 反而跌了 2.41%。MOVE/VIX 比值從 4.62 壓到 3.57，五個交易日下降 22.69%。這組數字比單看任何一個指標更重要：增量保費集中在股指選擇權，利率選擇權沒有同步追高。

![近一年 MOVE 與 VIX 標準化走勢](experiments/trending_2026_06_12_fed_move_vix/fig_1_move_vix_normalized_1y.png)

近一年標準化後，VIX 的尖峰比 MOVE 更密集。三月以後尤其明顯：債市波動率從高位回落，股市波動率仍反覆跳升。這代表市場現在更怕「事件如何打到股票現金流與風險偏好」，不是單純怕「Fed 會不會改利率」。

## MOVE/VIX 的座標：現在不是債市過度恐慌

MOVE/VIX 比值 3.57，落在全樣本第 19 百分位，近一年也只有第 21 百分位。2003 年以來中位數是 4.78。用 VIX 作比較基準，MOVE 目前在偏低端。

![MOVE/VIX 比值歷史位置](experiments/trending_2026_06_12_fed_move_vix/fig_2_move_vix_ratio_history.png)

這個位置對交易敘事有直接約束。「利率不確定性太高，所以股市應該更怕」這種敘事，要先解釋為什麼 MOVE/VIX 已經掉到 P19。至少到 6/11 收盤為止，市場沒有把債市波動率定成主要壓力源。

20 日 MOVE 與 VIX 日變化相關係數是 0.37，60 日是 0.48，全樣本是 0.29。兩者仍有關係，但短期同步性不足以支持「債市恐慌自動外溢到股市恐慌」這種直線推論。

## 這代表什麼

比較合理的讀法是分三層。

第一，短端利率路徑變得比較鈍。近月 Fed Funds 期貨隱含利率五日只上移約 3.25 bp，13 週 T-bill yield 收在 3.623%。這不像市場在重估一個大型降息循環，更像是把近期政策路徑重新錨定在「不急著降」。

第二，債市波動率已經先冷卻。MOVE 69.45 低於歷史中位，也低於近一年多數交易日。這表示利率選擇權市場沒有替下一個月的利率路徑付出很高保費。

第三，股市波動率還留著事件溢價。VIX 19.44 在歷史 P65，SPY 五日跌 2.55%。Fed、成長、地緣風險與估值一起進入股指選擇權價格，單一利率路徑解釋不了這個 VIX 水位。

後面只有兩種收斂方式：VIX 往下補跌，回到 MOVE 已經走出的冷卻路徑；或 MOVE 重新上升，代表利率路徑又變得不穩。現在的數字比較支持第一種壓力較大，但這不是預測，只是當前相對價的位置。

## 樣本限制與資料來源

這篇是描述性分析，不是交易回測。`ZQ=F` 是 Yahoo Finance 的 generic Fed Funds futures proxy，用來看短端定價方向；正式 FOMC 目標區間機率應以 [CME FedWatch](https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html) 為準。VIX 定義參考 [Cboe VIX methodology](https://cdn.cboe.com/resources/indices/Volatility_Index_Methodology_Cboe_Volatility_Index.pdf)，MOVE 定義參考 [ICE MOVE Index](https://developer.ice.com/fixed-income-data-services/catalog/ice-data-indices-move-index)。

資料來自 yfinance：`^VIX`、`^MOVE`、`SPY`、`TLT`、`^TNX`、`^IRX`、`ZQ=F`、`ZN=F`。樣本從 2003-01-02 到 2026-06-11，共 5,796 個 MOVE/VIX 共同交易日。完整腳本、CSV、結果 JSON 與兩張圖在 `experiments/trending_2026_06_12_fed_move_vix/`。
