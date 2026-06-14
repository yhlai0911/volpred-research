# experiment_diurnal_pattern_rv_2026_06_14

## 問題

本實驗檢查：在本地可用的 5 分鐘資料上，固定且可重複的日內 diurnal pattern，是否足以解釋 intraday realized variance 的主要變異。

## 動機

- 任務池 `research_diurnal_pattern_rv`
- `research_program.md` 把這題列為方法論基礎題
- 本地已有 SPY / 0050.TW 5 分鐘資料，可先做誠實的 proxy assessment

## 文獻

1. Christensen, Hounyo, Podolskij, "Is the diurnal pattern sufficient to explain intraday variation in volatility? A nonparametric assessment" ([arXiv](https://arxiv.org/abs/2601.16613), published version indexed at [IDEAS/RePEc](https://ideas.repec.org/a/eee/econom/v205y2018i2p336-362.html))
2. Engle, Sokalska, "Forecasting intraday volatility in the US equity market: Multiplicative component GARCH" ([OUP abstract](https://academic.oup.com/jfec/article-abstract/10/1/54/755620))
3. Andersen, Bollerslev, "Intraday periodicity and volatility persistence in financial markets" ([PDF](https://public.econ.duke.edu/~boller/Published_Papers/joef_97.pdf))

## 設計

- 資料：`data/intraday/` 本地 5 分鐘 CSV
- 標的：SPY、0050.TW
- 指標：每根 5 分鐘 bar 的 within-bar log return square
- 切分：按日期做 chronological 70/30 train/test
- train：估計 bin-of-day 平均 RV profile
- test：
  - 對 `log(bar_rv)` 做 one-way eta-squared（bin effect）
  - 用 day-block permutation 估 p-value
  - 再對 diurnal-adjusted RV 重做一次
- 若 deseasonalized 後 bin effect 仍顯著，代表 deterministic diurnal pattern 不足

## 限制

- 這不是完整的 CHP noise/jump-robust semimartingale test
- 樣本只涵蓋本地已累積的 2026-01 到 2026-06 5 分鐘資料
- 結論是 local proxy verdict，不應過度外推到更長歷史或論文級最終判定

## 產物

- `experiment_diurnal_pattern_rv_2026_06_14.py`
- `experiment_diurnal_pattern_rv_2026_06_14_results.json`
- `fig_diurnal_profiles.png`
- `fig_deseasonalized_effect.png`

## 樣本

- SPY：2026-01-14 至 2026-06-12，完整 5 分鐘交易日 99 天
- 0050.TW：2026-01-20 至 2026-06-11，完整 5 分鐘交易日 81 天
- 切分：chronological 70/30
  - SPY train/test = 69 / 30 天
  - 0050.TW train/test = 56 / 25 天

## 主要結果

### SPY

- raw bin effect：eta^2 = 0.0714，day-block permutation p = 0.001
- deseasonalized 後：eta^2 = 0.0334，p = 0.113
- deterministic diurnal profile 移除了約 53.2% 的 cross-bin effect
- 以固定 diurnal share 預測每日 RV 配置，相對 uniform baseline 的日均 R^2 = 0.076

### 0050.TW

- raw bin effect：eta^2 = 0.1015，day-block permutation p = 0.001
- deseasonalized 後：eta^2 = 0.0476，p = 0.101
- deterministic diurnal profile 移除了約 53.1% 的 cross-bin effect
- 相對 uniform baseline 的日均 R^2 = 0.097

## 結論

- 在這個本地 5 分鐘 proxy test 下，**兩個市場都無法在 5% 水準拒絕「deterministic diurnal pattern 已足夠」**。
- 但這不代表 diurnal pattern 能高精度解釋每天的 intraday RV 配置；固定 profile 對每日 bin-share 的增量解釋力仍偏低，日均 R^2 只有約 7.6% 到 9.7%。
- 因此較精確的說法是：
  - **作為 cross-bin average pattern，diurnal seasonality 很重要**
  - **作為逐日 intraday RV allocation 的完整解釋，證據仍然有限**

## 誠實限制

- `arXiv 2601.16613` 的 arXiv 條目對應的是 2026 年重新上架版本；IDEAS/RePEc 顯示正式發表版本是 *Journal of Econometrics* 2018。這裡只把它當方法論來源，不誤報為 2026 新發表結論。
- 這份結果只基於本地累積的 2026-01 到 2026-06 樣本，沒有跨危機期長歷史。
- 測試用的是 bar-level log-RV 的 permutation eta-squared proxy，不是文獻中的 pre-averaged bipower / jump-truncation 正式統計量。
- 若要做 paper-grade 結論，下一步應補更長歷史與 noise/jump-robust 正式檢定。
