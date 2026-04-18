# K1132 — Block-Bootstrap CI for K1131 OOS DM-HLN t-statistic

**Status**: ROBUST (NULL conclusion holds — spline is reliably worse than tertile, 95% CI never crosses -1.96 at any block size)
**Date**: 2026-04-18
**Author**: Claude (worktree agent-k1132)
**Data**: TAIFEX TX 5-min bars 2017-2021 (K1124 cache, identical to K1131)
**Upstream**: K1131 point DM-HLN t = -3.937 (spline vs tertile)

## 計劃（Plan）

對 K1131 的 OOS DM-HLN t-statistic (-3.937) 做 circular block bootstrap (Politis & Romano 1994)，計算 95% / 90% / 99% 信賴區間，並以 Ljung-Box 檢定驗證 block size 選擇的合理性。B=5000 resamples，block size 敏感性測試 b ∈ {20, 40, 60, 100}，seed=42 固定。

## 問題描述 + 動機（Why）

### 為什麼需要這個實驗

K1131 結論 "spline 不如 tertile (DM t=-3.94)" 是建立在 HAC/Newey-West 的 DM-HLN 漸近分布假設上。但以下狀況可能讓漸近 SE 失準：

1. **小樣本 OOS**: OOS window 僅 2020-2021 (~20,914 個 5-min bar，只有 33 個 jump)；loss differentials 可能有重尾
2. **COVID 期高波動**: 2020 Q1 VIX 最高到 82.69，單日 RV 爆增，loss differential 可能叢集
3. **Jump 事件稀疏**: 只有 33 個實際 jumps，多數 bar 的 loss differential 近乎 0，但 jump 附近會有大尖峰
4. **Loss differential 序列有長記憶**: 同一 jump 事件會在 spline 被推斷值爆炸時（VIX=82 extrapolation）造成連續多個 bar 的巨大 loss difference

這些特性下，簡單 HLN t 可能嚴重高估或低估顯著性。Block bootstrap 透過保留 local serial dependence 來估計 t 的真實分布，是對 K1131 NULL 結論的**獨立 statistical robustness check**。

### 結論如何影響後續研究方向

- **若 CI 窄且不跨 0** → K1131/K1130「problem is structural」的結論 robust，下一步可果斷放棄 spline/tertile rescue，改做 K1133 (rolling spline) 或 K1134 (non-OFI vol scaling)
- **若 CI 寬但不跨 0** → 方向 robust 但 magnitude 不確定，仍可接受 NULL
- **若 CI 跨 0** → 原 DM t=-3.94 可能是 small-sample artifact，需要擴充 OOS window 或用不同測試

## 方法（Method）

### 1. 資料重建

- 載入 K1124 cache (`_cache_bars_2017-01-01_2021-12-31.parquet`, 73,203 bars / 1,223 days)
- Lee-Mykland K=16 strictly-past BV jump detection，Gumbel α=0.01 threshold=5.126
- VIX T-1 lag (yfinance `^VIX`，前一 US close)
- IS 2017-2019 / OOS 2020-2021 切分（K1131 相同）
- Refit M_base / M_tertile / M_spline 於 IS，全部 MLE L-BFGS-B，L2=1e-4，seed=42
- OOS 預測 → 每 bar log-loss → loss_tertile - loss_spline

**reproduction sanity check**: point DM-HLN t 與 K1131 `H2_DM_spline_vs_tertile.t` 差值 |delta| 必須 ≤ 0.02；若不符則 `sys.exit(1)`。實測 t=-3.936694 vs K1131 t=-3.936694 → **exact match** (7 位小數)。

### 2. Ljung-Box 檢定 loss differentials

檢定 lags m ∈ {1, 5, 10, 20, 60, 120}：

| m | Q(m) | p | 詮釋 |
|---|---|---|---|
| 1 | 21.88 | 2.9e-06 | 明顯 lag-1 自相關 |
| 5 | 797.07 | 0 | |
| 10 | 808.50 | 0 | |
| 20 | 919.63 | 0 | |
| **60** | **1076.22** | **0** | **一個交易日** |
| 120 | 1190.41 | 0 | 兩個交易日 |

**結論**: Q(60) 相對 Q(20) 成長 17%，Q(120) vs Q(60) 再成長 11% — 自相關延伸到 ~60-120 bars（1-2 trading days）。Jump 事件（COVID Q1 一連多日的大跌）造成 loss differential 長叢集。**block size ≥ 60 合理**。

### 3. Circular block bootstrap（Politis-Romano 1994）

- `d_wrap = np.concatenate([d, d[:b]])` 長度 n+b（讓尾端可以 wrap）
- 每個 resample：`starts = rng.integers(0, n, size=ceil(n/b))`，每個 start s 取 `d_wrap[s:s+b]`，拼接後截斷至長度 n
- 對 resampled d 重新計算 DM-HLN t_hln
- B=5000 resamples，`rng = np.random.default_rng(42)` 固定 seed
- Block sizes tested: b ∈ {20, 40, 60, 100}
  - b=20 bars ≈ 100 min (~1.67 hour)
  - b=60 bars ≈ 300 min (~1 trading day)（headline）
  - b=100 bars ≈ 500 min (~1.7 trading day)

### 4. Pre-registered verdict rule（實驗前固定）

| Verdict | Rule |
|---|---|
| **robust** | 95% CI upper bound < -1.96 於 **所有** block sizes |
| **inconclusive** | 95% CI upper bound ≥ -1.96 於**任一** block size，或 CI 跨 0 |
| **not-robust** | 95% CI 包含 0 於任一 block size（sign could flip） |

### 5. Codex / Gemini review

- **Codex**：worktree agent 環境下 `codex:review` skill 被封鎖（權限拒絕），無法執行。與 K1130、K1131 相同情境（那兩次是 usage limit）— 保留 limitation 在下方記錄。
- **Self-audit 7 points**（取代 Codex review，主線程應於 merge 前追補）：
  1. HLN mult 公式 `sqrt((n+1-2h+h(h-1)/n)/n)` 對 h=1 → `sqrt((n-1)/n)` ✓
  2. Circular block bootstrap wrap 寫法正確：`d_wrap = concat(d, d[:b])` 長 n+b，`starts ∈ [0, n)`，`d_wrap[s:s+b]` 最大 index = (n-1)+(b-1) = n+b-2 < n+b ✓
  3. RNG 重現性：主 bootstrap 與 plot bootstrap 各用 fresh `np.random.default_rng(42)` → 同一序列 ✓
  4. Point DM reconstruction 對得上 K1131 t=-3.936694（7 位小數 match）✓
  5. Ljung-Box Q 公式: `Q = n(n+2) Σ_{k=1..m} ρ_k²/(n-k)` ✓
  6. No lookahead（bootstrap 在 post-prediction loss differentials 上做，不涉及未來）✓
  7. No shared-state writes（只寫 `experiments/k1132/` 內檔案）✓

## 結果（Results）

### Point estimate

| 指標 | 值 |
|---|---|
| DM-HLN t_hln | **-3.937** |
| DM plain t | -3.937 |
| mean_d (loss_tertile - loss_spline) | -7.579e-04 |
| SE_HAC | 1.925e-04 |
| n | 20,914 |

### Bootstrap CIs（B=5000，seed=42）

| Block size b | mean t_draws | std | 95% CI | 90% CI | 99% CI | P(t ≥ 0) | P(t ≥ -1.96) |
|---|---|---|---|---|---|---|---|
| 20 | -4.830 | 1.648 | [-8.958, -2.553] | [-7.788, -2.900] | [-10.94, -1.975] | 0.0002 | 0.0118 |
| 40 | -4.557 | 1.473 | [-8.209, -2.405] | [-7.198, -2.685] | [-9.62, -1.773] | 0.0000 | 0.0086 |
| **60** (headline) | **-4.513** | **1.399** | **[-7.979, -2.426]** | **[-7.426, -2.733]** | **[-9.20, -1.826]** | **0.0000** | **0.0090** |
| 100 | -4.461 | 1.376 | [-7.799, -2.418] | [-6.945, -2.704] | [-9.10, -1.794] | 0.0000 | 0.0082 |

### 詮釋

1. **Bootstrap mean t ≈ -4.5**（比 point -3.94 還負一些）→ HAC SE 可能**輕微高估** t（低估 |t|）；正確方向的不確定性**甚至比 HLN 宣稱的更強**。
2. **95% CI 在所有 block sizes 都完全低於 -1.96**，upper bound 最高 = -2.405（b=40），最低 = -2.553（b=20）。
3. **P(bootstrap t ≥ 0) ≤ 0.0002**（幾乎不可能 sign flip）
4. **P(bootstrap t ≥ -1.96) ≤ 0.012**（幾乎不可能失去 DM 顯著性）
5. **Block size 敏感性**: 從 b=20 到 b=100，bootstrap mean 從 -4.83 縮到 -4.46（約 0.4），CI 寬度也類似縮減。此行為符合 block bootstrap 理論（b 越大 → sample path 越保留 → variance estimate 越穩定但收斂較慢）。**所有 b 都得出同方向與同量級結論**，結果不受 block size 選擇主導。
6. **99% CI 也都不跨 0**（最寬 [-10.94, -1.975] 於 b=20）。

## 驗證（Verdict）

**`robust`**

- 95% CI upper bound < -1.96 於 **所有** 4 個 block sizes ✓
- 99% CI upper bound < 0 於所有 block sizes ✓
- P(t ≥ 0) ≤ 0.0002

## 預期 vs 實際

| 預期情境 | 實際 | 後續行動 |
|---|---|---|
| Narrow CI, 不跨 0 → NULL robust | **命中**（95% CI [-7.979, -2.426], b=60）| K1131/K1130 "structural" 結論 robust，下一步轉向 K1133 rolling spline / K1134 non-OFI vol scaling |
| Wide CI, 不跨 0 → direction robust, magnitude uncertain | 部分命中（CI 寬度 ≈ 5.5 t 單位，point 落在中央）| 已達成 direction robust |
| CI 跨 0 → artifact | 未發生 | — |

## 結論（Conclusion）

**K1131 OOS DM-HLN t=-3.94 對 block-bootstrap 敏感性驗證 robust。** Spline 確定在 COVID-era OOS 劣於 tertile——這個結論不是 HAC 小樣本漸近失準造成的統計假象。

結合：
- K1130: 擴展 IS 到 2012-2019（14 年）仍 NULL（min coverage 1.63%）
- K1131: 連續 spline 處理 cutoff 問題也 NULL（spline OOS AUC=0.496 below chance）
- K1132 (本實驗): K1131 OOS DM t 的 block-bootstrap 95% CI 嚴格低於 -1.96

**三條獨立證據都指向同一結論**: K1128 OFI→jump regime-switching 在 COVID-era OOS 表現為 NULL 不是 "cutoff 設計問題"、不是 "spline 參數化問題"、也不是 "small-sample noise"，而是 **OFI predictability 在 unprecedented VIX regime 下的結構性失效**。

**主線程 research_program.md 建議更新**：
- K1128 / K1130 / K1131 / K1132 共同 sub-lesson："regime-based rescue of structural OOS failure 不應再重複"
- K1133 (rolling/expanding-window spline) 作為最後一個 regime-based attempt
- K1134 (non-regime, OFI / σ vol-scaling) 值得優先推進

## 限制（Limitations）

1. **Block bootstrap 不能修復 jump 事件的結構性 mismatch**。如果 COVID 是一個 regime-shift 而非 in-distribution extreme，所有 IS-fit model 都會失準；bootstrap 只告訴我們「在這個 OOS sample 內 DM t 穩定為負」，不是「未來 OOS 也會持續失準」。
2. **Codex review 被封鎖**（worktree agent 環境 skill permission 拒絕）；以 self-audit 7 points 代替，主線程 merge 前應追補 Codex review。與 K1130/K1131 的 "Codex blocked by usage limit" 狀態一致，但這次是 permission 而非 usage。
3. **Block size 自動選擇**：本次手動固定 b ∈ {20, 40, 60, 100}。若用 Politis-White (2004) automatic block-length 會更嚴謹，但 Ljung-Box Q(60)=1076 已強力支持 b=60 足夠 capture 主要 dependence。
4. **只對 spline vs tertile 做 CI**；未對 spline vs base、tertile vs base 做同類 CI。理由：這些已在 K1131 報告中屬次要 contrast，且結果與本實驗一致方向（tertile vs base DM t=-0.42，絕對值遠低於 2，已明顯 non-significant）。

## Files

- `k1132.py` — 主腳本（循環 block bootstrap + Ljung-Box + Politis-Romano 1994）
- `k1132_results.json` — 完整數值結果
- `bootstrap_distribution.png` — 4 subplot（b=20/40/60/100）的 t_draws histogram + CI bounds
- `run.log` — 執行日誌
- `README.md` — 本檔

## References

- **Politis, D.N., Romano, J.P. (1994a)**. "The Stationary Bootstrap." *Journal of the American Statistical Association* 89(428), 1303-1313.
- **Politis, D.N., Romano, J.P. (1994b)**. "Large sample confidence regions based on subsamples under minimal assumptions." *Annals of Statistics* 22(4), 2031-2050. — circular block bootstrap
- **Politis, D.N., White, H. (2004)**. "Automatic block-length selection for the dependent bootstrap." *Econometric Reviews* 23(1), 53-70.
- **Harvey, D., Leybourne, S., Newbold, P. (1997)**. "Testing the Equality of Prediction Mean Squared Errors." *International Journal of Forecasting* 13(2), 281-291.
- **Diebold, F.X., Mariano, R.S. (1995)**. "Comparing Predictive Accuracy." *Journal of Business & Economic Statistics* 13(3), 253-263.
- **Ljung, G.M., Box, G.E.P. (1978)**. "On a measure of lack of fit in time series models." *Biometrika* 65(2), 297-303.
- K1131 (本 project): natural cubic spline OOS DM-HLN — the t-statistic we are bootstrapping.
- K1130 (本 project): extended-IS 2012-2019 — confirms structural rather than sample issue.
- K1128 (本 project): original VIX tertile experiment — the upstream.

## Derived Directions

1. **K1133 — rolling/expanding-window spline**: 每月 refit 在 expanding window，讓 COVID VIX 進入訓練；block-bootstrap 可在此重新驗證 DM t
2. **K1134 — non-regime vol-scaling**: 跳脫 regime-switching paradigm，改用 `|OFI| / σ̂_local` 測試 microstructure-shock-relative-to-noise hypothesis
3. **K1132b (optional)**: 對 K1131 其他 secondary contrast（high-VIX only M3 AUC=0.626 claim）做相同 block-bootstrap，進一步確認 descriptive-only 是 overfit artifact
