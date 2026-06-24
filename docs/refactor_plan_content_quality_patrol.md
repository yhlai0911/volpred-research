# Refactor Plan — 內容品質巡檢（Content Quality Patrol）

**狀態**：設計完成，待實作。2026-06-24 由用戶質疑觸發（meta-root-cause）。
**為什麼最高優先**：今天 4 個問題（發文脫班 / digest 重複 / 標題排版重複 / 前端 React #418）**全部靠用戶人工發現**，根因是系統只有「基礎設施巡檢」（cron 活著、池子空否、5h 沒發文），**缺「內容品質/流程正確性/排版/前端健康」這層主動巡檢**。建立此巡檢 = meta-fix：未來這類問題系統自己抓。

## 現有巡檢的盲區
| 現有 | 層級 | 盲區 |
|---|---|---|
| ops_dashboard（:30） | 基礎設施（cron stale / alert breach） | 不看內容對不對 |
| check_alerts（hourly） | 運營 outcome（池空 / release gap / cron fail） | 不看主題/排版/render |
| 脫班 dead-man（5h） | 被動 outcome | 5h 後才知道，且不知為何 |

## 內容品質巡檢設計（新固定任務，建議每 2–6h）
出一份 `storage/ops/content_quality_report.json` + breach 時走既有 `send_alert`（接 `build_alert_condition_report`，per `.claude/rules/alert.md`）。

### 巡檢項目
1. **發文節奏健康**：作用窗（台北 9–23）內近 N 篇 published 的時間間隔分佈；過密（<30min 連發）或過疏（>3h gap）→ warn。（比 5h dead-man 早預警）
2. **主題多樣性**：近 20 篇 published + draft 池的 narrative-arc 分佈；單一 arc 佔比 > 閾值 或 distinct-arc/total < 閾值 → warn。**這會早期抓到 release deadlock 源頭（draft 池全重複 arc）。**
3. **digest 唯一性**：每日 `每日精選導讀` published 數 == 1；> 1 → alert（抓今天的重複）。
4. **排版正確性**：
   - digest title 是否與區塊 header 前綴重複（`每日精選導讀｜...` vs header）。
   - 標題格式/長度/特殊字元異常。
5. **前端 render 健康**：fetch 關鍵頁面（首頁 / digest / reports/[id]）→ HTTP 200 + HTML 不含 React error marker（#418 hydration）+ 關鍵元素存在。（抓今天的 #418）
6. **內容完整性**：published 文章有無真圖表（image ref）、來源/實驗標註（呼應 CLAUDE.md 發文規範：每篇要有真圖表 + 數據來源）。
7. **release 健康早警**：`release_pool_articles` candidates 是否連續 K 次為 0（draft 池鎖死早期信號，不等 5h 脫班）。

### Auto-remediation（接 alert SOP）
- 主題過度集中 → 派 journal-discovery 補 fresh 方向（不是 force 發重複）。
- digest 重複 → retract 多餘 + 修生成冪等。
- 前端 render 錯 → 派前端修 task。
- release candidates 連續 0 → 觸發 release-deadlock 處理（refactor_plan_release_layer_deadlock）。

## 與既有的關係
- 不取代 ops_dashboard / check_alerts（基礎設施層），而是**補內容品質層**。
- 巡檢邏輯集中在一個 module（如 `src/volpred/ops/content_quality.py`），cron wrapper `~/.volpred/bin/cron_content_quality_patrol.sh`，config 登記 `config/runtime_schedules.json`。

## 驗證 gate
- 構造今天 4 個問題的場景（脫班/digest 重複/標題重複/#418）→ 巡檢應全部 flag。
- 不誤報：正常單篇 digest、多元 arc、正常 render → 不 alert。

## 為什麼這是 meta-fix
個別修 bug 是治標；建立品質巡檢是讓系統**自己持續發現這類問題**，符合「自主運營」本意——AI 不只維持機器運轉，還要自檢產出品質。今天用戶當了一整天的人工巡檢員，這個任務就是把那個角色自動化。
