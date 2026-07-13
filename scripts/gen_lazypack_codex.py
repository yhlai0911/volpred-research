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

Flow (2026-07-11 rewrite — see below): gather evidence package → codex WRITES a
render script (bounded call, no execution) → THIS process runs it locally with
its own timeout → verify PNGs → bounded repair rounds on failure. CLI mirrors
gen_lazypack_infographic.py so the two are drop-in swappable.

Why the LLM no longer executes anything (2026-07-11, boss Telegram msg 465):
the old flow handed codex one 900s agentic call to read evidence + write the
script + run matplotlib + hunt a CJK font + retry on tofu. That loop routinely
blew the wall (both 2026-07-11 renders died at exactly 900s), and a hourly agent
retrying it inline blocked past the supervisor's 3000s cap → SIGKILL →
hang_killed. Splitting it fixes the class, not the instance:

  codex   : reads evidence, writes <out_dir>/render_lazypack.py, stops.
            One bounded call. No matplotlib, no font hunt, no retry loop.
  local   : runs the script under `subprocess.run(timeout=)`. Deterministic,
            seconds not minutes, and a hang is impossible — the timeout is ours.
  repair  : if the script raises or a PNG is missing, feed the traceback back
            for a bounded fix-the-script call. At most REPAIR_ROUNDS of these.
  budget  : every phase draws from one wall-clock deadline (--budget-s), so the
            worst case is bounded no matter which phase misbehaves.

The CJK font is resolved HERE (matplotlib's own font list) and injected into the
prompt as a known-good family name, because font discovery was the single
biggest source of codex's agentic thrashing and it is a thing the local machine
can simply answer.

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
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dispatch_supervisor.procutil import kill_tree  # noqa: E402


def _resolve_codex_bin() -> str:
    """Absolute codex path, so a caller's PATH cannot decide whether we can render.

    codex lives in an nvm-managed bin dir that only interactive shells put on
    PATH (nvm init lives in .zshrc). Non-interactive callers — Claude Bash tool
    calls, subagents, any launchd job whose plist forgets the entry — get
    rc 3 "codex CLI not found", which reads as "codex cannot make images" when
    codex is in fact fine. Resolve the binary ourselves instead.
    """
    found = shutil.which("codex")
    if found:
        return found
    for candidate in Path.home().glob(".nvm/versions/node/*/bin/codex"):
        if os.access(candidate, os.X_OK):
            return str(candidate)
    for candidate in ("/opt/homebrew/bin/codex", "/usr/local/bin/codex"):
        if os.access(candidate, os.X_OK):
            return candidate
    return "codex"


def _ensure_codex_runtime_on_path(codex_bin: str) -> None:
    """codex's shebang is `env node` — resolving the codex path is not enough.

    A non-interactive caller that lacks the nvm bin dir also lacks `node`, so
    spawning an absolute codex still dies with `env: node: No such file`.
    Prepend the binary's own dir so its interpreter resolves too.
    """
    # NOT .resolve(): nvm's bin/codex is a symlink into lib/node_modules/,
    # and node lives in the bin dir, not in the symlink target dir.
    bin_dir = str(Path(codex_bin).absolute().parent)
    parts = os.environ.get("PATH", "").split(os.pathsep)
    if bin_dir not in parts:
        os.environ["PATH"] = os.pathsep.join([bin_dir, *parts])


CODEX_BIN = _resolve_codex_bin()
_ensure_codex_runtime_on_path(CODEX_BIN)

# One wall-clock budget for the whole generation; every phase draws from it.
# Stays under the 1800s compute_queue job timeout with room for the upload →
# append → sync steps that follow a render.
DEFAULT_BUDGET_S = 1500
# Writing a render script scales with the panel count — each panel is another
# layout codex has to compose and another set of evidence numbers to read. A
# flat 360s starved a 3-panel plan: on 2026-07-11 mile_531e4c87's write took
# ~1020s (measured off the orphan that outlived its own timeout), so budget the
# write per panel with headroom over that.
CODEX_WRITE_BASE_S = 420
CODEX_WRITE_PER_PANEL_S = 240
CODEX_WRITE_CEILING_S = 1200
# Local matplotlib/PIL render of a handful of panels. Seconds in practice.
RENDER_TIMEOUT_S = 240
REPAIR_ROUNDS = 3
RENDER_SCRIPT_NAME = "render_lazypack.py"

# Second writer. codex sometimes ends its turn having only *talked* about the
# render script without writing it (2026-07-13 mile_aa4713db: rc=2, "codex write
# produced no render_lazypack.py" — the transcript is codex narrating what the
# renderer *would* do). One provider refusing to emit a file must not strand the
# article in draft, so a different model gets the same prompt before we give up.
CLAUDE_FALLBACK_MODEL = os.environ.get("LAZYPACK_FALLBACK_MODEL", "claude-fable-5")


def _resolve_claude_bin() -> str:
    found = shutil.which("claude")
    if found:
        return found
    for candidate in (Path.home() / ".claude" / "local" / "claude",
                      Path("/opt/homebrew/bin/claude"),
                      Path("/usr/local/bin/claude")):
        if os.access(candidate, os.X_OK):
            return str(candidate)
    return "claude"


CLAUDE_BIN = _resolve_claude_bin()

# Ordered by how well they render zh-Hant on macOS. Resolved locally so codex
# never has to discover a font (the old flow's worst time sink).
_CJK_FONT_CANDIDATES = (
    "PingFang TC", "Heiti TC", "Hiragino Sans GB",
    "Arial Unicode MS", "Songti SC", "Noto Sans CJK TC",
)


def _resolve_cjk_font() -> str | None:
    """First installed family from `_CJK_FONT_CANDIDATES`, or None."""
    try:
        from matplotlib import font_manager
    except Exception as exc:  # noqa: BLE001
        print(f"WARN: matplotlib unavailable for font probe: {exc}", file=sys.stderr)
        return None
    installed = {f.name for f in font_manager.fontManager.ttflist}
    for name in _CJK_FONT_CANDIDATES:
        if name in installed:
            return name
    return None

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


def _gather_sources(a: argparse.Namespace, out_dir: Path | None = None) -> list[Path]:
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
            # Next to the panels, not in /var/folders: the render script cites
            # its source paths, and a script pointing at a reaped temp file is
            # neither re-runnable by the repair round nor by a reviewer.
            # Gitignored (.gitignore: storage/lazypack_jobs/*/panels/*_article.md) —
            # derived from feed.json, and no fire owns it, so tracking it strands
            # an orphan that PHASE-Z re-alerts on every shift.
            if out_dir is not None:
                out_dir.mkdir(parents=True, exist_ok=True)
                art = out_dir / f"{a.article_id}_article.md"
            else:
                art = Path(tempfile.mkstemp(suffix="_article.md")[1])
            art.write_text(content, encoding="utf-8")
            source_files.append(art)
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


def _build_prompt(
    title: str,
    panels: list[dict],
    sources: list[Path],
    out_dir: Path,
    font: str | None = None,
) -> str:
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
    font_rule = (
        f"- **字型**: 直接用 `'{font}'`（本機已確認安裝，不要再自己偵測或試別的）。"
        f"設 `plt.rcParams['font.sans-serif'] = ['{font}']` 且 "
        f"`plt.rcParams['axes.unicode_minus'] = False`。"
        if font else
        "- **字型**: 本機找不到 CJK 字型，程式裡用 matplotlib.font_manager 挑一個可用的 "
        "CJK family，設 font.sans-serif 且 axes.unicode_minus=False。"
    )
    script_path = out_dir / RENDER_SCRIPT_NAME
    return f"""你是資深資料視覺化工程師。請為一篇 VolPred 一般讀者文章「{title}」**寫一支** render 程式，
它會產生一組「懶人包圖組」PNG。

## 你的工作（只有兩步，做完就結束）
1. 讀以下 evidence package（**數字一律以 results.json 為準，逐字對齊，禁臆造**）:
{src_lines}
2. 寫出檔案 {script_path} — 一支獨立可執行的 Python 程式（matplotlib 或 PIL），
   執行後為下列每個 panel 各輸出一張獨立 PNG 到 {out_dir}，檔名用每個 panel 指定的 `<name>.png`。
{ref_hint}

## ⛔ 不要做的事（這些由呼叫端負責，你做了只會拖垮時間預算）
- **不要執行**那支程式（不要 `python render_lazypack.py`，不要試跑、不要驗證輸出）。
- **不要**安裝任何套件、不要 pip install。matplotlib / PIL / numpy 都已就緒。
- **不要**呼叫任何影像生成模型。
- **不要**自己偵測字型或迭代重跑。
寫完 {script_path} 就直接結束回合。

## 程式必須自帶的東西（因為呼叫端會直接跑它）
- 讀 evidence 的路徑用**絕對路徑**（上面列的那些），不要依賴 cwd。
- 數字從 evidence 檔案**讀出來**（json.load 等），不要把數字硬編在字串裡 — 除非該數字只在文章正文出現。
- `out_dir` 常數就寫死成 {out_dir}，並在寫檔前 `os.makedirs(out_dir, exist_ok=True)`。
- 用 `matplotlib.use("Agg")`（無頭環境）。
- 任何欄位缺失就 raise（讓呼叫端看得到 traceback），不要 silently 畫出假數字。

## Panels（每張只講一種資訊型態，禁止全塞一張）
{panels_text}

## 版面硬規則（研究誠實 + 專業，違反即失敗）
- **數字精確**: 圖上每個統計量/數字必須能對應 evidence 的某個欄位/數據；不確定就不要放。
- **語言**: 全部繁體中文（zh-Hant）。
{font_rule}
- **專業、資料導向、非卡通**: 乾淨圖表 + 圖示 + 大數字 + 分區；**禁卡通人物 / 可愛插畫 / 手繪塗鴉**。
- **每張底部標資料來源**: 例「資料來源：experiment K####」（K 編號從 evidence 檔名/內容判斷）。
- **不要把 panel 的 info / 資訊型態（concept/method/results）當文字標籤畫在圖上** — 那是內部分類，讀者不需要看到。
- **尺寸**: 橫式約 1600x1000 px、150 dpi、白底，邊距充足，字夠大（一眼看懂）。
- **不要**輸出 base64 或 data-URI；輸出實體 .png 檔到 {out_dir}。
- **文字不可溢出、不可互相重疊（呼叫端會機械檢查，違反直接 rc≠0）**：每段文字都必須完整落在畫布內，
  且任兩段文字的方框不得相撞（標題壓副標、內文壓浮水印、長句被右緣切掉，都算失敗）。
  長句請先在程式裡自己折行（textwrap）或縮小字級，**不要假設畫布會自動容納**；
  裝飾性大字（浮水印）要嘛不放，要嘛放在絕對不會被文字覆蓋的空白區。

## 完成後
一句話說明每張圖的主要數字讀自 evidence 的哪個欄位。
"""


def _build_repair_prompt(script_path: Path, failure: str, out_dir: Path,
                         missing: list[Path], font: str | None) -> str:
    missing_text = "\n".join(f"  - {p}" for p in missing) or \
        "  (無 — 檔案有產出但程式回報失敗)"
    font_note = f"\n- 字型固定用 '{font}'，不要換、不要偵測。" if font else ""
    return f"""你上一輪寫的 render 程式 {script_path} 執行失敗了。請**修好這支程式**。

## 執行結果（呼叫端在本機跑的，非你跑的）
```
{failure[-3000:]}
```

## 缺少的 PNG
{missing_text}

## 規則
- **只改** {script_path}，改完就結束回合。
- **不要執行**它、不要試跑、不要安裝套件 — 呼叫端會再跑一次。
- 原本的資料誠實規則不變：數字一律從 evidence 檔案讀，缺欄位就 raise，禁臆造。
- 輸出目錄仍是 {out_dir}。{font_note}
"""


def _kill_process_group(proc: subprocess.Popen) -> bool:
    """Kill codex and everything it spawned. True only if confirmed all gone.

    Delegates to `procutil.kill_tree` — the repo's single owner for killing a
    process and its escaped descendants. This used to be a local `killpg`, which
    cannot reach a child that `setsid()`s into its own group, and codex's worker
    does exactly that (2026-07-11 mile_531e4c87, 2026-07-13 mile_aa4713db: both
    wrote render_lazypack.py minutes after we declared the job dead). Group-only
    kills are why a "failed" job kept writing to disk behind our back.
    """
    ok = kill_tree(proc.pid)
    if not ok:
        print(f"[gen_lazypack_codex] WARNING: could not confirm codex pid "
              f"{proc.pid} and its children are dead — a surviving worker may "
              f"still write to the output dir", file=sys.stderr)
    proc.kill()  # reap our own handle; the tree kill already covered the group
    return ok


def _codex_write_timeout(panels: list[dict]) -> float:
    """Write budget for a plan. Scales with panels — see CODEX_WRITE_BASE_S."""
    return min(CODEX_WRITE_CEILING_S,
               CODEX_WRITE_BASE_S + CODEX_WRITE_PER_PANEL_S * max(1, len(panels)))


def _run_codex(prompt: str, out_dir: Path, timeout_s: float,
               model: str | None) -> tuple[int, str]:
    """One bounded `codex exec`. Returns (rc, combined stdout+stderr tail).

    rc 3 = codex CLI missing, rc 2 = timed out. Never raises on codex failure —
    the caller decides whether the render script it was supposed to write
    actually landed, which is the only outcome that matters.

    The call runs in its own process group so a timeout kills codex's workers
    too. `subprocess.run(timeout=)` only kills the process we spawned: on
    2026-07-11 mile_531e4c87 timed out at 360s, the surviving worker wrote
    render_lazypack.py 11 minutes later, and that unowned file sat in the
    worktree until PHASE-Z flagged it (3 shifts). A timeout must mean nothing
    further lands, otherwise "failed" jobs keep writing behind our back.
    """
    cmd = [CODEX_BIN, "exec", "-s", "workspace-write", "-C", str(ROOT),
           "--add-dir", str(out_dir), "--skip-git-repo-check"]
    if model:
        cmd += ["-m", model]
    try:
        proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, cwd=str(ROOT),
            start_new_session=True,
        )
    except FileNotFoundError:
        return 3, "codex CLI not found on PATH (see CLAUDE.md dual-CLI note)"
    try:
        out, err = proc.communicate(input=prompt, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        _kill_process_group(proc)
        try:
            out, err = proc.communicate(timeout=30)
        except Exception as e:  # noqa: BLE001
            print(f"[gen_lazypack_codex] drain after kill failed: {e}",
                  file=sys.stderr)
            out, err = "", ""
        tail = (out[-1000:] + "\n" + err[-1000:]).strip()
        return 2, (f"codex exec timed out after {timeout_s:.0f}s "
                   f"(process group killed)\n{tail}")
    out = out or ""
    err = err or ""
    if proc.returncode != 0:
        # 2026-07-10 incident: an API error (e.g. 400 model-not-supported) is
        # streamed mid-stdout while rc can still be 0 — surface it next to the
        # failure rather than burying it in the stream.
        for ln in [l for l in out.splitlines() if '"type":"error"' in l][-3:]:
            print(f"CODEX-ERROR: {ln[-300:]}", file=sys.stderr)
    return proc.returncode, (out[-2000:] + "\n" + err[-2000:]).strip()


def _run_claude(prompt: str, out_dir: Path, timeout_s: float,
                model: str) -> tuple[int, str]:
    """Fallback writer: headless Claude CLI, same prompt, different provider.

    Same contract as `_run_codex` — never raises, the caller only checks whether
    the render script landed. rc 3 = CLI missing, rc 2 = timed out.
    """
    # acceptEdits + a write-only allowlist, not bypassPermissions: this writer
    # only has to emit one render script, so it never needs Bash or network.
    cmd = [CLAUDE_BIN, "-p", "--model", model,
           "--permission-mode", "acceptEdits",
           "--allowedTools", "Write,Edit,Read",
           "--add-dir", str(out_dir)]
    try:
        proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, cwd=str(ROOT),
            start_new_session=True,
        )
    except FileNotFoundError:
        return 3, "claude CLI not found on PATH"
    try:
        out, err = proc.communicate(input=prompt, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        _kill_process_group(proc)
        try:
            out, err = proc.communicate(timeout=30)
        except Exception as e:  # noqa: BLE001
            print(f"[gen_lazypack_codex] drain after kill failed: {e}",
                  file=sys.stderr)
            out, err = "", ""
        tail = ((out or "")[-1000:] + "\n" + (err or "")[-1000:]).strip()
        return 2, f"claude -p timed out after {timeout_s:.0f}s\n{tail}"
    return proc.returncode, ((out or "")[-2000:] + "\n" + (err or "")[-2000:]).strip()


def _write_script(prompt: str, script: Path, out_dir: Path, budget_s: float,
                  model: str | None) -> tuple[int, str, str]:
    """Drive writers until `script` exists. Returns (rc, tail, writer_used).

    codex first (flat-rate ChatGPT subscription). If it ends its turn without
    writing the file, hand the identical prompt to a second model rather than
    failing the job — a writer that talks instead of writing is a per-provider
    failure, not a reason to leave the article without its 懶人包.
    """
    rc, tail = _run_codex(prompt, out_dir, budget_s, model)
    if script.exists():
        return rc, tail, "codex"
    print(f"[gen_lazypack_codex] codex produced no {script.name} (rc={rc}) — "
          f"escalating to {CLAUDE_FALLBACK_MODEL}", file=sys.stderr)
    rc2, tail2 = _run_claude(prompt, out_dir, budget_s, CLAUDE_FALLBACK_MODEL)
    if script.exists():
        print(f"[gen_lazypack_codex] fallback writer {CLAUDE_FALLBACK_MODEL} "
              f"wrote {script.name}", file=sys.stderr)
        return rc2, tail2, CLAUDE_FALLBACK_MODEL
    return (rc2 or rc or 1), f"codex(rc={rc}):\n{tail}\n\n" \
                             f"{CLAUDE_FALLBACK_MODEL}(rc={rc2}):\n{tail2}", "none"


def _run_render_script(script: Path, timeout_s: float) -> tuple[bool, str]:
    """Run the codex-written render script locally. (ok, failure_text).

    Under scripts/lazypack_layout_guard.py: a figure whose text is clipped by the
    canvas, overlaps other text, or bursts out of the card it is drawn on raises out
    of savefig, so a garbled panel fails here and reaches the repair round. Without it
    "the PNG exists" was the whole success criterion, and three unreadable panels
    shipped (2026-07-11).
    """
    guard = ROOT / "scripts" / "lazypack_layout_guard.py"
    try:
        proc = subprocess.run(
            [sys.executable, str(guard), str(script)], cwd=str(ROOT),
            capture_output=True, text=True, timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return False, f"render script exceeded {timeout_s:.0f}s and was killed"
    if proc.returncode != 0:
        return False, (f"render script exited rc={proc.returncode}\n"
                       f"{(proc.stderr or proc.stdout or '')[-3000:]}")
    return True, ""


def _missing_panels(out_dir: Path, panels: list[dict]) -> list[Path]:
    expected = [out_dir / f"{(p.get('name') or f'{i}_panel')}.png"
                for i, p in enumerate(panels, 1)]
    return [p for p in expected
            if not p.exists() or p.stat().st_size <= 1024]


def _generate(title: str, panels: list[dict], sources: list[Path], out_dir: Path,
              *, budget_s: float, model: str | None) -> int:
    """codex writes the script → we run it → bounded repair rounds. All phases
    share one deadline, so no single step can wedge the caller."""
    deadline = time.monotonic() + budget_s

    def remaining() -> float:
        return deadline - time.monotonic()

    font = _resolve_cjk_font()
    print(f"[gen_lazypack_codex] CJK font: {font or 'NONE FOUND (codex will pick)'}",
          file=sys.stderr)
    script = out_dir / RENDER_SCRIPT_NAME

    # Resume semantics. A lazypack run is one step of a longer job (render →
    # upload → append → sync); when a later step dies, the retry lands back
    # here with the panels already on disk. Re-driving codex to recreate work
    # that exists is what turned a failed upload into a 900s codex call.
    #   panels present        → nothing to do.
    #   script present, no PNG → run the script we already have before writing
    #                            a new one (a crashed render, not a bad prompt).
    if not _missing_panels(out_dir, panels):
        print(f"\nDONE: {len(panels)}/{len(panels)} panel PNGs already in {out_dir} "
              f"(reused — no codex call)")
        return 0

    prompt: str | None = _build_prompt(title, panels, sources, out_dir, font=font)
    if script.exists():
        print(f"[gen_lazypack_codex] {script.name} already exists — running it "
              f"before calling codex", file=sys.stderr)
        prompt = None

    for attempt in range(REPAIR_ROUNDS + 1):
        if prompt is not None:
            phase = "write" if attempt == 0 else f"repair {attempt}/{REPAIR_ROUNDS}"
            codex_budget = min(_codex_write_timeout(panels), remaining())
            if codex_budget <= 30:
                print(f"ERROR: budget exhausted before codex {phase} "
                      f"({remaining():.0f}s left of {budget_s:.0f}s)", file=sys.stderr)
                return 2
            print(f"[gen_lazypack_codex] codex {phase} (≤{codex_budget:.0f}s) "
                  f"→ {script}", file=sys.stderr)
            rc, tail, writer = _write_script(prompt, script, out_dir,
                                             codex_budget, model)
            if not script.exists():
                print(f"ERROR: no writer produced {script} during {phase} "
                      f"(rc={rc})\n{tail}", file=sys.stderr)
                return 2 if rc in (2, 3) else 1
            if writer != "codex":
                print(f"[gen_lazypack_codex] {phase} completed by fallback "
                      f"writer: {writer}", file=sys.stderr)

        render_budget = min(RENDER_TIMEOUT_S, remaining())
        if render_budget <= 10:
            print("ERROR: budget exhausted before local render", file=sys.stderr)
            return 2
        print(f"[gen_lazypack_codex] running {script.name} locally "
              f"(≤{render_budget:.0f}s)", file=sys.stderr)
        ok, failure = _run_render_script(script, render_budget)
        missing = _missing_panels(out_dir, panels)
        if ok and not missing:
            print(f"\nDONE: {len(panels)}/{len(panels)} panel PNGs in {out_dir}")
            for p in [out_dir / f"{(x.get('name') or f'{i}_panel')}.png"
                      for i, x in enumerate(panels, 1)]:
                print(f"  [ok] {p}")
            return 0

        failure = failure or f"script exited 0 but panels are missing/empty: {missing}"
        print(f"[gen_lazypack_codex] render failed: {failure.splitlines()[0]}",
              file=sys.stderr)
        if attempt == REPAIR_ROUNDS:
            break
        prompt = _build_repair_prompt(script, failure, out_dir, missing, font)

    missing = _missing_panels(out_dir, panels)
    print(f"ERROR: render still failing after {REPAIR_ROUNDS} repair round(s); "
          f"missing {len(missing)}/{len(panels)} panels", file=sys.stderr)
    for p in missing:
        print(f"  [MISSING] {p}", file=sys.stderr)
    return 1


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
    ap.add_argument("--budget-s", type=float, default=DEFAULT_BUDGET_S,
                    help="wall-clock budget for codex write + local render + "
                         f"repair rounds combined (default: {DEFAULT_BUDGET_S}s)")
    ap.add_argument("--dry-run", action="store_true", help="print the codex prompt and exit (no codex call)")
    a = ap.parse_args()

    panels = json.loads(Path(a.plan).read_text(encoding="utf-8"))
    if isinstance(panels, dict) and isinstance(panels.get("panels"), list):
        panels = panels["panels"]
    if not isinstance(panels, list) or not panels:
        print("ERROR: --plan must be a non-empty JSON list (or {panels:[...]})", file=sys.stderr)
        return 1

    out_dir = Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    sources = _gather_sources(a, out_dir)
    if not sources:
        print("ERROR: no sources — provide --experiment / --source / --article-id", file=sys.stderr)
        return 1

    title = a.title
    if title == "懶人包" and a.experiment:
        title = f"{a.experiment[0]} 懶人包"

    if a.dry_run:
        print(_build_prompt(title, panels, sources, out_dir, font=_resolve_cjk_font()))
        return 0

    return _generate(title, panels, sources, out_dir,
                     budget_s=a.budget_s, model=a.model)


if __name__ == "__main__":
    raise SystemExit(main())
