#!/usr/bin/env python3
"""Trending-topic candidate scanner — free agy (Antigravity gemini-3.5) driven.

Wired as VOLPRED_TRENDING_SCAN_CMD so reader_facing_refill 可自動 seed
trending_repost 候選（不再靠主線程手掃 / 不再停擺）。

定位：只 seed 候選「主題」；真正的即時 WebSearch + 證據包 + 量化由
trending_repost 寫作 agent 負責（refill_reader_facing_pool.py 註解所述）。
所以用免費 agy 生候選即可，無付費 API 成本（用戶 2026-05-29 指定）。

Output (stdout): JSON
`{"candidates": [{"topic","title","description","quant_claims"}, ...]}`
契約見 scripts/refill_reader_facing_pool.py::_extract_trending_candidates。

Usage:
  uv run python scripts/scan_trending_agy.py            # 印 JSON 候選
  VOLPRED_TRENDING_SCAN_CMD="uv run python scripts/scan_trending_agy.py"
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.dispatch_supervisor import procutil  # noqa: E402

AGY = "/Users/yhlai0911/.local/bin/agy"

# 掃描範疇對齊 memory reference_trending_blog_sources：
# havingchien / Stratechery / 凱基·Ranger·元大 + 國外 forums + high-viral 3 類
# (AI 發展 / token maxxing / 矽谷裁員)。VolPred 角度 = 波動率 / 風險 / 策略。
PROMPT = """你是 VolPred 波動率研究平台的選題助手。請列出「現在」最可能引發討論、且適合用
波動率/風險/交易策略角度改寫成評論文章的 2-3 個熱門主題（台灣或國際財經、市場、AI 投資、總經事件）。

範疇參考：美股/台股市場焦點、Fed/CPI/NFP 等總經、AI 資本支出與科技股、矽谷裁員、加密、地緣政治對市場波動的影響。

只輸出 JSON 陣列，每個元素含：
- topic: 短主題標籤（英數或中文，≤6 字）
- title: 一句話文章方向（VolPred 波動率/風險角度，繁中，≤30 字）
- description: 2-3 句改寫切入點 brief（繁中，說明可量化/可驗證的角度）
- quant_claims: title/description 內每一個具體百分比、指數點數、成交量或金額的結構化清單。
  不確定或尚未由 primary source 核對的數字不要寫進 title/description。若有數字，每筆必填
  kind（percent/points/volume/amount）、value（文字中的數值）、provider（yfinance/fred）、
  date（YYYY-MM-DD）、metric；yfinance 另填 ticker，fred 另填 series_id。
  yfinance metric 只可用 close_change_pct/close_change_points/volume；fred metric 用 observation。

範例格式：
[{"topic":"台股","title":"台股單日跌 6.5%，波動率如何反應？","description":"核對當日收盤後，分析尾部風險。","quant_claims":[{"kind":"percent","value":-6.5,"provider":"yfinance","ticker":"^TWII","date":"2026-07-17","metric":"close_change_pct"}]}]

不要解釋，不要額外文字，只回 JSON 陣列。"""


def _warn_scan(message: str, exc: Exception | None = None) -> None:
    suffix = f": {type(exc).__name__}: {exc}" if exc is not None else ""
    print(f"[scan_trending_agy] WARN {message}{suffix}", file=sys.stderr)


def _extract_json(text: str):
    """從 agy 輸出（可能含 ```json fence 或前後散文）抽出第一個 JSON 陣列/物件。"""
    # 去 code fence
    fenced = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    # 找第一個 [ 或 { 起始的 JSON
    for opener, closer in (("[", "]"), ("{", "}")):
        start = text.find(opener)
        if start == -1:
            continue
        depth = 0
        for i in range(start, len(text)):
            if text[i] == opener:
                depth += 1
            elif text[i] == closer:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break
    return None


def main() -> int:
    # `agy` is an agentic CLI: it spawns its own tool subprocesses. subprocess.run's
    # timeout kills only the pid we spawned, so on timeout agy's workers survive,
    # reparent to init, and keep running unsupervised. Same bug class as
    # gen_lazypack_codex (2026-07-11) and run_agent_job (2026-07-12) — the fix is a
    # process group + procutil.kill_pgid, which is the single owner of this concern.
    # Gate: scripts/tests/test_agentic_cli_timeout_killpg.py
    try:
        proc = subprocess.Popen(
            [AGY, "-p", PROMPT],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            start_new_session=True,
        )
    except FileNotFoundError as exc:
        _warn_scan("agy command failed before producing output", exc)
        print(json.dumps({"candidates": [], "error": type(exc).__name__, "detail": str(exc)[:200]}))
        return 0

    try:
        stdout, stderr = proc.communicate(timeout=180)
    except subprocess.TimeoutExpired as exc:
        try:
            procutil.kill_pgid(os.getpgid(proc.pid))
        except (ProcessLookupError, PermissionError) as kill_exc:
            _warn_scan("agy timed out and its process group could not be killed", kill_exc)
        proc.wait()
        # 失敗 = 印空候選（best-effort，refill 視為 skip 不報錯）
        _warn_scan("agy command failed before producing output", exc)
        print(json.dumps({"candidates": [], "error": type(exc).__name__, "detail": str(exc)[:200]}))
        return 0

    proc = subprocess.CompletedProcess(proc.args, proc.returncode, stdout, stderr)

    if proc.returncode != 0:
        _warn_scan(f"agy command exited nonzero returncode={proc.returncode}")
        print(json.dumps({
            "candidates": [],
            "error": "agy_exit_nonzero",
            "returncode": proc.returncode,
            "stderr_tail": (proc.stderr or "")[-200:],
        }, ensure_ascii=False))
        return 0

    parsed = _extract_json(proc.stdout or "")
    if parsed is None:
        _warn_scan("agy output did not contain JSON candidates")
        print(json.dumps({"candidates": [], "error": "no_json_from_agy",
                          "raw_tail": (proc.stdout or "")[-200:]}))
        return 0

    if isinstance(parsed, dict):
        candidates = parsed.get("candidates", [])
    elif isinstance(parsed, list):
        candidates = parsed
    else:
        candidates = []
    candidates = [c for c in candidates if isinstance(c, dict) and (c.get("topic") or c.get("title"))]
    print(json.dumps({"candidates": candidates}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
