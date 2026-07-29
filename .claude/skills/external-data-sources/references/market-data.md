# Market Data

## yfinance / Yahoo surface

適用於公開 market OHLCV、ETF、index 與 bounded intraday prototype。使用前以 provider
當下文件和實際 sample核對 ticker、adjustment、retention與timezone。

常用 semantic identifiers：

| Need | Typical identifier |
|---|---|
| US equity benchmark | `SPY`, `QQQ` |
| Rates / gold | `TLT`, `GLD` |
| Taiwan equity | `0050.TW`, `2330.TW`, `^TWII` |
| Volatility | `^VIX`, `^VVIX`, `^VIX3M`, `^SKEW`, `^VIX9D` |
| Crypto | `BTC-USD` |
| Futures quote | `ES=F`, `NQ=F`, `CL=F`, `GC=F` |

Identifier 存在不代表整段 history 可用或同質。

### Required checks

- Auto-adjust、split/dividend語義與 column layout
- First/last observation、missing trading days、duplicate index
- Exchange timezone與actual availability
- Intraday retention和extended-hours設定
- Cross-market joins以 availability timestamp，不以相同 date label
- 大量下載的 retry/backoff與partial response detection

0050.TW 使用 repository canonical cleaning helper，並對 split boundary做 return sanity
check；不要自行複製 correction factor。

## CBOE volatility indices

可從 CBOE official download、FRED mirror或market-data provider取得。使用前核對：

- 指數正式名稱與methodology
- first reliable date
- close time與holiday calendar
- provider間 value/date差異

既有研究結論從 knowledge index按 K-id查詢；本 source guide不保存「某指標必然有效/
無效」的敘事。

## Experiment provenance

保存 provider、identifier、request parameters、retrieval time、raw row count、
date range與input hash。API重抓可能得到修訂或不同adjustment，因此 URL/ticker本身不是
充分 identity。
