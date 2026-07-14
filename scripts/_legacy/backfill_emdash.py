#!/usr/bin/env python3
"""一次性 backfill：把既有 published 文章的補充式破折號 AI tell 收斂為逗號。

背景（2026-05-29 老闆「你決定就好」授權執行）：publisher + supabase_sync 已掛
`emdash_normalizer`（forward fix），新文章與 re-sync 文章自動清理；但既有 ~753
篇 feed.json 內文仍含破折號，多數不會自然 re-sync。本腳本把既有內容一次補齊。

設計（永遠修流程不修資料）：
- 復用 production normalizer `volpred.publisher.emdash_normalizer.normalize_emdash`
  （非另寫一套 regex）→ 與 publish-time 行為 byte-identical
- **diff 安全斷言**：逐篇驗證「改動前後唯一差異只有 `—`→`，`」— 任何其他字元
  變動即 abort（保護內容語意，研究誠實延伸）
- feed.json git-tracked → 可 `git checkout` 回滾
- `--apply` 才寫檔；`--sync` 才推 Supabase（預設 dry-run，只報告）

用法：
  uv run python scripts/backfill_emdash.py              # dry-run，報告會改幾篇
  uv run python scripts/backfill_emdash.py --apply       # 寫 feed.json（不 sync）
  uv run python scripts/backfill_emdash.py --apply --sync  # 並推 Supabase
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FEED = ROOT / "storage" / "reports" / "feed.json"
sys.path.insert(0, str(ROOT / "src"))

from volpred.publisher.emdash_normalizer import normalize_emdash  # noqa: E402


def _diff_is_emdash_only(before: str, after: str) -> bool:
    """核心安全斷言：剝掉 `—` 與 `，` 兩種字元後，before 與 after 必須完全相同
    → 保證唯一變動只發生在這兩種字元上，其他內容（數字/英數/結構/標點）byte 不變。

    count 關係：normalizer 把連續 `——` collapse 成單一 `，`，故「移除的 `—`」
    可多於「新增的 `，`」。只需確認方向正確：沒有反向新增破折號、沒有刪逗號。"""
    if before.replace("—", "").replace("，", "") != after.replace("—", "").replace("，", ""):
        return False
    removed_emdash = before.count("—") - after.count("—")
    added_comma = after.count("，") - before.count("，")
    # 方向性：只會移除破折號（≥0）、只會新增逗號（≥0）、且移除量 ≥ 新增量
    return removed_emdash >= added_comma >= 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="實際寫回 feed.json")
    ap.add_argument("--sync", action="store_true", help="推改動文章到 Supabase")
    args = ap.parse_args()

    def _process(feed: list) -> tuple[list[dict], int, list[str]]:
        changed: list[dict] = []
        total = 0
        aborted: list[str] = []
        for art in feed:
            if not isinstance(art, dict) or art.get("status") != "published":
                continue
            content = art.get("content") or ""
            if not content or "—" not in content:
                continue
            new_content, rep = normalize_emdash(content)
            if not rep.changed:
                continue
            if not _diff_is_emdash_only(content, new_content):
                aborted.append(art.get("id", "?"))
                continue
            if args.apply:
                art["content"] = new_content
            changed.append(art)
            total += rep.replaced
        return changed, total, aborted

    if not args.apply:
        feed = json.loads(FEED.read_text(encoding="utf-8"))
        changed, total_repl, aborted = _process(feed)
        print(f"[backfill_emdash] published 含破折號且可安全收斂: {len(changed)} 篇, "
              f"共 {total_repl} 處 `—`→`，`")
        if aborted:
            print(f"  ⚠️ {len(aborted)} 篇 diff 非純破折號變動，已跳過: {aborted[:10]}")
        print("  (dry-run — 加 --apply 寫回 feed.json)")
        return 0

    # apply：拿 publisher 同一把 shared lock，鎖內重讀+寫回，避免覆蓋並發 publish
    from volpred.ops.shared_lock import shared_state_lock
    storage_dir = str(FEED.parent.parent)
    with shared_state_lock("publisher_feed", storage_dir=storage_dir):
        feed = json.loads(FEED.read_text(encoding="utf-8"))  # 鎖內重讀（最新）
        changed, total_repl, aborted = _process(feed)
        print(f"[backfill_emdash] 鎖內重讀後可安全收斂: {len(changed)} 篇, "
              f"共 {total_repl} 處 `—`→`，`")
        if aborted:
            print(f"  ⚠️ {len(aborted)} 篇跳過（diff 非純破折號）: {aborted[:10]}")
        tmp = FEED.with_name(f".{FEED.name}.backfill.tmp")
        tmp.write_text(json.dumps(feed, indent=2, ensure_ascii=False), encoding="utf-8")
        json.loads(tmp.read_text(encoding="utf-8"))  # parse sanity
        tmp.replace(FEED)
    print(f"  ✅ feed.json 已更新 ({len(changed)} 篇)")

    if args.sync:
        from importlib import import_module
        ss = import_module("scripts.supabase_sync") if False else None  # noqa
        sys.path.insert(0, str(ROOT / "scripts"))
        import supabase_sync as ss  # noqa: E402
        ok = fail = 0
        for art in changed:
            try:
                if ss.sync_article(art):
                    ok += 1
                else:
                    fail += 1
            except Exception as exc:  # noqa: BLE001
                fail += 1
                print(f"  sync err {art.get('id')}: {type(exc).__name__}: {exc}", file=sys.stderr)
        print(f"  Supabase sync: ok={ok} fail={fail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
