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
import re
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
# RSS 是 PRIMARY source（2026-05-29）：export API query 端點對本機 IP 持續
# 429，但 per-category RSS feed（專為輪詢設計）穩定可用。RSS 給「最新公告批次」
# (new + cross + replace)，正好適合週期掃描。export API 留作 --source api fallback。
RSS_BASE = "https://rss.arxiv.org/rss"
RSS_CATEGORIES = ["q-fin.ST", "q-fin.RM", "q-fin.PM", "q-fin.TR"]
USER_AGENT = "VolPred-Research/1.0 (mailto:yihao.lai@gmail.com)"
_ATOM = {"a": "http://www.w3.org/2005/Atom"}

# 對齊 research_program.md 研究面向：每軸一組小寫關鍵詞（client-side 比對 RSS
# 的 title+abstract）+ 標籤。標籤回填到 candidate.matched_axis 方便注入歸面向。
# RSS 無法 server-side 搜尋，故改為本地子字串比對；用戶 copula 專長也納入。
AXES: list[tuple[str, list[str]]] = [
    ("面向A_波動率預測", ["volatility forecast", "realized volatility", "realised volatility", "garch", "har-rv", "har model"]),
    ("面向B_風險管理", ["value-at-risk", "value at risk", "expected shortfall", "tail risk", "var model"]),
    ("面向I_期貨避險", ["hedging", "hedge ratio", "minimum variance hedge", "futures hedge"]),
    ("面向_copula", ["copula", "dependence structure", "tail dependence"]),
    ("前沿_rough_vol", ["rough volatility", "hurst", "fractional volatility", "fractional brownian"]),
    ("前沿_ML_GARCH", ["machine learning volatil", "neural network", "deep learning", "autoencoder", "transformer", "reservoir computing"]),
    ("前沿_jump_tail", ["jump diffusion", "conformal prediction", "jump variation", "extreme value"]),
]
# export API fallback 用的 cat 限縮字串。
CATEGORIES = "cat:q-fin.ST OR cat:q-fin.RM OR cat:q-fin.PM OR cat:q-fin.TR"


def _match_axis(title: str, abstract: str) -> str | None:
    """回傳第一個命中的研究軸標籤；無命中回 None。"""
    hay = (title + " " + abstract).lower()
    for axis, kws in AXES:
        if any(kw in hay for kw in kws):
            return axis
    return None


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


def _fetch_rss(category: str, *, retries: int = 3) -> bytes | None:
    """抓 per-category RSS feed（PRIMARY）。429 指數退避。失敗回 None。"""
    url = f"{RSS_BASE}/{category}"
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
            print(f"  [scan_arxiv] RSS HTTP {exc.code} for {category}", file=sys.stderr)
            return None
        except Exception as exc:  # noqa: BLE001
            print(f"  [scan_arxiv] RSS {type(exc).__name__} for {category}: {exc}", file=sys.stderr)
            return None
    return None


# RSS description 形如 "arXiv:2605.29413v1 Announce Type: cross Abstract: <text>"
_ABSTRACT_RE = re.compile(r"Abstract:\s*(.*)", re.DOTALL)
_ID_IN_DESC_RE = re.compile(r"arXiv:(\d{4}\.\d{4,5})")


def _parse_rss(raw: bytes, *, include_replace: bool = False) -> list[dict]:
    """解析 RSS feed → candidate dict list（已套用研究軸關鍵詞過濾）。"""
    out: list[dict] = []
    head = raw[:4096].lower()
    if b"<!doctype" in head or b"<!entity" in head:
        print("  [scan_arxiv] RSS refused: DTD/entity in response", file=sys.stderr)
        return out
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return out
    atom_announce = "{http://arxiv.org/schemas/atom}announce_type"
    for it in root.findall(".//item"):
        title_el = it.find("title")
        link_el = it.find("link")
        desc_el = it.find("description")
        if title_el is None or link_el is None:
            continue
        title = " ".join((title_el.text or "").split())
        desc_raw = " ".join((desc_el.text or "").split()) if desc_el is not None else ""
        # announce_type: new / cross / replace — replace 是舊論文更新版，預設略過
        ann_el = it.find(atom_announce)
        ann = (ann_el.text or "").strip() if ann_el is not None else ""
        if ann == "replace" and not include_replace:
            continue
        # arxiv id：優先 link，退而求其次 description
        arxiv_id = (link_el.text or "").rsplit("/", 1)[-1].split("v")[0]
        if not re.fullmatch(r"\d{4}\.\d{4,5}", arxiv_id):
            m = _ID_IN_DESC_RE.search(desc_raw)
            arxiv_id = m.group(1) if m else ""
        if not arxiv_id:
            continue
        m = _ABSTRACT_RE.search(desc_raw)
        abstract = m.group(1).strip() if m else desc_raw
        axis = _match_axis(title, abstract)
        if axis is None:
            continue  # 不在任何研究軸 → 跳過
        cats = [c.text for c in it.findall("category") if c.text]
        pub_el = it.find("pubDate")
        published = (pub_el.text or "")[:16] if pub_el is not None else ""
        out.append({
            "arxiv_id": arxiv_id,
            "title": title,
            "published": published,
            "primary_category": cats[0] if cats else "",
            "announce_type": ann,
            "abstract_snippet": abstract[:280],
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


def scan(*, source: str = "rss", days: int = 30, max_per_axis: int = 6,
         include_replace: bool = False) -> dict:
    """掃 arXiv q-fin 新論文。source='rss'（預設，本機可靠）或 'api'（fallback）。"""
    now = datetime.now(timezone.utc)
    seen_ids = _existing_ids()
    found: dict[str, dict] = {}

    if source == "rss":
        for cat in RSS_CATEGORIES:
            raw = _fetch_rss(cat)
            if raw:
                for c in _parse_rss(raw, include_replace=include_replace):
                    found.setdefault(c["arxiv_id"], c)
            time.sleep(3)  # arXiv 政策：每 3 秒 1 request
        src_label = f"RSS:{','.join(RSS_CATEGORIES)}"
    else:  # api fallback
        from datetime import timedelta
        since = now - timedelta(days=days)
        for axis, kws in AXES:
            terms = " OR ".join(kws[:3])
            q = f"({CATEGORIES}) AND (abs:{terms})"
            raw = _fetch(q, max_per_axis)
            if raw:
                for c in _parse(raw, axis, since):
                    found.setdefault(c["arxiv_id"], c)
            time.sleep(3)
        src_label = CATEGORIES

    new = [c for c in found.values() if c["arxiv_id"] not in seen_ids]
    new.sort(key=lambda c: c.get("published", ""), reverse=True)
    return {
        "scanned_at": now.isoformat(),
        "source": src_label,
        "total_found": len(found),
        "new_count": len(new),
        "candidates": new,
    }


def _to_markdown(result: dict) -> str:
    date = result["scanned_at"][:10]
    lines = [f"### 新發現（{date} arXiv 自動掃描，scan_arxiv_topics.py）", ""]
    if not result["candidates"]:
        lines.append("（本次掃描無命中研究軸的新論文 — 既有 research_program 已覆蓋，或本批公告無相關題）")
        return "\n".join(lines)
    for c in result["candidates"]:
        lines.append(
            f"- **{c['title']}** (arXiv:{c['arxiv_id']}, {c['published']}, "
            f"{c['primary_category']}) [{c['matched_axis']}]"
        )
        lines.append(f"  - {c['abstract_snippet']}")
        lines.append(f"  - {c['pdf_url']}")
    return "\n".join(lines)


STAGING = ROOT / "storage" / "research" / "arxiv_candidates.json"


def write_staging(result: dict) -> dict:
    """合併本次掃描結果到 staging 候選池（dedup by arxiv_id，保留 first_seen）。

    Phase 2 設計：scanner（cron）只 seed 候選到 staging，**不自動寫 research_program
    北極星檔**（避免 axis matcher 邊際命中污染研究方向）。主線程選題時 review
    staging、把真正相關的 promote 到 research_program + seed experiment。
    狀態 status: new（待 review）→ reviewed/promoted/rejected（主線程更新）。
    """
    STAGING.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if STAGING.exists():
        try:
            for c in json.loads(STAGING.read_text(encoding="utf-8")).get("candidates", []):
                existing[c["arxiv_id"]] = c
        except (json.JSONDecodeError, KeyError):
            pass
    added = 0
    for c in result["candidates"]:
        aid = c["arxiv_id"]
        if aid in existing:
            continue  # 已在池中，保留原 first_seen/status
        existing[aid] = {**c, "first_seen": result["scanned_at"], "status": "new"}
        added += 1
    payload = {
        "updated_at": result["scanned_at"],
        "total": len(existing),
        "new_this_run": added,
        "candidates": sorted(existing.values(),
                             key=lambda c: c.get("first_seen", ""), reverse=True),
    }
    tmp = STAGING.with_name(f".{STAGING.name}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STAGING)
    return {"added": added, "total": len(existing)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["rss", "api"], default="rss",
                    help="rss=per-category RSS（預設，本機可靠）/ api=export query（fallback）")
    ap.add_argument("--days", type=int, default=30, help="api 模式：只取最近 N 天投稿")
    ap.add_argument("--max", type=int, default=6, help="api 模式：每軸最多 N 篇")
    ap.add_argument("--include-replace", action="store_true", help="rss 模式：含 replace（舊論文更新版）")
    ap.add_argument("--markdown", action="store_true", help="輸出 research_program.md 可貼區塊")
    ap.add_argument("--write-staging", action="store_true",
                    help="合併結果到 storage/research/arxiv_candidates.json（cron 用）")
    args = ap.parse_args()

    result = scan(source=args.source, days=args.days, max_per_axis=args.max,
                  include_replace=args.include_replace)
    if args.write_staging:
        st = write_staging(result)
        print(f"[scan_arxiv] staging 更新：新增 {st['added']} 候選，池中共 {st['total']}",
              file=sys.stderr)
    if args.markdown:
        print(_to_markdown(result))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
