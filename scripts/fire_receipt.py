#!/usr/bin/env python3
"""Record WHY this dispatch fire changed the tree. The agent's entire PHASE Z.

The dispatched agent does NOT run `git add` / `git commit` any more. PHASE-Z
(`scripts/dispatch_supervisor/phase_z.py`) is the single owner of committing a
fire's output, and it already knows — from the fire-start baseline — exactly which
paths this fire produced. It knows that better than the agent, which can only
recall what it thinks it touched; that guess is what swept three other sessions'
half-finished edits into a dispatch commit (docs/error_log.md 2026-07-10).

What PHASE-Z cannot know is *why*. That is the one thing left to the agent, and
this is how it hands it over:

    uv run python scripts/fire_receipt.py \
        --task-id k1702_followup \
        --subject "K1702 收件：raw-MDD 改善是 scale artifact，降級 R3 措辭" \
        --body "全量掃 knowledge.json 命中 12 筆；K1265b 補跑 vol-normalized MDD。"

Skipping this call does not lose work — PHASE-Z still commits, with a generated
message, and raises a warn so the audit gap is visible. The failure mode is a
worse commit message, never a dirty tree. That is the whole point of the 2026-07-13
refactor (docs/refactor_plan_agent_output_ownership.md).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dispatch_supervisor.phase_z import write_fire_receipt  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--subject", required=True,
                    help="一句話 what changed | why（會成為 commit subject）")
    ap.add_argument("--body", default="",
                    help="細節：掃了什麼、改了什麼、驗證方式（成為 commit body）")
    ap.add_argument("--task-id", default="",
                    help="next_tasks.json 的 task id，用於反查")
    ap.add_argument("--repo-root", default=str(REPO_ROOT))
    args = ap.parse_args(argv)

    ok = write_fire_receipt(
        Path(args.repo_root),
        subject=args.subject,
        body=args.body,
        task_id=args.task_id,
    )
    if not ok:
        # Non-fatal by design: a failed receipt must never fail the agent's task.
        # PHASE-Z will commit anyway and warn about the missing account.
        print("[fire_receipt] 無法寫入 receipt — PHASE-Z 仍會 commit，但訊息是自動生成的",
              file=sys.stderr)
        return 1
    print(f"[fire_receipt] 已記錄：{args.subject}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
