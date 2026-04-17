<!-- AUTO-GENERATED FROM agent-specs/. Edit canonical sources instead. -->

# Supabase Sync Checklist

建立時間: 2026-04-17（回應 market_daily silent-400 事件，已是同一 bug class 第 3 次犯）。

## 症狀模式（recurring failure class）

- 2026-03-24 `paper_trades` 缺 conflict key + 只 sync 今天 → trades=0
- 2026-04-11 Mirror API sync `except: pass` 吞 HTTP 400/401 → 5 週無備份
- 2026-04-17 `market_daily` schema drift + silent 400 → 5 天前端 /portfolio 價格空白

共通根因：`except Exception as e: print(...)` 把錯誤壓成 stderr 低聲部，無人審查。

## 新增 Supabase table sync pathway 時，必須：

1. **`CONFLICT_KEYS[table] = "primary_key_col"`** — 在 `scripts/supabase_sync.py` 最上面登記，否則重複 insert 會 409 silently drop
2. **明確 schema whitelist** — 定義 `_XXX_COLUMNS = {"col1", "col2", ...}`，`_post` 前過濾未知欄位，避免 schema drift 炸 400
3. **Backfill ≥ 30 天**，不是只同步今天 — 歷史缺口要能自動補
4. **失敗不能 silent** — sync helper 結尾必須 `print(f"  ⚠️  {table} sync: ok={n_ok} fail={n_fail}")`，`n_fail > 0` 必帶 `⚠️`
5. **寫一個 `sync_xxx_backfill(since=None)` helper**，讓 daily_update.py 或手動補回歷史都走同路徑

## 新增欄位到 `_market_daily` / `paper_trades` / 等本地 dict 時：

1. 同步更新對應的 `_XXX_COLUMNS` whitelist
2. 同步寫 Supabase migration（`docs/migration/` 或直接 SQL）
3. 若暫時不想加欄位到 Supabase：whitelist 幫你自動 strip，不會炸

## End-of-run health check（2026-04-17 已加到 daily_update.py）

`_run_sync_health_check()` 跑完 daily_update 後 query `paper_trades` / `market_daily` / `strategy_signals` 三張表的 max(trade_date)，與本地 paper_trading.json 比對。不符用 `⚠️` print。

下次 recurring-bug 第一個被抓的就是這個 health check 的 output。

## 除錯流程（當使用者回報 /portfolio 或其他頁面資料缺失）

1. 先查本機 `storage/paper_trading.json` — 欄位是否齊？
2. 再查 Supabase `{table}` — row 數 + max(trade_date) + 關鍵欄位 null 率
3. 若本機齊、Supabase 缺 → sync pathway bug（這份 checklist）
4. 若兩邊都缺 → daily_update.py 的計算 / registry bug
5. 若兩邊都齊、前端看不到 → 前端 query / schema mismatch

**禁止**：不可「手改 paper_trading.json 或 Supabase row 把缺的補上」。永遠修 pipeline，不修 row。
