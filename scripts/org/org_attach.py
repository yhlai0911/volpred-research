#!/usr/bin/env python3
"""Herdr cockpit: give every active department its own live pane.

The org's backbone is headless on purpose (launchd + disk-persisted state), so
the platform keeps running with no terminal open. This tool is the *other* half:
when you are at the machine and want to watch the organization work, it lays out
one pane per department, starts a named agent in each, and hands it the same
rehydration brief the headless runner would get.

A lease file per department names the live runner, so a pane agent and a
headless dispatch can never work the same inbox at once.

  uv run python scripts/org/org_attach.py attach            # all active depts
  uv run python scripts/org/org_attach.py attach --depts research,content
  uv run python scripts/org/org_attach.py attach --dry-run  # show the plan only
  uv run python scripts/org/org_attach.py status
  uv run python scripts/org/org_attach.py detach --depts research [--close-panes]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dept_routing import resolve_dept_routing  # noqa: E402
from _core import (  # noqa: E402
    DEFAULT_ORG_ROOT,
    REPO_ROOT,
    brief_path,
    build_brief,
    clear_lease,
    inbox_items,
    load_registry,
    now_iso,
    read_lease,
    runtime_dir,
    write_lease,
)

HERDR = "/opt/homebrew/bin/herdr"
DEFAULT_KIND = "claude"


class HerdrError(RuntimeError):
    pass


def herdr(*args: str, timeout: int = 60) -> dict:
    """Run a herdr CLI command and return its parsed `result` object."""
    proc = subprocess.run([HERDR, *args], capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise HerdrError(f"herdr {' '.join(args)} → exit {proc.returncode}: {proc.stderr.strip() or proc.stdout.strip()}")
    out = proc.stdout.strip()
    if not out:
        return {}
    try:
        return json.loads(out).get("result", {})
    except json.JSONDecodeError as exc:
        raise HerdrError(f"herdr {' '.join(args)} returned non-JSON: {out[:200]}") from exc


def require_herdr() -> None:
    if os.environ.get("HERDR_ENV") != "1":
        raise SystemExit(
            "不在 Herdr session 內（HERDR_ENV != 1）。\n"
            "這個工具只在你於 Herdr 終端中操作時可用；平台的無人值守運作不需要它。"
        )
    if not Path(HERDR).exists():
        raise SystemExit(f"找不到 herdr binary：{HERDR}")


def live_agents() -> dict[str, dict]:
    """Named agents currently alive, keyed by pane id (Herdr reports no name field)."""
    result = herdr("agent", "list")
    return {a["pane_id"]: a for a in result.get("agents", []) if a.get("pane_id")}


def active_departments(root: Path, wanted: list[str] | None) -> list[tuple[str, dict]]:
    registry = load_registry(root)
    depts = [(n, m) for n, m in sorted(registry.get("departments", {}).items())
             if m.get("status") == "active"]
    if wanted:
        known = {n for n, _ in depts}
        unknown = [w for w in wanted if w not in known]
        if unknown:
            raise SystemExit(f"這些部門不存在或非 active：{', '.join(unknown)}")
        depts = [(n, m) for n, m in depts if n in wanted]
    return depts


def _panes_in_tab(any_pane: str) -> list[dict]:
    layout = herdr("pane", "layout", "--pane", any_pane).get("layout", {})
    return layout.get("panes", [])


def _split_largest(any_pane_in_tab: str, cwd: str) -> str:
    """Split the roomiest pane in this tab, keeping tiles from degenerating."""
    panes = _panes_in_tab(any_pane_in_tab)
    if not panes:
        raise HerdrError(f"no panes reported for tab containing {any_pane_in_tab}")
    target = max(panes, key=lambda p: p["rect"]["width"] * p["rect"]["height"])
    rect = target["rect"]
    # Terminal cells are roughly 2:1 (w:h), so compare width against 2*height to
    # decide which axis actually has room left.
    direction = "right" if rect["width"] >= rect["height"] * 2 else "down"
    new = herdr("pane", "split", target["pane_id"], "--direction", direction,
                "--cwd", cwd, "--no-focus")
    pane_id = new.get("pane", {}).get("pane_id")
    if not pane_id:
        raise HerdrError(f"pane split returned no pane_id: {new}")
    return pane_id


def cmd_attach(args: argparse.Namespace) -> int:
    require_herdr()
    root: Path = args.root
    wanted = [d.strip() for d in args.depts.split(",") if d.strip()] if args.depts else None
    depts = active_departments(root, wanted)

    alive = live_agents()
    plan, skipped = [], []
    for name, meta in depts:
        lease = read_lease(root, name)
        if lease and lease.get("pane_id") in alive:
            skipped.append((name, f"已有 live pane {lease['pane_id']}"))
            continue
        if lease and lease.get("runner") == "headless":
            skipped.append((name, "headless runner 持有租約（避免雙跑）"))
            continue
        plan.append((name, meta))

    for name, reason in skipped:
        print(f"skip {name}: {reason}")
    if not plan:
        print("沒有需要新開的部門 pane。")
        return 0

    # The pane must actually RUN at the department's routing, not merely display
    # it: a cockpit that shows opus/xhigh while the session runs on CLI defaults
    # is a dashboard lying about its own subject.
    routing = resolve_dept_routing(load_registry(root))["departments"]
    print(f"將開 {len(plan)} 個 pane（kind={args.kind}）：")
    for name, _ in plan:
        s = (routing.get(name) or {}).get("session") or {}
        eff = args.effort or s.get("effort", "?")
        print(f"  {name:<18} {s.get('model', '?')}/{eff}"
              + (f"  [--effort 覆寫，路由建議 {s.get('effort')}]" if args.effort else "")
              + (f"  ⚠️ {s['conflict']}" if s.get("conflict") else ""))
    if args.dry_run:
        print("--dry-run：僅顯示計畫，未動 Herdr。")
        return 0

    cwd = str(REPO_ROOT)
    tab = herdr("tab", "create", "--cwd", cwd, "--label", args.label, "--no-focus")
    tab_id = tab.get("tab", {}).get("tab_id")
    seed_pane = tab.get("root_pane", {}).get("pane_id")
    if not seed_pane:
        raise HerdrError(f"tab create returned no root pane: {tab}")
    print(f"tab {tab_id} 建立（root pane {seed_pane}）")

    runtime_dir(root).mkdir(parents=True, exist_ok=True)
    attached, failed = [], []
    for idx, (name, meta) in enumerate(plan):
        try:
            pane_id = seed_pane if idx == 0 else _split_largest(seed_pane, cwd)
            session = (routing.get(name) or {}).get("session") or {}
            model = session.get("model") or "opus"
            effort = args.effort or session.get("effort") or "medium"
            herdr("agent", "start", name, "--kind", args.kind, "--pane", pane_id,
                  "--", "--model", model, "--effort", effort, timeout=120)
            title = meta.get("title") or name
            herdr("pane", "rename", pane_id, f"{title} · {name}")

            bpath = brief_path(root, name)
            bpath.write_text(build_brief(root, name), encoding="utf-8")
            write_lease(root, name, {
                "runner": "herdr", "pane_id": pane_id, "tab_id": tab_id,
                "agent": name, "kind": args.kind, "since": now_iso(),
                "model": model, "effort": effort,
                "effort_basis": "cli override" if args.effort else session.get("basis"),
            })

            pending = len(inbox_items(root, name))
            if not args.no_prompt:
                herdr("agent", "prompt", name,
                      f"你是 VolPred「{title}」部門（`{name}`），收件匣有 {pending} 件待辦。"
                      f"先完整讀 {bpath} 這份 brief 建立你的身分與脈絡，然後依優先序開始工作。"
                      f"結束前務必執行章程裡的 Session 收尾契約。",
                      timeout=90)
            attached.append((name, pane_id, pending))
            print(f"  ✓ {title} → pane {pane_id}  {model}/{effort}（待辦 {pending}）")
        except (HerdrError, subprocess.TimeoutExpired) as exc:
            failed.append((name, str(exc)))
            print(f"  ✗ {name}: {exc}", file=sys.stderr)

    print(f"\n完成：{len(attached)} 個部門已上線" + (f"，{len(failed)} 個失敗" if failed else ""))
    if attached:
        print(f"切到 tab 觀看：herdr tab focus {tab_id}")
    return 1 if failed else 0


def cmd_status(args: argparse.Namespace) -> int:
    require_herdr()
    root: Path = args.root
    alive = live_agents()
    routing = resolve_dept_routing(load_registry(root))["departments"]
    rows = []
    for name, meta in active_departments(root, None):
        session = (routing.get(name) or {}).get("session") or {}
        want = f"{session.get('model', '?')}/{session.get('effort', '?')}"
        lease = read_lease(root, name)
        if not lease:
            rows.append((name, meta.get("title") or name, "—", "未附掛", want, "—",
                         len(inbox_items(root, name))))
            continue
        pane = lease.get("pane_id", "?")
        state = alive.get(pane, {}).get("agent_status")
        status = f"live · {state}" if state else "租約過期（pane 已消失）"
        running = f"{lease.get('model', '?')}/{lease.get('effort', '?')}"
        rows.append((name, meta.get("title") or name, pane, status, want, running,
                     len(inbox_items(root, name))))

    if args.as_json:
        keys = ("dept", "title", "pane", "status", "routed", "running", "inbox")
        print(json.dumps([dict(zip(keys, r)) for r in rows], ensure_ascii=False, indent=2))
        return 0
    print(f"{'部門':<16}{'pane':<8}{'狀態':<20}{'路由':<14}{'實際':<14}待辦")
    for _, title, pane, status, want, running, inbox in rows:
        drift = "" if running in ("—", want) else "  ⚠️ 與路由不符"
        print(f"{title:<14}{pane:<8}{status:<20}{want:<14}{running:<14}{inbox}{drift}")
    return 0


def cmd_detach(args: argparse.Namespace) -> int:
    require_herdr()
    root: Path = args.root
    wanted = [d.strip() for d in args.depts.split(",") if d.strip()] if args.depts else None
    targets = [n for n, _ in active_departments(root, wanted)]
    alive = live_agents()

    for name in targets:
        lease = read_lease(root, name)
        if not lease:
            continue
        pane = lease.get("pane_id")
        if args.close_panes and pane in alive:
            try:
                herdr("pane", "close", pane)
                print(f"closed pane {pane} ({name})")
            except HerdrError as exc:
                print(f"WARN 無法關閉 {pane}: {exc}", file=sys.stderr)
        if clear_lease(root, name):
            print(f"released lease: {name}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", type=Path, default=DEFAULT_ORG_ROOT)
    sub = p.add_subparsers(dest="command", required=True)

    a = sub.add_parser("attach", help="one pane + named agent per active department")
    a.add_argument("--depts", default=None, help="comma-separated subset (default: all active)")
    a.add_argument("--kind", default=DEFAULT_KIND, help=f"agent kind (default {DEFAULT_KIND})")
    a.add_argument("--effort", choices=("low", "medium", "high", "xhigh", "max"), default=None,
                   help="override the routed effort for every pane in this attach")
    a.add_argument("--label", default="VolPred 組織", help="tab label")
    a.add_argument("--dry-run", action="store_true")
    a.add_argument("--no-prompt", action="store_true", help="start agents but send no work prompt")
    a.set_defaults(func=cmd_attach)

    s = sub.add_parser("status", help="which departments have a live pane")
    s.add_argument("--json", action="store_true", dest="as_json")
    s.set_defaults(func=cmd_status)

    d = sub.add_parser("detach", help="release leases (optionally close the panes)")
    d.add_argument("--depts", default=None)
    d.add_argument("--close-panes", action="store_true")
    d.set_defaults(func=cmd_detach)
    return p


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
