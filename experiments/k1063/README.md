# K1063: Realized Semi-Variance — Upside vs Downside Asymmetry Decomposition

**Status**: PRELIMINARY (60-day sample, 30 OOS days — far below 252-day threshold)
**Data**: SPY 5-min, 2026-01-14 ~ 2026-04-10 (60 trading days)
**Seed**: 42
**Proposer**: Claude (autonomous research queue) · Executor: Claude

## 1. 問題描述與動機

Barndorff-Nielsen, Kinnebrock & Shephard (2010) 指出 realized variance 可以依據
intraday return 正負號分解為兩個 semi-variance：

```
RV   = Σ r_i²
RV+  = Σ r_i² · 1{r_i > 0}        （upside / "good" variance）
RV-  = Σ r_i² · 1{r_i < 0}        （downside / "bad" variance）
SJ   = RV+ − RV−                  （signed jump variation）
```

Patton & Sheppard (2015, REStat) 實證發現：**下行半變異數 RV- 對未來波動率有
更強的預測力**，因為 leverage effect（負報酬帶來更多未來波動）在日內尺度延伸。

### 與先前實驗的區別

| K 編號 | 分解方式 | 結論 |
|--------|---------|------|
| K1054 | 無分解（HAR-RV 基準）| 60 天訓練不足，A4f-VIX 勝 |
| K1057 | RV = C + J（jump vs continuous, BNS 2006）| Jump 不可預測（ACF=-0.056）, 分解無預測價值 |
| **K1063** | **RV = RV+ + RV−（signed）** | **本實驗**：測試不同的分解軸——方向性 vs 極端性 |

K1057 測「極端 vs 平穩」（null），K1063 測「上行 vs 下行」，**預期會有不同結果**
因為 leverage effect 是已被廣泛記錄的實證規律。

## 2. 研究問題

1. **對稱性**：平均而言 RV+ 與 RV- 是否相等？
2. **持續性差異**：ACF(RV+) vs ACF(RV-) — 哪一個更 predictable？
3. **回歸係數不對稱（H1）**：HAR-SV 中 β(RV-) > β(RV+)？是否達 Harvey |t|>3.0？
4. **預測力**：HAR-SV / HAR-RV-down / HAR-LL 是否勝 HAR-RV（DM test）？
5. **Signed jump**：SJ 在 HAR 架構中有增量預測力嗎？
6. **跨模型公平比較**：相對 GJR-GARCH 與 A4f-VIX²（Patton 2011 r² 代理）如何？

## 3. 方法

### Part A: 描述與診斷
- 計算 60 個交易日 RV / RV+ / RV- / SJ
- 分解恆等式驗證：`|RV − (RV+ + RV−)|` 應為機器精度
- ACF at lag 1, 5, 22
- 對稱性 paired t-test（RV+ vs RV-）
- Leverage：corr(r_t, RV−_{t+1} − RV+_{t+1})

### Part B: 5 種 HAR 變體（expanding-window OLS，initial 30 天）

| 模型 | 預測方程 |
|------|---------|
| **HAR-RV** (baseline) | β₀ + β_d·RV_{t−1} + β_w·RV_w + β_m·RV_m |
| **HAR-SV** | β₀ + β⁺·RV⁺_{t−1} + β⁻·RV⁻_{t−1} + β_w·RV_w + β_m·RV_m |
| **HAR-RV-SJ** | β₀ + β_d·RV_{t−1} + β_sj·SJ_{t−1} + β_w + β_m |
| **HAR-RV-down** | β₀ + β_d·RV⁻_{t−1} + β_w·RV⁻_w + β_m·RV⁻_m |
| **HAR-LL** | β₀ + β_d·RV_{t−1} + β_lev·RV⁻_{t−1} + β_w + β_m |

**Target**：RV_t（all-HAR native）
**Evaluation**：QLIKE、MSE、MAE 在 **RV proxy（native）** 和 **r² proxy（Patton 2011 fair）**
**Significance**：Diebold-Mariano test with Newey-West HAC；Harvey (2016) |t|>3.0

### Part C: 跨模型基準
- **GJR-GARCH(1,1,1)**：rolling window=2000, normal innovation
- **A4f-VIX²**：VIX²_{t−1}/252 as daily variance

## 4. 主要結果

### (1) 分解結構 — **對稱性不明顯**

| 統計量 | RV | RV+ | RV- | SJ |
|--------|-----|-----|-----|-----|
| Mean | 5.47e-05 | 2.79e-05 (51.1%) | 2.68e-05 (48.9%) | 1.16e-06 |
| Skew | — | — | — | — |

**Paired t-test RV+ vs RV-**: t=+0.585, p=0.561 → **cannot reject symmetry** on average.

### (2) ACF — **最強不對稱證據**

| 序列 | lag 1 | lag 5 | lag 22 |
|------|-------|-------|--------|
| RV | +0.284 | +0.039 | +0.106 |
| **RV+** | **+0.059** | −0.050 | +0.092 |
| **RV−** | **+0.390** | **+0.173** | +0.017 |
| SJ | −0.237 | +0.008 | −0.104 |

**RV− 的 AR(1) 是 RV+ 的 6.6 倍**（0.390 vs 0.059）。
**RV+ 幾乎是 white noise，RV− 是可預測的核心。**

### (3) Leverage Effect — **符號與預期相反？**

- corr(r_t, RV−_{t+1}) = **−0.286**（負，預期正，因為負報酬後應有更多下行波動；**這裡是全期的 r_t，包含正負報酬**，負相關代表 |r_t| 大的正報酬也帶來下行波動——也就是 vol-of-vol 而非嚴格 leverage）
- corr(r_t, RV+_{t+1}) = **−0.328**
- corr(r_t, RV−_{t+1} − RV+_{t+1}) = **+0.137**（弱正相關；這正是 leverage 在 signed jump 上的殘餘）

此樣本 60 天太短，leverage effect 不顯著。**標準正確方向**（Patton-Sheppard 用 2000+ 天獲得強信號）。

### (4) 回歸係數不對稱（H1）

全樣本 HAR-SV OLS 估計：

| 係數 | 估計 | t-stat |
|------|------|--------|
| intercept | +1.86e-05 | +1.24 |
| **β⁺ (RV+_d)** | **−0.381** | **−1.51** |
| **β⁻ (RV−_d)** | **+1.181** | **+3.63** |
| β_w (RV_w) | −0.292 | −0.85 |
| β_m (RV_m) | +0.613 | +1.38 |

**Contrast test H1: β⁻ = β⁺**:
- β⁻ − β⁺ = **+1.562**
- SE = 0.503, **t = +3.103**, p = **0.003**
- **Harvey |t|>3.0 threshold met (borderline, t=3.10)** → **H1 SUPPORTED**

**解讀**：在 60 天樣本中，下行半變異數每多一單位，下一日 RV 增加 1.18 單位；
而上行半變異數係數**甚至為負**（雖不顯著），顯示 RV+ 的資訊價值幾乎是零。

### (5) OOS 預測力（DM test，n=30）

#### RV proxy（HAR native target）

| 模型 | QLIKE | vs HAR-RV (DM t) | 意義 |
|------|-------|------------------|------|
| **HAR-RV-down** | **−8.622** | **−2.99 \*\*** | 邊緣顯著勝 baseline（未達 Harvey |t|>3.0）|
| HAR-SV | −8.612 | −0.83 | 不顯著 |
| HAR-RV-SJ | −8.612 | −0.83 | 不顯著（= HAR-SV 重參數化）|
| HAR-LL | −8.612 | −0.83 | 不顯著（= HAR-SV 重參數化）|
| HAR-RV | −8.597 | — | baseline |
| GJR-GARCH | −8.504 | — | — |
| A4f-VIX² | −8.074 | — | — |

> HAR-SV、HAR-RV-SJ、HAR-LL 的 OOS QLIKE 完全相同，因為它們是對相同 4 個 regressor
> `{RV+, RV−, RV_w, RV_m}` 的**線性重參數化**（RV=RV+ + RV−, SJ=RV+ − RV−）。
> 這是機械上的必然（mechanical），不是發現。

#### r² proxy（Patton 2011 fair comparison）

| 模型 | QLIKE |
|------|-------|
| GJR-GARCH | −8.070 |
| A4f-VIX² | −7.895 |
| **HAR-RV-down** | **−7.802** |
| HAR-RV | −7.774 |
| HAR-SV | −7.748 |

**在 r² 上 GJR-GARCH 勝所有 HAR**，但沒有任何 pairwise DM test 達到顯著：
- HAR-SV vs HAR-RV: t=+0.31
- HAR-RV vs GJR-GARCH: t=+1.15
- **所有 DM t-stat | | < 2，無任何對拍達統計顯著**

排名**跨 proxy 不一致**（RV 上 HAR 系列贏，r² 上 GARCH 系列贏），印證 Patton (2011):
target 匹配規則——HAR 本來就是為了 RV 設計的。

## 5. 結論

1. **分解恆等式驗證通過**：|RV − (RV+ + RV−)| ≈ 4e-20（機器精度）
2. **RV+/RV- 在 level 上對稱**（paired t p=0.561），**但在 persistence 上高度不對稱**
   （RV- AR(1)=0.39，RV+ AR(1)=0.06）。這是此實驗最確定的發現。
3. **β⁻ > β⁺ 達 Harvey 門檻（t=3.10, p=0.003）**。H1 SUPPORTED（borderline）。
4. **HAR-RV-down 在 RV proxy 上邊緣勝 HAR-RV**（DM t=-2.99, 未達 |t|>3.0）。
5. **跨 proxy 檢驗**（r²）下所有 HAR 變體與 baseline HAR-RV 無顯著差異。
6. **Signed jump SJ 無增量預測力**（HAR-SV = HAR-RV-SJ = HAR-LL，重參數化）。
7. **與 K1057 對比**：signed 分解（RV+/RV-）比 jump 分解（C/J）稍有訊息，
   但在 60 天小樣本下**邊緣**且**target-dependent**，不改寫前人結論。

## 6. 限制（必讀）

- **樣本極小**：60 天訓練、30 天 OOS。遠低於 Patton-Sheppard 原文 2000+ 天。
- **Sharpe/DM 結論不可外推**。60 天內恰巧缺少明顯的 leverage 事件。
- **僅 SPY**：未跨市場驗證（0050.TW 5-min 不足 60 天）。
- **正負重參數化等價**：本實驗發現 HAR-SV / HAR-RV-SJ / HAR-LL 同時使用
  `{RV+, RV−}`、`{RV, SJ}`、`{RV, RV−}` 都張成**相同 2D 子空間**（加上 RV_w, RV_m 共 4 維），
  OOS QLIKE 相同是**線性代數必然**，不是實證發現。
- **預測 Target 是 RV（不是 r²）**：這給 HAR 族天生優勢。Patton (2011) 公平比較 r²
  上 GARCH 系列反勝；但 30 天 DM 無顯著。

## 7. 後續研究方向

1. **擴充樣本**：累積至 250+ 天 5-min 後重測。
2. **加入隔夜資訊**：Hansen & Lunde (2005) 全日 RV = RV_intraday + r²_overnight；
   semi-variance 分解是否延伸到隔夜？
3. **跨 regime**：VIX 高/低 regime 下 β⁻/β⁺ 是否穩定？
4. **替代分解**：continuous + signed jump（Patton-Sheppard 2015 完整 6-regressor 模型）。
5. **與 GJR γ 的對照**：RV-based β⁻/β⁺ 比 vs GJR daily return-based γ 是否一致？
   如果 daily GJR 已吸收所有 leverage，semi-variance 只提供邊緣資訊。

## 8. 檔案清單

| 檔案 | 說明 |
|------|------|
| `k1063.py` | 主腳本 |
| `k1063_results.json` | 完整結果（metrics、DM、coefs、OOS series）|
| `k1063_semi_variance_ts.png` | RV / RV+ / RV- / SJ 時序 |
| `k1063_leverage_asymmetry.png` | 對稱性診斷、leverage scatter、ACF bars |
| `k1063_model_comparison.png` | 5 HAR 變體 + GARCH 比較圖（bar + time-series overlay）|
| `README.md` | 本文件 |

## 9. 參考文獻

- Barndorff-Nielsen, O. E., Kinnebrock, S., & Shephard, N. (2010). *Measuring
  downside risk-realised semivariance.* Festschrift for R. Engle.
- Patton, A. J., & Sheppard, K. (2015). *Good volatility, bad volatility: Signed
  jumps and the persistence of volatility.* Review of Economics and Statistics,
  97(3), 683-697.
- Corsi, F. (2009). *A simple approximate long-memory model of realized
  volatility.* Journal of Financial Econometrics, 7(2), 174-196.
- Patton, A. J. (2011). *Volatility forecast comparison using imperfect
  volatility proxies.* Journal of Econometrics, 160(1), 246-256.
- Harvey, C. R. (2016). *Presidential address: The scientific outlook in
  financial economics.* Journal of Finance, 72(4), 1399-1440.
