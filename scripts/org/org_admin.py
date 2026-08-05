#!/usr/bin/env python3
"""Org administration: create / retire / suspend / resume / list departments.

Pure file operations — creating or retiring a department never requires a code
change (org-as-data). Every structural change is recorded in the bulletin.

Examples:
  uv run python scripts/org/org_admin.py init
  uv run python scripts/org/org_admin.py create research \
      --title 研究部 --mission "波動率研究與實驗" \
      --task-types experiment,lookup,strategy_lifecycle \
      --paths experiments/ --kpi "每週 >=3 個 OOS-verified 實驗"
  uv run python scripts/org/org_admin.py retire research --reason "併入 X"
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _core import (  # noqa: E402
    DEFAULT_ORG_ROOT,
    REGISTRY_VERSION,
    atomic_write_json,
    bulletin_append,
    check_path_conflicts,
    reserved_carveouts,
    dept_dir,
    load_registry,
    normalize_owned_path,
    now_iso,
    registry_path,
    save_registry,
    validate_dept_name,
)

TEMPLATES = Path(__file__).resolve().parent / "templates"


def _render(template: str, **kw: str) -> str:
    text = (TEMPLATES / template).read_text(encoding="utf-8")
    for key, value in kw.items():
        text = text.replace("{" + key + "}", value)
    return text


def cmd_init(args: argparse.Namespace) -> int:
    root: Path = args.root
    if registry_path(root).exists() and not args.force:
        print(f"registry already exists at {registry_path(root)}; use --force to re-init metadata only")
        return 1
    registry = {
        "version": REGISTRY_VERSION,
        "created_at": now_iso(),
        "departments": {},
    }
    if registry_path(root).exists():
        registry = load_registry(root)
    atomic_write_json(registry_path(root), registry)

    manager = root / "manager"
    for sub in ("memory", "inbox/_archive", "outbox/proposals"):
        (manager / sub).mkdir(parents=True, exist_ok=True)
    (root / "bulletin").mkdir(parents=True, exist_ok=True)
    (root / "receipts").mkdir(parents=True, exist_ok=True)
    (root / "departments").mkdir(parents=True, exist_ok=True)

    charter = manager / "charter.md"
    if not charter.exists():
        charter.write_text(_render("charter_manager.md", created_at=now_iso()), encoding="utf-8")
    notes = manager / "memory" / "notes.md"
    if not notes.exists():
        notes.write_text("# 運營經理私有記憶\n", encoding="utf-8")
    state = manager / "state.json"
    if not state.exists():
        atomic_write_json(state, {"last_tick": None, "pending_proposals": [], "next_review_due": None})
    bulletin_append(root, "org_admin", "org skeleton initialized")
    save_registry(root, load_registry(root))
    print(f"org initialized at {root}")
    return 0


def cmd_create(args: argparse.Namespace) -> int:
    root: Path = args.root
    validate_dept_name(args.name)
    registry = load_registry(root)
    if args.name in registry["departments"] and registry["departments"][args.name].get("status") != "retired":
        print(f"department {args.name!r} already exists (status={registry['departments'][args.name]['status']})")
        return 1

    task_types = [t.strip() for t in (args.task_types or "").split(",") if t.strip()]
    paths = [p.strip() for p in (args.paths or "").split(",") if p.strip()]
    conflicts = check_path_conflicts(registry, paths, exclude=args.name)
    if conflicts:
        print("path ownership conflicts — refusing to create:")
        for c in conflicts:
            print(f"  - {c}")
        return 1
    claimed = {
        t: d for d, m in registry["departments"].items() if m.get("status") == "active"
        for t in m.get("owned_task_types", [])
    }
    dup_types = [t for t in task_types if t in claimed]
    if dup_types:
        print(f"task_type conflicts: {', '.join(f'{t} (owned by {claimed[t]})' for t in dup_types)}")
        return 1

    ddir = dept_dir(root, args.name)
    for sub in ("memory", "inbox/_archive",):
        (ddir / sub).mkdir(parents=True, exist_ok=True)
    (ddir / "charter.md").write_text(
        _render(
            "charter_dept.md",
            name=args.name,
            title=args.title or args.name,
            status="active",
            created_at=now_iso(),
            task_types=", ".join(task_types) or "（無——由經理派 ad-hoc 工作）",
            paths=", ".join(paths) or "（無專屬 path）",
            min_cadence=args.min_cadence or "on-demand",
            mission=args.mission or "（待經理補充）",
            kpi=args.kpi or "（待經理補充）",
        ),
        encoding="utf-8",
    )
    (ddir / "memory" / "notes.md").write_text(f"# {args.name} 部門私有記憶\n", encoding="utf-8")
    (ddir / "journal.md").write_text(f"# {args.name} 工作日誌（append-only）\n", encoding="utf-8")
    atomic_write_json(ddir / "state.json", {
        "last_run": None, "open_items": 0, "health": "new", "kpi": {},
    })

    registry["departments"][args.name] = {
        "status": "active",
        "created_at": now_iso(),
        "title": args.title or args.name,
        "owned_task_types": task_types,
        "owned_paths": paths,
        "min_cadence": args.min_cadence,
    }
    save_registry(root, registry)
    bulletin_append(root, args.actor, f"department created: {args.name} ({args.title or args.name}); task_types={task_types}; paths={paths}")
    print(f"department {args.name!r} created at {ddir}")
    return 0


def cmd_retire(args: argparse.Namespace) -> int:
    root: Path = args.root
    registry = load_registry(root)
    meta = registry["departments"].get(args.name)
    if not meta or meta.get("status") == "retired":
        print(f"department {args.name!r} not active")
        return 1
    ddir = dept_dir(root, args.name)
    retired_root = root / "departments" / "_retired"
    retired_root.mkdir(parents=True, exist_ok=True)
    target = retired_root / args.name
    if target.exists():
        target = retired_root / f"{args.name}_{now_iso().replace(':', '')}"
    if ddir.exists():
        shutil.move(str(ddir), str(target))
    meta["status"] = "retired"
    meta["retired_at"] = now_iso()
    meta["retire_reason"] = args.reason
    save_registry(root, registry)
    bulletin_append(root, args.actor, f"department retired: {args.name} — {args.reason}")
    print(f"department {args.name!r} retired → {target}")
    return 0


def _set_status(args: argparse.Namespace, status: str) -> int:
    registry = load_registry(args.root)
    meta = registry["departments"].get(args.name)
    if not meta or meta.get("status") == "retired":
        print(f"department {args.name!r} not active/suspendable")
        return 1
    meta["status"] = status
    save_registry(args.root, registry)
    bulletin_append(args.root, args.actor, f"department {args.name}: status → {status}")
    print(f"department {args.name!r} → {status}")
    return 0


def cmd_set_paths(args: argparse.Namespace) -> int:
    """Change a department's turf — the only supported way to grant write access.

    Hand-editing the registry skips `check_path_conflicts`, which is the whole
    reason the field exists: two departments owning overlapping turf is how you
    get the concurrent-write damage the org was built to stop. It also skips the
    bulletin record, and three months later nobody can answer who granted a path
    or on whose authority.
    """
    registry = load_registry(args.root)
    meta = registry["departments"].get(args.name)
    if not meta or meta.get("status") == "retired":
        print(f"department {args.name!r} not active", file=sys.stderr)
        return 1

    before = list(meta.get("owned_paths") or [])
    # Not `.rstrip("/") + "/"`: that stored every declaration as a directory, so
    # `storage/org/policy.md` became `storage/org/policy.md/` and the settings
    # generator -- which cannot see what it was told -- granted `...md/**`, a
    # pattern matching nothing. The writer and the reader now share one
    # definition of what an owned path is (_core.normalize_owned_path).
    incoming = [
        normalize_owned_path(p) for p in args.paths.split(",") if p.strip()
    ]
    after = sorted(set(incoming if args.replace else before + incoming))

    conflicts = check_path_conflicts(registry, after, exclude=args.name)
    if conflicts:
        print("拒絕：轄區衝突\n  " + "\n  ".join(conflicts), file=sys.stderr)
        return 2

    meta["owned_paths"] = after
    save_registry(args.root, registry)

    holes = reserved_carveouts(after)
    bulletin_append(
        args.root, args.actor,
        f"owned_paths {args.name}: {before or '[]'} → {after}"
        + (f"（保留區挖洞：{holes}）" if holes else "")
        + f"　依據：{args.reason}",
    )
    print(f"{args.name}.owned_paths: {before or '[]'} → {after}")
    if holes:
        print(f"  保留區挖洞（生成的 settings 會 deny）：{', '.join(holes)}")
    print("⚠️  已 attach 的 session 不會拿到新權限——必須 re-attach 才生效：")
    print("    uv run python scripts/org/org_attach.py restore")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    registry = load_registry(args.root)
    print(json.dumps(registry, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=DEFAULT_ORG_ROOT, help="org root (default: storage/org)")
    parser.add_argument("--actor", default="manager", help="who is making this change (bulletin attribution)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="create org skeleton (registry, bulletin, manager)")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("create", help="create a department (pure file ops)")
    p.add_argument("name")
    p.add_argument("--title", default=None)
    p.add_argument("--mission", default=None)
    p.add_argument("--kpi", default=None)
    p.add_argument("--task-types", default=None, help="comma-separated owned task_types")
    p.add_argument("--paths", default=None, help="comma-separated owned repo-relative paths")
    p.add_argument("--min-cadence", default=None, help="e.g. daily / weekly / on-demand")
    p.set_defaults(func=cmd_create)

    p = sub.add_parser("retire", help="retire a department (moves dir to _retired/)")
    p.add_argument("name")
    p.add_argument("--reason", required=True)
    p.set_defaults(func=cmd_retire)

    p = sub.add_parser("suspend", help="suspend a department")
    p.add_argument("name")
    p.set_defaults(func=lambda a: _set_status(a, "suspended"))

    p = sub.add_parser("resume", help="resume a suspended department")
    p.add_argument("name")
    p.set_defaults(func=lambda a: _set_status(a, "active"))

    p = sub.add_parser("set-paths", help="grant/replace a department's owned_paths")
    p.add_argument("name")
    p.add_argument("--paths", required=True, help="comma-separated repo-relative dirs")
    p.add_argument("--replace", action="store_true", help="replace instead of adding")
    p.add_argument("--reason", required=True, help="who approved this and why (bulletin)")
    p.set_defaults(func=cmd_set_paths)

    p = sub.add_parser("list", help="print registry JSON")
    p.set_defaults(func=cmd_list)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
