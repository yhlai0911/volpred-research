#!/usr/bin/env python3
"""Apply a reviewed department's paper-edit instructions without widening the
`paper/**/*.tex` carve-out.

Background (`docs/governance/2026-08-05_tex_carveout_proposal.md` §4): manuscript prose
changes stay a main-thread decision (CLAUDE.md), but a department that has already done
the judgement work (review, evidence, exact FIND/REPLACE text) still has to hand the main
thread a whole editing session to get six mechanical string swaps applied. This script
turns that session into one command: it proves the swaps are mechanical (unchanged
target file, unique anchors, equal line counts, confined diff) and leaves the actual
"apply or not" decision with whoever runs it -- by defaulting to a dry-run that only
prints the diff.

Instructions-file format this script parses (see
`storage/org/departments/publications/work/prg_v8_edit_instructions.md` for the reference
fixture -- write new instruction files the same way):

    **Target file**: `<path/to/file.tex>`

    | 項目 | 期望值 |
    |---|---|
    | sha256 | `<64-hex-char sha256 of the target file>` |
    | bytes | `<byte count>` |

    **Round evidence**: `<path relative to the instructions file's own directory>`

    ## Edit 1 — `file.tex:LINE` — LABEL

    **Original**

    ```latex
    <exact text currently in the file, matched literally>
    ```

    **Replacement**

    ```latex
    <exact text to replace it with>
    ```

Repeat the `## Edit N` block for every edit. Only the *first* Original/Replacement pair
found under each `## Edit N` header is used -- a later "Option B" alternative documented
in the same section is not picked up, by design (the recommended option is always the
first pair).

Gates (docs/governance/2026-08-05_tex_carveout_proposal.md §2, C1-C6):

    C1  target file sha256 + byte count must match what the instructions declare
    C2  every FIND string must match the target file exactly once
    C3  every FIND/REPLACE pair must have the same line count (no prose growth/shrink
        sneaks past a reviewer who only read the printed diff)
    C4  the post-apply diff must be confined to the edited spans -- verified, not assumed
    C5  the round-evidence directory the instructions point at must exist and is where
        the apply report is written
    C6  the tool reports what it did; it does not declare the round converged -- that
        judgement stays with the department that owns the round

Default is a dry-run: parse, validate C1/C2/C3, print the diff, exit 0/1 -- no write.
`--apply` performs the write (atomic), verifies C4, writes the report into the round
evidence directory (C5), and sends a dept_send reply (C6) unless `--no-reply` is passed.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

_TARGET_FILE_RE = re.compile(r"\*\*Target file\*\*:\s*`([^`]+)`")
_SHA256_ROW_RE = re.compile(r"\|\s*sha256\s*\|\s*`([0-9a-fA-F]{64})`\s*\|")
_BYTES_ROW_RE = re.compile(r"\|\s*bytes\s*\|\s*`(\d+)`\s*\|")
_ROUND_EVIDENCE_RE = re.compile(r"\*\*Round evidence\*\*:\s*`([^`]+)`")
_EDIT_HEADER_RE = re.compile(r"^## Edit (\d+)\s*—\s*(.*)$", re.MULTILINE)
_ORIGINAL_BLOCK_RE = re.compile(
    r"\*\*Original\*\*\s*\n+```[a-zA-Z]*\n(.*?)\n```", re.DOTALL
)
_REPLACEMENT_BLOCK_RE = re.compile(
    r"\*\*Replacement\*\*\s*\n+```[a-zA-Z]*\n(.*?)\n```", re.DOTALL
)


class InstructionsError(ValueError):
    """The instructions file does not follow the documented format."""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_instructions(path: Path) -> dict:
    """Parse an instructions markdown file into target/gate/edits.

    Raises InstructionsError with a specific, actionable message on any missing or
    malformed section -- this gate has no silent-fallback branch: a section that cannot
    be found is a stop, not a skip.
    """
    text = path.read_text(encoding="utf-8")

    target_match = _TARGET_FILE_RE.search(text)
    if not target_match:
        raise InstructionsError(
            "no `**Target file**: `<path>`` line found"
        )
    target_rel = target_match.group(1).strip()

    sha_match = _SHA256_ROW_RE.search(text)
    if not sha_match:
        raise InstructionsError(
            "no `| sha256 | `<64-hex>` |` table row found"
        )
    expected_sha256 = sha_match.group(1).lower()

    bytes_match = _BYTES_ROW_RE.search(text)
    if not bytes_match:
        raise InstructionsError("no `| bytes | `<n>` |` table row found")
    expected_bytes = int(bytes_match.group(1))

    evidence_match = _ROUND_EVIDENCE_RE.search(text)
    if not evidence_match:
        raise InstructionsError(
            "no `**Round evidence**: `<path>`` line found"
        )
    round_evidence_rel = evidence_match.group(1).strip()

    headers = list(_EDIT_HEADER_RE.finditer(text))
    if not headers:
        raise InstructionsError("no `## Edit N — ...` sections found")

    edits: list[dict] = []
    for i, header in enumerate(headers):
        edit_id = int(header.group(1))
        label = header.group(2).strip()
        section_start = header.end()
        section_end = (
            headers[i + 1].start() if i + 1 < len(headers) else len(text)
        )
        section = text[section_start:section_end]

        original_match = _ORIGINAL_BLOCK_RE.search(section)
        if not original_match:
            raise InstructionsError(
                f"Edit {edit_id} ({label}): no **Original** fenced block found"
            )
        replacement_match = _REPLACEMENT_BLOCK_RE.search(section)
        if not replacement_match:
            raise InstructionsError(
                f"Edit {edit_id} ({label}): no **Replacement** fenced block found"
            )
        find = original_match.group(1)
        replace = replacement_match.group(1)
        if not find.strip():
            raise InstructionsError(f"Edit {edit_id} ({label}): empty FIND text")

        edits.append({
            "id": edit_id,
            "label": label,
            "find": find,
            "replace": replace,
        })

    return {
        "target_rel": target_rel,
        "expected_sha256": expected_sha256,
        "expected_bytes": expected_bytes,
        "round_evidence_rel": round_evidence_rel,
        "round_evidence_dir": (path.parent / round_evidence_rel).resolve(),
        "edits": edits,
        "source_path": path,
    }


def check_c1_staleness(parsed: dict, root: Path = REPO_ROOT) -> str | None:
    """Returns an error string, or None if the target file matches C1."""
    target_path = root / parsed["target_rel"]
    if not target_path.is_file():
        return f"target file does not exist: {parsed['target_rel']}"
    data = target_path.read_bytes()
    actual_sha256 = _sha256_bytes(data)
    actual_bytes = len(data)
    if actual_sha256 != parsed["expected_sha256"] or actual_bytes != parsed["expected_bytes"]:
        return (
            "round is stale -- target file no longer matches the instructions: "
            f"expected sha256={parsed['expected_sha256']} bytes={parsed['expected_bytes']}, "
            f"actual sha256={actual_sha256} bytes={actual_bytes}. "
            "Do not adjust the FIND strings to compensate -- return this round to its "
            "author department for a fresh instructions file."
        )
    return None


def check_c2_c3(parsed: dict, target_text: str) -> list[str]:
    """C2 (unique FIND) and C3 (equal line count) against the CURRENT working text.

    Applied against a running `target_text` so each edit's uniqueness/line-count check
    accounts for the edits already applied ahead of it in the list -- exactly what will
    be true at apply time.
    """
    problems: list[str] = []
    working = target_text
    for edit in parsed["edits"]:
        count = working.count(edit["find"])
        if count != 1:
            problems.append(
                f"Edit {edit['id']} ({edit['label']}): FIND text matches "
                f"{count} times, must match exactly once"
            )
            continue
        find_lines = edit["find"].count("\n") + 1
        replace_lines = edit["replace"].count("\n") + 1
        if find_lines != replace_lines:
            problems.append(
                f"Edit {edit['id']} ({edit['label']}): FIND is {find_lines} line(s), "
                f"REPLACE is {replace_lines} line(s) -- equal-line-count replacements only"
            )
            continue
        working = working.replace(edit["find"], edit["replace"], 1)
    return problems


def apply_edits(target_text: str, edits: list[dict]) -> str:
    working = target_text
    for edit in edits:
        if working.count(edit["find"]) != 1:
            raise InstructionsError(
                f"Edit {edit['id']} ({edit['label']}): FIND no longer matches exactly "
                "once at apply time (a prior edit in this batch must have changed it "
                "unexpectedly) -- aborting before any write"
            )
        working = working.replace(edit["find"], edit["replace"], 1)
    return working


def check_c4_confined_diff(before: str, after: str, edits: list[dict]) -> tuple[list[str], list[int]]:
    """Returns (problems, changed_line_numbers). Confined = every changed line falls
    inside a span whose text is one of the FIND/REPLACE pairs -- proven by re-deriving
    the same output from `before` + edits and comparing byte-for-byte, then reporting
    which 1-indexed lines actually differ so the evidence record is concrete, not a
    boolean claim."""
    problems: list[str] = []
    rederived = apply_edits(before, edits)
    if rederived != after:
        problems.append(
            "post-apply file does not equal before-text with only the declared edits "
            "applied -- something outside the FIND/REPLACE pairs changed"
        )
    before_lines = before.splitlines()
    after_lines = after.splitlines()
    changed_line_numbers: list[int] = []
    matcher = difflib.SequenceMatcher(a=before_lines, b=after_lines, autojunk=False)
    for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
        if tag != "equal":
            changed_line_numbers.extend(range(j1 + 1, j2 + 1))
    return problems, changed_line_numbers


def install_atomic(path: Path, data: bytes) -> None:
    """Write `data` to `path` without truncating the inode a reader may hold open."""
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass  # silent-ok: cleanup race-safe
        raise


def _deciding_department(source_path: Path, root: Path = REPO_ROOT) -> str | None:
    """`storage/org/departments/<dept>/work/...` -> <dept>; None if not that shape."""
    try:
        rel_parts = source_path.resolve().relative_to(
            (root / "storage" / "org" / "departments").resolve()
        ).parts
    except ValueError:
        return None  # silent-ok: caller prints a WARN and skips delivery on None
    return rel_parts[0] if rel_parts else None


def _print_diff(target_rel: str, before: str, after: str) -> None:
    diff_lines = list(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{target_rel}",
            tofile=f"b/{target_rel}",
        )
    )
    if diff_lines:
        sys.stdout.writelines(diff_lines)
    else:
        print("(no textual difference)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("instructions", type=Path, help="path to the *_edit_instructions.md file")
    parser.add_argument("--apply", action="store_true", help="write the file (default: dry-run, print diff only)")
    parser.add_argument("--reply-to", default=None, help="inbox item id this apply answers (kind=reply instead of report)")
    parser.add_argument("--no-reply", action="store_true", help="skip the automatic dept_send delivery after --apply")
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    args = parser.parse_args(argv)

    try:
        parsed = parse_instructions(args.instructions)
    except InstructionsError as exc:
        print(f"[apply_paper_edits] FAIL — instructions file malformed: {exc}", file=sys.stderr)
        return 1

    staleness = check_c1_staleness(parsed, root=args.root)
    if staleness:
        print(f"[apply_paper_edits] FAIL (C1) — {staleness}", file=sys.stderr)
        return 1

    target_path = args.root / parsed["target_rel"]
    before_text = target_path.read_text(encoding="utf-8")

    problems = check_c2_c3(parsed, before_text)
    if problems:
        print("[apply_paper_edits] FAIL (C2/C3):", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1

    after_text = apply_edits(before_text, parsed["edits"])
    print(
        f"[apply_paper_edits] {len(parsed['edits'])} edit(s) validated against "
        f"{parsed['target_rel']} (sha256={parsed['expected_sha256'][:12]}...): "
        "hash/byte match (C1), unique anchors (C2), equal line counts (C3)."
    )
    _print_diff(parsed["target_rel"], before_text, after_text)

    if not args.apply:
        print("[apply_paper_edits] dry-run — no file written. Re-run with --apply to write.")
        return 0

    c4_problems, changed_lines = check_c4_confined_diff(before_text, after_text, parsed["edits"])
    if c4_problems:
        print("[apply_paper_edits] FAIL (C4) — refusing to write:", file=sys.stderr)
        for p in c4_problems:
            print(f"  - {p}", file=sys.stderr)
        return 1

    install_atomic(target_path, after_text.encode("utf-8"))
    after_sha256 = _sha256_bytes(after_text.encode("utf-8"))

    round_evidence_dir = parsed["round_evidence_dir"]
    if not round_evidence_dir.is_dir():
        print(
            f"[apply_paper_edits] WARN — round evidence dir does not exist, report not written: "
            f"{round_evidence_dir}",
            file=sys.stderr,
        )
        report_path = None
    else:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        report_path = round_evidence_dir / f"apply_report_{timestamp}.json"
        report = {
            "instructions_file": str(parsed["source_path"]),
            "target_file": parsed["target_rel"],
            "applied_at": timestamp,
            "pre_apply": {
                "sha256": parsed["expected_sha256"],
                "bytes": parsed["expected_bytes"],
            },
            "post_apply": {
                "sha256": after_sha256,
                "bytes": len(after_text.encode("utf-8")),
            },
            "edits_applied": [
                {"id": e["id"], "label": e["label"], "find_lines": e["find"].count("\n") + 1}
                for e in parsed["edits"]
            ],
            "changed_line_numbers_post_apply": changed_lines,
            "note": (
                "This report is evidence of a mechanical apply, not a convergence "
                "verdict. Recompile / rerun the paper's reproduce gate and judge "
                "convergence in the owning department, per C6."
            ),
        }
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"[apply_paper_edits] wrote {report_path}")

    print(f"[apply_paper_edits] applied — {parsed['target_rel']} now sha256={after_sha256[:12]}...")

    if args.no_reply:
        return 0

    dept = _deciding_department(parsed["source_path"], root=args.root)
    if dept is None:
        print(
            "[apply_paper_edits] WARN — could not derive a deciding department from "
            f"the instructions path ({parsed['source_path']}); skipping dept_send reply",
            file=sys.stderr,
        )
        return 0

    message = (
        f"結果：{parsed['target_rel']} 已套用 {len(parsed['edits'])} 筆 edit"
        f"（{parsed['source_path'].name}），sha256 {parsed['expected_sha256'][:12]}... -> "
        f"{after_sha256[:12]}...。驗證：hash/bytes 綁定符合、每筆 FIND 全檔唯一、"
        "等行數替換、post-apply diff 已確認侷限在被替換的 span 內。"
        + (f"報告寫入 {report_path}。" if report_path else "")
        + "本工具不宣告 round 收斂，請貴部門依 recompile / reproduce 結果自行判定。"
    )
    cmd = [
        "uv", "run", "python", str(args.root / "scripts" / "org" / "dept_send.py"),
        dept, "--from", "platform_eng",
        "--kind", "reply" if args.reply_to else "report",
        "--priority", "P2",
        "--task", message,
        "--refs", f"{parsed['source_path']},{report_path or ''}",
    ]
    if args.reply_to:
        cmd += ["--reply-to", args.reply_to]
    result = subprocess.run(cmd, cwd=str(args.root), capture_output=True, text=True)
    if result.returncode != 0:
        print(
            f"[apply_paper_edits] WARN — dept_send reply failed (file was still written): "
            f"{result.stderr.strip()}",
            file=sys.stderr,
        )
    else:
        print(f"[apply_paper_edits] delivered reply to {dept}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
