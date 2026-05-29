#!/usr/bin/env python3
"""arXiv q-fin 前沿主題掃描器 — 補上「研究方向被既有主題框住」的缺口。

背景（2026-05-29 用戶問「有上 arXiv 找主題嗎？skill 嗎？」）：
`autonomous-research` SKILL + methodology.md 有方法論規則「每 session 至少
1 次 WebSearch arXiv 找最新文獻」，但**全靠主線程手動記得**，沒有腳本、沒有
cron。等於「研究框住」風險的根源。本腳本把這條自動化。

**研究誠實設計（關鍵）**：直接打 arXiv 官方 export API 取 **ground-truth
結構化資料**（論文 ID / 標題 / 摘要 / 日期皆來自 arXiv 本身），**不經 LLM
摘要** — 避免 hallucinate 論文 ID/標題（違反 citation 真實性，見 K1259
provenance 教訓 + memory feedback「LLM 對 fluent citation hallucinate 率最高」）。

對比 `scan_trending_agy.py`：trending 用 agy 生「散戶熱門題」候選（容許 LLM
生成，因只 seed 主題、寫作 agent 會再 WebSearch 驗證）；本腳本是**學術前沿**，
論文 metadata 必須 byte-accurate，故走 API 不走 LLM。

掃描範疇（對齊 research_program.md 研究面向 A-I + 前沿文獻方向）：
  q-fin.ST 統計金融 / q-fin.RM 風險管理 / q-fin.PM 組合管理 / q-fin.TR 交易微結構
搜尋軸：volatility forecasting, GARCH, realized volatility, hedging, VaR,
tail risk, rough volatility, jump, conformal prediction。

Output (stdout):
  --json (預設)：{"candidates":[{arxiv_id,title,published,primary_category,
                  abstract_snippet,pdf_url,matched_axis}, ...], "scanned_at",
                  "categories", "new_count"}
  --markdown：可直接貼進 research_program.md `## 前沿文獻方向` 的 dated block

去重：跳過 arxiv_id 已出現在 research_program.md 的論文（避免重複 seed）。

Rate-limit：arXiv 政策每 3 秒 1 request；本腳本 category 間 sleep 3s +
429 指數退避重試。429 為暫時性（IP 節流），重試仍 fail 時 graceful 回傳已取得部分。

Usage:
  uv run python scripts/scan_arxiv_topics.py                 # JSON 候選
  uv run python scripts/scan_arxiv_topics.py --markdown      # research_program 區塊
  uv run python scripts/scan_arxiv_topics.py --days 30 --max 8
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESEARCH_PROGRAM = ROOT / "research_program.md"

ARXIV_API = "http://export.arxiv.org/api/query"
USER_AGENT = "VolPred-Research/1.0 (mailto:yihao.lai@gmail.com)"
_ATOM = {"a": "http://www.w3.org/2005/Atom"}

# 對齊 research_program.md 研究面向：每軸一組 abs: 關鍵詞 + 標籤。
# 標籤回填到 candidate.matched_axis，方便注入時歸入對應面向。
AXES: list[tuple[str, str]] = [
    ("面向A_波動率預測", "volatility forecasting OR realized volatility OR GARCH"),
    ("面向B_風險管理", "Value-at-Risk OR expected shortfall OR tail risk"),
    ("面向I_期貨避險", "hedging OR hedge ratio OR minimum variance hedge"),
    ("前沿_rough_vol", "rough volatility OR Hurst OR fractional volatility"),
    ("前沿_ML_GARCH", "machine learning volatility OR neural network GARCH OR deep learning realized"),
    ("前沿_jump_conformal", "jump diffusion volatility OR conformal prediction finance"),
]
# 限縮在 q-fin 類別，避免撈到無關 cs/stat 論文。
CATEGORIES = "cat:q-fin.ST OR cat:q-fin.RM OR cat:q-fin.PM OR cat:q-fin.TR"


def _fetch(search_query: str, max_results: int, *, retries: int = 3) -> bytes | None:
    """打 arXiv API，429 指數退避重試。全失敗回 None（caller graceful）。"""
    url = ARXIV_API + "?" + urllib.parse.urlencode({
        "search_query": search_query,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "max_results": max_results,
    })
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    delay = 3
    for attempt in range(retries):
        try:
            return urllib.request.urlopen(req, timeout=30).read()
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < retries - 1:
                time.sleep(delay)
                delay *= 2
                continue
            print(f"  [scan_arxiv] HTTP {exc.code} for query, giving up: {search_query[:50]}",
                  file=sys.stderr)
            return None
        except Exception as exc:  # noqa: BLE001 — graceful degrade on any net error
            print(f"  [scan_arxiv] {type(exc).__name__}: {exc}", file=sys.stderr)
            return None
    return None


def _parse(raw: bytes, axis: str, since: datetime) -> list[dict]:
    out: list[dict] = []
    # XXE / billion-laughs 防禦（defense-in-depth）：arXiv Atom 回應從不含
    # DTD / 實體宣告；偵測到即拒絕，避免 stdlib ElementTree 的實體展開風險。
    head = raw[:4096].lower()
    if b"<!doctype" in head or b"<!entity" in head:
        print("  [scan_arxiv] refused: response contains DTD/entity declaration",
              file=sys.stderr)
        return out
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return out
    for e in root.findall("a:entry", _ATOM):
        pub_el = e.find("a:published", _ATOM)
        title_el = e.find("a:title", _ATOM)
        summ_el = e.find("a:summary", _ATOM)
        id_el = e.find("a:id", _ATOM)
        if pub_el is None or title_el is None or id_el is None:
            continue
        published = pub_el.text[:10]
        try:
            pub_dt = datetime.strptime(published, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if pub_dt < since:
            continue
        # id like http://arxiv.org/abs/2505.13933v1 → 2505.13933
        raw_id = (id_el.text or "").rsplit("/", 1)[-1]
        arxiv_id = raw_id.split("v")[0]
        primary = ""
        pc = e.find("{http://arxiv.org/schemas/atom}primary_category")
        if pc is not None:
            primary = pc.get("term", "")
        title = " ".join((title_el.text or "").split())
        summary = " ".join((summ_el.text or "").split()) if summ_el is not None else ""
        out.append({
            "arxiv_id": arxiv_id,
            "title": title,
            "published": published,
            "primary_category": primary,
            "abstract_snippet": summary[:260],
            "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}",
            "matched_axis": axis,
        })
    return out


def _existing_ids() -> set[str]:
    """已出現在 research_program.md 的 arxiv id（去重用）。"""
    if not RESEARCH_PROGRAM.exists():
        return set()
    import re
    text = RESEARCH_PROGRAM.read_text(encoding="utf-8")
    return set(re.findall(r"\b\d{4}\.\d{4,5}\b", text))


def scan(*, days: int, max_per_axis: int) -> dict:
    from datetime import timedelta
    # 不能用 argless datetime.now() 在某些 runtime；這裡是真實腳本（非 workflow），允許。
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    seen_ids = _existing_ids()
    found: dict[str, dict] = {}
    for axis, terms in AXES:
        q = f"({CATEGORIES}) AND (abs:{terms})" if " OR " in terms else f"({CATEGORIES}) AND abs:{terms}"
        raw = _fetch(q, max_per_axis)
        if raw:
            for c in _parse(raw, axis, since):
                # 同一論文多軸命中 → 保留首見軸
                found.setdefault(c["arxiv_id"], c)
        time.sleep(3)  # arXiv 政策：每 3 秒 1 request
    new = [c for c in found.values() if c["arxiv_id"] not in seen_ids]
    new.sort(key=lambda c: c["published"], reverse=True)
    return {
        "scanned_at": now.isoformat(),
        "categories": CATEGORIES,
        "days": days,
        "total_found": len(found),
        "new_count": len(new),
        "candidates": new,
    }


def _to_markdown(result: dict) -> str:
    date = result["scanned_at"][:10]
    lines = [f"### 新發現（{date} arXiv 自動掃描，scan_arxiv_topics.py）", ""]
    if not result["candidates"]:
        lines.append("（本次掃描無新論文 — 既有 research_program 已覆蓋，或 API 暫時限流）")
        return "\n".join(lines)
    for c in result["candidates"]:
        lines.append(
            f"- **{c['title']}** (arXiv:{c['arxiv_id']}, {c['published']}, "
            f"{c['primary_category']}) [{c['matched_axis']}]"
        )
        lines.append(f"  - {c['abstract_snippet']}")
        lines.append(f"  - {c['pdf_url']}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30, help="只取最近 N 天投稿（預設 30）")
    ap.add_argument("--max", type=int, default=6, help="每個研究軸最多取 N 篇（預設 6）")
    ap.add_argument("--markdown", action="store_true", help="輸出 research_program.md 可貼區塊")
    args = ap.parse_args()

    result = scan(days=args.days, max_per_axis=args.max)
    if args.markdown:
        print(_to_markdown(result))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
