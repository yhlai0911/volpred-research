---
title: "K1640：VIX 30/40 恐慌進場的事件研究，半真但不能當即時交易規則"
slug: k1640-vix-30-40-panic-entry-event-study
audience: research
status: draft
phase: research
tags:
  - VIX
  - SPY
  - 事件研究
  - 恐慌進場
  - 多重檢定
  - lookahead
  - HAC
  - 風險溢酬
experiment_refs:
  - K1640
image_url: "https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k1640_excess_returns.png"
---

# K1640：VIX 30/40 恐慌進場的事件研究，半真但不能當即時交易規則

[提出: 自動任務池, 執行: Codex]

## 摘要

K1640 檢驗一個很常見的擇時說法：VIX 第一次往上穿越 30 或 40 之後買進 SPY，是否比任意一天進場更好。樣本使用 yfinance 的 `^VIX` 收盤價與 SPY 調整後收盤價，期間為 1993-01-29 到 2026-07-02，共 8,413 個共同交易日。事件以 20 個交易日去叢集後，VIX 30 門檻有 50 次，VIX 40 門檻有 17 次。

結論是 `CONDITIONAL_PASS_HALF_TRUE_QUALIFIED`。lag0 事件研究中，8 個門檻乘 horizon cell 有 7 個平均報酬高於隨機進場；但 Benjamini-Hochberg FDR 5% 下沒有任何單一 cell 存活。FDR 10% 下留下三格：VIX>30 的 5 日與 60 日，以及 VIX>40 的 60 日。明確 lag 一天後，FDR 10% 存活數降為 0。恐慌後進場有方向性優勢，但證據支持的是「三個月慢反轉」而非立即反彈。

## 研究背景

VIX 被稱為恐慌指數，直覺上容易被拿來當 contrarian 訊號。問題在於，SPY 本身有長期正漂移；只要持有期拉長，隨機一天進場的勝率就已經偏高。K1640 因此把問題拆成兩層：第一，恐慌事件後的 SPY 前瞻報酬是否為正；第二，它是否比同 horizon 的無條件隨機進場更高。

K1640 是 K1633 的 focused replication。K1633 同時看 30/35/40 三個門檻；K1640 只保留任務指定的 30 與 40，使用 seed 42 重算完整表格、placebo 與 lag1 robustness。兩者在重疊的 30/40 lag0 cell 上數字一致到四捨五入層級。

## 方法與數據

| 項目 | 設定 |
|---|---|
| 資產 | `^VIX` close 與 SPY adjusted close |
| 期間 | 1993-01-29 到 2026-07-02 |
| 共同交易日 | 8,413 |
| 門檻 | VIX 第一次由下往上穿越 30 或 40 |
| 去叢集 | 20 個交易日 cooldown |
| horizon | 5、10、20、60 個交易日 |
| 事件數 | VIX>30: 50；VIX>40: 17 |
| baseline | 每個 eligible trading day 都當進場日，同價格序列、同 horizon |
| 主推論 | HAC/Newey-West 回歸 `forward_return ~ event_dummy`，`maxlags = H` |
| 多重檢定 | 8 個 lag0 cell 使用 Benjamini-Hochberg FDR |
| placebo | 每個 cell 抽 5,000 組 random entries |
| seed | 42 |

主設定是 signal-day close 的事件研究口徑：

```python
fwd = SPY[t + H] / SPY[t] - 1
```

這個設定量的是「VIX 收盤穿越門檻之後，後面 H 天發生什麼」。它不能直接解讀成同一個收盤價可無摩擦成交的交易規則。K1640 因此另跑 explicit lag1 版本：

```python
signal_lag1 = signal.shift(1).fillna(False)
```

這條 lag1 檢查是本文判斷 lookahead 風險的核心防線。

## Baseline 先天很強

無條件 SPY baseline 的勝率已經偏高。若忽略這一點，恐慌進場看起來會比實際更神奇。

| horizon | 隨機進場勝率 | 隨機進場平均報酬 |
|---:|---:|---:|
| 5 日 | 58.8% | 0.23% |
| 10 日 | 61.9% | 0.46% |
| 20 日 | 65.4% | 0.92% |
| 60 日 | 71.9% | 2.74% |

這個 baseline 讓 K1640 的設計比「事件後報酬是否為正」更嚴格。它問的是：在同樣持有 5、10、20、60 天時，恐慌進場是否還能多賺一段。

## 核心結果一：lag0 有方向性，但嚴格 FDR-5 不放行

lag0 版本的結果方向很一致：8 個 cell 中有 7 個 excess mean 為正。最強的經濟效果集中在 60 日 horizon，特別是 VIX>40 的 60 日 cell，平均多出 6.19 個百分點。

![K1640 lag0 與 lag1 excess returns](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k1640_excess_returns.png)

| Cell | 事件數 | Excess mean | 勝率差 | HAC p | BH q | FDR 10% |
|---|---:|---:|---:|---:|---:|---|
| VIX>30, H5 | 50 | +1.26% | +11.2pp | 0.0068 | 0.054 | Yes |
| VIX>30, H10 | 50 | +0.65% | +2.1pp | 0.3723 | 0.496 | No |
| VIX>30, H20 | 50 | +1.34% | +10.6pp | 0.0853 | 0.171 | No |
| VIX>30, H60 | 50 | +2.55% | +2.1pp | 0.0360 | 0.096 | Yes |
| VIX>40, H5 | 17 | +1.59% | +17.7pp | 0.1534 | 0.245 | No |
| VIX>40, H10 | 17 | -0.04% | +2.8pp | 0.9725 | 0.972 | No |
| VIX>40, H20 | 17 | +1.63% | +11.1pp | 0.4840 | 0.553 | No |
| VIX>40, H60 | 17 | +6.19% | +16.4pp | 0.0191 | 0.076 | Yes |

多重檢定後的讀法要保守：

- raw 5% 顯著 cell 有 3 個：VIX>30/H5、VIX>30/H60、VIX>40/H60。
- FDR 5% 存活 cell 為 0。
- FDR 10% 存活 cell 有 3 個，與 raw 5% 名單相同。

因此，K1640 不應被寫成「VIX 破 30/40 後買進一定有效」。較準確的說法是：lag0 事件研究下，恐慌進場相對隨機進場有正向 excess return pattern，但單一 cell 在嚴格 5% FDR 下沒有存活。

## 核心結果二：lag1 之後，交易語意明顯變弱

lag1 是更接近可執行設定的版本。它等到 VIX 穿越訊號出現後隔天收盤再進場。這個檢查沒有把 lag0 結果完全推翻，但顯著性明顯下降。

![K1640 事件勝率與 baseline 勝率比較](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k1640_winrates.png)

lag1 的整體摘要：

| 指標 | lag0 | lag1 |
|---|---:|---:|
| 正 excess cell | 7/8 | 6/8 |
| raw 5% survivor | 3/8 | 1/8 |
| FDR 5% survivor | 0/8 | 0/8 |
| FDR 10% survivor | 3/8 | 0/8 |

唯一 raw 5% 存活的 lag1 cell 是 VIX>30/H5，平均多出 1.14 個百分點，HAC p=0.0173，但 BH q=0.138，未過 FDR 10%。VIX>40 的 lag1 短天期更不穩：H5 平均 excess 為 -0.40 個百分點，`win_vs_base` 欄位為 -0.117542。

這個結果把文章的交易語氣壓低。K1640 可以支持「恐慌後的後續報酬分布偏正」，但不能支持「看到 VIX 收盤破 40，隔天立刻有穩健短線 alpha」。

## Placebo 與 60 日慢反轉

random-entry placebo 對 60 日慢反轉給出額外支持。VIX>40/H60 的 event mean 為 8.93%，baseline mean 為 2.74%，excess mean 為 6.19 個百分點；5,000 次 random-entry placebo 的 two-sided p=0.0012。VIX>30/H60 的 excess mean 為 2.55 個百分點，placebo two-sided p=0.0150。

短天期訊號較混雜。VIX>30/H5 的 placebo two-sided p=0.0002，數字很強；但 VIX>40/H5 的 HAC p=0.1534，沒有通過主要回歸推論。原因可能是 VIX>40 事件只有 17 次，單一事件路徑對估計影響很大。

因此，最穩的敘事應該寫成：「極端恐慌後 60 個交易日內，SPY 的平均前瞻報酬分布往右移」。60 個交易日大約是一季，與 VIX spike 後均值回歸常需數週到數月的經驗相容。

## 與相關實驗的關係

K1633 是完整 30/35/40 版本。它在 12 個 lag0 cell 中有 11 個正 excess，FDR 5% 同樣沒有單一 cell 存活，FDR 10% 留下 VIX>30/H5、VIX>35/H60、VIX>40/H60。K1640 去掉 35 門檻後，保留相同的核心訊息：方向性存在，嚴格多重檢定下要降級。

K571 檢查 VIX 均值回歸速度，樣本為 2004-01-05 到 2026-03-26，結論是「部分 OOS 改善但沒有 Harvey significance」。這提醒我們，VIX 的均值回歸可作為背景機制，但不能直接升級成強交易訊號。

K641 分解 VIX regime 下的 volatility targeting 表現。2024-08-05 與 2025-04-03 兩段危機裡，買進持有 SPY 在後續 20 日反彈分別為 6.71% 與 12.44%，而多數減碼型 VT 策略因曝險較低，只捕捉到部分反彈。這與 K1640 的慢反轉發現一致：高 VIX 後的反彈常存在，但持有多少風險曝險才是實務問題。

## DM/Harvey 與過度宣稱檢查

K1640 沒有把結果包裝成 DM 或 Harvey pass。本文使用的是 HAC/Newey-West 事件回歸、BH-FDR 多重檢定，以及 random-entry placebo。這些檢定回答的是「事件日後的前瞻報酬是否高於同 horizon baseline」，不是模型預測 loss 的 Diebold-Mariano 比較，也不是策略 Sharpe 的 Harvey 多重檢定。

因此，本文不宣稱新模型能預測市場，也不宣稱 VIX 30/40 是可上架策略。合理宣稱範圍只有三句：

1. lag0 事件研究中，恐慌穿越後的 SPY forward return 相對 baseline 多數為正。
2. 嚴格 FDR 5% 下，沒有任何單一 cell 可被視為強確認。
3. lag1 後顯著性下降，交易可執行性必須另行檢驗。

## 限制

1. lag0 是事件研究口徑，不是 guaranteed executable trade。
2. VIX>40 只有 17 個去叢集事件，單一 cell 估計容易受少數危機路徑影響。
3. 本研究只看 SPY，不含交易成本、稅、現金收益、滑價或實際下單延遲。
4. horizon 報酬有重疊窗口，K1640 用 HAC `maxlags=H` 修正，但有限樣本下仍需保守解讀。
5. FDR 10% 存活只能表示較弱的探索性證據，不應寫成正式策略確認。

## 結論

K1640 的結果支持「恐慌後進場有部分增量報酬」這個弱版命題。強版命題不成立：VIX 破 30/40 不是穩定的短線買進訊號，也不是可直接執行的 alpha 規則。

最好的讀法是把 VIX 30/40 當成事件研究標記。當 VIX 第一次向上穿越這些門檻，後續 60 個交易日的 SPY 報酬分布通常比隨機進場更好；但這份優勢有小樣本、多重檢定與交易時點三個折扣。若要做成策略，下一步應該用 lag1 或更保守的 next-open / next-close entry，加入 cash yield、稅與交易成本，再和 buy-and-hold 或 50/50 SPY/GLD 做同期間比較。

---

本文基於實驗 K1640。腳本：`experiments/k1640/k1640.py`；結果：`experiments/k1640/k1640_results.json`；審查：`experiments/k1640/codex_review.md`。資料來源：yfinance `^VIX` close 與 SPY adjusted close。期間：1993-01-29 到 2026-07-02；樣本：8,413 個共同交易日；隨機程序 seed=42。
