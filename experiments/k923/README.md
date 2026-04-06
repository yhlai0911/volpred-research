# K923: Copula-Based Optimal Hedge Ratio — SPY Hedged with GLD

## 問題
Copula-based hedge ratio 是否優於 OLS/DCC？尤其在尾部事件中？

## 方法
5 種方法：OLS / Rolling OLS / DCC / Copula / Copula Quantile Hedge
避險指標評估（HE/VaR Reduction/ES Reduction），IS+OOS 分開

## 結果（NULL）
- 所有方法 HE < 3%（SPY-GLD 相關性僅 0.058）
- Best OOS: DCC 2.69%, Copula 1.76%
- Copula Quantile: 唯一 ES reduction < 1.0 (0.9982)
- 尾部事件：Copula best tail variance ratio 0.902（10% 改善）
- 無 DM test 達 Harvey 門檻

## 結論
SPY-GLD 是分散化配對（r=0.058），不是避險配對。Copula hedging 的優勢在高相關資產對（spot-futures r>0.90）。

## 注意
腳本檔案因 worktree 清理意外遺失，需重新執行。結果基於 agent 回報。

## 數據來源
yfinance (SPY, GLD)
