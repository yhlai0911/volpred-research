# K1100g_d1 — TAIFEX day-session vs night-session PRG decomposition

[提出: Claude 自主研究 / 執行: Claude worktree agent-k1100g-d1]

## 1. 動機

K1100g 量化了 TAIFEX vs SPY 的四項微結構差異並發現：
**TAIFEX overnight/intraday vol ratio = 1.586 vs SPY = 1.001**。

這被視為 Paper 3「PRG 成功並非方法通用，而是台灣市場特有微結構」
reframe 的 anchor。但 K1100g 只量化「**多少波動在 session 之間**」，
沒有直接回答「**哪一個 session 攜帶預測資訊**」。

K1100g_d1 直接 decompose TAIFEX session 結構並跑 4+1 個 PRG 模型，
回答以下問題：

1. 日盤 vs 夜盤哪個 session 的波動率資訊量較高？
2. 一個 session 的資訊可以改善另一個 session 的波動率預測嗎？
3. 交互預測方向是否對稱（night→day vs day→night）？
4. K1100g 報告的 1.586 ratio 在乾淨的 session-by-session 拆解下是否重現？

## 2. 數據與時段定義

- **來源**：TAIFEX TX tick 2017-2021（重新從 raw 檔案萃取）
- **合約**：每個檔案選當日最大成交量的月份合約（避開 rollover gap）
- **樣本**：1223 個交易日（raw），1077 個有完整 day+night+combined 的 aligned 樣本

### Session 切分（基於交易時間戳，per-file）

```
夜盤 session_t:  15:00 day_{t-1}  →  05:00 day_t    (≈14h active)
日盤 session_t:  08:45 day_t      →  13:45 day_t    (5h)
close-to-close:  day_close_{t-1}  →  day_close_t    (combined return)
```

**時序**：night_t 的結束（05:00）發生在 day_t 開盤（08:45）之前 → 
night_t 的資訊在 day_t 開盤前就已經觀察到 → **不是 lookahead**。

### K1100g cache 為何不能直接用

K1100g cache 的 `night_open` / `night_close` 以 `time_int ∈ {15:00-23:59, 00:00-05:00}` 直接 mask，但因為 TAIFEX 檔案本身跨多個 `成交日期`，cache 只抓到最末尾幾個 tick（相隔幾秒），造成 `sigma(r_night)` 只有 ~0.000083（假象）。**K1100g_d1 完全從 raw tick 重建**，得到 `sigma(r_night) = 0.0058`（合理）。

## 3. 模型設定

**PRG kernel**（multiplicative τ×g，Engle-Rangel 2008 識別化）：

```
τ_t  = θ₀ + θ₁·r²_{t-1} + Σ_k δ_k·D_k,t  [+ ξ·exog]
g_t  = ω + α·u²_{t-1} + γ·u²_{t-1}·I(r<0) + β·g_{t-1}
       其中 u_{t-1} = r_{t-1} / √τ_{t-1}
h_t  = τ_t × g_t
```

**識別**：`ω = 1 - α - γ/2 - β`（強制 E[g] = 1，讓 τ 承載絕對水平）。
自由參數：9（或加 exog 為 10）。

| Model | Target | Exog | 參數數 | 資訊集 |
|-------|--------|------|-------|-------|
| M1 | r²_combined (close-to-close) | — | 9 | baseline |
| M2 | r²_day (日盤 OC) | — | 9 | 無夜盤資訊 |
| M3 | r²_night (夜盤 OC) | — | 9 | 無日盤資訊 |
| **M4** | r²_day | **r²_night[t]** (contemporaneous) | 10 | 當日夜盤 → 日盤 |
| **M5** | r²_night | **r²_day[t-1]** (lagged) | 10 | 昨日日盤 → 今夜盤 |

M4 的 `r_night[t]` 合法：night_t 結束 05:00 早於 day_t 開盤 08:45。
M5 的 `r_day[t-1]` 是最近一個「在 night_t 開始前」觀察到的日盤。

## 4. 統計檢定

| 檢定 | 用途 | 為何適用 |
|------|------|---------|
| **LRT (primary)** | M4 vs M2、M5 vs M3 | Nested in-sample 的標準工具 |
| **HLN-DM (secondary)** | 同上 | DM 原本設計給 OOS+非 nested，in-sample nested 僅供參考 |
| **AIC/BIC** | 模型排序 | penalize 自由度 |

## 5. 結果

### 5.1 Session 波動率對比

```
sigma(r_day)   = 0.00759   (5 hours)
sigma(r_night) = 0.00581   (≈14 hours)
ratio night/day = 0.765
```

**H4 FAIL**: 與 K1100g 的 1.586 不符——因為 K1100g 量的是 `sigma(overnight_gap) / sigma(intraday)`，其中 overnight_gap 包含 day_close_{t-1} → day_open_t（19小時，含 75 分鐘 13:45-15:00 gap + 整個 night session + 3h45m 05:00-08:45 gap）。**本研究乾淨拆分後的 session-to-session ratio 是 0.765**——夜盤 14h 的總波動只比日盤 5h 多不到一倍。

**每小時常態化後**：sigma(day)/√5 = 0.00339, sigma(night)/√14 = 0.00155
→ **日盤每小時波動是夜盤的 2.19 倍**。

### 5.2 模型 Log-likelihood 對照

| Model | LL | AIC | per-obs LL |
|-------|-----|------|-----------|
| M1 Combined PRG | 3513.53 | −7009.05 | 3.266 |
| M2 Day-only PRG | 3847.92 | −7677.84 | **3.576** |
| M3 Night-only PRG | 4194.88 | −8371.75 | **3.899** |
| M4 Cross (night→day) | 3854.16 | −7688.32 | 3.582 |
| M5 Reverse (day→night) | 4196.47 | −8372.93 | 3.900 |

### 5.3 假設檢定結果

| # | 假設 | 通過? | 關鍵數據 |
|---|------|-------|---------|
| **H1** | 夜盤資訊量 > 日盤 | ✓ PASS | per-obs LL: night 3.899 > day 3.576 |
| **H2** | 夜盤幫助日盤預測 | ✓ PASS | LRT χ²=12.48, p=0.0004 |
| **H3** | 反向預測較弱 | ✓ PASS | night→day LRT p=0.0004 vs day→night p=0.075 |
| **H4** | 重現 K1100g 1.586 | ✗ FAIL | ratio = 0.765（不同切分方式） |

### 5.4 Paper 3 Reframe 機制解釋

**Dominant session: night**（per-obs log-lik 最高）
**Cross-prediction: night_to_day_dominant**（χ² 12.48 vs 3.18）

這提供 Paper 3 的 reframe narrative：

> TAIFEX PRG 的成功不僅因為「session 之間波動率差異」（K1100g 1.586 ratio 
> 在 gap 包含下成立），更因為「**夜盤 session 攜帶 asymmetric predictive 
> information 給日盤 session**」。當乾淨拆分 session-to-session 的波動率
> 結構時，日盤每小時波動其實比夜盤高（2.19×）——但夜盤因為跨越 14 小時、
> 承接多個外部衝擊（US 市場、地緣風險、經濟數據），其 close 的資訊對隔日 
> 08:45 開盤的日盤變異有統計顯著的前瞻預測力（LRT χ²=12.5, p=0.0004），
> 且這個方向是**非對稱**的（反向 p=0.075）。

## 6. 限制

1. **In-sample 擬合**：沒有 OOS validation。LRT 是 nested 模型的正規工具，
   但 DM HLN 統計量顯著降低（t=1.07 / 0.21），提示 OOS 改善不必然維持。
2. **QML 假設**：用 Gaussian kernel；residuals 顯示明顯厚尾，未來可換 Student-t。
3. **Sample period 2017-2021**：包含 COVID 衝擊。穩健性需跨 2013-2016 / 2022-2025。
4. **Active contract 篩選**：每個檔案選最大成交量的月份合約。在轉倉日前後，
   夜盤與日盤的主力月份可能不同——這個微差異未單獨建模（Codex MED rating）。
5. **H4 的「失敗」其實是重要發現**：K1100g 的 1.586 不是 session asymmetry 的
   本質度量，而是 **gap 效應** 的度量。論文應明確區分。

## 7. 衍生的 3 個新方向

1. **K1100g_d2（OOS 驗證）**：用 expanding-window OOS（2017-2019 train, 
   2020-2021 test）重測 M4 和 M5，檢查 LRT 顯著性是否 generalize。

2. **K1100g_d3（Student-t PRG）**：換成 Student-t innovation 重估 M1-M5，
   檢查厚尾是否改變 H1-H3 結論。QLIKE loss 可能更符合尾部行為。

3. **K1100g_d4（跨年度穩定性）**：把 2017-2021 拆成 5 個單年，逐年擬合 M4，
   觀察 night→day 預測效應是否隨年度波動。若 COVID 2020 主導效應則 reframe 
   的 narrative 需要修正（可能不是結構性，是事件驅動）。

## 8. 檔案

- `k1100g_d1.py` — 實驗腳本（PRG kernel、LRT、DM、chart）
- `k1100g_d1_results.json` — 完整結果 JSON
- `firm_decomposition.csv` — 1133 天 day/night/combined 序列
- `_cache_taifex_sessions_2017-2021.parquet` — 乾淨的 session cache
- `k1100g_d1_day_night_vol_ts.png` — 30 天 rolling std 對照
- `k1100g_d1_cross_prediction.png` — HLN-DM t-stat bar chart
- `k1100g_d1_prg_decomposition.png` — 5 model log-lik 對照

## 9. Codex 審查（執行於 2026-04-13）

Codex 抓到 4 個問題，全部修正：

- **HIGH (double-lag)**: M4/M5 的 exog 本來傳入已 shifted 的序列，然後
  kernel 再取 `[t-1]`，等於 double-lag。修正為 `exog_contemp=True` 
  flag，M4 直接傳 `r_night²` 並使用 `exog[t]`（contemporaneous 但 info 
  set 合法）。M5 維持 `r_day²` + `exog[t-1]`。
- **HIGH (in-sample DM on nested)**: 改為 **LRT 為 primary**、DM 為 
  secondary 報告，DM 加 HLN small-sample correction。
- **HIGH (identification)**: multiplicative τ×g 沒有強制 E[g]=1 → τ 和 g 
  尺度互吸收。修正為 `ω = 1 - α - γ/2 - β`（profile out），減少一個自由度。
- **MED (JSON NaN)**: 加入 `clean_for_json()`，用 `allow_nan=False` 保證
  輸出是 strict JSON。

## 10. Seed 與可重現性

- `np.random.seed(42)` + `np.random.default_rng(42)`（全域）
- `fit_prg()` 內部也用 `np.random.default_rng(42)` 建 restart 初值
- L-BFGS-B 為 deterministic optimizer
- 重跑應得到完全相同結果（已驗證）
