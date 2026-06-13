# K740: 14 套紙上交易策略的後設比較

- Experiment ID: `K740`
- Status: completed
- Created At: 2026-04-16T09:40:48.866448+00:00
- Reviewed / repaired by Codex: 2026-06-13
- Article: `mile_2fb1dfb3`

## 問題描述

這個實驗比較 VolPred 目前 forward-tracked 的 14 套紙上交易策略，檢查「策略複雜度是否自然帶來更好的風險調整後績效」，並整理一般讀者可理解的策略選擇訊號。

## 資料來源與期間

- 資料來源：`storage/paper_trading.json` 與 `storage/strategy_metrics.json`
- 期間：2023-01-04 至 2026-03-27
- 樣本：14 套策略；各策略依實際可用 forward-tracked return 計算，日數因策略上線時間略有不同
- 產物：`k740_strategy_meta_analysis.py`、`k740_strategy_meta_analysis_results.json`、`k740_top_strategy_ranking.png`、`k740_complexity_vs_sharpe.png`

`storage/paper_trading.json` 會持續追加新列，因此 script 以固定起訖日重現已發佈文章的數字，避免後續 forward tracking 改變歷史文章結果。

## 方法

每個策略以實際 `portfolio_return` 計算 Sharpe、CAGR、最大回撤、Calmar、Sortino、月勝率、換手、交易成本後 net Sharpe、最差月、回復天數、年化波動、VaR / CVaR、偏態與峰態。

綜合排名使用 10 個指標的 min-max normalized equal-weight composite score：

- 高者佳：Sharpe、CAGR、MDD（較不負較佳）、Calmar、Sortino、月勝率、net Sharpe、最差月
- 低者佳：年化換手、回復天數

策略複雜度、資產類別與調整頻率的關係使用 Spearman correlation 與分組平均比較。這是描述性後設分析，不是新策略的正式上架 gate。

## 主要結果

- 保守型 VT（Piecewise）在 composite score 排第一，score = 0.8166，Sharpe = 3.158，最大回撤 = -2.48%，月勝率 = 87.2%。
- 複雜度與 Sharpe 的 Spearman rho = 0.149，p = 0.611，沒有證據支持「越複雜越好」。
- SPY+GLD 策略平均 Sharpe = 2.546，SPY-only 策略平均 Sharpe = 1.176，差距 = +0.826。
- 月頻策略平均 Sharpe = 2.343，日頻策略平均 Sharpe = 2.094；此比較是描述性結果，不應解讀成所有市場都適用。
- VIX-based strategies 的平均 Sharpe = 2.157，momentum/hybrid 平均 Sharpe = 2.173；VIX 策略的優勢不在平均 Sharpe 絕對勝出，而在實作簡單與風險控制敘事較清楚。

## 限制

- 這不是隨機化實驗；策略上線時間、資產類別、交易頻率與風險目標並不完全相同。
- composite score 權重是等權，適合一般比較，但不是唯一合理效用函數。
- 這個實驗沒有做 Harvey / DM / bootstrap 的預測模型比較；文章只能主張描述性排序與風險特徵，不應延伸成嚴格 alpha 顯著性結論。
- 紙上交易資料是 forward-tracked，但仍不是實盤成交紀錄，交易成本使用簡化估計。

## 發佈審查結論

2026-06-13 Codex review 修正了兩個再現性問題：

- script 原本從 `experiments/storage/` 讀資料，無法從 repo root 正常重跑。
- script 原本沒有固定 published article 的結束日期，後續 paper-trading 追加資料會讓同一篇文章的數字漂移。

修正後以 `.venv/bin/python experiments/k740/k740_strategy_meta_analysis.py` 可重跑，並重新產生 results 與兩張圖。
