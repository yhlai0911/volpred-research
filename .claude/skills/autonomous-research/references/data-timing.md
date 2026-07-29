# Data Timing and Cross-Market Alignment

這份 reference 只描述 information-set 規則。實際 collection cadence、wrapper、owner 與
receipt 每次從 `config/runtime_schedules.json` 讀取；本檔不保存排程副本。

## 1. Date label 不等於可用時間

每個輸入至少記錄：

- market timezone
- observation/event time
- official release or close time
- ingestion time
- forecast origin

yfinance 的日線 index 是交易日標籤，不是跨市場共同 timestamp。同一 label 的台股收盤
通常早於美股收盤；直接按 label merge 可能讓台股決策看到尚未發生的美股資料。

## 2. Information-set join

建立 forecast row 時：

1. 將每個 observation 轉成明確 timezone-aware availability timestamp。
2. 對每個 forecast origin，只 join `available_at <= forecast_origin` 的最新 observation。
3. 保存 source date 與 `available_at`，讓 review 能重建。
4. 市場休市時，價格可為計算目的 forward-fill，但 return 必須是 0；訊號不能假裝更新。
5. Forward label 的完整終點必須早於該 row 進入 training set 的時刻。

跨市場策略應描述「哪個市場何時收盤、下一個可交易市場何時開盤」，不能只說用了
`shift(1)` 就視為安全。

## 3. 修訂與發布延遲

FRED、官方總經及部分指數會回溯修訂：

- 優先使用 forecast origin 當時可取得的 vintage。
- 核對 first public release date；發布前的 backcast 不能作 real-time feature。
- 只拿得到 current vintage 時，結論標為 final-vintage pseudo-OOS。
- `reproduce_spec.json` 保存 series id、vintage/retrieval time、期間與 input identity。

## 4. Intraday 與 tick

- 記錄 regular/overnight session 定義、DST、auction rows 與跨午夜歸屬。
- RV sampling interval、timezone、filter 與 missing-bar rule 必須固定。
- Futures 以實際合約 identity 及可重建 roll rule 建 continuous series；不能依固定近月
  alias 猜測換月。
- 免費 API 的 intraday retention 是時間敏感限制；每次實驗前重新核對 provider 文件，
  不引用本 skill 的歷史天數。

## 5. Collection status

要確認資料是否按期取得：

1. 從 `config/runtime_schedules.json` 取得 job 與 receipt path。
2. 回讀 Operations Core terminal receipt。
3. 再回讀實際資料的最大 observation date、row count 或 hash。

只有第 2 步代表 scheduler 成功，第 3 步才代表下游收到正確資料；兩者都要保存。
