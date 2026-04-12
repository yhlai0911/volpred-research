# K1087: TLT A4f with Yield-Curve Factors — Finding the Bond-Matched Regressor

**Proposer**: 用戶 (Claude executing) · **Executor**: Claude · **Date**: 2026-04-12

## 問題 (Problem)

K1086 測試了「Asset-matched IV theory」在債券上的延伸（TLT + MOVE），結果全部 NULL：

| Model | DM t vs GJR (K1086) |
|---|---|
| A4f-VIX | +1.43 FAIL |
| A4f-MOVE | +1.36 FAIL |
| A4f-COMBO | +1.44 FAIL |

**診斷**：TLT 波動率並非由 option-implied volatility 驅動，而是由 **yield-curve dynamics**（duration risk）主導。MOVE 反映 option market 的 fear，但 TLT 的 r² 主要反映 duration × rate-change。因此 bond-matched regressor 應該是 yield-based，不是 IV-based。

## 動機 (Motivation)

若 K1087 找到 yield-curve factor Harvey-PASS（|t|>3），則可將 A4f 的統一理論延伸為：
> "Each asset class has its own matched regressor: Equity→VIX (K1075), Gold→GVZ (K1085), Bonds→yield factor (K1087)."

若仍 NULL → Paper 9 必須明確限縮主張到 equity + commodity，並誠實報告 bond vol 不適 A4f 結構。

## 方法 (Method)

### 資料
- **TLT**: yfinance Adj Close, 2003-01-02 ~ 2026-04-10
- **VIX, MOVE**: yfinance ^VIX, ^MOVE（K1086 baselines）
- **Yields (DGS10, DGS2, DGS5)**: 從 `storage/macro/fred_DGS*.csv` 載入；DGS5 直接從 FRED 下載
- **OOS**: 2011-01-01 ~ 2026-04-10（對齊 K1086）
- **Rolling window** = 2000 days, **refit every 63 days**（quarterly）

### 衍生變數（all in percent units, 除非標示）
```python
dy10   = Y10_t - Y10_{t-1}                 # daily change (%)
|dY10| = |dy10|  (and |dY10|_bps = |dY10| × 100)
slope  = Y10 - Y2                          # (%)
butterfly = 2×Y5 - Y2 - Y10                # (%)
```

### 八個模型

| Model | tau = θ₀ + ... |
|---|---|
| **GJR-GARCH** | baseline |
| **A4f-VIX** | θ₀ + θ₁·VIX²_{t-1} (K1086 baseline) |
| **A4f-MOVE** | θ₀ + θ₁·MOVE²_{t-1} (K1086 baseline) |
| **A4f-Level** | θ₀ + θ₁·Y10²_{t-1} |
| **A4f-Slope** | θ₀ + θ₁·\|Y10 - Y2\|²_{t-1} |
| **A4f-RateVol** | θ₀ + θ₁·\|ΔY10\|²_{t-1} |
| **A4f-Butterfly** | θ₀ + θ₁·\|2Y5 - Y2 - Y10\|²_{t-1} |
| **A4f-Combo** | θ₀ + θ₁·VIX²_{t-1} + θ₂·\|ΔY10\|²_{t-1} |

所有 tau 項基於 t-1 資訊（`signal.shift(1)`），透過建構時的 lag 陣列強制 — 代碼層 lookahead-free。
A4f-GARCH component: Engle 2013 規範 g_t = ω + α·(r_{t-1}/√τ_t)² + γ·asym + β·g_{t-1}。

### 評估
- **QLIKE** on r² (Patton 2011, proxy-robust)
- **DM test with Newey-West HAC**（max lag = T^{1/3}）；Harvey (2016) |t|>3.0 門檻
- **Spearman rank** correlation（分配無關）
- **Bootstrap 95% CI**（moving block，seed=42）
- **Pairwise DM matrix**（8×8）
- **Regime buckets**：VIX、|ΔY| (bps)、Y10 level
- **Crisis periods**：Euro_Debt, Taper_Tantrum, COVID_Crash, Rising_Rates_2022

## 假設 (Hypotheses)

- **H1**: A4f-RateVol DM t > 3 on TLT（realized rate vol 匹配 duration risk）
- **H2**: A4f-Level 或 A4f-Slope DM t > 3 on TLT
- **H3**: A4f-Combo 在 pairwise DM test 中 Harvey-beats A4f-VIX
- **H4**: 2022 升息期：yield-curve factor 比 option-IV factor 更能 capture TLT drawdown

## 預期 (Expectations)

- 若 RateVol PASS → 強烈支持「Each asset class has its own matched regressor」命題
- 若僅 Level/Slope 有 marginal 改善 → 支持 yield-curve factors 是 bond vol 的主要 driver
- 若全部 NULL → TLT vol 可能需要非 A4f 結構（如 regime-switching GARCH 或 2-factor model）

## 結論 (Conclusions)

**全部 4 個假設 FAIL，overall verdict = PARTIAL。**

### Full OOS 結果 (n=3,756, 2011-01-04 ~ 2026-04-07, 60 refits)

| Model | QLIKE | Spearman | DM t vs GJR | Harvey |
|---|---|---|---|---|
| GJR | -8.480707 | 0.251 | — | — |
| **A4f-VIX** | -8.497114 | 0.260 | **+2.018** | FAIL |
| A4f-MOVE | -8.492803 | 0.268 | +1.865 | FAIL |
| A4f-Level | -8.476688 | 0.249 | −1.259 | FAIL |
| A4f-Slope | -8.473337 | 0.252 | −1.269 | FAIL |
| A4f-RateVol | -8.482503 | 0.249 | +0.452 | FAIL |
| A4f-Butterfly | -8.477816 | 0.252 | −0.821 | FAIL |
| A4f-Combo (VIX+RateVol) | -8.495442 | 0.258 | +1.695 | FAIL |

**重要發現**：
1. **診斷相關性誤導結論**：`Corr(TLT r², |ΔY|²) = 0.652` >> `Corr(TLT r², VIX²) = 0.381`，但 A4f 結構下 RateVol 只贏 GJR +0.45（VIX 還 +2.02）。單日相關 ≠ 條件變異數預測力。
2. **Yield Level、Slope、Butterfly 全部負 DM**：這三個慢變數的資訊已被 GJR recursion 吸收，加入 A4f tau 反而引入額外雜訊。
3. **A4f-VIX 仍是 TLT 最佳外生 tau regressor**（t=+2.02）——股債相關（相關性約 -0.3 ~ +0.6 隨 regime 變）讓 VIX 也帶來部分資訊。
4. **Combo (VIX + RateVol) 貢獻極小**：t=+1.70 < A4f-VIX 單獨 +2.02，加 RateVol 反而稍微惡化——符合 K1086 的 COMBO 結果。

### 假設檢驗

| 假設 | 預期 | 實際 | 結論 |
|---|---|---|---|
| **H1**: A4f-RateVol Harvey-PASS | t > 3 | t=+0.452 | **FAIL** |
| **H2**: Level 或 Slope Harvey-PASS | t > 3 | Lvl=-1.26, Slp=-1.27 | **FAIL** |
| **H3**: Combo pairwise beats VIX | t > 3 | Combo 反而稍差 | **FAIL** |
| **H4**: Yield-curve > Option-IV in 2022 | YC DM > IV DM | best YC=-0.67, best IV=+1.67 | **FAIL** |

### Regime-specific 發現

- **VIX_Extreme (>40, n=51)**: Combo DM t=+2.32（接近 Harvey，但樣本太小不可信）
- **VIX_Low (<15, n=1,402)**: Combo t=+1.90、RateVol t=+1.92（波動率低時 A4f 有小幅幫助）
- **Yield_Low (<2%, n=1,191)**: RateVol t=+1.58（低利率 regime 稍好）
- **2022 升息期**: option-IV (VIX t=+1.67, MOVE t=+1.31) **勝** yield-curve factors（全部負）— 與預期完全相反

### Pairwise DM (focus)

Convention: "A vs B" positive = A 勝 B（QLIKE 較低）

- A4f_VIX vs A4f_RateVol: t=**+2.18** p=0.029（VIX 優於 RateVol，雖然 TLT r² 與 |ΔY|² 單日相關性 0.65 >> VIX² 的 0.38）
- A4f_MOVE vs A4f_RateVol: t=**+2.04** p=0.041（MOVE 也優於 RateVol）
- A4f_Slope vs A4f_RateVol: t=**−1.21** p=0.226（RateVol 略勝 Slope，但都不顯著）
- A4f_VIX vs A4f_Combo: t=+0.59 p=0.55（VIX 單獨略優於加入 RateVol 的 Combo，加 RateVol 沒幫助）

**教訓**：單日相關性高 ≠ 條件變異數預測力強。`|ΔY|²` 對 `r²` 單日相關 0.65 是因為 TLT 的 return 本身就是 yield × duration 的直接對映（會計恆等式），但 A4f 預測的是**下一期條件變異數**，這個機械關係被 GARCH recursion 已經隱含吸收。

### 意涵

**K1086 + K1087 共同確立**：
- TLT vol dynamics **不適 A4f 的 MIDAS-style τ×g 分解**，不論 regressor 是 option IV（VIX/MOVE）還是 yield-curve（Level/Slope/RateVol/Butterfly）。
- Asset-matched regressor 理論**在 bond 上失效**：K1085 的 GLD-GVZ 結果（t=4.46）無法外推到 bond。
- **Paper 9 必須限縮主張到 equity + commodity**，不能宣稱統一三資產類別的 A4f 理論。
- 未來可嘗試：regime-switching GARCH、duration-adjusted GARCH（τ depends on TLT duration × rate vol）、2-factor stochastic vol model、ARMA-GARCH with yield change as mean regressor（不是 vol regressor）。

### 局限

- OOS 只涵蓋 2011-2026（無 2002-2010），若 pre-2007 的長期債 bull market 性質不同，結論可能不適用那段期間。
- Rolling window=2000 固定；若縮短到 500 可能捕捉更快的 regime shift。
- 所有 yield factor 都是 unsquared 的線性組合，未測試非線性 transform（log|ΔY|、√|ΔY|）。
- 未單獨測試 yield change **符號**（升息 vs 降息）對 TLT vol 的不對稱效果。

## 檔案

- `k1087.py` — 主腳本
- `k1087_results.json` — 完整結果（full OOS、per-window、crisis、3 種 bucket、pairwise DM）
- `k1087_regressor_comparison.png` — 7 A4f 變體 vs GJR（DM t-bar）
- `k1087_yield_curve.png` — Y10/Y2、slope、|ΔY10| 時序
- `k1087_2022_rate_hike.png` — 2022 升息期 TLT 價格與 yield 動態
- `k1087_theta1_compare.png` — 各模型 θ₁ 穩定性
- `k1087_asset_class_final.png` — Equity/Gold/Bond × matched regressor 矩陣
- `README.md` — 本文件

## 參考文獻

- Engle, R. F., Ghysels, E., & Sohn, B. (2013). Stock market volatility and macroeconomic fundamentals. *Review of Economics and Statistics*, 95(3), 776-797.
- Patton, A. J. (2011). Volatility forecast comparison using imperfect volatility proxies. *Journal of Econometrics*, 160(1), 246-256.
- Harvey, D. I., Leybourne, S. J., & Newbold, P. (2016). Testing the equality of prediction mean squared errors. *International Journal of Forecasting*, 13(2), 281-291.
- Litterman, R., & Scheinkman, J. (1991). Common factors affecting bond returns. *Journal of Fixed Income*, 1(1), 54-61.
- Balduzzi, P., Elton, E. J., & Green, T. C. (2001). Economic news and bond prices: Evidence from the U.S. Treasury market. *Journal of Financial and Quantitative Analysis*, 36(4), 523-543.
- Chen, N.-F., Roll, R., & Ross, S. A. (1986). Economic forces and the stock market. *Journal of Business*, 59(3), 383-403.

## 先行實驗

- **K1075**: SPY A4f-VIX DM t=4.48 PASS（equity-matched）
- **K1085**: GLD A4f-GVZ DM t=4.46 PASS（gold-matched via gold IV）
- **K1086**: TLT A4f-VIX/MOVE NULL（bond option IV 不夠）
- **K1087**（本實驗）: TLT A4f-{Level, Slope, RateVol, Butterfly, Combo}
