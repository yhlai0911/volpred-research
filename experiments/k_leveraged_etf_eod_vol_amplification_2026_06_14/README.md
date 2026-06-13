# K: Leveraged ETF EOD Vol Amplification (SPY / QQQ underlying proxy)

**Experiment ID**: `k_leveraged_etf_eod_vol_amplification_2026_06_14`
**Date**: 2026-06-14
**Verdict**: **NULL** (hypothesis 不支持)

---

## 動機

槓桿 ETF（TQQQ/SPXL/UPRO）每日尾盤需做機械再平衡以維持 leverage 比例。文獻
（Cheng & Madhavan 2009; Tuzun 2014; Avellaneda & Zhang 2010）懷疑這些
re-balancing flow 在標的高 |daily return| 日可能放大標的尾盤波動。本實驗以 SPY 與
QQQ 5-min intraday data 作標的 proxy，檢驗此假設。

## 研究問題

以 SPY/QQQ 為標的 proxy，在高 |daily return| 日子，標的尾盤 (last 30 min) 已實現波動
是否顯著高於早盤同樣 30 min？

## 與既有 K 的差異

- **K30 (Leveraged ETF VT)**: 探討 leveraged ETF 自身 VT 策略下的 Sharpe 不變性，
  焦點在 ETF 本身的 risk-adjusted return；本實驗探討的是**標的** intraday vol pattern
  的橫斷面條件分配，scope 不同、變數不同。

## 資料

- **Tickers**: SPY, QQQ
- **Source**: yfinance（`period='60d'`, `interval='5m'`）
- **Sample period**: 2026-03-20 → 2026-06-12（59 RTH trading days）
- **Time zone**: America/New_York（RTH 09:30 – 16:00 ET）

## 方法

1. 5-min intraday OHLCV，filter `between_time("09:30","15:59")` 排除 16:00 邊界 bar
2. **每日內** 5-min log return = `log(Close).diff()` **groupby(date)**，避免跨日 overnight gap 污染第一個 bucket（Codex review high-severity issue 已修）
3. 30-min bucket realized vol = `sqrt(sum(r^2))`，bucket label = bucket 開始時間（09:30, 10:00, …, 15:30）
4. Daily log return = `log(每日 RTH 最後 5-min close).diff()`；`abs_ret` 為其絕對值
5. **分組**：
   - Median split：high vs low `|R|` (median = 0.55% SPY / 0.83% QQQ)
   - Quartile split：top quartile (Q4) vs bottom quartile (Q1)
   - All days
6. **檢定**：
   - 主：Paired t-test (close vs open bucket within day)
   - Robustness：Wilcoxon signed-rank
   - Between-group：Mann-Whitney U on `(close − open)` amplification difference (high vs low |R|)
7. **Bootstrap**：1000 次，`seed=20260614`（per-group derived seed），95% CI

## 主要結果

### Intraday vol path (mean per bucket, SPY)

| Bucket | 09:30 | 10:00 | 10:30 | 11:00 | 11:30 | 12:00 | 12:30 | 13:00 | 13:30 | 14:00 | 14:30 | 15:00 | 15:30 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| vol (%) | 0.233 | 0.187 | 0.202 | 0.167 | 0.152 | 0.143 | 0.140 | 0.157 | 0.139 | 0.125 | 0.117 | 0.126 | 0.152 |

→ **L-shape with mild EOD uptick**：open 最高，午盤最低，尾盤略升但**未超越** open bucket。

### Paired test (SPY, last vs first 30-min bucket)

| Group | n | mean_open | mean_close | mean_diff | paired-t p | wilcoxon p | amp_ratio (close/open) | bootstrap 95% CI mean_diff |
|---|---|---|---|---|---|---|---|---|
| all days | 59 | 0.234% | 0.153% | −0.081% | 1.3e-6 | 7.1e-7 | 0.654 | [−0.110%, −0.052%] |
| high |R| (median split) | 29 | 0.254% | 0.178% | −0.076% | 0.0025 | 4.5e-4 | 0.701 | [−0.118%, −0.029%] |
| low |R| | 30 | 0.214% | 0.128% | −0.086% | 1.6e-4 | 5.0e-5 | 0.600 | [−0.126%, −0.051%] |
| top quartile |R| | 15 | 0.288% | 0.209% | −0.079% | 0.011 | 0.015 | 0.725 | [−0.130%, −0.030%] |
| bottom quartile |R| | 15 | 0.224% | 0.116% | −0.108% | 0.0016 | 3.1e-4 | 0.519 | [−0.160%, −0.060%] |

### Paired test (QQQ)

| Group | n | mean_open | mean_close | mean_diff | paired-t p | wilcoxon p | amp_ratio |
|---|---|---|---|---|---|---|---|
| all days | 59 | 0.377% | 0.194% | −0.183% | 2.0e-13 | 1.2e-9 | 0.514 |
| high |R| | 29 | 0.410% | 0.217% | −0.194% | 1.5e-8 | 1.2e-7 | 0.528 |
| low |R| | 30 | 0.345% | 0.172% | −0.173% | 2.6e-6 | 5.1e-6 | 0.498 |
| top quartile |R| | 15 | 0.423% | 0.232% | −0.190% | 5.3e-5 | 1.2e-4 | 0.550 |
| bottom quartile |R| | 15 | 0.323% | 0.190% | −0.133% | 0.016 | 0.012 | 0.589 |

### Between-group amplification (high |R| vs low |R|)

| Ticker | mean high-amp | mean low-amp | Mann-Whitney p (one-sided, high > low) |
|---|---|---|---|
| SPY | −0.076% | −0.086% | **0.628** |
| QQQ | −0.194% | −0.173% | **0.667** |

→ **NULL on amplification hypothesis**：高 |R| 日的 (close − open) vol 差，與低 |R| 日**無顯著差異**。SPY 點估計甚至顯示 low |R| 日 close−open gap 更大（但不顯著）。

## Verdict: NULL

**Hypothesis 不支持**：
1. Last 30-min bucket vol **未** 顯著高於 first 30-min bucket — 反而 **低於**（paired tests 全部高度顯著朝反向）
2. 高 |daily return| 日的 close-vs-open vol 差，**未** 顯著大於低 |daily return| 日（Mann-Whitney p > 0.6）

**Caveat（必讀）**：
1. **未直接觀察 issuer rebalancing flow**：僅以標的 `|daily return|` 作 proxy
2. **樣本期間短**：~3 個月 / 59 trading days，含 macro regime 不平衡（2026 Q2）
3. **|R| 同時包含 EOD 期間**：定義上 |daily return| 在收盤後才知道，本研究是 ex-post conditional 分析，不可作為交易訊號的前瞻性 claim
4. **同日尾盤 uptick 確實存在**（15:30 bucket 比 14:00-15:00 高 ~20-30%），符合 U-shape 文獻；但**這個 uptick 與 |daily return| 大小無關**，所以不支持「leveraged ETF rebalancing → amplification」的因果機制
5. **5-min frequency 的 noise 大**，亦未做 microstructure 噪聲調整（Zhang/Mykland/Aït-Sahalia 2005 等 estimator 未採用）

## Codex Review

`codex-cli 0.137.0` review 識別出：
- **High**: first bucket 跨日 `Close.diff()` 把 overnight gap 算進 09:30 bucket → **已修**（groupby date reset）
- **Medium**: `between_time("09:30","16:00")` 邊界 → **已改** `"09:30"-"15:59"`
- **Medium**: Mann-Whitney 不適合 paired 同日 → **已改** between-group amp diff
- **Low**: bootstrap 同 seed 不同 group → **已改** per-group derived seed
- **Low**: print 處理 None → **已加 `_fmt` safety**

修正前：amp_ratio ~0.21 (SPY high |R|)，spurious 因 overnight gap；修正後：~0.70。Effect direction 一致。

## Next steps（建議）

NULL 結果下：
1. **直接資料**：要 LETF issuer-level rebalancing flow（13F 或 issuer SEC filings）而非用標的 |R| 推
2. **頻率升級**：到 1-min intraday 看 15:55-16:00 最後一根 bar（rebalancing 集中於收盤前最後幾分鐘）
3. **樣本擴展**：高頻 1-min data 通常 30 天限制，但用 5-min 可拉到 60 天，可改用 polygon.io / databento 拿 1+ 年
4. **Conditional events**：用 VIX 跳水/跳升 + LETF AUM 規模 + 日內動能等 multivariate condition 篩選 candidate amplification days，而非只用 |R|

## 主要 figures

- `bucket_vol_by_return_group_SPY.png` — 30-min bucket vol by |R| group bar chart
- `bucket_vol_by_return_group_QQQ.png`
- `event_study_amplification_SPY.png` — intraday vol path with 95% CI shading
- `event_study_amplification_QQQ.png`

## Reproduce

```bash
cd /Users/yhlai0911/Desktop/volpred-research
uv run python experiments/k_leveraged_etf_eod_vol_amplification_2026_06_14/k_leveraged_etf_eod_vol_amplification_2026_06_14.py
```

Seed = 20260614（np.random.seed + per-group derived bootstrap rng）。
yfinance `period='60d'` 每次 fetch 會更新到當前日期，欲復現 2026-06-12 為 end-date 之結果，
需固定 sample period（後續可加 `start/end` 而非 `period`）。
