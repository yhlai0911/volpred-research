# VT 3-spec 同質化 audit + 差異化方案 — 待您審

**Date**: 2026-06-30  
**Trigger**: email_12235「VT 3 檔在 VIX 15-20 區段權重幾乎相同」  
**Experiment**: K1573 (`experiments/k1573_vt_3spec_audit/`)  
**Codex review**: 待跑 (Phase 5)  
**Recommendation**: **ADOPT_B with caveats** — 採差異化參數，但先 paper-trade 6 個月再上線

---

## 一、您的觀察的精確版本

paper_trading 真實資料 (2023-01 ~ 2026-06，856 個交易日)：

- **VIX 15-20 區段佔 50.1%** 的交易日（您觀察正確 — 過去一年大多時間落此區段）
- 該區段內 3 檔平均 total risky exposure：
  - conservative (piecewise): **34%**
  - standard (12/VIX): **70%**  
  - aggressive (adaptive_tier): **68%**

→ **真正的同質化是 standard vs aggressive (相差僅 2pp)**；conservative 其實已有區別。

根因：aggressive 在 mid regime 用 `12/VIX/2 × 50/50 SPY+GLD`，總 risky 數學上 ≈ standard 的 `12/VIX SPY-only`。產品層面 indistinguishable。

---

## 二、差異化方案（建議採用）

| spec | VIX<15 | VIX 15-20 | VIX 20-25 | VIX 25+ |
|------|--------|-----------|-----------|---------|
| **conservative** | SPY 30% + GLD 30% (risky 60%) | SPY 20% + GLD 20% (risky 40%) | linear ramp → 0 | cash |
| **standard** | SPY = min(12/VIX, 1) | SPY = 12/VIX | SPY = 12/VIX | SPY = 12/VIX |
| **aggressive** | SPY = min(1.5×12/VIX, 2.0) | SPY = 100% (floor) | ramp 1.0→0.40 | ramp 0.40→0 by VIX 35 |

**Mid-regime SPY 分離**：
- cons vs std: 50pp ✅
- cons vs agg: 80pp ✅  
- std vs agg: 30pp ✅

全部超過 15pp 的 differentiated target。

### 設計理由

1. **Conservative** — 防禦至上、SPY 永遠 ≤ 30%，GLD 分散，VIX 25 全現金
2. **Standard** — 維持 12/VIX 不動（學術 canonical anchor，文章引用大量基於此）
3. **Aggressive** — VIX 15-20 直接滿倉（不再 VIX-scale），VIX<15 真正 2x leverage，VIX>20 才開始 derisk

---

## 三、Robustness 驗證（2015-2026, 2,886 days, seed=42）

| spec | Sharpe | CAGR | MDD | vol |
|------|--------|------|-----|-----|
| conservative | 0.77 | +3.3% | **-9.2%** | 4.3% |
| standard | 0.77 | +7.0% | -17.0% | 9.4% |
| aggressive | 0.72 | **+8.5%** | -24.4% | 12.4% |

✅ 3 specs 形成清楚的 **risk-return ladder**（不是「哪個 Sharpe 較高」，是 3 個 risk profile）

### Stress periods (cumulative %)

| period | cons | std | agg |
|--------|------|-----|-----|
| 2020 COVID (Feb-Apr) | **+2.0%** | -5.9% | -5.7% |
| 2022 QT (Jan-Jun) | -4.8% | -13.6% | -17.3% |
| 2024 carry unwind | +2.5% | +1.0% | +0.07% |

✅ Conservative 在 3 個 stress 都最防禦（如名）
⚠️ Aggressive 在 2022 QT 比 standard 多 -3.7pp — 高 conviction 的合理代價，**前端必須揭露此 trade-off**

### Bootstrap Sharpe 95% CI

3 specs 的 CI 高度重疊 (0.16~1.40)，全期 Sharpe 差異**不顯著** — 這正是「persona / risk profile」產品線應該的特性（不是 alpha 之爭）

---

## 四、上架前 gate checklist

| # | gate | status |
|---|------|--------|
| 1 | VT 公式有 `vix.shift(1)` lookahead-safe | ✅ verified |
| 2 | Bootstrap stability (n=500, block=20, seed=42) | ✅ all 3 positive |
| 3 | Stress robustness 3 期間 | ✅ all reasonable，cons 最防禦 |
| 4 | Codex code review | ⏳ pending Phase 5 |
| 5 | 您 approve 本 audit report | ⏳ pending |
| 6 | 6 個月 paper-trade (shadow mode) | ⏳ pending approval |
| 7 | Cross-OOS 5 個非重疊 2 年期間 | ⏳ pending（gate #2 of registry） |
| 8 | TX cost sensitivity (monthly rebalance) | ⏳ pending |
| 9 | Frontend disclosure：3 個 risk profile 表 | ⏳ pending |

---

## 五、Recommendation 與替代選項對照

| option | 描述 | 評估 |
|--------|------|------|
| (a) 整併成 1 檔 | 砍掉 2 個 spec | 浪費 paper-trading 歷史 + 失去 persona 多樣化 ❌ |
| **(b) 改 VT 參數差異化** | 本方案 | **採用，先 shadow paper-trade** ✅ |
| (c) 下架重合者保 1-2 檔 | 砍 standard 或 aggressive 之一 | 失去 12/VIX canonical anchor 或 leverage persona ❌ |

**RECOMMENDATION: ADOPT_B with caveats**

---

## 六、本次不做什麼

- ❌ **不直接 hot-swap 上線** — 必須 shadow paper-trade 6 個月（per `docs/strategy-registry.md` 「不輕易上架」原則）
- ❌ **不修改 active `daily_update.py`** — 上線時主線程或下一輪 hourly fire 走 `list_new_strategy.py` 流程
- ❌ **不變更 standard (`simple_12vix`)** — 學術 canonical anchor，文章引用大量基於此

---

## 七、待您回覆的決策點

1. **採 (b) 嗎？** Y/N
2. **conservative 的 GLD 配置是否接受？**（原始 piecewise 也是 GLD，這裡保留同設計）
3. **aggressive 的 2x leverage 與 SPY=100% floor 是否接受？**（高 conviction，可能引起讀者疑慮）
4. **shadow paper-trade 期間多長？** 預設 6 個月，可改 3/9/12
5. **上線時新 spec 是否覆蓋舊 spec 的歷史 paper_trading？** 預設不覆蓋（forward tracking 原則），保留舊系列做 audit trail

---

## 八、附件

- 完整 results JSON：`experiments/k1573_vt_3spec_audit/k1573_results.json`
- 復現腳本：`experiments/k1573_vt_3spec_audit/k1573_audit.py`
- 圖：
  - `figs/fig1_weight_timeseries.png` — 2015-2026 risky weight + VIX overlay
  - `figs/fig2_regime_histogram.png` — risky weight 分佈
  - `figs/fig3_stress_returns.png` — 3 個 stress periods cumulative returns
