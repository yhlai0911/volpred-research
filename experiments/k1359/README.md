# K1359 — tailasym5 / JOIM-skews 尾部不對稱估計法賽馬

## 動機

本題來自 `research_program.md` 2026-06-21 journal-discovery backlog：

> 用 ETF/期貨代理（SPY/QQQ/TLT/GLD/USO/UUP/FXY/HYG/EEM）月頻，測多種 robust asymmetry estimator，檢定下一月報酬、RV 與 left-tail exposure。

核心問題是：**只靠免費 ETF 歷史報酬做出的尾部不對稱 estimator，是否能形成穩健的跨資產尾部溢酬？**

這與 K1531 的 FX realized-skewness 單一題不同。K1359 不只測 realized skewness，也測修剪 / winsorized skew、上下行半變異、尾端均值差與最大損失-最大收益差，重點是 estimator robustness。

## 相關知識庫脈絡

- K1507：returns-only downside-skew proxy 無法複製 option smirk / borrow-fee 文獻的 ETF 橫斷面報酬訊號。
- K1531：FX realized skewness 不是 implied crash-risk premium 的免費替代品；左尾風險較高但沒有報酬補償。
- K1525：realized downside tail proxy 有 in-sample 痕跡，但 OOS 不穩。
- K447 / K535 / K979：SKEW / realized higher-moment 類 proxy 在 VolPred 知識庫中多為 NULL。

## 文獻定位

- Kelly and Jiang (2014), *Tail Risk and Asset Prices*, RFS：tail risk 可定價，但原始方法使用個股崩跌橫斷面，不是 ETF trailing moment。
- Bali, Cakici, and Whitelaw (2011), *Maxing out*, JFE：lottery-like tail payoff 與 expected returns 相關，動機上支持檢驗尾端形狀。
- Conrad, Dittmar, and Ghysels (2013), *Ex Ante Skewness and Expected Stock Returns*, JF：option-implied higher moments 與 expected returns 有關；K1359 測的是更便宜也更弱的 realized-return proxy。
- Kozhan, Neuberger, and Schneider (2013), *The Skew Risk Premium in the Equity Index Market*, RFS：skew risk premium 本質上是 option-surface / skew-swap 概念；K1359 不宣稱可替代。
- Harvey, Liu, and Zhu (2016), RFS：return predictor discovery 採 `|t| >= 3` 門檻。

## 資料

- 資料來源：`yfinance` adjusted close，`auto_adjust=True`；若本機已有 K1507 cache，重疊 ticker 優先複用並寫入 K1359 自身 `data/`。
- Universe：SPY, QQQ, TLT, GLD, USO, UUP, FXY, HYG, EEM。
- 樣本：2007-05-31 到 2026-05-31。
- 月數：229。
- Panel rows：12,348。
- 每個 estimator-month 有 7 到 9 檔 ETF。

## 方法

每日 log return 上，用 trailing 63 trading days 計算 6 個 estimator：

| Estimator | 定義 | 高值意義 |
|---|---|---|
| `bad_skew` | `- rolling realized skewness` | 較負偏 |
| `bad_trimmed_skew` | 去除 5%/95% 尾端後的 `-skew` | 中央分布較負偏 |
| `bad_winsor_skew` | 5%/95% winsorized 後的 `-skew` | robust 負偏 |
| `semivar_log_ratio` | `log(downside semivar / upside semivar)` | 下行半變異較大 |
| `tail_mean_gap` | 左 5% 平均損失 - 右 5% 平均收益 | 左尾較重 |
| `max_loss_gain_gap` | 最大單日損失 - 最大單日收益 | 極端左尾較重 |

每月形成訊號後，排序 ETF，取最高不對稱與最低不對稱 baskets（每邊 2-3 檔），測：

- next-month return：是否有尾部風險溢酬。
- next-month realized vol：是否只是風險狀態訊號。
- next-month downside vol。
- next-month worst daily loss。

Primary inference 是每月 high-minus-low spread 的 Newey-West HAC t-test；另報 Fama-MacBeth monthly slope。**不把 ticker-month pooled 起來當獨立樣本**，避免 K1355 的 asset-day pooled DM 類錯誤。

## Lookahead 防線

| 風險 | 防線 |
|---|---|
| signal 用到 forecast month | `K1359.py` 明確 `signal = feature.shift(1)` |
| rolling estimator 偷看未來 | pandas trailing rolling window，月末取當月最後一筆後再 shift |
| same-day / same-month 口徑混用 | signal at month-end `t-1` predicts month `t` outcomes |
| bootstrap 不可重現 | `SEED = 42`, bootstrap reps = 1000 |
| 跨資產 pooled false precision | 檢定單位是 monthly spread / monthly Fama-MacBeth slope |

## 成功標準

強 claim 必須同時滿足：

1. 至少 2 個 estimator 的 high-minus-low next-month return 為正，且 HAC `t >= +3`。
2. RV 或 left-tail exposure 方向支持高不對稱 basket 風險較高。
3. bootstrap CI 不與 0 衝突。

若只有 RV / left-tail 顯著、return 不顯著，只能說是 risk-state signal，不能說有 robust premium。

## 結果

Verdict：`RISK_SIGNAL_ONLY_NULL_PREMIUM`。

| Estimator | Return ann. spread | Return HAC t | RV spread | RV HAC t | Left-tail loss spread | Left-tail HAC t |
|---|---:|---:|---:|---:|---:|---:|
| `bad_skew` | +1.25% | +0.38 | +2.32 pp | +2.80 | +0.30 pp | +2.50 |
| `bad_trimmed_skew` | -0.64% | -0.16 | +2.71 pp | +2.55 | +0.38 pp | +2.46 |
| `bad_winsor_skew` | +1.46% | +0.41 | +2.75 pp | +3.00 | +0.39 pp | +3.02 |
| `max_loss_gain_gap` | +1.04% | +0.26 | +3.27 pp | +3.49 | +0.36 pp | +2.65 |
| `semivar_log_ratio` | -4.48% | -1.01 | +3.45 pp | +3.36 | +0.38 pp | +2.61 |
| `tail_mean_gap` | +2.08% | +0.51 | +3.83 pp | +4.22 | +0.42 pp | +3.06 |

Interpretation:

1. **Return premium FAIL**：0/6 estimator 通過 `t >= +3`；連 `t >= +2` 的弱 return premium 也沒有。
2. **Risk signal present**：4/6 estimator 對下一月 realized vol 或 left-tail loss 通過 `t >= 3`。
3. **結論強度**：尾部不對稱 estimator 可標記「下一月更高風險」狀態，但不能宣稱免費 ETF realized-return proxy 帶來穩健尾部溢酬。

## 圖表

- `figures/k1359_return_spreads.png`：6 個 estimator 的 return high-minus-low spread。
- `figures/k1359_tstat_heatmap.png`：return / RV / downside vol / left-tail loss 的 HAC t-stat heatmap。

## 檔案

- `K1359.py`：可重跑腳本。
- `K1359_results.json`：完整數值、config、文獻與 limitations。
- `K1359_panel.csv`：月頻 estimator-target panel。
- `data/*.csv`：本實驗用 adjusted close cache。
- `figures/*.png`：輸出圖。
- `codex_review.md`：source-level review。

## 限制

- 這不是 option-implied skew、skew swap、OptionMetrics、或 borrow-fee 資料；只是否定「returns-only proxy 足以替代」。
- 9 ETF universe 小，每月 high / low legs 只有 2-3 檔，不能過度推廣到個股橫斷面。
- 月頻 baskets 未計交易成本；此實驗是 empirical signal test，不是可上架策略。
- 若要重開，下一版應使用 option surface 或更大的 cross-section，並檢驗 regime / asset-class conditional premium。

## 重跑

```bash
uv run python experiments/k1359/K1359.py
```
