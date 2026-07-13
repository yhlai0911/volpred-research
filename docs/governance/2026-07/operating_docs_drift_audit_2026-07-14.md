# 運作指示文件 drift audit — 2026-07-14

## 結論

本輪完成四項 standing checklist，修正 9 個可直接驗證的 drift class：互動 turn 的 `ScheduleWakeup` 硬衝突、退役 dispatch log、錯誤的 path-trigger 心智模型、兩份失效的 rule frontmatter、task-type / model prose 重複、Codex paper-review 邊界、email ACK/CLOSE lifecycle、動態數量硬編，以及 `next_tasks.json` source-of-truth 矛盾。沒有新增第二套 enforcement；既有 hook、model router、dispatch state 與 task-pool lock 仍是唯一 owner。

## 稽核範圍與方法

- 比對 `CLAUDE.md`、`AGENTS.md`、13 份 `.claude/rules/*.md`、`platform-ops-manager` / `pdca-operations`、hourly dispatch prompt 與實際 hook、dispatcher、model router、runtime schedule。
- Fresh Claude Code 2.1.206 A/B：同一路徑以 Bash `jq` / Grep 查詢不載入 path rule；內建 Read（即使因檔案過大失敗）會載入。故 `paths:` 只能依賴 Read/open，不可把 `rg` / `jq` 當 trigger。
- 讀 `config/runtime_schedules.json` 與 `storage/ops/dispatch_state.json` 驗證 2026-07-04 cutover 後的 canonical health source。
- 比對 queue 真實 task types、`task_pool_claim.py::CODEX_ELIGIBLE_TASK_TYPES` 與 `scripts/model_router.py`。

## Findings 與處置

| 等級 | Finding | Evidence | 本輪處置 |
|---|---|---|---|
| Critical | platform skill 要求任何 turn 最後呼叫 `ScheduleWakeup`，但互動 hook 會 exit 2 deny | `CLAUDE.md` + `scripts/hooks/deny_wakeup_interactive.py` | 分離 interactive / autonomous path；互動以文字收尾，OS backbone 負責 persistence |
| Critical | ops health 仍 grep 已退役 `hourly_dispatch.log` | runtime schedule 已標 deprecated；supervisor state 有 heartbeat / completions | protocol 改讀 `dispatch_state.json`；skill 的重複 4-step prose 縮成 pointer |
| Critical | CLAUDE 把 Bash query 誤算成 path trigger | fresh-session A/B | 重寫 path-trigger 原則；publishing 選題前改為顯式讀 rule/skill |
| High | `experiments.md`、`frontend-and-deploy.md` byte 0 是 LF，導致 frontmatter 不被識別、startup 全域載入 | 兩檔原首 bytes `0a2d2d2d` | 移除首空行；13/13 rules 現均以 `---` 起始 |
| High | model / effort / topology 同時存在 code 與 prose，task-type count 已漂移 | audit 起點的固定數量為 CLAUDE=11、playbook=10、routing heading=13；queue 另有 `telegram_reply`，Codex gate 另有 `code_review` | routing / hourly prompt 移除固定 inventory 與 model ladder；router 補 `telegram_reply`、`code_review` mechanical mapping，測試鎖住 Codex-eligible coverage |
| High | `paper_review` prose 只許 Codex 小修，但 claim gate 允許完整 review | `task_pool_claim.py` eligibility | 對齊為 Codex 可做完整 read-only review/report；結構性 `.tex` 寫入必改列 `paper_body` |
| High | `email_reply` routing 還寫 plan+close，但正式流程已改為收件 ACK + 完工 CLOSE | gmail-poll / hourly PHASE 0 已明定 ACK owner | routing 改成 gmail-poll 單次 ACK、hourly 執行與 CLOSE，避免重複寄 plan email |
| Medium | alert、worktree、receipt、CLI version 等動態數字硬編後過期 | alerts registry 28 conditions；`agy --version`=1.1.1；worktree test 已擴充 | 改成 canonical command / code pointer；歷史段落保留當時數字，不冒充即時 inventory |
| Medium | AGENTS 同時稱 next_tasks canonical 與 legacy | `AGENTS.md` source-of-truth 段與 refill 段 | 統一為 `next_tasks.json` canonical pending queue；`storage/ops` 僅 receipts |

## Path-trigger 時序結果

- `agent-delegation` / `task-routing` 補上其真正 SoT：`config/models.json`、`scripts/model_router.py`、`docs/workflow-index.md`、brief / prompt 與 task-pool paths。
- `publishing` 補 `config/article_series.json`、`scripts/series_registry.py`；`worktree` 移除不存在的 bootstrap script，補 `.codex/worktrees/**` 與 reclaim script。
- 重要限制已寫回 bootstrap：上述 paths 只對內建 Read/open 有效。selection 若只跑 Bash，必須由 CLAUDE pointer、dispatch prompt 或顯式 skill load 提前載入。

## Anti-stacking

- `CLAUDE.md` 不再複製 autonomous 4-step；唯一程序 owner 是 `storage/ops/autonomous_loop_protocol.md`。
- `platform-ops-manager` 不再複製 protocol commands / interval table。
- `task-routing` 與 hourly prompt 移除固定 task inventory、model / effort 欄與硬編 ladder；唯一 mechanical owner 是 `scripts/model_router.py`。

## 已知 residual（已 materialize follow-up）

1. `.agents/skills` 是目前 Codex discovery surface，但被 gitignore；26 個共享 skill 中有 18 個與 `.claude` 不同，而 `agent-specs/` canonical source 幾乎為空。由 `governance_agent_surface_model_config_parity` 修 ownership / render gate，並一併釐清 `config/models.json` 對 Fable 的互相矛盾 availability。
2. `daily_checkup.py` 有 wrapper、沒有 canonical host schedule；本輪把「已排每日 cron」更正為 GAP，由 `platform_ops_materialize_daily_checkup_schedule` 落實 schedule，不以散文假裝已自動化。

## 驗證

```text
uv run pytest tests/test_model_router_topology.py tests/test_agent_spec.py -q
13 passed

bash scripts/tests/test_deny_wakeup_interactive.sh
PASS 5 / FAIL 0

bash scripts/check_skills_complete.sh --json
missing_skill_md=[]; empty_frontmatter=[]; dead_references=[]; workflow_drift=[]

jq empty config/runtime_schedules.json
exit 0

all .claude/rules/*.md first 4 bytes
13 × "---"
```

## Cadence

下一個日期化 instance：`governance_self_revise_operating_docs_20260721`。它先以 `blocked_until=2026-07-20T19:00:00+00:00` 等待，沿用 hourly `unblock_expired_blocked_tasks.py --apply` 到期轉 `pending`；不重用固定 id，也不在完成後立即 pending 造成下一班重跑。
