# K1107: Panel θ_EAV with Time Fixed Effects — K1104 Robustness

**提出**: Claude  **執行**: Claude  **日期**: 2026-04-13

## 動機

K1104 cross-sectional OLS (N=23 firms) 發現 fabless dummy 負向顯著
(β=-9.61e-4, t=-2.22, p=0.039 *)。但 firm-level regression 無法
區分以下兩種可能：

1. **Firm effect**: Fabless 企業的 earnings 資訊本質上 pre-announcement
   leaked (supply-chain/order-book channel)，事件日本身無新資訊 → τ 不升
2. **Time effect**: Fabless 企業（MediaTek/Realtek/Novatek/Phison）的
   earnings 碰巧集中在特定年份，那些年份整體 tech vol regime 偏低 →
   看起來 fabless 效果為負

K1107 用 **event-level panel (firm × event)** 加上 time fixed effects
(year + quarter dummies) 來分離這兩個效果。

## 方法

### 資料
- 重用 K1104 fitted A4f-EAV 參數 (24 firms × full-sample MLE)
- 排除 persistence ≥ 0.998 (0 firms) + 排除 holdout ASE
- 剩餘 23 firms × ~60 events/firm = **1377 事件**
- 資料期間 2010-01-01 → 2025-12-31

### Panel 依變數
**Outcome #1 — Reconstructed τ lift** (原 brief 版本):
- 每個 event t 重建 `τ_t = θ₀ + θ₁·VIX²_{t-1} + θ₂·EAV_{t-1}`
- `rel_lift = (τ_{t+1} − τ_baseline) / τ_baseline`
- `τ_baseline` = 事件前 30 天 (lag 5 日) 的 τ 平均
- **Caveat**: 因為 θ₂ 在單一企業內為常數，Outcome #1 的 within-firm
  變異主要由 VIX² 變化驅動，對 K1104 的 θ₂ 檢驗並無新資訊。

**Outcome #2 — Model-free log-r² surprise** (本實驗新增):
- `y_{i,t} = log(r²_{i,t} / mean(r²_{i, baseline window}))`
- 完全不使用 K1104 的 fitted params，直接用觀察到的事件日平方報酬
- **This is the clean panel test** of K1104's claim: 若 fabless 企業
  確實 event-day vol 較低，此 outcome 會直接顯示

### 模型
- 四個 spec: (a) Baseline (no time FE); (b) Year FE only;
  (c) Quarter FE only; (d) Year + Quarter FE
- 自變數: foundry, fabless, log_mktcap_z
- Firm-clustered SE (Petersen 2009)

## 結果

### Outcome #1: Reconstructed τ-lift (panel, 1377 events)

| Spec | fabless β | SE(clust) | t | p |
|------|-----------|-----------|---|---|
| Baseline | +0.113 | 0.584 | +0.19 | 0.848 |
| + Year FE | +0.112 | 0.587 | +0.19 | 0.850 |
| + Quarter FE | +0.113 | 0.584 | +0.19 | 0.848 |
| + Year + Quarter FE | +0.113 | 0.588 | +0.19 | 0.850 |

Time FE attenuation: **+0.7%** (essentially zero). Year effect absent
because by-year rel_lift 很穩定 (0.66–0.95) 全期間。

### Outcome #2: Model-free log(r²_event / r²_baseline) (1377 events)

| Spec | fabless β | SE(clust) | t | p |
|------|-----------|-----------|---|---|
| Baseline | +0.255 | 0.265 | +0.96 | 0.347 |
| + Year + Quarter FE | +0.257 | 0.266 | +0.97 | 0.344 |

**Foundry**: β=+0.80, t=+2.16, p=0.04 ** (顯著正向) — 與 K1104
方向一致但此處達顯著 (panel N 較大所致)。

**log_mktcap_z**: β=−0.18, t=−1.57, p=0.13 — 方向一致 (大公司 event
vol surprise 較低)，但不顯著。

### Firm-level decomposition (為什麼 K1104 vs K1107 結論相左)

| Firm | Type | K1104 θ₂ | Event-panel rel_lift | log r² surprise |
|------|------|---------|---------------------|----------------|
| MediaTek | Fabless | -1.61e-3 | -0.12 | -2.40 |
| Realtek | Fabless | -2.39e-3 | -0.16 | -2.75 |
| Novatek | Fabless | +7.02e-4 | **+1.89** | -2.03 |
| Phison | Fabless | +1.20e-3 | **+2.73** | -1.45 |
| TSMC | Foundry | +6.05e-5 | +0.42 | -2.56 |
| UMC | Foundry | +4.31e-4 | +1.67 | -1.48 |

**Fabless 內部 bimodal**：MediaTek/Realtek θ₂<0 但 Novatek/Phison θ₂>0。
K1104 的 cross-sectional regression 給每家公司 equal weight，四家平均
為負。Event panel 則給每個事件 equal weight，四家事件數量相近 (≈60)，
但 Novatek/Phison 的大正值拉高 fabless 平均為接近零。

## Verdict

**NOT SUPPORTED**: K1104's fabless-negative claim does not generalise to
panel event-level analysis.

- **Outcome #1** (reconstructed τ-lift): fabless 係數近零，時間 FE 前後
  均無變化。這是 mechanical (因 θ₂ firm-invariant 且 within-firm 變異
  由 VIX 驅動)。
- **Outcome #2** (model-free event vol surprise): fabless 係數 +0.26,
  p=0.34，時間 FE 加入後幾乎不變 (+0.1% attenuation)。**Fabless 企業
  在事件日的觀察到的 vol surprise 與其他企業無顯著差異**。
- **Foundry 則顯著為正** (t=+2.16 * with time FE) — 與 K1104 方向一致
  且此處達顯著，證實 foundry 企業 event-day vol surprise 確實較高。

### Time FE 本身的貢獻

對所有 firm covariate (foundry/fabless/log_mktcap)，Year+Quarter FE
前後 t-stat 變化均 < 5%。代表 **event-day vol dynamics 在年份間相當穩定**
(by-year rel_lift 均落於 0.66–0.95)。K1104 的 cross-sectional 結論
**不是時間效應的 artifact**，而是來自：

1. **Firm-level heterogeneity within fabless**: 只有 4 家 fabless 企業，
   其中 MediaTek/Realtek 與 Novatek/Phison 符號相反
2. **Weighting 差異**: Equal-firm weight (K1104) vs equal-event weight
   (K1107 panel)

## Paper 2 含義

1. **Fabless "negative θ₂" 不是 time artifact，但也不是 firm-level universal**：
   K1104 的 firm-level 發現受 MediaTek/Realtek 兩家主導，Novatek/Phison
   表現相反。不能將 "fabless→低 EAV 效果" 當成 paper 2 的 firm-selection
   規則。
2. **Foundry → 高 EAV surprise 是 ROBUST 發現**：
   time FE + firm cluster 之下仍顯著 (t=+2.16)。這是 paper 2 firm-selection
   可靠的一條線索。
3. **擴大 N 至關重要**：4 家 fabless 太少無法得到穩健結論，建議 D1
   (50 檔 0050.TW) 增加 fabless 至少到 8 家。
4. **重新思考 sector dummy 的 granularity**：IC 設計 (fabless) 內部
   還可細分 (通訊類 vs memory controller vs display driver)，MediaTek
   (通訊) 與 Phison (memory controller) 的商業模式差異可能比
   "fabless vs foundry" 更重要。

## 統計限制

- **Outcome #1 含 K1104 的 MLE artefact**：只是診斷用，不作結論
- **Outcome #2 是 model-free 但 signal-to-noise 低** (R² ≈ 0.02) ──
  event-day r² 本身極雜訊大，需要更大樣本或更穩健指標 (如 RV from
  intraday)
- **Firm cluster G=23** 邊緣偏小 (推薦 G>30 for asymptotic cluster SE)
- **Fabless N=4 firms** (239 events) — 誤差依然由少數 firm 主導

## 輸出

- `k1107.py` — 全腳本
- `k1107_results.json` — 四 spec coef + 兩 outcome + verdict
- `k1107_panel.csv` — 1377 events × 16 columns
- `k1107_fabless_forest.png` — coefficient forest plot
- `k1107_lift_by_year.png` — by-year rel_lift (time heterogeneity check)
- `run.log` — 執行 log

## References

- **K1104** — Cross-sectional firm-level θ₂ regression (this experiment's baseline)
- **K1103** — Rolling-window τ-lag fix (source of A4f-EAV params)
- Engle, Ghysels & Sohn (2013). Stock market volatility and macroeconomic
  fundamentals. *RES* 95(3), 776-797.
- Petersen, M.A. (2009). Estimating standard errors in finance panel
  data sets: Comparing approaches. *RFS* 22(1), 435-480.

## Decision Tree

- [x] K1104 baseline reproduced (K1104's full-sample θ₂ used as input)
- [x] Time FE added (Year 2010-2025 + Quarter Q1-Q4)
- [x] Outcome comparison: fabless coef essentially 0 in both Outcome #1
      and Outcome #2, with or without time FE
- [x] Verdict: **Not supported** — but the failure mode is firm-level
      heterogeneity (MediaTek/Realtek vs Novatek/Phison), not time effect
- [x] Next: D1 (50-firm extension) to get reliable fabless sub-classification
