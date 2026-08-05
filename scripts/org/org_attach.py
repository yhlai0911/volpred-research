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
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dept_routing import resolve_dept_routing  # noqa: E402
from model_router import pick_model  # noqa: E402
from _core import (  # noqa: E402
    declares_a_file,
    reserved_carveouts,
    DEFAULT_ORG_ROOT,
    REPO_ROOT,
    brief_path,
    build_brief,
    build_manager_brief,
    dept_dir,
    identity_path,
    identity_prompt,
    work_prompt,
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
MANAGER = "manager"
MANAGER_TASK_TYPE = "org_manager"


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


def start_agent(name: str, kind: str, pane_id: str, extra: list[str]) -> None:
    """Start an agent, waiting out a pane whose shell has not reached its prompt.

    A freshly split pane needs a moment before it is an "available shell"; the
    first attach lost every role to agent_pane_busy purely on timing.
    """
    last: HerdrError | None = None
    for attempt in range(5):
        try:
            herdr("agent", "start", name, "--kind", kind, "--pane", pane_id, "--", *extra, timeout=120)
            return
        except HerdrError as exc:
            if "agent_pane_busy" not in str(exc) and "not an available shell" not in str(exc):
                raise
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise last if last else HerdrError(f"could not start {name} in {pane_id}")


def find_org_tab(label: str) -> str | None:
    """Reuse the existing org tab so a partial attach cannot scatter roles."""
    for ws in herdr("workspace", "list").get("workspaces", []):
        for tab in herdr("tab", "list", "--workspace", ws["workspace_id"]).get("tabs", []):
            if (tab.get("label") or "") == label:
                return tab.get("tab_id")
    return None


def turf_patterns(declared: list[str]) -> list[str]:
    """Turn declared ownership into the permission patterns that grant it.

    Two ways a real grant used to deny every write:

    1. **A declaration that names a file.** Everything was treated as a
       directory and given ``/**``, so ``scripts/gen_*_article_charts.py``
       became ``...py/**`` — a pattern matching nothing. The registry said the
       department owned the file, the settings said it owned a directory that
       does not exist, and the department was told "denied" with no explanation.
       Ownership of a single file is a legitimate declaration (content owns its
       chart scripts, governance owns policy.md) and must survive the trip.

    2. **Dot-directories inside an owned tree.** ``**`` does not cross a path
       segment beginning with a dot in most glob implementations, so a
       department owning ``frontend-v2-fix/`` still could not write
       ``frontend-v2-fix/.claude/no-session-lock`` — a file inside its own turf
       that the manager had explicitly approved (D51, 2026-08-05).

    A trailing slash, or the absence of a filename-looking last segment, means
    directory. Anything with a suffix or a glob in its final segment names a
    file and is passed through untouched.
    """
    patterns: list[str] = []
    for raw in declared:
        item = (raw or "").strip()
        if not item:
            continue
        if declares_a_file(item):
            patterns.append(item)
            continue
        base = item.rstrip("/")
        # The dot patterns are additive, never a replacement: `**` still carries
        # every ordinary path, and stating the dot case explicitly is cheaper
        # than depending on one matcher's opinion about leading dots.
        patterns += [f"{base}/**", f"{base}/.*", f"{base}/.*/**"]
    return patterns


def generate_dept_settings(root: Path, dept: str) -> Path | None:
    """Grant a department write access to exactly the turf its charter declares.

    Departments reported every write denied: the project allow-list has 111
    Bash rules and zero Edit/Write rules, so a pane could only write when a
    human sat there approving. Ownership is already declared in the registry —
    this turns that declaration into the permission that makes it real, and no
    wider: a department still cannot write another's turf.

    Written to runtime/ (regenerated per attach) so a hand-authored
    departments/<dept>/settings.json always wins.
    """
    registry = load_registry(root)
    if dept == MANAGER:
        # The coordinator was the one role with no generated settings, so it
        # could not write anything -- not the registry it governs, not the
        # bulletin that is its audit trail, not even its own outbox. On
        # 2026-08-05 that cost two proposals (owner-facing, never landed on
        # disk) and left the bulletin blank for three hours; the coordinator
        # reported "Edit/Write 連續第二班被 deny" and had to route its own
        # decisions through Telegram. Its charter already names this scope:
        # registry, bulletin, any department inbox, its own subtree.
        meta = {"owned_paths": ["storage/org/"], "capabilities": []}
    else:
        meta = registry.get("departments", {}).get(dept)
    if meta is None:
        return None

    # Relative patterns resolve against the SETTINGS FILE's directory, not the
    # project root — a generated file under storage/org/runtime/ turned
    # "storage/drafts/**" into "storage/org/runtime/storage/drafts/**", which
    # matches nothing. That is why every department reported writes denied even
    # after being granted its turf. Absolute patterns need a LEADING DOUBLE
    # SLASH; a single slash is still read as relative.
    rel = turf_patterns(
        [f"storage/org/departments/{dept}/", *(meta.get("owned_paths") or [])]
    )
    turf = [f"/{REPO_ROOT}/{r}" for r in rel]
    allow = [f"{tool}({t})" for t in turf for tool in ("Edit", "Write")]
    # Capabilities a department declares in the registry. Kept out of the turf
    # list because these are TOOLS, not territory: two departments may both need
    # the browser, and neither owns it.
    #
    # computer_use unlocks what `awaiting_interactive_session` used to park
    # forever: a cockpit pane IS an interactive session on the boss's machine,
    # so the real-Chrome path that headless cron could never drive is reachable
    # now. The canonical script stays the only door — no MCP, no headless
    # browser, no hand-rolled DOM steps (fb-publishing owns that boundary).
    capability_rules = {
        "computer_use": [
            "Bash(uv run python scripts/fb_realchrome_post.py:*)",
            "Bash(uv run python scripts/mark_fb_post_status.py:*)",
            "Bash(uv run python scripts/fb_page_post.py:*)",
        ],
    }
    for cap in meta.get("capabilities") or []:
        allow += capability_rules.get(cap, [])

    # The closeout contract requires archiving handled items, which is a file
    # move inside the department's own tree. Granting Edit/Write without the
    # move made the contract mechanically impossible to satisfy — content
    # reported exactly that.
    own = f"{REPO_ROOT}/storage/org/departments/{dept}"
    allow += [f"Bash(mv {own}/inbox/*:*)", f"Bash(mkdir -p {own}/:*)"]

    allow += [
        "Bash(uv run python scripts/org/dept_send.py:*)",
        "Bash(uv run python scripts/org/inbox_archive.py:*)",
        "Bash(uv run python scripts/org/org_status.py:*)",
        "Bash(uv run python scripts/org/dept_routing.py:*)",
        "Bash(uv run python scripts/git_writer_lock.py:*)",
        "Bash(uv run pytest:*)",
    ]
    # Holes in the turf. A department may own a parent of a reserved zone
    # (`scripts/` while the supervisor stays reserved, `paper/` while `.tex`
    # authorship stays main-thread), so the grant is real and the exception is
    # enforced here rather than by refusing the whole grant. deny outranks allow.
    # A directory carve-out needs the `**` that makes it recursive; a file
    # pattern (`paper/**/*.tex`) is already complete and appending `**` to it
    # produces `*.tex**`, which matches nothing — a deny rule that silently
    # protects nothing is worse than no rule, because it reads as protection.
    carveouts = reserved_carveouts(list(meta.get("owned_paths") or []),
                                   role="manager" if dept == MANAGER else "department")
    deny = [f"{tool}(/{REPO_ROOT}/{c + '**' if c.endswith('/') else c})"
            for c in carveouts for tool in ("Edit", "Write")]

    path = runtime_dir(root) / f"{dept}.settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    # The department, not the session, is the writer identity. Successive panes
    # for the same department get different session ids, so a claim keyed by
    # session made a department block ITSELF: content could not land drafts
    # because an earlier content session still held storage/drafts/.
    path.write_text(json.dumps({
        "permissions": {"allow": allow, "deny": deny},
        "env": {"VOLPRED_ORG_DEPT": dept},
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def dept_session_args(root: Path, dept: str) -> list[str]:
    """Per-department CLI config, opt-in by what exists on disk.

    Departments are not distinguished by their skills today — every pane loads
    the same repo-wide `.claude/skills/`. These hooks make differentiation
    possible without a second config system: drop the file in the department's
    directory and it takes effect on the next attach; leave it out and nothing
    changes.

      settings.json  → --settings        (permissions, hooks, env)
      skills/        → --plugin-dir      (department-only skills)
      tools.allow    → --allowed-tools   (one tool pattern per line)
      tools.deny     → --disallowed-tools
    """
    ddir = dept_dir(root, dept) if dept != MANAGER else root / MANAGER
    extra: list[str] = []
    settings = ddir / "settings.json"
    if not settings.is_file():
        generated = generate_dept_settings(root, dept)
        if generated:
            settings = generated
    if settings.is_file():
        extra += ["--settings", str(settings)]
    skills = ddir / "skills"
    if skills.is_dir():
        extra += ["--plugin-dir", str(skills)]
    for fname, flag in (("tools.allow", "--allowed-tools"), ("tools.deny", "--disallowed-tools")):
        f = ddir / fname
        if f.is_file():
            patterns = [ln.strip() for ln in f.read_text(encoding="utf-8").splitlines()
                        if ln.strip() and not ln.startswith("#")]
            if patterns:
                extra += [flag, " ".join(patterns)]
    return extra


def cmd_attach(args: argparse.Namespace) -> int:
    require_herdr()
    root: Path = args.root
    wanted = [d.strip() for d in args.depts.split(",") if d.strip()] if args.depts else None
    depts = active_departments(root, wanted)

    alive = live_agents()
    plan, skipped = [], []
    if args.with_manager and not wanted:
        lease = read_lease(root, MANAGER)
        if lease and lease.get("pane_id") in alive:
            skipped.append((MANAGER, f"已有 live pane {lease['pane_id']}"))
        else:
            plan.append((MANAGER, {"title": "運營經理"}))
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
    mm, me = pick_model(MANAGER_TASK_TYPE)
    routing[MANAGER] = {"title": "運營經理",
                        "session": {"model": mm, "effort": me,
                                    "basis": f"model_router[{MANAGER_TASK_TYPE}]"}}
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
    tab_id = find_org_tab(args.label)
    if tab_id:
        panes = herdr("pane", "list", "--workspace", tab_id.split(":")[0]).get("panes", [])
        in_tab = [p for p in panes if p.get("tab_id") == tab_id]
        free = [p for p in in_tab if not p.get("agent")]
        seed_pane = (free[0] if free else in_tab[0])["pane_id"]
        print(f"沿用既有 tab {tab_id}（避免角色被拆到不同 tab）")
        if not free:
            seed_pane = _split_largest(seed_pane, cwd)
    else:
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
            ipath = identity_path(root, name)
            ipath.parent.mkdir(parents=True, exist_ok=True)
            ipath.write_text(
                build_manager_brief(root) if name == MANAGER else identity_prompt(root, name),
                encoding="utf-8",
            )
            start_agent(name, args.kind, pane_id,
                        ["--model", model, "--effort", effort,
                         "--append-system-prompt-file", str(ipath),
                         *dept_session_args(root, name)])
            title = meta.get("title") or name
            herdr("pane", "rename", pane_id, f"{title} · {name}")

            bpath = brief_path(root, name)
            bpath.write_text(
                build_manager_brief(root) if name == MANAGER else build_brief(root, name),
                encoding="utf-8",
            )
            write_lease(root, name, {
                "runner": "herdr", "pane_id": pane_id, "tab_id": tab_id,
                "agent": name, "kind": args.kind, "since": now_iso(),
                "model": model, "effort": effort,
                "effort_basis": "cli override" if args.effort else session.get("basis"),
            })

            # Identity already rode in on the system prompt; the message carries
            # only what changes between wakes.
            if name == MANAGER:
                pending = len(list((root / "manager" / "inbox").glob("*.json")))
                opening = (f"開始協調。收件匣 {pending} 件；完整組織現況與工具清單見 {bpath}。"
                           f"依優先序處理，判斷與理由記進 bulletin。")
            else:
                pending = len(inbox_items(root, name))
                opening = (f"開始工作。{work_prompt(root, name)}")
            if not args.no_prompt:
                herdr("agent", "prompt", name, opening, timeout=90)
            attached.append((name, pane_id, pending))
            print(f"  ✓ {title} → pane {pane_id}  {model}/{effort}（待辦 {pending}）")
        except (HerdrError, subprocess.TimeoutExpired) as exc:
            failed.append((name, str(exc)))
            print(f"  ✗ {name}: {exc}", file=sys.stderr)

    print(f"\n完成：{len(attached)} 個部門已上線" + (f"，{len(failed)} 個失敗" if failed else ""))
    if attached:
        print(f"切到 tab 觀看：herdr tab focus {tab_id}")
    return 1 if failed else 0


def reap_dead_leases(root: Path, alive: dict) -> list[str]:
    """Drop leases whose pane no longer exists (every lease after a reboot).

    A lease naming a dead pane makes dispatch try to deliver into nothing and
    makes status claim a runner that is not there. Reaping is safe: the lease is
    runtime state, never the department's identity or work.
    """
    reaped = []
    registry = load_registry(root)
    for name in list(registry.get("departments", {})) + [MANAGER]:
        lease = read_lease(root, name)
        if lease and lease.get("runner") == "herdr" and lease.get("pane_id") not in alive:
            clear_lease(root, name)
            reaped.append(name)
    return reaped


def cmd_restore(args: argparse.Namespace) -> int:
    """One command to bring the whole organization back after a reboot."""
    require_herdr()
    root: Path = args.root

    print("1/3 檢查無人值守骨幹（重開機後由 launchd 自動復活，與 Herdr 無關）")
    for label in ("com.volpred.operations-core-scheduler", "com.volpred.dispatch-supervisor",
                  "com.volpred.work-dashboard"):
        try:
            probe = subprocess.run(["launchctl", "list", label],
                                   capture_output=True, text=True, timeout=15)
            ok = probe.returncode == 0
            print(f"    {'✓' if ok else '✗'} {label}")
            if not ok and label.endswith("work-dashboard"):
                # Everyone queries the dashboard for org state; a dead one makes
                # the whole organization guess instead of look.
                print("      ↳ 組織全景失明。復原："
                      "launchctl kickstart -k gui/$(id -u)/com.volpred.work-dashboard")
        except (OSError, subprocess.SubprocessError) as exc:
            print(f"    ? {label}（無法查詢：{type(exc).__name__}）")

    print("2/3 清理指向已消失 pane 的租約")
    reaped = reap_dead_leases(root, live_agents())
    print(f"    清掉 {len(reaped)} 筆" + (f"：{', '.join(reaped)}" if reaped else ""))

    print("3/3 重開經理與各部門 pane")
    return cmd_attach(args)


def cmd_status(args: argparse.Namespace) -> int:
    require_herdr()
    root: Path = args.root
    alive = live_agents()
    routing = resolve_dept_routing(load_registry(root))["departments"]
    mm, me = pick_model(MANAGER_TASK_TYPE)
    routing[MANAGER] = {"title": "運營經理",
                        "session": {"model": mm, "effort": me,
                                    "basis": f"model_router[{MANAGER_TASK_TYPE}]"}}
    rows = []
    roles = [(MANAGER, {"title": "運營經理"})] + active_departments(root, None)
    for name, meta in roles:
        session = (routing.get(name) or {}).get("session") or {}
        want = f"{session.get('model', '?')}/{session.get('effort', '?')}"
        lease = read_lease(root, name)
        if not lease:
            pend = (len(list((root / "manager" / "inbox").glob("*.json")))
                    if name == MANAGER else len(inbox_items(root, name)))
            rows.append((name, meta.get("title") or name, "—", "未附掛", want, "—", pend))
            continue
        pane = lease.get("pane_id", "?")
        state = alive.get(pane, {}).get("agent_status")
        status = f"live · {state}" if state else "租約過期（pane 已消失）"
        running = f"{lease.get('model', '?')}/{lease.get('effort', '?')}"
        pend = (len(list((root / "manager" / "inbox").glob("*.json")))
                if name == MANAGER else len(inbox_items(root, name)))
        rows.append((name, meta.get("title") or name, pane, status, want, running, pend))

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
    a.add_argument("--no-manager", dest="with_manager", action="store_false",
                   help="departments only; do not open the coordinator pane")
    a.add_argument("--effort", choices=("low", "medium", "high", "xhigh", "max"), default=None,
                   help="override the routed effort for every pane in this attach")
    a.add_argument("--label", default="VolPred 組織", help="tab label")
    a.add_argument("--dry-run", action="store_true")
    a.add_argument("--no-prompt", action="store_true", help="start agents but send no work prompt")
    a.set_defaults(func=cmd_attach)

    r = sub.add_parser("restore", help="one-shot recovery after a reboot")
    r.add_argument("--depts", default=None)
    r.add_argument("--kind", default=DEFAULT_KIND)
    r.add_argument("--label", default="VolPred 組織")
    r.add_argument("--dry-run", action="store_true")
    r.add_argument("--no-prompt", action="store_true")
    r.add_argument("--no-manager", dest="with_manager", action="store_false")
    r.add_argument("--effort", choices=("low", "medium", "high", "xhigh", "max"), default=None)
    r.set_defaults(func=cmd_restore)

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
