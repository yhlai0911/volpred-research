# K1100f: Copula + Periodic GARCH (PRG) on REAL Spot-Futures Pair (SPY-ES=F)

- **提出者 (Proposer)**: Claude 自主研究（K1100b Paper 3 重構提議的驗證）
- **設計者/執行者**: Claude (autonomous-research, worktree agent)
- **日期**: 2026-04-13
- **狀態**: 完成
- **父實驗 (Parents)**: K1100 (SPY-GLD null), K1100b (5 equity pairs null), K868/K874c/d/e/K880 (PRG session structure)
- **關聯 (Related)**: K1041 (DCC-A4f), K1092 (A4f-ASYM best), Lai 2024 APFM PRS copula hedging

---

## 問題 (Research Question)

K1100 + K1100b 已證明 copula-GARCH 在 general equity pairs 上**全部 NULL**（即使是 tail-dependent equity pair 也打不過 DCC-A4f-ASYM）。但 Lai 2024 APFM 31(2) PRS 在 TAIFEX TX spot-futures 上成功。三個可能的關鍵因素：

1. **spot-futures 幾近完美相關** (~0.99)
2. **periodic return 結構**（day-of-week、結算日、session 效應）
3. **temporal lead-lag**（futures price discovery）

**K1100f 核心問題**：在真正的美國 spot-futures pair（SPY vs ES=F CME E-mini S&P 500 期貨）上，**copula + periodic GARCH (PRG) 是否能一起取得 Harvey-significant 優勢**？

這是 Paper 3 真正應該聚焦的 scope，不是 K1100b 的 general equity expansion。若這個實驗也 NULL，Paper 3 可能整個需要從「發展新方法」重構為「台灣市場特殊性紀錄」。

## 動機 (Motivation)

1. **K1100b 結論給出明確方向**：Copula 在 general equity 無效，但 Lai 2024 在 TAIFEX 成功 → 關鍵在 spot-futures + periodic 結構。K1100f 是這個假設的**直接實證檢驗**。
2. **若 SPY-ES=F 這種近乎完美 spot-futures pair 也失敗** → Lai 2024 的成功來自台灣市場特殊性（交易機制、夜盤開閉、tick 精細度），不是 copula+periodic 的普適優勢。Paper 3 需要重新定位。
3. **若成功** → Paper 3 正路確認，可擴大到 cross-market validation（TW/JP/HK futures）。

## 方法 (Method)

### 資料

| Asset | Source | Role | 說明 |
|-------|--------|------|------|
| SPY | yfinance (auto_adjust) | spot | S&P 500 ETF，日頻 close |
| **ES=F** | yfinance | **futures** | **CME E-mini S&P 500 continuous futures** |
| GLD | yfinance | spot (robustness) | 黃金 ETF |
| GC=F | yfinance | futures (robustness) | COMEX Gold continuous futures |
| ^VIX | yfinance | regressor | 兩個 marginal 的共同外生變數 |

- **期間**: 2013-01-02 ~ 2026-04-10（ES=F 與 SPY 同期可用）
- **Full-sample corr**: SPY-ES=F = **+0.9719**（非常接近 spot-futures 完美相關）
- **GLD-GC=F = +0.9065**（ETF tracking + physical gold arbitrage）

### 4 個模型

| Model | Marginal | Correlation | 設計意義 |
|-------|----------|-------------|---------|
| **M1: DCC-A4f-ASYM** | A4f (K1041/K1092) | Gaussian DCC | K1100b baseline |
| **M2: Copula-t-A4f-ASYM** | A4f | Student-t copula | K1100b 標準 copula |
| **M3: DCC-PRG-ASYM** | PRG (A4f + 4 DOW dummies) | Gaussian DCC | **periodic marginal only** |
| **M4: Copula-t-PRG-ASYM** | PRG | Student-t copula | **FULL combo (Paper 3 spec)** |

### PRG (Periodic GARCH) 規格

A4f-ASYM 結構加上 day-of-week dummies（Monday = baseline）：

```
τ_t  = θ₀ + θ₁·x²_{t-1} + δ_Tue·I(DOW=Tue) + δ_Wed·I(DOW=Wed)
                        + δ_Thu·I(DOW=Thu) + δ_Fri·I(DOW=Fri)
g_t  = ω + α·u²_{t-1} + γ·u²_{t-1}·I(r<0) + β·g_{t-1}   (unchanged)
h_t  = τ_t · g_t
```

10 參數 per asset（A4f 有 6 個，PRG 多 4 個 DOW dummies）。

Dummy bounds: ±1e-4（Codex review 後收緊，原為 ±5e-4 太寬鬆可能主導 τ）。

### 估計 + OOS

- Training window: 1250 days
- OOS start: **2018-02-01**（2013 起算，保留 5 年 training）
- OOS days: **2058 天 per pair**
- Refit frequency: 63 日
- Monte Carlo paths: 3000（copula VaR/ES 用）
- Seed: 42（全部可重現）

### 評估

- **Primary**: DM QLIKE (Harvey 2016 |t|>3.0 門檻)
- **VaR/ES**: Trinity test (Kupiec + CC + Basel) at α=1%, 2.5%
- **FZ score**: Fissler-Ziegel joint VaR-ES scoring
- **Periodic diagnostic**: 各模型在不同 day-of-week 的 conditional variance 均值
- **Decomposition**: Δ_PRG = QLIKE(M1) − QLIKE(M3), Δ_Copula = QLIKE(M1) − QLIKE(M2), Δ_Full = QLIKE(M1) − QLIKE(M4), Interaction = Δ_Full − Δ_PRG − Δ_Copula

### Codex 審查

實驗代碼執行前先經 Codex 審查，發現並修正 2 處 CONCERN：

1. **PRG dummy bounds 過寬** (±5e-4 → ±1e-4)：原本相對於 θ₀~1e-5 可能主導 τ
2. **DCC eps_prev timing bug**：原本用 `r_{t-1}/√h_t`，修正為 `r_{t-1}/√h_{t-1}` 的正確時序（K1100b 繼承的 bug；i>0 時修正，i=0 保留原式作為 one-step approximation）

其他 5 項 PRG kernel logic、onestep forecast、portfolio variance、state carry-over、lookahead check 全數 PASS。

## 假設與預期 (Hypotheses)

| 假設 | 說明 | 門檻 |
|------|------|------|
| **H1** | M4 (full combo) > M1 (baseline) | DM QLIKE Harvey \|t\| > 3.0 |
| **H2** | M3 (PRG only) > M1 | Harvey 顯著 |
| **H3** | M2 (copula only) > M1 | Harvey 顯著 |
| **H4** | (M4−M3) > (M2−M1) i.e. 交互效應 > 0 | interaction 顯著為正 |
| **Fallback** | 若 H1-H4 全 FAIL，Paper 3 走 Taiwan-specific route | — |

---

## 結論 (Findings)

### 核心發現：**所有假設 (H1-H4) 全部 FAIL**

**即使在 corr=0.9719 的真正 spot-futures pair (SPY vs ES=F)，加上 PRG periodic marginal，再加上 Student-t copula，模型組合仍然無法在 Harvey |t|>3 門檻下擊敗基本的 DCC-A4f-ASYM。K1100 + K1100b 結論強化：copula + periodic 不是 general-purpose 的波動率預測改善方法。**

### 主表：DM QLIKE t-stat（兩 pair × 6 組比較）

| Pair | corr | H3 Cop-vs-M1 | H2 PRG-vs-M1 | H1 Full-vs-M1 | Harvey Sig? |
|------|------|--------------|--------------|---------------|-------------|
| **SPY-ES** (spot-futures) | +0.972 | −0.033 | −1.111 | **−1.125** | ❌ 全 NULL |
| **GLD-GC** (robustness) | +0.907 | −0.718 | +0.768 | **+0.697** | ❌ 全 NULL |

（正 DM t = 右側模型較好；負 DM t = 左側 baseline 較好）

### 方差分解（QLIKE 差距：正 = 加新成分有改善）

| Pair | Δ_PRG (M1→M3) | Δ_Copula (M1→M2) | Δ_Full (M1→M4) | Interaction |
|------|---------------|------------------|----------------|-------------|
| SPY-ES | **−0.00513** | −0.00001 | −0.00516 | −0.00001 |
| GLD-GC | +0.00622 | −0.00058 | +0.00580 | +0.00016 |

- **SPY-ES 上 PRG 造成 QLIKE 退化**（符號為負意即 M3 比 M1 還差）
- **GLD-GC 上 PRG 微幅改善但未達顯著**（+0.006 但 DM t=+0.77）
- **Interaction 項幾乎為零**：無論如何都沒有「PRG+copula 協同效應」

### Mean QLIKE（每 pair 4 個模型，lower = better）

| Pair | M1 DCC-A4f | M2 Copula-A4f | M3 DCC-PRG | M4 Copula-PRG |
|------|-----------|---------------|-----------|---------------|
| **SPY-ES** | **−8.3522** (best) | −8.3522 | −8.3471 | −8.3471 |
| **GLD-GC** | −8.3285 | −8.3279 | **−8.3347** (best) | −8.3343 |

### Trinity VaR (α=1%) 通過情況

| Pair | DCC-A4f | Copula-A4f | DCC-PRG | Copula-PRG |
|------|---------|------------|---------|------------|
| SPY-ES | ✅ | ✅ | ✅ | ❌ Kupiec+Basel FAIL |
| GLD-GC | ✅ | ✅ | ✅ | ✅ |

**SPY-ES 上 Copula-PRG (M4) 反而在 1% VaR 失敗** — periodic 與 copula 結合在 spot-futures 扭曲了尾部。

### Copula 結構觀察（FYI）

| Pair | ρ_mean (A4f) | ρ_range (A4f) | ν | λ_L (A4f) |
|------|--------------|---------------|---|-----------|
| SPY-ES | +0.985 | [0.978, 0.990] | 2.4 | **0.9217** |
| GLD-GC | +0.899 | [0.877, 0.928] | 2.5 | 0.6959 |

- **SPY-ES λ_L = 0.92**：Copula 正確偵測到極度 tail dependence（spot-futures 本質如此）
- **但 tail dependence 偵測到 ≠ 預測改善**。K1100b 也觀察到同樣現象。

### Regime correlation（VIX < 20 vs VIX > 30）

| Pair | Calm corr | Stress corr |
|------|-----------|-------------|
| SPY-ES | +0.9720 | +0.9584 |
| GLD-GC | +0.9017 | +0.9220 |

SPY-ES 在壓力時期 corr 略降（0.972→0.958），但仍高。**沒有顯著 regime-switching**，所以 DCC 的動態 ρ 已足以捕捉。

### 關鍵觀察

**1. "近乎完美相關" 本身造成 copula 無用**
- SPY-ES corr=0.97、copula ρ=0.985 → 組合報酬變異幾乎就是兩資產變異的算術平均 ± tiny cross-term
- Portfolio variance formula `w₁²h₁ + w₂²h₂ + 2w₁w₂ρs₁s₂` 在 ρ→1 時退化為 `(w₁s₁ + w₂s₂)²`
- 尾部結構差異（Gaussian vs Student-t）在幾乎相同的 portfolio return 下變得邊際微小
- **Paradox**: copula 最擅長抓 tail dep，但在 tail dep 極強時 QLIKE 反而最不敏感

**2. PRG DOW dummies 量級極小 (~1e-6 to 1e-5)**
- Fit 出來的 dummies 大多在 `~1e-5` 量級，θ₀~1e-5、θ₁·VIX² ~1e-4
- DOW 效應相對於 VIX 驅動的時變 τ **小 10 倍以上**
- 換句話說：**VIX 已經把 periodic structure 吸收乾淨了**
- 如果要 PRG 顯著，需要 x² 吸收能力有限的場景（如無 IV 市場、tick-level periodic effects）

**3. 這對 Paper 3 的意義**

| 可能路徑 | 現狀 | 結論 |
|---------|------|------|
| "Copula + PRG on US spot-futures" | ❌ K1100f 否定 | **放棄** |
| "Lai 2024 PRS 是台灣市場特殊性" | ✅ 符合證據 | **採用（核心重構）** |
| "Tick-level periodic 仍可能有效" | 未測試 | 保留（但要 TAIFEX tick，只到 2021） |
| "其他 cross-market futures" | 未測試 | 低優先（除非有強理論動機） |

### 假設檢驗結果

| 假設 | 結果 | 證據 |
|------|------|------|
| **H1**: Copula-PRG > DCC-A4f Harvey | **❌ FAIL** | SPY-ES t=-1.13, GLD-GC t=+0.70 |
| **H2**: PRG > A4f Harvey | **❌ FAIL** | t=-1.11 (SPY-ES), t=+0.77 (GLD-GC) |
| **H3**: Copula > DCC Harvey | **❌ FAIL** | t=-0.03 (SPY-ES), t=-0.72 (GLD-GC) |
| **H4**: Interaction > 0 significant | **❌ FAIL** | Interaction ≈ 0 (−1e-5 to +1.6e-4) |

**Verdict: `PRG+COPULA NULL on US spot-futures — Paper 3 needs reframing as Taiwan market finding`**

### 研究誠實原則標註

- **實證分析（真實數據）**：yfinance daily data, 2013-01 ~ 2026-04, 3338 days per asset
- **Null result 如實報告**：H1-H4 全部拒絕
- **固定 seed (42)**：所有 MC paths 可重現
- **Codex 事前審查**：發現並修正 2 處 concern (dummy bounds, DCC timing) 後才執行
- **局限性**：
  - 僅 2 pairs（N=2 無法做 cross-pair Spearman 檢定）
  - ES=F 是 continuous futures（yfinance roll 機制可能平滑了結算日效應，這是 Paper 3 可能需要回到 TAIFEX TX 自行 roll 的原因）
  - OOS 2018-02 起，沒涵蓋 2008 GFC（ES=F 從 2013 才有）
  - PRG 只用 DOW dummies，沒測試 month-end, FOMC-week, options expiration 等其他 periodic effects
  - 日頻（daily）頻率 — Lai 2024 PRS 用 tick-level (15-min session splits)

### Mechanical vs Empirical 區分

- **Mechanical**: ρ → 1 時 copula 尾部結構差異對 portfolio variance 影響變小（公式使然）
- **Empirical**: PRG 在 SPY-ES 上退化 QLIKE 而在 GLD-GC 上小幅改善 ← 實證發現（可能反映黃金的 Monday/Friday 交易 pattern 與股票不同）
- **Empirical**: Copula-PRG 在 SPY-ES 1% VaR 失敗 ← 實證發現（periodic 扭曲尾部）

### 下一步方向（衍生 K 編號建議）

1. **K1100g: 重新定位 Paper 3 為 "Taiwan market copula hedging" 論文** — 核心貢獻從「方法論」改為「台灣市場實證紀錄」，比較 TAIFEX TX 與 SPY-ES 的 copula performance 差異，解釋為何同方法在兩個市場結果不同（tick 結構、夜盤、外匯 arbitrage、結算日效應）

2. **K1100h: Tick-level PRG on TAIFEX TX spot-futures (2017-2021)** — 只在 tick-level 才能看到真正的 periodic structure（夜盤邊界、結算日）。用 Dropbox 本地 TAIFEX data，不是 yfinance daily

3. **K1100i: 探究 GLD-GC 上 PRG 微幅有效的原因** — 是否與「黃金的 NYSE 交易時段 vs. COMEX 交易時段」的錯位有關？若是，可擴到 other commodity-ETF pairs (USO vs CL=F 原油, SLV vs SI=F 白銀)

## 檔案 (Files)

- `k1100f.py`：完整實驗腳本（~1300 行，包含 PRG numba kernels + fit + OOS forecast + backtesting + plotting）
- `k1100f_results.json`：完整結果（37KB）
- `k1100f_4model_dm.png`：兩 pair 的 4 模型 DM vs baseline 條形圖（H3/H2/H1 並列）
- `k1100f_periodic_seasonality.png`：各模型 portfolio conditional variance 按 day-of-week 分佈
- `k1100f_basis_SPY-ES.png`：SPY-ES 的 basis 時序 + copula λ_L (OOS)
- `k1100f_basis_GLD-GC.png`：GLD-GC 同上
- `k1100f_copula_gain_decomposition.png`：Δ_PRG / Δ_Copula / Δ_Full / Interaction decomposition

## 參考文獻 (References)

- **K1100** (SPY-GLD copula null, tail-independent pair)
- **K1100b** (5 equity pairs copula null)
- **K868, K874c/d/e, K880** (PRG on TAIFEX session structure)
- **K1041, K1092** (DCC-A4f-ASYM baseline, best-in-class)
- Bollerslev & Ghysels (1996). Periodic autoregressive conditional heteroscedasticity. *JBES* 14(2), 139-151.
- Patton (2006). Modelling asymmetric exchange rate dependence. *IER* 47(2), 527-556.
- Jondeau & Rockinger (2006). The Copula-GARCH model of conditional dependencies. *JIMF* 25(5), 827-853.
- Christoffersen, Errunza, Langlois & Huang (2012). Is the potential for international diversification disappearing? A dynamic copula approach. *RFS* 25(12), 3711-3751.
- **Lai (2024)**. PRS-based copula hedging. *APFM* 31(2). (用戶論文；**本實驗的主要 inspiration**)
- Harvey, Leybourne & Newbold (2016). Tests of equal forecast accuracy. *JBES* 15(2).
- Fissler & Ziegel (2016). Higher order elicitability and Osband's principle. *Ann Stat* 44(4).
- Kupiec (1995). Techniques for verifying the accuracy of risk measurement models. *J Derivatives* 3(2).
- Christoffersen (1998). Evaluating interval forecasts. *Int Econ Rev* 39(4).
- Acerbi & Szekely (2014). Backtesting expected shortfall. *Risk*.

---

**執行時間**：約 130 秒（2 pairs × 4 models × 2058 OOS days × MC=3000 paths，包含 numba JIT 編譯）

**主要限制**：continuous futures (ES=F) 的 roll 機制可能平滑了結算日效應；若要嚴格複製 Lai 2024，應用 TAIFEX TX 自行 roll（見 K1100h 建議）。

**對 Paper 3 的直接建議**：將論文定位從「發展新方法 for US markets」**改為「Taiwan market copula hedging 實證研究」**，對比 US 與 TW 結果解釋差異。K1100f 的 SPY-ES NULL 是支撐這個重新定位的關鍵證據。
