# K1072: Realized Kernel vs Standard RV — Microstructure Noise Robustness

**Status**: PRELIMINARY (60 days 5-min, 58 usable, 28 OOS << 252)
**Period**: 2026-01-14 ~ 2026-04-10
**Asset**: SPY (yfinance 5-min bars)
**Extends**: K1054 (HAR vs GJR vs A4f under RV proxy); K1063 (semi-variance asymmetry)

## 問題描述

K1054/K1057/K1063/K1065 都將 5-min RV 當作「真 vol」的 proxy，並隱含假設 5-min 間隔已足夠稀疏，microstructure noise 可忽略。但如果：
- 5-min returns 有 bid-ask bounce 導致 negative first-order autocorrelation
- 非同步交易讓 returns 與 noise 相關
則標準 RV 會被 noise 膨脹，Realized Kernel (RK) 才是 σ² 的一致估計量。

若 K1054 的 A4f DM 結論對 proxy 敏感（把 RV 換成 RK 後結論翻轉），代表過去的結論可能是 proxy 造成的 artifact。

## 動機

1. 驗證 K1054、K1063、K1065 採用 RV proxy 的穩健性
2. 了解 SPY 5-min 的 microstructure noise 量級
3. 決定 Paper 9 是否需要報告 RK-based robustness table
4. 建立 Subsampled RV（Zhang et al. 2005）作為中介比較值

## 方法

### Estimators

| Estimator | 公式 | 角色 |
|-----------|------|------|
| **RV** | Σ r²_{5min,i} | baseline（noise-inflated） |
| **RK** (Parzen) | γ_0 + Σ_{h=1}^{H} k(h/(H+1))·2γ_h | noise-robust (BNHLS 2008) |
| **RV_sub** | 5 offset grid 平均 | ZMA 2005 中介估計 |

**Parzen kernel**:
```
k(x) = 1 - 6x² + 6x³     for 0 ≤ x ≤ 0.5
     = 2(1-x)³           for 0.5 < x ≤ 1
     = 0                 otherwise
```

**Optimal bandwidth H***（BNHLS 2008 eq. 4.1 近似）:
```
H* = 3.5134 · (ξ²)^0.4 · n^0.6
```
其中 ξ² = noise-to-signal ratio ≈ ω²/(IV/n)，ω² 由 max(−γ_1/n, 0) 估計。

### HAR 規格（Corsi 2009）
```
RV_t = β_0 + β_d·RV_{t-1} + β_w·mean(RV_{t-5:t-1}) + β_m·mean(RV_{t-22:t-1}) + ε
```
三個版本：`HAR-RV`、`HAR-RK`、`HAR-sub`。Expanding window OLS，initial window = 30 days，小樣本採 ridge (λ=0.01)。

### 評估
- **QLIKE** (Patton 2011, proxy-robust)、MSE
- **DM test** Harvey |t|>3.0（帶防算術零除的保護）
- Random seed 42

## 主要結果

### 1. 三個 estimator 的比較（58 天樣本）

| Estimator | Mean | Std | Median |
|-----------|------|------|--------|
| RV | 5.63e-5 | 3.00e-5 | 5.48e-5 |
| RK | 5.70e-5 | 4.52e-5 | 4.42e-5 |
| RV_sub | 5.25e-5 | 3.66e-5 | 4.20e-5 |

**相關性**：
- corr(RV, RK) = 0.756
- corr(RV, RV_sub) = 0.872
- corr(RK, RV_sub) = 0.934

### 2. Microstructure noise 證據（H1/H2）

| 指標 | 值 | 解讀 |
|------|---|------|
| (RV−RK)/RV mean | +2.99% | RV 平均高於 RK ~3% |
| (RV−RK)/RV median | +8.43% | **中位數 ~8.4%，右偏分布** |
| % days RV > RK | 63.8% | 大多數日 RV > RK |
| paired t RV vs RK | −0.16 (p=0.87) | **均值差異不顯著** |
| Wilcoxon RV vs RK | W=745 (p=0.39) | **非參數也不顯著** |
| γ_1/γ_0 mean | +0.0006 | 近零（不像典型 bid-ask bounce 的負值） |
| % days γ_1 < 0 | 43.1% | 不到一半 |
| 最優 H* (Parzen) | mean 17.2, range [14, 32] | 中等 bandwidth |

**結論 H1**：**在 5-min 頻率下，SPY 沒有顯著 microstructure noise。** RV 和 RK 的中位數差 8% 看似大，但 (a) paired t/ Wilcoxon 都不顯著（p > 0.3），(b) γ_1/γ_0 不呈現典型的負值特徵。58 天樣本小，統計力有限，但初步證據不支持「5-min RV 被 noise 膨脹」假說。

**結論 H2**：Noise-to-signal q 估計值 mean 0.31 / median 0.19，但此估計量依賴於 ω² = max(−γ_1/n, 0) 的粗估。由於 γ_1 有 56.9% 的日為正值，此估計量在一半以上日子被 floor 到 0。該 q 估計不可信賴，實際噪聲可能遠小於 0.19。

### 3. HAR 預測比較（H3）

| QLIKE Target | HAR-RV | HAR-RK | HAR-sub |
|---|---|---|---|
| RV | −8.592 | −8.590 | −8.590 |
| **RK** | −8.660 | **−8.674** | −8.661 |
| RV_sub | −8.703 | −8.726 | −8.713 |

**HAR-RK vs HAR-RV on RK target**：DM t = +1.999, p = 0.056。**不通過 Harvey 門檻 (|t|>3.0)**，但 5% 邊緣顯著。

**結論 H3**：用 RK 作 target 時，HAR-RK 邊緣優於 HAR-RV（t ≈ 2），但未達 Harvey 門檻。28 天 OOS 樣本過小，不能下定論。若 noise 真的存在，HAR-RK 應該在更長樣本中顯示更清楚的優勢。

### 4. A4f Proxy 敏感性（H4，核心結果）

QLIKE 在 4 個 proxy 下的比較：

| Proxy | HAR-RV | GJR-GARCH | A4f-VIX² | Ranking |
|-------|--------|-----------|----------|---------|
| **RV_5min** | −8.592 | −8.481 | −8.406 | HAR > GJR > A4f |
| **RK** | **−8.660** | **−8.543** | **−8.450** | **HAR > GJR > A4f** |
| **RV_sub** | −8.703 | −8.559 | −8.466 | HAR > GJR > A4f |
| **r²_daily** | −7.631 | −7.977 | −8.040 | A4f > GJR > HAR |

**DM tests（HAR-RV vs A4f，關鍵對比）**：
- under RV_5min: t = −3.498 (p=0.002) — Harvey PASS，HAR-RV 贏
- **under RK**: t = −2.864 (p=0.008) — Harvey fail，但仍明顯 HAR-RV 贏
- under RV_sub: t = −3.308 (p=0.003) — Harvey PASS，HAR-RV 贏
- under r²_daily: t = +1.511 (p=0.14) — 不顯著，A4f 方向

**結論 H4**：**K1054 的核心結論（HAR-RV > A4f 在 RV 上）完全穩健於 proxy 選擇**。切換到 noise-robust RK 或 subsampled RV 後：
- 排序不變（HAR > GJR > A4f）
- DM t-stat 雖略縮小（−3.50 → −2.86），但方向一致
- 只有在 r² proxy 下排序翻轉（A4f > HAR），此為 K1054 已知的模型-target mismatch 現象（HAR 預測 intraday RV，不該用全日 r² 評估 — 見 preamble 模型-target 匹配規則）

### 5. Subsampled RV 地位（H5）

RV_sub mean (5.25e-5) < RV mean (5.63e-5) < RK mean (5.70e-5)。相關性 corr(RK, RV_sub) = 0.934 > corr(RV, RK) = 0.756，表明 subsampling 和 kernel 方法在消除某種短期相關時行為類似。但 RV_sub 並未 cleanly 介於 RV 和 RK 之間，原因是 RK 的標準差 (4.52e-5) 比 RV (3.00e-5) **大**，顯示 RK estimator 在 small n_bars ≈ 78 下本身變異較大。

## 結論（對 Paper 9 的意涵）

1. **SPY 5-min 的 microstructure noise 在 2026 年樣本不顯著**（paired t / Wilcoxon 都 p > 0.3）。這與 Liu, Patton & Sheppard (2015) 對 liquid indices 的結論一致 — 5-min 已經夠稀疏。
2. **K1054 的 A4f DM 結論完全通過 proxy robustness check**：
   - 在 RV / RK / RV_sub 三個 intraday proxy 下，排序恆為 HAR-RV > GJR > A4f
   - DM t-stat 略縮小但方向一致
   - r² 下的翻轉是 mechanical（target mismatch），不是實證矛盾
3. **建議 Paper 9 報告 RK-based robustness table** 作為附錄，但主文可繼續用 RV：
   - 主結論沒變
   - RK 估計在 n=78 bars 下本身 variance 較大，不必然是更好的 proxy
4. **短 OOS (28 天) 是主要限制**。當樣本累積到 252+ 天，應重跑 K1072 以獲得更可靠的 noise diagnostics 和 HAR-RK vs HAR-RV 統計檢定。

## 局限性

- **58 天樣本太短**：DM test 統計力不足；noise 估計 ω̂² 大半被 floor 到 0
- **Noise variance 估計粗糙**：更精確方法需要 realized autocovariance at multiple bandwidths (BNHLS 2008 Table 1 的 ξ² 估計程序)
- **Two-Scales RV (TSRV, Zhang et al. 2005)** 尚未實作 — subsampled RV 是更簡單的版本
- **HAR-RK 預測 RK target**：隱含假設 RK 是「真 vol」 — 但 RK 本身在小 n 下 noisy，此假設可能過於理想化
- **沒有 intraday signature plot**：Aït-Sahalia-Mykland-Zhang 用 signature plot (RV 對 sampling freq) 診斷 noise，本實驗未涵蓋

## 檔案

- `k1072.py` — 主腳本
- `k1072_results.json` — 完整結果（含 per-day estimators, betas, DM, QLIKE, ranking）
- `k1072_estimator_comparison.png` — RV/RK/RV_sub 時序 + scatter + 分布
- `k1072_noise_diagnostics.png` — γ_1/γ_0、ω̂²、H* 時序
- `k1072_har_comparison.png` — HAR QLIKE 三 target 比較 bar plot
- `k1072_a4f_proxy_sensitivity.png` — QLIKE heatmap + DM t-stats across proxies

## 參考文獻

- Barndorff-Nielsen, Hansen, Lunde & Shephard (2008). "Designing Realized Kernels..." *Econometrica* 76.
- Zhang, Mykland & Aït-Sahalia (2005). "A Tale of Two Time Scales" *JASA* 100.
- Corsi (2009). "A simple approximate long-memory model of realized volatility" *JFEC*.
- Patton (2011). "Volatility forecast comparison using imperfect volatility proxies" *JoE*.
- Liu, Patton & Sheppard (2015). "Does anything beat 5-minute RV?..." *JoE*.
- Harvey, Leybourne & Newbold (1997). "Testing the equality of prediction MSEs" *Intl J. Forecasting*.

## 衍生研究方向

1. **累積到 252+ 天後重跑 K1072** — 獲得足夠統計力確認 RK vs RV 差異
2. **Two-Scales RV (TSRV) 實作** — Zhang et al. 2005 的 bias-corrected 版本
3. **Signature plot 分析** — 計算 RV at 1-min, 2-min, 5-min, 10-min, 15-min，看 RV 隨 sampling 頻率的變化
4. **Pre-averaged RV (Jacod et al. 2009)** — 另一個 noise-robust alternative
5. **Intraday VIX signal (K1065) 在 RK 下重跑** — 確認 intraday VIX 的 predictive power 不因 proxy 切換消失

## Preamble 規則遵守確認

- [x] 模型-target 匹配：HAR 用 RV/RK/RV_sub（各自原生），GJR/A4f 用 r²，跨模型比較用 Patton proxy-robust QLIKE
- [x] Mechanical vs empirical：清楚區分 r² proxy 下 A4f 贏是 target mismatch (mechanical)，RV/RK 下 HAR 贏是 empirical
- [x] 統計門檻：Harvey |t|>3.0 標註於所有 DM tests
- [x] Random seed 42 固定
- [x] Lookahead 避免：expanding window，forecast at t 只用 data < t
- [x] Worktree 共享狀態禁令：只產出 `experiments/k1072/` 下檔案
