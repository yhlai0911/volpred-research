# K1636 — 投資迷思驗證：「量先價行 / 爆量長黑是出貨」

**類型**：投資迷思驗證系列（老闆 TG msg154 directive）  
**主題**：檢驗成交量事件在 `SPY`、`0050.TW`、`2330.TW` 日資料中，是否能預測隔日方向、隔日報酬，以及未來一週波動。

## 結論

**myth_verdict = `not_supported_as_next_day_direction_rule`**

「量先價行」若被理解成「爆量後隔日比較容易下跌 / 爆量長黑隔日繼續跌」，本樣本不支持。12 個 primary next-day tests（3 資產 × 2 訊號 × 平均報酬/下跌機率）做 BH-FDR 後沒有任何 downside-predictive cell 通過。

| 資產 | 高量日 N | 高量日隔日均值差 | 高量日下跌率差 | mean q / prop q | 高量長黑 N | 高量長黑隔日均值差 | 高量長黑下跌率差 | mean q / prop q |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| SPY | 380 | +0.012pp | -1.05pp | 0.951 / 0.951 | 76 | +0.335pp | -5.00pp | 0.871 / 0.897 |
| 0050.TW | 585 | -0.037pp | -0.43pp | 0.951 / 0.951 | 88 | +0.090pp | -0.33pp | 0.951 / 0.951 |
| 2330.TW | 406 | +0.244pp | -5.69pp | 0.192 / 0.192 | 124 | +0.184pp | -5.29pp | 0.897 / 0.871 |

2330 的「高量日」有 raw p 值（mean p=0.032、down-prob p=0.028），但方向是**隔日偏正、下跌率較低**，不是「出貨後續跌」；而且經 12-test BH 後 q=0.192，不足以當正式發現。

真正比較穩定的是**波動，不是方向**：爆量長黑後，未來 5 日年化 realized volatility 顯著升高。

| 資產 | 高量日 forward 5d RV ratio | 高量長黑 forward 5d RV ratio |
|---|---:|---:|
| SPY | 2.03× | 2.90× |
| 0050.TW | 1.12× | 1.85× |
| 2330.TW | 1.22× | 1.42× |

一句話：爆量是壓力與資訊流的 marker，會提高後續波動風險；但不能直接升格成「隔天會跌」的方向規則。

## 動機與文獻

這個迷思常把兩件事混在一起：成交量和當天大幅價格變動的**同時關係**，以及成交量是否能預測**下一天方向**。文獻提醒兩者必須分開。

- Karpoff (1987), *The Relation Between Price Changes and Trading Volume*, JFQA：price-volume 關係強，但多半先是價格變動幅度與 volume 的同時關係。<https://www.jstor.org/stable/2330874>
- Campbell, Grossman, and Wang (1993), *Trading Volume and Serial Correlation in Stock Returns*, QJE：volume 會調節短期 return autocorrelation，因此可以檢驗，但方向未必是民間口訣想像的「爆量後續跌」。<https://academic.oup.com/qje/article-abstract/108/4/905/1899978>
- Lamoureux and Lastrapes (1990), *Heteroskedasticity in Stock Return Data: Volume versus GARCH Effects*, Journal of Finance：volume 更像資訊到達 / 波動 proxy，提醒本實驗必須把 direction 與 volatility 分開。<https://doi.org/10.1111/j.1540-6261.1990.tb05088.x>
- Lee and Swaminathan (2000), *Price Momentum and Trading Volume*, Journal of Finance：volume 和中期 momentum persistence 有關；本實驗測的是更短的日頻民間版本。<https://doi.org/10.1111/0022-1082.00280>

本專案相近知識：

- K113：日頻 volume / order-flow proxy 對 next-day volatility prediction 幫助有限。
- K160：volume-volatility 同時關係成立，lagged predictive value 弱。
- K418：台股 yfinance volume proxy 作法人情緒訊號為 comprehensive null。

## 資料

- 來源：yfinance daily OHLCV，首次下載後快取於 `experiments/k1636/data/`。
- 樣本：2010-01-04 至 2026-07-02/03，依資產可得日不同。
- 標的：
  - `SPY`：美股大盤 ETF。
  - `0050.TW`：台股大盤可交易 proxy；不用 `^TWII` volume，因 index volume 不是乾淨交易量序列。
  - `2330.TW`：台積電個股。
- 報酬：simple `pct_change` on adjusted close when available。
- seed：`1636`；bootstrap reps：10,000。

## 方法

### 事件定義

- **高量日**：`log(volume[t])` 高於前 252 個交易日 rolling 90% 分位數；rolling threshold 用 `shift(1)`，不含當日 volume。
- **2x 爆量日**（secondary）：`volume[t] >= 2 × 前 60 日 rolling median volume`；rolling median 同樣用 `shift(1)`。
- **長黑 / down day**：當日 adjusted close-to-close 報酬 `<= -2%`。這只作為事件條件，不把同日跌幅當作預測結果。

### 目標與檢定

- Primary target：`ret[t+1]` 與 `P(ret[t+1] < 0)`。
- Secondary target：`T+1..T+5` 累積報酬與 forward 5d realized volatility。
- 平均報酬：event vs non-event Welch t-test + bootstrap CI。
- 方向機率：two-proportion z-test + Fisher exact p-value + bootstrap CI。
- 多重檢定：primary 12 tests 用 BH-FDR。
- 連續訊號 robustness：`next_ret[t+1] ~ log_vol_surprise[t] + ret[t] + abs_ret[t]`，HAC maxlags=5。

## 防錯對照

- **Lookahead**：rolling volume 門檻全部用 `shift(1)`；程式也產生 `signal.shift(1)` 的 target-date audit 欄位。
- **隔日對齊**：事件日 t 的訊號對 `next_ret = ret.shift(-1)`；forward RV 只取 `t+1..t+5`。
- **同日不當預測**：same-day return/volume 只報 descriptive，不作為預測證據。
- **重疊窗口**：5d forward RV 是 secondary risk result；不把它混入 next-day direction verdict。
- **多重檢定**：12 個 primary p-values 做 BH-FDR，2330 raw p 不當成正式通過。
- **Null result**：方向迷思如實判定不支持；波動升高另列為風險條件。

## 檔案

- `k1636.py`：完整可重跑實驗。
- `k1636_results.json`：統計結果與 verdict。
- `fig1_next_day_mean_diff.png`：primary 訊號的隔日平均報酬差。
- `fig2_next_day_down_prob_lift.png`：primary 訊號的隔日下跌機率差。
- `fig3_forward_volatility_ratio.png`：事件後 5 日 realized volatility ratio。
- `codex_review.md`：source-level review。

## 復現

```bash
uv run python experiments/k1636/k1636.py
```
