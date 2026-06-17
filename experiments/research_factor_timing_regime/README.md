# research_factor_timing_regime — 高維 factor timing 在波動 regime 下是否只是在過度換手

- Experiment ID: `research_factor_timing_regime`
- Task: `research_factor_timing_regime`
- Status: completed
- Created: 2026-06-18 台灣時間

## 問題

Factor timing 的直覺很吸引人：價值、動能、品質、低波動、成長等風格會輪動，
所以可以根據波動 regime 或近期 factor 訊號動態調整權重。但實務上真正的問題不是
gross Sharpe 有沒有變高，而是：

1. OOS 是否能打贏 simple equal-weight factor basket？
2. 若 gross 有改善，turnover 與交易成本是否吃掉 edge？
3. 高波動 regime 下的改善是否只是多換手、多押防禦因子造成？

## 文獻與背景

- AQR, "Factor Timing is Hard" (`https://www.aqr.com/Insights/Perspectives/Factor-Timing-is-Hard`)：主張 factor timing 可能比 market timing 更難，估值/宏觀訊號雖變動但未必能轉成可交易 alpha。
- Kozak / Nagel / Santosh, "Factor Timing" (`https://www.nber.org/system/files/working_papers/w26708/w26708.pdf`)：理論上 factor loading 與 SDF conditional properties 有時間變動，factor timing 可能有價值。
- Robeco, "A prudent route to effective factor timing" (`https://www.robeco.com/docm/docu-202307-a-prudent-route-to-effective-factor-timing.pdf`)：強調 multi-factor timing 若要可行，核心是低 turnover 與避免過度反應。
- Garcia-Feijoo et al. (2015), "Low-Volatility Cycles" (`https://www.aqr.com/-/media/AQR/Documents/Insights/Journal-Article/Low-Volatility-Cycles-The-Influence-of-Valuation-and-Momentum-on-Low-Volatility-Portfolios.pdf`)：低波動組合表現受 valuation / momentum cycle 影響，支持檢查 factor-cycle 狀態，但不等於可交易 timing。

## 相似 K / 防重複

- K1503 Factor-MAX：factor ETF 的 prior-month MAX 對 next-month return anomaly 為 NULL，但對 next-month RV 是強訊號。
- K1512 Double-ML factor：ETF-level factor causal/partial return relation 在小樣本下不穩，0/3 factor 過 Bonferroni。
- K1337-v2 / K1519 / K1520：regime label 常有描述力，但 OOS 增量常被 HAR/VIX/simple baseline 吃掉。

本實驗差異：不問單一 factor anomaly，而是把多 factor timing strategy 放進 turnover/cost audit。

## 方法

### 資料

- yfinance adjusted close
- Factor ETFs: `MTUM`, `VLUE`, `QUAL`, `USMV`, `RPV`, `IVE`, `IWF`
- Controls: `SPY`, `^VIX`
- 月頻，OOS 起點 `2018-01-31`

### 策略

1. `EW`：7 factor ETFs 等權，月頻再平衡。
2. `MOM_12_1_TOP3`：用 12-1M momentum 排名，long-only top 3 等權。
3. `EN_REGIME_TOP3`：expanding panel ElasticNet 預測 next-month factor return，features 包含：
   - factor 自身 1/3/6M return、12-1M momentum
   - factor 3/6M realized vol
   - SPY 3M return / vol
   - VIX level、3M change、`VIX>20` dummy
   - momentum × high-VIX、vol × high-VIX interaction

### 防 lookahead

- feature date `t` 只用月末 `t` 已知資訊。
- training rows for forecast date `t` require `feature_date < t`；最新可用 target 是 `(t-1)→t`，在 month-end `t` 已知。
- weights formed at month-end `t` apply to month `t+1` returns。
- code 中保留明確 indexing guard，不用 same-month target 訓練同月 forecast。

### 成本與檢定

- 交易成本：10 bps one-way × turnover。
- DM：`volpred.stats.model_evaluation.strategy_dm_test` on net monthly returns；negative t means timing strategy has lower loss / higher return than EW。
- Bootstrap：stationary bootstrap, B=1000, mean block=6 months, seed fixed。
- Harvey threshold：`|t| > 3` 才當 robust pass。

## 預註冊判準

- `PASS`：timing strategy net Sharpe > EW，DM `|t|>3` 且 bootstrap Sharpe-diff CI > 0。
- `CONDITIONAL_PASS`：net edge positive、DM p<0.05 或 bootstrap mostly positive，但未過 Harvey。
- `NULL`：gross 或 net edge 不穩；成本/turnover 吃掉；DM/Bootstrap 不支持。
- `FAIL`：timing 顯著劣於 EW 或發現 lookahead / implementation bug。

## 結果

資料實際範圍：daily `2013-01-02` 到 `2026-06-17`；月頻樣本只用完整月份，
因此 monthly end 到 `2026-05-31`，OOS `2018-01-31` 後共有 100 個持有月份。

| Strategy | Net Sharpe | Net CAGR | MDD | Avg monthly turnover | Ann cost drag |
|---|---:|---:|---:|---:|---:|
| EW | 0.799 | 12.59% | -23.37% | 0.026 | 0.03% |
| MOM_12_1_TOP3 | 0.867 | 13.88% | -21.21% | 0.287 | 0.34% |
| EN_REGIME_TOP3 | 0.643 | 10.62% | -30.73% | 0.706 | 0.85% |

檢定：

- `MOM_12_1_TOP3` vs `EW`: DM `t=-0.63`, `p=0.529`；bootstrap Sharpe diff CI `[-0.159, 0.251]`。
- `EN_REGIME_TOP3` vs `EW`: DM `t=+0.69`, `p=0.494`；bootstrap Sharpe diff CI `[-0.346, 0.048]`。

成本診斷：

- Momentum top-3 gross edge vs EW 約 `+1.44%/yr`，net edge `+1.13%/yr`，成本吃掉約 `0.31%/yr`。
- ElasticNet regime timing gross edge 已是 `-0.64%/yr`，net edge `-1.46%/yr`，不是「有 edge 被成本吃掉」，而是高維 timing 本身沒有穩健 edge，且 turnover 額外放大損失。

**Verdict: NULL.** 在這個 ETF-level free-data specification 中，簡單 momentum rotation 方向上略優但遠未過 Harvey/Bootstrap；高維 ElasticNet + vol-regime interaction 產生高 turnover，淨表現劣於等權。不能宣稱 volatility-regime factor timing 有可交易 alpha。

## 產物

- `research_factor_timing_regime.py`
- `research_factor_timing_regime_results.json`
- `figures/factor_timing_wealth_turnover.png`
