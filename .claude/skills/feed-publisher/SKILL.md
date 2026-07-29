---
name: feed-publisher
description: >
  Use when a prepared reader-facing Markdown draft must be created, updated,
  or read back through VolPred's formal feed publisher. This is the only agent
  workflow allowed to enter the feed gateway. Never edit feed JSON, article
  projections, or live database rows directly. Topic selection, prose
  drafting, release scheduling, and Facebook delivery belong to other skills.
---

# Feed Publisher

`feed-publisher` 是薄的**發布 orchestrator 與唯一 feed gateway**。內容 producer 交付草稿；本 skill 驗證並呼叫 canonical publisher，再用 local、projection 與 live surface 回讀。它不兼任寫手或排程器。

## Ownership boundary

| 階段 | 唯一責任 |
|---|---|
| 選題 | `publication-candidates` |
| 正文與證據 | 對應內容 producer；公共文字共跑 `anti-ai-style` |
| 懶人包 plan | `lazypack-infographic` |
| Feed create／update／status transition | **本 skill，僅經正式 CLI** |
| 文章池 cadence | Operations Core + canonical release settings |
| FB 文案 | 內容 producer |
| FB delivery | `fb-publishing` |

任何 agent 或 worktree 都只能產出 draft、圖與 plan；**不得 append、patch、重排或覆寫 `storage/reports/feed.json`，也不得直接寫 Supabase `articles`**。更正既有文章也必須走 update gateway。

## 1. 接受 handoff

最低輸入契約：

- reader-facing Markdown draft 路徑
- `audience`、`task_type`、預期 `status`
- evidence／experiment 路徑與資料期間
- 圖片或可重現圖表來源
- general 文章的 strict data-bound lazypack plan
- source task id；若同一任務要求 FB，另有 canonical FB-native draft

缺資料就退回 producer，不在發布階段即興補研究結論或重寫文章。

## 2. 每次都解析 live state

```bash
uv run python scripts/task_pool_control.py status
uv run volpred ops platform-cycle-summary
jq '{active_frontend, deploy: .deploy.active_service, site: .site.default_remote_url}' \
  config/project_targets.json
```

- task lifecycle 的 canonical owner 是 `storage/ops/task_pool_mode.json`；以
  `task_pool_control.py status` 對同一份 state 的 receipt 為準，不得硬編
  queued/direct mode。
- draft release mode、interval 與 next release 依 `platform-cycle-summary`、`storage/.release_settings.json` 及 `config/runtime_schedules.json`；不得在 skill 保存分鐘數或 cron。
- public base URL、active frontend 與 deploy service 只讀 `config/project_targets.json`。
- task mode 決定工作如何被擁有，**不自動決定文章 status**。文章 status 必須來自 source task／用戶指令與 publisher 當下 gate。

## 3. 發布前 gate

先讀 `.claude/rules/publishing.md` 的當前 reader-visible 契約，再執行：

```bash
uv run python scripts/anti_ai_gate.py --file <draft.md> --no-fb-mode

uv run python scripts/publish_draft.py <draft.md> \
  --audience <audience> \
  --status <draft|scheduled|published> \
  --dry-run
```

dry-run 或 anti-AI gate 非 0 就停止。不要用 bypass flag 掩蓋缺圖、重複、lazypack 或證據錯誤；豁免只能來自有記錄且可審核的真實例外。

事件文章的內容差異化可按 [event-article-templates.md](references/event-article-templates.md)，但事件排程仍由 formal event workflow 擁有。

## 4. 唯一 mutation path

### 新文章

```bash
uv run python scripts/publish_draft.py <draft.md> \
  --phase <phase> \
  --audience <audience> \
  --status <draft|scheduled|published> \
  --tags '<comma-separated-tags>' \
  --lazypack-plan <plan.json>
```

- `--lazypack-plan` 只在契約要求時傳；helper 會替 draft/scheduled 文章建立正式 compute receipt。
- 不自己呼叫 `Publisher()` heredoc，不直接改 canonical JSON。

### 更正／更新

```bash
uv run python scripts/publish_draft.py <revised.md> \
  --update <mile_id> \
  --update-action <stable-action> \
  --update-summary "<what changed and why>" \
  --sync-supabase
```

更新要保存 audit trail。若是 retraction、unpublish 或 destructive correction，改走對應 `volpred ops` command 與 incident/correction contract，不用 JSON workaround。

## 5. Projection 與 reader readback

從 publisher output 擷取真實 `mile_id`，接著：

```bash
# targeted local readback；只讀，不寫
jq --arg id "<mile_id>" \
  '.[] | select(.id == $id) | {id,title,status,audience,updated_at,details}' \
  storage/reports/feed.json

# projection convergence
uv run volpred ops feed-sync --dry-run
```

若 dry-run 顯示本次文章有 drift，才走正式 reconcile：

```bash
uv run volpred ops feed-sync --apply
uv run volpred ops feed-sync --dry-run
```

`--apply` 必須得到 acknowledged success，第二次 dry-run 必須 clean；命令 exit 0 但 effect 未 acknowledged 不能算完成。

對 `published` 文章，再由 `config/project_targets.json` 解析 public base URL，讀取對應 report route，確認 HTTP 200、標題與關鍵更正已出現。draft／scheduled 不要求提前出現在 public reader surface。

general draft 若排了 lazypack，依 `lazypack-infographic` 讀 compute receipt；沒有 terminal receipt 與文章 section，不得宣稱 reader-visible gate 完成。

## 6. Task completion

只有以下條件全過才回報發布完成：

- publisher 回傳穩定 `mile_id`
- targeted local readback 的 title/status/audience 正確
- Supabase projection acknowledged 且無本次 drift
- published 文章 live readback 正確；或 draft/scheduled 的 queue/compute receipts 已明確記錄
- 若 source task 含 FB 雙發，canonical FB draft 已 handoff 給 `fb-publishing`；是否可結束整張 source task，依其 acceptance contract 判定

回報精確列出：`mile_id`、status、gateway command、projection readback、live URL或待完成 receipt。不要以「指令沒報錯」代替下游確認。

## Progressive disclosure

- 內容硬規則：`.claude/rules/publishing.md`
- 自然語氣：`anti-ai-style`
- 選題與 pre-write dedup：`publication-candidates`
- 懶人包：`lazypack-infographic`
- FB delivery：`fb-publishing`
- CLI/schema 的最新參數：`uv run python scripts/publish_draft.py --help`、`uv run volpred ops feed-sync --help`
