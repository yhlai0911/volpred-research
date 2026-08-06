#!/usr/bin/env python3
"""Move intentional generated-file governance edits into the canonical source."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "config" / "governance_shared.md"

TOKEN_HEADING = "## Token / Context 紀律\n\n\n"
TOKEN_BLOCK = """## Token / Context 紀律

### 額度緊縮的常設分層（老闆 2026-08-05 指令，不是一次性處置）

額度訊號看 **`/usage`**（All models 週用量 %）。`storage/reports/token_usage/daily_*.json` 的
billable 計數是**使用報告與成本歸屬**用的，單位不同，**不能拿來回答「還剩多少」**——兩個
儀表兩個工作。平常就要做**逐角色／逐 task_type 的用量分析**，緊縮當下才知道該砍哪裡；
沒有分析就降檔＝憑印象砍。

緊縮時一律照這個順序，不必每次重想（機械 owner＝`config/token_conservation.json` ＋
`scripts/model_router.py::pick_model`，帶 `expires_at` 自動失效，避免臨時降檔變永久降級）：

1. **絕不砍**：每日必做 —— 文章撰寫、資料蒐集、發文、boss 回覆
2. **降檔**：ops／治理／審查／查詢（checklist 型，sonnet 足夠）
3. **暫緩**：論文寫作與修改（無時效性；**暫緩不是降檔**——用降檔模型改論文比晚幾天改更糟）
4. **完全不受限**：**不耗 token 的程式運算**（compute queue、回測、模擬、資料抓取）。
   那是 CPU 不是 token，暫停它只損失研究進度、省不到額度。只有「需要 LLM 判讀結果」
   那一段才受上面三條管。


"""

OLD_DISPATCH = "**核心 dispatch 規則（inline 保留；2026-07-21 lane 重構後）**："
NEW_DISPATCH = (
    "**核心 dispatch 規則**（2026-08-05 起：「誰派工」看上面的組織層那節；這裡是"
    "**任務池本身**\n的規則，對經理的 `queue_dispatch` 與 supervisor lane 同樣成立）："
)


def update_canonical() -> None:
    text = CANONICAL.read_text(encoding="utf-8")

    if "### 額度緊縮的常設分層" not in text:
        if TOKEN_HEADING not in text:
            raise RuntimeError("Token / Context canonical anchor is missing")
        text = text.replace(TOKEN_HEADING, TOKEN_BLOCK, 1)

    if OLD_DISPATCH in text:
        text = text.replace(OLD_DISPATCH, NEW_DISPATCH, 1)
    elif NEW_DISPATCH not in text:
        raise RuntimeError("dispatch canonical anchor is missing")

    CANONICAL.write_text(text, encoding="utf-8")


def sync_and_verify() -> None:
    subprocess.run(
        [sys.executable, "scripts/sync_governance.py", "--apply"],
        cwd=ROOT,
        check=True,
    )
    subprocess.run(
        [sys.executable, "scripts/sync_governance.py", "--check"],
        cwd=ROOT,
        check=True,
    )

    for relative in ("config/governance_shared.md", "CLAUDE.md", "AGENTS.md"):
        text = (ROOT / relative).read_text(encoding="utf-8")
        if "### 額度緊縮的常設分層" not in text:
            raise RuntimeError(f"standing token policy missing from {relative}")
        if NEW_DISPATCH not in text:
            raise RuntimeError(f"current dispatch explanation missing from {relative}")


def main() -> int:
    update_canonical()
    sync_and_verify()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
