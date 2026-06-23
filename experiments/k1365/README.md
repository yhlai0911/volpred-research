# K1365 — 同指數 ETF liquidity-clientele concentration 作 index RV 壓力代理

## 動機

本題來自 `research_program.md` journal-discovery backlog：同指數 ETF 之間常有一檔高 turnover / 高流動性的 legacy ETF，另有較低費率或較新 share class。若短線交易需求集中到 legacy ETF，這個 liquidity-pool concentration 可能代表短線風險轉移，而不只是被動 AUM flow。

K1365 測的是 **same-index ETF 內部交易池集中度**，和既有「被動 flow / ETF ownership」題不同。這一版只使用免費可重跑的 `yfinance` OHLCV，所以定位為 proxy diagnostic，不宣稱掌握真實 NAV premium/discount、creation/redemption、歷史 AUM 或投資人 clientele。

## 相關知識庫脈絡

- `research_program.md:1148`：本題原始 backlog。
- `knowledge.json` 搜尋未發現既有 K1365 或同指數 ETF liquidity-clientele concentration 結論。
- K1439 / K1359 的方法教訓：overlapping RV target 必須用 HAC；弱 proxy 結果不可升格成強結論。

## 文獻定位

- Khomyn, Putnins, and Zoican (2024), *The Value of ETF Liquidity*, RFS：同指數 ETF 的流動性 clientele 與 fee premium 是本題的直接動機。
- Ben-David, Franzoni, and Moussawi (2018), *Do ETFs Increase Volatility?*, JF：ETF 交易可能把 liquidity/noise-trader shock 傳導到波動。
- Agarwal, Hanouna, Moussawi, and Stahel (2018/2021), *Do ETFs Increase the Commonality in Liquidity of Underlying Stocks?*：ETF ownership / arbitrage activity 與 liquidity commonality 相關。
- Box, Davis, Evans, and Lynch (2021), *Intraday Arbitrage Between ETFs and Their Underlying Portfolios*, JFE：ETF arbitrage / tracking dispersion channel 支持本題的 same-index dispersion proxy。

## 資料

- Source：`yfinance` daily adjusted OHLCV，`auto_adjust=True`。
- Requested period：2010-01-01 到 2026-06-23。
- Groups：
  - S&P 500：SPY / IVV / VOO，leader=SPY。
  - Nasdaq-100：QQQ / QQQM，leader=QQQ。
  - Russell 2000：IWM / VTWO，leader=IWM。
  - Emerging markets：EEM / IEMG，leader=EEM。

每組使用該組全體 ETF 皆有 OHLCV 的共同樣本；QQQM、IEMG、VOO 等上市日前資料不補值。

## 方法

每日建立同組 ETF 的 dollar-volume share：

- `volume_hhi = sum(volume_share_i^2)`
- `leader_volume_share = leader ETF dollar volume / group total dollar volume`
- `volume_fragmentation = 1 - volume_hhi`
- `volume_entropy = normalized entropy(volume_share)`

Primary signal 是 `leader_share_z_l1`：`leader_volume_share` 的 63 日 rolling z-score 後 **`signal.shift(1)`**。其他信號（HHI、fragmentation、entropy）是 robustness。

Target：

- `next_abs_return`
- `next_squared_return`
- `next_range_vol`
- `forward5_rv`
- `same_index_return_dispersion`
- `same_index_tracking_range`

Primary inference：

```text
z(log(target_t)) ~ z(signal_{t-1}) + z(log(target_{t-1})) + z(total_dollar_volume_{t-1})
```

用 OLS-HAC / Newey-West `maxlags=5`。Discovery bar 採 Harvey-style positive `t >= 3`；另報所有 group × signal × target regression 的 BH q-value。

## Lookahead 防線

| 風險 | 防線 |
|---|---|
| same-day signal 乘 same-day target | 所有 liquidity signal 都在程式裡明確 `.shift(1)` |
| 上市日前補值 | 每組只取全體 ETF 共同 OHLCV 樣本，不補歷史 |
| overlap target p-value 過度樂觀 | `forward5_rv` 與所有 target 統一用 HAC `maxlags=5` |
| 總成交額 shock 混同 concentration | regression 控制 `total_dollar_volume_z_l1` |
| proxy 過度宣稱 | README / results 明列未包含 NAV premium、AUM、creation/redemption、bid-ask quote |

## 成功標準

強 claim 需要至少兩個 primary leader-share tests 具有：

1. coefficient 為正；
2. HAC `t >= 3`；
3. BH q-value `<= 0.05`。

若只有單一 target 或單一 group 達標，只能給 `CONDITIONAL_PASS` 或更弱；若沒有 primary test 達 Harvey threshold，結論是 `NULL_PROXY`。

## 結果

Verdict：`NULL_PROXY`。

原始 concentration 假說沒有通過。16 個 primary leader-share tests 中，正向 HAC t 的有 8 個，但 **0 個**達到正向 Harvey `t >= 3`；BH q-value 校正後也沒有任何正向 primary hit。

| Group | Sample | N days | Mean leader volume share | Mean volume HHI |
|---|---:|---:|---:|---:|
| S&P 500 (SPY/IVV/VOO) | 2010-09-09 至 2026-06-22 | 3,969 | 0.919 | 0.852 |
| Nasdaq-100 (QQQ/QQQM) | 2020-10-13 至 2026-06-22 | 1,428 | 0.985 | 0.971 |
| Russell 2000 (IWM/VTWO) | 2010-09-22 至 2026-06-22 | 3,960 | 0.990 | 0.982 |
| EM (EEM/IEMG) | 2012-10-24 至 2026-06-22 | 3,432 | 0.805 | 0.718 |

Primary leader-share 結果摘要：

| Group | Target | beta | HAC t | BH q | Interpretation |
|---|---:|---:|---:|---:|---|
| S&P 500 | `next_range_vol` | -0.035 | -2.73 | 0.031 | 反向，未達 `t <= -3` |
| Nasdaq-100 | `same_index_return_dispersion` | +0.047 | +1.89 | 0.129 | 弱正向，不達標 |
| Russell 2000 | `forward5_rv` | -0.008 | -0.95 | 0.416 | null |
| EM | `forward5_rv` | -0.049 | -5.34 | 0.000009 | 顯著反向 |
| EM | `next_range_vol` | -0.050 | -3.22 | 0.025 | 顯著反向 |
| EM | `same_index_return_dispersion` | -0.052 | -3.02 | 0.029 | 顯著反向 |

Secondary diagnostics 顯示一個值得後續追的反向訊號：EM 組中，**fragmentation / entropy** 而非 leader concentration 領先 higher forward 5d RV。

| Group | Signal | Target | beta | HAC t | BH q |
|---|---|---|---:|---:|---:|
| EM | `fragmentation_z_l1` | `forward5_rv` | +0.0468 | +4.86 | 0.000029 |
| EM | `entropy_z_l1` | `forward5_rv` | +0.0472 | +4.87 | 0.000029 |

## 解讀

1. **原假說 FAIL**：免費 OHLCV proxy 不支持「交易量越集中到 legacy high-turnover ETF，隔日/未來波動越高」。
2. **EM 反向訊號**：EEM/IEMG 這組中，leader share 越低、交易池越分散時，下一段 forward 5d RV 較高。這可能代表壓力時流動性從 EEM 分散到 IEMG，或只是 EM ETF pair 的產品結構 / 樣本特性；不可直接推廣到所有同指數 ETF。
3. **SPY/QQQ/IWM 組高度集中**：leader share 平均 0.92 到 0.99，free-data 訊號的有效變異有限，尤其 QQQM 樣本短。
4. **不能宣稱 premium-discount channel**：此版沒有 NAV，所以 same-index return dispersion 只是 tracking / price-dislocation proxy。

## 圖表與輸出

- `K1365_results.json`：完整 structured outputs。
- `K1365_regression_table.csv`：所有 group × signal × target regression。
- `figures/leader_share_hac_t_heatmap.png`：primary leader-share HAC t-stat heatmap。
- `figures/forward5_rv_by_leader_share_quintile.png`：lagged leader-share quintile 與 forward 5d RV。
- `data/raw/*.csv`：本次 yfinance OHLCV cache。
- `codex_review.md`：source-level review。

## 後續

- 若要升級成可發佈 finding，下一版應取得 ETF NAV premium/discount、bid-ask quotes、historical AUM / shares outstanding、creation/redemption 或 ETF holdings liquidity。
- 反向 EM fragmentation 訊號值得獨立 K 題重跑，加入 EEM/IEMG NAV discount、EM stress controls（VIX / DXY / EEM volume shock）與非重疊 weekly target。

## 重跑

```bash
uv run python experiments/k1365/K1365.py
```

重新抓 Yahoo：

```bash
uv run python experiments/k1365/K1365.py --refresh
```
