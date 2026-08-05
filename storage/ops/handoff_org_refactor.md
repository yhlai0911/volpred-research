# Handoff：運營經理＋部門制改組（2026-08-05）

> 這份不會被 `generate_handoff.py` 的每小時重生覆蓋（那支只寫 `handoff_latest.md`）。
> 接手前先讀完本檔，再讀計劃書 `~/.claude/plans/agents-herdr-agent-ticklish-chipmunk.md`。

## 一句話現況

平台已從「單一引擎按 task_type 派工」切換為「運營經理下轄 7 部門」，**舊派工引擎已停用**
（可一鍵回滾），派工權收歸經理單一來源。組織態全在 `storage/org/`（git 管理），
重開機／移機後 `git pull` + 一個指令即完整回復。

## 架構要點（讀懂這五條就懂全局）

1. **組織即資料**：部門 = `storage/org/departments/<dept>/` 目錄（charter／memory／
   inbox／journal／state）。開／裁部門是純檔案操作（`scripts/org/org_admin.py`），不改程式碼。
2. **session 是執行體，不是身分**：身分（章程＋組織通則＋私有記憶）進 system prompt
   （`--append-system-prompt-file`），易變的工作（journal tail＋收件匣）才放訊息。
   兩半由 `_core.identity_prompt()` / `work_prompt()` 同源組合，`build_brief()` = 兩半相加。
3. **時鐘歸機械，判斷歸 agent**：`org_manager_tick`（每 30 分，launchd）跑零成本硬事實
   閘門，有事才喚醒經理。經理不排班、部門更不排班。
4. **一個隊列一個派工者**：canonical 池仍是 `storage/next_tasks.json`；
   `queue_dispatch.py` 依 task_type 歸屬派給部門，部門收到的是**指標不是副本**，
   結案走 `task_pool_claim`。
5. **併發靠機械**：`write_claim_guard`（PreToolUse）自動認領路徑，**部門是寫入者**
   （跨 session 同一身分，靠 settings 注入 `VOLPRED_ORG_DEPT`）；
   `git_writer_lock` 仍是唯一 commit 入口。

## 常用指令

```bash
uv run python scripts/org/org_attach.py restore     # 重開機後一鍵復原駕駛艙（8 個 pane）
uv run python scripts/org/org_attach.py status      # 誰在哪個 pane、路由 vs 實際、待辦數
uv run python scripts/org/queue_dispatch.py --dry-run   # canonical 池 → 部門的分佈
uv run python scripts/org/manager_tick.py --shadow  # 看閘門會不會 fire 及理由（不喚醒）
uv run python scripts/org/boss_digest.py --dry-run  # 預覽給老闆的日報
uv run python scripts/path_claims.py list           # 誰正在改什麼
curl -s localhost:8787/api/org | jq .               # 組織全景（含 blockers）
```

## 已完成（今天，逐項可驗證）

- P0 骨架＋7 部門＋經理（`45609a5bf` `b286c4693`）
- `org_manager_tick` 接電並轉為實際運作（`46b193acb` `f6d2748fb`）
- Herdr 駕駛艙：每角色一 pane、租約防雙跑（`e502e2aca`）
- 部門 model/effort 真正生效（研究/論文 xhigh、治理 low⋯）（`0ce687d11`）
- 併發寫入閘門＋path_claims CLI（`e69a0c55c`）
- token 報表根因修復＋回填（`dab112d3a`）— 7 天有 6 天日報是 0，少記 141.1M
- 一個隊列一個派工者，舊引擎停用（`b7d975351`）
- 日報排程 08:30／20:30（`0f782a608`）
- computer_use 能力宣告（FB 真 Chrome）（`0111cdc54`）
- 部門是寫入者＋經理看得到阻塞（`a17aa310c`）

## 未完成（按建議順序）

1. **老闆 Telegram 訊息即時喚醒經理** — 現在進 manager inbox 但要等下一班 tick
   （最多 30 分）。`scripts/org/org_intake.py` 有明講「未接線」的樁。
   老闆定過的規矩是急件直達，這條該補。
2. **GitHub Issues 入池** — `org_intake.py --github` 是 no-op。工作登記處是 Issues，
   但經理讀不到。
3. **部門 headless 執行** — 部門目前只能在 cockpit pane 工作。關掉 Herdr 後經理仍
   headless 運作，部門不會。真正 24/7 無人值守目前只有經理那一層。
4. **部門派 subagent** — 目前無授權。建議走 capability 宣告（同 computer_use），
   限定用途（大搜尋／大 log／隔離分析），產出由部門驗證後才落地。老闆已問過，待決定。
5. **Skill 重寫** — 只需重寫內建舊派工模型的 3–5 個 ops skill
   （platform-ops-manager、task-pool-operator、pdca-operations 等），
   其餘 32 個是方法論不受影響。刻意延到 cutover 穩定後，用 `/writing-great-skills`。
6. **治理部的 gate 全量盤點**（in flight）— 老闆反映「gate 太多動不動被鎖」，
   已派 P1 要求逐條回答：30 天擋幾次／擋對還擋錯／有沒有出路，分類處置後提案給經理。

## 已知風險與現場

- 經理收件匣曾堆到 39 件；日報排程上線後應自動收斂，**下一班 20:30 要確認真的寄出**。
- `platform_eng` 囤 80 件 canonical 任務、研究部只有 7 件 —— ops 吃掉研究，
  已寫進經理章程要它提出優化，追蹤是否真的動作。
- 舊引擎回滾方式：`config/runtime_schedules.json` 把 `paused_jobs.agent_dispatch_tick`
  搬回 `active_jobs` 即可，程式碼未動。

## 接續提示詞（可直接貼）

```
讀 storage/ops/handoff_org_refactor.md 建立脈絡，然後從「未完成」第 1 項開始：
把老闆的 Telegram 訊息接成即時喚醒經理（現在要等最多 30 分鐘的 tick）。
接完做第 2 項 GitHub Issues 入池。每項都要有測試、實測驗證、並經 git_writer_lock commit。

動工前先跑 uv run python scripts/org/org_attach.py status 確認 8 個角色都在，
以及 curl -s localhost:8787/api/org 看有沒有部門自報阻塞需要先處理。
架構／caller／影響面的問題先走 graphify query 再 grep。
```
