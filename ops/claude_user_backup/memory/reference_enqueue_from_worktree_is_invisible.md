---
name: reference_enqueue_from_worktree_is_invisible
description: 在 worktree 內跑 compute_queue enqueue 會寫進 worktree 自己的 storage/，worker 看不到
metadata: 
  node_type: memory
  type: reference
  originSessionId: 0ced801b-c57e-4491-a65d-03113ec27ccf
  modified: 2026-07-21T07:15:35.191Z
---

`scripts/compute_queue.py` 的 `ROOT = Path(__file__).resolve().parents[1]`，**錨定在腳本自己的實體位置**，`QUEUE_DIR = ROOT/storage/ops/compute_queue`。

git worktree 有自己的工作目錄副本，所以在 worktree 內跑
`uv run python scripts/compute_queue.py enqueue ...` 會把 job JSON 寫進
**worktree 的** `storage/ops/compute_queue/` —— CLI 照樣印 `enqueued: <id>`，**不會報錯**，
但 compute worker 讀的是主 repo，那份 job 等於不存在。2026-07-21 K1731 F1 踩到；
若沒手動比對主 repo 的 queue 目錄就會回報「已排入 queue」而實際沒有。

正解（走 CLI，不要手動複製 JSON —— 那是改資料不是修流程）：

```bash
uv run python /Users/yhlai0911/volpred-research/scripts/compute_queue.py enqueue ...
```

用**主 repo 的腳本絕對路徑**呼叫，ROOT 就會解析到主 repo。事後必驗：
`ls /Users/yhlai0911/volpred-research/storage/ops/compute_queue/ | grep <job-id>`。

同時注意 compute job 的 `script_path` 也是相對**主 repo root**（`cwd` 只有
`enqueue-agent` 會設）；worktree 內新寫的腳本在 branch 合併前，job 會 file-not-found 秒失敗，
可 `requeue`。相關：[[feedback_no_cd_into_worktree_before_merge]]、[[reference_compute_queue_token_split]]。
