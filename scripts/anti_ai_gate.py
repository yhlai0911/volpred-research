#!/usr/bin/env python3
"""Anti-AI-style hard gate — runs editor-sop checklist programmatically.

Per publishing.md rule #7: 「所有讀者向文章都必跑 anti-ai-style，這是
publish gate 不是可選優化」. This script makes it enforceable not just
self-discipline.

Usage:
  uv run python scripts/anti_ai_gate.py --text "<draft>"
  uv run python scripts/anti_ai_gate.py --file /tmp/draft.md
  echo "draft" | uv run python scripts/anti_ai_gate.py --stdin

Exit codes:
  0 = PASS (no AI-style landmines found)
  1 = FAIL (failures listed; do not publish)
  2 = usage error
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Callable

# ─── Checklist patterns (from editor-sop.md grep-able subset) ──────────────

CHECKS: list[tuple[str, str, re.Pattern, Callable[[list[str]], str] | None]] = [
    (
        "1.1 不是...而是 套路對比",
        "MUST",
        re.compile(r"不是.{0,15}而是|不只是.{0,15}而是|並非.{0,15}而是"),
        None,
    ),
    (
        "1.3 無 source claim 語",
        "WARN",
        re.compile(r"有人說|不少人認為|坊間流傳|常聽到|數據顯示|研究指出|專家分析|許多投資人"),
        None,
    ),
    (
        "2.2 套話形容詞 (深入/深刻/關鍵/值得關注 等)",
        "WARN",
        re.compile(r"深入(分析|解析|探討)|深刻(意義|啟示)|至關重要|不容忽視|值得關注|綜上所述|總而言之|簡而言之"),
        None,
    ),
    (
        "2.3 英文翻譯腔 (被動 / of / when 直譯)",
        "WARN",
        re.compile(r"被(認為|視為|證明|發現)為|的事實|當.{0,20}時，這.{0,10}意味"),
        None,
    ),
    (
        "3.0 套路 hook (朋友問我 / 根據資料)",
        "MUST",
        re.compile(r"朋友(問|問起|提到)|有人問我|常被問|根據(數據|資料)顯示|讓我們|首先.{0,5}讓我|今天市場"),
        None,
    ),
    (
        "3.3 結尾 aphorism (注意力放別處 / 值得我們深思 等)",
        "WARN",
        re.compile(r"值得我們?深思|啟示我們|引人深思|不容小覷|留待時間|未來.{0,15}拭目以待"),
        None,
    ),
    (
        "AI typical bridge phrases (其實.*也合理 / 結論.*反直覺)",
        "WARN",
        re.compile(r"其實也(合理|不奇怪)|結論.{0,8}反直覺|讓人意外|更值得思考的是"),
        None,
    ),
]


def long_paragraph_check(text: str) -> tuple[bool, str]:
    """Check 3.2 short-paragraph rule (FB tone)."""
    paragraphs = [p for p in text.split("\n\n") if p.strip()]
    long_paras = [p for p in paragraphs if p.count("\n") + 1 > 4 or len(p) > 200]
    if long_paras:
        return False, f"{len(long_paras)} 段超過 4 行 / 200 字（FB tone 要短段）"
    return True, "段落長度 OK"


def list_structure_check(text: str) -> tuple[bool, str]:
    """Check 3.4 — FB shouldn't use numbered/bulleted lists heavily."""
    list_lines = re.findall(r"^\s*(?:[一二三四五六七八九十]、|\d+\.|\*\s|-\s|•\s)", text, re.M)
    if len(list_lines) >= 3:
        return False, f"{len(list_lines)} 行列表結構（FB 不是 newsletter, 列表項目 ≥3 視為過硬）"
    return True, "列表結構 OK"


def run_checks(text: str, *, fb_mode: bool = True) -> tuple[bool, list[str]]:
    failures: list[str] = []
    must_fail = False

    for name, level, pat, _ in CHECKS:
        hits = pat.findall(text)
        if hits:
            line = f"  [{level}] {name}: hit {len(hits)} 次 — 範例 {hits[0]!r}"
            failures.append(line)
            if level == "MUST":
                must_fail = True

    if fb_mode:
        ok, msg = long_paragraph_check(text)
        if not ok:
            failures.append(f"  [WARN] 3.2 段落長度: {msg}")
        ok, msg = list_structure_check(text)
        if not ok:
            failures.append(f"  [WARN] 3.4 列表結構: {msg}")

    # GATE: MUST always blocks; ≥3 WARN also blocks (cumulative AI-flavor)
    warn_count = sum(1 for f in failures if "[WARN]" in f)
    blocked = must_fail or warn_count >= 3
    return (not blocked), failures


def main() -> int:
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--text")
    src.add_argument("--file")
    src.add_argument("--stdin", action="store_true")
    ap.add_argument("--no-fb-mode", action="store_true", help="Disable FB-specific short-paragraph/list checks")
    args = ap.parse_args()

    if args.text:
        text = args.text
    elif args.file:
        text = Path(args.file).read_text(encoding="utf-8")
    else:
        text = sys.stdin.read()

    if not text.strip():
        print("EMPTY input", file=sys.stderr)
        return 2

    passed, failures = run_checks(text, fb_mode=not args.no_fb_mode)

    if passed:
        print(f"PASS — no AI-style landmines (warn={sum(1 for f in failures if '[WARN]' in f)}/3 ok)")
        if failures:
            print("\nMinor warnings (not blocking):")
            for f in failures:
                print(f)
        return 0
    else:
        print("FAIL — anti-AI-style gate blocked publish:")
        for f in failures:
            print(f)
        print("\nFix per .claude/skills/anti-ai-style/references/editor-sop.md")
        return 1


if __name__ == "__main__":
    sys.exit(main())
