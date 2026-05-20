---
title: "VT 加最低部位 floor 真的能贏 buy-and-hold 嗎？K696 答案：哪一個 floor 都贏不了"
audience: general
status: draft
tags:
  - 波動率目標
  - VT策略
  - 風險管理
  - 最低部位
  - Buy-and-Hold
  - 一般讀者
experiment_refs:
  - K696
---

# VT 加最低部位 floor 真的能贏 buy-and-hold 嗎？K696 答案：哪一個 floor 都贏不了

## 一個對 VT 策略最常見的質疑

如果你曾經在牛市看到 VT（Volatility Targeting，波動率目標）策略的回測表現，最常見的反應大概是這句：「為什麼牛市它的部位這麼小？要是強迫它至少維持一定的曝險，是不是就能追上 buy-and-hold？」

這個直覺其實有道理。VT 的核心邏輯是「波動高就減碼、波動低就加碼」，但 VIX 即使在多頭也常常維持在 18-22 區間，導致 12÷VIX 的目標權重大概在 0.55-0.70 之間，於是「總是少抱一些股票」。如果 VT 的問題真的只是「在牛市抱太少」，那設一個 minimum exposure floor（強制最低部位 30%、50%、70%…）應該就能在保留下檔保護的同時，把上檔還回來。

K696 把這個直覺認真地測了一遍。結論非常清楚：**沒有任何一個 floor 數值能讓 VT-with-floor 在 Sharpe 上贏過 buy-and-hold**。

## 實驗設計

- **資料來源**：yfinance 的 SPY（S&P 500 ETF）+ GLD（黃金 ETF）+ ^VIX，2006-01-01 至 2026-03-27
- **OOS 評估期**：2007-01-03 至 2026-03-27，4838 個交易日
- **Portfolio**：50/50 SPY/GLD 等權
- **VT 訊號**：weight_t = max(floor, min(12 ÷ VIX_{t-1}, 1.0))，**lag 1 天（信號用 t-1，報酬用 t）**
- **Baseline**：50/50 SPY+GLD 永遠滿倉（B&H 5050）
- **交易成本**：5 bps；無風險利率 4% 年化
- **Floor 掃描**：0%、10%、20%、30%、40%、50%、60%、70% 八個版本

VT 訊號的設計刻意保守：12÷VIX 的歷史中位數是 0.7011，平均值 0.7034，亦即不加 floor 的純 VT 平均部位約 68%（mean weight 0.6822）。Floor 越高，VT 在低波動期就越接近滿倉，理論上「該抓到牛市」的能力應該越強。

## 核心結果：每一個 floor 都輸 B&H

下表是各 floor 版本的 OOS 績效（4838 天）：

| 策略 | Sharpe | CAGR | MDD | Annual Vol | 平均權重 |
|---|---:|---:|---:|---:|---:|
| VT floor 0% | 0.4316 | 7.24% | -12.23% | 7.61% | 68.22% |
| VT floor 10% | 0.4316 | 7.24% | -12.23% | 7.61% | 68.22% |
| VT floor 20% | 0.4386 | 7.31% | -12.23% | 7.62% | 68.24% |
| VT floor 30% | 0.4398 | 7.37% | -13.12% | 7.75% | 68.44% |
| VT floor 40% | 0.4433 | 7.50% | -15.52% | 8.01% | 69.03% |
| VT floor 50% | 0.4572 | 7.80% | -17.56% | 8.47% | 70.47% |
| VT floor 60% | 0.4803 | 8.31% | -19.94% | 9.17% | 73.34% |
| **VT floor 70%** | **0.5056** | **8.97%** | -23.06% | 10.09% | 77.74% |
| **B&H 50/50（baseline）** | **0.5448** | **11.10%** | -32.49% | 13.70% | 100% |

幾個關鍵數字：

- **Best Sharpe floor = 70%，Sharpe = 0.5056**
- **B&H Sharpe = 0.5448**
- **gap ≈ -0.04**（best floor 仍輸 B&H 約 4 個 Sharpe 百分點）
- **does_any_floor_beat_bh = false**
- **floors_beating_bh = []**（空集合）

換句話說，掃完整個 0-70% 的 floor 區間，沒有一個版本能在 Sharpe 上追平 B&H。CAGR 也呈現相同的單調性：floor 越高、CAGR 越接近 B&H，但 4838 天累積下來，best floor 70% 的 CAGR 8.97% 仍落後 B&H 的 11.10% 整整 2 個百分點以上。

![圖 1：各 floor 版本的 Sharpe 與 B&H 對照](k696_floor_sharpe.png)

從邊際效應看更直觀：每多 10pp 的 floor，Sharpe 平均只上升 0.005-0.025、但 MDD 惡化 1-3pp。floor 從 60% 拉到 70% 是邊際效益最大的一段（ΔSharpe +0.025），但同時 MDD 也從 -19.94% 惡化到 -23.06%。

![圖 2：Sharpe gap（VT-with-floor − B&H），整段 0-70% 都在零線之下](k696_sharpe_gap.png)

## 為什麼直覺錯了？

直覺認為「強制最低部位能追上 B&H」，但忽略了一件事：**VT 在 4838 天裡的平均部位本來就有 68%，已經抱了大部分股票了**。把 floor 從 0% 拉到 70%，平均部位只從 68.22% 升到 77.74%，差不多多抱了 10pp。這 10pp 在牛市能多賺一點，但在熊市同樣多賠一點——以 5 bps 交易成本和 4% 無風險利率為基準，淨效應是 Sharpe 略升、CAGR 略升、但**MDD 大幅惡化**（floor 0% 的 MDD 是 -12.23%，floor 70% 的 MDD 是 -23.06%）。

於是 floor 機制本質上是把 VT「往 B&H 方向調」，當 floor 拉到 100%（理論上）就完全等於 B&H。在 0-70% 的整段區間裡，floor 越高就越像 B&H，但**從來沒有比 B&H 更好的點**。VT 想用更低的曝險換更穩的曲線，但 4% 無風險利率拉高了「抱滿倉」的相對效益，使整段曲線都壓在 B&H 之下。

## 但 VT 真的「沒用」嗎？危機期間的 dollar impact

如果只看 Sharpe，這個實驗看起來是 VT 的全面投降。但只看 Sharpe 會嚴重低估 VT 的真正價值——**下檔保護**。看危機期間的累積報酬：

| 期間 | B&H | VT floor 0% | VT floor 40% | VT floor 60% |
|---|---:|---:|---:|---:|
| GFC（2008-09 至 2009-03） | -13.77% | -4.15% | -4.49% | -6.87% |
| COVID Crash（2020-02 至 2020-04） | -2.90% | -0.97% | -0.45% | -0.92% |
| 2022 Bear（2022-01 至 2022-10） | -13.85% | -6.28% | -6.20% | -7.38% |

在三次主要危機期間，VT 不論 floor 高低，**下檔損失都是 B&H 的一半左右**。這個保護不是免費的——recovery 期 VT 也只賺到 B&H 的 30-60%。但對於需要避免大額drawdown 的避險帳戶（退休金、保險、家族信託），這個 trade-off 經常是值得的。

![圖 3：三次危機期間的 dollar impact，VT 各版本對 B&H 的損失壓抑](k696_crisis_dd.png)

這也呼應了 K674 的發現：在 5 個跨期 crisis stress test 中，**Piecewise Conservative VT 在最大回撤上 dominate B&H**——只是它輸 Sharpe。

## 誠實的 framing

這個實驗的結論需要小心地表達清楚，避免 over-claim：

1. **「VT-with-floor 沒贏 B&H」是 specific to evaluated period（2007-2026）的結論**，不是 universal truth。樣本期橫跨 GFC、QE 時代、COVID、2022 升息四個 regime，B&H 受惠於 Fed put 與低利率紅利。在不同 regime（例如停滯通膨、長期熊市）結果可能反轉。
2. **VT 的價值不該被 Sharpe 比較蓋過**。下檔保護、CRRA 高 risk-aversion 投資人偏好（K688）、避險帳戶的 utility-based 評估，都是 Sharpe 看不到的維度。
3. **這個實驗只測 12÷VIX 訊號**。其他 VT 訊號（GARCH conditional vol、HAR-RV、realized vol）對 floor 的反應可能不同。
4. **沒有 out-of-sample split**。Best floor 70% 是 in-sample 的最佳值，true OOS 上它可能更差。

t-test 顯示 best floor 70% vs B&H 的日度報酬差為 -0.94 bps（年化 -2.36pp），統計強度 -2.72，達顯著水準（顯著性 0.0066），但**未通過嚴格統計檢驗門檻**（Harvey, Liu and Zhu (2016) 建議的 |t| ≥ 3.0），因此不能視為「VT 顯著地輸 B&H」。它只是「在這個樣本期間沒贏」。

## 下一步

這個 NULL result 開了一個有趣的方向：**regime-conditional floor**。如果固定 floor 永遠輸 B&H，那麼一個依市場 regime（牛市低 floor、熊市高 floor，或反之）動態切換的 floor，能不能找到突破點？這正是 K687 與 K688 後續的研究方向。

對一般讀者的實務建議：**如果你的目標是長期最大化 Sharpe，2007-2026 的證據顯示直接買 50/50 SPY+GLD 比加任何固定 floor 的 VT 都更省事**。但如果你在意 drawdown（例如不能讓退休基金一年跌超過 15%），VT 的價值仍在那裡——只是用 Sharpe 看不到。

## 參考實驗與文獻

- **K696**：本實驗；experiments/k696/k696_results.json
- **K687**：Definitive lag-corrected strategy ranking — B&H 50/50 在 Sharpe 上贏所有 VT 變體
- **K688**：CRRA utility framework — VT 在 gamma ≥ 5 時於 utility 上勝出
- **K674**：5 期 crisis stress test — Piecewise Conservative 在 MDD dominate B&H
- Copeland & Copeland (1999): Market Timing with VIX
- Fleming, Kirby and Ostdiek (2001): The Economic Value of Volatility Timing
- Harvey, Liu and Zhu (2016): ...and the Cross-Section of Expected Returns
