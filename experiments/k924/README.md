# K924: Bayesian SSVS for GJR-GARCH Mean Equation

## 問題
哪些外生變數能預測 SPY daily return？用 Bayesian SSVS（So, Chen & Liu 2006 JRSS-C）從 10 個候選變數中選擇最優子集。

## 動機（K433 用戶指定方向，2026-03-26 開放）
- K484: SSVS variance equation 成功（4/5 PIP=1.0）
- K913: VRP return prediction NULL（frequentist）
- Bayesian 方法可能找到 frequentist 錯過的信號

## 方法
- 10 候選變數：VIX level, ΔVIX, VRP, momentum 5d/22d, term spread, credit spread, GLD ret, TLT ret, VIX slope
- MCMC 20000 iter, burn-in 5000
- PIT: standardized residuals z_t = r_t / σ_t
- 15 expanding-window refits (OOS 2019-2026)

## 結果（NULL）
| 變數 | PIP | 結論 |
|------|-----|------|
| VRP | 0.312 | 最高但仍排除 |
| GLD_ret | 0.294 | 排除 |
| mom_5d | 0.165 | 排除 |
| credit_spread | 0.123 | 排除 |
| 其他 6 個 | < 0.10 | 決定性排除 |

- 所有 15 次 refit 都選出 0 個變數
- OOS R² ≈ 0.7%（近零）
- 全部 DM test 未達 Harvey 門檻

## 結論
SPY daily return 不可預測——Bayesian 和 Frequentist 一致。VRP PIP=0.312 確認 K913 null。這是 return prediction 問題的 Bayesian closure。

## 注意
腳本檔案因 worktree 清理意外遺失，需重新執行。結果基於 agent 回報。

## 數據來源
yfinance (SPY, GLD, TLT, ^VIX, ^VIX3M) + FRED (GS10, GS2, BAA, AAA)
