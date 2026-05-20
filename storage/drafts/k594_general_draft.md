---
title: "動態調整估計視窗能改善 VT 嗎？K594 NULL：固定 W=2000 已經夠用"
audience: general
status: draft
tags: [vt-strategy, garch, rolling-window, robustness, K594, vol-forecasting]
experiment_refs: [K594]
---

# 動態調整估計視窗能改善 VT 嗎？K594 NULL：固定 W=2000 已經夠用

## 一個讓研究者很想試的「好點子」

凡是用過 GARCH 做波動率預測的人，都會碰到一個技術選擇：**rolling window 要用多長？** 學界常見三個答案：W=2000（約 8 年，穩定）、W=1000（約 4 年，折衷）、W=504（約 2 年，反應靈敏）。

過去我們在 K406/K408 的論證下，把 SPY 的 VT（Volatility Targeting）策略 baseline 鎖在 **W=2000**。但市場是活的：calm 期長窗口估得準，crisis 期短窗口跟得快。所以一個「設計感很強」的點子自然冒出：

> **能不能依市場 regime 動態切換 W？平靜時用 W=2000，恐慌時用 W=504？**

聽起來很合理 — 而且 K593 已經實證過「最佳窗口確實是 regime-dependent」。但是：**用對窗口** 跟 **動態切窗口在 OOS 上能贏** 是兩件事。K594 就是針對這個誘惑做的嚴格實驗，結論是一個**乾乾淨淨的 NULL**。

## K594 的設計：把 regime-switching 直接植入 estimation

K594 把估計視窗依當下 VIX 切成三段：

- **Calm**（VIX < 15）→ W=2000（穩定）
- **Moderate**（15 ≤ VIX < 25）→ W=1000（折衷）
- **Crisis**（VIX ≥ 25）→ W=504（靈敏）

對手是四個 baseline：

1. **Fixed W=2000 VT**（我們現行 standard）
2. **Fixed W=504 VT**（永遠靈敏）
3. **12/VIX VT**（不用 GARCH，純 VIX overlay）
4. **Buy-and-Hold SPY**（最低基準）

資料是 SPY + VIX（yfinance, 2005-2026），目標年化波動 12%，每 21 日 refit 一次，交易成本 5 bp。OOS 切成五個不重疊期間：**2012-13、2014-15、2016-17、2020-21（COVID）、2023-24**。每期約 502-505 個交易日。

## 結果一：跨期 Sharpe 幾乎打平

![各 OOS 期間 Sharpe 比較](/experiments/k594/fig1_sharpe_by_period.png)

把五期的 Sharpe 一字排開，Adaptive（紅）和 Fixed W=2000（藍）幾乎黏在一起。Adaptive 在 2023-24 確實小幅領先（1.4842 vs 1.2488），但在 2012-13 反而落後（1.3742 vs 1.4862）。其餘三期差距都在 ±0.1 之內。

跨五期取平均：

| 策略 | Mean Sharpe | 期間勝出次數 |
|---|---|---|
| Adaptive VT (regime-switching W) | **0.971** | 0 / 5 |
| Fixed W=2000 VT | 0.959 | 1 / 5 |
| Fixed W=504 VT | 0.981 | 0 / 5 |
| 12/VIX VT | 1.007 | 1 / 5 |
| Buy-and-Hold SPY | 1.119 | 3 / 5 |

Adaptive 平均 Sharpe 比 Fixed W=2000 高 **+0.012**（千分之十二），比 Fixed W=504 還**低** **-0.010**，比 12/VIX 低 **-0.036**。**沒有任何一期 Adaptive 是冠軍。**

## 結果二：DM 統計檢定全 NULL

僅看數字差距還不夠，學術上要看顯著性。把 Adaptive 對 Fixed W=2000 在五期分別做配對檢定，並計算 pooled 跨期的整體統計強度：

![平均 Sharpe + 各期顯著性](/experiments/k594/fig2_mean_sharpe_and_pvalues.png)

**Pooled 跨期統計（Adaptive vs Fixed W=2000）**：

- Sharpe 差 = +0.029
- 統計強度 = 0.34（很弱）
- 達顯著水準（顯著性 0.7357）

**個別期間最接近顯著的是 2023-24**（顯著性 0.1012，方向上 Adaptive 領先），但**仍沒過 0.10 門檻**。其餘四期 p 值分別是 0.0746、0.9776、0.5842、0.9855。請注意 2012-13 的 0.0746 是 **Adaptive 顯著輸給** Fixed W=2000 — 反方向的 marginal 顯著。

**結論非常乾淨**：Adaptive 既沒有跨期顯著贏 Fixed W=2000，也沒有任何單期穩定贏。這正是嚴格的 NULL。

## 結果三：累積報酬與成本面也沒有翻盤

有人會說：「Sharpe 沒贏，但說不定 drawdown 改善了？或交易成本省了？」答案都不是。

![各期累積報酬比較](/experiments/k594/fig3_cum_return_by_period.png)

- **累積報酬**：五期合計 Adaptive 是 154.92%，Fixed W=2000 是 153.31%，Fixed W=504 是 157.50%。Adaptive 在絕對報酬上連 Fixed W=504 都沒贏。
- **交易成本**：Adaptive 平均日週轉率 0.024，Fixed W=2000 只有 0.012 — Adaptive **反而多週轉一倍**（因為 regime 切換時參數跳動會誘發倉位變化），這在實戰中是隱藏成本。
- **MDD**：差距同樣不顯著，2020-21 COVID 期 Adaptive -13.89% vs Fixed W=2000 -12.24%（Adaptive 還略差）。

## 為什麼這個漂亮的點子會 NULL？三個可能解釋

**第一**，GJR-GARCH 在 W=2000 下估計已經足夠 robust。波動率有強 persistence，多 1500 天樣本邊際資訊很有限；當你切到 W=504 時雖然「最近資訊權重高」，但同時參數估計變異也放大，兩者在 VT 的 weight = min(target/σ, 1) 公式上互相抵銷。

**第二**，VT 公式對 σ 的微小估計誤差不敏感。Sharpe 的差異需要 σ̂ 系統性錯估才會放大，而 W=2000 vs W=504 的 σ̂ 在 OOS 上**相關係數通常 > 0.95**（K593 已驗證）。差不多的 σ̂ 不可能產生差很多的 weight。

**第三**，regime gate 本身有 lag。VIX 跨閾值的當下換窗口意味著估計樣本「跳變」，下一次 refit 時用的是不同期間的資料，引入 transition noise — 這是隱性成本。

## 把 K594 放回 evidence chain：固定參數已足夠

K594 不是孤立結果，它和我們之前兩個 NULL 形成完整的「固定參數已足夠」evidence chain：

- **K550**：Adaptive threshold（動態調整 VT 的目標波動）— **NUANCED**，個別 regime 改善但跨期不穩定
- **K571**：固定 12/VIX 已足夠 — **NULL**，加任何 ML 訊號都沒額外 alpha
- **K594（本文）**：Adaptive estimation window — **NULL**，動態切窗口沒額外 alpha

三個獨立實驗，三個獨立的「想用更聰明的方法擊敗固定參數」嘗試，全部 NULL 或 NUANCED。這不是巧合，是 VT 這類 monotone weight 結構對參數調整本身有一定 robustness 的反映。

## 重要 caveat：別過度推論

K594 結論**只 specific to SPY 日頻 VT**：

- **不能推論到其他資產**（台股、加密貨幣、商品的 vol persistence 結構不同）
- **不能推論到其他預測 horizon**（intraday 或週/月頻可能不同）
- **不能推論到其他策略型態**（直接交易 σ 預測值的策略對視窗更敏感）
- **「固定 W=2000 是 universal best」這句話我們不會說** — 它只是「對 SPY 日頻 VT，相對於 adaptive 沒輸」

## 給研究者與實作者的兩個 takeaway

1. **設計實驗時，要區分「現象的存在」和「現象可被交易」**。K593 證實了「最佳窗口 regime-dependent」，但 K594 證實「regime-switching 視窗不能轉成可交易 alpha」。學術文獻很多都卡在第一層就停了。

2. **對 VT 這種 weight = min(target/σ, 1) 結構，在參數細節上鑽下去往往是 NULL**。資源應該花在更上游：訊號本身（K571 已證實 VIX 主導）、目標波動的設計（K550 NUANCED）、組合層次的多資產 VT（未測）。

## 下一步

K594 的自然延伸是 **cross-asset VT**（QQQ / IWM / 0050.TW / BTC）— 同樣的 adaptive window 邏輯在 thinner-tailed 或更高 vol 的資產上會不會有不同結果？以及更長 horizon 的 weekly VT，視窗動態是否還重要？這些都是接下來的方向。

但對 SPY 日頻 VT 而言，**K594 已經 close 了這個問題**：固定 W=2000 是合理 default，動態切窗口不是 alpha 來源。

---

**實驗來源**：K594（experiments/k594/）。資料：yfinance SPY + VIX 2005-2026。模型：GJR-GARCH(1,1)-t。回測 OOS 五期不重疊，每期約 502 交易日。所有檢定固定 seed，signal lag 已驗證。

**參考**：K406/K408（W=2000 升級依據）、K591（W 敏感性 sweep）、K593（W cross-OOS）、K550（adaptive threshold NUANCED）、K571（12/VIX 已足）；Moreira & Muir (2017, JF) Volatility-managed Portfolios；Fleming, Kirby & Ostdiek (2001, JFE) Economic Value of Vol Timing；Feng & Zhang (2025, J. Forecasting) U-shape Window。
