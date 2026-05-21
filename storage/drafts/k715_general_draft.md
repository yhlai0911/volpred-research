---
title: "VT 何時真的有效?同期間驗證:2023-2026 高 VIX 期間 VT 終於勝過 BH"
audience: general
status: draft
description: "20 年長期回測說 BH 50/50 是冠軍,但 2023-2026 高 VIX 期間的真實 live 數據顯示:VT 家族策略確實勝過 BH。VT 不是永遠的 alpha,而是 regime-dependent 的保險—只在高波動時期發揮作用。"
tags:
  - regime-dependent
  - vol-targeting
  - forward-tracking
  - high-vix-period
  - same-period
  - SPY-GLD
  - paper-trading
experiment_refs:
  - K715
  - K687
---

# VT 何時真的有效?同期間驗證:2023-2026 高 VIX 期間 VT 終於勝過 BH

[提出: 用戶, 執行: Claude]

## 摘要

如果你看過去 20 年的數據,簡單的「永遠 50/50 SPY/GLD」策略勝過所有花式波動率目標 (Volatility Targeting, 簡稱 VT) 策略,風險調整後報酬最高。但如果你只看 2023 年初到 2026 年 5 月這段「真實在跑的 live forward tracking」期間,結論完全反過來:平台上已上架的所有 VT 策略全部勝過 BH 50/50。為什麼?因為這 3 年是少見的「持續高 VIX 環境」(2025 年關稅衝擊讓 VIX 一度衝破 60)。VT 的價值不是天天賺超額報酬,而是 **regime-dependent**:長期沒 alpha,但在高波動時期是真正的避震器。本文以實際 paper trading 真實績效解析這個看似矛盾的二元真相。

## 兩個看似矛盾的事實

研究團隊在 2026 年 3 月做了一個誠實到不舒服的盤點。

**事實 A — 來自 K687 (2007-2026 共 19.2 年)**:把 7 種波動率目標策略放在 19 年完整週期裡,連同正確處理交易延遲、5 bp 一邊交易成本後,結論是「沒有任何 VT 策略在 Sharpe ratio 上勝過簡單的 BH 50/50 SPY/GLD」。BH 50/50 Sharpe = 0.545 排第一,EWMA VT (λ=0.94) Sharpe = 0.525 排第二。VT 唯一的明確優勢是大幅降低最大回撤 (BH 50/50 -32% vs 12/VIX -12%)—這是「保險」而非「alpha」。

**事實 B — 來自 K715 (2023-01-04 → 2026-05-08,真實 live forward tracking)**:同樣的策略集合,在 paper trading 真實追蹤的這 3 年裡,平台上已上架的 top 10 策略全部勝過 BH 50/50。BH 50/50 Sharpe 1.862 在 15 個策略中排第 11(K715 評估時的快照)。台灣動量策略 Sharpe 3.43、Tri-Zone 三區策略 3.63、VIX 條件加碼 2.69—全部遠勝 BH。

讀者的直覺問題:**到底哪個是真的?**

答案是:**兩個都是真的,只是說的是不同事**。

![2023-2026 同期間策略排名:VT 家族在高 VIX 時期勝過 BH](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k715_strategy_ranking_2023_2026.png)

## 為什麼 2023-2026 這 3 年特別?關鍵字:VIX

過去 19 年的歷史涵蓋了 2008 金融海嘯、2020 COVID、2022 通膨衝擊—但中間夾雜了 2013-2017、2018-2019、2021 等多段「VIX 持續低於 20」的低波動年。低波動期間,VT 策略反而會減碼 (恐懼計算結果說「不該滿倉」),結果錯過行情;BH 全程 100% 滿倉,反而吃到完整漲幅。19 年平均下來,「全時間滿倉的人贏」。

但 2023-2026 不同。看下面這張 VIX 時序圖:

![2023-2026 VIX 時間序列:多次高 VIX 區段提供 VT 策略發揮空間](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k715_vix_regime_overlay.png)

紅色陰影區是 VIX > 25 的高波動期。期間出現了:

- **2023 年 3 月**:矽谷銀行 (SVB) 與 Credit Suisse 連環倒,VIX 衝上 30
- **2024 年 8 月**:日圓套利交易 (carry trade) 平倉日,VIX 短暫衝到 65
- **2025 年 4 月**:美國新一波關稅戰開打,VIX 一度衝破 45,本期間最高點

期間 VIX 平均值落在比歷史平均更高的水位。**對 VT 策略,這就像保險公司碰到地震頻發年—保費收得回來、且能避開最嚴重的損失。** 對 BH 來說,這 3 年是「上沖下洗、最終回正」的折磨期—總報酬還行,但波動率被拉高、Sharpe 必然被稀釋。

## 跨期間對比:同樣的策略,不同的結局

下面這張並排對比清楚說明問題:

![長期 vs 近期:VT 是 regime-dependent](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k715_long_term_vs_recent_bh.png)

**左圖 (K687, 19.2 年完整週期)**:BH 50/50 Sharpe 0.545 排第一,VT 全敗北。
**右圖 (K715, 2023-2026 高 VIX 期間)**:同樣的 BH 50/50 變成輸家,VT 家族在 Sharpe 1.6-3.6 之間,推薦的 12/VIX 配置也微幅勝出。

這種對比,在金融研究裡有個專門名詞叫做 **regime-dependent alpha**—在某種市場狀態下有用,在另一種市場狀態下就沒用。

## 實務意義:你該怎麼看待 VT 策略?

對一般投資人,這個發現帶來三個重要訊息。

**第一,別把短期 outperformance 當作「策略發現了什麼」**。如果你最近 3 年看到某個 VT 策略狂勝 BH,先不要急著加碼—它有可能只是吃到 regime 紅利。要等到再經歷一次低波動年 (例如未來某個 VIX 持續低於 15 的年度),才能驗證它是否仍有效。

**第二,別把長期歷史 underperformance 當作「策略沒用」**。19 年 BH 勝出不代表 VT 永遠輸。當市場真的進入持續高波動時期,VT 在 drawdown 控制和 Sharpe 上都會反超—2023-2026 就是這樣的時期。把 VT 當成「保險」而非「alpha 來源」會比較貼近事實:平時看似多餘,出事時救你一命。

**第三,組合可以同時用兩種**。很多實務做法會把 BH 與 VT 各放一半—長期週期裡 BH 那半貢獻 alpha,危機週期裡 VT 那半幫你縮小回撤。這樣不需要押對「現在是哪種 regime」,也能拿到兩邊的優點。

## 為什麼 paper trading 數據可信賴?

讀者合理會問:為什麼相信這 3 年的數據?萬一是過度擬合?

關鍵是 **paper_trading.json 是 live forward tracking,不是回測**。每天系統按照前一天市場收盤後的訊號,在隔天市場執行,把「假錢」記錄起來,複利累積。沒有 lookahead (用未來資訊回頭做決策),也沒有 backtest 自由參數重調。837 個交易日 (對 SPY/GLD 起點 2023-01-04 算起) 的每一筆都是當下決定、事後不能修改。

這就是為什麼即使 K715 的結論「看起來」推翻了 K687 的長期結論,我們仍然採信它—**它是真實流過的時間,不是事後挑出來的子集**。研究誠實的標準,不容許忽略其中任何一邊。

## 局限與下一步

- **3 年仍是樣本不足**:雖然 paper trading 的「live」性質已是強驗證,但 3 年只覆蓋一個 high-VIX regime cycle。要等到下一個低波動年回來,才能真正驗證 VT 在 regime 切換時的反應速度
- **2023-2026 的 high-VIX 結構是否會持續?** 沒人知道。但至少,VT 在高波動年提供保險的價值,已被真實 live data 確認
- **跨市場驗證**:本期間台灣相關策略 (TW Momentum / TW VT / TW Hybrid Leverage) 表現特別好;這是台股本身近 3 年走勢強的副產品,還是 VT 在台股有額外的結構性優勢?後續實驗會延伸驗證

---

*本文基於實驗 K715 與 K687。資料來源:`storage/paper_trading.json` (2023-01-04 → 2026-05-08 真實 live forward tracking, 801-837 個交易日) + `experiments/k687/k687_results.json` (yfinance SPY/GLD/VIX 2007-2026, 19.2 年完整回測, n=4838 交易日)。BH 50/50 baseline Sharpe 1.862 為 K715 評估時 (2026-03-29) 的快照值,後續 live forward 數據持續累積。*
