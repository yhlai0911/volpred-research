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
# Cartoon / cute / hand-drawn styles look unprofessional for finance content
# (user 2026-06-04: "不要做得太卡通顯得很不專業"; mile_71dd116b 卡通小人踩過坑).
PRO_STYLES = {"professional", "bento-grid", "editorial", "scientific"}
CARTOON_STYLES = {"sketch-note", "instructional", "kawaii", "anime", "clay", "bricks"}
VALID_ORIENT = {"landscape", "portrait", "square"}
VALID_DETAIL = {"concise", "standard", "detailed"}

# Appended to EVERY infographic prompt as a belt-and-suspenders professional
# guard, even if a caller forgets (style alone is not enough — the model still
# inserts cartoon mascots unless the prompt forbids them).
_NO_CARTOON = (
    "風格務必專業、簡潔、資料導向；嚴禁卡通人物、可愛插畫、手繪塗鴉、emoji 表情人物；"
    "用乾淨的圖表、圖示與數字，呈現像專業財經研究報告的質感。"
)


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
    *, source_files: list[Path], title: str, panels: list[dict], out_dir: Path,
    keep_notebook: bool,
) -> list[Path]:
    """Generate MULTIPLE infographics (poster-session style) from one notebook.

    source_files: the FULL evidence package the article was written from —
    experiment <k>_results.json + README.md + draft/article + references — NOT
    just the finished article prose. Feeding the source data (not the lossy
    article text) lets the method/results panels be accurate (boss directive
    2026-06-04). All sources are added to one notebook.

    panels: [{name, prompt, style?, orientation?, detail?}]. Each panel is a
    separate `generate infographic` call (different focused prompt/style) so each
    image covers ONE info type — concept, method, results — instead of cramming
    everything onto one image (poster-session feel).

    Returns the list of successfully written PNG paths.
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
        added = 0
        for sf in source_files:
            if not sf.exists():
                print(f"  WARN: source not found, skipping: {sf}", file=sys.stderr)
                continue
            ok, res = _run(
                [NB_BIN, "source", "add", str(sf), "-n", nb_id,
                 "--title", sf.name, "--json"],
                parse_json=True,
            )
            if ok:
                added += 1
                print(f"  source added: {sf.name}")
            else:
                print(f"  WARN: source add failed for {sf.name}: {res}", file=sys.stderr)
        if added == 0:
            print("ERROR: no sources added", file=sys.stderr)
            return []

        for i, panel in enumerate(panels, 1):
            name = panel.get("name") or f"panel{i}"
            style = panel.get("style", "professional")
            # Force professional: cartoon/cute styles look unprofessional for
            # finance content (user 2026-06-04). Silently downgrade + warn.
            if style in CARTOON_STYLES:
                print(f"  [pro-guard] style '{style}' is cartoonish → using 'professional'",
                      file=sys.stderr)
                style = "professional"
            # Append the no-cartoon directive to the prompt (style alone leaks
            # cartoon mascots without it).
            prompt = panel["prompt"].rstrip() + "\n\n" + _NO_CARTOON
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
    # Sources = the FULL evidence package (combine freely). Feed the source DATA
    # (results.json / README / refs), not just the finished article prose.
    ap.add_argument("--experiment", action="append", default=[],
                    help="K-id — auto-adds experiments/<k>/{<k>_results.json,README.md,draft.md}; repeatable")
    ap.add_argument("--source", action="append", default=[],
                    help="extra source file (data/refs/.md); repeatable")
    ap.add_argument("--article-id", help="feed.json article id (mile_...) — adds article content as a source")
    ap.add_argument("--source-file", help="(legacy alias for --source) single article file")
    ap.add_argument("--title", default="懶人包")
    # Single-panel mode:
    ap.add_argument("--prompt", help="single-panel GOOD prompt (see skill)")
    ap.add_argument("--out", help="single-panel output png path")
    ap.add_argument("--style", default="professional", choices=sorted(VALID_STYLES))
    ap.add_argument("--orientation", default="landscape", choices=sorted(VALID_ORIENT))
    ap.add_argument("--detail", default="standard", choices=sorted(VALID_DETAIL))
    # Multi-panel (poster-session) mode:
    ap.add_argument("--plan", help="JSON file: [{name,prompt,style?,orientation?,detail?}] "
                    "— one infographic per panel (concept / method / results), each its own info type")
    ap.add_argument("--out-dir", help="output dir for multi-panel mode")
    ap.add_argument("--keep-notebook", action="store_true")
    a = ap.parse_args()

    if not a.plan and not (a.prompt and a.out):
        ap.error("provide either --plan + --out-dir (multi) or --prompt + --out (single)")

    # --- Build the evidence-package source list ---
    source_files: list[Path] = []
    for k in a.experiment:
        k_lower = k.lower()
        kdir = ROOT / "experiments" / k_lower
        for fname in (f"{k_lower}_results.json", "README.md", "draft.md"):
            p = kdir / fname
            if p.exists():
                source_files.append(p)
    for s in a.source:
        source_files.append(Path(s))
    if a.source_file:
        source_files.append(Path(a.source_file))
    if a.article_id:
        content = _article_content(a.article_id)
        if content:
            tmp = Path(tempfile.mkstemp(suffix="_article.md")[1])
            tmp.write_text(content, encoding="utf-8")
            source_files.append(tmp)
        else:
            print(f"WARN: article {a.article_id} not found in feed.json (continuing with other sources)",
                  file=sys.stderr)
    if not source_files:
        print("ERROR: no sources — provide --experiment / --source / --source-file / --article-id",
              file=sys.stderr)
        return 1

    title = a.title
    if title == "懶人包":
        if a.experiment:
            title = f"{a.experiment[0]} 懶人包"
        elif a.article_id:
            title = f"{a.article_id} 懶人包"

    if a.plan:
        panels = json.loads(Path(a.plan).read_text(encoding="utf-8"))
        if not isinstance(panels, list) or not panels:
            print("ERROR: --plan must be a non-empty JSON list", file=sys.stderr)
            return 1
        out_dir = Path(a.out_dir or tempfile.mkdtemp())
        written = generate_panels(
            source_files=source_files, title=title, panels=panels,
            out_dir=out_dir, keep_notebook=a.keep_notebook,
        )
        print(f"\nDONE: {len(written)}/{len(panels)} panels -> {out_dir}")
        for p in written:
            print(f"  {p}")
        return 0 if written else 1

    # single-panel: map to a 1-panel plan
    out = Path(a.out)
    written = generate_panels(
        source_files=source_files, title=title,
        panels=[{"name": out.stem, "prompt": a.prompt, "style": a.style,
                 "orientation": a.orientation, "detail": a.detail}],
        out_dir=out.parent, keep_notebook=a.keep_notebook,
    )
    if written and written[0] != out:
        try:
            written[0].replace(out)
        except OSError:
            pass
    return 0 if written else 1


if __name__ == "__main__":
    raise SystemExit(main())
