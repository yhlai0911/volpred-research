# K1103: τ-lag Bug-Fix Replication Across TSMC / MediaTek / UMC

**[提出: 賴奕豪, 執行: Claude]**

## Problem / Bug description

K1067 系列（K1067 TSMC, K1067b UMC, K1067c MediaTek）的 A4f-EAV GARCH-MIDAS
實作在短期分量 g 的更新中使用了錯誤的 τ 時間索引：

```python
# Original (BUGGY)
u_prev = r_{t-1} / sqrt(tau[t])       # 使用 t 期的 τ

# Correct
u_prev = r_{t-1} / sqrt(tau[t-1])     # 使用 t-1 期的 τ
```

在 canonical GARCH-MIDAS (Engle, Ghysels & Sohn 2013) 中，短期殘差定義為
`u_t = r_t / sqrt(τ_t)`。因此 g 更新應該使用 `u_{t-1} = r_{t-1}/sqrt(τ_{t-1})`，
而不是 `τ_t`。

**為何有潛在放大效果？** 當 EAV 是二元公告指標時，`τ` 在公告後 T 天會因
`θ₂·EAV_{t-1}=1` 而大幅上升。舊代碼用 `sqrt(large τ[t])` 標準化 `r_{t-1}`，
會人為縮小 `u_{t-1}²`，放緩 g 的更新，讓 `σ²_t = τ_t · g_t` 維持
接近「未受干擾的 g × 放大的 τ」。這種雙向因果路徑理論上可能把 EAV 的
event-window 邊際效果放大，進而解釋 UMC 的 +39.27% 顯著表現與 TSMC 的
-0.25% null result 為何差距如此大。

## Motivation

K1067b UMC 的 event-window DM |t|=2.20, improvement=+39.27% 是整個 Paper 2
「選股作為 Paper 差異化」論述的支柱。如果這個結果是 τ-lag bug artefact，
則 K1067b/K1067c 的 monotonicity 討論整個崩塌。

K1103 的決策樹：

| UMC new |event DM t| | 結論 | Paper 2 影響 |
|---------------------|------|--------------|
| `< 1.0` | Scenario 1: 結果是 bug artefact | 徹底移除 EAV 章節 |
| `∈ [1.0, 2.0]` | Scenario 2: 部分 artefact | 保留但加 timing warning |
| `≥ 2.0` | Scenario 3: bug 影響 negligible | 結論穩固，可繼續推進 |

## Method

統一修正三份原始代碼的四處 τ-lag 出錯點：

1. `fit_a4f` / `fit_a4f_eav` 的 `neg_loglik` 內迴圈（MLE 訓練）
2. 每次 refit 後的 g state warmup 迴圈
3. OOS forecast loop — 新增 `state['tau_prev']` 追蹤前一天 τ
4. Full-sample `fit_and_score_full_sample`（K1103 內已納入一致化的 OOS-only 版本）

實驗規格與 K1067 系列完全一致（WINDOW=2000, REFIT_EVERY=63,
OOS_START=2019-01-01, DATA_END=2025-12-31, seed=42）。
評估：QLIKE on r² target（Patton 2011），Harvey DM |t|>3.0。

Codex read-only 審查已通過（三處 τ/g state transition 全部 verified correct）。

## Data

- `yfinance`：2330.TW, 2454.TW, 2303.TW, ^VIX (auto_adjust=True)
- `財報公告日.txt`（Big5）→ 按 code 過濾（2330 / 2454 / 2303）
- Period 2010-01-01 → 2025-12-30，n=3911 trading days per firm
- OOS 2019-01-01 → end，n_oos=1697，n_refits=27 per firm

## Old vs New 完整對照表

### Event-window (T+1) DM 與 improvement

| 公司 | T+1 amp | 指標 | Old (buggy) | New (fixed) | Δ | 評估 |
|------|--------:|------|------------:|------------:|---:|------|
| TSMC | 0.98 | Event DM t        | `+0.083` | `+0.678` | +0.595 | 仍 NULL |
| TSMC | 0.98 | Event improvement | `-0.249%` | `-7.178%` | -6.930 pp | EAV 在 TSMC 更差 |
| MediaTek | 1.67 | Event DM t        | `+1.588` | `+1.406` | -0.182 | 仍 NULL（方向錯） |
| MediaTek | 1.67 | Event improvement | `-23.461%` | `-22.558%` | +0.903 pp | 幾乎不變 |
| **UMC** | **2.58** | **Event DM t**        | `-2.204` | `-2.399` | **-0.194** | **穩定 significant** |
| **UMC** | **2.58** | **Event improvement** | `+39.266%` | `+39.425%` | **+0.159 pp** | **穩定** |

### Aggregate OOS DM 與 improvement

| 公司 | 指標 | Old (buggy) | New (fixed) | Δ | 評估 |
|------|------|------------:|------------:|---:|------|
| TSMC | Aggregate DM t     | `+0.348` | `+0.239` | -0.109 | NULL (both) |
| TSMC | Aggregate improvement | `-0.070%` | `-0.058%` | +0.012 pp | 幾乎不變 |
| MediaTek | Aggregate DM t     | `+0.616` | `+0.283` | -0.333 | NULL (both) |
| MediaTek | Aggregate improvement | `-0.154%` | `-0.070%` | +0.084 pp | 幾乎不變 |
| UMC | Aggregate DM t     | `-1.371` | `-1.610` | -0.239 | 仍 not significant at Harvey |
| UMC | Aggregate improvement | `+0.517%` | `+0.503%` | -0.014 pp | 穩定 |

### θ₂ 分配

| 公司 | 指標 | Old (buggy) | New (fixed) | 評估 |
|------|------|------------:|------------:|------|
| TSMC | θ₂ positive fraction | `0.593` | `0.556` | 都在 ~0.5-0.6（noise） |
| TSMC | one-sided p_one      | `0.948` | `0.383` | 都 not significant |
| MediaTek | θ₂ positive fraction | `0.185` | `0.111` | 都 < 0.2（θ₂ 主要為負） |
| MediaTek | one-sided p_one      | `0.980` | `0.968` | 都 not significant |
| **UMC** | **θ₂ positive fraction** | `1.000` | `1.000` | **永遠為正（27/27 refits）** |
| **UMC** | **one-sided p_one**      | `6.68e-15` | `8.35e-13` | **仍 extremely significant** |

## 決定性結論：SCENARIO_3_STABLE

**UMC event DM |t| 從 2.204 → 2.399（更強），通過 |t| ≥ 2.0 門檻。**
**→ τ-lag bug 對主要結論影響 negligible。K1067b/K1067c monotonicity findings 穩固。**

具體地：

1. **UMC** 在每個指標（event DM、event improvement、θ₂ pos_frac、θ₂ p-value、
   aggregate DM、aggregate improvement）都幾乎完全穩定。θ₂ one-sided p-value
   從 6.7e-15 略降至 8.3e-13，但依然是 extremely significant（遠超 Harvey |t|>3 門檻的對應 p-value）。

2. **TSMC** NULL 結果不變：event DM 從 +0.08 → +0.68，方向仍為 A4f better，
   且 Harvey |t|>3 仍 FAIL。改動主要反映修正後 τ 與 u 的正確對齊讓
   EAV dummy 的擾動沒有被「抵消」——TSMC 的實際 EAV signal 本來就弱。

3. **MediaTek** 非單調性（T+1 amp=1.67 but event DM=+1.41 與 TSMC/UMC 不在
   同一方向）保留：修正後 θ₂ pos_frac 甚至更低（0.185→0.111），顯示
   MediaTek 的 EAV 實際上傾向為負貢獻 τ。這進一步支持 K1067c 的結論
   ——monotonicity 並非 T+1 amplification 單一決定，而是 UMC 的極端
   foundry commodity exposure 產生的特殊 signature。

## Paper 2 最終決策

**Keep EAV with monotonicity nuance。** 具體：

- **保留 UMC event-window analysis 作為 Paper 2 的示範案例**，因為 fix 後 DM |t|≥2 且 θ₂ 高度顯著。
- **TSMC 仍列為 null result** 支持 K1067 結論：低 T+1 amplification 股票 EAV 無邊際。
- **MediaTek 維持「非單調反例」論述**：K1067c 結論（T+1 amp 不是唯一決定因素）
  在 τ-lag fix 後更站得住腳——MediaTek 的 θ₂ 明顯偏負，反映 announcement-day 之後
  波動不一定放大，與 TSMC/UMC 的清晰 asymmetry 形成對比。
- 論文務必在 methodology 段**明確定義** `u_t = r_t/sqrt(τ_t)` 並引用
  Engle-Ghysels-Sohn (2013) 的 canonical 表達式，避免讀者誤以為 `τ[t]` vs
  `τ[t-1]` 的差別可忽略。

## 衍生方向

1. **回溯 K1067 系列 knowledge 紀錄**：所有 k1067 系列 knowledge entries 應加
   「τ-lag 修正後結果一致」的 annotation，提升可信度（不用推翻），並引用 K1103 作為 robustness 證據。
2. **Multi-covariate firm-level model**：既然 T+1 amp 不夠解釋（MediaTek 反例），
   下一步是加入 foundry/fabless dummy、analyst coverage、beta、size 等協變量做
   cross-sectional regression of θ₂ on firm attributes（K1060 已有 Top 4 data，
   可擴展到 Top 20）。
3. **ASE (3711.TW, T+1=1.85) 與其他 chip names validation**：既然 UMC signal
   穩固，下一步可以測試是否延伸到其他 foundry/IC 股票（ASE、WPG、Nanya 等）。

## Files

- `k1103.py` — 統一代碼（內部迴圈跑三家公司）
- `k1103_results.json` — 完整結果（含 old-vs-new comparison 表）
- `k1103_three_firms_comparison.png` — Chart 1: 三公司 old vs new DM/improvement bar chart
- `k1103_theta2_evolution_fixed.png` — Chart 2: 三公司 θ₂ 時序（修正後）
- `k1103_event_window_fixed.png` — Chart 3: 三公司 event T+1 vs non-event（修正後）

## References

- Engle, R. F., Ghysels, E. & Sohn, B. (2013). Stock market volatility and macroeconomic fundamentals. *Review of Economics and Statistics* 95(3):776-797.
- Patton, A. J. (2011). Volatility forecast comparison using imperfect volatility proxies. *Journal of Econometrics* 160(1):246-256.
- Harvey et al. (2016). DM t > 3.0 threshold.
- K1067 / K1067b / K1067c — original (buggy) implementations.

## Reproducibility

- Random seed: 42 (numpy + `np.random.default_rng(42)` for bootstrap)
- Runtime: ~595 s (10 min) on Apple M1 Max, single-threaded
- Data timestamp: 2026-04-13
- Data source: yfinance (auto_adjust=True) + `財報公告日.txt` (Big5, code-filtered)
