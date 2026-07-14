#!/usr/bin/env python3
"""Audit: figure-producing scripts that draw CJK text without a CJK font.

matplotlib's default font (DejaVu Sans) has no CJK glyphs, so any Chinese label
renders as tofu boxes (□□□). The figure still saves, uploads, and embeds in a
published article — the failure is *only* visible to a human looking at the PNG.
That is why this keeps recurring:

  2026-06-11  k202 / mile_872abdc3   → fix was `scripts/plot_style.py`
  2026-07-13  CPI T-2 / mile_9560b9cc → same tofu, went live, caught by eye

The 2026-06-11 fix shipped a helper but no enforcement, so the next script that
forgot to call it reproduced the bug. This audit is the enforcement owner.

A script is a VIOLATION when all three hold:
  1. it draws with matplotlib (imports pyplot / matplotlib)
  2. it puts CJK characters in a string literal (titles, labels, legends)
  3. it never establishes a CJK font chain — neither `apply_cjk_style()` from
     scripts/plot_style.py, nor an explicit rcParams font list naming a CJK face

Usage:
    uv run python scripts/audit_cjk_chart_fonts.py                # human report
    uv run python scripts/audit_cjk_chart_fonts.py --json
    uv run python scripts/audit_cjk_chart_fonts.py --strict \
        --baseline storage/qa/cjk_chart_font_baseline.json        # CI ratchet
    uv run python scripts/audit_cjk_chart_fonts.py --write-baseline

--strict exits 1 when a violation appears outside the frozen baseline. The
baseline may only shrink: fix a script, drop it from the baseline. It must never
grow.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = REPO_ROOT / "storage" / "qa" / "cjk_chart_font_baseline.json"

SCAN_DIRS = ("experiments", "scripts", "src", "storage/event_articles")
SKIP_PARTS = {"_legacy", ".venv", "node_modules", "__pycache__", "archived"}

CJK_RE = re.compile(r"[一-鿿぀-ヿ]")

# Font faces that actually carry CJK glyphs. Naming any one of these in an
# rcParams font list counts as establishing the chain by hand.
CJK_FACES = (
    "PingFang", "Heiti", "STHeiti", "Songti", "Arial Unicode",
    "Noto Sans CJK", "Microsoft JhengHei", "SimHei", "Hiragino",
)

MPL_MARKERS = ("matplotlib", "pyplot")
STYLE_HELPERS = ("apply_cjk_style", "apply_article_style", "setup_cjk")

# Calls whose text argument is rendered into the figure (→ tofu without a font).
TEXT_CALLS = {
    "title", "suptitle", "set_title", "xlabel", "ylabel", "set_xlabel",
    "set_ylabel", "legend", "text", "annotate", "set_xticklabels",
    "set_yticklabels", "figtext", "set_label", "bar_label",
}


def _iter_python_files() -> list[Path]:
    out: list[Path] = []
    for d in SCAN_DIRS:
        root = REPO_ROOT / d
        if not root.is_dir():
            continue
        for p in root.rglob("*.py"):
            if SKIP_PARTS & set(p.parts):
                continue
            out.append(p)
    return sorted(out)


def _draws_cjk_text(tree: ast.AST) -> bool:
    """True when CJK text is passed to a call that renders it into the figure.

    Deliberately narrower than "file contains a CJK string": a Chinese docstring
    or a Chinese log message is not a rendering defect, and counting those would
    bury the real violations in noise (they inflated the first pass 244 → mostly
    false positives). Only text that reaches a drawing call becomes tofu.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
        if name not in TEXT_CALLS:
            continue
        args = list(node.args) + [kw.value for kw in node.keywords]
        for a in ast.walk(ast.Module(body=[ast.Expr(value=x) for x in args], type_ignores=[])):
            if isinstance(a, ast.Constant) and isinstance(a.value, str) and CJK_RE.search(a.value):
                return True
    return False


def _establishes_cjk_font(source: str) -> bool:
    # Merely importing a helper is not enough: the rcParams only change when
    # the helper is actually called. Requiring an AST Call prevents an
    # import-only script from silently passing this gate.
    try:
        tree = ast.parse(source)
    except SyntaxError:
        tree = None
    if tree is not None:
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            if name in STYLE_HELPERS:
                return True
    # Explicit rcParams font chain naming a real CJK face, e.g.
    #   plt.rcParams["font.sans-serif"] = ["PingFang HK", ...]
    for line in source.splitlines():
        if "font.sans-serif" in line or "font.family" in line:
            if any(face in line for face in CJK_FACES):
                return True
    # Multi-line font lists: look for a CJK face near any font rcParam mention.
    if ("font.sans-serif" in source or "font.family" in source) and any(
        face in source for face in CJK_FACES
    ):
        return True
    return False


def check_file(path: Path) -> dict | None:
    """Verdict for one script: a violation dict, or None if clean/irrelevant.

    Split out of `scan()` so the publish path can ask the same question about a
    single experiment's figure script. The CI ratchet only fires on push — which
    is *after* the article is live, so it caught k1703's tofu charts only once
    readers could already see them (2026-07-14). The publish gate needs a per-file
    verdict, and it has to be this same verdict, not a second opinion.
    """
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        print(f"[WARN] 讀檔失敗 path={path} err={e}", file=sys.stderr)
        return None
    if not any(m in source for m in MPL_MARKERS):
        return None
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        print(f"[WARN] AST parse 失敗 path={path} err={e}", file=sys.stderr)
        return None
    if not _draws_cjk_text(tree):
        return None
    if _establishes_cjk_font(source):
        return None
    try:
        rel = str(path.relative_to(REPO_ROOT))
    except ValueError:
        rel = str(path)
    return {
        "path": rel,
        "reason": "matplotlib + CJK 字串，但未建立 CJK 字型鏈（會渲染成豆腐字）",
    }


def scan() -> list[dict]:
    violations: list[dict] = []
    for path in _iter_python_files():
        verdict = check_file(path)
        if verdict is not None:
            violations.append(verdict)
    return violations


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true", help="超出 baseline 即 exit 1")
    ap.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    ap.add_argument("--write-baseline", action="store_true", help="凍結當前違規為 baseline")
    args = ap.parse_args()

    violations = scan()
    paths = sorted(v["path"] for v in violations)

    if args.write_baseline:
        args.baseline.parent.mkdir(parents=True, exist_ok=True)
        args.baseline.write_text(
            json.dumps({"note": "只准變少；修好一個就從這裡移除", "violations": paths},
                       ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"[OK] baseline 已寫入 {args.baseline}（{len(paths)} 個）")
        return 0

    if args.json:
        print(json.dumps({"count": len(paths), "violations": violations},
                         ensure_ascii=False, indent=2))
    else:
        print(f"CJK chart font audit — {len(paths)} 個違規腳本")
        for p in paths:
            print(f"  ✗ {p}")
        if not paths:
            print("  （無）")

    if not args.strict:
        return 0

    if not args.baseline.is_file():
        print(f"[FAIL] --strict 需要 baseline，但 {args.baseline} 不存在", file=sys.stderr)
        return 1
    frozen = set(json.loads(args.baseline.read_text(encoding="utf-8"))["violations"])
    new = sorted(set(paths) - frozen)
    fixed = sorted(frozen - set(paths))
    if fixed:
        print(f"[INFO] 已修好 {len(fixed)} 個（可從 baseline 移除）: {', '.join(fixed[:5])}")
    if new:
        print(f"\n[FAIL] {len(new)} 個新的豆腐字風險腳本（baseline 只准變少）:", file=sys.stderr)
        for p in new:
            print(f"  ✗ {p}", file=sys.stderr)
        print("\n修法：在 savefig 前呼叫 scripts/plot_style.py 的 apply_cjk_style()", file=sys.stderr)
        return 1
    print(f"[OK] 無新增違規（baseline={len(frozen)}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
