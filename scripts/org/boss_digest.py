#!/usr/bin/env python3
"""Boss digest: fold manager/outbox + department reports into ONE message.

This is the single boss-facing channel for the org: departments never mail the
boss, they report to the manager, and the manager sends one digest. Delivery
goes through the canonical durable owner (`volpred ops send-alert`) — this
script never grows its own send path, so dedup, retry and Sent read-back stay
where they already work.

  uv run python scripts/org/boss_digest.py --dry-run   # render only
  uv run python scripts/org/boss_digest.py --send      # deliver one digest
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _core import DEFAULT_ORG_ROOT, REPO_ROOT, load_registry  # noqa: E402


HEADLINE_CHARS = 160


def _headline(task: object) -> str:
    """One scannable line per item; the full text already lives on disk.

    Inlining whole task bodies turned 122 items into 1931 lines on 2026-08-05,
    which is how 54 P1 reports became invisible without a single one being
    dropped.
    """
    text = " ".join(str(task or "").split())
    if len(text) <= HEADLINE_CHARS:
        return text
    return text[:HEADLINE_CHARS - 1] + "…"


def render(root: Path) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"# VolPred 運營日報（{now}）", ""]

    pending = root / "manager" / "outbox" / "digest_pending.md"
    if pending.exists() and pending.read_text(encoding="utf-8").strip():
        lines += ["## 經理彙報", "", pending.read_text(encoding="utf-8").strip(), ""]

    reports = sorted((root / "manager" / "inbox").glob("*.json"))
    dept_reports = []
    cc_count = 0
    corrupt: list[str] = []
    for path in reports:
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            corrupt.append(path.name)
            continue  # silent-ok: not silent — corrupt items are surfaced in the digest's ⚠️ section below
        if item.get("from") == "boss":
            continue
        # Department-to-department traffic auto-copies the manager, so most of
        # this inbox is cc: org bookkeeping the owner takes no action on. On
        # 2026-08-05 that was 41 of 122 entries, and they arrive EARLIEST, so
        # an arrival-ordered list put every one of them above the decisions.
        # Dropped from the owner's list, but counted -- never silently.
        if item.get("kind") == "cc":
            cc_count += 1
            continue
        dept_reports.append(item)
    if dept_reports:
        # Order by priority, not by arrival. The digest rendered on 2026-08-05
        # was 1931 lines with 54 P1 items below the noise; the manager read the
        # top of it and reported the channel as carrying nothing but cc. A
        # boss-facing message whose important half is under the fold has already
        # failed, even though every byte of it was present.
        rank = {"P1": 0, "P2": 1, "P3": 2}
        dept_reports.sort(key=lambda i: rank.get(str(i.get("priority") or "P3"), 2))
        lines += ["## 部門上報", ""]
        for item in dept_reports:
            lines.append(
                f"- [{item.get('priority', 'P3')}] **{item.get('from')}**: "
                f"{_headline(item.get('task'))}"
            )
        lines.append("")
    if cc_count:
        lines += [
            f"_另有 {cc_count} 則部門間知會（kind=cc）未列入；完整內容在 manager/inbox_",
            "",
        ]
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


def has_content(root: Path) -> bool:
    """True when there is something worth a boss-facing message.

    An empty digest on a quiet morning is exactly the noise this channel was
    built to end, so a quiet org sends nothing at all.
    """
    pending = root / "manager" / "outbox" / "digest_pending.md"
    if pending.exists() and pending.read_text(encoding="utf-8").strip():
        return True
    if any((root / "manager" / "outbox" / "proposals").glob("*.md")):
        return True
    for path in (root / "manager" / "inbox").glob("*.json"):
        try:
            if json.loads(path.read_text(encoding="utf-8")).get("from") != "boss":
                return True
        except (json.JSONDecodeError, OSError):  # silent-ok: unreadable items are rendered as ⚠️ in the digest
            return True
    return False


def send(root: Path, text: str, *, force: bool = False) -> int:
    """Deliver through the canonical durable email owner, never a private path."""
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as fh:
        fh.write(text)
        body = fh.name
    cmd = ["uv", "run", "volpred", "ops", "send-alert", "--level", "info",
           "--title", "VolPred 運營日報（經理彙整）", "--body-md", body]
    if force:
        cmd.append("--force")
    try:
        proc = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"digest 寄送失敗（{type(exc).__name__}: {exc}）", file=sys.stderr)
        return 1
    finally:
        Path(body).unlink(missing_ok=True)
    if proc.returncode != 0:
        print(f"digest 寄送失敗：{(proc.stderr or proc.stdout).strip()[:300]}", file=sys.stderr)
        return 1

    # Consume what was reported so the next digest is not a repeat.
    archive = root / "manager" / "inbox" / "_archive"
    archive.mkdir(parents=True, exist_ok=True)
    for path in (root / "manager" / "inbox").glob("*.json"):
        try:
            if json.loads(path.read_text(encoding="utf-8")).get("from") == "boss":
                continue  # boss instructions are the manager's to close, not the digest's
        except (json.JSONDecodeError, OSError):  # silent-ok: unreadable items were rendered; archiving them stops a loop
            pass
        path.replace(archive / path.name)
    pending = root / "manager" / "outbox" / "digest_pending.md"
    if pending.exists():
        pending.write_text("", encoding="utf-8")
    print("digest 已寄出")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ORG_ROOT)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--send", action="store_true")
    parser.add_argument("--force", action="store_true", help="bypass the 24h dedup once")
    args = parser.parse_args()

    if not args.dry_run and not args.send:
        parser.error("需要 --dry-run 或 --send")

    if args.send and not has_content(args.root):
        print("組織這段時間沒有需要回報的事——不寄空信。")
        return 0

    text = render(args.root)
    if args.dry_run:
        print(text)
        return 0
    return send(args.root, text, force=args.force)


if __name__ == "__main__":
    raise SystemExit(main())
