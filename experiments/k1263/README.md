# K1263: KAN-GARCH-MIDAS — Can structured Kolmogorov-Arnold Networks break the ML ceiling?

> **Status**: pending finalization (see `k1263_results.json` for verdict).
> **Date**: 2026-05-02
> **Proposer**: User; **Executor**: Claude (main thread)

## 動機

ML / NN models on equity daily volatility 已連續 **6 次 NULL** 對 GJR-GARCH baseline:

| K | Method | Verdict |
|---|--------|---------|
| K785 | MF2-GARCH | NULL (DM\|t\|<2) |
| K816v2 | GINN (GARCH-informed NN) | NULL |
| K784 | GARCH-GRU | NULL |
| K1038 | GAS-t (equity) | NULL |
| K1129 | GAS-t (commodities) | NULL |
| K1100g_d* | various NN ensembles | NULL |

KAN (Liu et al. 2024, arXiv:2404.19756) 用 **learnable spline activations on edges** 替代 fixed-activation MLP nodes — 結構化先驗（spline grid + cubic basis），假設可在 unstructured ML 失敗處勝出。Falsifiable hypothesis：若 KAN 也 NULL，則為 **ML ceiling 第 7 次確認**。

## 假設

- **H0**: KAN-GARCH-MIDAS QLIKE 與 GJR baseline 統計上 indistinguishable（DM-HLN \|t\|<3.0）。
- **H1**: KAN 提供 marginal QLIKE 改善，三重 OOS gate 全過。

## 設計

### 數據
- **Assets**: SPY, QQQ (yfinance, daily, 2007-01-01 → 2026-04-10)
- **Macro X**（皆 lagged by 1 day; 防 lookahead）:
  1. VIX level (`^VIX`)
  2. 10y − 3m term spread (`^TNX − ^IRX`)
  3. HYG/IEF log-return (credit-spread proxy; FRED 不可用 → yfinance ETFs)
  4. 22d rolling realized vol of SPY

### 模型
- **Baseline (B)**: GJR-GARCH-Normal, expanding window, scipy MLE multistart, refit every 63 days (與 K785 同口徑)
- **Challenger (C)**: KAN-GARCH-MIDAS

  $$\sigma^2_{t+1} = g_{t+1|t} \times \tau_{t+1|t}$$

  - $\tau_t = \exp(\text{KAN}(X_{t-1}))$ — KAN width=[d, 3, 1], grid=5, k=3 (cubic spline), pykan 0.0.5
  - KAN target: 22-day EWMA-smoothed $\log r_t^2$ (long-run variance proxy)
  - $g_t$: GJR-Normal one-step variance forecast scaled by $\tau$ training mean

### Walk-forward
- Window: KAN trained on rolling 1500 obs; GJR expanding
- Refit: 每 63 trading days (quarterly) 重新 fit 兩模型
- OOS: 2021-01-04 → 2026-04-10 (≈ 1300 trading days)
- Sub-period split: 2024-01-01 (early ≈ 750 days, late ≈ 550 days)

### 評估
- **Loss**: Patton (2011) QLIKE on $r^2$
- **DM-HLN**: Diebold-Mariano with Harvey-Leybourne-Newbold (1997) small-sample correction, $h=1$
- **三重 OOS publishable gate** (per K1100g_d1):
  1. DM-HLN \|t\| > 3.0 (Harvey 2016)
  2. QLIKE relative improvement ≥ 5%
  3. Sub-period stable (early + late 都 better)

### 隨機性控制
- Global seed = 42 (numpy + torch + KAN init)
- 所有 macro X 在 walk-forward 前一次性 `.shift(1)`（可在代碼 `build_panel()` + `run_asset()` 開頭 verify）

## 結果

詳見 `k1263_results.json`。摘要會在跑完後填入。

```
TBD: per-asset QLIKE (GJR vs KAN), DM t-stat, gates passed, verdict
```

## Verdict

詳見 `k1263_results.json` 的 `overall_verdict`。

- **若 NULL** (gates < 3 on both assets) → **ML ceiling 第 7 次確認**, 寫成 null-result 文章 + 加入 `research_program.md` ceiling tracker
- **若 POSITIVE** (gates = 3 on ≥1 asset) → Paper-3 候選, 進 multi-asset robustness check

## 圖表

- `k1263_qlike_comparison.png` — QLIKE bar chart（GJR vs KAN-GARCH-MIDAS, per asset）
- `k1263_dm_heatmap.png` — DM-HLN heatmap（full + sub-period, 統一 positive=KAN better convention）

## Reproduce

```bash
# Requires anaconda3 python with pykan 0.0.5 + torch 2.0.1 (system python)
python experiments/k1263/k1263.py
```

執行時間：~10–20 min (取決於 KAN refit 數)。資料 cache 在 `experiments/k1263/data/`。

## References

1. Liu Z. et al. (2024). "KAN: Kolmogorov-Arnold Networks." *arXiv:2404.19756*.
2. Liu Z. et al. (2025). "KAN 2.0." *arXiv:2408.10205*.
3. Engle R., Ghysels E., Sohn B. (2013). "Stock Market Volatility and Macroeconomic Fundamentals." *Review of Economics and Statistics* 95(3): 776–797.
4. Conrad C., Engle R. (2025). "Long- and Short-Run Components of GARCH." *Journal of Applied Econometrics*.
5. Patton A. (2011). "Volatility forecast comparison using imperfect volatility proxies." *Journal of Econometrics* 160: 246–256.
6. Harvey C., Liu Y., Zhu H. (2016). "...and the Cross-Section of Expected Returns." *Review of Financial Studies* 29(1): 5–68.
7. Diebold F., Mariano R. (1995). "Comparing Predictive Accuracy." *JBES* 13: 253–263.
8. Harvey D., Leybourne S., Newbold P. (1997). "Testing the equality of prediction mean squared errors." *Int. J. Forecasting* 13: 281–291.

## Codex Review (round 1, 2026-05-02)

4 issues raised, all addressed:
- **P1** (`pykan` undeclared in pyproject) → explicit `ImportError` with env note
- **P1** (silent random-init KAN fallback) → now `RuntimeError` if both LBFGS + Adam fail
- **P2** (HYG/IEF level vs documented log-return) → fixed to log-return per design header
- **P3** (DM heatmap sign inconsistency) → flipped full-OOS row sign so all rows use `positive = KAN better`

## 防錯規則 checklist

- ✅ `signal.shift(1)` for ALL macro X (`df[macro_cols] = df[macro_cols].shift(1)`)
- ✅ Baseline 與 challenger 同 lag 慣例（GJR train on `r[:idx]`, forecast `idx`; KAN reads X at idx where X already pre-lagged）
- ✅ Fixed seed = 42（numpy / torch / KAN init）
- ✅ Codex review pre-execution（round 1 PASS w/ fixes applied）
- ✅ Three-gate publishable bar (DM \|t\|>3 + 5% rel-impr + sub-period stable)
- ✅ Patton QLIKE on $r^2$ (proxy-robust)
- ✅ DM-HLN small-sample correction
- ✅ Numerical clamps (`max(..., 1e-10)` in QLIKE, `clip(log_tau, -8, 8)` in tau exp)
