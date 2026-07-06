---
title: "K1590：MNA 併購套利波動 proxy 的描述性診斷"
audience: research
status: draft
phase: research
tags: [併購套利, MNA, VIX, proxy, Welch, lookahead, volatility]
experiment_refs: [K1590]
description: "K1590 檢驗 IQ Merger Arbitrage ETF (MNA) 是否能作為併購套利 deal-spread volatility 的公開 proxy。結果為 GO for Phase 2，但只限描述性診斷，不能升級成預測、因果或交易宣稱。"
image_url: https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/mna_vol_vs_vix.png
---

# K1590：MNA 併購套利波動 proxy 的描述性診斷

## 摘要

K1590 問一個很窄的研究問題：用公開可下載的 IQ Merger Arbitrage ETF (MNA) 日資料，能不能替昂貴的個別 deal-spread database 提供一個 portfolio-level volatility proxy。實驗使用 yfinance adjusted close，`auto_adjust=False`，tickers 為 MNA、SPY、IWM、HYG、^VIX；results.json 記錄的 request window 為 2020-01-01 至 2026-07-01，MNA return sample 為 1629 個交易日，random seed 為 42。

診斷結果給出 `GO`，但口徑只到 Phase 2 gate。高 VIX 日的 MNA 絕對日對數報酬均值為 0.00640896487954151，低 VIX 日為 0.0021013888263734398，high/low ratio 為 3.0498710182075395。Welch two-sample t-test 的 t-stat 為 5.131558387537391，p-value 為 8.788855818933238E-7。用 t-1 VIX 分類 day-t MNA 絕對報酬的 robustness check 仍通過，t-stat 為 4.770461360726556，p-value 為 0.0000043260491685067335。

這些數字支持一個保守結論：MNA 值得進入下一階段的併購套利波動研究。它沒有支持三個更強宣稱：個別併購案破局預測、反壟斷因果效應、可交易的樣本外 alpha。

![MNA realized volatility and VIX level](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/mna_vol_vs_vix.png)

## 研究問題

併購套利的核心風險是 deal-break risk。現金收購案宣布後，target price 和 offer price 之間的 spread 會反映交易完成機率、資金成本、監管阻力與時間價值。真正理想的資料是逐筆交易的 target price、offer price、公告日、審查文件與完成日；這類資料多半來自 Bloomberg、Refinitiv 或專門 M&A feed。

K1590 採用較低成本的替代路徑：觀察 MNA 這檔 merger-arbitrage ETF 的日報酬分布。若 MNA 只是在跟著 SPY 或 HYG 移動，portfolio-level proxy 就沒有研究價值；若它在壓力狀態下有明顯不同的 tail shape 與 regime sensitivity，Phase 2 才值得投入個別 deal data 工程。

這個研究設計的 gate 很明確：

| Gate | results.json 欄位 | 通過條件 | K1590 結果 |
|---|---:|---:|---:|
| 高低 VIX regime 差異 | `vol_regime_test.p_value` | p < 0.05 | 8.788855818933238E-7 |
| 放大倍數 | `magnitude_ratio_high_over_low` | ratio >= 1.5 | 3.0498710182075395 |
| 不是 SPY clone | `pearson_mna_spy` | Pearson < 0.9 | 0.5170433823391993 |

三個 gate 都通過，所以 verdict 為 `GO`。Codex review 的口徑是 `CONDITIONAL_PASS`：可作 Phase 2 diagnostic gate，不可作 forecast、causal antitrust 或 trading claim。

## 方法與樣本

K1590 的 pipeline 很短，優點是容易審查：

| 項目 | 設定 |
|---|---|
| 實驗 ID | K1590 |
| 資料來源 | yfinance adjusted close，`auto_adjust=False` |
| Tickers | MNA / SPY / IWM / HYG / ^VIX |
| results.json request window | 2020-01-01 至 2026-07-01 |
| MNA return sample | 1629 trading days |
| 隨機種子 | 42 |
| 核心變數 | MNA daily log return 的絕對值 |
| Regime 分類 | VIX < 20、20 <= VIX <= 30、VIX > 30 |
| 主要檢定 | Welch two-sample t-test on `abs(MNA daily log return)` |
| Robustness | t-1 VIX classification 對 day-t `abs(MNA return)` |

主要檢定用同日 VIX close 分類同日 MNA 絕對報酬。這個設定適合做描述性 regime split，因為問題是「高 VIX 狀態下 MNA 的日震盪是否較大」。如果讀者把它改讀成「昨天看到 VIX 後預測今天 MNA」，同日分類就會有 lookahead 風險。因此 K1590 同時報告 lag-1 VIX classification：用 t-1 的 VIX 狀態分類 day-t 的 MNA 絕對報酬。lagged robustness 的 p-value 為 0.0000043260491685067335，代表描述性 pattern 沒有完全依賴同日分類。

這裡沒有 DM test，因為沒有兩個 forecast model 的 OOS loss series。這裡也沒有 Harvey multiple-testing correction，因為 K1590 不是一組策略搜尋或多模型 forecast horse race。文章若把 t-test 的 p-value 寫成 Harvey-pass forecast evidence，就會超出實驗設計。

## 核心發現

### 發現一：MNA 在高 VIX regime 的日震盪明顯放大

results.json 的 `vol_regime_test` 欄位直接記錄了主要比較：

| Regime | n | mean abs return | std abs return |
|---|---:|---:|---:|
| VIX < 20 | 924 | 0.0021013888263734398 | 0.0019031318886444403 |
| VIX > 30 | 149 | 0.00640896487954151 | 0.01021799016865489 |

high/low magnitude ratio 為 3.0498710182075395。這個效果量足夠大，通過預先設定的 >= 1.5 gate。Welch t-stat 為 5.131558387537391，p-value 為 8.788855818933238E-7。

用 t-1 VIX classification 的 robustness 也保留方向與統計強度：n_low 為 923，n_high 為 149，t-stat 為 4.770461360726556，p-value 為 0.0000043260491685067335。這個 lagged check 是本文最重要的 lookahead 防線。

![MNA regime bars](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/mna_regime_bars.png)

### 發現二：MNA 不像單純 SPY clone

單看「高 VIX 日所有風險資產波動放大」沒有太多研究價值。K1590 因此加入 non-clone gate：MNA 對 SPY 的 Pearson correlation 必須低於 0.9。results.json 的 verdict_reasoning 記錄 `pearson_mna_spy = 0.5170433823391993`，通過 gate。

相關矩陣也提供了幾個輔助觀察：MNA 對 IWM 的 Pearson correlation 為 0.5369，對 HYG 為 0.4873，對 VIX return 為 -0.3166，對 VIX level 為 -0.103。MNA 明顯仍受 equity / credit / volatility regime 影響，但沒有高到可直接視為 SPY 的低 beta version。

### 發現三：tail shape 比 correlation 更像併購套利 payoff

full-sample stats 記錄 MNA 的 skew 為 -2.888390752010034，excess kurtosis 為 66.40310870790032。同期 SPY 的 skew 為 -0.5538162806886228，excess kurtosis 為 13.568197771359948。

這種左尾與厚尾 profile 比 correlation 更貼近 merger-arbitrage 的 payoff intuition：多數時間承接小 spread carry，少數時間承受 deal-break shock。K1590 沒有直接觀察個別 deal spread，所以不能宣稱它已經量到每筆交易的破局風險；它只顯示 MNA 這個 portfolio proxy 的分布形狀和一般 equity ETF 有差異。

## Lookahead 與統計口徑

K1590 最容易被誤讀的地方，是同日 VIX 分類。同日 VIX close 和同日 MNA return 同屬 day t 資訊，用來描述 day t regime 沒問題；用來做 day t 交易信號就有問題。本文只採描述性解讀，並把 lag-1 robustness 列為 forward-safe check。

第二個邊界是 Welch t-test。絕對報酬是 heavy-tailed variable，高 VIX sample 只有 149 天，低 VIX sample 有 924 天。Welch test 能處理異質變異，但不能自動解決厚尾、clustered stress days 或 threshold sensitivity。Phase 2 應加入 bootstrap、rank-based test、alternative VIX cutoffs，並把結果放進 OOS forecast framework。

第三個邊界是 Harvey / DM。K1590 沒有 OOS forecast loss series，所以沒有 DM test 的對象；也沒有多策略 alpha 搜尋，所以不能寫成 Harvey significant strategy evidence。正確文字是「描述性 regime difference statistically strong」與「Phase 2 research line passes diagnostic gate」。

## 下一步研究設計

K1590 的 `GO` 不該直接進入策略化。Phase 2 比較合理的路徑有四個：

1. 建個別交易層資料：從 SEC EDGAR DEF14A 與 merger announcement 資料建立 target price、offer price、announcement-to-close window。
2. 把 VIX 從 regime label 改成 forecast input：對 MNA daily volatility 或 individual deal-spread volatility 做 ex-ante forecast。
3. 用 HAR-RV、GARCH-X 或 state-switching model 建立 baseline，再用 DM / QLIKE 做 OOS 比較。
4. 對 FTC second request、DOJ filing、financing shock 建事件窗，區分 antitrust channel 與 general risk-off channel。

這四步完成前，MNA 只能稱為公開 proxy，不能稱為 deal-break warning model。

## 結論

K1590 給出的答案是保守的 `GO`：MNA 在高 VIX regime 的絕對日報酬均值是低 VIX regime 的 3.0498710182075395 倍，lag-1 VIX robustness 仍然高度顯著，且 MNA/SPY correlation 只有 0.5170433823391993。這組證據足以支持「值得做 Phase 2」。

同一組證據仍停在描述性層級。它沒有測個別交易 spread，沒有做 out-of-sample volatility forecast，沒有比較交易策略，也沒有處理 antitrust event causality。VolPred 可以把 K1590 放進 research pipeline，但平台文章與後續 paper 必須維持這條邊界。

---

*本文基於實驗 K1590（腳本：`experiments/k1590/k1590_diagnostic.py`；結果：`experiments/k1590/k1590_diagnostic_results.json`；Codex review：`experiments/k1590/codex_review.md`）。資料來源為 yfinance adjusted close，`auto_adjust=False`，tickers 為 MNA / SPY / IWM / HYG / ^VIX。本文為研究紀錄與方法審查，不構成投資建議。*
