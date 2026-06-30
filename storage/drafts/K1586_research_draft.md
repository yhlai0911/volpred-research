---
title: "K1586：穩定幣儲備變化與短端 T-bill realized vol 的領先性檢定"
audience: research
status: draft
phase: research
tags: [穩定幣, 短期公債, USDC, SVB, Granger, event study, SHY, BIL]
experiment_refs: [K1586]
description: "K1586 檢驗 USDT、USDC、DAI 市值變化是否領先 DGS1MO/DGS3MO realized vol，並分別處理 USDC-SVB depeg 與 GENIUS Act 事件窗。"
image_url: experiments/K1586/figures/svb_event_study.png
---

# K1586：穩定幣儲備變化與短端 T-bill realized vol 的領先性檢定

## 摘要

K1586 檢驗穩定幣儲備變化是否能預測短端美債波動，並把問題拆成三個層次：日頻 lead-lag、USDC-SVB depeg event study、GENIUS Act 事件窗診斷。樣本期間為 2020-04-06 至 2026-06-26，共 1557 個 business days；資料來源為 DefiLlama free、FRED CSV 與 yfinance。

整體結論是 `NULL_PARTIAL`。H1 的 lead-lag 假設為 NULL：DGS1MO_RV 與 DGS3MO_RV 的所有 lag-target Granger p-value 全部大於 0.29，穩定幣市值變化沒有提供可採信的 incremental predictability。H2 在 USDC-SVB 事件中只對 SHY 通過：event mean absolute return 為 37.2406 bps，control 為 13.1759 bps，ratio 為 2.8264，Welch t 為 2.7518，Bonferroni p 為 0.0383，block-bootstrap Bonferroni p 為 0.0228。H3 的 GENIUS Act 事件窗只能作描述性診斷；DGS1MO_RV 上升、DGS3MO_RV 下降，方向分裂比較像同時期 regime change，不能寫成法案的因果效應。

## 研究背景

穩定幣儲備和短期美債市場之間有自然的研究連結：大型 USD-pegged stablecoin 需要持有現金或短期安全資產，儲備流入與流出可能改變短端工具的需求壓力。K1586 的問題不放在敘事層，而是直接檢定三個可驗證假設。

第一，穩定幣總市值變化是否領先 DGS1MO 與 DGS3MO 的 realized vol。第二，USDC-SVB depeg 這種壓力事件是否讓短端 ETF 的 realized movement 明顯放大。第三，GENIUS Act 簽署日附近是否有可觀察的短端波動變化；這一層只做事件窗描述，不把政策事件解讀成結構因果。

K1586 的價值在於把同一個主題分成「可預測性」、「壓力事件反應」與「政策事件診斷」。三者回答的問題不同，統計證據也不能互相替代。

## 方法與數據

| 項目 | 設定 |
|------|------|
| 實驗編號 | K1586 |
| 樣本期間 | 2020-04-06 至 2026-06-26 |
| 樣本數 | 1557 個 business days |
| 隨機種子 | 42 |
| 穩定幣資料 | DefiLlama free，USDT + USDC + DAI 市值 |
| 利率資料 | FRED CSV，DGS1MO 與 DGS3MO |
| ETF 資料 | yfinance，SHY 與 BIL |
| RV 定義 | 22-day trailing rolling std |
| H1 predictor | `sb_dlog`，即三大穩定幣總市值日對數差分 |
| H1 lookahead 控制 | predictor 使用 `shift(k>=1)`，不做 contemporaneous regression |
| H2 event date | 2023-03-10，USDC-SVB depeg |
| H2 event window | event date ±5 business days，event_n = 11 |
| H2 control window | ±30 business days 中排除 ±5，control_n = 50 |
| H2 檢定 | Welch t-test，兩檔 ETF Bonferroni correction；block bootstrap n_boot = 5000，block_size = 5 |
| H3 event date | 2025-07-18，GENIUS Act |

H1 對 DGS1MO_RV 與 DGS3MO_RV 各跑 lag 1 至 lag 5。Pearson correlation 與 HAC OLS 只作關聯與 effect size 參考；H1 verdict 依 Granger F-test 判定，因為 Granger specification 控制 response 自身落後項後，才測穩定幣變化是否增加預測力。

![Lead-lag correlation](experiments/K1586/figures/leadlag_corr.png)

## 核心發現

### 發現一：H1 lead-lag 為 NULL，HAC OLS 只能讀成 marginal association

DGS1MO_RV 的 Granger p-value 從 lag 1 到 lag 5 分別為 0.4453、0.6902、0.8472、0.8612、0.9379。DGS3MO_RV 的對應數值為 0.4480、0.3687、0.3129、0.3740、0.2921。所有 lag-target 組合全部大於 0.29，沒有任何一組接近 0.05。

| Target | Lag | Pearson corr | n | HAC beta | HAC t-stat | HAC p-value | Granger F | Granger p-value |
|--------|-----|--------------|---|----------|------------|-------------|-----------|-----------------|
| DGS1MO_RV | 1 | -0.1401 | 1556 | -74.0623 | -4.0854 | 0.0000440 | 0.5828 | 0.4453 |
| DGS1MO_RV | 2 | -0.1405 | 1555 | -74.2276 | -4.0873 | 0.0000436 | 0.3708 | 0.6902 |
| DGS1MO_RV | 3 | -0.1395 | 1554 | -73.7340 | -4.0777 | 0.0000455 | 0.2698 | 0.8472 |
| DGS1MO_RV | 4 | -0.1412 | 1553 | -74.6052 | -4.0824 | 0.0000446 | 0.3252 | 0.8612 |
| DGS1MO_RV | 5 | -0.1409 | 1552 | -74.4588 | -4.0941 | 0.0000424 | 0.2540 | 0.9379 |
| DGS3MO_RV | 1 | -0.1780 | 1556 | -43.1809 | -4.1146 | 0.0000388 | 0.5760 | 0.4480 |
| DGS3MO_RV | 2 | -0.1806 | 1555 | -43.7556 | -4.1201 | 0.0000379 | 0.9985 | 0.3687 |
| DGS3MO_RV | 3 | -0.1835 | 1554 | -44.4311 | -4.1353 | 0.0000355 | 1.1880 | 0.3129 |
| DGS3MO_RV | 4 | -0.1859 | 1553 | -44.9887 | -4.1295 | 0.0000364 | 1.0618 | 0.3740 |
| DGS3MO_RV | 5 | -0.1900 | 1552 | -45.9357 | -4.2388 | 0.0000225 | 1.2308 | 0.2921 |

HAC OLS 的 t-stat 約落在 -4.08 至 -4.24，表面上很穩定，但該 specification 沒有控制 lagged realized vol。K1586 因此把 HAC OLS 定位為 marginal association only。可採信的 H1 判準仍是 Granger F-test；依該判準，穩定幣市值變化沒有預測 DGS1MO_RV 或 DGS3MO_RV。

### 發現二：H2 只在 SHY 通過，BIL 為 NULL

USDC-SVB depeg 的 event study 結果集中在 SHY。SHY event window 的平均絕對日報酬為 37.2406 bps，control window 為 13.1759 bps，ratio = 2.8264。Welch t-stat = 2.7518，原始 p-value = 0.0191，Bonferroni p = 0.0383。加入 block bootstrap 後，two-sided p = 0.0114，Bonferroni p = 0.0228。這組結果同時通過 Welch 與 block-bootstrap gate。

BIL 沒有通過。BIL event window 平均絕對日報酬為 2.2825 bps，control window 為 1.9490 bps，ratio = 1.1711。Welch t-stat = 0.6490，原始 p-value = 0.5254，Bonferroni p = 1.0000；block-bootstrap two-sided p = 0.4402，Bonferroni p = 0.8804。

![USDC-SVB event study](experiments/K1586/figures/svb_event_study.png)

| ETF | event_n | control_n | Event mean abs bps | Control mean abs bps | Ratio | Welch t | Welch p | Bonferroni p | Bootstrap p | Bootstrap Bonferroni p | Verdict |
|-----|---------|-----------|--------------------|----------------------|-------|---------|----------|---------------|-------------|-------------------------|---------|
| SHY | 11 | 50 | 37.2406 | 13.1759 | 2.8264 | 2.7518 | 0.0191 | 0.0383 | 0.0114 | 0.0228 | PASS |
| BIL | 11 | 50 | 2.2825 | 1.9490 | 1.1711 | 0.6490 | 0.5254 | 1.0000 | 0.4402 | 0.8804 | NULL |

這個分裂很重要。SHY 是 1-3 年期 Treasury ETF，BIL 是 1-3 個月 T-bill ETF。USDC-SVB 事件在 SHY 的 absolute return 上有顯著放大，在 BIL 上沒有；比較保守的讀法是「壓力事件可能反映在較長短端 duration 的 ETF movement」，而非「穩定幣壓力必然推升所有短端 T-bill 波動」。

### 發現三：H3 GENIUS Act 只作描述性事件窗

GENIUS Act 事件日設定為 2025-07-18，位於 K1586 樣本內。DGS1MO_RV 的 event mean 為 3.8921，control mean 為 2.8077，Welch t-stat = 5.1554，p-value = 0.0000098068。DGS3MO_RV 的 event mean 為 1.0102，control mean 為 1.8748，Welch t-stat = -10.2438，p-value = 0.000000000000016566。

| Target | event_n | control_n | Event mean RV | Control mean RV | Welch t | p-value | Direction |
|--------|---------|-----------|---------------|-----------------|---------|---------|-----------|
| DGS1MO_RV | 11 | 50 | 3.8921 | 2.8077 | 5.1554 | 0.0000098068 | Up |
| DGS3MO_RV | 11 | 50 | 1.0102 | 1.8748 | -10.2438 | 0.000000000000016566 | Down |

DGS1MO_RV 上升、DGS3MO_RV 下降，方向 split 明顯。K1586 因此不把 H3 解讀成 GENIUS Act 的 law effect。合理寫法是：事件窗附近短端曲線不同 maturity 的 realized vol 發生方向相反的變化，較符合 coincident regime change 的描述性診斷。

## 實務意義

第一，K1586 不支持把穩定幣總市值日變化直接納入短端利率 RV 的日頻預測模型。H1 的 HAC OLS 看起來有穩定負向係數，但 Granger p-value 全部不過；若要做交易或風控 predictor，應以 Granger 結果為準，避免把 marginal association 當成可交易訊號。

第二，壓力事件可以保留為 risk-monitoring feature。USDC-SVB event study 顯示 SHY 的 absolute return 在事件窗內顯著放大，且 block bootstrap 後仍通過 Bonferroni gate。這比較適合用在事件風險標記、壓力情境設定或模型 residual 解釋，不適合延伸成穩定幣日變化可穩定預測短端波動的結論。

第三，BIL 的 NULL 提醒研究設計要分 maturity。若把 SHY 與 BIL 合併成「短端美債」單一籃子，會掩蓋 1-3 年與 1-3 個月工具在事件反應上的差異。後續研究若要測 reserve flow 對 Treasury market 的影響，需要把 bill、front-end note 與 ETF proxy 分開處理。

## 限制與穩健性

K1586 的 lookahead 控制是明確的：H1 predictor 使用 `shift(k>=1)`，response 是 t 日的 trailing 22-day RV，`forward_label` 為 false。H2 的 block bootstrap 使用 seed = 42、n_boot = 5000、block_size = 5，目的是降低 volatility clustering 對 Welch t-test 的影響。

主要限制有三項。第一，H1 使用 USDT + USDC + DAI 的總市值日對數差分，沒有拆 reserve composition、發行商資產配置或跨鏈流量。第二，H2 是單一事件 study，USDC-SVB depeg 的樣本只提供 11 個 event-window observations；即使 SHY 通過檢定，也不能外推到所有 stablecoin stress。第三，H3 沒有識別設計，事件窗同時可能受到其他利率、政策預期與流動性因素影響；方向分裂本身已經足以阻止因果敘事。

穩健性上，H1 的所有 Granger 檢定一致為 NULL，這支持「沒有日頻 lead-lag predictability」的結論。H2 的 SHY 同時通過 Welch Bonferroni 與 block-bootstrap Bonferroni，支持「USDC-SVB event window 中 SHY movement 放大」的窄結論。BIL 與 H3 的結果則要求降級處理，不應併入同一個強敘事。

## 結論

K1586 的核心訊息是分層後的 `NULL_PARTIAL`。穩定幣總市值日變化沒有 Granger 領先 DGS1MO_RV 或 DGS3MO_RV；H1 為 NULL。USDC-SVB depeg event study 在 SHY 上通過，event mean abs return 為 37.2406 bps，control 為 13.1759 bps，ratio 為 2.8264，Welch t = 2.7518，Bonferroni p = 0.0383，block-bootstrap Bonferroni p = 0.0228；BIL 則為 NULL，ratio = 1.1711，Welch Bonferroni p = 1.0000，bootstrap Bonferroni p = 0.8804。

對研究計畫而言，K1586 不應被寫成「穩定幣儲備可預測短端 T-bill 波動」。更精確的表述是：日頻 lead-lag predictability 不成立，但特定 stablecoin stress event 可能對 SHY 這類較長短端 duration ETF 的 realized movement 有可測反應。GENIUS Act 事件窗僅提供描述性訊號，DGS1MO_RV 與 DGS3MO_RV 方向相反，不能主張法案造成短端波動變化。

*本文基於實驗 K1586（腳本：`experiments/K1586/K1586.py`，結果：`experiments/K1586/K1586_results.json`）。資料來源：DefiLlama free、FRED CSV、yfinance。期間：2020-04-06 至 2026-06-26。樣本：1557 個 business days。*
