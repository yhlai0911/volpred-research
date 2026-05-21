---
title: "策略池有 11 個，演算法怎麼幫你挑？K647 配對機制全公開"
audience: general
status: draft
tags:
  - strategy-matching
  - investor-profile
  - tx-cost
  - live-oos
  - pareto-frontier
experiment_refs:
  - K647
---

# 策略池有 11 個，演算法怎麼幫你挑？K647 配對機制全公開

平台目前同時追蹤 11 個量化策略：從最簡單的 12/VIX，到複雜的 Adaptive Tier、Taiwan Hybrid Leverage。對讀者來說最常見的問題是：「我該照哪一個做？」

K647 不是直接給答案，而是建一個**配對演算法**：先把投資人的條件（風險容忍、資金規模、市場 access、操作能力）變成數字，再把每個策略的屬性（Sharpe、MDD、複雜度、交易成本）也變成數字，然後算分排序。

這篇文章把這個演算法的**機制與結果**公開，特別聚焦在我們之前一篇舊文章沒寫到的兩個重點：**真實 live OOS 績效（15 個月）** 與 **交易成本的隱性殺傷力**。

> 註：這是 K647 的**升級版內容**。先前已有一篇 testing-style 的 K647 文章，使用更早期的 backtest 數字（Sharpe 2.81 / MDD -2.5%）。本次更新使用 2025-01 至 2026-03 共 15 個月真實 live paper trading 結果，數字略有變動，演算法機制本身不變。

---

## 演算法在做什麼？三步驟

**Step 1 — Hard Filter（硬性篩選）**：

- **市場 access**：你只能交易美股 → 自動剔除所有 0050.TW 策略
- **最低資金**：策略要求 \$20,000 → 你只有 \$10,000 就剔除（沒辦法做槓桿就是沒辦法）

**Step 2 — Score（多目標加權）**：

每個策略的得分 = `w1 × Sharpe + w2 × MDD safety + w3 × Simplicity + w4 × Capital fit`

權重隨投資人類型變化。例如保守型權重在 MDD 安全（0.5），積極型權重在 Sharpe（0.5）。

**Step 3 — Soft Penalty（軟性扣分）**：

- MDD 超過容忍：每超 10% 扣 0.15
- 複雜度超過偏好：每多 1 級扣 0.10
- 偏好低頻但策略每日再平衡：扣 0.05
- **Net Sharpe 為負（交易成本吃光報酬）：固定扣 0.20**

最後一條，是這次更新最關鍵的揭示。

---

## 真實 Live 數據：15 個月 OOS 排序

![策略池：Live Sharpe vs Maximum Drawdown](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k647v2_sharpe_vs_mdd_pareto_1920f9.png)

上圖把 11 個策略放在「Live Sharpe vs MDD」散布圖裡。**右上角=高 Sharpe + 低 MDD = 最理想**。

**驚人的發現**：橘圈標出的 **Piecewise Conservative VT** 同時握有 **Sharpe 3.975** 和 **MDD -2.48%** — 兩個維度都是策略池中最佳。

這在量化投資中幾乎不該發生。一般來說 Sharpe 高 → 倉位大 → MDD 也大。Piecewise Conservative 之所以能逃出這個 trade-off，是因為它有一個**極度保守的觸發機制**：只有市場真的平靜時才滿倉，一旦波動率有任何上升就快速縮倉。代價是牛市中漲幅捕捉率較低。

**重要 caveats**：

- 「Pareto dominant」**只在這 15 個月 live sample 內成立**。15 個月是短樣本（covers 2025 全年 + 2026 Q1），未經歷完整的牛熊循環。
- 紅點代表策略在這段期間 **net Sharpe 為負** — 看起來有正報酬（Live Sharpe 0.255 / 0.232），但扣完交易成本就被吃光。

---

## 交易成本：被忽視的策略殺手

![交易成本是策略排序的關鍵差異化](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k647v2_net_sharpe_after_tx_1920f9.png)

上圖把每個策略的 **gross Sharpe（藍）** 和扣完 TX cost 後的 **net Sharpe（綠/紅）** 並排。柱頂寫了該策略的年化交易成本。

最戲劇性的兩個 case：

| 策略 | Gross Sharpe | Net Sharpe | TX cost 年化 |
|---|---|---|---|
| 12/VIX (SPY) | 0.232 | **-0.417** | 5.99% |
| GARCH VT (SPY) | 0.255 | **-0.187** | 4.08% |

兩者看似有正 Sharpe，**扣完每日換倉的交易成本就是淨虧**。對應的演算法處置：固定扣 0.20，這兩個策略幾乎不可能進任何 profile 的 top-3。

反觀 **Risk Parity (SPY+GLD)** 的年化 TX cost 只有 **1.67%**（GLD 與 SPY 走勢分散，少需要再平衡），net Sharpe 高達 2.32，是池中扣完成本後第二好的策略。**這是「換手率」決定生死的最直接示範**。

---

## 三種投資人 → 三套答案

![三種投資人 Profile 配對結果](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k647v2_profile_match_matrix_1920f9.png)

| Profile | Top 1 | Top 2 | Top 3 |
|---|---|---|---|
| **保守型 (退休族)** \$50K, MDD≤5% | Piecewise Conservative (3.98 / -2.5%) | 50/50 SPY/GLD (2.00 / -7.7%) | VIX Cond Leverage (2.83 / -6.4%) |
| **標準型 (上班族)** \$10K, MDD≤15% | Piecewise Conservative (3.98 / -2.5%) | 50/50 SPY/GLD (2.00 / -7.7%) | Risk Parity (2.45 / -11.1%) |
| **成熟型** \$100K+, MDD≤20%, 含台股 access | Piecewise Conservative (3.98 / -2.5%) | Adaptive Tier VT (3.74 / -4.9%) | Taiwan Hybrid Leverage (3.76 / -8.5%) |

兩個有趣現象：

**1. Piecewise Conservative 三組都是第一名**

這不是 bug，是這 15 個月的 live sample 真實情況：它**同時主導所有三個篩選維度**。如果你問「我不知道我是哪種投資人，那選什麼？」— 演算法在當前資料下傾向回答 Piecewise Conservative，但**強烈建議**讀者在更長 sample（5 年以上）出現後再驗證。

**2. 成熟型才看得到台股 + 槓桿**

Adaptive Tier 與 Taiwan Hybrid Leverage 都需要 ≥\$15K-20K 與台股 access，hard filter 直接擋掉前兩個 profile。**這是真實制約，不是演算法偏好** — 散戶確實沒辦法做這些策略，承認這點比假裝平等推薦來得誠實。

---

## 誠實 Caveats

1. **15 個月 ≠ 完整循環**。Live sample 只覆蓋 2025-01 至 2026-03，主要是震盪偏多頭區間。一次 -30% 級空頭就可能完全改變排序。
2. **「Pareto dominant」是樣本內結論**。Piecewise Conservative 的觸發機制在持續低波動 regime 表現極佳，但若進入長期高波動環境，它的縮倉邏輯也可能讓它錯過反彈。
3. **演算法是輔助，不是處方**。Profile dimensions 只有 4 個（風險容忍、資金、市場、複雜度），真實投資人有更多 nuance（稅務、避險需求、流動性偏好）。
4. **複雜度評分主觀**。1-5 級由研究者標註，不同人對「複雜」的定義不同。
5. **TX cost 假設**。每筆 round-trip 10bps，未考慮個人券商手續費差異。

---

## 一句話結論

K647 不是要告訴你「買哪一個」，而是要告訴你：**你的條件決定哪些策略**對你**根本不可選**（hard filter），剩下的策略**交易成本會不會吃光報酬**（net Sharpe penalty），以及在當前 15 個月 live sample 中**哪一個同時兼顧高報酬與低風險**（Pareto dominant: Piecewise Conservative）。

下一步：跨更長 OOS、加入 cross-asset robustness、把 profile dimension 從 3 種擴充到 6-8 種（含稅務、流動性、避險需求）。

---

*本文基於實驗 K647（資料來源：K640 live audit paper_trading.json + strategy_metrics.json，期間：2025-01-02 至 2026-03-27 live OOS + 2022-01 至 2026-03 backtest，共 11 個策略 × 3 種投資人 profile）。*

*[提出: 用戶, 執行: Claude]*
