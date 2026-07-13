#!/usr/bin/env python3
"""產出即交付 — 把「寫完了但沒進系統」的成品自動收編，永不丟棄。

老闆 Telegram msg 624：完成的產出最後只能棄用 = 浪費 token。要求從底層邏輯修。

## 為什麼會有孤兒成品

一份 reader-facing 草稿要真正「交付」，需要兩件事：檔案寫進 `storage/drafts/`，
以及走 `publish_draft.py` 註冊進 feed（草稿池 → release cron 發出去）。producer 只做了
第一件事就結束的情況一直存在 —— 尤其是 fire lane 以外的 producer（codex-vscode session、
async render job）。對系統來說，只寫了檔案的成品**不存在**：feed 查不到、release 排不到、
dashboard 看不到。它唯一的痕跡是 `git status` 裡一行未追蹤檔案。

於是它被當成「垃圾」處理。PHASE-Z 看到不是自己這班產的檔案就不收（那道防線是對的 ——
盲目 `git add -A` 造成過三次事故），連續幾班沒人收就升級成 critical，而那封信的出口寫著
「人工判斷後二選一：commit 或丟棄」。一份寫完的深度文章，就這樣走到「丟棄」那一格。

## 這支程式怎麼修

修的不是 git，是**交付路徑**。git 收養與否是 PHASE-Z 的事，這裡不碰；這裡負責讓成品
走它本來就該走的正規入口（`publish_draft.py`），由那條路徑做完所有 gate 並註冊進池。
檔案進了池，PHASE-Z 自然會在同一班把它連同 feed 一起 commit —— 因為那時它是**這班產的**。

三條硬規則：
1. **永不刪除、永不 checkout**。認不出來源的成品只會被「保留 + 回報」，不會被丟棄。
   這支程式裡沒有任何一行會刪檔，這是設計上的不變量，不是自律。
2. **偏向不收養**。判斷不確定時寧可漏收（檔案留著、下班再看）也不重複發佈 ——
   漏收的代價是延遲，重複發佈的代價是網站上出現兩篇一樣的文章。
3. **只管 cutover 之後的成品**。`storage/ops/orphan_draft_baseline.json` 凍結了改動前
   已存在的草稿（多數早已發佈，只是當年沒留下 provenance 欄位）。baseline 只准變少。

## 交付憑證

`publish_draft.py` 現在會把 `details.source_draft` 寫進 feed entry —— 草稿檔與文章之間
第一次有了機器可查的連結。在這之前，「這份草稿發了沒」只能靠標題比對用猜的，
而猜不出來的那些，就是被判死的那些。

用法：
    uv run python scripts/reap_orphan_deliverables.py              # 掃描 + 回報（預設）
    uv run python scripts/reap_orphan_deliverables.py --apply      # 收編（跑正規入池）
    uv run python scripts/reap_orphan_deliverables.py --init-baseline   # 一次性 cutover
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from volpred.ops.diagnostics import warn  # noqa: E402

DRAFTS_DIR = ROOT / "storage" / "drafts"
FEED_PATH = ROOT / "storage" / "reports" / "feed.json"
TASKS_PATH = ROOT / "storage" / "next_tasks.json"
BASELINE_PATH = ROOT / "storage" / "ops" / "orphan_draft_baseline.json"
REPORT_PATH = ROOT / "storage" / "ops" / "orphan_reap_report.json"

# A draft younger than this is presumed to still have an author typing into it.
# Adopting mid-write would publish half an article — the one failure mode worse
# than leaving it alone for an hour.
GRACE_SECONDS = 2 * 3600

# Outward-facing writes are rate-limited on purpose. If ten orphans show up at
# once, something upstream is broken and dumping ten articles onto the site is
# not the fix — the report will say so and the next run takes the next two.
DEFAULT_MAX_ADOPT = 2

# Below this, a "draft" is a stub or a scratch note, not a deliverable. Held for
# the author, never discarded.
MIN_BODY_CHARS = 800


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        # Fail-open is right here (a missing feed must not stop the sweep) but it
        # must not be silent: an unreadable feed makes every draft look unregistered,
        # which is the one input that could push this thing toward over-adopting.
        warn("reap_orphan", "load failed — treating as empty",
             path=str(path), err=str(exc))
        return default


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Return (frontmatter, body). Tolerates a missing/malformed block.

    Deliberately not a YAML dependency: we only need scalar keys, and a draft
    with exotic YAML is exactly the kind we want to hand back to its author
    rather than guess at.
    """
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    raw = text[3:end]
    body = text[end + 4:].lstrip("\n")
    fm: dict[str, str] = {}
    for line in raw.splitlines():
        if ":" not in line or line.lstrip().startswith("#"):
            continue
        key, _, val = line.partition(":")
        fm[key.strip()] = val.strip().strip('"').strip("'")
    return fm, body


def _norm_title(title: str) -> str:
    """Collapse whitespace/punctuation so a title match survives light editing."""
    return re.sub(r"[\s　·・\-—–|｜:：,，.。!！?？]+", "", title or "").lower()


def _k_ids(fm: dict, body: str) -> set[str]:
    found = set()
    for src in (fm.get("kid", ""), fm.get("k_id", ""), fm.get("experiment_refs", "")):
        found.update(re.findall(r"[Kk]\d{3,4}", src or ""))
    return {k.upper() for k in found}


def load_baseline() -> set[str]:
    data = _load_json(BASELINE_PATH, {})
    return set(data.get("drafts", []))


def is_registered(rel: str, fm: dict, body: str, feed: list[dict]) -> tuple[bool, str]:
    """Has this draft already been delivered as an article?

    Three probes, strongest first. Any hit means "leave it alone" — the bias is
    deliberate and asymmetric: a missed orphan costs a delay, a double-publish
    costs the reader two copies of the same article on the site.
    """
    for art in feed:
        details = art.get("details") or {}
        if isinstance(details, dict) and details.get("source_draft") == rel:
            return True, f"source_draft → {art.get('id')}"

    # Pre-provenance window: articles published before `source_draft` existed
    # carry no back-link. Title is the only honest fallback.
    title = _norm_title(fm.get("title", ""))
    if title:
        for art in feed:
            if _norm_title(art.get("title", "")) == title:
                return True, f"title match → {art.get('id')}"

    # A K already covered for this audience means the finding has shipped; a
    # second draft of it is a duplicate, not an orphan (the arc-dedup gate would
    # have blocked it at write time anyway).
    kids = _k_ids(fm, body)
    audience = (fm.get("audience") or "").strip()
    if kids and audience:
        for art in feed:
            if (art.get("audience") or "") != audience:
                continue
            refs = ((art.get("details") or {}).get("experiment_refs")) or []
            if isinstance(refs, list) and kids & {str(r).upper() for r in refs}:
                return True, f"K-coverage → {art.get('id')}"
    return False, ""


def _inflight_stems(tasks: list[dict]) -> set[str]:
    """Draft stems a live task is still working on — not orphans, just in flight."""
    live = {"claimed", "in_progress"}
    blob = " ".join(
        json.dumps(t, ensure_ascii=False)
        for t in tasks
        if isinstance(t, dict) and t.get("status") in live
    )
    return set(re.findall(r"[\w\-]+(?=_draft\.md)", blob)) | set(
        re.findall(r"storage/drafts/([\w\-.]+)\.md", blob)
    )


def scan(*, now_ts: float | None = None) -> dict:
    """Classify every post-cutover draft. Pure read — writes nothing, deletes nothing."""
    now_ts = now_ts if now_ts is not None else time.time()
    feed = _load_json(FEED_PATH, [])
    feed = feed if isinstance(feed, list) else []
    tasks = _load_json(TASKS_PATH, [])
    tasks = tasks if isinstance(tasks, list) else tasks.get("tasks", []) if isinstance(tasks, dict) else []
    baseline = load_baseline()
    inflight = _inflight_stems(tasks)

    adoptable: list[dict] = []
    held: list[dict] = []
    skipped = {"baseline": 0, "registered": 0, "grace": 0, "inflight": 0}

    for path in sorted(DRAFTS_DIR.glob("*.md")) if DRAFTS_DIR.is_dir() else []:
        rel = str(path.relative_to(ROOT))
        if rel in baseline:
            skipped["baseline"] += 1
            continue
        try:
            stat = path.stat()
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            warn("reap_orphan", "draft unreadable — held, not discarded",
                 path=rel, err=str(exc))
            held.append({"path": rel, "reason": "unreadable", "detail": str(exc)})
            continue

        age_s = now_ts - stat.st_mtime
        if age_s < GRACE_SECONDS:
            skipped["grace"] += 1
            continue
        if path.stem in inflight or path.stem.replace("_draft", "") in inflight:
            skipped["inflight"] += 1
            continue

        fm, body = parse_frontmatter(text)
        registered, why = is_registered(rel, fm, body, feed)
        if registered:
            skipped["registered"] += 1
            continue

        # From here on it is an orphan: on disk, finished-looking, unknown to the
        # product. The only question left is whether we can route it ourselves.
        if not fm.get("title"):
            held.append({"path": rel, "reason": "no_title",
                         "detail": "缺 frontmatter title — 入池需要標題，保留等作者確認"})
            continue
        if len(body.strip()) < MIN_BODY_CHARS:
            held.append({"path": rel, "reason": "too_short",
                         "detail": f"正文 {len(body.strip())} 字 < {MIN_BODY_CHARS} — 像半成品，保留"})
            continue
        adoptable.append({
            "path": rel,
            "title": fm.get("title", ""),
            "audience": fm.get("audience", ""),
            "status": fm.get("status") or "draft",
            "body_chars": len(body.strip()),
            "age_hours": round(age_s / 3600, 1),
        })

    return {
        "generated_at": _now().isoformat(),
        "adoptable": adoptable,
        "held": held,
        "skipped": skipped,
        "orphan_count": len(adoptable) + len(held),
    }


def adopt(entry: dict, *, timeout_s: int = 900) -> dict:
    """Route one orphan through the canonical intake. Never touches the file itself.

    `publish_draft.py` owns every gate (anti-AI, arc-dedup, image, lazypack) and
    every write to feed.json. Calling it — rather than re-implementing intake here
    — is what keeps this a delivery fix instead of a second, competing publisher.
    """
    cmd = [
        "uv", "run", "python", "scripts/publish_draft.py", entry["path"],
        "--status", entry.get("status") or "draft",
    ]
    try:
        proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout_s)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return {"path": entry["path"], "adopted": False, "reason": f"intake_error: {exc}"}
    if proc.returncode == 0:
        return {"path": entry["path"], "adopted": True, "reason": "published_into_pool"}
    tail = (proc.stderr or proc.stdout or "").strip().splitlines()
    return {
        "path": entry["path"],
        "adopted": False,
        # A gate rejection is a real answer, not a failure to be papered over: the
        # draft stays on disk, the report says which gate said no, and a human or
        # a later fire fixes the draft. Nothing is discarded either way.
        "reason": f"gate_rejected (rc={proc.returncode}): {tail[-1][:200] if tail else 'no output'}",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true",
                    help="實際收編（跑 publish_draft 入池）。預設只掃描回報。")
    ap.add_argument("--max", type=int, default=DEFAULT_MAX_ADOPT,
                    help=f"單次最多收編幾份（預設 {DEFAULT_MAX_ADOPT}）")
    ap.add_argument("--init-baseline", action="store_true",
                    help="一次性 cutover：把現存草稿全數凍結為 baseline（豁免）")
    ap.add_argument("--json", action="store_true", help="只輸出 JSON")
    args = ap.parse_args()

    if args.init_baseline:
        drafts = sorted(str(p.relative_to(ROOT)) for p in DRAFTS_DIR.glob("*.md"))
        BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
        BASELINE_PATH.write_text(json.dumps({
            "note": "改動前既存草稿（多數早已發佈，只是當年沒有 source_draft provenance）。"
                    "只准變少：確認某份已交付或已收編就從這裡移除。",
            "cutover_at": _now().isoformat(),
            "drafts": drafts,
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"[reap] baseline 凍結 {len(drafts)} 份既存草稿 → {BASELINE_PATH.relative_to(ROOT)}")
        return 0

    result = scan()
    adopted: list[dict] = []
    if args.apply:
        for entry in result["adoptable"][: args.max]:
            outcome = adopt(entry)
            adopted.append(outcome)
            print(f"[reap] {'收編' if outcome['adopted'] else '未收編'}: "
                  f"{entry['path']} — {outcome['reason']}")
        if len(result["adoptable"]) > args.max:
            print(f"[reap] 本次上限 {args.max}，還有 "
                  f"{len(result['adoptable']) - args.max} 份待下次收編（沒有丟棄）")
    result["adopted"] = adopted
    result["applied"] = args.apply

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")

    if args.json:
        print(json.dumps(result, ensure_ascii=False))
        return 0

    print(f"[reap] 孤兒成品 {result['orphan_count']} 份："
          f"可收編 {len(result['adoptable'])}、保留待確認 {len(result['held'])}")
    print(f"[reap] 略過：{result['skipped']}")
    for h in result["held"][:10]:
        print(f"  - 保留 {h['path']} — {h['detail']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
