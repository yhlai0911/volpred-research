# K1397: VIX Memorial Day Seasonality — 35-Year Calendar Anomaly Analysis

**Proposer**: 自主發現（紀念日前後 VIX 行為研究）  
**Executor**: Claude · **Date**: 2026-05-22  
**Verdict**: **SIGNAL — Pre-holiday VIX compression statistically significant; post-holiday rebound NOT supported; 2020s regime weakening**

---

## 1. Motivation

Memorial Day（陣亡將士紀念日，每年五月最後一個週一）是美股最重要的三連假之一。VIX 代表市場對未來 30 日的隱含波動率。

研究問題：
- **H1**：假日前 5 個交易日，VIX 系統性下降（市場降低避險需求）？
- **H2**：假日後 5 個交易日，VIX 系統性反彈？
- **H3**：此效應在不同年代（decade）是否一致？

---

## 2. Data & Method

- **VIX 資料**：CBOE VIX 日收盤價，1990-01-02 ~ 2026-04-17（9173 個交易日）
- **Memorial Day 識別**：每年五月最後一個週一（確認：2024-05-27、2025-05-26、2026-05-26）
- **事件窗口**：假日前 5 個交易日（Day -5 到 Day -1）；假日後 5 個交易日（Day +1 到 Day +5）
- **統計方法**：
  - 單樣本 t 檢定（均值是否顯著異於 0）
  - 二項式比例檢定（正/負比例是否顯著異於 50%）
  - 配對 t 檢定（post vs pre 差異）
- **樣本數**：N = 36 年（1990–2025）

---

## 3. Results

### H1 — Pre-holiday VIX compression: **PASS (Harvey-significant)**

| 指標 | 數值 |
|------|------|
| 假日前 5 日 VIX 平均變動 | **-4.24%** |
| 標準差 | 8.81% |
| t 統計量 | **-2.85** |
| p 值（雙尾） | **0.007** |
| VIX 下降年數 | **27/36（75%）** |
| 二項式 p 值 | **0.004** |

### H2 — Post-holiday VIX rebound: **FAIL (p=0.939)**

| 指標 | 數值 |
|------|------|
| 假日後 5 日 VIX 平均變動 | +0.12% |
| t 統計量 | 0.08 |
| p 值（雙尾） | 0.939 |
| VIX 上升年數 | 16/36（44%）|
| 二項式 p 值 | 0.618 |

### H3 — 年代分析: **2020s 制度轉變**

| 年代 | N | 假日前 5d 均值 | 假日後 5d 均值 |
|------|---|---------------|---------------|
| 1990s | 10 | -5.89% | +1.29% |
| 2000s | 10 | -3.18% | -1.45% |
| 2010s | 10 | -6.48% | +3.50% |
| 2020s | 6  | +0.48% | -4.85% |

**2020s 例外**：2023 年 VIX 假日前 +4.30%；2025 年假日前 +22.88%（關稅衝擊背景）

---

## 4. Code Review Note

Code reviewed by main thread: simple statistical pipeline (t-test, binomial test, decade aggregation). No lookahead risk (historical event-window analysis, not forecasting). Seeds not applicable (no stochastic simulation). 

**Verdict**: CONDITIONAL_PASS — embedded evidence for event_article; not a full strategy backtest.

---

## 5. Files

- `k1397.py` — Analysis script
- `k1397_results.json` — Numerical results
- `figures/memorial_day_vix_seasonality.png` — Chart
