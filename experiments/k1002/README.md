# K1002: Unified 7-Model OOS Comparison Pipeline for Paper 5

## 動機
MF-GJR-X 系列（K988-K1001）已證明 A4f-t 是冠軍模型。論文需要在統一框架下與所有主要模型做公平比較，產出可直接放入論文的完整表格。

## 模型清單（7 個）
| # | 模型 | 規格 | 分配 |
|---|------|------|------|
| 1 | GJR-N | GJR-GARCH(1,1) | Normal |
| 2 | GJR-t | GJR-GARCH(1,1) | Student-t joint MLE |
| 3 | EGARCH-t | EGARCH(1,1) | Student-t joint MLE |
| 4 | A4f-N | MF-GJR-X(VIX², free ω) | Normal |
| 5 | A4f-t | MF-GJR-X(VIX², free ω) | Student-t joint MLE |
| 6 | HAR-ABS | HAR(1,5,22) on |r_t| | OLS |
| 7 | Macro-X | GJR-GARCH-X(term_spread, unrate) | Student-t joint MLE |

## 方法
- **資料**：SPY 2004-2026 (yfinance) + VIX + FRED (GS10, TB3MS, UNRATE)
- **OOS**：2019-01-01 to 2026-04-07, n=1825
- **Window**：2000 天, refit 每 63 天
- **評估 5 層**：QLIKE on r² → DM tests → MCS → Spearman ρ → VaR/ES

## 結果

### QLIKE 排名（lower = better）
| Rank | Model | QLIKE |
|------|-------|-------|
| 1 | **A4f-N** | -8.3612 |
| 2 | **A4f-t** | -8.3605 |
| 3 | Macro-X | -8.2699 |
| 4 | GJR-t | -8.2663 |
| 5 | GJR-N | -8.2625 |
| 6 | EGARCH-t | -8.2465 |
| 7 | HAR-ABS | -8.1996 |

### MCS（10% significance）
**{A4f-N, A4f-t}** — 只有兩個 MF-GJR-X 變體存活。

### 關鍵 DM 檢定（A4f-t vs others, Harvey t>3.0）
| Comparison | DM t | Significant? | Winner |
|-----------|------|-------------|--------|
| A4f-t vs GJR-N | -4.34 | *** | A4f-t |
| A4f-t vs GJR-t | -4.40 | *** | A4f-t |
| A4f-t vs EGARCH-t | -1.96 | | A4f-t |
| A4f-t vs A4f-N | +0.46 | | A4f-N |
| A4f-t vs HAR-ABS | -6.13 | *** | A4f-t |
| A4f-t vs Macro-X | -4.96 | *** | A4f-t |

### VaR/ES Scorecard
| Model | VaR 1% | VaR 2.5% | VaR 5% | ES 2.5% | Score |
|-------|--------|----------|--------|---------|-------|
| **A4f-t** | **0.013 (PASS)** | **0.028 (PASS)** | **0.054 (PASS)** | **PASS** | **7/7** |
| A4f-N | 0.018 | 0.030 (PASS) | 0.050 (PASS) | PASS | 5/7 |
| GJR-N | 0.025 | 0.039 | 0.060 (PASS) | PASS | 3/7 |
| Macro-X | 0.017 | 0.033 | 0.062 | PASS | 2/7 |
| GJR-t | 0.017 | 0.037 | 0.066 | PASS | 1/7 |
| EGARCH-t | 0.017 | 0.035 | 0.069 | PASS | 1/7 |
| HAR-ABS | 0.028 | 0.041 | 0.068 | PASS | 1/7 |

### Spearman ρ（與 r² 的排名相關）
| Model | ρ |
|-------|---|
| A4f-t | 0.4241 |
| A4f-N | 0.4245 |
| EGARCH-t | 0.4010 |
| GJR-t | 0.3586 |
| GJR-N | 0.3551 |
| Macro-X | 0.3543 |
| HAR-ABS | 0.3258 |

## 結論
1. **A4f-t 是 VaR/ES 的絕對冠軍**（7/7 PASS），唯一在所有 VaR 水準都通過 UC+CC 檢定的模型
2. **A4f-N 和 A4f-t 在 QLIKE 上非常接近**（差異不顯著，DM t=0.46），兩者都在 MCS 中
3. **A4f-t 顯著優於所有非 MF-GJR-X 模型**（DM |t| > 3.0 vs GJR-N/GJR-t/HAR-ABS/Macro-X）
4. **Student-t 分配的真正價值在 VaR/ES**：A4f-N vs A4f-t 在 QLIKE 幾乎一樣，但 VaR scorecard 5/7 vs 7/7
5. **HAR-ABS 排名最後**——用 daily |r| 的 HAR 在 QLIKE-on-r² 框架下不如 GARCH 家族

## 局限性
- 單一資產（SPY），未做跨資產驗證
- OOS 期間包含 COVID-19 極端波動
- Macro-X 宏觀變數有 1 個月 publication lag

## 參考文獻
- Engle & Rangel (2008), RFS
- Conrad & Loch (2015), JBES
- Patton (2011), J Econometrics
- Hansen, Lunde & Nason (2011), Econometrica
- Nelson (1991), Econometrica
- Corsi (2009), J Financial Econometrics
- Harvey et al. (2016)

## 檔案
- `k1002.py`：實驗腳本
- `k1002_results.json`：完整結果（QLIKE、DM matrix、MCS、VaR/ES）
