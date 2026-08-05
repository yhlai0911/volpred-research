#!/usr/bin/env python3
"""Boss digest: fold manager/outbox + department reports into ONE message.

P0/P1: --dry-run renders the digest to stdout. Live delivery (P2) will route
through the existing durable email owner (`email.ops_alert`) / telegram
transport — this script never grows its own send path.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _core import DEFAULT_ORG_ROOT, load_registry  # noqa: E402


def render(root: Path) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"# VolPred 運營日報（{now}）", ""]

    pending = root / "manager" / "outbox" / "digest_pending.md"
    if pending.exists() and pending.read_text(encoding="utf-8").strip():
        lines += ["## 經理彙報", "", pending.read_text(encoding="utf-8").strip(), ""]

    reports = sorted((root / "manager" / "inbox").glob("*.json"))
    dept_reports = []
    corrupt: list[str] = []
    for path in reports:
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            corrupt.append(path.name)
            continue  # silent-ok: not silent — corrupt items are surfaced in the digest's ⚠️ section below
        if item.get("from") != "boss":
            dept_reports.append(item)
    if dept_reports:
        lines += ["## 部門上報", ""]
        for item in dept_reports:
            lines.append(f"- [{item.get('priority', 'P3')}] **{item.get('from')}**: {item.get('task')}")
        lines.append("")
    if corrupt:
        lines += ["## ⚠️ 無法解析的 inbox 項（需人工/經理處理）", ""]
        lines += [f"- `{name}`" for name in corrupt]
        lines.append("")

    proposals = sorted((root / "manager" / "outbox" / "proposals").glob("*.md"))
    if proposals:
        lines += ["## 待核准提案（telegram 回 `approve <id>` 核准）", ""]
        for p in proposals:
            lines.append(f"- `{p.stem}`: {p.read_text(encoding='utf-8').splitlines()[0].lstrip('# ')}")
        lines.append("")

    try:
        registry = load_registry(root)
        active = [d for d, m in registry["departments"].items() if m.get("status") == "active"]
        lines.append(f"_active departments: {', '.join(sorted(active))}_")
    except FileNotFoundError:
        lines.append("_⚠️ org registry unavailable — 組織尚未初始化或路徑錯誤_")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ORG_ROOT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    text = render(args.root)
    if args.dry_run:
        print(text)
        return 0
    print("live delivery not wired yet (P2) — use --dry-run; digest NOT sent", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
