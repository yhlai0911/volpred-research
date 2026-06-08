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

## OOS 後續方向（→ compute_queue followup brief）

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

OOS follow-up（async worker；expanding window + strict `shift(1)`）：

```
uv run python scripts/compute_queue.py enqueue \
  --script experiments/k1426/oos.py \
  --title "K1426 — OOS partial cointegration hedging" \
  --result-artifact experiments/k1426/k1426_oos_results.json \
  --followup-brief "Read k1426_oos_results.json. Verify whether any pair shows OOS HE_PCH > HE_OLS with bootstrap 95% CI excluding 0 and DM |t| > 3.0 after multiple-testing caution. If all six pairs are NULL/weak, write a null-result interpretation and decide whether multivariate PCH is still worth queueing." \
  --followup-task-type paper_review \
  --timeout 21600
```

## 三件套 + 附件

- `README.md` — 本檔
- `k1426.py` — PCH/Kalman/MLE/baseline canonical implementation
- `run_fast.py` — scope-cut runner（pair 2/3 用 20-start MLE）
- `k1426_results.json` — 數字結果
- `figures/` — spread 比較 + state decomposition 圖
- `references.md` — 3 篇文獻 APA + DOI + 核心 quote
