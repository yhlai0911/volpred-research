# K1431 — VIX9D–VIX Spread as HAR-RV OOS Covariate (SPY Daily RV)

## 動機

短期 VRP / term-structure 文獻長期主張：當 `Δ = VIX9D − VIX > 0`（backwardation），
市場對近端波動性訂價高於中端，這往往對應隔日 realized vol 上升。常被當作「明天會放大波動」
的 leading indicator。本實驗在 SPY 日頻、HAR-RV 框架下做一個誠實的 OOS 檢驗：
**spread 本身**（不是 VIX level）是否能在純 HAR-RV 之外提供獨立的預測增量？

K1428 review 已建議優先把 realized-measure baseline 打穩再談花俏 covariate；K1430 也提醒短樣本下 deep
synthetic measure 不一定勝過樸素 measure。K1431 接在這條紀律之上。

## 假說

- **H1**：HAR-RV + `spread_lag1` 在 OOS QLIKE 上**顯著**勝過 vanilla HAR-RV。
- **Side question**：若同時放 `VIX_lag1` 作控制，spread 的增量是否仍存在？

## 資料

- yfinance：`^VIX9D`（2011-01-03 上線）、`^VIX`、`^GSPC` (SPY proxy)
- 期間：2011-02-04 → 2026-06-08，**n = 3857 日**
- Spread 描述統計：mean = −0.648, std = 2.266, min = −6.470, max = 28.090（2020-03 COVID
  high spread 反映 backwardation）

## 方法

### RV proxy
- 主：daily squared log return（Andersen-Bollerslev-Diebold-Labys 1999 daily approx）
- Robustness：|log return|

### Models（皆 OLS，log-RV 空間擬合）
- **M0 baseline**：HAR-RV = `{logRV_d, logRV_w, logRV_m}` (all `_lag1`)
- **M1 +spread**：M0 + `spread_lag1`
- **M2 +spread +VIX**：M0 + `spread_lag1 + VIX_lag1`

### Lookahead 防錯
- 所有 covariate 都明確 `.shift(1)`；rolling OOS 每步只用 `[0..t−1]` 擬合，預測 `t`。
- 程式中對應行：`df["spread_lag1"] = df["spread"].shift(1)` 等。

### 為什麼用 log-RV？
RV 在 linear 空間波動極大（squared return ~ 1e-4）且非負；直接 OLS 容易給出負值預測，
QLIKE 在負值上爆炸。標準 HAR 文獻（Andersen-Bollerslev-Diebold 2007）用 log-RV 擬合，
exp() 還原 RV，保證正值且降低 jump 影響。本實驗遵此 convention。

### Evaluation
- Rolling expanding window，min_train = 1000 → OOS window：**2015-01-28 → 2026-06-08, n = 2857 days**
- QLIKE（Patton 2011，scale-robust，主指標）；MSE 因 exp() 後極端值不穩定，僅次要參考
- DM Harvey-Leybourne-Newbold 小樣本校正（h=1）
- 子期間：2015-2017 / 2018-2021（含 COVID）/ 2022-2026（含 2022 熊市 + 2025 春）
- Robustness：|log return| 作 AV target 重跑

### Seed
`SEED = 42`，`np.random.seed(42)`；OLS 為閉式解無隨機性。

## 結果（QLIKE，越低越好）

### Full sample（OOS n = 2857）

| 比較 | base QLIKE | alt QLIKE | improvement | DM HLN | p-value |
|---|---|---|---|---|---|
| **M0 vs M1 (+spread)** | 4.629 | 4.528 | **+2.18%** | 0.617 | **0.538** |
| M0 vs M2 (+spread+VIX) | 4.629 | 3.753 | +18.93% | 5.94 | 3.2e-09 |

### Subperiods (M0 vs M1, +spread only)

| Subperiod | n | base | alt | impr | DM HLN | p |
|---|---|---|---|---|---|---|
| 2015-2017 | 738 | 4.067 | 3.879 | +4.62% | 0.86 | 0.389 |
| 2018-2021 | 1008 | 5.371 | 5.316 | +1.03% | 0.14 | 0.890 |
| 2022-2026 | 1111 | 4.329 | 4.245 | +1.96% | 0.53 | 0.595 |

### Subperiods (M0 vs M2, +spread+VIX) — side finding

| Subperiod | n | impr | DM HLN | p |
|---|---|---|---|---|
| 2015-2017 | 738 | +12.78% | 2.21 | 0.028 |
| 2018-2021 | 1008 | +31.13% | 5.10 | 4.1e-07 |
| 2022-2026 | 1111 | +9.04% | 2.25 | 0.025 |

## 結論

**Verdict: NULL** for the stated hypothesis H1.

1. **VIX9D−VIX spread 單獨無增量**：HAR-RV 已經抓住短期波動 persistence；spread 在
   M0 上加 covariate 的全期改善只有 +2.18%，p = 0.54；**0/3 子期間**達 p<0.10。
2. **VIX level 才是「短期 VRP 文獻效應」的真正來源**：M2 加入 VIX_lag1 後改善
   +18.9%、p≈3e-9，三段子期間全部顯著。這跟 Bollerslev-Tauchen-Zhou (2009) VRP 文獻
   方向一致 — VIX 本身就是 next-day vol 的 leading indicator。
3. **Implication**：把 "term-structure spread" 包成 short-term VRP proxy 有理論吸引力，但
   在 OOS 上**沒有打贏 vanilla HAR-RV 的增量**。要做交易訊號應該直接看 VIX level，
   不是 VIX9D−VIX spread。

這是 honest NULL：spread 故事在 OOS 上不成立，但**並非沒有 publishable insight** —
它清楚劃出「VIX 是有用的、但 spread 不是 incremental 來源」這個分界，避免社群被
spread sign-flip 文章誤導。

## 限制

1. **RV proxy 是 daily squared return，不是 5-min RV**。daily proxy 有強 measurement noise；
   未來若 SPY intraday 樣本 ≥ 252 日，應重做 5-min HAR-RV target。
2. **OLS linear 模型**；可延伸 HAR-Q（Bollerslev-Patton-Quaedvlieg 2016）或 HAR-CJ。
3. **單一資產（SPY/SPX）**；跨指數 / 跨資產（QQQ、^NDX、^RUT）為未來方向。
4. **OOS 起始 2015-01-28**（min_train=1000）；VIX9D 2011 前不存在，無法延伸更早。
5. **MSE 在 log-RV exp() 空間不穩**（rare 大預測值放大誤差）；QLIKE 是主要指標，
   MSE 結果僅作為次要參考，不參與 verdict。

## 文獻

1. Corsi, F. (2009). *A Simple Approximate Long-Memory Model of Realized Volatility.* JFE.
2. Patton, A. J. (2011). *Volatility forecast comparison using imperfect volatility proxies.* Journal of Econometrics.
3. Bollerslev, T., Tauchen, G., & Zhou, H. (2009). *Expected stock returns and variance risk premia.* RFS.
4. Andersen, T. G., Bollerslev, T., Diebold, F. X., & Labys, P. (1999). *The distribution of realized exchange rate volatility.* JASA.
5. Harvey, D., Leybourne, S., & Newbold, P. (1997). *Testing the equality of prediction mean squared errors.* IJF.
6. Bollerslev, T., Patton, A. J., & Quaedvlieg, R. (2016). *Exploiting the errors: A simple approach for improved volatility forecasting.* Journal of Econometrics.

## 三件套

- `README.md`
- `k1431.py`
- `k1431_results.json`
- `k1431_oos_qlike.png`
- `k1431_spread_regime.png`

## 復現

```bash
uv run python experiments/k1431/k1431.py
```
