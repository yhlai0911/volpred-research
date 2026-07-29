# TAIFEX Tick Data

## Resolve source through repository tooling

先檢查現有inventory/collector，而不是在brief寫本機archive path：

```bash
uv run python scripts/taifex_tick_inventory.py --help
uv run python scripts/collect_taifex_tick.py --help
uv run python scripts/taifex_tick_to_canonical.py --help
```

使用collector/manifest回傳的resolved source、coverage與schema evidence。正式實驗把
所用partition/file identity寫入reproduce spec。

## Contract and roll

- `TX` raw surface包含實際contract month資訊；TX1/TX2是provider alias，不是穩定的
  continuous return series。
- 每日RV可以依完成日成交量選active contract，但這是EOD selection rule，不可冒充
  same-day real-time signal。
- Return/RV不能跨contract roll gap或closed-session gap計算。
- 保存active contract、selection rule與`is_roll`。

## Schema eras

歷史CSV的column count、header、time formatting及night-session availability會改變。
Parser必須以semantic header mapping正規化，不以固定column index或日期硬切。

Required validation：

- encoding與header map
- positive price、legal time、row count
- day/night session歸屬
- auction rows
- contract month與volume
- schema-transition boundary

## RV construction

- 明確列sampling interval、timezone、session window與missing-bar rule。
- 只在同一session/contract內計算log return。
- Day、night、total RV分開保存；沒有night session的年代不可補0後當同質樣本。
- Roll與session rule必須進README、results與reproduce spec。

## Data availability

先以inventory實測coverage與gap；不要引用skill內的file count、GB數、first/last date。
Archive不完整、placeholder或尚未同步時回報blocked，不猜測資料存在。
