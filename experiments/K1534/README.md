# K1534 — Realized CRP 左尾 spike 前置訊號 event-study

**Date**: 2026-06-23
**Type**: Descriptive event-study (NOT a trading backtest)
**Verdict**: **CONDITIONAL_PASS** — VIX term structure (VIX3M/VIX) 在 ρ_R spike 前 5 日有 Holm-corrected p<0.05 的顯著壓縮；其他 (feature, lag) 組合不顯著。

---

## Motivation

Driessen-Maenhout-Vilkov (2009, *Journal of Finance*) 用 **implied** correlation 推導 correlation risk premium。本 K 用 **realized** correlation proxy ρ_R(t)，目的不是估 premium，而是檢定：當 SPY 與其 top-10 持股之間的實現相關性「整體飆升」(everything-correlates spike) 時，前 1/5/10 個交易日的 VIX-family + breadth 訊號**是否有統計顯著的領先變化**。

商業 / 學術相關性：
- 若 spike 可預警 → 後續 K 可建構 short-correlation carry 擇時策略（dispersion trading 風險管理）
- 學術上補上「realized 版本 DMV」在 spike 前 lead-time 訊號的描述性 evidence

**Scope hard limit**: 本 K 只回答「訊號是否 statistically lead spike」，**不**回答「能否交易獲利」（後者需 OOS lead-time backtest + transaction cost，屬未來 K）。

---

## Differentiation vs Prior K

| K | 主題 | 方法 | 區別 |
|---|------|------|------|
| K1418 | SPY 集中度 vs constituent vol gap | descriptive vol-gap | 沒算 ρ_R，沒做 event-study，沒 significance test |
| research_risk_regime_correlation_breakdown | SPY/TLT regime breakdown | regime detection | stock-bond cross-asset，非 SPY-component |
| K559 (planning) | 未完成 | — | — |
| **K1534 (本 K)** | **ρ_R spike onset 前置訊號** | **realized DMV proxy + event-study + Holm-Bonferroni** | **正式 significance test + onset 獨立性處理** |

---

## Method

### 1. 數據（全免費 yfinance）
- **Universe**: SPY + top-10 持股 (AAPL, MSFT, NVDA, GOOG, AMZN, META, BRK-B, AVGO, LLY, JPM)
- **VIX family**: ^VIX, ^VIX9D, ^VIX3M
- **期間**: 2018-01-01 → 2026-06-01 (~2092 trading days)
- **Auto-adjust=True**（除權息調整）

### 2. ρ_R 計算

每日 log return → 21-day rolling realized variance (σ²)。每個 grid point t：

$$\rho_R(t) = \frac{\sigma^2_{index}(t) - \sum_{i=1}^{10} w_i^2 \sigma^2_i(t)}{\left(\sum_i w_i \sigma_i(t)\right)^2 - \sum_i w_i^2 \sigma^2_i(t)}$$

分母等於 $\sum_{i \neq j} w_i w_j \sigma_i \sigma_j$ — Driessen-Maenhout-Vilkov 簡化版。權重 $w_i = 0.1$（等權，descriptive 簡化；非精確 SPY weights）。

### 3. Spike onset 偵測（含獨立性修正）

- Threshold = ρ_R 整段樣本 90th percentile = **0.387**
- Raw onsets = ρ_R 從 ≤thresh 升破 >thresh 的 rising-edge 日
- **獨立性過濾**（CRITICAL fix from code review）：若 onset_{i+1} 距前一個保留 onset < `rv_window` = 21 trading days，**捨棄** — 否則兩個 spike 共用同一批 returns 估 ρ_R，違反 Welch t 獨立性假設，會顯著低估標準誤
  - Pre-filter raw onsets: 14
  - Post-filter independent onsets: **7**

### 4. 識別到的 7 個獨立 spike 事件

| Onset | 對應宏觀事件 |
|-------|------------|
| 2018-02-08 | "Volpocalypse" — XIV blow-up 後續 |
| 2018-12-26 | 2018 年底 Powell pivot 前的恐慌 |
| 2019-08-23 | 8 月 yield-curve inversion + tariff escalation |
| 2020-02-27 | COVID-19 全球擴散 onset |
| 2022-06-01 | 2022 通膨 cliff |
| 2022-09-19 | Fed 75bp 加碼 + UK gilt crisis 前夕 |
| 2025-04-04 | 2025 關稅衝擊 |

### 5. 特徵與 lags

| Feature | 定義 |
|---------|------|
| `vix` | VIX index level (t) |
| `vix_ts` | VIX3M / VIX — term structure；<1 = 倒掛 = 短期恐慌 |
| `breadth` | 10 檔成分股當日正報酬比例的 21-day MA |

Lags: **{-10, -5, -1}** trading days before onset。

### 6. 統計檢定
- **Spike sample**: 7 個 onset，feature 在 `onset + lag` 取值
- **Control sample**: 從非 spike-window (±21 d) 的 trading days 隨機抽 500 個 (seed=42)
- Welch's t-test (two-sided) + Mann-Whitney U (robustness)
- **Multiple testing**: Holm-Bonferroni 在 9 個 (3 features × 3 lags) tests

### 7. Lookahead 與 seed 防範
- 所有 features 在 `onset + lag` 評估，lag∈{-10,-5,-1} 嚴格 ≤ -1 → feature 在 onset 之前
- ρ_R(t) 用 returns r_{t-20..t} — 是 descriptive marker（不是 forecast），不需 shift
- `np.random.seed(42)` + `np.random.default_rng(42)` 全程固定

---

## Results

### Holm-corrected significance table (sorted)

| Feature × lag | t | p (Welch) | p (Holm) | Significance |
|---|---|---|---|---|
| **vix_ts_lag_-5** | **-4.28** | **0.0045** | **0.0402** | **★★ (<0.05)** |
| vix_ts_lag_-10 | -4.06 | 0.0080 | 0.0584 | ★ (<0.10) |
| vix_ts_lag_-1 | -3.96 | 0.0073 | 0.0584 | ★ (<0.10) |
| vix_lag_-1 | +3.54 | 0.0116 | 0.0696 | ★ (<0.10) |
| breadth_lag_-1 | -3.31 | 0.0151 | 0.0757 | ★ (<0.10) |
| breadth_lag_-10 | -2.10 | 0.0892 | 0.3569 | ns |
| breadth_lag_-5 | -1.46 | 0.1922 | 0.5765 | ns |
| vix_lag_-10 | +0.40 | 0.7041 | 1.0000 | ns |
| vix_lag_-5 | +0.68 | 0.5185 | 1.0000 | ns |

### Descriptive event-study (lag=-5)

| Feature | Spike pre-event mean (n=7) | Control mean (n=500) |
|---|---|---|
| VIX level | 21.15 | 19.67 |
| VIX3M/VIX (term structure) | **1.04** | **1.13** |
| Breadth (21-MA pct positive) | 0.506 | 0.537 |

### Headline finding

> **VIX term structure (VIX3M/VIX) 在 ρ_R spike 前 5 個交易日壓縮至 1.04（接近倒掛），相對於 control 1.13 有 Holm-corrected p=0.040 的統計顯著差距。Spike 前 5-10 天的恐慌已部分定價於 VIX term structure，但 breadth 與 VIX level 在 corrected level 上未獨立 lead。**

---

## Verdict logic

- ≥1 個 (feature, lag) Holm p<0.05 → **CONDITIONAL_PASS**
- 即使 Holm p<0.01 也**不直接 PASS**，因為：
  1. ρ_R 用 21-day rolling RV，t-day spike 與 t-5/t-10 的市場壓力有 mechanical persistence（相關性 ≠ 純 lead）
  2. n=7 樣本小（雖已排除 overlapping window），長期穩定性需更多 spike 累積
  3. 此 K 為 descriptive event-study；任何「可交易」claim 需獨立 OOS lead-time backtest（後續 K）

PASS 門檻保留給「OOS validation + transaction cost test」級別的證據。

---

## 防錯規則自評（per `.claude/rules/experiments.md`）

| 規則 | 自評 | 證據 |
|---|---|---|
| Lookahead 防範 | ✅ | features 在 `onset + lag` (lag<0) 評估；ρ_R 為 descriptive marker，非 forecast；不適用 `signal.shift(1)`（沒有 baseline strategy） |
| Seed 固定 | ✅ | `SEED=42`，`np.random.seed(42)` + `np.random.default_rng(42)` |
| Codex / 第三方 code review | ✅ | `feature-dev:code-reviewer` subagent（Codex CLI fallback per `.claude/rules/experiments.md`）— 找到 **CRITICAL bug** (overlapping RV window 違反 Welch 獨立性) 並已修正 |
| 套件 fail → 手算 | ✅ | RV / correlation 全用 numpy 手算，未依賴 套件 |
| QLIKE direction | N/A | 本 K 是 event-study，不涉及 variance forecast loss |
| Pooled-MLE 100+ multistart | N/A | 不涉及 MLE |
| 跨資產 pooled iid 誤用 | N/A | 不是 panel inference |
| 結果好得不像真的 = 90% bug | ✅ | 修正前 9/9 tests p_holm<0.05 觸發此警示；review 找到 overlapping RV window bug；修正後 onsets 14→7，僅 1 個顯著 (Holm<0.05) — 合理 |

---

## Files

- `K1534.py` — 完整可重跑腳本
- `K1534_results.json` — 結構化結果（含 onset dates、gap 分佈、9 tests stats、Holm 校正）
- `fig_rho_R_timeseries.png` — ρ_R(t) 時序圖 + threshold + onset markers
- `fig_event_study_lags.png` — 三特徵 × 三 lags subplot

---

## 重跑指令

```bash
uv run python experiments/K1534/K1534.py \
  --start 2018-01-01 --end 2026-06-01 \
  --top 10 --rv-window 21 --spike-pct 0.90
```

需網路（yfinance）+ ~3 分鐘。Seed 固定，結果應 bit-exact 重現。

---

## Future K (不在本 K scope)

1. **OOS lead-time profitability**: 用 vix_ts_lag_-5 < threshold 作 short-correlation 進場訊號，跨期間 OOS backtest + transaction cost。
2. **跨市場驗證**: TW 0050、HSI、N225 的 ρ_R spike 是否同樣被 local term-structure lead。
3. **Implied vs realized 比較**: 若取得 OptionMetrics IV，比較 implied correlation 與 ρ_R 的 spike timing 是否一致。
4. **Spike 規模 scaling**: spike 持續天數、最大幅度與 lead-time 訊號強度的關係。
