# K1426 — Partial Cointegration Hedging (PCH) — IS-only PoC

## 動機

`research_program.md` backlog 列出 "Partial Cointegration Hedging — RQFA 2023"
（Poulos, Curphey & Williams 2024 RQFA）。Clegg & Krauss (2018) Quantitative
Finance 提出將 pair spread 分解為 AR(1) mean-reverting (M_t) + random walk (R_t)
兩成分的 state-space 模型，使 hedge ratio 估計同時容納長期偏離與短期均值回歸；
與本平台用戶（賴奕豪副教授）長期 hedging 研究線（PRS、copula-GARCH hedging）
互補。

K1426 是 IS-only proof of concept：驗證 (a) 自寫 Kalman + multistart MLE 收斂、
(b) PCH hedge effectiveness 是否與經典 OLS / EG-VECM hedge 可比、(c) 對哪類
pair 結構 PCH 才有意義（R²_MR gate）。OOS rolling-window + bootstrap CI 留
給 compute_queue 接手。

## 文獻（詳見 `references.md`）

1. **Clegg & Krauss (2018)** — Pairs trading with partial cointegration. *Quantitative Finance*, 18(1), 121–138. — canonical PCH state-space formulation
2. **Poulos, Curphey & Williams (2024)** — Empirical asset pricing via partial cointegration. *Review of Quantitative Finance and Accounting*, 62(3), 1031–1061. — R²_MR diagnostic + cross-sectional asset pricing 應用
3. **Lien (2004)** — Cointegration and the optimal hedge ratio: the general case. *Quarterly Review of Economics and Finance*, 44(5), 654–658. — 經典 OLS vs ECM hedge 比較 baseline

## 方法

### 模型
觀測（log price）關係：

    log_x_t = mu + beta * log_y_t + M_t + R_t
    M_t = rho * M_{t-1} + eps_M,t,   eps_M ~ N(0, sigma_M^2)   (mean-reverting AR(1))
    R_t = R_{t-1} + eps_R,t,         eps_R ~ N(0, sigma_R^2)   (random walk)

### 估計
- **Kalman filter** on residual `log_x_t − mu − beta·log_y_t`，狀態 `(M_t, R_t)`
- **MLE**：`scipy.optimize.minimize` L-BFGS-B 最小化 −loglik
- **rho** 經 `tanh()` reparameterization 確保 |rho| < 1
- **sigma_M, sigma_R** 經 `log()` reparameterization 確保正定
- **Multistart**：seed=42 隨機初始化（per pooled-MLE 硬規則）
  - Pair 1 (SPY/IVV)：100 multistarts（完整 spec）
  - Pair 2 (USO/BNO), Pair 3 (GLD/IAU)：20 multistarts（時間 cap 下的 scope cut，
    full 100-start 由 compute_queue followup 補）

### Baselines
- **OLS static hedge**：`log_x = mu + beta_OLS·log_y + eps`
- **EG-VECM**：Stage-1 OLS → Stage-2 ECM 估速度調整參數 alpha

### Diagnostics & honesty gate
- **R²_MR** = σ²_M / (σ²_M + σ²_R) — mean-reverting variance share
- **Half-life** = −log(2) / log(rho) days
- **Hedge effectiveness (HE)** = 1 − Var(Δspread) / Var(Δlog_x)
- **Gate**：rho ≥ 0.999 或 R²_MR < 0.05 → 報 NULL（PCH 退化為純 random walk）

### Lag / Lookahead
本實驗為 hedge ratio 估計（IS variance reduction），非 directional strategy；
OLS / EG-VECM / PCH 都對同一日的 `(log_x_t, log_y_t)` 做 contemporaneous
regression，spread 由同期 residual 構成。三 estimator 採對稱 IS 口徑（symmetric
refinement 規則延伸），沒有 lookahead 不對等性。隨機數均固定 `seed=42`。

## 資料

- Source: `yfinance` daily adjusted close, 2015-01-01 — 2024-12-31
- Pairs:
  - **Pair 1**: SPY / IVV — 重複指數 ETF（S&P 500），預期高度 cointegrated 與
    高 HE（economically duplicate）；作為 PCH 收斂正確性 sanity check
  - **Pair 2**: USO / BNO — WTI vs Brent oil ETFs，預期 partial cointegration
    最有意義的 pair（兩種原油有結構性 spread）
  - **Pair 3**: GLD / IAU — 重複黃金 ETF，類 Pair 1 sanity check
- 內部 log-price，inner join 對齊日期

## 結果

**Overall verdict: NULL**（3/3 pairs 落在 honesty gate 內）。詳見
`k1426_results.json`。

| Pair | β_OLS | β_PCH | ρ | R²_MR | half-life | HE_OLS | HE_PCH | Verdict |
|---|---|---|---|---|---|---|---|---|
| SPY/IVV | 0.998 | 0.996 | −0.198 | 0.813 | inf | 0.998 | 0.998 | NULL_RHO_NEGATIVE |
| USO/BNO | 0.424 | 1.008 | −0.401 | 0.070 | inf | 0.590 | 0.887 | NULL_RHO_NEGATIVE |
| GLD/IAU | 0.982 | 0.998 | 0.053 | 0.990 | 0.24d | 0.994 | 0.994 | NULL_HALFLIFE_TRIVIAL |

### Honesty gates applied
1. **ρ ≥ 0.999** → PCH degenerates to pure RW (none triggered)
2. **R²_MR < 0.05** → M component negligible (none triggered)
3. **ρ ≤ 0** → AR(1) oscillates, not mean-reverts → SPY/IVV, USO/BNO 都中
4. **half_life < 1 day** → "mean reversion" indistinguishable from i.i.d. noise → GLD/IAU 中

### Methodological honesty notes
- **Pair 2 (USO/BNO) HE_PCH = 0.887 vs HE_OLS = 0.590 is _not_ evidence of PCH
  improvement**: PCH chose β = 1.008 while OLS chose β = 0.424. The two
  spreads are on **different scales** and HE values are not directly
  comparable. PCH's choice essentially enforces a 1:1 oil-benchmark
  relationship while OLS fits the minimum-variance hedge — these are
  different decompositions of the data, not the same hedge with different
  estimators. The Clegg-Krauss canonical interpretation of PCH _requires_
  the cointegrating β to be near the long-run economic equilibrium, but
  the ρ ≤ 0 result says the AR(1) component isn't economically
  mean-reverting anyway, so this "HE gain" is an artifact of decomposition
  scale, not partial cointegration.
- **Pair 1 & 3 (duplicate ETFs)** as sanity checks: OLS β ≈ 1, HE > 0.99
  matches economic prior (duplicate ETFs ⇒ near-perfect hedge). PCH adds
  no structural value (ρ negative for SPY/IVV, half-life trivial for GLD/IAU).

### Interpretation
On these three pairs, with 2015-2024 daily data, PCH's mean-reverting
component is **not identified as a persistent economic mean-reverting
structure** under the Clegg-Krauss canonical interpretation. This does
**not** invalidate PCH as a methodology — it indicates that:
(a) duplicate-ETF pairs have spreads too close to zero for state-space
identification, and
(b) WTI vs Brent (USO/BNO) under 2015-2024 (including 2020 oil shock)
has a spread dynamic dominated by random walk + noise rather than
persistent mean reversion.

The result is consistent with Poulos et al. (2024) finding that "many
pairs degenerate to R²_MR ≈ 0 (pure random walk)" — even when R²_MR is
high (our Pair 1 R²_MR = 0.81), the ρ may be uninformative.

### Figures
`figures/`:
- `fig_{pair}_spread.png` — 三 estimator spread 時序疊圖
- `fig_{pair}_decomp.png` — PCH Kalman-filtered M_t / R_t 狀態分解

## 限制 / Caveats

1. **IS-only** — 無 OOS rolling-window 驗證；in-sample HE 是 upper bound。
2. **Pair 2/3 用 20-start MLE** — 為了在 50min cap 內收尾；full 100-start 留
   compute_queue（多 start 可能找到更高 loglik 的 basin，數字會微調但量級不變）。
3. **未做 Codex code review** — worktree agent 環境限制；主線程 verify 後再
   寫 `knowledge.json`（K1259 process gate）。
4. **重複 ETF pair（SPY/IVV、GLD/IAU）HE 接近 1 是經濟結構必然，不是 bug**
   — 它們追蹤同 underlying；這兩 pair 主要用來 sanity-check PCH 收斂與 MLE
   不發散。USO/BNO 是真正的鑑別 pair。
5. **未做 statsmodels coint test 對照** — 自寫 MLE 已是按方法論硬規則（套件
   不支援 PCH state-space → 必自寫），不再額外跑套件。

## OOS 結果（2026-07-17 收尾）— NULL：PCH 對報酬避險無增益

上節「OOS 後續方向」第 2-4 點已執行完畢（`oos.py`，分 3 個 shard 跑完 6 pairs，
`merge_shards.py` 合併為 `k1426_oos_results.json`）。**結論是 null result：PCH 相對
於一個兩行的報酬迴歸沒有任何增量價值。**

### 表面結果（對照組 = levels OLS）

判準：block-bootstrap 95% CI 排除 0 **且** DM |t| > 3.0（Harvey 多重檢定門檻）。

| pair | HE_ols | HE_pch | diff | boot 95% CI | DM t | 判定 |
|---|---|---|---|---|---|---|
| SPY/IVV | 0.9981 | 0.9983 | +0.0002 | [0.0000, 0.0004] | −1.36 | null（t 未過） |
| USO/BNO | 0.8044 | 0.8835 | +0.0791 | [0.0562, 0.1155] | −6.70 | 兩 gate 皆過 |
| GLD/IAU | 0.9948 | 0.9951 | +0.0003 | [0.0001, 0.0005] | −3.13 | 兩 gate 邊際過（diff 僅 +0.0003，見下） |
| GLD/SLV | 0.2405 | 0.6027 | +0.3622 | [0.2407, 0.5125] | −6.53 | 兩 gate 皆過 |
| XLE/USO | 0.2950 | 0.3581 | +0.0632 | [−0.0144, 0.1240] | −1.44 | null（CI 含 0） |
| XLF/XLK | 0.4869 | 0.4411 | −0.0458 | [−0.0974, −0.0169] | +3.91 | PCH 顯著**較差** |

若停在這裡，會得出「PCH 在多個 pairs（USO/BNO、GLD/SLV 大幅，GLD/IAU 邊際）顯著勝出」
的結論。**那是錯的。**

### 為什麼表面結果不成立

`fit_ols_hedge`（`k1426.py:251`）是在 log **價格水準**上回歸，得到的是共整合 beta；
`oos.py:200` 卻把該 beta 拿去避險**日報酬**。水準 beta 不是報酬變異數最小化的 beta，
所以這個對照組沒有被 scored 的損失函數所最適化。報酬避險的正確對照組是
**報酬對報酬的迴歸 beta**。

`oos_return_benchmark.py` 用**完全相同**的 OOS 協定（擴張窗、min_train=756、
refit_every=63、beta 由 `[:i]` 訓練後套用到 i−1→i 的報酬）補上這個對照組。
其 levels-OLS 逐字複製了原始數字（`levels_beta_replicates_merged=true`）、
OOS 樣本數相符（`sample_matches_merged=true`），故比較有效：

| pair | beta_PCH | beta_報酬OLS | 差 | HE_PCH | HE_報酬OLS | 差 |
|---|---|---|---|---|---|---|
| SPY/IVV | 0.9951 | 0.9880 | 0.0072 | 0.9983 | 0.9982 | 0.00012 |
| USO/BNO | 1.0009 | 0.9976 | 0.0033 | 0.8835 | 0.8834 | 0.00002 |
| GLD/IAU | 0.9972 | 0.9943 | 0.0029 | 0.9951 | 0.9951 | 0.00003 |
| GLD/SLV | 0.4414 | 0.4413 | 0.0001 | 0.6027 | 0.6027 | 0.00001 |
| XLE/USO | 0.4556 | 0.4573 | −0.0016 | 0.3581 | 0.3579 | 0.00025 |
| XLF/XLK | 0.7261 | 0.7269 | −0.0008 | 0.4411 | 0.4405 | 0.00053 |

**PCH 的 beta 就是報酬迴歸 beta**（GLD/SLV 差 0.0001），HE 差距全部 ≤ 0.0005 —— 
相對於 GLD/SLV 那個 +0.3622 的標題數字等於零。PCH 的 levels likelihood 恰好回收了
報酬最適 beta，而對照組用了不適合該任務的水準 beta；「勝出」全部來自這個落差，
與 partial cointegration 機制無關。

XLF/XLK 的反向證據同樣支持這個解釋：PCH 在該對「輸」給 levels OLS，而報酬 OLS
也一樣輸（0.4405 vs 0.4869）—— 那對的水準 beta 只是 OOS 碰巧較好。決定 HE 的
是「用哪個 beta」，不是「有沒有 PCH」。

機制診斷與此一致：兩個「勝出」pair 的均值回歸成分幾乎不存在
（USO/BNO：mean_rho = −0.374、R²_MR = 0.072；GLD/SLV：rho = 0.216、R²_MR = 0.116）。
負 rho 是振盪而非均值回歸，PCH 實質退化為 random walk + noise。

### 配對檢定：return-OLS vs PCH（2026-07-27 補齊）

原殘留（return-OLS vs PCH 只有點估計、GLD/IAU 資料缺）已解決：daily-series-persistence
patch 下 3 個 shard（6 pairs）全部重跑，每 pair 都持久化了逐日 PCH 避險報酬序列，
`oos_return_benchmark.py` 因此能對每 pair 算出**配對** DM + block-bootstrap（1000 reps,
block_len=20, seed=42），寫入 `paired_return_ols_vs_pch`（n_common=1759/pair）。數字直接
讀自 `k1426_oos_return_benchmark.json`：

| pair | HE_報酬OLS | HE_PCH | diff(報酬OLS−PCH) | 配對 DM \|t\| | boot 95% CI | CI 跨 0？ |
|---|---|---|---|---|---|---|
| SPY/IVV | 0.99822 | 0.99834 | −0.00012 | 7.66 | [−0.00019, −0.00007] | **否** |
| USO/BNO | 0.88345 | 0.88346 | −0.00002 | 0.05 | [−0.00043, +0.00044] | 是 |
| GLD/IAU | 0.99507 | 0.99510 | −0.00004 | 1.45 | [−0.00008, +0.00001] | 是 |
| GLD/SLV | 0.60266 | 0.60267 | −0.00001 | 0.32 | [−0.00010, +0.00007] | 是 |
| XLE/USO | 0.35790 | 0.35811 | −0.00021 | 0.42 | [−0.00140, +0.00067] | 是 |
| XLF/XLK | 0.44053 | 0.44103 | −0.00050 | 5.26 | [−0.00080, −0.00033] | **否** |

**判決：NULL confirmed（未翻轉）。** 六對的點估計 HE 差全部 |diff| ≤ 0.0005（最大 XLF/XLK
0.00050），量級與先前點估計一致 —— PCH 的 levels-likelihood beta 恰好回收報酬最適 beta，
標題那個 GLD/SLV +0.3622 完全來自對照組用錯 beta，與 partial cointegration 無關。

honesty note（不粉飾）：4/6 pairs 如預期 DM |t| 偏小且 CI 跨 0（統計上無法區分）；但
**SPY/IVV（|t|=7.66）與 XLF/XLK（|t|=5.26）配對 DM 顯著、CI 排除 0**。這兩對的差異是
「統計顯著、經濟為零」的教科書情形：HE 差僅 0.00012 與 0.00050（皆 ≤0.0005 的 null 尺度），
方向是 PCH 微幅較佳。以「無增量價值」的經濟判準看，可被統計偵測到的 ≤0.0005 HE edge
不足以推翻 null，反而印證 +0.36 標題塌縮至零。**整體 NULL 判斷不變。**

### 判定與後續

- **K1426 OOS = NULL**：PCH 對報酬避險相對報酬 OLS 無增量價值。
- **Multivariate PCH 不排入 queue**（原第 5 點）。在 PCH 能勝過報酬 OLS 之前，
  把它擴到 3+ assets 只是把一個無增益的方法變複雜。門檻應為：先在單 pair 上
  對報酬 OLS 顯示增益，才談 multivariate。
- ~~已知殘留：GLD/IAU 資料缺、return-OLS vs PCH 只有點估計而無配對檢定~~
  **已於 2026-07-27 解決**（daily-series-persistence patch 重跑 3 shard → 每 pair 持久化
  逐日 PCH 避險報酬序列）：GLD/IAU 已補齊資料，六對皆有配對 DM + block-bootstrap
  （見上「配對檢定」節）。配對後 null 判定不變（|diff| ≤0.0005；2 對統計顯著但經濟為零）。

### Codex 審查

`oos_return_benchmark.py` 經 codex exec 審查：lookahead PASS（beta 僅用 `[:i]`，
`np.diff(train_x)` 最後一筆為 log_x[i−1]−log_x[i−2]，無洩漏）、公平比較 PASS
（同訓練窗/同 refit 節奏/同 OOS 觀測/HE 同 ddof=1）。Codex 對本文主張的收斂修正
已採納：levels OLS 作為「共整合估計量 vs 共整合估計量」的控制組**仍有效**
（PCH 本身也從 levels likelihood 估 beta），故不宜稱其為全然的 straw man；
準確結論是**它不足以支持 return-hedging superiority 的宣稱**。

### spec 修正

shard notes 寫「Monthly (21-day) refit cadence」與 `spec.refit_every=63`（季度）矛盾。
`merge_shards.py` 以 spec 為準（那是代碼實際消費的值）並在合併輸出中更正該註記。
`oos.py` 的 docstring 與 metadata note **已更正**（2026-07-27）：refit cadence 現寫
63 日/quarterly、n_starts=50、line-345 的 `lookahead_rule` 為
「Train on [:t-1], apply hedge beta to return t via shift(1).」，reproducibility metadata
與代碼實際消費值一致。

## OOS 後續方向（→ compute_queue followup brief）

> ⚠️ 下列為 2026-06-09 撰寫的原始方向；第 2-4 點已於 2026-07-17 執行完畢並得出
> null（見上節），第 5 點 multivariate 已依該結論**否決**。保留供脈絡。

1. **Pair 2/3 full 100-multistart PCH** — 確認 loglik basin
2. **OOS rolling-window** — expanding window 估 (beta, rho)，shift(1) 後計算
   OOS HE
3. **Bootstrap CI** — block bootstrap 1000 reps 計 HE_PCH − HE_OLS 的 95% CI +
   Patton-style DM 等價檢定
4. **Cross-pair generalization** — 加 commodity pairs（GLD/SLV, XLE/USO,
   XLF/XLK）測 R²_MR 跨資產類別行為
5. **Multivariate extension** — 對 3+ assets 擴 PCH 為 multivariate state-space
   (cf. Poulos 等 2024 cross-sectional setup)

## 復現

```
uv run python experiments/k1426/run_fast.py
```

或完整 100-start spec（pair 2/3 也跑 100）：

```
uv run python experiments/k1426/k1426.py
```

（後者預計 ~15-25min，前者 ~3-5min）

## 三件套 + 附件

- `README.md` — 本檔
- `k1426.py` — PCH/Kalman/MLE/baseline canonical implementation
- `run_fast.py` — scope-cut runner（pair 2/3 用 20-start MLE）
- `k1426_results.json` — 數字結果（in-sample）
- `oos.py` — OOS 擴張窗 runner（分 shard 執行）
- `k1426_oos_shard_{a,b,c}.json` — 3 個 shard 的原始輸出（parent job 6h timeout 後拆分）
- `merge_shards.py` — shard 合併（idempotent）
- `k1426_oos_results.json` — 合併後 OOS 結果
- `oos_return_benchmark.py` — 報酬迴歸對照組（推翻表面 OOS 結論的關鍵檢查）
- `k1426_oos_return_benchmark.json` — 對照組結果
- `figures/` — spread 比較 + state decomposition 圖
- `references.md` — 3 篇文獻 APA + DOI + 核心 quote
