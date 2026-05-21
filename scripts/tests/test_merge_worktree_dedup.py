#!/usr/bin/env python3
"""
test_merge_worktree_dedup.py — Post-merge knowledge.json integrity gate.

驗證 `scripts/merge_worktree.sh` jq dedup 結束後，`storage/memory/knowledge.json`
（或任何 JSON list of entries）的 id / title / content / experiment_id 自我一致，
且無 duplicate id / 異常檔案大小。

歷史背景：
  - 2026-04-10: knowledge.json bloat 50,304 entries 96.4% duplicates
    → merge_worktree.sh jq dedup bug
  - 2026-05-08: 25 entries id-vs-title misalignment（K932-K956 ids 帶 K109-K140 legacy
    content）→ 同一個 jq dedup bug 的另一種 silent corruption mode

兩次 incident 都是 jq dedup 的 silent corruption — script 跑完沒驗證資料完整性
就 commit 進 git history。

用法：
    # 驗證 production 檔（absolute mode — 報告所有 hard fail）
    python3 scripts/tests/test_merge_worktree_dedup.py

    # 驗證指定路徑
    python3 scripts/tests/test_merge_worktree_dedup.py path/to/knowledge.json

    # Delta mode（推薦於 merge_worktree.sh 整合）：與 baseline file 比對，
    # 只在 *新增* 失敗時 exit 1。Baseline 從 pre-merge state 抽取。
    python3 scripts/tests/test_merge_worktree_dedup.py --baseline /tmp/pre_merge_baseline.json
    python3 scripts/tests/test_merge_worktree_dedup.py --emit-baseline /tmp/pre_merge_baseline.json

    # CI / regression：跑 fixture-based test cases (見 tests/test_merge_worktree_dedup_regression.py)

退出碼：
    0 = all checks PASS（或 delta mode 下無新增 failure）
    1 = ≥1 hard check FAIL（id-vs-title / content-id / exp-id / duplicate）；
        delta mode 下指 *新增* 的 failure
    2 = file 不存在 / JSON parse error / baseline 不可讀
    （size warning 不會 exit non-zero — 只在 stderr 印警告）

整合於 merge_worktree.sh 末尾：
    pre-merge 抽 baseline → merge → 跑 --baseline 模式
    若 exit 1 → main caller revert 到 pre-merge state
    若 exit 2 → 印 abort hint，保留 worktree 待人工處理

歷史已存在 corruption（pre-2026-05-08 dedup bug 殘留，~26 個 K-id 各有 2 entry）
不是本 gate 的修復目標 — delta mode 容忍 baseline，只攔截**新**問題。
單獨 absolute mode 用於 CI / regression test，跑 fixture（fixture 是乾淨的）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# K-id 規格：K + ≥1 digit + optional alpha suffix（K1216b, K222c 也合法）
# 但 strict id field 我們只認 ^K\d+$（無 suffix），這是 2026-05-08 audit 採用的規格。
RE_KID_STRICT = re.compile(r"^K\d+$")
RE_KID_TITLE_PREFIX = re.compile(r"^K(\d+)(?:[a-z])?:")
RE_KID_IN_CONTENT = re.compile(r"\bK(\d+)(?:[a-z])?\b")
SIZE_WARN_BYTES = 5 * 1024 * 1024  # 5MB
SIZE_DANGER_BYTES = 30 * 1024 * 1024  # 30MB — 2026-04-10 bloat 達 54.5MB


def _kid_num(kid: str) -> str | None:
    """從 'K936' / 'K1216b' 取出 numeric part '936' / '1216'。"""
    m = re.match(r"^K(\d+)", kid)
    return m.group(1) if m else None


def check_id_title_consistency(entries: list[dict]) -> list[str]:
    """Test 1: 對每個 id matching ^K\\d+$ 的 entry，若 title **有** 'KNNN:' 前綴，
    必須與 id 對齊。

    註：歷史上有許多 legacy entries 用無前綴的描述性 title（"DCC-GARCH SPY-GLD..."）—
    這不是 corruption，只是早期 convention。本檢查只抓「title 確實有 KNNN: 前綴
    但編號與 id 不符」的硬 bug（即 2026-05-08 K936 incident pattern）。
    """
    failures: list[str] = []
    for idx, e in enumerate(entries):
        if not isinstance(e, dict):
            continue
        eid = e.get("id")
        if not isinstance(eid, str) or not RE_KID_STRICT.match(eid):
            continue
        title = e.get("title", "")
        if not isinstance(title, str) or not title:
            continue
        m = RE_KID_TITLE_PREFIX.match(title)
        if m is None:
            # 無 KNNN: 前綴 → legacy 描述性 title，不視為硬 bug（避免假警報）
            continue
        title_num = m.group(1)
        id_num = _kid_num(eid)
        if id_num != title_num:
            failures.append(
                f"  [entry #{idx}] id={eid!r} (numeric={id_num}) vs title 起頭 K{title_num}: 不一致 → {title[:80]!r}"
            )
    return failures


def check_content_id_alignment(entries: list[dict]) -> list[str]:
    """Test 2: 抓「id / title / content 三方矛盾」的硬 bug。

    K936 incident pattern: id="K936", title="K112: EMD-GARCH...", content="[..] K112: EMD-GARCH..."
    title 和 content 都自述 K112，只有 id 是 K936 — 強信號 dedup silent corruption。

    邊界 case：legitimate 跨 K 引用 (e.g. id=K861, title="K861: ...", content="[..] K44: prior...")
    title 與 id 一致 → 不視為 mismatch。

    判定條件（要全 true 才 flag）：
    1. id 是 KNNN 格式
    2. content 開頭 ~300 chars 含 'KMMM:' self-ref pattern (M ≠ N)
    3. **title 也是 'KMMM:' 前綴（同一個 M）** — 三方矛盾才 raise
       若 title 已對齊 id（K861: ...）但 content 提到 K44，那是 legitimate cross-ref
    """
    failures: list[str] = []
    for idx, e in enumerate(entries):
        if not isinstance(e, dict):
            continue
        eid = e.get("id")
        if not isinstance(eid, str) or not RE_KID_STRICT.match(eid):
            continue
        content = e.get("content", "")
        if not isinstance(content, str) or not content:
            continue

        head = content[:300]
        self_ref = re.search(r"\bK(\d+)(?:[a-z])?\s*:", head)
        if self_ref is None:
            continue
        ref_num = self_ref.group(1)
        id_num = _kid_num(eid)
        if id_num == ref_num:
            continue  # content self-ref 對齊 id

        # content 自述為 K{ref_num} 但 id 是 K{id_num}。檢查 title 是否同樣自述 K{ref_num}：
        # 是 → 三方矛盾（title+content 一致但 id 偏差）→ 強信號 corruption
        # 否 → 純 cross-ref（content 提到別的 K，但 id/title 內部一致）→ 不 flag
        title = e.get("title", "")
        if not isinstance(title, str):
            continue
        m_title = RE_KID_TITLE_PREFIX.match(title)
        if m_title is None:
            continue  # title 無前綴，無法判定為硬 bug
        title_num = m_title.group(1)
        if title_num == ref_num and title_num != id_num:
            # title 與 content 都指向 K{ref_num}，但 id 是 K{id_num} — K936 pattern
            failures.append(
                f"  [entry #{idx}] id={eid!r} (numeric={id_num}) 但 title+content 都自述為 K{ref_num} → "
                f"title={title[:60]!r} | content head={head[:80]!r}"
            )
    return failures


def check_experiment_id_consistency(entries: list[dict]) -> list[str]:
    """Test 3: 若 experiment_id 存在且符合 ^K\\d+$ 格式，驗證 id / title 都對齊。"""
    failures: list[str] = []
    for idx, e in enumerate(entries):
        if not isinstance(e, dict):
            continue
        exp_id = e.get("experiment_id")
        if not isinstance(exp_id, str) or not RE_KID_STRICT.match(exp_id):
            continue
        eid = e.get("id", "")
        title = e.get("title", "")
        exp_num = _kid_num(exp_id)
        # id check（若 id 也是 K\d+ 格式）
        if isinstance(eid, str) and RE_KID_STRICT.match(eid):
            id_num = _kid_num(eid)
            if id_num != exp_num:
                failures.append(
                    f"  [entry #{idx}] experiment_id={exp_id!r} 但 id={eid!r} 不一致"
                )
        # title check
        if isinstance(title, str) and title:
            m = RE_KID_TITLE_PREFIX.match(title)
            if m is not None and m.group(1) != exp_num:
                failures.append(
                    f"  [entry #{idx}] experiment_id={exp_id!r} (K{exp_num}) "
                    f"但 title 起頭為 K{m.group(1)}: → {title[:80]!r}"
                )
    return failures


def check_no_duplicate_ids(entries: list[dict]) -> list[str]:
    """Test 4: 不可有 ≥2 個「實質」duplicate id（jq dedup 應已收斂）。

    例外：legacy stub（`legacy: true` + 無 title/content）+ 同 id 完整 entry 是
    pre-existing baseline pattern（2026-04-10 dedup fix 後的殘留），不 flag。
    若同 id 有 ≥2 個非 stub 完整 entries → flag（dedup bug 仍在）。
    """

    def is_legacy_stub(e: dict) -> bool:
        if e.get("legacy") is not True:
            return False
        title = e.get("title")
        content = e.get("content")
        title_empty = not isinstance(title, str) or not title.strip()
        content_empty = not isinstance(content, str) or not content.strip()
        return title_empty and content_empty

    failures: list[str] = []
    seen: dict[str, list[int]] = {}
    for idx, e in enumerate(entries):
        if not isinstance(e, dict):
            continue
        eid = e.get("id")
        if not isinstance(eid, str):
            continue
        seen.setdefault(eid, []).append(idx)

    for eid, indices in seen.items():
        if len(indices) <= 1:
            continue
        # 過濾 legacy stub
        substantive = [i for i in indices if not is_legacy_stub(entries[i])]
        if len(substantive) > 1:
            failures.append(
                f"  duplicate id={eid!r} 出現於 entries {indices} "
                f"(substantive count={len(substantive)}, total={len(indices)})"
            )
    return failures


def check_file_size(path: Path) -> tuple[str, str | None]:
    """Test 5: file size sanity. 回傳 (level, message)；level ∈ {ok, warn, danger}。"""
    if not path.exists():
        return "ok", None
    size = path.stat().st_size
    mb = size / (1024 * 1024)
    if size >= SIZE_DANGER_BYTES:
        return "danger", (
            f"  knowledge.json size={mb:.1f}MB ≥ {SIZE_DANGER_BYTES // (1024*1024)}MB "
            f"DANGER threshold（2026-04-10 bloat 達 54.5MB / 50,304 entries 96.4% dup）"
            f"\n  立即跑 memory-health skill 檢查 dedup 健康。"
        )
    if size >= SIZE_WARN_BYTES:
        return "warn", (
            f"  knowledge.json size={mb:.1f}MB ≥ {SIZE_WARN_BYTES // (1024*1024)}MB warn threshold"
            f"\n  歷史教訓：2026-04-10 dedup bloat 從 1.4MB → 54.5MB；建議跑 memory-health。"
        )
    return "ok", None


def collect_failures(entries: list[dict]) -> dict[str, list[str]]:
    """跑 4 個 hard check，回傳 dict[test_name → failure messages]。"""
    return {
        "test1_id_title": check_id_title_consistency(entries),
        "test2_content_id": check_content_id_alignment(entries),
        "test3_experiment_id": check_experiment_id_consistency(entries),
        "test4_duplicate_id": check_no_duplicate_ids(entries),
    }


def run_all_checks(
    path: Path,
    *,
    strict_size: bool = False,
    baseline: dict[str, list[str]] | None = None,
    emit_baseline_path: Path | None = None,
) -> int:
    """執行 5 個 checks。回傳 exit code（0=PASS, 1=hard fail, 2=parse error）。

    Modes:
      - baseline=None (absolute): 任何 hard check failure → exit 1
      - baseline={...}: delta mode — 只 exit 1 若有新增 failure 不在 baseline
      - emit_baseline_path: 寫當前 failures 到 path，always exit 0
    """
    if not path.exists():
        print(f"[FATAL] file 不存在: {path}", file=sys.stderr)
        return 2
    try:
        with path.open() as f:
            data = json.load(f)
    except json.JSONDecodeError as ex:
        print(f"[FATAL] JSON parse error in {path}: {ex}", file=sys.stderr)
        return 2
    except OSError as ex:
        print(f"[FATAL] read error {path}: {ex}", file=sys.stderr)
        return 2

    if not isinstance(data, list):
        print(
            f"[FATAL] {path} 預期是 list of entries，實際 type={type(data).__name__}",
            file=sys.stderr,
        )
        return 2

    print(f"=== knowledge.json dedup integrity check ===")
    print(f"  file: {path}")
    print(f"  entries: {len(data)}")
    if baseline is not None:
        baseline_total = sum(len(v) for v in baseline.values())
        print(f"  mode: delta (baseline has {baseline_total} pre-existing failures)")
    elif emit_baseline_path is not None:
        print(f"  mode: emit-baseline → {emit_baseline_path}")
    else:
        print("  mode: absolute (any failure → exit 1)")

    failures = collect_failures(data)

    # Emit baseline mode: dump 並 exit 0
    if emit_baseline_path is not None:
        try:
            with emit_baseline_path.open("w") as f:
                json.dump(failures, f, ensure_ascii=False, indent=2)
        except OSError as ex:
            print(f"[FATAL] emit baseline write error: {ex}", file=sys.stderr)
            return 2
        total = sum(len(v) for v in failures.values())
        print(f"[OK] baseline 寫入 {emit_baseline_path}（{total} 筆 pre-existing failures）")
        return 0

    test_titles = {
        "test1_id_title": "Test 1: id-vs-title consistency",
        "test2_content_id": "Test 2: content-id alignment",
        "test3_experiment_id": "Test 3: experiment_id consistency",
        "test4_duplicate_id": "Test 4: no duplicate ids",
    }

    new_failures_total = 0
    absolute_failures_total = 0

    for key, title in test_titles.items():
        cur = failures[key]
        absolute_failures_total += len(cur)
        if baseline is not None:
            base = set(baseline.get(key, []))
            new = [line for line in cur if line not in base]
            if new:
                print(f"\n[FAIL] {title} — {len(new)} 新增 mismatch(es) (baseline 已有 {len(base)})")
                for line in new[:20]:
                    print(line)
                if len(new) > 20:
                    print(f"  ... 另 {len(new) - 20} 筆 (truncated)")
                new_failures_total += len(new)
            else:
                print(f"[PASS] {title} ({len(cur)} 筆全在 baseline，無新增)")
        else:
            if cur:
                print(f"\n[FAIL] {title} — {len(cur)} mismatch(es)")
                for line in cur[:20]:
                    print(line)
                if len(cur) > 20:
                    print(f"  ... 另 {len(cur) - 20} 筆 (truncated)")
            else:
                print(f"[PASS] {title}")

    # Test 5: size
    level, msg = check_file_size(path)
    if level == "danger":
        print(f"\n[DANGER] Test 5: file size")
        print(msg)
        if strict_size:
            absolute_failures_total += 1
            new_failures_total += 1
    elif level == "warn":
        print(f"\n[WARN] Test 5: file size")
        print(msg)
    else:
        print("[PASS] Test 5: file size sanity")

    print()
    if baseline is not None:
        if new_failures_total > 0:
            print(f"=== NEW FAILURES (delta mode): {new_failures_total} ===")
            print("Action: merge_worktree.sh 應 revert 到 pre-merge state；不可 commit。")
            return 1
        print(f"=== ALL CHECKS PASS (delta mode; absolute={absolute_failures_total}) ===")
        return 0
    if absolute_failures_total > 0:
        print(f"=== TOTAL FAILURES: {absolute_failures_total} ===")
        print("Action: merge_worktree.sh 應 revert 到 pre-merge state；不可 commit。")
        return 1
    print("=== ALL CHECKS PASS ===")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else "")
    parser.add_argument(
        "path",
        nargs="?",
        default=None,
        help="knowledge.json 路徑（預設 storage/memory/knowledge.json）",
    )
    parser.add_argument(
        "--strict-size",
        action="store_true",
        help="size DANGER 視為 hard fail（exit 1），預設只 warn",
    )
    parser.add_argument(
        "--baseline",
        default=None,
        help="與 baseline JSON 比對；只在 *新增* failure 時 exit 1",
    )
    parser.add_argument(
        "--emit-baseline",
        default=None,
        help="寫當前 failures 到指定 path，供後續 --baseline 使用（always exit 0）",
    )
    args = parser.parse_args()

    if args.path:
        target = Path(args.path)
    else:
        # 找 repo root（向上找 .git）
        here = Path(__file__).resolve()
        for parent in here.parents:
            if (parent / ".git").exists():
                target = parent / "storage" / "memory" / "knowledge.json"
                break
        else:
            print(
                "[FATAL] 找不到 repo root；請傳 path argument。", file=sys.stderr
            )
            return 2

    baseline_data: dict[str, list[str]] | None = None
    if args.baseline:
        bpath = Path(args.baseline)
        if not bpath.exists():
            print(f"[FATAL] baseline file 不存在: {bpath}", file=sys.stderr)
            return 2
        try:
            with bpath.open() as f:
                baseline_data = json.load(f)
        except (json.JSONDecodeError, OSError) as ex:
            print(f"[FATAL] baseline read/parse error: {ex}", file=sys.stderr)
            return 2

    emit_path = Path(args.emit_baseline) if args.emit_baseline else None

    return run_all_checks(
        target,
        strict_size=args.strict_size,
        baseline=baseline_data,
        emit_baseline_path=emit_path,
    )


if __name__ == "__main__":
    sys.exit(main())
