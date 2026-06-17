---
title: "K1528：免費 sentiment-beta proxy 沒有重現情緒 beta 溢酬"
audience: research
phase: research
status: draft
tags:
  - sentiment-beta
  - cross-section
  - emotion-beta
  - null-result
  - yfinance
  - FRED
  - robustness
experiment_refs:
  - K1528
description: "K1528 以 yfinance Adj Close、FRED UMCSENT、SPY 與 VIX 建立免費 sentiment-beta proxy，檢驗美國大型股 cross-section 是否存在高 beta 減低 beta 溢酬。結果為 NULL：VIX optimism proxy 方向反轉，UMCSENT change proxy 僅有很小正報酬且未通過 Harvey 與 Fama-MacBeth 門檻。"
image_url: experiments/k1528/figures/k1528_summary_bars.png
---

# K1528：免費 sentiment-beta proxy 沒有重現情緒 beta 溢酬

## 摘要

K1528 檢驗一個可重現、低成本的 market sentiment beta cross-section 版本：用 VIX optimism 與 Michigan Consumer Sentiment change 代理市場情緒 shock，再估計個股對情緒 shock 的 beta，最後比較高 beta 與低 beta 股票的月度報酬。

結論是 NULL。VIX optimism proxy 的 high-minus-low 年化報酬為 -9.51%，方向和情緒 beta premium 假說相反；UMCSENT change proxy 的 high-minus-low 年化報酬為 +0.67%，但 DM t=-0.18、Fama-MacBeth t=-0.29，經濟幅度與統計強度都不足。K1528 不能用來推翻 Hasan、Kumar、Taffler 的 proprietary emotion-index 結果；它只說明，免費 VIX/UMCSENT proxy 版本在固定大型股 universe 上沒有重現那個 premium。

![K1528 high-minus-low annualized return and DM t summary](experiments/k1528/figures/k1528_summary_bars.png)

## 研究背景

Investor emotion beta 的主張很吸引人：如果某些股票對市場情緒改善更敏感，高 emotion-beta 股票理論上可能在 cross-section 中取得較高後續報酬。問題在於原始 emotion indicator 不容易用公開資料重建。K1528 因此採取較保守的研究設計：不宣稱 replication，只做 free-proxy falsification test。

兩個 proxy 分別捕捉不同層面的情緒變化：

| Proxy | 定義 | 直覺 |
|---|---|---|
| VIX optimism | -diff(log(VIX)) | VIX 下降代表恐慌緩和，數值越高表示市場風險情緒改善 |
| UMCSENT change | diff(UMCSENT) / 100 | Michigan consumer sentiment 的月度變化 |

## 方法與數據

| 項目 | 設定 |
|---|---|
| 實驗 ID | K1528 |
| 資料來源 | yfinance Adj Close（auto_adjust=False）與 FRED UMCSENT |
| 期間 | 2004-01-01 至 2026-06-14 |
| Universe | 固定 52 檔美國流動大型股 |
| 月報酬列數 | 269 |
| Beta 估計 | rolling 60 個月，估計窗排除當月報酬 |
| 統計門檻 | Harvey threshold \|t\| > 3.0 |
| Bootstrap | moving block，B=1000、block=6、seed=42 |

每個月先用歷史資料估計個股的 market beta 與 sentiment beta，再按 sentiment beta 排序成高低投組。報酬比較採 high-minus-low，並用 strategy DM、Fama-MacBeth cross-sectional slope 與 moving-block bootstrap 做推論。

這個設計有一個重要限制：universe 是固定的 current liquid large-cap list。固定清單避免動態成分股 membership 的 lookahead，但保留 survivorship bias。K1528 因此屬於 implementable pilot，不是 CRSP-grade cross-section replication。

## 核心發現

| Proxy | 月數 | Median stocks | High ann. ret | Low ann. ret | High-Low ann. | DM t | Fama-MacBeth t | Bootstrap CI ann. | Verdict |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| VIX optimism | 210 | 52 | 18.13% | 27.64% | -9.51% | 1.90 | -2.13 | [-18.23%, 1.05%] | NULL |
| UMCSENT change | 208 | 52 | 22.42% | 21.75% | 0.67% | -0.18 | -0.29 | [-4.20%, 8.97%] | NULL |

### 1. VIX optimism proxy 方向反了

如果高 sentiment beta 股票應該取得 premium，high-minus-low 年化報酬應為正。VIX optimism proxy 的結果是 -9.51%。高 beta 投組年化報酬 18.13%，低 beta 投組年化報酬 27.64%。Fama-MacBeth slope 也為負，t=-2.13。

這個 proxy 給出的訊號指向低 beta 組在這段大型股樣本中表現更好，高情緒 beta premium 沒有出現。即便 high-low DM t=1.90 接近一般顯著門檻，仍未達 K1528 預先設定的 Harvey \|t\| > 3.0 門檻，且方向與研究假說相反。

### 2. UMCSENT change 方向正，但小到不能支撐策略結論

UMCSENT change proxy 的 high-minus-low 年化報酬為 +0.67%，方向符合 premium 假說。可是高 beta 投組年化報酬 22.42%，低 beta 投組 21.75%，差距很小。DM t=-0.18，Fama-MacBeth t=-0.29，bootstrap CI 也跨過 0。

以研究判定而言，這不是「弱但可用」的訊號。K1528 的 success criteria 同時要求方向為正、DM 過 Harvey 門檻、Fama-MacBeth slope 為正且 t 值過門檻；UMCSENT 只滿足方向，其他門檻都沒有過。

![K1528 sentiment-beta long-short cumulative return](experiments/k1528/figures/k1528_cumulative_long_short.png)

## Lookahead 與實作完整性

Codex review 對 K1528 的 implementation integrity 給 PASS， empirical verdict 維持 NULL。主要防線如下：

- Rolling sentiment beta 的估計窗為 60 個月，排除排序月本身的報酬。
- 排序用已估出的 beta，月度 portfolio return 不回灌到同月 beta 估計。
- yfinance 下載採 auto_adjust=False，程式明確選用 Adj Close。
- 隨機流程固定 seed=42。
- Bootstrap 設定為 B=1000、block=6。

這些防線讓 NULL 結果比較有解讀價值。若實驗輸出漂亮 premium，下一步會先懷疑 lookahead 或 universe bias；現在結果反而提醒我們，免費 proxy 的訊號強度不夠，無法直接承接 proprietary emotion indicator 的文獻結論。

## 實務意義

K1528 給後續研究三個約束。

第一，sentiment beta 不是只要換成 VIX 或 consumer sentiment 就會自然出現。VIX optimism 甚至產生反向 long-short 報酬。

第二，cross-section 的情緒研究需要更接近原始 construct 的資料。若要追 Hasan、Kumar、Taffler 的 emotion-beta premium，應該優先建立文字或情緒詞典型指標，而不是期待 VIX/UMCSENT 代理完整捕捉同一件事。

第三，固定大型股 universe 的 NULL result 不能外推到小型股、難套利股票或歷史成分股 universe。Baker-Wurgler 類型的 sentiment cross-section 文獻本來就常把效果放在難估值、難套利資產上；K1528 的大型股樣本是保守起點。

## 結論

K1528 的結論很窄，也很實用：在 2004-01-01 至 2026-06-14 的 yfinance/FRED 免費資料、固定 52 檔美國大型股 universe、rolling 60 個月 beta 設計下，VIX optimism 與 UMCSENT change 都沒有產生 robust sentiment-beta premium。

研究流程上，這是一個有價值的 NULL result。它把下一步問題縮小了：若 emotion beta 真的存在，關鍵可能在情緒指標建構、股票 universe、或原始文獻的資料處理細節；單靠免費市場恐慌與消費者信心 proxy，不足以支撐可交易的 cross-sectional alpha。

*本文基於實驗 K1528（腳本：`experiments/k1528/k1528.py`，結果：`experiments/k1528/k1528_results.json`，審查：`experiments/k1528/codex_review.md`）。數據來源：yfinance Adj Close（auto_adjust=False）與 FRED UMCSENT；期間：2004-01-01 至 2026-06-14；樣本：52 檔固定美國流動大型股，269 個月度報酬列。*
