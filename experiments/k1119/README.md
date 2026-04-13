# K1119: BTC native IV (Deribit DVOL) vs US VIX — Paper 4 crypto case

> **Status**: results pending (run logged in `run.log`). Narrative template below is
> filled in programmatically when `k1119.py` finishes (see `k1119_results.json`).

## 研究問題

Paper 4 Universal IV Sufficiency compendium 的 crypto 分支：
K916（MF-GJR on BTC with VIX）顯示 BTC 對 US VIX 幾乎無反應
（BTC-VIX lag1 corr = 0.055 vs SPY 0.547），DM t=-2.81（Harvey FAIL）。
K1118 用「30-day rolling realized vol」當 BTC 的 IV proxy — 不是真正的 native IV。

**K1119 決定性問題**：換成真正的 **Deribit DVOL**（BTC 期權隱含波動率官方指數，
2021-03-24 起 public），native IV 是否足以預測 BTC 未來波動率？這是 Paper 4
universal IV sufficiency 在 crypto 的 clean test。

## Hypotheses

- **H1 SUFFICIENT**：A4f-DVOL 在 daily rolling OOS 上 Harvey PASS（|t|>3）且 VaR
  Trinity 至少在一個 alpha 過關 → 「crypto native IV works」，與 SPY/GLD/TLT 並列。
- **H2 NULL**：DVOL 加進 GJR 毫無增益 → crypto 是 IV-insufficient asset class；
  Paper 4 narrative 改為「native IV 在 equity/commodity/bond 充分，但 crypto 無法」。
- **H3 PARTIAL**：2<|t|<3 或 sub-period 不穩 → 中間地帶，需要更長歷史或 regime-conditional。

## 資料

| 序列 | 來源 | 樣本 | 備註 |
|---|---|---|---|
| BTC-USD OHLCV | yfinance | 2020-01-01 → 2026-04-13 (n=2,295) | close-to-close log return |
| Deribit DVOL (BTC) | `public/get_volatility_index_data` | 2021-03-24 → 2026-04-13 (n=1,847) | 日頻 UTC close |
| CBOE VIX | yfinance ^VIX | 2020-01-02 → 2026-04-13 (n=1,577) | 對照組 |

Panel 由 DVOL 起始點決定：**2021-03-24 → 2026-04-13**，daily n=1,847 / weekly n=263。
VIX 只在美股交易日有值，在 BTC 的 24/7 panel 上 forward-fill 最多 3 天。

## 方法

### 1. Weekly OLS battery（對齊 K1116/K1118 框架）
- Target：週 RV = √(Σ r_t²)（週五-週五）
- M1: AR(1) baseline
- M2: AR(1) + VIX_lag1（US VIX 在 BTC 上還有用嗎？）
- M3: AR(1) + DVOL_lag1 ← **主 hypothesis**
- M4: AR(1) + DVOL_lag1 + VIX_lag1
- M5: AR(1) + DVOL_lag1 + |Σr|_lag1（直接殘差訊號）
- IS: 2021–2023 / OOS: 2024–2026
- Head-to-head DM: M2 vs M3（DVOL vs VIX 直接較量）

### 2. Daily GJR-GARCH vs A4f-DVOL（GARCH-MIDAS 架構）
- GJR(1,1)：σ²_t = ω + α r²_{t-1} + γ r²_{t-1} I(r<0) + β σ²_{t-1}
- A4f-DVOL：σ²_t = g_t · τ_t
  - g_t GJR(1,1) with EGS E[g]=1
  - log(τ_t) = m + θ · z(DVOL²_daily)（z-score 穩定數值）
- Rolling 2y window（504d），one-step-ahead forecast
- 每次 re-fit 兩個模型，記錄 h_GJR, h_A4f, r, r²

### 3. Evaluation
- QLIKE（Patton 2011 proxy-robust）
- DM-HLN with Harvey (2016) |t|>3.0 門檻
- Sub-period stability（2023/2024/2025/2026）
- VaR/ES trinity（Kupiec + Christoffersen CC + Basel traffic light）
  with Student-t scaling（df MLE）at α = 1% 和 5%

### Lookahead discipline
- `signal.shift(1)` 明確寫在 weekly `make_X` 裡
- A4f forecast：`next_h = g_{t+1} · τ_t` 其中 τ_t 只用到 DVOL_{t}（= 訓練期最後一天的 DVOL）
- 所有 random seed = 42

## 預期決策樹

| 結果 | Verdict | Paper 4 narrative 影響 |
|---|---|---|
| A4f DM t>3 & VaR PASS | **H1 SUFFICIENT** | universal IV 擴展到 crypto；DVOL 是正確工具，VIX 在 K916 的失敗是 instrument mismatch |
| A4f DM \|t\|<2 or GJR wins | **H2 NULL** | crypto 屬 IV-insufficient；Paper 4 revise 為 equity/commodity/bond sufficient, crypto exception |
| 2<\|t\|<3 or 分期不穩 | **H3 PARTIAL** | 需要更長歷史或 regime conditional，先掛 future K1120 |

## 局限

- **DVOL 僅 2021-03-24 起**：錯過 2020 COVID crash 與 2021 之前 BTC 大 cycle。
  OOS window 只涵蓋 1 個完整 bull-bear-halving cycle。
- **DVOL 是 BTC-only**：無 ETH/大盤 crypto 的 IV 對照；結論僅限 BTC。
- **weekly RV 使用 close-to-close**：BTC 24/7 下 weekly 聚合 5–7 天並非 trading-day 對齊，
  與 K1116 SPY 的週框略有結構差異。
- **VIX 對 BTC 在週末有 forward-fill**：可能略微低估 VIX 的 noise；head-to-head 應保守解讀。

## Files

- `k1119_fetch.py` — Deribit DVOL + yfinance 下載
- `k1119.py` — 主實驗（weekly battery + daily GJR vs A4f-DVOL + VaR trinity）
- `k1119_results.json` — 完整數字結果
- `k1119_dvol_vs_vix.png` — DVOL vs VIX 時序圖（+ Pearson corr 標註）
- `k1119_qlike_timeseries.png` — 30d rolling QLIKE: GJR vs A4f-DVOL
- `run_fetch.log`, `run.log`

## 結論（H2 NULL）

**Verdict: H2 NULL — DVOL 無法打敗純 GJR。**

### 核心數字（daily rolling OOS, n=1,343, 2022-08-10..2026-04-13, window=504d）

| 指標 | GJR | A4f-DVOL | 差距 |
|---|---|---|---|
| OOS QLIKE | -6.4018 | -6.3956 | **-0.10% A4f 劣化** |
| DM-HLN t (A4f − GJR) | — | — | **-0.177 (p=0.860)** |
| Harvey \|t\|>3 | — | — | **不過** |

### 權重週頻 OLS battery（OOS 2024+, n≈67 週）

| 模型 | OOS QLIKE | DM vs M1 | p |
|---|---|---|---|
| M1_AR1 | **-4.3909** | baseline | — |
| M2_AR1_VIX | -4.3836 | t=-0.49 | 0.63 |
| M3_AR1_DVOL | -4.3728 | t=-0.27 | 0.79 |
| M4_AR1_DVOL+VIX | -4.3563 | t=-0.47 | 0.64 |
| M5_AR1_DVOL+\|r\| | -4.3735 | t=-0.26 | 0.79 |
| **M2 vs M3 (VIX vs DVOL)** | — | **t=-0.18** | 0.86 |

AR(1) baseline 本身最強；加 DVOL 或 VIX 都沒有顯著改善，兩者之間也打平。

### Sub-period DM (A4f − GJR)
| 年 | n | QLIKE GJR | QLIKE A4f | DM t | p |
|---|---|---|---|---|---|
| 2023 | 365 | -6.529 | -6.501 | -0.32 | 0.75 |
| 2024 | 366 | -6.169 | -6.124 | -0.93 | 0.35 |
| 2025 | 365 | -6.698 | -6.734 | +0.99 | 0.32 |
| 2026 | 103 | -6.109 | -6.181 | +1.06 | 0.29 |

A4f 在 2025-2026 後半段 marginal positive t 但從未達 Harvey |t|>3。無穩定 sub-period edge。

### VaR Trinity（Student-t scaled, α=1%, 5%）

| α | 模型 | Kupiec | CC | Basel | Trinity |
|---|---|---|---|---|---|
| 1% | GJR | pass (19 viol, rate=1.4%, p=0.15) | pass (p=0.19) | green | **PASS** |
| 1% | A4f-DVOL | fail (25 viol, rate=1.9%, p=0.005) | fail (p=0.014) | yellow | **FAIL** |
| 5% | GJR | pass (55 viol, p=0.12) | pass (p=0.07) | red (>expected) | FAIL |
| 5% | A4f-DVOL | pass (76 viol, p=0.28) | pass (p=0.52) | red | FAIL |

**GJR 贏 1% VaR trinity；A4f-DVOL 反而因為 Student-t df=6.47 (vs GJR 12.40) 過度放大尾部而 over-violates。**

### 基本統計（daily, 2021-03..2026-04）
- DVOL mean 61.71%、VIX mean 19.15%（BTC IV ~3.2× VIX）
- corr(DVOL, VIX) = 0.300（中度），corr(DVOL, BTC 日報酬) = -0.060（幾乎無方向訊號）
- A4f theta 估計值 avg=0.559，100% 的 rolling window theta>0 → DVOL 確實和未來 variance 同向，但邊際資訊被 GJR 的自我回歸完全吸收

### Paper 4 narrative

> **Paper 4 Universal IV Sufficiency 的 crypto 分支結論**：即使換成 BTC 自己的 native IV
> (Deribit DVOL)，也無法打敗純 GJR-GARCH。**crypto 是 IV-insufficient asset class**。
>
> 這跟 K1116（SPY native VIX 充分）、K1118（GLD/TLT native IV 充分、EPU/NFCI 無效）
> 形成對比。Paper 4 narrative 從 "VIX is the wrong instrument for crypto" 演化為
> "IV-based vol predictability is equity/commodity/bond specific; crypto 的波動率
> 結構不允許 option-implied information 產生 OOS edge"。
>
> 可能的機制解釋（待後續實驗驗證）：
> 1. BTC options 市場仍相對薄（Deribit dominant 但 retail/options-flow 結構 vs 美股不同）
> 2. crypto funding-rate/基差在波動率訊息傳導上可能主導 options IV
> 3. GJR 在 BTC 上持續度 avg=0.84，本身已 capture 了 long memory；DVOL 的邊際訊息被吸收

### 局限

- DVOL 僅 2021-03-24 起，無 2020 COVID / 2017-2019 cycle
- BTC-only（無 ETH/大盤）——結論對「crypto 整體」外推需 K1120 後續驗證
- Rolling window 504 天；更長 window 可能改變 GJR 估計的穩定性（未測）
- OOS 1343 天仍遠多於 Hwang & Valls Pereira 最低 252 天要求，樣本已充足
