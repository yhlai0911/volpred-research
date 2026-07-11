# K432：Bayesian MCMC GJR-GARCH 與 MLE

## Data & Methodology

- 類型：empirical forecast comparison
- 資料：yfinance SPY；IS 2005-01-04 至 2022-12-30（4,530 日），OOS 2023-01-03 至 2024-12-31
- Target / loss：close-to-close `r²`、QLIKE
- 模型：MLE GJR-GARCH；Bayesian Mean / Median / BMA，兩條 5,000-iteration MH chains
- MCMC：Rhat 全部 <1.01；MLE convergence flag=0
- DM：paired finite mask 後委派 canonical HAC，Harvey `|t|>3`

## 2026-07-11 canonical HAC 重跑

| Bayes 對 MLE | 舊 t | canonical HAC t | ACF(1) | Harvey |
|---|---:|---:|---:|---|
| Mean | 2.673 | 3.011 | +0.014 | PASS（MLE 較佳） |
| Median | 2.042 | 2.256 | -0.001 | FAIL |
| BMA | 2.773 | 3.152 | +0.003 | PASS（MLE 較佳） |

Mean / BMA 的負高階自相關使 canonical SE 變小，|t| 反而增加；遺漏 HAC 的偏誤不是單向。
最佳 Bayesian 點預測是 Median（QLIKE 1.4647，MLE 1.4629），但 Median 並未通過 Harvey，
所以正確結論是：MLE 點排名仍第一；Mean 與 BMA 明確較差，但不能宣稱所有 Bayesian 版本都
正式顯著輸給 MLE。Bayesian 的主要價值仍是不確定性量化。

兩次 live-yfinance 重跑的 DM t 最大漂移 0.000061，所有 gate 一致。輸出路徑已由死亡 worktree
改回本目錄，並採原子 JSON 寫入。
