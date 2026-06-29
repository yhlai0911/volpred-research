---
name: data-collection-ops
description: >
  資料收集 / 更新的常態運營流程 —— 所有資料 job 的排程、時效窗口、新鮮度判準、
  靜默落後偵測、手動 recovery 指令。觸發時機：每日大體檢 data_freshness 維度有 finding、
  「績效/資料卡在舊日期」、資料 job 疑似沒跑、要手動補資料、要新增資料源 job。
  Trigger phrases: '資料沒更新', '績效卡在', '資料落後', 'daily_update', 'collect_us',
  'collect_tw', 'twse_orderflow', '補資料', '資料新鮮度', 'data freshness', 'data recovery'.
  Do NOT use for: 資料源代碼/欄位查詢（external-data-sources）、實驗用資料分析（autonomous-research）。
---

# 資料收集 Ops（常態資料更新流程 + recovery）

2026-06-30 incident：collect_us 3 天沒跑、twse_orderflow 12 天沒補、daily_update 因
時間點抓到舊資料 → 線上績效卡在 6/26，全靠老闆發現。根因：無「資料 job 新鮮度」廣域監控
+ 無 recovery SOP。本 skill 把這常態工作固化。

**致命提醒**：盤中 / tick / order flow 類資料有**收集窗口**，錯過可能**永久無法補**。
EOD（yfinance / FRED）多半可 backfill。判斷「是否時效性」決定急迫度。

## 資料 job 全表（排程 + 時效窗口 + recovery）

| job | 排程(cron) | 抓什麼 | 時效性 | recovery 指令 |
|---|---|---|---|---|
| `daily_update` | `3 8 * * 1-6` + **新增 `5 15 * * 1-5`**（台股盤後，期貨需 14:30-15:00 才齊） | paper_trading + market_daily + 策略 metrics + sync | EOD 可補 | `uv run python scripts/daily_update.py` |
| `collect_us` | `3 7 * * 2-6`（跳週一；週二抓週一 EOD） | 美股 EOD（SPY/QQQ/VIX/N225…）+ SPY 5min | EOD 可補 | `uv run python scripts/collect_us*.py`（或 wrapper） |
| `collect_tw` | `0 15 * * 1-5`（台股盤後） | 台股 EOD | EOD 可補 | `uv run python scripts/collect_tw*.py` |
| `collect_twse_orderflow` | **未排程（manual）→ 應加排程** | TWSE 委託流量 backfill | ⚠️ TWSE archive 有窗口，越久越可能漏 | `uv run python scripts/collect_twse_orderflow.py` |
| `fred_backfill_guard` | 每日（週一更新 FRED） | FRED 總經 | 可 backfill | wrapper |

注意：macOS host cron 只可靠 `0 * * * *`；其餘 cron pattern 走 **piggy-back `run_due_jobs`**（讀 `config/runtime_schedules.json` 的 `cron` 欄評估 due）。改排程 = 改 config 的 `cron` 欄即可（crontab entry 不 fire），見 `.claude/rules/control-plane.md`。

## 時間點陷阱（為何「今天卻顯示前幾天」）

`daily_update` 排 `08:03` 台北 —— **早於台股收盤 13:30、也早於美股當日數據**：
- 週一 08:03 抓到的是上週五 EOD（週一台股/美股都還沒收）。
- 所以週二早上前，最新只到上週五 → 看似「卡了好幾天」（再加週末）。
- **修法（用戶 2026-06-30 指定）**：**增加**一個盤後更新點（台股 15:05，在 collect_tw 15:00 抓完之後、期貨資料已齊），保留原 08:03（美股盤前時效）。不是「改」是「加」。

## 每日大體檢的 data_freshness 維度

`scripts/daily_checkup.py` 已含 data_freshness：掃 `DATA_JOBS_EXPECTED_H` 每個 job 的 cron log mtime，超過預期 1.5× → warn、3× → critical，附 recovery 指令。**有 finding 直接跑 recovery，不只 alert。**

## Recovery SOP（發現資料落後時）

1. 跑 `scripts/daily_checkup.py` 看 data_freshness 哪些 job stale。
2. 判時效性：order flow / 盤中 / tick → 最急（搶窗口）；EOD → 可從容 backfill。
3. 直接跑對應 recovery 指令（背景跑重的，`nohup ... &` 或 run_in_background）。
4. **Check**：跑完查資料檔最新日期 / 線上 API data_date 是否前進到最新交易日。
5. 若 job 反覆不跑 → 查 cron config（piggy-back 有沒有讀到、wrapper 能不能 exec）+ 修流程不修資料。

## 新增資料源 job 時

- 在 `config/runtime_schedules.json` 加 job（id/cron/wrapper_script），piggy-back 自動接。
- wrapper 放 `~/.volpred/bin/`（TCC），canonical source 在 `scripts/`。
- 同步把新 job 加進 `daily_checkup.py::DATA_JOBS_EXPECTED_H`（否則大體檢監控不到）。
- 資料源代碼/欄位細節 → `external-data-sources` skill。

## 關聯
- `.claude/rules/control-plane.md`（piggy-back scheduler / crontab 維運）
- `.claude/skills/external-data-sources/SKILL.md`（資料源代碼）
- `.claude/skills/pdca-operations/SKILL.md`（大體檢 + 發現即修）
- `scripts/daily_checkup.py`
