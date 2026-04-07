# K965: Wild Bootstrap Optimal Hedge Ratio — SPY/ES Futures

## 動機
傳統 OLS hedge ratio 假設同質變異，GARCH 需要複雜模型設定。JRFM 2024 發現 bootstrap percentile-based MVHR 可能優於 DCC-GARCH。本實驗用 Wild Bootstrap (Mammen 1993) 方法估計最小變異避險比率的信賴區間，並以不同百分位數作為 hedge ratio 與 OLS、DCC-GARCH 比較。

## 方法
- **Wild Bootstrap**: Mammen (1993) two-point distribution, B=10,000
- **比較方法**: Naive (h=1), OLS Static, Rolling OLS (252d), DCC-GARCH(1,1), WB 25th/50th/75th percentile
- **數據**: SPY + ES=F (E-mini S&P 500 futures), 2010-01-05 ~ 2026-04-02, 4084 天
- **IS/OOS**: 60/40 split (IS: 2010-2019, OOS: 2019-2026)
- **Seed**: 42

## 核心結果

### OOS Hedging Effectiveness
| Method | HE | Downside HE | VaR Reduction | Ann. Std |
|--------|-----|------------|---------------|----------|
| Naive (h=1) | 0.9426 | 0.9304 | 0.9183 | 4.85% |
| OLS Static | 0.9435 | 0.9323 | 0.9047 | 4.81% |
| Rolling OLS | 0.9402 | 0.9283 | 0.9107 | 4.95% |
| DCC-GARCH | 0.9344 | 0.9247 | 0.8999 | 5.18% |
| **WB 25th** | 0.9434 | **0.9329** | 0.9016 | 4.81% |
| WB 50th | 0.9436 | 0.9321 | 0.9053 | 4.81% |
| **WB 75th** | **0.9437** | 0.9319 | 0.9126 | 4.80% |

### Bootstrap Distribution
- OLS β = 0.9550, Bootstrap mean = 0.9550, std = 0.0087
- 95% CI: [0.9396, 0.9684]
- 分布近似對稱，centred on OLS estimate

### Cross-OOS (5 non-overlapping 2-year periods)
- WB 25th: mean HE = 0.9519 ± 0.0111 (最穩定)
- OLS Static: mean HE = 0.9518 ± 0.0117
- DCC-GARCH: mean HE = 0.9450 ± 0.0174 (最不穩定)

### DM Test
所有 WB vs OLS 的 DM 統計量均不顯著 (|t| < 1.0)，表示 bootstrap 方法與 OLS 在統計上無顯著差異。DCC-GARCH 相對 OLS 有邊際劣勢 (DM=-1.86, p=0.064)。

## 結論
1. **SPY/ES=F 相關性極高 (0.974)**，所有方法的 HE 都在 0.93-0.94 之間，差異微小
2. **Wild Bootstrap 方法表現與 OLS 幾乎相同**——因為 bootstrap 分布高度集中 (std=0.0087)，不同百分位數差異僅 ~0.012
3. **DCC-GARCH 反而最差** (HE=0.9344)——SPY/ES 高度相關時，動態調整反而引入噪音
4. **WB 的真正價值不在 point estimate，而在 uncertainty quantification**——95% CI [0.94, 0.97] 提供避險比率的可信區間
5. **對於高相關性的 spot-futures pair，static OLS 已經足夠好**——複雜方法幾乎無法改善

## 局限性
- SPY/ES=F 是近乎完美避險的配對，差異空間極小
- 對相關性較低的配對（如 commodity futures, cross-hedge）可能有更大差異
- DCC-GARCH 用 grid search 而非 MLE，可能非最優
- Bootstrap 只用 IS 數據估計，未做 expanding window

## 參考文獻
- JRFM 2024, Vol 17, Issue 7, Article 310: Wild Bootstrap Percentile-Based MVHR
- Mammen, E. (1993). Bootstrap and wild bootstrap for high dimensional linear models. Annals of Statistics.

## 檔案
- `k965_wild_bootstrap_ohr.py` — 實驗腳本
- `k965_wild_bootstrap_ohr_results.json` — 結果 JSON
- `k965_bootstrap_distribution.png` — Bootstrap 分布直方圖
- `k965_he_comparison.png` — HE 比較柱狀圖
- `k965_hedge_ratio_timeseries.png` — Hedge ratio 時序圖
- `k965_cumulative_returns.png` — 累積報酬圖
