---
title: "買 put 避險划算嗎？K544 給散戶的 NEGATIVE 答案：12/VIX VT 已經夠用"
audience: general
status: draft
phase: research
tags: tail-hedge,put-protection,vt-strategy,risk-management,k544
kid: K544
experiment_refs: K544
---

# 買 put 避險划算嗎？K544 給散戶的 NEGATIVE 答案：12/VIX VT 已經夠用

「市場高點要不要買點 put 保險？」「VIX 期權能不能保住我的退休金？」這類問題每年都在散戶群組裡循環。學術界的答案其實已經很明確：**Israelov（2017, Journal of Portfolio Management）那篇有名的「Pathetic Protection」就指出，無條件買 put 保護長期是 NPV 為負的策略**。但問題是：如果加上時機判斷呢？看 VIX 便宜時買、看 contango 深時買、漲多時買 — 這些「條件式擇時」能不能扭轉劣勢？

K544 用 SPY、VIX、VIX3M 從 2006 年 7 月到 2025 年底**將近 19 年（4,896 個交易日）**的真實資料做了一次系統性測試。先講結論：**verdict 是 NEGATIVE**。原文寫得很白：「No tail hedge strategy consistently improves MDD across all OOS periods. ... 12/VIX VT already provides sufficient drawdown protection.」這不是 K544 「發現」的新東西 — 這是 **K544 用 19 年數據再次確認 Israelov 的結論**，並進一步指出：你已經有 12/VIX VT（volatility targeting）作為基礎時，再疊加尾端保險的邊際效益接近於零。

## K544 怎麼設計的？

K544 把六種配置全部跑了一遍：

- **VT only**：12/VIX 波動率目標，沒有任何尾端保險（baseline）
- **Buy & Hold**：純粹持有 SPY（對照組）
- **VT + always**：每月固定 2% 倉位買 5x 槓桿、行使價 -5% 的 put
- **VT + vix_cheap**：只在 VIX < 15 時買保險
- **VT + contango**：只在 VIX/VIX3M < 0.80（深度 contango）時買
- **VT + momentum**：只在 SPY 60 日報酬 > +10% 時買
- **VT + combined**：上述三條件中至少滿足兩項時買

四個「條件式」策略都是學術文獻和散戶群組裡常見的 timing rule。對照 baseline 是 **12/VIX volatility targeting**（K41 既有研究已驗證的 baseline，不是新策略）。比較指標包含 max drawdown、Calmar、Sortino、tail ratio、worst month、CVaR、crash month rate。

## Full Sample 結果：所有策略淨損益都是負

19 年累積數字（單位：% of NAV）：

| 策略 | MDD | 累積成本 | 累積賠付 | **淨損益** |
|---|---|---|---|---|
| VT only (baseline) | -28.60% | — | — | — |
| VT + always | -27.03% | 7.711 | 7.621 | **-0.089** |
| VT + vix_cheap | -28.62% | 1.585 | 0.368 | **-1.217** |
| VT + contango | -28.60% | 0.204 | 0.082 | **-0.122** |
| VT + momentum | -28.62% | 0.805 | 0.412 | **-0.393** |
| VT + combined | -28.62% | 0.350 | 0.000 | **-0.350** |

幾個關鍵觀察：

1. **MDD 改善幅度幾乎可以忽略** — 最積極的 always 策略，19 年累積花了 7.71% 換到 MDD 從 -28.60% 改善到 -27.03%，僅 1.57 個百分點。
2. **所有條件式策略淨損益都是負的** — 從 -0.122% 到 -1.217%。
3. **最尷尬的是 vix_cheap**：花最多錢（1.585%）、賠付最少（0.368%）、MDD 反而比 baseline 還差 0.02 pp。「VIX 便宜時買保險」聽起來合理，數據上是最差選項。

![圖 1：尾端對沖策略的成本與 MDD 改善](https://storage.volpred.zeabur.app/k544/fig1_mdd_vs_cost.png)

## 跨 OOS 期間：沒有一個策略全部都賺

把樣本切成三段獨立 OOS 來看一致性：

| 策略 | 2016-2019 平靜 | 2020-2021 Covid | 2022-2024 升息 | 平均 MDD 改善 (pp) | 全期都改善？ |
|---|---|---|---|---|---|
| always | -0.13 | -0.29 | -0.70 | **-0.37** | 否 |
| vix_cheap | -0.16 | 0.00 | 0.00 | -0.05 | 否 |
| contango | 0.00 | 0.00 | -0.05 | -0.02 | 否 |
| momentum | 0.00 | 0.00 | 0.00 | 0.00 | 否 |
| combined | 0.00 | 0.00 | 0.00 | 0.00 | 否 |

（負值代表 MDD 比 VT only 更差）

**沒有任何一個策略在三個 OOS 期間都改善 MDD**。always 策略平均改善竟然是 -0.37 pp（更糟），主要是 2022-2024 升息期間 -0.70 pp 拖累。

最值得玩味的是 **always 策略只在 Covid 期間賺錢**：2020-2021 的 net hedge PnL 是 +0.465%，是 19 年裡唯一一段正報酬。其他兩段都是賠的。換句話說，**那些「靠買 put 抓到 Covid 大跌」的故事是真的，但前提是你要「永遠」買、19 年不停買** — 而 19 年累積成本 7.71% 把這個收益完全抵銷掉了。

![圖 2：各 OOS 期間 MDD 改善熱圖](https://storage.volpred.zeabur.app/k544/fig2_oos_heatmap.png)

## 統計檢定怎麼說？

K544 跑了 t-test 比較對沖策略 vs VT only 的月報酬差。**always 策略在「最差 10% 月份」確實達到顯著水準**（t=3.446，達顯著水準（顯著性 0.0023））— 也就是說，在真正大跌的月份，always 平均比 baseline 多 +0.22% 月報酬。**問題是平時要付的成本把這個尾端保護完全吃掉**：總體月報酬差是 -0.0019%，t=-0.224，達顯著水準（顯著性 0.823），統計上 indistinguishable。

這正是 Israelov 2017 的核心論點：**put protection 在尾端是真的有效的，但平常的成本拉率（cost drag）會吃光保護價值，整體 NPV 為負**。K544 用更長的樣本（19 年 vs Israelov 原文約 12 年）再次確認這個結論在 2017 年之後依然成立。

![圖 3：各策略各 OOS 期間的尾端對沖淨損益](https://storage.volpred.zeabur.app/k544/fig3_net_pnl_by_oos.png)

## 那散戶到底要怎麼避險？

K544 的 verdict 同時帶出一個重要的**正面訊息**：你已經有 12/VIX volatility targeting 的話，**MDD 已經從 buy & hold 的 -55.19% 壓到 -28.60%**，這個壓縮幅度遠超過任何 put 策略能再榨出來的 1-2 pp。VT 不是新發現，是 K41 既有 baseline；但比較完 K544 之後可以更踏實地說：**對一般投資人，做好 VT 已經夠了，不需要再花心思（和錢）買尾端保險**。

如果你還是想加保護，K544 的數據暗示幾條：

- **不要相信「VIX 便宜時買保險」這種 timing rule** — 全期最差的就是它
- **不要每月都買** — 累積成本 7.71% 太貴
- 真要做的話，**always + VT** 是淨損益最不糟的（-0.089%），但要忍受 19 年慢慢出血換 1.57 pp MDD 改善

## 學術 framing 與下一步

K544 的貢獻是**用更長樣本（涵蓋 2018Q4、Covid、2022 升息、2024 高位）對 Israelov (2017) 的延伸驗證**，而不是原創發現。研究還能往兩個方向推進：

1. **Regime-conditional hedging**：條件不是固定 VIX/contango threshold，而是用 GARCH-based 機率模型判斷 regime（K15 既有 regime decomposition 可接）
2. **跨資產驗證**：K544 只跑 SPY；台股、新興市場、加密貨幣的尾端結構差異可能讓結論不同

但現階段對一般讀者的實用結論很清楚：**先做好 VT，尾端保險可以省下來**。

---

**研究方法說明**：本文所有數字直接來自 `experiments/k544/k544_tail_hedge_results.json`，樣本為 SPY / ^VIX / ^VIX3M 2006-07-17 至 2025-12-30 日頻資料（4,896 交易日，234 個月）。VT 配置：12/VIX 槓桿，月度再平衡。Put 模型參數：2% 倉位、5x 槓桿、行使價 -5%、月度到期。完整方法見 K544 README。

**參考文獻**：
- Bhansali, V. (2014). *Tail Risk Hedging: Creating Robust Portfolios for Volatile Markets.* McGraw-Hill.
- Israelov, R. (2017). "Pathetic Protection: The Elusive Benefits of Protective Puts." *Journal of Portfolio Management*, 43(5), 55-69.
- 內部研究：K41（VT 保險溢價約 4%/年）、K15（VT regime decomposition）、K43（VVIX/SKEW overlay null result）

**實驗編號**：K544
