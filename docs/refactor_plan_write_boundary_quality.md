# Refactor Plan: Write-Boundary Quality + Alert Routing（品質責任移到寫入邊界）

- **建立**: 2026-07-14 19:xx（owner 2026-07-14 晚間糾正：「你不是說已經改好了嗎…立即從底層邏輯架構流程整個重構，不是修補」＋「現在是怎樣 改了也沒用？」）
- **Authority**: CLAUDE.md Three-Strike Rule；本檔是對「gate 存在但持續被穿過 / 老闆持續收到內部警報」這一 class 的三層重構
- **與 `refactor_plan_token_ops_waste.md` 的關係**: 那份處理 token/資源浪費；本份處理**品質環路的邊界錯位** — 老闆晚間看到的警報流（push held、silent fallback NEW、PHASE-Z 無基線、gate 死鎖）全部屬於本 class

## 0. 觸發證據（2026-07-14 晚間，全部實查）

1. **Gate 死鎖**（18:47）：dispatch tick 把新 pre-commit hook 部署進 `.git/hooks/`（Gate 0 要求 auditor 支援 `--index`）但沒 commit 升級後的 auditor 源 → hook 用 HEAD 舊 auditor 跑 `--index` → usage error → **所有 .py commit 被鎖死，包括修復本身**。gate 自己犯了它要抓的「測試先上、原始碼沒跟上」。
2. **Push 人質**：HEAD 帶 5 個 NEW silent fallback → push held → 之後所有無辜 commits 一起被扣（一度 ahead=24）。5 個 NEW 中 2 個是偵測器誤報（失敗已記入 `bad[]` findings）、2 個該補 warn、1 個合法 silent — 但它們能被 commit 進來本身就是穿透。
3. **PHASE-Z 無基線**（18:49）：84 檔無主 — hook 死鎖期間 + supervisor selfreload 之際基線暫態遺失（當日稍早已有「基線在 commit 失敗前被消耗」的修復，此為餘震）。
4. **老闆信箱被內部乒乓塞爆**：上述每一環都寄 email。全部屬「系統已知修法、能自癒」的類型 — 卻要老闆讀。

## 1. 三層診斷

1. **底層邏輯（domain model 錯位）**：品質責任綁在 **push/CI 時間點**（事後），但寫入者是 N 個並發 agent（interactive / hourly dispatch / codex loop / phase_z / compute worker）。「先寫壞、後面攔、寄信修」的模型保證老闆看到失敗流。正確模型：**每個 writer 的「完成」定義內建 gate-green**（write-boundary）；push/CI 只是最後防線，常態下永遠不咬。
2. **流程（alert 路由錯位）**：有機械修復路徑的 warn（push held / baseline missing / fallback NEW）直送老闆信箱，違反 `feedback_alert_is_a_task_not_a_chore`（只有老闆能處理的 alert = 設計失敗）。正確流程：此類 alert **只建 P1 task 不寄信**；自動修復連續 ≥2 班失敗才升級 email。
3. **程式架構（共用 checkout 的並發寫入）**：所有 dispatch 類 tick 直接寫主 checkout，PHASE-Z 靠基線快照猜作者。實驗類已有 worktree 隔離 + merge gate；platform_ops / governance 類沒有。長期解 = 擴大 worktree 紀律到全部 dispatch 寫入（大工程，分階段）。

## 2. Workstreams 與狀態

| # | 項目 | 層 | 狀態 |
|---|---|---|---|
| 1 | 5 個 fallback 站點修復（2 warn + 3 silent-ok）+ push 解封 | 止血 | ✅ ceed60567（strict new=0；ahead=0 已推） |
| 2 | Gate 契約原子性落地（auditor `--index` + hook 源同 commit） | 止血 | ✅ ceed60567（用設計好的 bootstrap 逃生口） |
| 3 | **Gate -1：hook 部署/源原子性自檢** — 部署副本 ≠ 源 → 任何 commit 被擋，死鎖 class 消滅 | 邏輯 | ✅ 384e3612f（break-then-verify：弄歪會咬、同步會過） |
| 4 | **Alert 分層**：`git_push_backup` hold / `phase_z` baseline / silent-fallback NEW 三類改「auto P1 task + 不寄信；連續 2 班自動修復失敗才 email」 | 流程 | ✅ `alert_routing_internal_remediable`：stable-key P1、explicit resolve、兩次 completed repair 後升級 |
| 5 | 偵測器精度：audit_silent_fallbacks 認得 `bad.append` / findings-collector 類 observable 出口（本次 2 個誤報的 class） | 流程 | ✅ 同任務完成：只接受 local empty-list + exception payload + unconditional returned collector 的保守 AST proof |
| 6 | **Writer 隔離擴大**：platform_ops/governance dispatch 改 worktree + gate-green 才 merge（比照實驗紀律） | 架構 | 📝 設計完成待 owner 核准：`docs/dispatch-writer-isolation-design.md`；尚未改 supervisor/runtime |
| 7 | 完成定義機械化：dispatch prompt 的「完成」檢查表加一行機械項 — 收工前 `git status` 乾淨（自己的檔都 commit）+ strict audit new=0 | 流程 | ✅ 已在 dispatch prompt HARD RULE（本次補強 pointer 至本檔） |

## 3. 驗證 Gate
- Gate -1 已 break-then-verify（上表 #3）。
- #4 完成的 Check：連續 7 天老闆信箱只收到 boss_report/work_summary/token_report + 真需決策的 alert；內部乒乓 0 封。
- #6 動工前需 owner 過目設計（架構級變更）。
- #6 設計的首波建議只 pilot `platform_ops repo_patch`；owner 核准前不得把文件中的 proposed schema、
  landing protocol 或 routing 當成已啟用行為。

## 4. 廢棄面
- 落地 #4 後：push-held / baseline-missing 的 email 路徑退役（保留 task 路徑與 escalation email）。
- 落地 #6 後：PHASE-Z 的「基線快照猜作者」降級為 fallback（worktree 隔離下大多數檔案天生有主）。
