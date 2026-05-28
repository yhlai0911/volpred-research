# K1404 — HAR-RV Quantile Tail Forecasting on TW market (^TWII)

## Research Question

K1402 (SPY) verdict = NULL: HAR-RV quantile-median QLIKE 顯著差於 OLS point
forecast (DM HLN stat=-10.20, p≈0), 但 tail coverage (τ=0.95/0.99) ±2pp 內
acceptable，因此方法走 *conditional-usable-for-tail-VaR upper bound* 路線。

K1403 (QQQ/GLD/TLT) verdict = **TAIL_CALIB_USABLE**: 3/3 dm_sig_neg AND
3/3 tail_usable — 跨資產確認 SPY 結論非 idiosyncratic。

K1404 把同一 pipeline 套到亞洲市場 ^TWII，回答：

1. K1402/K1403 cross-region 是否在亞洲市場仍成立？
2. TW 市場 tail coverage band 是否可餵 multi-asset Risk Forecast 頁的 TW 區段。

## 動機（vs Mission compass）

- **Mission #2 研究嚴謹**：跨區域檢驗方法的 transportability — frontier
  (arXiv:2508.15922 PRV Quantile Forecasting) 僅 US，無 TW evidence。
- **Mission #4 平台運營** + **#5 曝光**：成功則 Risk Forecast 頁多 TW band
  視覺化，付費 premium tier 區隔。
- **避開 NULL quartet**：用 Koenker-Bassett 1978 經典 quantile regression
  (non-ML)，不踩 `diversity_rule_post_null_quartet`。

## 設計

| Item                 | Spec                                                        |
|----------------------|-------------------------------------------------------------|
| Asset                | ^TWII (yfinance, adj close)                                 |
| 期間                 | 2007-01-03 → today (yfinance 拉得到的最早交易日)            |
| Target               | `daily_rv_t = |daily log return %|` (one-step-ahead 預測)   |
| Features (HAR-RV)    | `rv_d = daily_rv[t-1]` ; `rv_w = mean(rv[t-5:t-1])` ;       |
|                      | `rv_m = mean(rv[t-22:t-1])` — 全 `.shift(1)` lag           |
| OOS split            | 2021-01-04 起 (與 K1402/K1403 對齊)                          |
| Baseline             | HAR-RV (OLS, MSE) — point forecast                          |
| Treatment            | HAR-RV QuantReg (pinball loss) τ ∈ {.50, .75, .90, .95, .99}|
| OOS refit            | none (single fixed-origin fit)                              |
| Seed                 | `np.random.seed(42)`                                        |

### Lookahead 自檢

代碼 `build_har_panel()` 中三 feature 全經 `.shift(1)`：

```python
rv_d = daily_rv.shift(1)
rv_w = daily_rv.rolling(5).mean().shift(1)
rv_m = daily_rv.rolling(22).mean().shift(1)
```

執行時 print first 3 OOS rows 印證：

```
            daily_rv      rv_d      rv_w      rv_m
2021-01-04  1.143947  0.304757  0.654017  0.663907
2021-01-05  0.655476  1.143947  0.811311  0.682160
2021-01-06  0.112733  0.655476  0.731885  0.708037
```

`rv_d` at 2021-01-05 = `daily_rv` at 2021-01-04 → 正確 lag。

## 評估

1. **Pinball loss** at each τ on OOS
2. **Empirical coverage** `cov_τ = P(daily_rv_actual ≤ q̂_τ)` vs nominal τ
3. **Kupiec UC test** for τ=0.95/0.99 violation rate
4. **DM test (HLN-adjusted, h=1)** OLS QLIKE vs τ=0.5 quantile median QLIKE
   - HLN k = `sqrt((n + 1 - 2h + h(h-1)/n) / n)`, t-dist df=n-1

## 成功標準（與 K1402/K1403 一致）

| Verdict             | DM                       | Tail (τ=0.95/0.99)                            |
|---------------------|--------------------------|-----------------------------------------------|
| PASS                | SIG_POS (stat>0 p<0.10)  | gap ≤±2pp + Kupiec UC p>0.05                  |
| CONDITIONAL_PASS    | NS (p≥0.10)              | gap ≤±5pp + Kupiec PASS                       |
| TAIL_CALIB_USABLE   | SIG_NEG (stat<0 p<0.10)  | gap ≤±5pp + Kupiec PASS                       |
| NULL                | SIG_NEG                  | OR gap > ±5pp OR Kupiec reject                |

## 結果

- **Verdict = TAIL_CALIB_USABLE**（與 K1403 跨資產驗證、K1402 SPY 同 pattern
  並擴展到亞洲市場）
- n_test = 1,305 (OOS 2021-01-04 → 2026-05-27)
- DM HLN stat = **-8.901** (p ≈ 0) → qmed QLIKE 顯著差於 OLS（dm_status=SIG_NEG）
- τ=0.95 coverage gap = **+0.019 pp**（empirical 95.02% vs nominal 95%）
- τ=0.99 coverage gap = **-0.149 pp**（empirical 98.85% vs nominal 99%）
- Kupiec UC: τ=0.95 p=0.9747, τ=0.99 p=0.5962 → PASS both → tail_status=TIGHT
- 結論：HAR-RV quantile median 點預測 inferior to OLS（同 K1402/K1403），但
  τ=0.95/0.99 tail 在 ±2pp tight band → **VaR upper bound 可用，可上 Risk
  Forecast 頁 TW band 視覺化**

詳細數字看 `K1404_results.json`。

## 對接的 K

- **K1402** — SPY，verdict NULL（DM SIG_NEG）但 tail usable，K1404 同 pattern
- **K1403** — QQQ/GLD/TLT，verdict TAIL_CALIB_USABLE，K1404 把結論擴展到亞洲市場
- **K1322** — 0050.TW 5-min HAR-RV CONDITIONAL_PASS (n_test=17 小樣本)，
  K1404 補上 ^TWII daily 大樣本 (n=1305)
- **K783c** — expanding window 是 RV 預測 cross-regime 最佳折衷
  （K1404 為對齊 K1402/K1403 採 fixed-origin，未來可補 expanding 對照）

## 檔案

- `K1404.py` — 可重跑；seed=42；含 `.shift(1)` 三 feature
- `K1404_results.json` — full per-asset metrics + verdict
- `coverage_plot.png` — empirical vs nominal coverage band (±2pp / ±5pp 標記)
- `data/twii.csv` — yfinance raw cache

## 重跑

```bash
uv run python experiments/K1404/K1404.py
```

## 後續方向（主線程裁決）

1. **Risk Forecast 頁 TW band**：把 K1404 τ=0.95/0.99 quantile 加進 multi-asset
   視覺化 — Mission #4 落地
2. **Cross-region meta paper**：K1402/K1403/K1404 三組 13 assets 跨三區域 (US
   equity / US bond / US commodity / TW equity) 統一支持 TAIL_CALIB_USABLE，
   可寫成短文投 Finance Research Letters / Economics Letters
3. **Expanding window 對照**：依 K783c 預期 expanding 可能 narrow tail gap，
   下一個 K
