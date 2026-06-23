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

## 重跑

```bash
uv run python experiments/k1365/K1365.py
```

重新抓 Yahoo：

```bash
uv run python experiments/k1365/K1365.py --refresh
```
