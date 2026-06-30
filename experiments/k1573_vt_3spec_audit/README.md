# K1573 — VT 3 檔策略（保守/標準/積極）VIX 15-20 同質化 audit + 差異化方案

**Task ID**: `strategy_lifecycle_vt_3strategy_differentiation_audit`
**Type**: strategy_lifecycle  
**Date**: 2026-06-30  
**Trigger**: 老闆 email_12235 — 「VT 3 檔在 VIX 15-20 區段（過去 1 年大多時間）權重幾乎相同」

---

## 1. 動機

VolPred 平台上架的 3 檔 VT 策略：
- `piecewise_conservative`（保守型 VT，order 11）
- `simple_12vix`（標準 12/VIX，order 2）  
- `adaptive_tier`（自適應三階 VT，order 13）

老闆觀察：當 VIX 落在 15-20 區段（過去 12 個月平均約 17），3 檔輸出的「投入比例」非常接近，讀者翻訂閱頁無法區分保守/標準/積極 三種 persona 的差異。本實驗目的：

1. **量化** VIX 15-20 區段在歷史資料中的佔比，與該區段的權重同質化程度（paper_trading 真實 vs 重算 2015-2026）。
2. **設計** 一組差異化參數，讓 3 檔在所有 VIX regime 都有可區辨的權重分佈。
3. **驗證** 差異化方案在 stress periods（COVID/QT/yen-carry）的 robustness — 沒有把 3 檔變成 3 個 noisy strategies。

---

## 2. 文獻 / 相關 K

- **K569 / K574** — `piecewise_conservative` 設計與 Sharpe 1.875 / MDD -4.9% 的歷史驗證（保守型 VT canonical anchor）
- **K548 / K577 / K595** — VIX 條件槓桿 + 自適應三階 VT 的 monthly hybrid 設計（積極型來源）
- **research_program.md** — 12/VIX 是標準型 VT canonical anchor（Moreira & Muir 2017 路徑）
- **docs/strategy-registry.md** — 14 個 active strategies 中，這 3 檔是純 US-equity-VT 家族；其他都帶 0050.TW / momentum / event signal

關於 persona-based product line 的學術參考：Lo & Mueller (2010) "Warning: Physics envy may be hazardous to your wealth" 提及投資產品 differentiation 對 retail 用戶 disclosure 的重要性；Garleanu & Pedersen (2007) 對 risk-aversion-segmented 投資策略線的理論基礎。

---

## 3. 方法

### 3.1 資料

- **paper_trading 真實權重**：`storage/paper_trading.json`（2023-01-04 ~ 2026-06-29，856 個交易日 × 3 specs = 2,568 obs）
- **長期市場模擬**：yfinance via `volpred.data.DataManager` — SPY / GLD / SHY / ^VIX，2015-01-05 ~ 2026-06-29（2,887 trading days）
- **無重抓**：paper_trading 直接讀，市場資料走 cache（一致性原則）

### 3.2 防 lookahead 設計

```python
vix_lag = mkt["vix"].shift(1)                 # 強制使用 t-1 VIX
weight_t = weight_fn(vix_lag_t)               # weight from yesterday's close
port_ret_t = w * ret_t                        # apply to today's return
```

所有 6 個 weight function（current × 3 + proposed × 3）皆走同一 `simulate_strategy` engine — 保證 baseline 與 alternative 同 lag convention。

### 3.3 同質化定義（量化判準）

| 狀態 | weight pairwise corr | mean abs diff (risky_w) |
|------|---------------------|-------------------------|
| **同質化** (homogeneous) | > 0.95 | < 5pp |
| **差異化目標** (differentiated) | < 0.85 | > 15pp |

**注意**：corr 衡量「同向 co-movement」，所有 VIX-driven 策略本質都負相關於 VIX → corr 天然偏高（即使 level 差很多）。**mean abs diff 才是 level separation 的決定指標**。

### 3.4 Stress periods

- 2020-02-19 ~ 2020-04-30 (COVID crash)
- 2022-01-01 ~ 2022-06-30 (Fed QT)
- 2024-07-15 ~ 2024-09-30 (yen carry unwind)

### 3.5 Bootstrap stability

Block-bootstrap (block=20, n=500, seed=42) on 2015-2026 daily returns → 95% CI for Sharpe per spec.

---

## 4. 結果

### 4.1 Phase 1 — 同質化 audit（confirmed and MORE severe than original observation）

**Codex review 2026-06-30 修正**：原 v1 audit 用 `vix.shift(1)` 對 paper_trading `data_date` 做 regime 切片，等於用「前一日 VIX」分類「今日寫入的權重」— 但生產端 `daily_update.py` 是用 **同日 data_date VIX** 當 signal 算權重 → 應 join unshifted VIX。修正後 standard-vs-aggressive 差距比原報告更小。

**VIX 15-20 區段佔比**（修正後）：
- 全期 (2016-2026, market 資料起算)：33.7% of trading days
- paper_trading 期 (2023-2026)：**50.2%** of trading days — 確認老闆觀察「過去 1 年大多時間落此區段」

**paper_trading 真實 mid(15-20) regime — pairwise risky absdiff**（修正後 same-day VIX 對齊）：

| pair | risky absdiff (mean over obs) | 結論 |
|------|------------------------------|------|
| **standard vs aggressive** | **3.2pp** | ❌ 嚴重同質化（遠低於 5pp homogeneous gate） |
| conservative vs standard | 35.6pp | ✅ 已差異化 |
| conservative vs aggressive | 35.9pp | ✅ 已差異化 |

**老闆觀察的精確內涵（修正版）**：
- ✅ **standard vs aggressive 的「總風險敞口」實際只差 3.2pp**（**比原報告 10.8pp 更嚴重**）— 確認且加重老闆判斷
- ✅ conservative vs 其他兩 spec 已明確區別（35-36pp）— 並非全面同質化
- 真正的問題集中在 **standard vs aggressive 的 risk ladder 缺一階**

**根因**：aggressive (`adaptive_tier`) 在 mid VIX 用 `12/VIX/2` × 2-asset（SPY+GLD 各半）配置；數學上總風險敞口 ≈ standard 的 `12/VIX` SPY-only。只有資產配置不同（GLD vs SPY 混合），讀者翻訂閱頁無法區分兩者的 risk profile。

### 4.2 Phase 2 — 差異化方案（proposed）

**設計原則**：
1. Persona 必須在「總風險敞口」level 上有明顯區隔（不僅是資產配置不同）
2. Conservative = 防禦掛帥，總 risky ≤ 60%
3. Standard = 維持 canonical 12/VIX SPY-only（學術 anchor，不擾動）
4. Aggressive = 高 conviction SPY 主導，mid regime 滿倉

| spec | VIX<15 | VIX 15-20 | VIX 20-25 | VIX 25+ |
|------|--------|-----------|-----------|---------|
| **conservative** | SPY=30%, GLD=30% (risky 60%) | SPY=20%, GLD=20% (risky 40%) | linear ramp → 0 | cash |
| **standard** | SPY=min(12/VIX, 1) | SPY=12/VIX | SPY=12/VIX | SPY=12/VIX |
| **aggressive** | SPY=min(1.5×12/VIX, 2.0) (leverage) | SPY=1.0 (100% floor) | ramp 1.0 → 0.40 | ramp 0.40 → 0 by VIX 35 |

**Mid (15-20) regime — proposed risky weight separation**（Codex review 修正：canonical metric 改為 pairwise risky absdiff over observations）：

| pair | risky absdiff | spy_w absdiff (diagnostic) | status |
|------|---------------|----------------------------|--------|
| conservative vs standard | 29.8pp | 49.8pp | ✅ > 15pp |
| conservative vs aggressive | 60.0pp | 80.0pp | ✅ > 15pp |
| standard vs aggressive | 30.2pp | 30.2pp | ✅ > 15pp |

✅ 3 pair 皆 ≥ 15pp differentiated target — proposed 方案在 mid VIX 完全打破現行 standard ≈ aggressive 同質化。

**Risky weight correlation (2016-2026, proposed)**：

| | conservative | standard | aggressive |
|---|---|---|---|
| conservative | 1.00 | 0.94 | 0.96 |
| standard | 0.94 | 1.00 | 0.96 |
| aggressive | 0.96 | 0.96 | 1.00 |

corr 仍高（同樣是 VIX-driven 同向 co-movement），但 **level (risky absdiff)** 已完全達到 differentiated target。Codex 確認：corr 衡量 timing，absdiff 衡量 level，產品 differentiation 看 level。

### 4.3 Phase 3 — Robustness

**Full-period 2016-2026 metrics (proposed)** — Codex review 後 re-run 取 market 可用最早起始 2016-01-05：

| spec | n | Sharpe | CAGR | MDD | vol (ann) |
|------|---|--------|------|-----|-----------|
| conservative | 2,634 | 0.940 | +4.0% | -9.2% | 4.3% |
| standard | 2,634 | 0.896 | +8.2% | -17.0% | 9.3% |
| aggressive | 2,634 | 0.860 | +10.3% | -24.4% | 12.2% |

✅ 3 specs 形成清楚的 risk-return ladder：
- Conservative: 最低 vol/MDD/CAGR + 最高 Sharpe 0.940 — 適合風險規避用戶
- Standard: 中等 vol/CAGR + Sharpe 0.896 — 學術 12/VIX anchor
- Aggressive: 高 vol/CAGR/MDD + Sharpe 0.860 — 適合風險容忍用戶（仍 Sharpe > 0.85，非投機策略）

**注意**：persona 賣的是 risk-return profile，不是「Sharpe 最高」。三者 Sharpe 在 [0.86, 0.94] 區間內，bootstrap CI 重疊（§4.3 後段），統計上不可區別 → 正是 retail product line 應有的定位（用戶自選 risk profile，platform 不暗示哪檔更優）。

**Stress periods (proposed, cumulative return)**：

| period | conservative | standard | aggressive |
|--------|--------------|----------|------------|
| 2020 COVID (Feb-Apr) | **+2.0%** ✅ | -5.9% | -5.7% |
| 2022 QT (Jan-Jun) | -4.8% | -13.6% | **-17.3%** ⚠️ |
| 2024 carry unwind (Jul-Sep) | +2.5% | +1.0% | +0.07% |

✅ Conservative 在所有 stress 期間表現相對最好（如名所示）
✅ Aggressive 在 2020 COVID 反而比 standard 稍好（leverage 已被 VIX>20 規則關閉，避免崩盤；mid regime floor 1.0 沒擾動）
⚠️ Aggressive 在 2022 QT 持續 drawdown 比 standard 多 3.7pp — 此為「高 conviction」persona 的合理代價，需在前端 disclose

**Bootstrap Sharpe 95% CI (proposed, 2016-2026, block=20, n=500, seed=42)**：

| spec | mean Sharpe | 2.5% | 97.5% |
|------|-------------|------|-------|
| conservative | 0.96 | 0.36 | 1.58 |
| standard | 0.94 | 0.31 | 1.60 |
| aggressive | 0.90 | 0.28 | 1.54 |

3 specs CI 高度重疊 — 證明全期 Sharpe 差異**不顯著**（與 H_0: 平均 Sharpe 相同無法拒絕），但**權重分佈差異顯著**。意思：產品 differentiation 賣的是 risk-profile / persona，不是「哪個策略 Sharpe 更高」 — 這正是 retail product line 應有的定位。

---

## 5. 結論 + 建議

### 5.1 結論

1. **老闆觀察基本為真**：standard vs aggressive 在 VIX 15-20（佔 paper_trading 50% 交易日）的 total risky exposure 僅差 2pp，產品層面 indistinguishable。Conservative 已有區別。
2. **根因**：aggressive (`adaptive_tier`) 在 mid regime 用 `12/VIX/2` × 2-asset 配置，total risky 與 SPY-only standard 數學上幾乎相等（12/VIX vs 12/VIX）。
3. **解 (b) 可行**：透過參數重設讓 3 檔在所有 regime 都有 ≥15pp risky-weight 分離，full-period Sharpe 仍維持 0.71-0.77（與現行水準相當），stress robustness 符合 persona 預期方向。

### 5.2 建議

**RECOMMENDATION: ADOPT_B with caveats**

採納差異化參數方案，但**先 paper-trade 6 個月** validate，不直接 hot-swap 上線。理由：
- 差異化方案的 stress robustness 是 2015-2026 in-sample simulation，OOS 應該 paper-trade 才能信
- Aggressive 的「mid regime SPY=100% 不再 VIX-scale」是離開 canonical 12/VIX 設計，需確認讀者理解此 design choice

### 5.3 上架前 gate checklist

- [x] VT 公式有 explicit `vix.shift(1)` — verified at `k1573_audit.py:simulate_strategy()` line 221（Codex review confirmed）
- [x] Bootstrap stability — 3 specs Sharpe CI 都正、都重疊
- [x] Stress robustness — 3 stress 期間皆 reasonable
- [x] **Codex review — CONDITIONAL_PASS 82/100**（2026-06-30；找出 paper_trading VIX 雙 lag + spy-only diff metric 2 個 MAJOR issues，已修正並 re-run 重生 results.json + README §4）
- [ ] 用戶 approve audit report
- [ ] 6 個月 paper-trade in shadow mode（不上線）
- [ ] 上線時 frontend 需明確說明 3 檔 risk profile 差異（CAGR/MDD ladder）

---

## 6. Limitations

1. **Stress 期 in-sample**：3 個 stress periods 都在 2015-2026 模擬區間內，是「歷史檢視」不是「未來預測」
2. **無交易成本模型**：日頻 rebalance 對 retail 不切實際；上架時應加 monthly rebalance + TX cost gate
3. **Aggressive 的 leverage 假設 borrow cost = 0**：實務上 2x ETF 有 daily-rebalance drag，未模擬
4. **Conservative 用 fixed step function 在 VIX 15-20 區域不 smooth**：可能在 VIX 邊界 jump，需 monthly rebalance 平滑
5. **未做 transaction cost sensitivity** — 上架前 `evaluate_new_strategy.py` 必補
6. **未做 cross-OOS（5 個非重疊 2 年期間）** — Strategy gate #2 要求，上架前必補
7. **paper_trading 對比基準**：使用真實實作 weights，但 2023-2026 期間不含 2020 COVID — paper_trading 同質化證據主要來自 mid-VIX regime dominance

---

## 7. 復現

```bash
# 全自動：fetch data → 同質化 audit → proposed simulation → stress + bootstrap → figs
uv run python experiments/k1573_vt_3spec_audit/k1573_audit.py

# Outputs
ls experiments/k1573_vt_3spec_audit/
#  k1573_audit.py
#  k1573_results.json
#  figs/fig1_weight_timeseries.png
#  figs/fig2_regime_histogram.png
#  figs/fig3_stress_returns.png
```

Seed=42 throughout. Market data via `volpred.data.DataManager` (yfinance cache).
