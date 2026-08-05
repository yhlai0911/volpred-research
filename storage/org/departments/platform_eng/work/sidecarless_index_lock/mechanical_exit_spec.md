# 無 sidecar `.git/index.lock` 的機械出口規格

- 部門：platform_eng ｜ 2026-08-05 ｜ 依 D14 裁決 (c) 撰寫，**未落地**（`scripts/dispatch_supervisor/` 仍不在轄區）
- 前置：同目錄 `forensics.md`（成因已用實驗確立：正在寫 index 的 git 子行程被 SIGKILL，5/10 留下 0-byte lock）

## 0. 這份規格要解的到底是什麼

現行 `phase_z.reclaim_leaked_index_lock()` 的規則是「**沒有 sidecar 的鎖一律不准碰**」。
這個方向是對的，docstring 講的理由也成立：天真的 stale-lock cleaner 會刪掉真正
正在寫的 index。**問題不在 fail-closed，而在 fail-closed 之後沒有下一步。**

實測後果（2026-08-05）：一顆 0-byte、無 sidecar 的鎖讓**全部七個部門**的
`git_writer_lock commit` 同時失敗，治理部四次 commit 被擋、會員部與本部門收尾卡死，
持續約 10 分鐘，最後靠本部門人工判斷才解開。2026-08-04 13:49 那顆也是人工解的。
**同一個 class 兩次都靠「有人剛好在線上且剛好敢判斷」收場——那是紀律，不是機制**
（error_log 2026-08-04 已經寫過這句話，一年後還是同一句）。

所以要補的是：**一條機械的、會留證據的、且不會誤殺真寫入的出口**。

## 1. 判準（四項全滿足才回收，缺一即不動）

| # | 判準 | 為什麼是它 |
|---|---|---|
| 1 | 檔案大小 **== 0 bytes** | git 先 `O_CREAT\|O_EXCL` 建空檔再寫入。非 0 代表 index 內容已在寫，碰它就是毀掉一次真寫入。實驗中被 SIGKILL 留下的殘骸**全部**是 0 bytes |
| 2 | 齡 **≥ 300 秒** | 遠大於任何正常 index 寫入（本 repo 實測 < 2s）。避開 adopt 中途與慢碟 |
| 3 | `lsof -- <lock>` **無任何持有者** | 檔案層級的直接證據，不依賴 pid 猜測 |
| 4 | `ps` 全機 **無存活 git 行程**（排除本 repo 之外的判斷不做，寧可保守） | 對付「持有者已死但 fd 已釋放」與「另一個 repo 的 git 正在跑」兩種情況 |

**探測失敗 ≠ 通過**。`lsof` 回非 0 且 stdout 非空 → 視為有持有者；`lsof` 本身
執行失敗（找不到指令、逾時）→ **視為未證明，不回收**。這條沿用既有
`check_identity` 的 `unverified` 語意，不另立第二套。

## 2. 處置：改名，不是刪除

```
.git/index.lock  →  .git/index.lock.stale-<lock mtime 的 UTC 時戳>
```

例：`.git/index.lock.stale-20260805T090147`（本部門今天實際採用的形式；
2026-07-28 也有一顆同形式的 `index.lock.stale-20260728T030522`）。

理由：判斷若有誤，原檔還在，可以還原。而且殘骸本身就是下一次追查的檢體——
`forensics.md` 能寫出來，正是因為 07-28 那顆沒有被刪掉。

同名已存在時（同一秒內兩顆）→ 附加 `-2`、`-3`，**不覆蓋**。

## 3. Receipt（沒有 receipt 就等於沒發生）

寫入既有的 receipt 流（`_append_receipt`），不新增檔案：

```json
{
  "event": "index_lock_reclaimed_sidecarless",
  "at": "<ISO8601>",
  "lock_mtime": "<ISO8601>",
  "age_s": 483,
  "size_bytes": 0,
  "renamed_to": ".git/index.lock.stale-20260805T090147",
  "evidence": {
    "lsof_holders": [],
    "git_processes": [],
    "probe_ok": true
  },
  "actor": "phase_z.reclaim_sidecarless_index_lock"
}
```

`evidence` 是必填而非選填：一顆被回收的鎖如果說不出「當時憑什麼判它是孤兒」，
下次事故就無法回溯是回收錯了還是本來就壞。

## 4. 掛在哪（anti-stacking：不新增第二個 watchdog）

收編進**既有 owner** `scripts/dispatch_supervisor/phase_z.py`：

- 新函式 `reclaim_sidecarless_index_lock(repo_root, *, now=None, min_age_s=300)`
- 由 `reclaim_leaked_index_lock()` 在回傳 `{"reclaimed": False, "reason": "not_ours"}`
  **之前**呼叫；有 sidecar 的路徑完全不變（既有 8 條測試不受影響）
- 呼叫點沿用 `run_phase_z()` 進入時的自我回收，不新增 tick、不新增 cron

## 5. 這條出口**不能**取代真正的修法

`forensics.md` §(c) 的 **pre-spawn sidecar** 才是根治：daemon 內任何可能寫 index 的
git 子行程，在 `Popen` **之前**寫 owner sidecar，被 SIGKILL 也會留下有主的鎖，
既有回收器直接就能處理。本規格處理的是**外部來源**（Codex、老闆手動、非 daemon
的任何 git）留下的鎖——那部分永遠不會有 sidecar，所以永遠需要這條出口。

兩者的關係：pre-spawn sidecar 把「大多數」變成有主的鎖；本規格讓「剩下的無主鎖」
不再需要一個人在線上。**只做前者，全組織仍會被外部來源的鎖凍結。**

## 6. 驗證 gate（落地時必跑，且不得在主 checkout 上做）

沿用本部門今天驗證成因的方式——**臨時 repo**，不在 production checkout 上做破壞測試
（control-plane 規則明文禁止；daemon 隨時可能載入被弄壞的程式碼）：

1. `git add` 執行中 SIGKILL → 產生 0-byte 無 sidecar 鎖 → 斷言**回收成功**且 receipt 齊全
2. 真的 spawn 一個持鎖子行程並讓它活著 → 斷言 **不回收**（`lsof` 有持有者）
3. 鎖齡 100 秒 → 斷言 **不回收**（未達 300s）
4. 非 0 bytes 的鎖 → 斷言 **不回收**（真寫入進行中）
5. `lsof` 不可用（PATH 移除）→ 斷言 **不回收**（探測失敗不是通過）
6. 有 sidecar 的鎖 → 斷言走**既有**路徑，本函式不介入

第 2、5 兩條是這份規格的核心安全主張，缺任一條即視為未驗證。

## 7. 阻塞

修改面 `scripts/dispatch_supervisor/phase_z.py` + `scripts/tests/`，
platform_eng 的 `owned_paths` 目前只有 `frontend-v2-fix/`。標記 **blocked-on-D14**，
不重複開單、不繞路。
