#!/usr/bin/env python3
r"""Lazypack (懶人包圖組) generator — PRIMARY path via `codex exec`.

Boss directive (2026-06-30): generate reader-facing 懶人包 infographics with
`codex exec` (ChatGPT-subscription Codex CLI — flat-rate, NOT per-image metered),
NOT NotebookLM (now the FALLBACK, see gen_lazypack_infographic.py).

Why codex exec is primary:
  - Codex WRITES a Python render script (matplotlib/PIL) fed the evidence package,
    so every number on the image is read straight from `<k>_results.json` — no
    AI-image-gen hallucination (research honesty).
  - Reproducible: the render script is saved next to the PNGs; same input → same
    output; reviewers can re-run it.
  - Zero incremental cost: ChatGPT subscription is flat; local matplotlib/PIL
    render calls no metered image API. (gpt-image-2 / paid Gemini key forbidden.)
  - Controllable poster layout (bento-grid / sections / big numbers) by code.

A frozen example of the kind of data-bound Pillow renderer codex should write
lives at scripts/lazypack_render_example_spacex.py (article-specific; reference
only). This harness makes codex write a BESPOKE renderer per article instead.

Flow: gather evidence package → compose a codex prompt (evidence paths + panel
plan + hard rules) → `codex exec -s workspace-write` writes & runs a render script
→ verify each expected PNG exists. CLI mirrors gen_lazypack_infographic.py so the
two are drop-in swappable.

Usage:
  uv run python scripts/gen_lazypack_codex.py \
    --experiment K1576 \              # auto-adds experiments/k1576/{<k>_results.json,README,draft}
    --source experiments/k1576/refs.md \
    --title "K1576 懶人包" \
    --plan /tmp/plan.json \           # [{name, info, must_show?, style?}] one PNG per panel
    --out-dir /tmp/k1576_poster

plan.json panel schema (each panel = one PNG, one info type):
  [
    {"name": "1_framework", "info": "concept", "must_show": "這篇在問什麼 + 核心名詞白話"},
    {"name": "2_method",    "info": "method",  "must_show": "怎麼量/算的（白話步驟，非統計術語）"},
    {"name": "3_results",   "info": "results", "must_show": "主要數字 + 一句結論"}
  ]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CODEX_BIN = "codex"
# codex render can take a few minutes (write script + matplotlib/PIL run).
CODEX_TIMEOUT_S = 900

_STYLE_HINTS = {
    "professional": "乾淨企業風、留白充足、深色標題列 + 數據區塊",
    "bento-grid": "bento-grid 分格，每格一個重點數字/圖示",
    "editorial": "雜誌編輯風、清楚層級、一個主視覺 + 註解",
    "scientific": "研討會壁報風、方法步驟 + 圖表，標資料來源",
}
_REFERENCE_RENDERER = ROOT / "scripts" / "lazypack_render_example_spacex.py"


def _article_content(article_id: str) -> str | None:
    feed_path = ROOT / "storage" / "reports" / "feed.json"
    try:
        feed = json.loads(feed_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"WARN: cannot read feed.json for {article_id}: {exc}", file=sys.stderr)
        return None
    for item in feed:
        if isinstance(item, dict) and item.get("id") == article_id:
            return item.get("content") or item.get("description")
    return None


def _gather_sources(a: argparse.Namespace) -> list[Path]:
    source_files: list[Path] = []
    for k in a.experiment:
        kdir = ROOT / "experiments" / k.lower()
        for fname in (f"{k.lower()}_results.json", "README.md", "draft.md"):
            p = kdir / fname
            if p.exists():
                source_files.append(p)
    for s in a.source:
        p = Path(s)
        if p.exists():
            source_files.append(p)
        else:
            print(f"WARN: --source not found, skipping: {s}", file=sys.stderr)
    if a.article_id:
        content = _article_content(a.article_id)
        if content:
            tmp = Path(tempfile.mkstemp(suffix="_article.md")[1])
            tmp.write_text(content, encoding="utf-8")
            source_files.append(tmp)
        else:
            print(f"WARN: article {a.article_id} not found in feed (continuing)", file=sys.stderr)
    seen: set[str] = set()
    uniq: list[Path] = []
    for p in source_files:
        key = str(p.resolve())
        if key not in seen:
            seen.add(key)
            uniq.append(p)
    return uniq


def _build_prompt(title: str, panels: list[dict], sources: list[Path], out_dir: Path) -> str:
    src_lines = "\n".join(f"  - {p}" for p in sources)
    panel_lines = []
    for i, panel in enumerate(panels, 1):
        name = panel.get("name") or f"{i}_panel"
        info = panel.get("info") or "results"
        must = panel.get("must_show") or ""
        style = panel.get("style") or "professional"
        hint = _STYLE_HINTS.get(style, _STYLE_HINTS["professional"])
        panel_lines.append(
            f"  Panel {i} — 檔名 {name}.png\n"
            f"    資訊型態: {info}\n"
            f"    必含: {must}\n"
            f"    版面風格: {style}（{hint}）"
        )
    panels_text = "\n".join(panel_lines)
    ref_hint = (
        f"可參考既有的 data-bound Pillow 範例 {_REFERENCE_RENDERER}（數字綁 JSON 欄位的寫法），"
        "但你要為這篇文章自己的數據重寫，不要沿用 SpaceX 欄位。"
        if _REFERENCE_RENDERER.exists() else ""
    )
    return f"""你是資深資料視覺化工程師。請為一篇 VolPred 一般讀者文章「{title}」產生一組「懶人包圖組」PNG。

## 你的工作（用程式 render，不要呼叫任何影像生成模型）
1. 先讀以下 evidence package（**數字一律以 results.json 為準，逐字對齊，禁臆造**）:
{src_lines}
2. 寫一支 Python render 程式（matplotlib 或 PIL），為下列每個 panel 各輸出一張獨立 PNG 到目錄:
   {out_dir}
   檔名就用每個 panel 指定的 `<name>.png`。
3. 跑這支程式，確認每個 PNG 都產出且非空。
4. 把 render 程式存成 {out_dir}/render_lazypack.py（可復現）。
{ref_hint}

## Panels（每張只講一種資訊型態，禁止全塞一張）
{panels_text}

## 硬規則（研究誠實 + 專業，違反即失敗）
- **數字精確**: 圖上每個統計量/數字必須能對應 evidence 的某個欄位/數據；不確定就不要放。
- **語言**: 全部繁體中文（zh-Hant）。matplotlib 必設 CJK 字型（macOS 試 'Heiti TC' / 'PingFang TC' /
  'Arial Unicode MS'，挑一個存在的；設 plt.rcParams['font.sans-serif'] 且 axes.unicode_minus=False）。
  **檢查不可有缺字方框（tofu）**；若主字型缺字就換另一個 CJK 字型重跑。
- **專業、資料導向、非卡通**: 乾淨圖表 + 圖示 + 大數字 + 分區；**禁卡通人物 / 可愛插畫 / 手繪塗鴉**。
- **每張底部標資料來源**: 例「資料來源：experiment K####」（K 編號從 evidence 檔名/內容判斷）。
- **不要把 panel 的 info / 資訊型態（concept/method/results）當文字標籤畫在圖上** — 那是內部分類，讀者不需要看到。
- **尺寸**: 橫式約 1600x1000 px、150 dpi、白底，邊距充足，字夠大（一眼看懂）。
- **不要**輸出 base64 或 data-URI；輸出實體 .png 檔到 {out_dir}。

## 完成後
列出實際產出的 PNG 絕對路徑清單，並一句話確認每張的主要數字來自 evidence 的哪個欄位。
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--experiment", action="append", default=[],
                    help="K-id — auto-adds experiments/<k>/{<k>_results.json,README.md,draft.md}; repeatable")
    ap.add_argument("--source", action="append", default=[],
                    help="extra source file (data/refs/.md); repeatable")
    ap.add_argument("--article-id", help="feed.json article id (mile_...) — adds article content as a source")
    ap.add_argument("--title", default="懶人包")
    ap.add_argument("--plan", required=True,
                    help="JSON file: [{name, info, must_show?, style?}] — one PNG per panel")
    ap.add_argument("--out-dir", required=True, help="output dir for the PNG set")
    ap.add_argument("--model", help="override codex model (default: codex config)")
    ap.add_argument("--dry-run", action="store_true", help="print the codex prompt and exit (no codex call)")
    a = ap.parse_args()

    panels = json.loads(Path(a.plan).read_text(encoding="utf-8"))
    if isinstance(panels, dict) and isinstance(panels.get("panels"), list):
        panels = panels["panels"]
    if not isinstance(panels, list) or not panels:
        print("ERROR: --plan must be a non-empty JSON list (or {panels:[...]})", file=sys.stderr)
        return 1

    sources = _gather_sources(a)
    if not sources:
        print("ERROR: no sources — provide --experiment / --source / --article-id", file=sys.stderr)
        return 1

    title = a.title
    if title == "懶人包" and a.experiment:
        title = f"{a.experiment[0]} 懶人包"

    out_dir = Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    prompt = _build_prompt(title, panels, sources, out_dir)
    if a.dry_run:
        print(prompt)
        return 0

    cmd = [CODEX_BIN, "exec", "-s", "workspace-write", "-C", str(ROOT),
           "--add-dir", str(out_dir), "--skip-git-repo-check"]
    if a.model:
        cmd += ["-m", a.model]
    print(f"[gen_lazypack_codex] invoking codex exec for {len(panels)} panel(s) -> {out_dir}",
          file=sys.stderr)
    try:
        proc = subprocess.run(
            cmd, input=prompt, text=True, timeout=CODEX_TIMEOUT_S,
            cwd=str(ROOT), capture_output=True,
        )
    except FileNotFoundError:
        print("ERROR: codex CLI not found on PATH (install Codex CLI; see CLAUDE.md dual-CLI note)",
              file=sys.stderr)
        return 3
    except subprocess.TimeoutExpired:
        print(f"ERROR: codex exec timed out after {CODEX_TIMEOUT_S}s", file=sys.stderr)
        return 2
    if proc.stdout:
        print(proc.stdout[-4000:])
    if proc.returncode != 0:
        print(f"ERROR: codex exec rc={proc.returncode}\n{(proc.stderr or '')[-2000:]}", file=sys.stderr)
        # fall through to verification — codex may have produced files before erroring

    expected = [out_dir / f"{(p.get('name') or f'{i}_panel')}.png" for i, p in enumerate(panels, 1)]
    made = [p for p in expected if p.exists() and p.stat().st_size > 1024]
    if not made:
        # 2026-07-10 incident：codex 串流內的 API error（如 400 model-not-supported）
        # 印在 stdout 中段、rc 可能仍為 0 — 零產出時把 error 事件浮上 stderr summary，
        # 讓「為什麼失敗」跟「失敗了」出現在同一個地方（error_log 當日 entry）。
        err_lines = [ln for ln in (proc.stdout or "").splitlines() if '"type":"error"' in ln]
        for ln in err_lines[-3:]:
            print(f"CODEX-ERROR: {ln[-300:]}", file=sys.stderr)
        if err_lines:
            print("HINT: API error 常見根因是 config model × CLI 版本不相容 — 先跑 "
                  "`codex exec --skip-git-repo-check \"echo TEST\"` smoke（experiments.md 診斷 SOP step 6）",
                  file=sys.stderr)
    print(f"\nDONE: {len(made)}/{len(expected)} panel PNGs in {out_dir}")
    for p in expected:
        ok = p.exists() and p.stat().st_size > 1024
        print(f"  [{'ok' if ok else 'MISSING'}] {p}")
    return 0 if len(made) == len(expected) else 1


if __name__ == "__main__":
    raise SystemExit(main())
