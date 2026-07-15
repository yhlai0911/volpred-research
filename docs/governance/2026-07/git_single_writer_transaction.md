# Git single-writer transaction（2026-07-15）

## 裁定與因果更正

2026-06-28 的原始 incident 並未遺失；全文在
`docs/error_log_archive/2026-Q2.md`，且原文寫的是 `Root cause TBD`。保留下來的
`AUTO_MERGE` tree 在三個 canonical 檔都帶有 `Updated upstream` / `Stashed changes`
markers，因此直接 producer 是未解的 `stash pop/apply` conflict。普通的兩個 concurrent
`git commit` 不會自己建立 `AUTO_MERGE`；現存證據也無法判定當時是哪個 process 發起
merge-class operation。

已證實的結構性問題是：多個 writer 在同一 main checkout 交錯執行 status、stage、stash、
ref adoption 與 cleanup，卻沒有共同的 transaction mutex。盤點期間，一個 brief 明寫應在
worktree 執行的 K1695 compute agent，receipt 的 cwd 實際是 main，並確實直接在 main 產生
`bdf6b451f`、`3eb7fa59a` 兩個 commit。這不是假設性風險。

## Writer inventory 與收斂點

| Surface | 新邊界 |
|---|---|
| Dispatch PHASE-Z | alternate-index candidate / gate 可並行；鎖內先驗 canonical symbolic main，再以 `update-ref refs/heads/main <new> <old>` CAS 與 shared-index refresh 完成 adoption |
| Scheduled self-commit jobs | lock 內重驗 target index ownership；literal explicit-path add→diff→commit，失敗只還原自己 target index |
| Orphan reaper | job receipt + preflight/add/commit/evidence stamp；paper、draft 先拒絕 late pre-staged collision，失敗 exact reset |
| Worktree integrator | 非 dry-run 的 auto-commit、main status/stash、merge/abort、stash restore、verification 整段一把 lease |
| Codex work-log backfills | 全部改走 CLI explicit-path commit |
| Legacy hourly dispatcher | rollback-only；若重啟，整個 main-checkout lifetime 由 CLI parent 持 lease |
| Supervisor / Codex failover | launcher cwd 是 repo 外 0700 scratch；Claude 顯式載 project settings/AGENTS。inline edit 用 canonical absolute path、Git 只歸 PHASE-Z；只有 routing 明定 worktree 才建立且本班正式 merge。Codex failover 用 exact-path lock helper |
| Interactive Codex / Claude | `AGENTS.md` 與 hourly prompt 指向同一 CLI；shell-aware pretool 禁止 shared checkout 的 add/merge/checkout/config/ref 等裸 mutation，installed main-ref hook 是最後 ref gate |
| Telegram responder | repo 外 0700 cwd；read/diagnose/reply + canonical task routing only，prompt 禁止 repo/Git mutation |
| Detached agent job | enqueue 與 runner 雙層要求 `--cwd` 是 registered non-main linked worktree |
| Rollback / stale-worktree reclaim | restore/apply/delete 與 clean-check→worktree metadata remove 各自持完整 lease |
| Raw main ref updates | common-dir `reference-transaction` hook 只驗證 inherited kernel lease + capability；default repo hook config 下，`--no-verify`、raw `update-ref main` 與 canonical `HEAD` pseudo-ref update 都不能繞過 |

`cron_git_push_backup.sh` 不在 main transaction lease 內：它先固定 `PUSH_SHA`，ahead/behind、
silent-fallback audit 與 push 都綁同一 object，最後 push
`${PUSH_SHA}:refs/heads/main`；網路等待不阻塞本機 commit，期間的新 commit 留給下一班。
nested `frontend-v2-fix` 是另一個 Git common-dir，天然取得不同 sentinel。

## Canonical contract

唯一 owner 是 `src/volpred/ops/git_writer_lock.py`；shell / interactive adapter 是
`scripts/git_writer_lock.py`。

- lock path 由 `git rev-parse --path-format=absolute --git-common-dir` 推導，main 與 linked
  worktrees 指到同一 sentinel。
- sentinel 永不 unlink / replace；取到 `flock` 後比對 `fstat(fd)` 與 `stat(path)` inode。
- `fcntl.flock(LOCK_EX|LOCK_NB)` 以 finite monotonic deadline poll；busy 回 `EX_TEMPFAIL=75`，
  `NaN/inf` timeout 直接拒絕，且不得在取鎖前 staging。
- metadata（actor、pid、token、時間、capability inode）只供驗證/診斷；kernel FD 才是 lock。不得依 TTL / pid 猜測
  force-steal，也不得刪 lockfile「解鎖」。
- CLI 只接受 repo 內的 exact file path（拒絕 `--all`、目錄、repo root、Git magic pathspec），
  並全程 `--literal-pathspecs`。取鎖後若 target 已 staged 就拒絕；commit/hook 失敗只 reset
  preflight 證明原本乾淨的 target index，working bytes 與 foreign index 保持不變。
- 外層 transaction 的 child 必須同時繼承 lock FD 與匿名 pipe capability FD；verifier 先用獨立
  probe 證明 flock 已被占用，再驗 declared FD 是原 open-file-description，並比對 metadata
  內不可由 stale token 重建的 capability inode。這避免 holder crash 後以 stale token 新開 FD
  冒充。same-process nested lease 直接 borrow，fork child 由 holder PID + at-fork clear 阻止冒充。
- `run` 把 command tree 放入獨立 session，預設 runtime cap 3600 秒；逾時或 foreground leader
  結束後先 TERM/KILL 殘留 descendants 才釋放。parent 被 SIGKILL 時 child 繼承的同一 FD
  仍持 kernel lease，直到它退出。
- common-dir `reference-transaction` hook 在 Git 的 `prepared` 階段對 `refs/heads/main` 與 canonical
  checkout 的 `HEAD` pseudo-ref fail-fast 驗證現有 lease，**絕不在 ref lock 內另取 flock**，避免
  lock-order inversion。hook 呼叫 common hooks dir 內的 self-contained verifier，並 pin
  `/usr/bin/python3` / `/usr/bin/git`，不讀可修改 working-tree helper或 caller PATH。
- `scripts/git_hooks/install.sh` 只接受 canonical symbolic main，整段持同一 lease；同目錄 temp
  file chmod 後 atomic rename，先裝 verifier、最後換 reference hook，live gate 不會被 `cp`
  truncate 成空檔而短暫 fail-open。
- 所有 canonical commit/adoption owner 都在 lease 內驗證 top-level 是 common-dir parent 且
  `HEAD=refs/heads/main`；linked worktree 的 side branch commit 仍由該 worktree owner直接處理。

## Workaround retirement

`.gitattributes` 的 broad `merge=ours` 已刪除。它會在 conflict 時靜默捨棄一側，並未保護資料；
把可見 conflict 變成不可見 data loss 不是修復。

`git_conflict_guard.py` 不再設定 `merge.ours.driver`，也不再 `git reset` shared index 或
`checkout HEAD` 覆寫作者 bytes。它現在只會在同一 lease 內刪除可證明為空的 orphan
`AUTO_MERGE`（無 MERGE_HEAD/rebase、無 unmerged entries、無 tracked markers）；ambiguous
現場完整保留並告警。

## Regression / acceptance

`scripts/tests/test_git_writer_lock.py` 用 temp repo 讓 writer A 取得 lease 後停在 transaction
中段，writer B 同時嘗試必須 rc=75，HEAD/index/worktree 完全不動；A 釋放後 B 再進，兩筆
exact-path commits 線性存在。結束時必無 `AUTO_MERGE`、`MERGE_HEAD`、unmerged index 或
`index.lock`。同檔也 pin main/linked worktree 的 lock path相同、foreign index preservation、
nested/fork、parent crash、background descendant、非 finite timeout、magic pathspec、
pre-staged collision 與 hook-failure index rollback。`test_git_reference_transaction_hook.py`
實際證明 raw commit（含 `--no-verify`）、raw `update-ref main`、canonical `HEAD` pseudo-ref、
fake-PATH interpreter、unlocked FD 與 crash 後 stale-token/capability forgery 都被擋；locked commit
可落地，registered linked worktree 的 side branch不受 main gate影響。hook installer另 pin
canonical-source refusal與 atomic replacement順序。

`scripts/tests/test_git_conflict_guard_nondestructive.py` pin 有 markers 時 bytes 與 foreign staged
entry 不動；只有空 orphan 可刪。`test_pretooluse_deny.sh` 覆蓋 direct、`command`/`env` wrapper、
quoted `-C`、`cd`、explicit git-dir/work-tree、hooksPath override、Git builtin/custom alias（含
one-shot、effective、shell 與 dynamic body）及 worktree mutation；compute queue / runner tests pin
main 或 missing cwd fail-closed。Supervisor tests證明 scratch cwd不屬任何 Git repo、顯式載
project settings，scratch建立失敗會釋放 reservation。

## 誠實限制

這是同 UID、repo-controlled writer 的 transaction boundary，不是 hostile-process security
boundary。在 installed/effective default hook config 下 raw main **ref update** fail-closed；同 UID
hostile caller仍可改 common hook bytes或用 command-local `core.hooksPath` 關掉 hook。Git 也沒有能在
`git add` 前 veto 的 repository hook：Claude path 有 project-settings pretool 提早拒絕，repo-owned
runtime writer已逐一遷移且從 repo外 scratch啟動，但任意外部 process仍可污染 shared
index/worktree。要防這類 hostile operation需不同 OS identity / read-only main `.git`，不是再疊一層
prompt。這個 lease不替代 canonical JSON 各自的 RMW data lock，也不阻止一般程式在鎖外改 working
bytes。
