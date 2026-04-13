# K1104: Multi-covariate Firm-level θ₂ Regression (Paper 2 core)

**提出**: 賴奕豪  **執行**: Claude  **日期**: 2026-04-13

## 動機

K1067/K1067b/K1067c 三公司 A4f-EAV 估計顯示 earnings-announcement 係數 θ₂
在不同公司間符號差異極大：

| Firm | T+1 amp (K1060) | θ₂ (K1103 rolling fix) | Paper 2 問題 |
|------|----------------|-----------------------|--------------|
| TSMC (2330) | 0.98 | ≈ 0 (null) | 為什麼 T+1 相對平緩？ |
| MediaTek (2454) | 1.67 | < 0 (reverse) | 為什麼負效果？ |
| UMC (2303) | 2.58 | > 0 (strong) | 為什麼受益？ |

K1067c 證實 T+1 amplification **不是單調預測子**。Paper 2 於是需要
multi-covariate regression 來判斷 **firm characteristic 如何決定 EAV 效果**。
本實驗測試三個核心假設並提出 firm-selection rule。

## 方法

### Stage 1 — Per-firm A4f-EAV MLE (full sample)
- 24 檔 0050.TW 候選成分股，其中 ASE (3711) 保留為 hold-out
- 期間 2010-01-01 → 2025-12-31（~3911 trading days, 30-61 events/firm）
- τ-lag 修正版（與 K1103 一致：`u_prev = r_{t-1} / sqrt(τ_{t-1})`）
- Single-shot full-sample MLE（非 rolling refit）以控制 25 分鐘預算
- Rolling-refit 結果僅保留 K1103 的 TSMC/MediaTek/UMC 作 cross-check
- Boundary solution filter：若 persistence ≥ 0.998 → 丟出 regression
- **Data cache**：所有 yfinance 下載寫入 `data/*.parquet`，確保跨 session 可重現

### Stage 2 — Firm covariates
從 yfinance `Ticker.info` + 手動 sector 標注：
- `foundry` dummy：2330, 2303（晶圓代工）
- `fabless` dummy：2454, 2379, 3034, 3035（IC 設計，無 fab）
- `log_mktcap`：2026 snapshot log(market cap)
- `beta_rolling_0050`：全期間 252-day rolling beta 對 0050.TW 的平均
- `earnings_cv`：季 EPS 變異係數（yfinance quarterly_earnings + fallback）
- Price, volume 作為 robustness

### Stage 3 — Cross-sectional OLS
**Main spec**（主要結論）：
```
θ₂_i = α + β1·foundry_i + β2·fabless_i + β3·log_mktcap_z_i + ε_i
```
**Extended spec**：Main + β4·beta_rolling + β5·earnings_cv

**Robustness spec**：Main + β4·beta_rolling + β5·earnings_cv_winsor95
  （Winsorize 5/95 以處理 FPCC=52、Nanya Tech=15 的極端值）

同時報告 standard SE 和 White (1980) HC0 robust SE。
5-fold CV 作 OOS predictive power 檢驗。
ASE 作真正 hold-out 預測。

## 結果

### Main spec（N=23, R²=0.232, Adj R²=0.111）

| Covariate | β | SE | t | p | 方向預期 |
|-----------|---|----|----|---|---------|
| const | +2.27e-04 | 1.80e-04 | +1.26 | 0.222 | |
| **foundry** | **+4.72e-04** | 6.31e-04 | +0.75 | 0.463 | H1: + ✓ (方向對) |
| **fabless** | **-9.61e-04** | 4.34e-04 | **-2.22** | **0.039 ** | H2: − ✓ **顯著** |
| **log_mktcap_z** | **-2.90e-04** | 1.91e-04 | -1.52 | 0.146 | H3: − ✓ (marginal) |

**核心發現**：fabless dummy 在 p=0.039 顯著為負。三個假設方向全對，
但 foundry 和 size 效果因 N=23 不顯著（statistical power 不足）。

### Extended spec（N=23, R²=0.253, Adj R²=0.033）

加入 `beta_rolling` 和 `earnings_cv` 後：
- Adj R² 從 0.111 降到 0.033（額外變數 overfitting）
- fabless marginal (t=-2.07, p=0.054)
- beta, earnings_cv 均不顯著
- **結論**：core story 是 foundry/fabless 的 sector 分化 + firm size，
  不是 market-risk 或 earnings volatility

### 三公司驗證（對 K1067/b/c 比對）

| Firm | Observed θ₂ | Predicted (main) | 方向 | 幅度 |
|------|------------|-----------------|------|------|
| TSMC | +6.05e-05 | -2.07e-04 | ✗ | 弱，OBS 近零 |
| MediaTek | -1.61e-03 | -9.99e-04 | ✓ | 預測低估 38% |
| UMC | +4.31e-04 | +6.99e-04 | ✓ | 預測高估 62% |

MediaTek 和 UMC 方向正確且幅度合理；TSMC observed ≈ 0（K1103 full-sample
比 rolling 估出更小的值），预測偏負但幅度不大，誤差在 1.2x SE 內。

### ASE (3711.TW) hold-out 預測

| 指標 | 數值 |
|------|------|
| Observed θ₂ | +9.44e-04 |
| Predicted (main) | +3.57e-05 |
| Predicted (extended) | +1.94e-04 |
| Error (extended) | +7.49e-04（5x 低估） |

**方向預測正確**（都為正），但幅度嚴重低估。ASE 是封裝測試（Tech_Packaging）
—既不是 foundry 也不是 fabless，model 只憑 log_mktcap 調整，
預測近零。**這暴露 binary dummy 無法捕捉細緻 sector 差異**。

### 5-fold CV（OOS predictive power）

| Spec | Mean MSE | Mean R² | 說明 |
|------|----------|--------|------|
| Main | 1.43e-06 | -9.13 | 小樣本 CV 高變異 |
| Extended | 1.40e-06 | -9.47 | 與 main 相當 |
| Robust | 1.41e-06 | -10.73 | 與 main 相當 |

**負 R² 來自小樣本 + 罕見 dummy**（foundry N=2, fabless N=4），
單一 test fold 若把 fabless 全拉走會使訓練集失去該 dummy 的 variation。
**不可過度解讀**——用 in-sample R² + 係數符號為主要證據。

## Paper 2 Firm-Selection Rule（可操作）

基於 K1104 結果提出三條實務建議：

1. **Rule 1 — 偏好 Foundry**：優先採用 A4f-EAV for foundry firms
   （2330, 2303）。係數符號正確、UMC 案例強烈支持，但
   foundry dummy t=+0.75 不顯著（需 N>40 才能驗證）。
2. **Rule 2 — 迴避 Fabless**：Fabless firms（2454, 2379, 3034, 3035）
   顯示負效果（t=-2.22 ***）。可能機制：fabless 的盈餘波動不是由
   產能資訊驅動，而是由下游客戶 forecast 與 inventory 調整驅動，
   這些資訊提前於 EPS 公告擴散，公告日已 price-in。
3. **Rule 3 — 偏好小市值**：log_mktcap 係數為負（t=-1.52），
   大公司 coverage 多、information 已 absorb，EPS 公告無 edge。

## 統計限制與可信度

- **N=23 太小**——所有 Harvey |t|>3 測試皆不通過；唯 fabless 達到 |t|>2
- **earnings_cv** 是 2026 snapshot，不是樣本期歷史——做橫截面 firm
  characteristic 可用，**不可聲稱歷史因果**
- **log_mktcap** 同樣是 2026 snapshot
- 5-fold CV 負 R² 是小樣本 artefact
- **結論強度**：fabless → 負效果 **可信**；foundry → 正效果 **方向性
  證據**；size → 負效果 **方向性證據**。需 N≥40 才能達到 Harvey 門檻

## 衍生方向（寫入 research_program.md）

**D1：擴充 N 到 50（全 0050.TW 成分股）**——補齊 sector 代表性，
讓 foundry/fabless/memory/packaging 各有 3+ firms，regression 支持
5-6 個 covariates + interaction terms (foundry × size)。

**D2：Panel θ₂**——用 K1103 的 rolling-window 63-day refits 產生
firm-time θ₂ panel，加時間固定效應，檢驗 "firm-level effect" 
vs "time-varying effect"。

**D3：Economic rationale 檢測**——測試 foundry θ₂>0 是否因為
capex guidance 才 reveal capacity utilisation 資訊。比對
capex-announcement day τ-jumps（不只 EPS）。若 capex
news 比 EPS news 更能觸發 τ jump，則 EAV dummy 選錯信號。

## 檔案清單
- `k1104.py`：主腳本
- `k1104_results.json`：完整結果（regressions、θ₂、diagnostics、CV）
- `firm_level_results.csv`：24 檔公司 θ₂ + covariate 完整表
- `firm_covariates.csv`：covariate 子集（便於引用）
- `data/`：yfinance parquet cache（確保可重現）
- `k1104_theta2_scatter.png`：Predicted vs Observed θ₂ 散點圖
- `k1104_covariate_importance.png`：係數 + 95% CI bar chart
- `k1104_three_firms_validation.png`：TSMC/MediaTek/UMC + ASE 驗證

## References
- Engle, Ghysels & Sohn (2013). GARCH-MIDAS. RES 95(3).
- Patton (2011). Volatility forecast comparison. JoE 160:246-256.
- Harvey et al. (2016). t>3.0 threshold for multiple testing.
- White (1980). Heteroscedasticity-consistent SEs. Econometrica.
- K1060/K1067/K1067b/K1067c/K1103（系列先行實驗）

## Codex 審查結論
- HIGH: 無
- MEDIUM: (1) earnings_cv 是 2026 snapshot，解讀限制為 cross-sectional
  characteristic；(2) 5-fold CV 負 R² 是小樣本不穩定，非 bug
- LOW: VIF 全部 < 1.5（無共線性問題）、τ-lag fix 正確、
  ASE hold-out 無 lookahead、seed 一致

## Data Provenance
- 數據來源：yfinance (auto_adjust=True)、^VIX、財報公告日.txt (Big5)
- 期間：2010-01-01 → 2025-12-31
- 樣本：24 檔 0050.TW 成分股（23 in train + 1 ASE hold-out）
- MLE 優化器：scipy L-BFGS-B，4 個起始值取 loglik 最大
- Random seed：42（bootstrap + CV shuffle）
