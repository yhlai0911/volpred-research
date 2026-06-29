# K1571 — Deep Quantile VaR 的公平 Baseline 審計（Stage 1）

## 動機

研究 backlog open question：DNN quantile VaR 在文獻常聲稱「打敗 baseline」，但 baseline 多半是 historical simulation (HS) 或 GARCH-normal。**真正的問題是**：DNN 是真的學到非線性 / 高維交互，還是只是吃到高維 covariate 的 information advantage？

**Stage 1（本實驗）= 建立一個誠實 baseline plateau**：用同一組 covariate，跑 4 個古典 quantile / VaR 模型，看 covariate 本身能擠出多少 value。Stage 2（後續 compute_queue task）才把 DNN 接上來、用同一 covariate set 比較。

若 DNN 在 Stage 2 沒明顯打敗本 Stage 1 plateau → DNN claim 純粹是 vs-HS-only artifact。

## 設計

| Spec | Value |
|------|-------|
| Assets (dependent) | TLT (20+yr Treasury), HYG (HY credit) |
| Topic-cluster compliance | 排除 SPY/QQQ；VIX 僅作 covariate |
| OOS window | 2015-01-01 ~ 2026-06-26（~11 年 / asset, 2887 obs） |
| Refit | Monthly expanding |
| Targets | VaR(5%), VaR(1%) |
| Lag | 全 covariate 用 `signal.shift(1)`（line 128，已 Codex review） |
| Seed | 1571 (CAViaR multi-start 用 `rng.default_rng(SEED)`) |

### 4 個 baseline 模型

1. **HS-250** — Rolling 250-day empirical quantile（無 covariate，傳統教科書）
2. **LinearQR** — `statsmodels.QuantReg`，covariates = `[rv5, ief_mom, lqd_mom, credit_chg, vix]`
3. **HARQ** — Quantile regression on `[rv_d, rv_w, rv_m]`（Engle & Gallo HAR-Quantile）
4. **CAViaR-SAV** — Engle & Manganelli (2004) Symmetric Absolute Value，6-start Nelder-Mead pinball-loss optimization

### 統計檢定

- Pinball loss（pointwise tick loss）
- Kupiec POF (unconditional coverage)
- Christoffersen independence (clustering)
- Diebold-Mariano with Newey-West HAC SE（L = floor(1.5 · n^{1/3})），HLN small-sample correction (h=1)

## 結果

### Calibration

| Asset | α | HS250 viol | LinearQR | HARQ | CAViaR |
|-------|---|------------|----------|------|--------|
| TLT | 0.05 | 0.0572 | 0.0495 | 0.0499 | 0.0499 |
| TLT | 0.01 | 0.0135 | 0.0118 | 0.0090 | 0.0104 |
| HYG | 0.05 | 0.0585 | 0.0378 | 0.0464 | 0.0440 |
| HYG | 0.01 | 0.0163 | 0.0066 | 0.0062 | 0.0069 |

HS-250 在 HYG VaR(5%) Kupiec p=0.040（rejects calibration）、Christoffersen p=4e-9（極強 violation clustering）— 古典 baseline 明顯 mis-calibrated。Covariate models 通過或接近通過兩個檢定。

### DM tests（HAC + HLN，h=1, n=2887）

**HYG VaR(5%)** — covariate 全打敗 HS：

| Pair | t-stat | p |
|------|--------|---|
| LinearQR vs HS250 | -2.16 | **0.031** |
| CAViaR vs HS250 | -2.39 | **0.017** |
| HARQ vs HS250 | -2.50 | **0.013** |
| HARQ vs LinearQR | +0.94 | 0.347 |
| HARQ vs CAViaR | +1.21 | 0.227 |
| LinearQR vs CAViaR | -0.61 | 0.543 |

**HYG VaR(1%)** — borderline 顯著：

| Pair | t | p |
|------|---|---|
| CAViaR vs HS250 | -2.01 | **0.044** |
| HARQ vs HS250 | -1.90 | 0.057 |
| LinearQR vs HS250 | -1.83 | 0.067 |

**TLT VaR(5%)** — 弱：

| Pair | t | p |
|------|---|---|
| CAViaR vs HS250 | -1.99 | **0.047** |
| HARQ vs HS250 | -1.69 | 0.090 |
| LinearQR vs HS250 | -1.00 | 0.317 |

**TLT VaR(1%)** — 全 NS（p > 0.09）。

### 一句話結論（Stage 1 plateau）

**HYG（信用）對 covariate 有顯著反應；TLT（利率）對本實驗的 covariate set 反應弱。三個 covariate-aware 模型彼此 statistically indistinguishable** — 形成一個 ~mean_pinball 0.00048 的 plateau。

**Stage 2 任何 DNN claim 必須 beat 這個 plateau（不是只贏 HS）才算 real information value。**

## 防錯規則對照

- ✓ `signal.shift(1)` 於 `build_panel`（line 128），HS rolling window 用 `y.shift(1)`（line 239）
- ✓ Refit on `ts` 使用 `df[df.index < ts]` 嚴格 t-1 訓練集（line 271, 314）
- ✓ Seed 1571 + `np.random.default_rng(SEED)` for CAViaR multi-start
- ✓ Common OOS index intersection 避免 model-specific cherry-pick window
- ✓ Pinball loss canonical `α·e if e≥0 else (α-1)·e`
- ✓ DM HAC Newey-West + HLN（h=1 → factor=1）
- ✓ No data leakage：CAViaR re-seed `q_prev` by recursion replay over `df[df.index < ts]` only

## 輸出

- `k1571.py` — 完整 reproducible script (604 行)
- `k1571_results.json` — meta + per-model summary + DM pairs
- `fig_quantile_loss_compare.png` — 4 panels (asset × alpha) cumulative pinball loss
- `fig_var_violations.png` — rolling 250d violation rate vs target
- `data_cache.parquet` — TLT/HYG/IEF/LQD/VIX adjusted close 2010-2026

## 下一步（Stage 2，async）

派 compute_queue 跑 DNN quantile（如 Conditional Autoregressive Value-at-Risk Neural Net 或 Taylor 2000 RNN-quantile），**強制使用同 covariate set + 同 OOS window + 同 refit cadence**，跑 DM vs (HS250, LinearQR, HARQ, CAViaR)。若 DNN 沒打敗 plateau 中位數 → null claim、寫文章「複雜模型未必勝」。

## References

- Engle & Manganelli (2004) — CAViaR
- Engle & Gallo (2006) — HAR-Q for vol; quantile extension Žikeš & Baruník (2016)
- Christoffersen (1998) — independence test
- Kupiec (1995) — POF test
- Diebold & Mariano (1995); Harvey, Leybourne & Newbold (1997) — DM test + small-sample correction
- Patton, Ziegel & Chen (2019) — joint VaR/ES scoring（Stage 2 採用）
