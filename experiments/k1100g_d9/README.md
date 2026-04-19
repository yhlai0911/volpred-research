# K1100g_d9 — Refit-cadence robustness rerun of K1100g_d8 at d7 cadence

[提出: Claude 自主研究 / 執行: Claude worktree agent-aa9aeb5d / 2026-04-18]

## 1. 動機（Why）

K1100g_d8 (2026-04-17) 想用 **Hansen (1994) skewed-t innovation** 把 K1100g_d7 的 N225 gap² DM +2.32 推過 Harvey |t|>3。實際結果出乎意料：

| 實驗 | refit_every | N225 DM gap Student-t | N225 DM gap skewed-t | SPY DM gap Student-t | SPY DM gap skewed-t |
|------|-------------|----------------------:|---------------------:|---------------------:|--------------------:|
| K1100g_d7 | **5**  | **+2.32** | —        | **+0.66** | —        |
| K1100g_d8 | **25** | **-1.92** | **-1.33** | **-2.10** | **-1.74** |

**Student-t DM 在 d7→d8 cadence 從 5 放寬到 25 之間符號翻轉且強度大幅改變**（+2.32 → -1.92）。
d8 README Sec 5.1 直接把這個現象定性為 **"refit cadence artifact"**，並把 Hansen skewed-t 的 verdict 標為 PRELIMINARY，呼籲 K1100g_d9 用 **d7 cadence** 重跑以確認：

1. 若 d9（refit_every=5）把 Student-t DM 恢復到 d7 的 +2.32 → 確認是 cadence artifact；skewed-t 的 d8 結果也需在正確 cadence 重新評估
2. 若 d9 的 skewed-t DM 也跟著恢復到高位 → d8 "skewed-t 不 help" 結論被推翻
3. 若 d9 的 skewed-t DM 仍 borderline/negative → 即使 cadence 恢復 skewed-t 仍不 help，d8 主結論成立

這是 **Paper 3 TAIFEX/cross-market microstructure narrative 的 robustness 關鍵 gate**。narrative state machine 規則：三個互補實驗（d7/d8/d9）都完成後才進 Paper 3 body rewrite decision。

## 2. 方法（How）

### 2.1 設計原則：**唯一差別 = refit cadence（+ 對應 n_restarts）**

| 參數 | K1100g_d7 | K1100g_d8 | K1100g_d9 |
|------|----------:|----------:|----------:|
| `refit_every` | 5 | 25 | **5** |
| `n_restarts_is` | 8 (default) | 10 | 10 |
| `n_restarts_oos_warm` | 4 | 2 | **4** |
| `n_restarts_oos_cold` | 6 | 4 | **6** |
| Innovation | Student-t | Student-t + Hansen skewed-t | Student-t + Hansen skewed-t |
| Markets | SPY, N225 | SPY, N225 | SPY, N225 |
| Model count per market | 2 | 4 | 4 |

**其餘全部 identical to d8**：同 PRG τ×g kernel、同 Hansen skewed-t 閉式密度、同 9+1/9+2 PRG parameterization、同 gap² definition、同 TRAIN/TEST split（2010-2019 / 2020-2025）、同 yfinance daily OHLC cache（symlink 自 d8 `data/`）。

### 2.2 PRG kernel（抄自 d8，不變）

```
σ²_t = τ_t × g_t
τ_t  = θ0 + θ1·r²_{t-1} + Σ d_k·DOW_k(t)   (+ ξ·gap²_t 當 exog)
g_t  = (1-α-γ/2-β) + α·u²_{t-1} + γ·u²_{t-1}·I(r_{t-1}<0) + β·g_{t-1}
```

Student-t: 11 params (`[θ0,θ1,d1,d2,d3,d4,α,γ,β,(ξ),df]`)。
Hansen skewed-t: 12 params（`df` 換成 `(η, λ)`）。

Hansen (1994) 閉式密度（E[z]=0, Var[z]=1）：
```
c = Γ((η+1)/2) / (sqrt(π(η-2)) Γ(η/2))
a = 4·λ·c·(η-2)/(η-1)
b = sqrt(1 + 3λ² - a²)
For z ≥ -a/b:  log f(z) = log b + log c - ((η+1)/2) log(1 + ((bz+a)/(1+λ))²/(η-2))
For z <  -a/b:  log f(z) = log b + log c - ((η+1)/2) log(1 + ((bz+a)/(1-λ))²/(η-2))
```

λ=0 退化為 variance-standardised Student-t；**import-time sanity check 強制通過**。

### 2.3 Lookahead / seed 紀律

- `gap²_t = (log Open_t - log Close_{t-1})²`：在 `r_intraday_t = log(Close_t/Open_t)` 從 Open 開始累積之前已 realized（Paper 6 K880 option-b precedent；與 d7/d8 一致）
- `np.random.seed(42)`、`RNG = np.random.default_rng(42)`、fitters 內 `local_rng = np.random.default_rng(42)`
- L-BFGS-B deterministic；OOS warm-start 傳遞 previous refit params

### 2.4 資料

| Market | Ticker | n | Train (2010-2019) | Test (2020-2025) |
|--------|--------|---|-------------------|------------------|
| N225 | `^N225` | 3970 | 2447 | 1465 |
| SPY  | `SPY`   | 4084 | 2515 | 1508 |

Cache 經 symlink 自 `../k1100g_d8/data/`，raw input 與 d8 完全相同。

### 2.5 評估

- IS LRT (χ²(1))：gap 貢獻 + innovation λ=0 限制
- OOS expanding-window at refit_every=5
- DM-HLN（Harvey-Leybourne-Newbold 1997 correction；1/3 power bandwidth）
- Harvey (2016) |t|>3 threshold
- **Cadence-sensitivity classifier**：比較 d9 vs d8 vs d7 DM

### 2.6 Cadence-sensitivity verdict 分類

| Verdict | 判準 | Paper 3 narrative 意涵 |
|---------|------|-----------------------|
| `PASS_N225_HARVEY_UNDER_CADENCE` | N225 gap_sk DM > +3.0 | d8 結論推翻；proper cadence 下 skewed-t DOES help |
| `ROBUST_WITH_RECOVERY` | d9 Student-t DM 回到 d7 sign + abs>1.0；d9 gap_sk DM 仍 <1.96 | cadence artifact 確認；skewed-t 不 help 結論成立（有 clean baseline 支持） |
| `ROBUST_WITH_RECOVERY_SK_BORDERLINE` | d9 Student-t 回到 d7；d9 gap_sk 5%-sig 但 \|t\|<3 | d7 DIRECTION_CONSISTENT 擴展到 skewed-t |
| `NON_RECOVERY` | d9 Student-t 未回到 d7 sign | cadence 非主導 driver；d8 結論需獨立驗證 |
| `MIXED` | SPY / N225 模式不一致 | 無法一刀切 |

搭配 **cadence_sensitivity_verdict** 子分類：
- `CADENCE_ARTIFACT_FOR_STUDENT_T_NOT_FOR_SKEWED_T`：Student-t recovered、skewed-t 仍 not Harvey → **預期路徑**
- `CADENCE_ARTIFACT_MASKED_SKEWT_GAIN`：skewed-t 在 d9 終於過 Harvey → d8 誤導
- `CADENCE_NOT_DOMINANT_DRIVER`：Student-t 都未 recover → cadence 不是主因
- `MIXED_ACROSS_MARKETS`：跨市場不一致

## 3. 預期結果（Expectations before run）

基於 d8 Sec 5.1 的 cadence artifact 假設：

1. **最可能**：`ROBUST_WITH_RECOVERY`
   - N225 Student-t DM 恢復到 +2.0 ~ +2.5 區間（接近 d7 +2.32）
   - SPY Student-t DM 恢復到 +0.5 ~ +1.0（接近 d7 +0.66）
   - N225 skewed-t gap DM：~ +2.0 ~ +2.5 range（類似 Student-t，因 IS LRT innov=0 表示 λ 對 N225 無貢獻）
   - SPY skewed-t gap DM：~ +0.5 ~ +1.5（innov_gap SPY d8 已經 +1.88 borderline，d9 proper cadence 下應維持或略強）
   - **cadence_sensitivity_verdict = `CADENCE_ARTIFACT_FOR_STUDENT_T_NOT_FOR_SKEWED_T`**

2. **次可能**（~20% prob）：`PASS_N225_HARVEY_UNDER_CADENCE`
   - 若 Hansen skewed-t + proper cadence 真的讓 N225 過 |t|>3 → Paper 3 narrative 升級為 "N225-confirmed"

3. **低機率**（<15% prob）：`NON_RECOVERY`
   - 若 d9 Student-t 仍 negative → 意外發現，代表 d7 +2.32 本身可能是 d7 特殊 n_restarts 或其他 numerical 問題。需進一步 k1100g_d10 diagnostic。

4. **Runtime 預期**：90-150 分鐘（8 OOS 迴圈 × ~300 refits each × ~1-2s/refit；skewed-t 比 Student-t 慢約 1.5×）

## 4. 結論（Conclusions）

**[在 run 完成後更新此段]**

### 4.1 核心 DM 表

*待 run 完成填入*

| 市場 | d7 Student-t DM | d8 Student-t DM | d9 Student-t DM | d8 SkewT DM | d9 SkewT DM | Harvey pass? |
|------|----------------:|----------------:|----------------:|------------:|------------:|:-:|
| N225 | +2.32 | -1.92 | TBD | -1.33 | TBD | TBD |
| SPY  | +0.66 | -2.10 | TBD | -1.74 | TBD | TBD |

### 4.2 Verdict

*待 run 完成填入。例：`ROBUST_WITH_RECOVERY` / `PASS_N225_HARVEY_UNDER_CADENCE` / `NON_RECOVERY`.*

### 4.3 Paper 3 narrative 意涵

*根據 verdict 填入。可能方向*：
- 若 `ROBUST_WITH_RECOVERY`：d7 verdict `DIRECTION_CONSISTENT_ALL_BORDERLINE` 成立；d8 的 "skewed-t 不 help" 結論也成立。canonical innovation = Student-t，canonical cadence = refit_every=5。
- 若 `PASS_N225_HARVEY_UNDER_CADENCE`：Paper 3 narrative 升級，觸發 body rewrite decision（但仍需 ≥3 互補實驗）。
- 若 `NON_RECOVERY`：pivot 回 diagnostic mode，設計 k1100g_d10 專門驗證 d7 reproducibility（可能要加 k_restarts variation sweep）。

### 4.4 OOS SkewT 參數穩定性

*待 run 完成填入（針對 d8 Sec 5.2 的 "frozen warm-start" 警訊）*

## 5. 限制與 caveat

1. **Runtime 成本**：d7 cadence 比 d8 慢 ~6×（~60 refits → ~300 refits per OOS 迴圈）。實際 runtime 記錄在 results JSON。
2. **d9 與 d8 同 raw data + 同 TRAIN/TEST**：差別僅 refit cadence + n_restarts → 理論上 OOS forecast time series 不同，DM value 不同，但比較是控制變因的。
3. **DM(d9 vs d8) 是 descriptive delta**：d8/d9 forecast 同樣是 OOS expanding-window 但 cadence 不同；無法做正式 joint test。
4. **TAIFEX 未重跑**：d5 n=464 small-sample + d8 已未 test TAIFEX skewed-t；d9 維持此限制。
5. **yfinance daily OHLC only**：5-min intraday 只能回溯 ~60 日，無法覆蓋 15-year span。
6. **n_restarts 差異 confound**：d9 vs d8 同時改 refit_every（5 vs 25）**和** n_restarts_warm/cold（4/6 vs 2/4）。這是刻意對齊 d7 cadence，但意味著 d9 vs d8 delta 同時混合兩個 driver。未來 K1100g_d10 可做 2×2 ablation：(refit=5, restart=d7) / (refit=5, restart=d8) / (refit=25, restart=d7) / (refit=25, restart=d8)。

## 6. 衍生方向

- **K1100g_d10**：2×2 cadence × n_restarts ablation，分離 refit_every 與 n_restarts 的貢獻
- **K1100g_d11**：Winsorized gap² (1% / 5%)，測 COVID Mar 2020 極端 gap 對 DM stability 的貢獻
- **K1100g_d12**：加入 DAX / FTSE 提升 spatial coverage
- **Paper 3 body rewrite**：若 d9 確認 ROBUST_WITH_RECOVERY，narrative state machine 仍需第 4 個互補實驗才觸發 body rewrite

## 7. 檔案

- `k1100g_d9.py` — 主腳本（clone d8 + cadence 變更）
- `k1100g_d9_results.json` — 完整結果（含 point_estimates, CI, DM_stat_vs_d8, cadence_sensitivity_verdict）
- `k1100g_d9_cadence_sensitivity.png` — d7/d8/d9 DM 對比圖
- `k1100g_d9_skewt_param_stability.png` — OOS (η, λ) 時間序列（對 d8 Sec 5.2 frozen-param 警訊 verify）
- `data/n225_daily_2010-2026.parquet` → symlink to `../../k1100g_d8/data/`
- `data/spy_daily_2010-2026.parquet`  → symlink to `../../k1100g_d8/data/`
- `run.log` — 執行 log

## 8. 參考文獻

- **Hansen, B. E. (1994)** "Autoregressive Conditional Density Estimation", *IER* 35(3), 705-730
- **Jondeau & Rockinger (2003)** *JEDC* 27(10), 1699-1737
- **Bollerslev (1987)** *REStat* 69(3), 542-547 — Student-t GARCH
- **Engle & Rangel (2008)** *RFS* 21(3) — multiplicative τ×g PRG
- **Harvey, Leybourne & Newbold (1997)** *IJF* 13(2) — HLN DM correction
- **Harvey (2016)** *JF* — |t|>3 threshold

## 9. Seed 與可重現性

- `np.random.seed(42)` + `np.random.default_rng(42)`
- fitters 內 `local_rng = np.random.default_rng(42)` 建 restart 初值
- L-BFGS-B deterministic；warm-start from prev OOS refit
- yfinance cache symlink 自 d8，raw data 一致
- `_hansen_sanity_check()` 在 import time 強制執行
- 重跑應得到完全相同的 IS/OOS 結果到 4 位小數
