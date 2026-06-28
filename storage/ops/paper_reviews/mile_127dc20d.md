# Paper Review — mile_127dc20d (Codex 24h-rule, K1018 lesson)

**Article**: 「預測輸了，守底線卻贏了：一個模型的分裂成績單」
**Published**: 2026-06-28T01:00:26Z
**Source experiment**: K1403 (HAR-RV Quantile Forecasting Cross-Asset Robustness)
**Reviewer**: hourly-21 main thread (Codex 24h-rule audit per .claude/rules/agent-delegation.md K1018 lesson)
**Verdict**: PASS

---

## 1. Number verification (article ↔ k1403_results.json 對照)

### 點預測誤差倍率（article 高出 X%）

| 資產 | Article | Code-derived | Match |
|------|---------|--------------|-------|
| QQQ | 高出 44% | 44.07% (qmed_qlike 2.490 vs ols 1.728) | ✅ |
| GLD | 高出 64% | 64.03% (qmed 2.134 vs ols 1.301) | ✅ |
| TLT | 高出 35% | 35.15% (qmed 1.485 vs ols 1.099) | ✅ |

DM 三資產 stat = -12.68 / -10.51 / -11.59, p ≈ 0.000 (signs all NEG → OLS 顯著更低 QLIKE) ✓

### 尾端覆蓋率偏差（百分點）

| 資產 | 95% claim | 95% actual | 99% claim | 99% actual |
|------|-----------|------------|-----------|------------|
| QQQ | +0.42 | +0.424 | +0.11 | +0.114 |
| GLD | +0.06 | +0.055 | +0.26 | +0.262 |
| TLT | -0.54 | -0.535 | -0.03 | -0.033 |

All within rounding tolerance ✅

### Kupiec UC p-value range (claim 0.31 ~ 0.93)

| 資產 | q95 p | q99 p |
|------|-------|-------|
| QQQ | 0.467 | 0.666 |
| GLD | 0.925 | 0.309 |
| TLT | 0.374 | 0.903 |

Lowest = 0.309 (≈ article 0.31 ✓) / Highest = 0.925 (≈ article 0.93 ✓)
All 6/6 PASS Kupiec UC (p > 0.05) ✓

---

## 2. Methodology audit (K1018 lookahead + DM overclaim primary risks)

### Lag / lookahead — CLEAN ✅
- `experiments/k1403/k1403.py:69-81` `build_har_panel`
- `rv_d = daily_rv.shift(1)` (line 72)
- `rv_w = daily_rv.rolling(5).mean().shift(1)` (line 73)
- `rv_m = daily_rv.rolling(22).mean().shift(1)` (line 74)
- 後接 `.dropna()` 確保 train 起點所有 lag features 已 ready
- target `daily_rv = |ret_pct|`（未 shift）— 預測 row t 的當日 vol，features 用 t-1 為止資訊，無 lookahead

### DM test sign convention — CORRECT ✅
- `dm_test(qlike_ols, qlike_qmed, h=1)` (line 197) → d = qlike_ols − qlike_qmed
- mean_diff < 0 → mean(qlike_ols) < mean(qlike_qmed) → OLS 損失較小（OLS 勝）
- Code `classify_dm_status` 對應：`dm_stat < 0 → SIG_NEG`（qmed worse than OLS）— 正確 ✓
- HLN small-sample correction included (k factor lines 132-133) ✓

### QLIKE formula — CANONICAL ✅
`log(σ²_pred) + σ²_true/σ²_pred` (line 146) — Patton (2011) standard variance loss

### Kupiec UC — STANDARD ✅
χ² LR 公式 line 99-108，自由度 1，標準 unconditional coverage test

### OOS sample — CONSISTENT ✅
- All 3 assets: n_oos = 1,355, dates 2021-01-04 → 2026-05-27 (article 數字一致)
- 涵蓋 2022 全面跌、2023 AI 反彈、2024-25 高 vol — article narrative 與真實 OOS 期間相符

---

## 3. Caveats（未阻擋 publish，建議未來 K-series 改進）

### 3.1 `refit: "none (single fixed-origin fit)"`
- HAR-RV 跑 5 年 OOS 用 fixed 2007-2021 coefficients。Corsi (2009) canonical 用 rolling window。
- Internal OLS vs QR comparison 兩者用 same train sample → comparison valid，但**absolute** point-forecast 表現可能因 coefficient drift 而過度悲觀
- 不影響本文章 narrative（OLS 內部勝 QR 在 fixed-origin 下成立）。

### 3.2 「HAR-RV」naming with `|return|` proxy
- 嚴格 HAR-RV 是 5-min realized variance；本實驗用 daily `|log return|` 是 HAR-RAV / HAR-MAD 變體
- Code 內部一致（train + OOS 同 proxy）→ comparison 合法
- README 與 article 都直接稱 HAR-RV — minor terminology imprecision，不影響結論。

### 3.3 「點預測」narrative 細緻度
- Article 把 QR (τ=0.5) 描述為「猜中間值」、OLS「猜平均」— 對一般讀者 OK
- 技術上 q=0.5 是 conditional median，OLS 是 conditional mean。對右偏 vol 分佈，**兩者預測 functional 不同**（不是「同目標、不同方法」而是「不同目標」）
- 文章雖然用「打不同靶」做類比說明了這層意思，technically 仍可更精確
- 一般讀者文章可接受。

---

## 4. K1018 / DM overclaim risk audit

K1018 教訓：production article 24h 內檢查 lookahead + DM/Harvey overclaim。

- **Lookahead**: ✅ 無
- **DM overclaim**: ✅ 無 — article 用 conservative phrasing「p 值全趨近 0，不可能是巧合」對應實際 p=0.0
- **Coverage overclaim**: ✅ 無 — article 沒宣稱 strict pass，反而誠實寫出 0.31-0.93 範圍
- **"唯一/最佳" overclaim**: ✅ 無
- **資料來源**: ✅ 註明 yfinance 調整後收盤 + 訓練/OOS 期間 + n_oos
- **Aggregate verdict label**: K1403 = `TAIL_CALIB_USABLE`，article narrative「分裂成績單」忠實反映

---

## 5. Verdict & Action

**PASS** — 數字 100% 對齊、methodology sound、無 lookahead、無 overclaim。

無需 retract / 更正 / 補充更正啟事。

3.1-3.3 caveats 列入 future K-series 改進清單（後續 quantile RV experiment 可改 rolling refit + 5-min RV proxy 加強 absolute claim 力度），不影響本篇 article published 狀態。
