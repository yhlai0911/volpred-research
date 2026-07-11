---
name: project_canonical_write_test_leak_gate
description: 「測試寫 canonical state」bug class 的 class-level gate（tree-clean CI step）+ lock 子類；round3 branch 待 phase_z 綠後合併
metadata: 
  node_type: memory
  type: project
  originSessionId: 6dedbcb3-4ab2-438b-b166-4da6f2bb03cf
---

2026-07-10「測試不得寫 canonical `storage/` state」bug class 同日三振。三道防線分工（勿加第四層）：
- **預防** = `volpred.ops.canonical_write.guard_canonical_write()` 接在 writer（不是 caller），env 被 subprocess/`uv run`/孤兒孫程序繼承。
- **偵測（本機）** = `tests/conftest.py::_forbid_canonical_state_mutation`，盯硬編清單，天生會漏。
- **不變量（CI，class owner）** = `.github/workflows/pytest.yml` 的 `Assert the suite mutated no repo state` step = `git status --porcelain`（tracked 改動+刪除）+ `find storage config paper -newer <sentinel>`（其餘含 gitignored）。判準是「跑完 checkout 有沒有變」，不是清單。**只放 CI 不放 pre-push**（開發機 cron 本來就改那些檔）。

**關鍵教訓**：此 class 四條洩漏路徑**全部 gitignored**（`storage/ops/tasks/`、`pending_sessions.json`、`notifications/*.json`、`hourly_pregate.jsonl`、`phase_z_pre_fire_dirty.json`），`git status` 對它們永久失明 → 用 mtime sentinel 窮舉，不用 git status。**鎖是例外**：`shared_lock.sandboxed_lock_path()` **重導向**而非 raise（受測碼真的需要 fcntl 鎖；raise 會刪覆蓋率）。判準：side effect 是否為受測碼跑完所必需 → 需要就重導向，不需要就 raise。

**Round 2 的誤判**（本輪推翻）：round 2 sweep 把 3 個 `.lock` 判「用完即棄，無害」——錯。blocking LOCK_EX 會讓測試阻塞等生產 cron writer；drought LOCK_NB 單飛鎖會讓測試持鎖那班的真實補救靜默 no-op。危害在持鎖時間，不在殘留檔。另 `mark_task_blocked` 有 shadow `shared_state_lock`（同名、自己 LOCK_DIR）→ AST 測試釘死。

**合併狀態**：✅ 已合併 main（2026-07-11，commit `d04b902d9`，ff on top of 併發 session 的 `b7104106a`）。owner 直接指示 rebase+merge。合併前 phase_z 那 29 紅已由其 owner 於 43b37c3fb 修綠；rebase 後全套 **2066 passed / 0 failed**、tree-clean 自檢（porcelain+sentinel）雙空（含 `phase_z_pre_fire_dirty.json` 已不再洩漏）。rebase 唯一衝突是 error_log.md（雙方都 prepend，保留兩則）。**未 push origin**（owner 只說 merge）。tree-clean CI step 仍需一次真實 ubuntu run 變綠才算完全開通（本機/worktree 綠 ≠ runner 綠，見 error_log 同日 pytest gate 教訓）。相關 [[feedback_declare_complete_requires_class_sweep]]。
