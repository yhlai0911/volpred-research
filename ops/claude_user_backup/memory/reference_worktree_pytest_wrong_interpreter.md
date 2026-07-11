---
name: reference_worktree_pytest_wrong_interpreter
description: "在 worktree 裡 `uv run pytest` 會靜默掉到系統 py3.9 pytest；要用 `uv run --extra dev python -m pytest` 並載入主 checkout 的 .env.local"
metadata: 
  node_type: memory
  type: reference
  originSessionId: a32a489d-9797-47c3-90b7-011872590a1b
---

`.claude/worktrees/*` 的 `.venv` **沒裝 pytest**（只有主 checkout `/Users/yhlai0911/volpred-research/.venv` 有，pytest 9.0.3）。
`uv run pytest` 找不到就往 PATH fallback → 撈到系統 **pytest 7.4.4 / Python 3.9**，於是 `list | dict`（PEP 604）之類的 3.10+ 語法在 collect 階段就 `TypeError`，看起來像「程式壞了」，其實是跑錯直譯器。

worktree 內正確跑法：

```bash
set -a; . /Users/yhlai0911/volpred-research/.env.local >/dev/null 2>&1; set +a
uv run --extra dev python -m pytest <targets> -q
```

兩個必要條件：
- `--extra dev python -m pytest` → 強制用專案 venv 的直譯器（`python -m` 而非裸 `pytest`）
- 載入 `.env.local` → 它是 gitignored、只存在主 checkout；缺了會在 import `scripts/supabase_sync.py` 時 `RuntimeError: Missing SUPABASE_URL`

**Why**：這是 test harness 層的 silent fallback（見 [[feedback_fix_silent_fallback_immediately]] 同一類病）。症狀偽裝成語法/相容性錯誤，會誘導人去改根本沒問題的原始碼。

**How to apply**：worktree 裡看到 pytest collect 出現 `TypeError: unsupported operand type(s) for |` 或 `Missing SUPABASE_URL`，先 `uv run python -c "import pytest"` 確認 venv 有沒有 pytest，不要先懷疑程式碼。
