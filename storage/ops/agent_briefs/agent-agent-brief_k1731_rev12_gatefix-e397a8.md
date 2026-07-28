# K1731 armB rev12 — 修復 gate crash 後完成 rev11 驗收鏈

## 為什麼有這張單（triage 結論，診斷已做完，不要重做）

上一個 job `agent-brief_k1731_rev11_freeze_integrity-1fc0fd` 的
`process_exit_code=0`（**實驗腳本本身跑完了**），但 `failure_reason=experiment_gate_failed`
（job exit 4）。失敗的不是 gate **violation**，是 gate 自己 **crash**：

```
File "scripts/experiment_gates.py", line 157, in _scan_dm_hac
    for finding in dm_hac.scan_file(path, _candidate_root(path)):
TypeError: scan_file() takes 1 positional argument but 2 were given
```

**根因已定位到唯一一個檔案（主線程已逐一比對，不要再擴大搜尋）**：

| 檔案 | worktree | main | 狀態 |
|---|---|---|---|
| `scripts/audit_dm_hac_lag.py` | `scan_file(path)` — 1 arg（33,091 B） | `scan_file(path, root=REPO_ROOT)` — 2 args（33,478 B） | ❌ **唯一不一致** |
| `scripts/audit_mdd_scale_artifact.py` | `scan_file(path, root=REPO_ROOT)` | 同 | ✅ |
| `scripts/audit_nested_dm_misuse.py` | 多參數版 | 同 | ✅ |

worktree 的 `scripts/experiment_gates.py`（45,433 B，含本輪新增的 gate/測試；main 只有
26,282 B）四個呼叫點 `:149 :157 :165 :173` **全部**傳 `_candidate_root(path)`。三個 callee
接受，只有 `dm_hac` 是舊簽章 → 在 `:157` 炸掉，且它排在 `_scan_mdd`（`:165`）之前，
**後面的 gate 一個都沒跑到**。

main 版 `audit_dm_hac_lag.py:671` 的 docstring 明寫：`root` 是 site key 的相對基準，
**linked worktree 必須傳自己的 root**，否則 ratchet 會錯位。所以正確方向是把 worktree 的
`audit_dm_hac_lag.py` 更新到 main 的版本，**不是**把呼叫點的第二個參數拿掉去遷就舊簽章
（那會讓 ratchet 用錯 root），更不是放寬或跳過 gate。

## Worktree

`/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731`

## 已知現況（主線程實測，可直接採信）

- `experiments/k1731/k1731_armB_rev11_freeze_selfcheck.json`（21,091 B, mtime 07-28 22:07:58）
  已存在且自述 `entries_total=43 / entries_matched=43 / mismatches=null` ——
  即 round 10 那個 3/35 byte 不符的問題，這輪的原子化重凍結**看起來**已解決。
- `experiments/k1731/k1731_armB_rev11_freeze.txt`（5,718 B, 61 行）同時間產出。
- **但 gate 沒跑過 = 這兩個產物 UNCERTIFIED**。不得直接當成功採用，也不得因為
  「數字看起來對」就跳過驗收。

## 工作項（依序，任一項不過就停手回報，禁止放寬標準求過）

1. **修 gate crash**：把 worktree 的 `scripts/audit_dm_hac_lag.py` 更新為 main 的版本
   （帶 `root: Path = REPO_ROOT` 參數那版）。只動這一個檔；若發現還有其他簽章不一致，
   列出來回報，不要順手大改。
2. **重跑 gate**：`python3 scripts/experiment_gates.py run --target experiments/k1731`
   （或該腳本的正式用法）。必須真的跑完並回報每個 gate 的結果。若這次跑出**真正的
   violation**（不是 crash），照實回報、不要修改 gate 或門檻去讓它過。
3. **獨立重算凍結完整性**：自己重算 `k1731_armB_rev11_freeze.txt` 每一條 entry 的 sha256，
   確認與 selfcheck.json 的 `entries_matched == entries_total` 一致；並比對 manifest mtime
   vs 各檔 mtime，確認凍結後沒有再寫入。**不要採信 selfcheck.json 自述的數字**，要自己算。
4. **測試**：`uv run pytest scripts/tests/test_experiment_gates.py -q` — 三個新測試必須綠、
   且無回歸。
5. **artifact gate**：`python3 scripts/check_experiment_artifacts.py check --path experiments/k1731`，
   並驗 `reproduce_spec.json` 的 entrypoint sha/size 與 disk 上的實驗腳本一致
   （AGENTS.md 2026-07-22 K1708 教訓：spec 必須描述真正跑出結果的那份程式）。
6. 1–5 全過才 commit worktree。**不要 merge**（主線程的事）、**不要寫 knowledge.json**
   （K1259：只有主線程能寫）、**不要 enqueue Codex**（收件的主線程會做）。

## 產出契約

寫 `experiments/k1731/k1731_armB_rev12_gatefix_report.json`，至少包含：

- `gate_fix`：改了哪個檔、from/to sha256 與 byte size
- `gates_run`：每個 gate 的名稱與結果（pass / violation 明細）
- `freeze_recheck`：你**自己重算**的 entries_total / entries_matched / 任何 mismatch 的檔名
  與兩邊 sha、manifest 與各檔 mtime 比對結論
- `pytest`：指令、通過數、失敗數
- `artifact_gate`：check_experiment_artifacts.py 的輸出摘要 + spec/disk sha 比對
- `status`：`READY_FOR_CODEX_ROUND_11` 或 `BLOCKED`（附具體原因）

## 禁止

放寬/跳過任何 gate；把呼叫點改成單參數以迴避 TypeError；force-remove worktree；
把 UNCERTIFIED 產物當成功結果；寫 knowledge.json；自行 merge。

**Model**: opus / xhigh (per model_router)
