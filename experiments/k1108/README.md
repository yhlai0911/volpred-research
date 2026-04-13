# K1108: Foundry capex-guidance mechanism for θ₂ > 0

**提出**: 賴奕豪  **執行**: Claude  **日期**: 2026-04-13

## 動機（Problem & Hypothesis）

K1104 的橫截面回歸 (N=23 0050.TW 成分股) 顯示：

| Sector | θ₂ (A4f-EAV earnings coefficient) | Significance |
|--------|-----------------------------------|--------------|
| **Foundry** (TSMC 2330, UMC 2303) | ≥ 0 | direction only |
| **Fabless** (2454/2379/3034/3035) | < 0 | t=-2.22, p=0.039 * |

但**為什麼 foundry 公司在財報日 τ 上升，而 fabless 公司下降？**

**經濟機制假說（H1）**：Foundry 公司（TSMC/UMC）的財報會除了標準
earnings 資訊外，還會**更新年度 capex guidance**（例：「FY2025 capex
raised to $38-42 bn」）。Capex guidance 直接揭示未來 capacity expansion
rate，對 vol 有實質資訊。Fabless 公司財報聚焦 gross margin / product
cycle，不含 capex guidance。

**⇒ 若 H1 成立**：θ₂ 的 foundry positive 效果應**集中在 capex guidance
有更新的財報日**（revision days），而不是所有財報日。

## 方法（Design）

### Models

| Spec | τ_t specification |
|------|-------------------|
| **M1** GJR baseline | τ_t = θ₀ |
| **M2** A4f-EAV standard | τ_t = max(θ₀ + θ₁·VIX²_{t-1} + θ₂·EAV_{t-1}, ε) |
| **M3** A4f-EAV + capex split | τ_t = max(θ₀ + θ₁·VIX²_{t-1} + θ_change·EAV_change_{t-1} + θ_stable·EAV_stable_{t-1}, ε) |

共同 GARCH 動態：`g_t = ω + α·u²_{t-1} + γ·u²_{t-1}·I[u<0] + β·g_{t-1}`，
`σ² = τ_t · g_t`，`u = r/√τ`。

### EAV 指標定義

- **EAV_all** = 1 if day t is TSMC 財報日, else 0.
- **EAV_change** = 1 if 財報日 AND capex guidance 在該次 earnings call
  **有更新**。
- **EAV_stable** = 1 if 財報日 AND capex guidance **維持不變**。
- `EAV_change + EAV_stable = EAV_all`（disjoint partition）。

### 資料來源

| 項目 | 來源 | 期間 | 樣本 |
|------|------|------|------|
| TSMC 股價 | yfinance 2330.TW (K1104 cache) | 2014-01-03 → 2025-12-30 | 2,922 trading days |
| VIX | yfinance ^VIX (K1104 cache) | 同上，ffill | 2,922 days |
| 財報日期 | 財報公告日.txt (TWSE) | 2014-2025 | 48 earnings calls |
| Capex guidance 分類 | **TSMC IR 公開新聞稿** (手動編碼於 `k1108_fetch_capex.py`) | 2014-2025 | 48 calls → 25 revised, 23 held |

**Capex guidance 分類來源透明**：每筆 `guide_updated=1/0` 都對應到公開
press release（TSMC IR 檔案 [investor.tsmc.com](https://investor.tsmc.com/english/)）
可以追溯。沒有虛構、沒有模擬。

### 統計檢定

1. **LR test**：M3 vs M2（H0: θ_change = θ_stable，χ²(1)）
2. **Wald test**：H0: θ_change − θ_stable = 0
3. **One-sided t test**：H0: θ_change ≤ 0 vs H1: > 0
4. **Bootstrap** (seed 42, 1000 reps)：resample change/stable days
   separately with replacement，產出 θ_change − θ_stable CI 與 p 值

### Lookahead 防護

- EAV_{t-1} 指「前一交易日是否為財報日」→ 代入 τ_t 預測 σ²_t（t 日
  return）。這是 K1067 standard lag convention，無 lookahead。
- capex_flag 基於**已公告**的當日數字（earnings call 收盤前已發佈）。
- 固定 `np.random.seed(42)` + `rng = np.random.default_rng(42)`。

### 決策樹

| θ_change − θ_stable | Wald p | 一側 t_change | 判定 |
|---------------------|--------|---------------|------|
| > 2× |θ_stable| 且 > 0 | < 0.05 | > 1.96 | **MECHANISM_CONFIRMED** |
| |θ_change| > |θ_stable| | 0.05–0.10 | — | **MECHANISM_PARTIAL** |
| ≈ 0 | ≥ 0.10 | — | **MECHANISM_REJECTED** |
| 其他 | — | — | **INCONCLUSIVE** |

## 結果（填於實驗完成後）

### Pre-estimation diagnostics (TSMC log_ret, N=2922)

| 指標 | 值 |
|------|---|
| Mean | 0.00103 |
| Std  | 0.01659 |
| Skew | 0.084 |
| Kurtosis (excess) | 3.56 |
| ADF stat | -40.40 (p<0.001, stationary) |
| Ljung-Box Q(10) | 14.0 (p=0.17) |
| ARCH LM (10 lags) | 193.5 (p<1e-35, strong ARCH) |

結論：定態、微弱 autocorrelation、強 ARCH 效應 → 適合 GARCH-family。

### 樣本切分

- 48 earnings events 全數匹配到 capex guidance 表（unmatched = 0）
- **25** capex_change days
- **23** capex_stable days

### Model comparison（seed 42）

| Spec | loglik | Δ vs M1 | Δ vs M2 |
|------|--------|---------|---------|
| M1 GJR baseline | 7,973.96 | — | — |
| M2 A4f-EAV standard | 7,999.38 | +25.42 | — |
| M3 A4f-EAV + capex split | 8,001.89 | +27.93 | **+2.51** |

- **LR test (M3 vs M2)**: stat = 5.01, df = 1, **p = 0.025 \***  
  → 把 EAV 分成 capex_change / capex_stable **顯著改善** fit。

### M3 point estimates

| Parameter | Coef | SE | t-stat |
|-----------|------|------|--------|
| θ₀ (baseline τ intercept) | +1.277e-04 | 2.36e-05 | +5.41 |
| θ₁ (VIX² slope) | +3.77e-07 | (SE degenerate) | — |
| **θ_capex_change** | **+6.79e-06** | 7.46e-05 | **+0.09** |
| **θ_capex_stable** | **-7.36e-05** | 4.26e-05 | **-1.73 (marginal)** |
| ω (GARCH intercept) | +5.31e-02 | 2.05e-02 | +2.58 |
| α (ARCH) | +3.21e-02 | 9.37e-03 | +3.42 |
| γ (GJR asymmetry) | +5.90e-02 | 2.47e-02 | +2.39 |
| β (GARCH persistence) | +8.93e-01 | 2.70e-02 | +33.13 |

Persistence = α + γ/2 + β ≈ 0.955，合理 (非 boundary)。

### Statistical tests

| Test | Statistic | p-value | H0 |
|------|-----------|---------|-----|
| **Wald** (θ_change = θ_stable) | diff = +8.04e-05, t = +0.94 | **p = 0.348** | 兩者相等 |
| **One-sided** t(θ_change > 0) | t = +0.09 | **p = 0.464** | θ_change ≤ 0 |
| **Bootstrap diff** (500 reps, seed 42) | mean = +4.78e-05, 95% CI [-8.04e-05, +9.87e-05] | one-sided p = 0.226 | diff ≤ 0 |

### τ_t diagnostics (M3)

| Day type | Mean τ | Jump vs non-event |
|----------|---------|-------------------|
| Non-event | 2.67e-04 | — |
| capex_change | 2.85e-04 | **+6.79%** |
| capex_stable | 1.64e-04 | **-38.53%** |

**有趣的方向**：capex_change days 的 τ 比非事件日**略高** (+6.8%)，
capex_stable days 的 τ **顯著較低** (-38.5%)。這意味著**capex 更新日
長期波動成分 τ 確實略被推高，但 capex 穩定日 τ 被大幅下拉**。然而
差距（+8.04e-05）在 Wald/bootstrap 兩個檢定下都不顯著。

### Verdict

**MECHANISM_INCONCLUSIVE**（方向支持，但統計檢定 underpowered）

詳細決策樹對應：

| 指標 | 值 | 判定 |
|------|---|------|
| θ_change > 2× \|θ_stable\| | 否 (6.8e-6 vs 7.4e-5，θ_stable 幅度更大) | 不符合 |
| Wald p < 0.05 | 否（p=0.348） | 不符合 |
| one-sided t_change > 1.96 | 否（t=0.09） | 不符合 |
| θ_change 方向 > θ_stable | 是（+8.0e-5 差距朝 H1 方向） | 支持 H1 方向 |
| LR(M3 vs M2) p<0.05 | 是（p=0.025 *） | 支持 split 有信息 |

**敘述結論**：

1. **H1 資本支出機制方向上被支持**：θ_change − θ_stable = +8.04e-05
   > 0（符合 H1 預期，capex 更新日 τ 效果大於 capex 不變日）。
   Bootstrap 95% CI [-8.04e-05, +9.87e-05] 包含 0 但重心偏正。
2. **統計 power 不足**：Wald p=0.348 遠大於 0.05，一側 t 幾乎為 0。
   **單檔 TSMC 48 events 不足以建立顯著機制證據**——需要多檔 foundry
   彙總（UMC, GlobalFoundries ADR, SMIC 等）。
3. **LR p=0.025 支持「split 有意義」**，但主要由 θ_stable 負值貢獻
   （capex 無更新日 τ 被降低 38.5%）——這個方向跟假說相反，可能
   表示 **capex 穩定日市場會降低不確定性**（因為沒有負面 surprise），
   反而 capex 更新日（即便是 raise）也帶來了一些 τ 擾動。
4. 方向對 Paper 2 的實務啟發：**「有 capex guidance 更新的財報」
   並非顯著更劇烈**，本實驗未能為 foundry θ₂>0 提供 mechanism
   證據。Paper 2 firm-selection rule 需要考慮其他驅動 (e.g.,
   capacity utilisation announcement、manufacturer concentration)。

### 機制假說未被確認，衍生新方向

- **D1 — Capex guidance delta magnitude**：本研究只用 binary flag。
  改為 `guide_delta_pct` 連續變數（已在 CSV 中備有，-32.5% to +60.6%），
  再估 θ_capex_delta，可能 power 更足。
- **D2 — Multi-foundry pool**：合併 TSMC + UMC + 台積電 ADR (TSM)
  + GlobalFoundries (GFS) + SMIC，event days 可達 250+，power 充足。
- **D3 — Non-capex signals**：檢查 R&D guidance、wafer-price guidance、
  utilisation 等非 capex 量化訊號是否為更強的 foundry edge driver。

**D1–D3 已寫入 CLAUDE 導讀給 Paper 2 後續實驗（K1120+）。**

## 檔案清單
- `k1108.py`：主腳本（M1/M2/M3 MLE + LR + Wald + bootstrap）
- `k1108_fetch_capex.py`：建立 TSMC capex guidance CSV（hand-coded
  from IR press releases）
- `k1108_results.json`：完整結果
- `data/tsmc_capex_guidance.csv`：capex guidance 分類表
- `k1108_theta_split.png`：M2 vs M3 的 θ bar chart（含 95% CI）
- `k1108_tau_jump_timeseries.png`：TSMC τ_t 時序，標示 capex_change 和
  capex_stable 事件
- `run.log`：full-run stdout

## References
- Engle, Ghysels & Sohn (2013). GARCH-MIDAS. RES 95(3).
- Patton (2011). Volatility forecast comparison. JoE 160:246-256.
- Harvey et al. (2016). t>3.0 threshold for multiple testing.
- TSMC IR press releases 2014-2025（公開 capex guidance 歷史）
- K1067/K1067b/K1067c/K1103/K1104（系列先行實驗）

## 統計限制
- **N=25 / N=23 event days** → 遠低於 Harvey (2016) |t|>3 所需的 power
- **Single-firm test**（僅 TSMC）——未驗證 UMC、其他 foundry
- Capex guidance 分類是**二元** dummy；實際 guidance 幅度（±$2 bn vs
  ±$20 bn）未被利用（已在 `guide_delta_pct` 欄位備存，供 D1 延伸）
- MLE landscape 在 θ_change/θ_stable 維度上平坦，對 starting values
  敏感——bootstrap CI 為主要信賴工具

## Codex 審查
（實驗完成後 Codex 審查結論補入）

## Data Provenance
- 數據期間：2014-01-03 → 2025-12-30
- 交易日數：2,922
- Earnings events：48（全部匹配 capex guidance 表）
- 分類來源：手動編碼於 `k1108_fetch_capex.py:GUIDANCE_EVENTS`
  （每行附 note 說明 raise/cut/held，可對照 TSMC IR 檔案驗證）
- Random seed：42
- MLE：scipy L-BFGS-B，multi-start（M2 最佳解作為 M3 hot seed，
  確保 nested model property `loglik(M3) ≥ loglik(M2)`）
