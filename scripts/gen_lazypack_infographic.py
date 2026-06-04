#!/usr/bin/env python3
"""Generate a 懶人包 (cheat-sheet) infographic for an article via NotebookLM.

WHY (2026-06-04): every general-reader (audience='general') article must carry a
designed explainer infographic at the end, summarising its main result / method /
key concept. NotebookLM's `generate infographic` produces a .png for FREE (drives
the user's NotebookLM web product via notebooklm-py — no per-call API billing),
which satisfies the boss's hard "不要花錢" constraint. This wraps the validated
end-to-end flow (create notebook → add source → generate → download) into one
command so the lazypack-infographic skill / publish pipeline can call it.

Free-cost only: uses notebooklm-py (NotebookLM web). NEVER calls a paid image API
(gpt-image-2 / paid Gemini key).

Usage:
    # From a feed.json article id:
    uv run python scripts/gen_lazypack_infographic.py \
        --article-id mile_31b2b0bb --prompt "<good prompt>" --out /tmp/x.png

    # From a markdown/text file:
    uv run python scripts/gen_lazypack_infographic.py \
        --source-file /tmp/article.md --title "K1413 懶人包" \
        --prompt "<good prompt>" --out /tmp/x.png

Options mirror notebooklm: --style --orientation --detail. Language is locked to
zh_Hant (Traditional Chinese). Pass --keep-notebook to skip cleanup.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NB_BIN = str(Path.home() / ".local" / "bin" / "notebooklm")
FEED = ROOT / "storage" / "reports" / "feed.json"

VALID_STYLES = {
    "auto", "sketch-note", "professional", "bento-grid", "editorial",
    "instructional", "bricks", "clay", "anime", "kawaii", "scientific",
}
VALID_ORIENT = {"landscape", "portrait", "square"}
VALID_DETAIL = {"concise", "standard", "detailed"}


def _run(args: list[str], parse_json: bool = False):
    """Run notebooklm CLI; return (ok, parsed_or_text)."""
    proc = subprocess.run(args, capture_output=True, text=True, timeout=900)
    out = (proc.stdout or "") + (proc.stderr or "")
    if parse_json:
        # CLI prints a "Matched: ..." preamble before the JSON block; find the
        # first '{' and parse from there.
        idx = out.find("{")
        if idx != -1:
            try:
                return proc.returncode == 0, json.loads(out[idx:])
            except json.JSONDecodeError:
                pass
        return proc.returncode == 0, {"_raw": out}
    return proc.returncode == 0, out


def _article_content(article_id: str) -> str | None:
    if not FEED.exists():
        return None
    feed = json.loads(FEED.read_text(encoding="utf-8"))
    for item in feed:
        if isinstance(item, dict) and item.get("id") == article_id:
            return item.get("content") or item.get("description")
    return None


def _extract_nb_id(res) -> str | None:
    if not isinstance(res, dict):
        return None
    nb = res.get("notebook")
    if isinstance(nb, dict) and nb.get("id"):
        return nb["id"]
    data = res.get("data")
    if isinstance(data, dict) and data.get("id"):
        return data["id"]
    return res.get("id")


def generate_panels(
    *, source_file: Path, title: str, panels: list[dict], out_dir: Path,
    keep_notebook: bool,
) -> list[Path]:
    """Generate MULTIPLE infographics (poster-session style) from one notebook.

    panels: [{name, prompt, style?, orientation?, detail?}]. The source is added
    ONCE; each panel is a separate `generate infographic` call (different focused
    prompt/style) so each image covers ONE info type — concept, method, results —
    instead of cramming everything onto one image.

    Returns the list of successfully written PNG paths (download artifact = the
    most recent generation, so panels are produced & downloaded one at a time).
    """
    ok, res = _run([NB_BIN, "create", title, "--json"], parse_json=True)
    nb_id = _extract_nb_id(res)
    if not nb_id:
        print(f"ERROR: could not create notebook: {res}", file=sys.stderr)
        return []
    print(f"notebook: {nb_id}")
    written: list[Path] = []
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        ok, res = _run(
            [NB_BIN, "source", "add", str(source_file), "-n", nb_id,
             "--title", title, "--json"],
            parse_json=True,
        )
        if not ok:
            print(f"ERROR: source add failed: {res}", file=sys.stderr)
            return []

        for i, panel in enumerate(panels, 1):
            name = panel.get("name") or f"panel{i}"
            prompt = panel["prompt"]
            style = panel.get("style", "professional")
            orientation = panel.get("orientation", "landscape")
            detail = panel.get("detail", "standard")
            print(f"--- panel {i}/{len(panels)}: {name} ({style}) ---")
            ok, res = _run(
                [NB_BIN, "generate", "infographic", prompt, "-n", nb_id,
                 "--orientation", orientation, "--detail", detail,
                 "--style", style, "--language", "zh_Hant",
                 "--wait", "--retry", "3", "--json"],
                parse_json=True,
            )
            status = res.get("status") if isinstance(res, dict) else None
            if not ok or (isinstance(res, dict) and res.get("error")) or status not in ("completed", None):
                print(f"  WARN: panel {name} generation failed: {res}", file=sys.stderr)
                continue
            # download the just-generated artifact (latest)
            out = out_dir / f"{name}.png"
            ok, dres = _run([NB_BIN, "download", "infographic", str(out), "-n", nb_id])
            if ok and out.exists():
                print(f"  OK: {name} -> {out} ({out.stat().st_size} bytes)")
                written.append(out)
            else:
                print(f"  WARN: download {name} failed: {dres}", file=sys.stderr)
        return written
    finally:
        if not keep_notebook and nb_id:
            _run([NB_BIN, "delete", "-n", nb_id, "--yes"])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--article-id", help="feed.json article id (mile_...)")
    src.add_argument("--source-file", help="path to a .md/.txt article file")
    ap.add_argument("--title", default="懶人包")
    ap.add_argument("--prompt", required=True, help="GOOD infographic prompt (see skill)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--style", default="professional", choices=sorted(VALID_STYLES))
    ap.add_argument("--orientation", default="landscape", choices=sorted(VALID_ORIENT))
    ap.add_argument("--detail", default="standard", choices=sorted(VALID_DETAIL))
    ap.add_argument("--keep-notebook", action="store_true")
    a = ap.parse_args()

    if a.article_id:
        content = _article_content(a.article_id)
        if not content:
            print(f"ERROR: article {a.article_id} not found in feed.json", file=sys.stderr)
            return 1
        tmp = Path(tempfile.mkstemp(suffix=".md")[1])
        tmp.write_text(content, encoding="utf-8")
        source_file = tmp
        title = a.title if a.title != "懶人包" else f"{a.article_id} 懶人包"
    else:
        source_file = Path(a.source_file)
        if not source_file.exists():
            print(f"ERROR: source file not found: {source_file}", file=sys.stderr)
            return 1
        title = a.title

    ok = generate(
        source_file=source_file, title=title, prompt=a.prompt, out=Path(a.out),
        style=a.style, orientation=a.orientation, detail=a.detail,
        keep_notebook=a.keep_notebook,
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
