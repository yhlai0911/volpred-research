# 無 sidecar `.git/index.lock` 來源追查（canonical `assign_3e73a554`）

- 部門：platform_eng ｜ 2026-08-05（台灣時間）
- 已知實例：**2026-08-04 13:49:47**（任務描述的那顆）與 **2026-08-05 17:01:47**（本部門今天親手回收的那顆）

## 1. 這次多了一份第一手證據

08-05 那顆是本部門在 17:09 回收的：0 bytes、滯留 483 秒、`lsof` 無持有者、
全機無 git 行程，改名保留為 `.git/index.lock.stale-20260805T090147`。
兩顆的形狀完全一致（**0 bytes、無 sidecar**），可視為同一 class。

## 2. 機制：已用實驗確立，不是推測

在 scratchpad 裡建臨時 repo（400 檔）實測三種候選，各 40 次（kill 組 10 次）：

| 候選機制 | 結果 |
|---|---|
| `git status --porcelain \| head -1`（SIGPIPE 中斷 index refresh）| **0/40 洩漏 → 排除** |
| `git status --porcelain > /dev/null`（對照組）| 0/40 |
| `git add -A` 執行中被 **SIGKILL** | **5/10 洩漏，且留下的正是 0-byte lock** |

結論：**這個 class 的成因是「正在寫 index 的 git 子行程被 SIGKILL」**——
SIGKILL 不跑任何清理，所以 lock 留下、sidecar 不存在（sidecar 只由 phase_z 自建的
CAS lock 路徑寫）。0-byte 這個特徵與實驗完全吻合：git 是先 `O_CREAT|O_EXCL` 建空檔
再寫入，被殺在那之間就留下空檔。

任務描述列的三個候選裡，「git status opportunistic refresh 被中斷」**已被實驗排除**；
剩下兩個（daemon 內其他 git subprocess 被 kill、外部 session）與實驗結果一致。

## 3. 具體創建者：**未能鎖定**（不硬湊）

- `storage/ops/writer_log.jsonl` 在兩顆 lock 的時間點**都沒有任何一列**
  （08-04 05:49:47Z 前後最近的是 05:10 與 06:52；08-05 09:01:47Z 之前最近的是 08:46）。
  → 兩顆都**不是** `git_writer_lock` 正規交易建的。這一點是確定的。
- 唯一時間吻合的 daemon 事件是 `dispatch_supervisor.log:4564`
  `phase_z: orphan-half probe HEAD run did not finish (timeout)`（17:02:06，
  且這行在整份 log 裡**只出現過一次**）。但讀 `phase_z.py:2763-2772` 後要誠實說：
  那個 timeout 殺掉的是 **clone 裡的 pytest**（`_run_clone_pytest`），
  不是對主 repo 寫 index 的 git。**所以這個時間巧合並不能解釋主 repo 的 index.lock，
  我不把它當成結論。**
- 當時另有多個部門 session 在跑 git（治理部四次 commit 被擋、會員部、內容部），
  但它們的 Bash 只留 session 側紀錄，repo 這端沒有可回讀的痕跡。

**因此本輪只能結到 `contained`：class 的機制已證，個案的創建者未證。**

## 4. 為什麼「找出創建者」這條路本身就是死路

追不到不是因為找得不夠仔細，而是因為 **git 的 `index.lock` 不帶任何持有者身分**——
存在即宣告。事後沒有任何觀測能區分「誰建的」，這正是 error_log §A 規則 4 已經寫下的
那句「持有者已死必須可以被後續程序證明」。

所以正確的做法不是繼續追這一顆，而是**讓下一顆自己說出它是誰的**：

### (c) 建議修法：pre-spawn stamp

任何 daemon 內**可能寫 index 的 git 子行程**，在 `Popen` **之前**寫 owner sidecar
（pid + `ps lstart` 指紋 + host + 時間戳），子行程正常結束再清掉。
關鍵是 **pre-spawn**：現行 sidecar 只由 phase_z 自建 CAS lock 的路徑寫，
而被 SIGKILL 的子行程沒有任何機會補寫。這樣一來，被殺的 git 留下的 lock
就變成「有主的鎖」，`reclaim_leaked_index_lock()` 現行的 liveness 判定即可直接回收，
不需要放寬「無 sidecar 不准碰」。

### (b) 覆蓋策略：無 sidecar 的鎖仍需要一條有出口的路

即使 (c) 做完，外部 session（Codex、老闆手動、任何非 daemon 的 git）留下的鎖仍然無主。
現行規則「無 sidecar 一律不准碰」是 fail-closed，方向對，但**它目前沒有出口**：
今天這顆讓全部 7 個部門的 commit 同時失敗約 10 分鐘，治理部與會員部都被迫送 P1 求助，
最後靠本部門人工判斷才解開——這是紀律，不是機制（error_log 2026-08-04 已經講過同一句話）。

建議把「人工判斷」升級成**機械且留證的四項判準**（本部門今天實際使用的即是這一組）：
`0 bytes` ＋ `age ≥ 300s` ＋ `lsof` 無持有者 ＋ 全機無 git 行程，四項齊全才回收，
且處置是**改名**成 `index.lock.stale-<UTC>`（不刪除，證據留存）、寫 receipt。
缺任一項則維持不碰。這樣 fail-closed 仍然成立，但死局有了出口。

## 5. 未落地

(b)(c) 的修改面都在 `scripts/dispatch_supervisor/phase_z.py` 與周邊，
platform_eng 的 `owned_paths` 只有 `frontend-v2-fix/`，寫入被權限閘擋下。
本檔是可直接施工的規格；等經理對 owned_paths 的裁決
（`item_20260805T090132643067Z`）。
