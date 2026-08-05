# 池內 pending platform_ops 的寫入面分類（D14 裁決 (d)）

- 部門：platform_eng ｜ 2026-08-05 18:1x（台灣時間）
- 樣本：`storage/next_tasks.json` 中 `status=pending & task_type=platform_ops`，
  **實際 88 件**（派工單寫 86，以池為準）
- 方法：抽出每張任務 title/description 裡的所有路徑字樣，逐一歸區。
  只有「至少命中一個轄區內路徑、且**完全沒有**轄區外路徑」才算現在能動；
  完全沒提到路徑的另立一類，**不當成能動**（沒寫路徑通常代表沒交代，不是沒需求）。

## 結論（一句話）

**沒有任何一張是「只要 `frontend-v2-fix/` 就能做完」的。** 88 張裡 72 張明確指名
轄區外路徑，16 張沒指名路徑；逐張看過那 16 張後，**只有 1 張現在真的能動**，
而且它能動的原因不是路徑在轄區內，是它**根本不需要寫 repo**。

| 分類 | 件數 |
|---|---|
| 指名轄區外路徑 → blocked-on-D14 | 72 |
| 未指名路徑（逐張人工看過） | 16 |
| ↳ 其中現在真的能動 | **1** |

路徑出現次數（轄區外）：`scripts/` 80、`storage/` 39、`docs/` 15、`.claude/` 11、
`src/` 6、`paper/` 5、`config/` 3、`tests/` 2。

## 現在能動的那一張

**`deploy_verify_v3_digest_route_20260717`（P3）** — v3 導讀頁 Chrome 視覺審查。
部署與狀態碼／HTML 內容驗證 2026-07-17 已完成，**本單剩下的唯一工作是用眼睛看**：
(1) 新頁是否符合 v3 Editorial 設計語言；(2) 共用元件 V3Prose 抽出後
`/v3/reports/<id>` 有沒有被改壞——逐行比對與 build 都過了，但**沒有人看過**。

能動的原因：這是瀏覽器審查，零 repo 寫入。而且**萬一看出問題，修正面正好落在
`frontend-v2-fix/`——本部門唯一有權寫的地方**。本班依 (a)「不要再拉新工作」未啟動，
等你排序。

## 16 張未指名路徑的逐張判定

| 任務 | 判定 | 依據 |
|---|---|---|
| `deploy_verify_v3_digest_route_20260717` | **可動** | 純 Chrome 視覺審查，零寫入；修正面在 frontend-v2-fix/ |
| `ci-red-30983363179` | blocked（但近乎一鍵） | 見下節 |
| `ci-red-30884267057` / `-30911746339` / `-30973884810` | blocked | 三個各自不同的根因，修正面在 scripts/src/tests |
| 5 張 `control_gate_review_*`（dispatch_collision / task_generation / publisher_provenance_contract / candidate_silent_fallback_audit 等） | blocked | 裁決後**必須**更新 `config/control_gate_registry.json` 的 lifecycle 並回讀，`task_pool_claim` 會驗 registry Act receipt，不寫 config 就無法結案 |
| `compute_followup_backlog_adjudication_20260721` | blocked | 產出物指定寫 `storage/ops/compute_followup_backlog_20260721.md`，`storage/ops/` 不在轄區 |
| `assign_3e73a554`（無 sidecar index.lock） | blocked，**規格已備妥** | 修正面 `scripts/dispatch_supervisor/phase_z.py`；出口規格見 `work/sidecarless_index_lock/mechanical_exit_spec.md` |
| `assign_38977f4c`（CI fire 執行契約 3-strike） | blocked | scripts/dispatch_supervisor/ |
| `assign_4e4e8030`（CLI 自動升級打斷 backbone） | blocked | pin 檔與 wrapper 都在 scripts/ 與 `~/.volpred/bin` |
| 2 張 `platform_ops_release_audit_fix_mile_*` | blocked | release-pool audit blockers 走 feed/publisher 面，非本部門轄區 |
| `platform_ops_strategy_candidate_funnel_monitor_2026_07_30` | blocked | 月度 scan 產出報告，落點在 storage/ 或 docs/ |

## 附帶發現：四張 CI 紅燈**不是**同一個根因（原本假設是）

我把四張的偵測摘要拉出來比對，結果是四個**互相獨立**的失敗：

| 任務 | head | 失敗 |
|---|---|---|
| `ci-red-30884267057` | 899b31b2d | `AttributeError: 'Namespace' object has no attribute 'knowledge_ref'` |
| `ci-red-30911746339` | 2e744b57c | `New local DM implementation(s) omit HAC or use an h=1-degenerate bandwidth` |
| `ci-red-30973884810` | eba1b8783 | `assert [LocalHelperS...t', line=349)] == []` |
| `ci-red-30983363179` | dbd2402c0 | `cron wrapper manifest is out of date` |

最新那張我做了唯讀確認（`sync_cron_wrappers.check_manifest`，沒有改任何東西）：

```
manifest_missing_entry: cron_org_boss_digest.sh (new wrapper never synced)
manifest_missing_entry: cron_org_manager_tick.sh (new wrapper never synced)
```

**根因是組織遷移自己造成的**：新增了兩支 org wrapper，但沒有跑
`scripts/sync_cron_wrappers.py --render-manifest`，於是每次 push 都紅。
修法是**一道 canonical 指令**，它會重生 `config/cron_wrapper_manifest.json`——
`config/` 不在轄區，所以依 (a) 停在原地，沒有動手。

這件事值得你單獨排一下優先序，理由：CI 紅燈**對全 repo 生效**，
所有部門的 push 都掛在同一盞紅燈上，而這一張的修復成本是四張裡最低的。

## 這份分類的用法

72 張 blocked 的那批，D14 核准後**不需要重新分類**——它們指名的路徑就是核准清單裡的
`scripts/` / `config/` / `tests/`。核准當下即可整批解凍。
