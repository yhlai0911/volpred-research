# experiment_0dte_intraday_overnight_vol_2026_06_13

## 研究問題

0DTE 普及後，SPY 的 realized variance 結構是否從原本的「隔夜 vs 日內」分配出現可驗證的斷裂？本實驗用日頻 OHLC 拆出兩段變異，先做描述統計，再以 `2022-04-18`（Cboe 上線週二到期）與 `2022-05-11`（週四到期補齊，達成每個交易日皆有到期）為制度節點，做固定斷點與簡化 DiD 檢定。

## 動機與差異化

- `research_program.md` 已明列此題為待做方向，但現有 repo 尚無對應三件套。
- 既有文獻對 0DTE 對波動的影響有**相反結論**：有研究指出 0DTE 提高 intraday / close-to-close volatility，也有研究指出流動性提供者的 hedging 平均降低波動。
- 本實驗不直接估計 option gamma 或 order flow，而是退一步問更穩健的結構問題：**股票指數本身的隔夜/日內變異占比是否真的改變**。
- 與 [`experiments/k1465/README.md`](/Users/yhlai0911/Desktop/volpred-research/experiments/k1465/README.md) 的差異在於：K1465 研究 weekday clustering；本題研究的是 **2022 年 0DTE rollout 的制度斷點**。

## 資料

- 資料源：`yfinance` `SPY`
- 期間：`2010-01-01` 到 `2026-06-15`（實際可用交易日至 yfinance 最新）
- 樣本：SPY 每日 `Open / Close / Adj Close`
- 調整方式：以 `Adj Close / Close` 比率聯動調整 `Open`，避免拆股/配息扭曲隔夜報酬

## 變數定義

- `overnight_ret_t = adj_open_t / adj_close_{t-1} - 1`
- `intraday_ret_t = adj_close_t / adj_open_t - 1`
- `overnight_var_t = overnight_ret_t^2`
- `intraday_var_t = intraday_ret_t^2`
- `overnight_share_t = overnight_var_t / (overnight_var_t + intraday_var_t)`
- `log_var_ratio_t = log((overnight_var_t + eps) / (intraday_var_t + eps))`

## 方法

1. 描述統計：比較 pre/post 0DTE 時期的 `overnight_share`、`overnight_var`、`intraday_var`
2. 固定斷點檢定：
   - HAC OLS：`y_t = alpha + beta * post_0dte_t + e_t`
   - Chow test：在 `2022-04-18` 固定 break
   - CUSUM：看殘差穩定性
3. 簡化 DiD：
   - `y_t = a + b1*post_t + b2*tue_thu_t + b3*(post_t*tue_thu_t) + e_t`
   - 因為 2022-04-18 起先新增週二到期，`2022-05-11` 再補週四；若真是新增到期日驅動，`b3` 應該比純 post dummy 更有訊息

## 文獻前置

1. Lou, Polk, Skouras (2019, JFE): 隔夜與日內報酬有不同經濟機制。
2. Won (2026, SSRN 4426358): 0DTE 交易與較高波動正相關。
3. The Market for 0DTE (2024, SSRN 4881008): 流動性提供者中介平均降低波動。
4. Cboe (2022): `2022-04-18` 週二到期、`2022-05-11` 週四到期，形成每日到期結構。

## 防錯規則

- 無策略回測，不涉及 same-day signal 乘 same-day return。
- 僅用已實現報酬拆解 realized variance，沒有 lookahead signal。
- `auto_adjust=False` 明確固定，避免 yfinance 預設漂移。
- 不把制度前後差異直接宣稱為因果；若 DiD interaction 不顯著，只能說是同時期整體市場狀態變化。

## 檔案

- [`experiment_0dte_intraday_overnight_vol_2026_06_13.py`](/Users/yhlai0911/Desktop/volpred-research/experiments/experiment_0dte_intraday_overnight_vol_2026_06_13/experiment_0dte_intraday_overnight_vol_2026_06_13.py)
- [`experiment_0dte_intraday_overnight_vol_2026_06_13_results.json`](/Users/yhlai0911/Desktop/volpred-research/experiments/experiment_0dte_intraday_overnight_vol_2026_06_13/experiment_0dte_intraday_overnight_vol_2026_06_13_results.json)
- `figures/*.png`

## 本輪結果

- 樣本數：`4,135` 個交易日
- `overnight_share` 平均值：
  - pre-0DTE：`0.4379`
  - post-0DTE：`0.4151`
  - 變化：`-2.28` 個百分點
- HAC post dummy：`beta = -0.0228`，`p = 0.048`
- Tue/Thu DiD interaction：`beta = -0.0117`，`p = 0.637`
- Chow fixed-break：`p = 0.069`
- CUSUM：`p = 0.046`

### 結論

可誠實報告的版本是：

1. `2022-04-18` 之後，SPY 的**隔夜變異占比小幅下降**，代表日內占比略升。
2. 但這個變化**不是由 Tue/Thu 新增到期日單獨驅動**，因為 DiD interaction 完全不顯著。
3. 因此本實驗支持的是「2022 後市場微結構整體有漂移」，**不支持**「0DTE rollout 本身明確改寫隔夜/日內結構」這種更強的因果敘事。

## 重現

```bash
uv run python experiments/experiment_0dte_intraday_overnight_vol_2026_06_13/experiment_0dte_intraday_overnight_vol_2026_06_13.py
```
