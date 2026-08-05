#!/usr/bin/env python3
"""Org view for the work dashboard: the hierarchy, and the work that moved through it.

`scripts/org/org_status.py` answers "what is the org right now" in one screen of
text. This module answers the two questions a text snapshot cannot: **who reports
to whom** and **what actually happened between them**. Both come from the same
disk state (`storage/org/`), so nothing here is a second source of truth — it is
a projection of the department directories, their inboxes, journals, receipts and
the org bulletin into one time-ordered view.

Served by `scripts/work_dashboard_server.py` at `/org` — that server stays the
single HTTP owner; this file owns only the shape of the data and its page.

  uv run python scripts/work_dashboard_org.py                 # JSON to stdout
  uv run python scripts/work_dashboard_org.py --html out.html # standalone snapshot
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
from volpred.ops.diagnostics import warn

ORG_ROOT = ROOT / "storage" / "org"
TZ = ZoneInfo("Asia/Taipei")

# A file this view cannot read is a hole in the picture, not an empty result:
# an unreadable state.json would otherwise render as a healthy department with
# no blockers. Every recovery path appends here and the page shows the banner.
_WARNINGS: list[str] = []

# Message kinds carry the org's constitution: only the manager may assign, peers
# may only ask. Colouring them apart is what makes a wrong flow visible at a glance.
KIND_META = {
    "assignment": ("派工", "#1f6feb"),
    "request": ("求助", "#d29922"),
    "reply": ("回覆", "#39c5cf"),
    "report": ("回報", "#3fb950"),
    "cc": ("知會", "#8b949e"),
    "run": ("執行紀錄", "#a371f7"),
    "bulletin": ("經理公告", "#bc8cff"),
    "tick": ("經理巡檢", "#6e7681"),
    "wake": ("喚醒判斷", "#6e7681"),
}
FLOW_KINDS = ("assignment", "request", "reply", "report", "cc")
HEALTH_COLOR = {
    "ok": "#3fb950", "healthy": "#3fb950", "green": "#3fb950",
    "blocked": "#f85149", "critical": "#f85149", "red": "#f85149",
    "degraded": "#d29922", "warn": "#d29922", "amber": "#d29922",
}
DEPT_COLOR = {
    "research": "#58a6ff", "publications": "#bc8cff", "content": "#3fb950",
    "member_success": "#f0883e", "platform_eng": "#e3b341", "governance": "#8b949e",
    "growth": "#f778ba", "resource_monitor": "#39c5cf",
}
DEPT_ICON = {
    "research": "🔬", "publications": "📄", "content": "✍️", "member_success": "💬",
    "platform_eng": "🛠", "governance": "⚖️", "growth": "📈", "resource_monitor": "📊",
}
TIMELINE_CAP = 300

_ISO_UTC = re.compile(r"(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?Z")
_TW_CLOCK = re.compile(r"(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2})")
_DATE_ONLY = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_OUTCOME = re.compile(r"outcome=([^\s（(]+)")
_BULLETIN = re.compile(r"^-\s+(\S+)\s+\*\*([^*]+)\*\*:\s*(.+)$")
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _now() -> datetime:
    return datetime.now(UTC)


def _read_json(path: Path):
    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        rel = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
        msg = f"讀不到 {rel}（{type(exc).__name__}）— 該區塊在頁面上會缺項"
        warn("org-dashboard", msg, path=str(path))
        _WARNINGS.append(msg)
        return None


def _parse_iso(value) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None  # silent-ok: an absent timestamp is a legitimate state (never run)
    try:
        dt = datetime.fromisoformat(value.strip())
    except ValueError:
        msg = f"時間戳無法解析：{value!r} — 該事件會被排到時間軸最末"
        warn("org-dashboard", msg, value=value)
        _WARNINGS.append(msg)
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def _tw(dt: datetime | None) -> str:
    return dt.astimezone(TZ).strftime("%m-%d %H:%M") if dt else "—"


def _rel(dt: datetime | None) -> str:
    """Relative age in Chinese; the absolute Taipei timestamp travels alongside it."""
    if not dt:
        return "—"
    secs = (_now() - dt).total_seconds()
    if secs < 0:
        return "剛剛"
    for limit, div, unit in ((60, 1, "秒"), (3600, 60, "分"), (86400, 3600, "小時")):
        if secs < limit:
            return f"{int(secs // div)}{unit}前"
    return f"{int(secs // 86400)}天前"


def _iso(dt: datetime | None) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ") if dt else ""


def _clip(text: str, n: int = 160) -> str:
    # Departments sometimes write a literal backslash-n into a task string; a
    # headline must not show it as two characters of noise.
    text = " ".join((text or "").replace("\\n", " ").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _event(at: datetime | None, kind: str, *, source: str, title: str, body: str = "",
           frm: str = "", to: str = "", priority: str = "", ident: str = "",
           approx: bool = False, tags: list[str] | None = None) -> dict:
    label, color = KIND_META.get(kind, (kind, "#6e7681"))
    return {
        "at": _iso(at), "at_tw": _tw(at), "rel": _rel(at), "approx": approx,
        "kind": kind, "kind_label": label, "color": color,
        "source": source, "title": title, "body": body,
        "from": frm, "to": to, "priority": priority, "id": ident,
        "tags": tags or [], "_sort": at or _EPOCH,
    }


def _inbox_items(inbox: Path) -> list[dict]:
    """Open items plus anything already archived, tagged so the UI can tell them apart."""
    out: list[dict] = []
    pairs = [(p, False) for p in sorted(inbox.glob("*.json"))]
    pairs += [(p, True) for p in sorted((inbox / "_archive").glob("*.json"))]
    for path, archived in pairs:
        payload = _read_json(path)
        if not isinstance(payload, dict):
            out.append({"id": path.name, "task": f"⚠️ 無法解析 {path.name}", "priority": "P1",
                        "kind": "assignment", "archived": archived})
            continue
        payload["archived"] = archived
        out.append(payload)
    return out


def _journal_runs(path: Path, dept: str) -> list[dict]:
    """Split a department journal into its `## ` sections, dated as written.

    Journal headers are free text (departments write them by hand), so the time is
    recovered rather than assumed: an explicit `...Z` is UTC, a bare
    `YYYY-MM-DD HH:MM` follows the project convention of Taipei local time, and a
    date with no clock is flagged approximate instead of having a time invented.
    """
    if not path.exists():
        return []
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        msg = f"{dept} 的 journal.md 讀不到（{type(exc).__name__}）— 該部門執行紀錄會顯示為空"
        warn("org-dashboard", msg, dept=dept, path=str(path))
        _WARNINGS.append(msg)
        return []

    runs: list[dict] = []
    header: str | None = None
    buf: list[str] = []

    def flush() -> None:
        if header is None:
            return
        at, approx = None, False
        if (m := _ISO_UTC.search(header)):
            at = datetime(*(int(g) for g in m.groups()[:5]), int(m.group(6) or 0), tzinfo=UTC)
        elif (m := _TW_CLOCK.search(header)):
            at = datetime(*(int(g) for g in m.groups()), tzinfo=TZ).astimezone(UTC)
        elif (m := _DATE_ONLY.search(header)):
            at = datetime(*(int(g) for g in m.groups()), tzinfo=TZ).astimezone(UTC)
            approx = True
        oc = _OUTCOME.search(header)
        runs.append({"dept": dept, "at": at, "approx": approx, "header": header.strip(),
                     "outcome": oc.group(1) if oc else "", "body": "\n".join(buf).strip()})

    for line in raw.splitlines():
        if line.startswith("## "):
            flush()
            header, buf = line[3:], []
        elif header is not None:
            buf.append(line)
    flush()
    return runs


def _bulletin_events(root: Path) -> list[dict]:
    events: list[dict] = []
    bdir = root / "bulletin"
    if not bdir.is_dir():
        return events
    for path in sorted(bdir.glob("*.md")):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            msg = f"公告 {path.name} 讀不到（{type(exc).__name__}）— 該月公告不會出現在快訊"
            warn("org-dashboard", msg, path=str(path))
            _WARNINGS.append(msg)
            continue
        for line in lines:
            if (m := _BULLETIN.match(line.strip())):
                events.append(_event(_parse_iso(m.group(1)), "bulletin", source=path.name,
                                     frm=m.group(2), title=_clip(m.group(3), 110), body=m.group(3)))
    return events


def _receipt_events(root: Path, limit: int = 60) -> list[dict]:
    events: list[dict] = []
    rdir = root / "receipts"
    if not rdir.is_dir():
        return events
    for path in sorted(rdir.glob("*.json"))[-limit:]:
        payload = _read_json(path)
        if not isinstance(payload, dict):
            continue
        at = _parse_iso(payload.get("at"))
        kind = str(payload.get("kind") or "?")
        if kind.endswith("would_fire"):
            reasons = [str(r) for r in (payload.get("reasons") or [])]
            shadow = kind.startswith("shadow")
            events.append(_event(
                at, "tick", source=path.name, frm="manager",
                title=("影子模式：" if shadow else "") +
                      ("判定該喚醒經理" if payload.get("fire") else "判定無事，跳過"),
                body="\n".join(f"· {r}" for r in reasons),
                tags=[f"{len(reasons)} 個理由"] if reasons else []))
        elif kind == "dept_wake":
            rows = [r for r in (payload.get("departments") or []) if isinstance(r, dict)]
            woken = [r for r in rows if r.get("woken")]
            events.append(_event(
                at, "wake", source=path.name, frm="manager",
                title=f"部門喚醒掃描：{len(woken)}/{len(rows)} 個被喚醒" if rows else "部門喚醒掃描",
                body="\n".join(f"· {r.get('dept')}：{'已喚醒' if r.get('woken') else '未喚醒'}"
                               f" — {r.get('reason', '')}" for r in rows)))
        elif kind == "manager_wake":
            events.append(_event(at, "wake", source=path.name, frm="manager",
                                 title="經理被喚醒", body=_clip(json.dumps(payload, ensure_ascii=False), 400)))
    return events


def collect(root: Path = ORG_ROOT) -> dict:
    _WARNINGS.clear()  # one banner per render, not an ever-growing pile
    registry = _read_json(root / "registry.json")
    if not isinstance(registry, dict) or "departments" not in registry:
        return {"available": False, "warnings": list(_WARNINGS),
                "reason": f"registry 無法讀取或格式不符：{root / 'registry.json'}"}

    routing: dict = {}
    try:  # model/effort projection is decoration — the org view must render without it
        sys.path.insert(0, str(ROOT / "scripts" / "org"))
        from dept_routing import resolve_dept_routing

        routing = resolve_dept_routing(registry).get("departments", {})
    except Exception as exc:  # noqa: BLE001
        msg = f"模型路由投影失敗（{type(exc).__name__}: {exc}）— 部門詳情不顯示 model/effort"
        warn("org-dashboard", msg, error=str(exc))
        _WARNINGS.append(msg)
        routing = {}

    events: list[dict] = []
    departments: list[dict] = []
    edges: dict[tuple[str, str, str], dict] = {}

    def note_edge(frm: str, to: str, kind: str, at: datetime | None, text: str) -> None:
        if not frm or not to or frm == to:
            return
        row = edges.setdefault((frm, to, kind), {
            "from": frm, "to": to, "kind": kind,
            "kind_label": KIND_META.get(kind, (kind, ""))[0],
            "count": 0, "last_at": "", "last_tw": "", "last": ""})
        row["count"] += 1
        if at and (not row["last_at"] or _iso(at) > row["last_at"]):
            row.update(last_at=_iso(at), last_tw=_tw(at), last=_clip(text, 90))

    def ingest(items: list[dict], holder: str) -> dict:
        """Turn one inbox into timeline events + a per-priority histogram."""
        counts = {"P1": 0, "P2": 0, "P3": 0, "open": 0, "archived": 0}
        for item in items:
            at = _parse_iso(item.get("created_at"))
            kind = str(item.get("kind") or "assignment")
            kind = kind if kind in KIND_META else "assignment"
            prio = str(item.get("priority") or "P3")
            frm, to = str(item.get("from") or "?"), str(item.get("to") or holder)
            task = str(item.get("task") or "")
            if item.get("archived"):
                counts["archived"] += 1
            else:
                counts["open"] += 1
                counts[prio] = counts.get(prio, 0) + 1
            events.append(_event(
                at, kind, source=f"{holder}/inbox", frm=frm, to=to, priority=prio,
                ident=str(item.get("id") or ""),
                title=_clip(task.splitlines()[0] if task else "(無內容)", 110), body=task,
                tags=["已歸檔"] if item.get("archived") else []))
            note_edge(frm, to, kind, at, task)
        return counts

    manager_items = _inbox_items(root / "manager" / "inbox")
    manager_counts = ingest(manager_items, "manager")
    manager_state = _read_json(root / "manager" / "state.json") or {}
    pdir = root / "manager" / "outbox" / "proposals"
    proposals = [p.name for p in sorted(pdir.glob("*.md"))] if pdir.is_dir() else []

    for name, meta in sorted((registry.get("departments") or {}).items()):
        if meta.get("status") == "retired":
            continue
        ddir = root / "departments" / name
        state = _read_json(ddir / "state.json")
        state = state if isinstance(state, dict) else {}
        items = _inbox_items(ddir / "inbox")
        counts = ingest(items, name)
        lease = _read_json(root / "runtime" / f"{name}.lease.json")
        lease = lease if isinstance(lease, dict) else None
        runs = _journal_runs(ddir / "journal.md", name)
        for run in runs:
            events.append(_event(run["at"], "run", source=f"{name}/journal.md", frm=name,
                                 title=_clip(run["header"], 110), body=run["body"],
                                 approx=run["approx"],
                                 tags=[f"outcome={run['outcome']}"] if run["outcome"] else []))

        last_run = _parse_iso(state.get("last_run"))
        health = str(state.get("health") or "unknown")
        departments.append({
            "name": name,
            "title": meta.get("title") or name,
            "icon": DEPT_ICON.get(name, "🏢"),
            "color": DEPT_COLOR.get(name, "#8b949e"),
            "status": meta.get("status", "?"),
            "cadence": meta.get("min_cadence") or "on-demand",
            "task_types": meta.get("owned_task_types") or [],
            "owned_paths": meta.get("owned_paths") or [],
            "health": health,
            "health_color": HEALTH_COLOR.get(health.lower(), "#6e7681"),
            "kpi": state.get("kpi") if isinstance(state.get("kpi"), dict) else {},
            "blockers": [b for b in (state.get("blockers") or []) if isinstance(b, dict)],
            "pending_on_others": [str(p) for p in (state.get("pending_on_others") or [])],
            "open_items": state.get("open_items"),
            "last_run_tw": _tw(last_run),
            "last_run_rel": _rel(last_run) if last_run else "尚未執行",
            "ran": bool(last_run),
            "inbox": counts,
            "lease": {
                "active": lease is not None,
                "runner": (lease or {}).get("runner", ""),
                "model": (lease or {}).get("model", ""),
                "effort": (lease or {}).get("effort", ""),
                "pane": (lease or {}).get("pane_id", ""),
                "since_tw": _tw(_parse_iso((lease or {}).get("since"))),
                "since_rel": _rel(_parse_iso((lease or {}).get("since"))),
            },
            "routing": routing.get(name, {}).get("task_routing", {}),
            "runs": [{"header": r["header"], "outcome": r["outcome"], "at_tw": _tw(r["at"]),
                      "rel": _rel(r["at"]), "approx": r["approx"], "body": r["body"]}
                     for r in sorted(runs, key=lambda r: r["at"] or _EPOCH, reverse=True)],
            "items": [{"id": str(i.get("id") or ""), "kind": str(i.get("kind") or "assignment"),
                       "priority": str(i.get("priority") or "P3"), "from": str(i.get("from") or "?"),
                       "created_tw": _tw(_parse_iso(i.get("created_at"))),
                       "rel": _rel(_parse_iso(i.get("created_at"))),
                       "archived": bool(i.get("archived")), "task": str(i.get("task") or "")}
                      for i in sorted(items, key=lambda i: str(i.get("created_at") or ""), reverse=True)],
        })

    events.extend(_bulletin_events(root))
    events.extend(_receipt_events(root))
    events.sort(key=lambda e: e["_sort"], reverse=True)
    for e in events:
        e.pop("_sort", None)

    since = _now() - timedelta(hours=24)
    recent = [e for e in events if (d := _parse_iso(e["at"])) and d >= since]
    stats = {
        "departments": len(departments),
        "blocked": sum(1 for d in departments if d["health"] == "blocked"),
        "running": sum(1 for d in departments if d["lease"]["active"]),
        "never_run": sum(1 for d in departments if not d["ran"]),
        "inbox_open": sum(d["inbox"]["open"] for d in departments) + manager_counts["open"],
        "p1_open": sum(d["inbox"].get("P1", 0) for d in departments) + manager_counts.get("P1", 0),
        "blockers": sum(len(d["blockers"]) for d in departments),
        "msgs_24h": sum(1 for e in recent if e["kind"] in FLOW_KINDS),
        "runs_24h": sum(1 for e in recent if e["kind"] == "run"),
        "events_total": len(events),
        "timeline_capped": len(events) > TIMELINE_CAP,
        "timeline_cap": TIMELINE_CAP,
    }

    gate = next((e for e in events if e["kind"] == "tick"), None)
    return {
        "available": True,
        "generated_tw": _now().astimezone(TZ).strftime("%Y-%m-%d %H:%M:%S 台灣時間"),
        "registry_updated": registry.get("updated_at", ""),
        "warnings": list(_WARNINGS),
        "manager": {
            "title": "運營經理",
            "inbox": manager_counts,
            "proposals": proposals,
            "last_tick_tw": _tw(_parse_iso(manager_state.get("last_tick"))),
            "gate": {"title": gate["title"], "rel": gate["rel"], "at_tw": gate["at_tw"],
                     "body": gate["body"]} if gate else {},
            "items": [{"id": str(i.get("id") or ""), "kind": str(i.get("kind") or "report"),
                       "priority": str(i.get("priority") or "P3"), "from": str(i.get("from") or "?"),
                       "created_tw": _tw(_parse_iso(i.get("created_at"))),
                       "rel": _rel(_parse_iso(i.get("created_at"))),
                       "archived": bool(i.get("archived")), "task": str(i.get("task") or "")}
                      for i in sorted(manager_items, key=lambda i: str(i.get("created_at") or ""),
                                      reverse=True)],
        },
        "departments": departments,
        "edges": sorted(edges.values(), key=lambda r: (-r["count"], r["from"])),
        "timeline": events[:TIMELINE_CAP],
        "stats": stats,
    }


# ---------------------------------------------------------------------------
# Page. Served live at /org (fetches /api/org); --html writes the same markup
# with the payload inlined so a snapshot can be mailed or opened offline.
# ---------------------------------------------------------------------------

PAGE = r"""<!DOCTYPE html><html lang=zh-Hant><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>VolPred · 組織全景</title><style>
*{box-sizing:border-box}
body{margin:0;font:13px/1.6 -apple-system,"PingFang TC","Noto Sans TC",sans-serif;background:#0d1117;color:#e6edf3}
a{color:#79c0ff}
header{padding:12px 18px;background:#161b22;border-bottom:1px solid #30363d;display:flex;align-items:center;
  gap:14px;flex-wrap:wrap;position:sticky;top:0;z-index:9}
h1{font-size:15px;margin:0}
.muted{color:#8b949e;font-size:11px}
.strip{display:flex;gap:8px;flex-wrap:wrap;padding:9px 18px;border-bottom:1px solid #30363d}
.warnbar{background:#3a2f10;color:#e3b341;border-bottom:1px solid #6b4f0f;padding:7px 18px;font-size:11px}
.warnbar b{color:#ffd866}
.chip{background:#161b22;border:1px solid #30363d;border-radius:7px;padding:4px 10px;font-size:11px}
.chip b{color:#79c0ff;font-size:13px}
.chip.bad b{color:#f85149}.chip.good b{color:#3fb950}.chip.warn b{color:#d29922}
section{padding:14px 18px}
h2{font-size:13px;margin:0 0 10px;color:#e6edf3;display:flex;align-items:center;gap:8px}
h2 .muted{font-weight:400}

/* hierarchy */
.chart{display:flex;flex-direction:column;align-items:center}
.mgr{width:min(520px,100%);background:#161b22;border:1px solid #30363d;border-top:3px solid #bc8cff;
  border-radius:10px;padding:11px 14px;cursor:pointer}
.mgr:hover{border-color:#8957e5}
.mgr .nm{font-size:14px;font-weight:700}
.mgr .row{display:flex;gap:8px;flex-wrap:wrap;margin-top:6px}
.trunk{width:2px;height:20px;background:#30363d}
/* One framed layer instead of a single bus line: with seven departments the row
   wraps, and a bus that only reaches the first row would draw a hierarchy that
   does not exist. Every card visibly hangs off the same layer. */
.layer{position:relative;width:100%;border:1px solid #30363d;border-radius:12px;padding:18px 14px 14px;
  background:#0f141b}
.layer .tag{position:absolute;top:-9px;left:16px;background:#0d1117;padding:0 8px;font-size:11px;color:#8b949e}
.depts{display:grid;grid-template-columns:repeat(auto-fit,minmax(232px,1fr));gap:12px;width:100%}
.dwrap{display:flex;flex-direction:column;align-items:center;height:100%}
.stem{width:2px;height:10px;background:#30363d;flex:0 0 auto}
.dept{width:100%;flex:1;background:#161b22;border:1px solid #30363d;border-top-width:3px;border-radius:9px;
  padding:9px 11px;cursor:pointer;transition:border-color .12s,transform .12s}
.dept:hover{transform:translateY(-2px)}
.dept.sel{border-color:#58a6ff;box-shadow:0 0 0 1px #1f6feb inset}
.dept .dn{font-weight:700;font-size:13px;display:flex;align-items:center;gap:6px}
.dot{width:8px;height:8px;border-radius:50%;display:inline-block;flex:0 0 auto}
.dept .sub{font-size:10px;color:#8b949e;margin-top:2px}
.badges{display:flex;gap:4px;flex-wrap:wrap;margin-top:7px}
.b{font-size:10px;border-radius:8px;padding:1px 7px;background:#21262d;color:#c9d1d9}
.b.p1{background:#3a1518;color:#ff7b72}.b.p2{background:#3a2f10;color:#e3b341}.b.p3{background:#1c2c3a;color:#79c0ff}
.b.live{background:#132e1a;color:#3fb950}
.tt{font-size:10px;color:#7d8590;margin-top:6px;line-height:1.5}
.blk{margin-top:7px;border-top:1px dashed #30363d;padding-top:5px;font-size:10px;color:#ff9492}
.pend{font-size:10px;color:#d29922;margin-top:3px}

/* flows */
.flows{display:grid;grid-template-columns:repeat(auto-fill,minmax(310px,1fr));gap:8px}
.flow{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:7px 10px;font-size:11px}
.flow .hd{display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.arrow{color:#8b949e}
.cnt{margin-left:auto;background:#21262d;border-radius:8px;padding:0 7px;font-size:10px}

/* timeline */
.filters{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px;align-items:center}
.f{font-size:11px;padding:3px 10px;border-radius:12px;border:1px solid #30363d;background:#161b22;
  color:#c9d1d9;cursor:pointer}
.f.on{background:#1f6feb;border-color:#1f6feb;color:#fff}
.tl{border-left:2px solid #21262d;margin-left:8px}
.ev{position:relative;padding:7px 0 7px 18px}
.ev::before{content:"";position:absolute;left:-6px;top:14px;width:10px;height:10px;border-radius:50%;
  background:var(--c);border:2px solid #0d1117}
.ev .hd{display:flex;gap:7px;align-items:baseline;flex-wrap:wrap}
.time{font-family:ui-monospace,monospace;font-size:11px;color:#8b949e;white-space:nowrap}
.k{font-size:10px;padding:1px 7px;border-radius:8px;font-weight:600}
.route{font-size:11px;color:#c9d1d9}
.route b{color:#e6edf3}
.ttl{font-size:12px;margin-top:2px;color:#e6edf3}
details.body{margin-top:3px}
details.body summary{font-size:10px;color:#6e7681;cursor:pointer;list-style:none}
details.body summary::-webkit-details-marker{display:none}
details.body summary:hover{color:#79c0ff}
pre.raw{white-space:pre-wrap;word-break:break-word;background:#0b0f15;border:1px solid #21262d;border-radius:7px;
  padding:8px 10px;font:11px/1.65 ui-monospace,monospace;color:#c9d1d9;margin:5px 0 0;max-height:340px;overflow:auto}

/* drawer */
.drawer{position:fixed;top:0;right:0;height:100%;width:min(560px,100%);background:#10151c;
  border-left:1px solid #30363d;transform:translateX(100%);transition:transform .16s;z-index:20;
  overflow:auto;padding:16px 18px 40px}
.drawer.open{transform:none}
.drawer h3{margin:0 0 4px;font-size:15px}
.kv{display:grid;grid-template-columns:auto 1fr;gap:3px 12px;font-size:11px;margin:8px 0}
.kv div:nth-child(odd){color:#8b949e}
.close{position:absolute;top:12px;right:14px;cursor:pointer;color:#8b949e;font-size:18px}
.sec{margin-top:14px;border-top:1px solid #21262d;padding-top:10px}
.sec h4{margin:0 0 6px;font-size:12px;color:#79c0ff}
.item{border:1px solid #21262d;border-radius:7px;padding:6px 9px;margin-bottom:6px;font-size:11px}
.scrim{position:fixed;inset:0;background:#00000080;z-index:15;display:none}
.scrim.on{display:block}
@media(max-width:700px){.bar{display:none}.trunk,.stem{height:8px}}
</style></head><body>
<header>
  <h1>🏢 VolPred · 組織全景</h1>
  <span class=muted id=gen>載入中…</span>
  <span class=muted style=margin-left:auto><a href="/">← 工作監控</a> · 每 20s 自動刷新</span>
</header>
<div class=warnbar id=warnbar style=display:none></div>
<div class=strip id=strip></div>

<section>
  <h2>組織層級 <span class=muted>點任一張卡看細節（KPI · 阻塞 · 收件匣 · 執行紀錄）</span></h2>
  <div class=chart>
    <div class=mgr id=mgr></div>
    <div class=trunk></div>
    <div class=layer><span class=tag id=layertag>部門層</span>
      <div class=depts id=depts></div>
    </div>
  </div>
</section>

<section>
  <h2>任務流向 <span class=muted>經理才能派工；部門之間只能求助（request）</span>
    <button class=f id=flowmore style=margin-left:auto>顯示全部</button></h2>
  <div class=flows id=flows></div>
</section>

<section>
  <h2>任務快訊 <span class=muted id=tlcount></span></h2>
  <div class=filters id=filters></div>
  <div class=tl id=tl></div>
</section>

<section class=muted style="border-top:1px solid #21262d;padding-top:12px">
  資料來源全部是磁碟上的組織狀態，非另存的統計：層級與轄區來自 <code>storage/org/registry.json</code>；
  部門健康 / KPI / 阻塞來自各部 <code>state.json</code>；派工·求助·回報來自 <code>inbox/</code>；
  執行紀錄來自各部 <code>journal.md</code>；巡檢與喚醒判斷來自 <code>receipts/</code>；經理公告來自 <code>bulletin/</code>。
  <span id=srcnote></span>
</section>
<div class=scrim id=scrim></div>
<div class=drawer id=drawer></div>

<script>
var DATA=null, KIND_FILTER='flow', DEPT_FILTER='';
function el(id){return document.getElementById(id)}
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){
  return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]})}
function T(n){var d=(DATA&&DATA._titles)||{};return d[n]||n}

function renderStrip(s){
  var m=DATA.manager||{};
  el('strip').innerHTML=[
    ['部門', s.departments, ''],
    ['執行中', s.running, s.running?'good':''],
    ['阻塞部門', s.blocked, s.blocked?'bad':'good'],
    ['未結阻塞', s.blockers, s.blockers?'warn':'good'],
    ['待處理收件', s.inbox_open, s.inbox_open?'warn':'good'],
    ['其中 P1', s.p1_open, s.p1_open?'bad':'good'],
    ['24h 訊息', s.msgs_24h, ''],
    ['24h 執行紀錄', s.runs_24h, ''],
    ['經理收件匣', (m.inbox||{}).open||0, ((m.inbox||{}).open?'warn':'good')]
  ].map(function(r){
    return '<span class="chip '+r[2]+'">'+esc(r[0])+' <b>'+esc(r[1])+'</b></span>'}).join('');
}

function renderMgr(){
  var m=DATA.manager||{},g=m.gate||{},i=m.inbox||{};
  el('mgr').innerHTML='<div class=nm>👔 運營經理 <span class=muted>manager</span></div>'+
    '<div class=row>'+
      '<span class="b '+(i.open?'p1':'')+'">收件匣 '+esc(i.open||0)+'</span>'+
      '<span class=b>待批提案 '+esc((m.proposals||[]).length)+'</span>'+
      '<span class=b>上次 tick '+esc(m.last_tick_tw||'—')+'</span>'+
    '</div>'+
    (g.title?'<div class=tt>最近巡檢判斷（'+esc(g.at_tw)+' · '+esc(g.rel)+'）：'+esc(g.title)+'</div>':'');
  el('mgr').onclick=function(){openManager()};
}

function renderDepts(){
  var s=DATA.stats||{};
  el('layertag').textContent='部門層 · '+s.departments+' 個部門'+
    (s.blocked?' · '+s.blocked+' 個阻塞':'')+(s.running?' · '+s.running+' 個有執行 session':'');
  el('depts').innerHTML=DATA.departments.map(function(d){
    var i=d.inbox||{},L=d.lease||{};
    var badges=[];
    if(i.P1)badges.push('<span class="b p1">P1 '+i.P1+'</span>');
    if(i.P2)badges.push('<span class="b p2">P2 '+i.P2+'</span>');
    if(i.P3)badges.push('<span class="b p3">P3 '+i.P3+'</span>');
    if(!i.open)badges.push('<span class=b>收件匣清空</span>');
    if(L.active)badges.push('<span class="b live">▶ '+esc(L.model||'?')+'/'+esc(L.effort||'?')+
      (L.pane?' · '+esc(L.pane):'')+(L.since_rel?' · '+esc(L.since_rel)+'起':'')+'</span>');
    var b0=(d.blockers||[])[0]||{};
    var blk=(d.blockers||[]).length?'<div class=blk>⛔ 阻塞 '+d.blockers.length+'：'+
      esc(String(b0.what||'').slice(0,60))+'…</div>':'';
    var pend=(d.pending_on_others||[]).length?'<div class=pend>⏳ 等待他部 '+d.pending_on_others.length+' 項</div>':'';
    return '<div class=dwrap><div class=stem></div>'+
      '<div class="dept'+(DEPT_FILTER===d.name?' sel':'')+'" style="border-top-color:'+esc(d.color)+
        '" data-d="'+esc(d.name)+'">'+
        '<div class=dn><span class=dot style="background:'+esc(d.health_color)+'"></span>'+
          esc(d.icon)+' '+esc(d.title)+'</div>'+
        '<div class=sub>'+esc(d.name)+' · '+esc(d.cadence)+' · 狀態 '+esc(d.health)+'</div>'+
        '<div class=sub>上次執行 '+esc(d.last_run_rel)+(d.ran?'（'+esc(d.last_run_tw)+'）':'')+'</div>'+
        '<div class=badges>'+badges.join('')+'</div>'+
        (d.task_types.length?'<div class=tt>'+esc(d.task_types.join(' · '))+'</div>':'')+
        blk+pend+
      '</div></div>';
  }).join('');
  Array.prototype.forEach.call(document.querySelectorAll('.dept'),function(n){
    n.onclick=function(){openDept(n.getAttribute('data-d'))};
  });
}

var FLOW_ALL=false, FLOW_TOP=12;
function renderFlows(){
  var all=(DATA.edges||[]).filter(function(e){return e.kind!=='cc'});
  var rows=FLOW_ALL?all:all.slice(0,FLOW_TOP);
  el('flowmore').textContent=FLOW_ALL?'只看前 '+FLOW_TOP+' 條':'顯示全部（'+all.length+' 條）';
  el('flowmore').onclick=function(){FLOW_ALL=!FLOW_ALL;renderFlows()};
  el('flows').innerHTML=rows.map(function(e){
    var c=(DATA._kindColor||{})[e.kind]||'#8b949e';
    return '<div class=flow><div class=hd>'+
      '<b>'+esc(T(e.from))+'</b><span class=arrow>→</span><b>'+esc(T(e.to))+'</b>'+
      '<span class=k style="background:'+c+'22;color:'+c+'">'+esc(e.kind_label)+'</span>'+
      '<span class=cnt>'+esc(e.count)+' 則</span></div>'+
      (e.last?'<div class=muted style="margin-top:3px">最近 '+esc(e.last_tw)+'：'+esc(e.last)+'</div>':'')+
    '</div>';
  }).join('')||'<div class=muted>尚無跨層級訊息</div>';
}

var FILTERS=[['flow','任務流（派工/求助/回報）'],['assignment','派工'],['request','求助'],
  ['report','回報'],['run','執行紀錄'],['bulletin','經理公告'],['tick','巡檢/喚醒'],['all','全部']];
function renderFilters(){
  el('filters').innerHTML=FILTERS.map(function(f){
    return '<button class="f'+(KIND_FILTER===f[0]?' on':'')+'" data-k="'+f[0]+'">'+esc(f[1])+'</button>'}).join('')+
    (DEPT_FILTER?'<button class="f on" data-k="__dept">僅看 '+esc(T(DEPT_FILTER))+' ✕</button>':'');
  Array.prototype.forEach.call(document.querySelectorAll('.f'),function(n){
    n.onclick=function(){
      var k=n.getAttribute('data-k');
      if(k==='__dept'){DEPT_FILTER='';renderDepts()}else{KIND_FILTER=k}
      renderFilters();renderTimeline();
    };
  });
}

function match(e){
  if(DEPT_FILTER && e.from!==DEPT_FILTER && e.to!==DEPT_FILTER) return false;
  if(KIND_FILTER==='all') return true;
  if(KIND_FILTER==='flow') return ['assignment','request','reply','report','cc'].indexOf(e.kind)>=0;
  if(KIND_FILTER==='tick') return e.kind==='tick'||e.kind==='wake';
  return e.kind===KIND_FILTER;
}

function nl(s){return String(s==null?'':s).replace(/\\n/g,'\n')}
function renderTimeline(){
  var rows=(DATA.timeline||[]).filter(match),s=DATA.stats||{};
  el('tlcount').textContent='顯示 '+rows.length+' / 共 '+s.events_total+' 則事件（新→舊，台灣時間）'+
    (s.timeline_capped?'；本頁只載入最近 '+s.timeline_cap+' 則':'');
  el('tl').innerHTML=rows.map(function(e){
    var route=e.to?('<b>'+esc(T(e.from))+'</b> → <b>'+esc(T(e.to))+'</b>')
                   :('<b>'+esc(T(e.from||'—'))+'</b>');
    var pr=e.priority?'<span class="b '+esc(e.priority.toLowerCase())+'">'+esc(e.priority)+'</span>':'';
    var tags=(e.tags||[]).map(function(t){return '<span class=b>'+esc(t)+'</span>'}).join('');
    var body=e.body&&e.body.length>0?
      '<details class=body><summary>展開全文（'+e.body.length+' 字）</summary><pre class=raw>'+
        esc(nl(e.body))+'</pre></details>':'';
    return '<div class=ev style="--c:'+esc(e.color)+'">'+
      '<div class=hd><span class=time>'+esc(e.at_tw)+(e.approx?'*':'')+'</span>'+
        '<span class=k style="background:'+esc(e.color)+'22;color:'+esc(e.color)+'">'+esc(e.kind_label)+'</span>'+
        '<span class=route>'+route+'</span>'+pr+tags+
        '<span class=muted style=margin-left:auto>'+esc(e.rel)+'</span></div>'+
      '<div class=ttl>'+esc(e.title)+'</div>'+body+'</div>';
  }).join('')||'<div class=muted style=padding:10px>此篩選下沒有事件</div>';
}

function drawer(html){el('drawer').innerHTML='<span class=close id=dx>✕</span>'+html;
  el('drawer').classList.add('open');el('scrim').classList.add('on');
  el('dx').onclick=closeDrawer;el('drawer').scrollTop=0}
function closeDrawer(){el('drawer').classList.remove('open');el('scrim').classList.remove('on')}
el('scrim').onclick=closeDrawer;
document.addEventListener('keydown',function(e){if(e.key==='Escape')closeDrawer()});

function itemsHtml(items,empty){
  if(!items||!items.length) return '<div class=muted>'+esc(empty)+'</div>';
  return items.map(function(i){
    var c=(DATA._kindColor||{})[i.kind]||'#8b949e';
    return '<div class=item>'+
      '<div class=hd><span class="b '+esc((i.priority||'').toLowerCase())+'">'+esc(i.priority)+'</span> '+
      '<span class=k style="background:'+c+'22;color:'+c+'">'+esc(i.kind)+'</span> '+
      '<span class=muted>來自 '+esc(T(i.from))+' · '+esc(i.created_tw)+' · '+esc(i.rel)+
      (i.archived?' · 已歸檔':'')+'</span></div>'+
      '<div style=margin-top:3px>'+esc(nl(i.task).split('\n')[0].slice(0,150))+'</div>'+
      (i.task.length>150?'<details class=body><summary>展開全文</summary><pre class=raw>'+esc(nl(i.task))+
        '</pre></details>':'')+
    '</div>';
  }).join('');
}

function openManager(){
  var m=DATA.manager||{},g=m.gate||{};
  drawer('<h3>👔 運營經理</h3><div class=muted>storage/org/manager/ · 派工的唯一來源</div>'+
    '<div class=kv><div>收件匣</div><div>'+esc((m.inbox||{}).open||0)+' 件未處理（已歸檔 '+
      esc((m.inbox||{}).archived||0)+'）</div>'+
    '<div>待批提案</div><div>'+esc((m.proposals||[]).join('、')||'無')+'</div>'+
    '<div>上次 tick</div><div>'+esc(m.last_tick_tw||'—')+'</div></div>'+
    (g.title?'<div class=sec><h4>最近巡檢判斷 · '+esc(g.at_tw)+'</h4><div>'+esc(g.title)+'</div>'+
      (g.body?'<pre class=raw>'+esc(g.body)+'</pre>':'')+'</div>':'')+
    '<div class=sec><h4>收件匣（部門回報 / 知會）</h4>'+itemsHtml(m.items,'收件匣清空')+'</div>');
}

function openDept(name){
  var d=(DATA.departments||[]).filter(function(x){return x.name===name})[0];
  if(!d)return;
  DEPT_FILTER=name;renderDepts();renderFilters();renderTimeline();
  var L=d.lease||{},kpi=d.kpi||{};
  var kpiHtml=Object.keys(kpi).length?'<div class=kv>'+Object.keys(kpi).map(function(k){
    return '<div>'+esc(k)+'</div><div>'+esc(typeof kpi[k]==='object'?JSON.stringify(kpi[k]):kpi[k])+'</div>'
  }).join('')+'</div>':'<div class=muted>本部門尚未回報 KPI</div>';
  var blk=(d.blockers||[]).length?(d.blockers||[]).map(function(b){
    return '<div class=item><div style="color:#ff9492">⛔ '+esc(b.what||'')+'</div>'+
      (b.workaround?'<div class=muted style=margin-top:3px>暫行處置：'+esc(b.workaround)+'</div>':'')+
      (b.escalated_to?'<div class=muted>已上報：'+esc(T(b.escalated_to))+'</div>':'')+'</div>';
  }).join(''):'<div class=muted>無</div>';
  var pend=(d.pending_on_others||[]).length?'<ul style="margin:4px 0 0 16px;padding:0;font-size:11px">'+
    d.pending_on_others.map(function(p){return '<li>'+esc(p)+'</li>'}).join('')+'</ul>':'<div class=muted>無</div>';
  var routing=Object.keys(d.routing||{}).length?'<div class=kv>'+Object.keys(d.routing).map(function(t){
    var r=d.routing[t];return '<div>'+esc(t)+'</div><div>'+esc(r.model)+' / '+esc(r.effort)+
      (r.mapped===false?' <span style="color:#f85149">[未對照]</span>':'')+'</div>'}).join('')+'</div>':'';
  var runs=(d.runs||[]).length?(d.runs||[]).map(function(r){
    return '<div class=item><div><b>'+esc(r.header)+'</b></div>'+
      '<div class=muted>'+esc(r.at_tw)+(r.approx?'（僅標日期）':'')+' · '+esc(r.rel)+
      (r.outcome?' · outcome='+esc(r.outcome):'')+'</div>'+
      (r.body?'<details class=body><summary>展開紀錄</summary><pre class=raw>'+esc(nl(r.body))+'</pre></details>':'')+
    '</div>'}).join(''):'<div class=muted>尚無 journal 紀錄</div>';

  drawer('<h3>'+esc(d.icon)+' '+esc(d.title)+' <span class=muted>'+esc(d.name)+'</span></h3>'+
    '<div class=muted>storage/org/departments/'+esc(d.name)+'/</div>'+
    '<div class=kv>'+
      '<div>健康</div><div style="color:'+esc(d.health_color)+'">'+esc(d.health)+'</div>'+
      '<div>上次執行</div><div>'+esc(d.ran?d.last_run_tw+'（'+d.last_run_rel+'）':'尚未執行')+'</div>'+
      '<div>節奏</div><div>'+esc(d.cadence)+'</div>'+
      '<div>收件匣</div><div>'+esc((d.inbox||{}).open||0)+' 件未處理 · P1 '+esc((d.inbox||{}).P1||0)+'</div>'+
      '<div>執行中</div><div>'+(L.active?esc(L.runner+' · '+L.model+'/'+L.effort+' · '+L.pane+
        '（'+L.since_rel+'）'):'未啟動')+'</div>'+
      '<div>擁有任務類型</div><div>'+esc((d.task_types||[]).join('、')||'—')+'</div>'+
      '<div>擁有路徑</div><div>'+esc((d.owned_paths||[]).join('、')||'—')+'</div>'+
    '</div>'+
    (routing?'<div class=sec><h4>模型路由（由 model_router 投影）</h4>'+routing+'</div>':'')+
    '<div class=sec><h4>KPI（部門自報）</h4>'+kpiHtml+'</div>'+
    '<div class=sec><h4>阻塞</h4>'+blk+'<h4 style=margin-top:8px>等待其他部門</h4>'+pend+'</div>'+
    '<div class=sec><h4>收件匣</h4>'+itemsHtml(d.items,'收件匣清空')+'</div>'+
    '<div class=sec><h4>執行紀錄（journal）</h4>'+runs+'</div>');
}

function renderWarnings(w){
  var bar=el('warnbar');
  if(!w||!w.length){bar.style.display='none';bar.innerHTML='';return}
  bar.style.display='block';
  bar.innerHTML='<b>⚠️ 這一頁有 '+w.length+' 處讀不到的來源，畫面因此不完整：</b> '+
    w.map(function(x){return esc(x)}).join('｜');
}
function render(d){
  DATA=d;
  renderWarnings(d&&d.warnings);
  if(!d||!d.available){
    el('gen').textContent=(d&&d.reason)||'組織未初始化';
    el('depts').innerHTML='';el('mgr').innerHTML='';return;
  }
  DATA._titles={manager:'運營經理'};
  (d.departments||[]).forEach(function(x){DATA._titles[x.name]=x.title});
  DATA._kindColor={};(d.timeline||[]).forEach(function(e){DATA._kindColor[e.kind]=e.color});
  el('gen').textContent='更新於 '+d.generated_tw;
  el('srcnote').textContent='註記 * 的時間表示該 journal 標題只寫了日期，時間為當日起算的近似值。'+
    ' registry 最後更新 '+(d.registry_updated||'—')+'。';
  renderStrip(d.stats||{});renderMgr();renderDepts();renderFlows();renderFilters();renderTimeline();
}

function load(){
  fetch('/api/org').then(function(r){return r.json()}).then(render)
    .catch(function(e){el('gen').textContent='讀取失敗：'+e});
}
if(window.__ORG_SNAPSHOT__){render(window.__ORG_SNAPSHOT__)}else{load();setInterval(load,20000)}
</script></body></html>"""


def render_standalone(snapshot: dict) -> str:
    """Same page with the payload inlined — for offline snapshots / mail."""
    payload = json.dumps(snapshot, ensure_ascii=False)
    return PAGE.replace(
        "<script>\nvar DATA=null",
        f"<script>\nwindow.__ORG_SNAPSHOT__={payload};\nvar DATA=null",
        1,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ORG_ROOT)
    parser.add_argument("--html", type=Path, help="write a standalone snapshot page here")
    args = parser.parse_args()

    snap = collect(args.root)
    if args.html:
        args.html.write_text(render_standalone(snap), encoding="utf-8")
        print(f"wrote {args.html}")
    else:
        print(json.dumps(snap, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
