#!/usr/bin/env python3
"""Reader-preference analysis engine (Phase 1) — 讀者偏好自動化歸納.

Owner directive 2026-07-15: 自主研究平台要自動化分析讀者偏好（議題、論述、文字風格、
圖片、表格等角度），歸納成未來運營（選題、圖文表使用）的參考。

它做什麼
--------
把「文章特徵」× 「讀者互動」做對照，找出**傾向訊號**（非因果）：例如有表格 vs 無表格的
中位觀看數、問句標題 vs 直述、各系列、各 tag、圖表數 bucket 等。輸出兩個檔：

    storage/analytics/reader_preferences.json         (機器可讀，供 build_publication_candidates 加分)
    storage/analytics/reader_preferences_report.md    (人讀，含合格結論 + 樣本不足清單 + 建議)

資料來源
--------
- 互動：Supabase `article_impressions`（views / read_time_sec / user_id — 會員 vs 匿名）
  + `article_reactions`（like / bookmark / share）。讀法與 outlier / bounce 口徑重用
  `scripts/pull_reader_metrics.py`（同一 SUPABASE_URL/KEY env + `_paged_select` 分頁 + 同樣的
  BOUNCE / OUTLIER cap 常數），避免兩支 script 對「一次有效閱讀」有不同定義。
- 文章特徵：本地 canonical `storage/reports/<slug>.json`（逐篇讀）。缺檔時 fallback 到
  `feed.json` 內同 id 的 entry（同樣帶 title/tags/audience/content），並 warn 記錄，
  不 silent（見 `.claude/rules/no-silent-fallback.md`）。

研究誠實硬約束（違反 = 任務失敗，見 CLAUDE.md 研究誠實原則）
-----------------------------------------------------------
全站互動量極小（~1,500 impressions，多數文章 1–3 views）。因此：
  1. 每個 bucket 必附樣本數（篇數 + impressions）。
  2. bucket 篇數 < MIN_ARTICLES(10) 或 impressions < MIN_IMPRESSIONS(30) → 標
     `insufficient_sample`，**不得**進「合格結論」區，只列在樣本不足清單。
  3. 對比一律用 **median**（重尾分佈，mean 會被單一 outlier 帶走）。
  4. 輸出明寫「傾向訊號，非因果」；絕不編造顯著性 / p-value。
  5. read_time 是 proxy（無「讀完」欄位），沿用 pull_reader_metrics 的 proxy 標記。

模組結構（DB 與純函式分離，讓 hermetic 測試不必打真 DB）
--------------------------------------------------------
- `extract_features(article)`、`bucket_labels(features)`、`aggregate_buckets(...)`、
  `build_outputs(...)` 全是純函式，import 本模組不會觸發任何 Supabase / .env.local 讀取。
- Supabase client 與 pull_reader_metrics 的 import 都是 **lazy**（在 `main()` / fetch 內），
  所以測試 `import analyze_reader_preferences` 不需要憑證，也不會誤讀 production `.env.local`
  （error_log §P 教訓）。

Usage:
  uv run python scripts/analyze_reader_preferences.py --days 365
  uv run python scripts/analyze_reader_preferences.py --days 365 --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ANALYTICS_DIR = ROOT / "storage" / "analytics"
REPORTS_DIR = ROOT / "storage" / "reports"
FEED_PATH = REPORTS_DIR / "feed.json"
JSON_OUT = ANALYTICS_DIR / "reader_preferences.json"
MD_OUT = ANALYTICS_DIR / "reader_preferences_report.md"

# --- Sample-size gate (research-honesty hard constraint) -------------------
MIN_ARTICLES = 10       # a bucket needs >=10 distinct articles-with-activity ...
MIN_IMPRESSIONS = 30    # ... AND >=30 total impressions to be a "qualified" bucket.

# --- read_time proxy thresholds (mirror pull_reader_metrics.py) ------------
# Kept as local defaults so the pure functions never need to import the DB
# module; main() imports the canonical values from pull_reader_metrics and
# asserts they still match, so a future edit there can't silently drift us.
BOUNCE_THRESHOLD_SEC = 5
MAX_READ_TIME_SEC = 1200
ENGAGED_THRESHOLD_SEC = 30

CONCLUSION_CAVEAT = "傾向訊號，非因果（觀察性關聯，樣本小；勿當作 A/B 因果證據）"

# Series prefixes the platform actively runs (matched as a title substring).
# Order matters only for display; each article maps to exactly one series.
SERIES_MARKERS: list[tuple[str, str]] = [
    ("迷思實驗室", "迷思實驗室"),
    ("事件溫度計", "事件溫度計"),
    ("無人載具", "無人載具"),
    ("每日策略", "每日策略"),
    ("會員提問", "會員提問"),
]

# Markdown table separator row, e.g. `| --- | :--: |`. Exactly one per table
# block, so counting these counts tables robustly regardless of column count.
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$", re.MULTILINE)
_KID_RE = re.compile(r"\bK\d{2,}\b", re.IGNORECASE)
_DIGIT_RE = re.compile(r"\d")


# ---------------------------------------------------------------------------
# Feature extraction (pure)
# ---------------------------------------------------------------------------
def _series_of(title: str) -> str:
    for needle, label in SERIES_MARKERS:
        if needle in title:
            return label
    return "無系列"


def _bucket_len(n: int, small: int, big: int, labels=("短", "中", "長")) -> str:
    if n < small:
        return labels[0]
    if n <= big:
        return labels[1]
    return labels[2]


def _chart_bucket(n: int) -> str:
    if n <= 0:
        return "0"
    if n <= 2:
        return "1-2"
    return "3+"


def _table_bucket(n: int) -> str:
    if n <= 0:
        return "0"
    if n == 1:
        return "1"
    return "2+"


def extract_features(article: dict) -> dict:
    """Pure feature extractor from a report/feed article dict.

    Never raises on missing fields — a partially-populated article just yields
    empty/default features. Returns a dict of scalar feature values.
    """
    title = str(article.get("title") or "")
    content = str(article.get("content") or "")
    audience = str(article.get("audience") or "").strip() or "general"
    tags = [str(t).strip() for t in (article.get("tags") or []) if str(t).strip()]
    details = article.get("details") if isinstance(article.get("details"), dict) else {}

    chart_count = content.count("![")
    charts_meta = details.get("charts")
    if isinstance(charts_meta, list) and len(charts_meta) > chart_count:
        # details.charts is the structured render manifest; if it lists more
        # charts than the markdown embeds (some renderers attach figures out of
        # band) trust the larger, non-fabricated count.
        chart_count = len(charts_meta)
    table_count = len(_TABLE_SEP_RE.findall(content))

    has_lazypack = ("懶人包" in content) or ("懶人包" in title) or bool(details.get("lazypack"))

    experiment_refs = details.get("experiment_refs") if isinstance(details.get("experiment_refs"), list) else []
    is_research = bool(experiment_refs) or bool(_KID_RE.search(title)) or any(_KID_RE.search(t) for t in tags)

    title_stripped = title.rstrip()
    return {
        "audience": audience,
        "series": _series_of(title),
        "tags": tags,
        "title_is_question": ("？" in title) or ("?" in title),
        "title_has_number": bool(_DIGIT_RE.search(title)),
        "title_has_exclamation": ("！" in title) or title_stripped.endswith("!"),
        "title_len_bucket": _bucket_len(len(title), 20, 35),
        "content_len_bucket": _bucket_len(len(content), 1500, 3500),
        "chart_count": chart_count,
        "chart_bucket": _chart_bucket(chart_count),
        "table_count": table_count,
        "table_bucket": _table_bucket(table_count),
        "has_table": table_count > 0,
        "has_lazypack": has_lazypack,
        "research_vs_narrative": "research" if is_research else "narrative",
    }


def _yn(value: bool) -> str:
    return "yes" if value else "no"


# Single-valued dimensions: article -> exactly one bucket label.
# (label, human title, feature-key -> bucket-label function)
SINGLE_DIMENSIONS: list[tuple[str, str, str]] = [
    ("audience", "受眾（audience）", "audience"),
    ("series", "系列", "series"),
    ("title_is_question", "問句標題 vs 直述", "title_is_question"),
    ("title_has_number", "標題含數字 vs 無", "title_has_number"),
    ("title_has_exclamation", "標題含驚嘆 vs 無", "title_has_exclamation"),
    ("title_len_bucket", "標題長度", "title_len_bucket"),
    ("content_len_bucket", "內文長度", "content_len_bucket"),
    ("chart_bucket", "圖表數", "chart_bucket"),
    ("table_bucket", "表格數", "table_bucket"),
    ("has_lazypack", "有無懶人包", "has_lazypack"),
    ("research_vs_narrative", "研究文（K-id）vs 敘事文", "research_vs_narrative"),
]


def bucket_labels(features: dict) -> dict[str, str]:
    """Map an article's features to {single_dimension: bucket_label}."""
    out: dict[str, str] = {}
    for dim_key, _title, feat_key in SINGLE_DIMENSIONS:
        val = features.get(feat_key)
        out[dim_key] = _yn(val) if isinstance(val, bool) else str(val)
    return out


# ---------------------------------------------------------------------------
# Aggregation (pure)
# ---------------------------------------------------------------------------
def _median(values: list) -> float | None:
    vals = [v for v in values if v is not None]
    return round(statistics.median(vals), 2) if vals else None


def _bucket_metrics(rows: list[dict]) -> dict:
    """Aggregate engagement metrics over a list of per-article records.

    Each record: {views, median_read_time, reactions_total, impressions,
    member_impressions}. `views == impressions` (one impression row = one view).
    """
    n_articles = len(rows)
    total_impressions = sum(int(r.get("impressions") or 0) for r in rows)
    member_impr = sum(int(r.get("member_impressions") or 0) for r in rows)
    sample_ok = n_articles >= MIN_ARTICLES and total_impressions >= MIN_IMPRESSIONS
    return {
        "n_articles": n_articles,
        "total_impressions": total_impressions,
        "median_views_per_article": _median([r.get("views") for r in rows]),
        "median_read_time_sec": _median([r.get("median_read_time") for r in rows]),
        "median_reactions_per_article": _median([r.get("reactions_total") for r in rows]),
        "member_impression_share": (round(member_impr / total_impressions, 4) if total_impressions else None),
        "read_time_is_proxy": True,
        "sample_ok": sample_ok,
        "insufficient_sample": not sample_ok,
    }


def aggregate_buckets(records: list[dict]) -> dict:
    """Group per-article records into single-valued + tag dimensions.

    `records`: list of {"slug", "features": {...}, "views", "median_read_time",
    "reactions_total", "impressions", "member_impressions"}.
    Returns {dim_key: {"title", "buckets": {label: metrics}}}.
    """
    dims: dict[str, dict] = {}
    for dim_key, dim_title, _feat in SINGLE_DIMENSIONS:
        dims[dim_key] = {"title": dim_title, "kind": "single", "buckets": {}}

    grouped: dict[str, dict[str, list]] = {d[0]: {} for d in SINGLE_DIMENSIONS}
    tag_groups: dict[str, list] = {}

    for rec in records:
        feats = rec.get("features") or {}
        labels = bucket_labels(feats)
        for dim_key, label in labels.items():
            grouped[dim_key].setdefault(label, []).append(rec)
        for tag in feats.get("tags") or []:
            tag_groups.setdefault(tag, []).append(rec)

    for dim_key in grouped:
        for label, rows in grouped[dim_key].items():
            dims[dim_key]["buckets"][label] = _bucket_metrics(rows)

    # Tag dimension: keep only tags that reach the article threshold so the
    # output isn't flooded with 1-article tag buckets (they'd all be
    # insufficient anyway). Below-threshold tags are summarised, not fabricated.
    tag_buckets: dict[str, dict] = {}
    tags_below_threshold = 0
    for tag, rows in tag_groups.items():
        if len(rows) >= MIN_ARTICLES:
            tag_buckets[tag] = _bucket_metrics(rows)
        else:
            tags_below_threshold += 1
    dims["tag"] = {
        "title": "主題標籤（tag，多值）",
        "kind": "multi",
        "buckets": tag_buckets,
        "tags_below_article_threshold": tags_below_threshold,
    }
    return dims


def _qualifying(buckets: dict) -> dict:
    return {lbl: m for lbl, m in buckets.items() if m.get("sample_ok")}


def build_conclusions(dims: dict) -> tuple[list[dict], list[dict]]:
    """Derive qualified conclusions + the insufficient-sample list.

    A conclusion is only emitted when a dimension has >=2 qualifying buckets,
    comparing the highest vs lowest median_views_per_article among them. Every
    conclusion carries both buckets' sample sizes and the non-causal caveat.
    """
    conclusions: list[dict] = []
    insufficient: list[dict] = []

    for dim_key, dim in dims.items():
        buckets = dim.get("buckets") or {}
        for label, m in buckets.items():
            if not m.get("sample_ok"):
                insufficient.append({
                    "dimension": dim_key,
                    "dimension_title": dim.get("title"),
                    "bucket": label,
                    "n_articles": m.get("n_articles"),
                    "total_impressions": m.get("total_impressions"),
                })
        qual = _qualifying(buckets)
        # Need >=2 qualifying buckets with a defined median_views to contrast.
        scored = {
            lbl: m for lbl, m in qual.items()
            if m.get("median_views_per_article") is not None
        }
        if len(scored) < 2:
            continue
        hi = max(scored.items(), key=lambda kv: kv[1]["median_views_per_article"])
        lo = min(scored.items(), key=lambda kv: kv[1]["median_views_per_article"])
        if hi[0] == lo[0]:
            continue
        conclusions.append({
            "dimension": dim_key,
            "dimension_title": dim.get("title"),
            "metric": "median_views_per_article",
            "higher_bucket": hi[0],
            "higher_value": hi[1]["median_views_per_article"],
            "higher_sample": {"n_articles": hi[1]["n_articles"], "total_impressions": hi[1]["total_impressions"]},
            "lower_bucket": lo[0],
            "lower_value": lo[1]["median_views_per_article"],
            "lower_sample": {"n_articles": lo[1]["n_articles"], "total_impressions": lo[1]["total_impressions"]},
            "delta": round(hi[1]["median_views_per_article"] - lo[1]["median_views_per_article"], 2),
            "qualifying_buckets": len(scored),
            "caveat": CONCLUSION_CAVEAT,
        })
    return conclusions, insufficient


# ---------------------------------------------------------------------------
# Output assembly (pure)
# ---------------------------------------------------------------------------
def build_outputs(records: list[dict], meta: dict) -> tuple[dict, str]:
    """Assemble the machine JSON and the human Markdown report. Pure."""
    dims = aggregate_buckets(records)
    conclusions, insufficient = build_conclusions(dims)

    total_impr = sum(int(r.get("impressions") or 0) for r in records)
    member_impr = sum(int(r.get("member_impressions") or 0) for r in records)

    payload = {
        "generated_at": meta.get("generated_at"),
        "window_days": meta.get("window_days"),
        "since_date": meta.get("since_date"),
        "gate": {"min_articles": MIN_ARTICLES, "min_impressions": MIN_IMPRESSIONS},
        "totals": {
            "articles_with_activity": len(records),
            "total_impressions": total_impr,
            "member_impression_share_overall": (round(member_impr / total_impr, 4) if total_impr else None),
        },
        "data_source_errors": meta.get("data_source_errors", {}),
        "feature_source_counts": meta.get("feature_source_counts", {}),
        "methodology_notes": {
            "signal_is_directional_not_causal": True,
            "caveat": CONCLUSION_CAVEAT,
            "comparison_statistic": "median (heavy-tailed engagement; mean excluded)",
            "read_time_is_proxy": True,
            "read_time_bounce_filter_sec": BOUNCE_THRESHOLD_SEC,
            "read_time_outlier_cap_sec": MAX_READ_TIME_SEC,
            "engaged_threshold_sec": ENGAGED_THRESHOLD_SEC,
            "member_definition": "impression with non-null user_id = member; null = anonymous",
            "sample_gate": f"bucket needs >={MIN_ARTICLES} articles AND >={MIN_IMPRESSIONS} impressions to qualify",
        },
        "dimensions": dims,
        "qualified_conclusions": conclusions,
        "insufficient_samples": insufficient,
    }
    md = _render_markdown(payload)
    return payload, md


def _render_markdown(payload: dict) -> str:
    L: list[str] = []
    L.append("# 讀者偏好分析報告（Phase 1）")
    L.append("")
    L.append(f"- 產生時間：{payload.get('generated_at')}")
    L.append(f"- 視窗：近 {payload.get('window_days')} 天（自 {payload.get('since_date')}）")
    t = payload.get("totals", {})
    L.append(f"- 有互動的文章數：{t.get('articles_with_activity')}；總 impressions：{t.get('total_impressions')}")
    L.append(f"- 會員 impression 佔比：{t.get('member_impression_share_overall')}")
    gate = payload.get("gate", {})
    L.append(f"- 合格門檻：bucket 需 ≥{gate.get('min_articles')} 篇 **且** ≥{gate.get('min_impressions')} impressions")
    L.append("")
    L.append(f"> ⚠️ {payload.get('methodology_notes', {}).get('caveat')}")
    L.append("> read_time 為 proxy（無「讀完」欄位），已做 bounce 過濾與 outlier 上限。")
    L.append("")

    conclusions = payload.get("qualified_conclusions") or []
    L.append("## 合格結論（樣本足夠的傾向訊號）")
    L.append("")
    if not conclusions:
        L.append("_目前沒有任何維度達到合格樣本門檻 —— 全站互動量仍太小。這是誠實的空結果，"
                 "不是失敗；隨著流量累積會逐步出現合格結論。_")
    else:
        for c in conclusions:
            hs, ls = c["higher_sample"], c["lower_sample"]
            L.append(
                f"- **{c['dimension_title']}**：`{c['higher_bucket']}` 的中位觀看數"
                f"（{c['higher_value']}，n={hs['n_articles']} 篇 / {hs['total_impressions']} impr）"
                f" 高於 `{c['lower_bucket']}`"
                f"（{c['lower_value']}，n={ls['n_articles']} 篇 / {ls['total_impressions']} impr）"
                f"，Δ={c['delta']}。"
            )
        L.append("")
        L.append(f"_{CONCLUSION_CAVEAT}_")
    L.append("")

    L.append("## 給運營的建議（選題 / 圖文表使用）")
    L.append("")
    if not conclusions:
        L.append("- 尚無足夠樣本支撐具體建議。維持既有選題節奏，持續累積互動數據。")
    else:
        for c in conclusions:
            L.append(
                f"- 「{c['dimension_title']}」維度：在其他條件相近時，可**優先嘗試** "
                f"`{c['higher_bucket']}`（目前中位觀看較高，Δ={c['delta']}）；"
                f"仍需更多樣本才能確認，勿當硬規則。"
            )
    L.append("")

    insufficient = payload.get("insufficient_samples") or []
    L.append(f"## 樣本不足清單（{len(insufficient)} 個 bucket，未進結論）")
    L.append("")
    if not insufficient:
        L.append("_無。_")
    else:
        L.append("| 維度 | bucket | 篇數 | impressions |")
        L.append("| --- | --- | ---: | ---: |")
        for r in insufficient:
            L.append(f"| {r.get('dimension_title') or r.get('dimension')} | {r['bucket']} | "
                     f"{r.get('n_articles')} | {r.get('total_impressions')} |")
    L.append("")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# I/O (impure) — Supabase + local files
# ---------------------------------------------------------------------------
def _load_feed_index() -> dict[str, dict]:
    """slug -> feed entry, used only as a fallback when a report file is absent.

    build_publication_candidates.py reads feed.json in full the same way; the
    'no whole-file feed.json read' rule is a main-thread context/token rule, not
    a ban on scripts parsing their own canonical store.
    """
    if not FEED_PATH.exists():
        return {}
    try:
        feed = json.loads(FEED_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        from volpred.ops.diagnostics import warn
        warn("analyze_reader_preferences", "feed.json unreadable, no feature fallback", err=str(exc))
        return {}
    return {e.get("id"): e for e in feed if isinstance(e, dict) and e.get("id")}


def load_article_features(slug: str, feed_index: dict[str, dict]) -> tuple[dict | None, str]:
    """Return (features, source) for a slug. source in {report, feed, missing}."""
    report_path = REPORTS_DIR / f"{slug}.json"
    if report_path.exists():
        try:
            article = json.loads(report_path.read_text(encoding="utf-8"))
            return extract_features(article), "report"
        except (OSError, json.JSONDecodeError) as exc:
            from volpred.ops.diagnostics import warn
            warn("analyze_reader_preferences", "report unreadable, trying feed fallback",
                 slug=slug, err=str(exc))
    entry = feed_index.get(slug)
    if entry is not None:
        return extract_features(entry), "feed"
    return None, "missing"


def fetch_engagement(since_date: str, since_iso: str):
    """Pull impressions (with user_id) + reactions from Supabase.

    Lazy-imports the DB layer so `import analyze_reader_preferences` stays
    credential-free for hermetic tests.
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    sys.path.insert(0, str(ROOT / "src"))
    import pull_reader_metrics as prm  # noqa: E402  reuse client + outlier/bounce caps

    # Guard against silent drift between the two scripts' read-time definitions.
    assert prm.BOUNCE_THRESHOLD_SEC == BOUNCE_THRESHOLD_SEC, "bounce threshold drift vs pull_reader_metrics"
    assert prm.MAX_READ_TIME_SEC == MAX_READ_TIME_SEC, "outlier cap drift vs pull_reader_metrics"

    impressions, impr_err = prm._paged_select(
        "article_impressions", "article_id,impression_date,read_time_sec,user_id",
        f"impression_date=gte.{since_date}",
    )
    reactions, react_err = prm.fetch_reactions(since_iso)
    return impressions, reactions, impr_err, react_err, prm


def aggregate_by_article(impressions: list[dict], reactions: list[dict], uuid_to_slug: dict[str, str]) -> dict[str, dict]:
    """Per-slug engagement aggregate, applying the shared read-time filtering."""
    per: dict[str, dict] = {}

    def bucket(slug: str) -> dict:
        return per.setdefault(slug, {
            "impressions": 0, "member_impressions": 0, "read_times": [],
            "outliers_excluded": 0, "reactions": {"like": 0, "bookmark": 0, "share": 0},
        })

    for row in impressions:
        aid = row.get("article_id")
        slug = uuid_to_slug.get(aid)
        if not slug:
            continue
        b = bucket(slug)
        b["impressions"] += 1
        if row.get("user_id"):
            b["member_impressions"] += 1
        rt = row.get("read_time_sec")
        if isinstance(rt, (int, float)) and rt > BOUNCE_THRESHOLD_SEC:
            if rt <= MAX_READ_TIME_SEC:
                b["read_times"].append(rt)
            else:
                b["outliers_excluded"] += 1

    for row in reactions:
        aid = row.get("article_id")
        slug = uuid_to_slug.get(aid)
        reaction = row.get("reaction")
        if not slug or reaction not in ("like", "bookmark", "share"):
            continue
        bucket(slug)["reactions"][reaction] += 1

    return per


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=365,
                    help="lookback window in days (default 365 — small reader base needs a wide window)")
    ap.add_argument("--dry-run", action="store_true", help="print summary only; do not write output files")
    args = ap.parse_args(argv)

    now = datetime.now(timezone.utc)
    since_date = (now - timedelta(days=args.days)).date().isoformat()
    since_iso = f"{since_date}T00:00:00+00:00"

    impressions, reactions, impr_err, react_err, prm = fetch_engagement(since_date, since_iso)
    if not prm.SUPABASE_URL or not prm.SUPABASE_KEY:
        print("ERROR: missing SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY (checked env + .env.local)", file=sys.stderr)
        return 1

    uuid_to_slug = {aid: (m.get("slug") or "") for aid, m in
                    prm.fetch_article_meta(list({r.get("article_id") for r in impressions if r.get("article_id")})).items()}
    per = aggregate_by_article(impressions, reactions, uuid_to_slug)

    feed_index = _load_feed_index()
    records: list[dict] = []
    source_counts = {"report": 0, "feed": 0, "missing": 0}
    for slug, b in per.items():
        if not slug:
            continue
        features, source = load_article_features(slug, feed_index)
        source_counts[source] += 1
        if features is None:
            continue  # no features to bucket by; already counted as 'missing'
        reactions_total = b["reactions"]["like"] + b["reactions"]["bookmark"]
        records.append({
            "slug": slug,
            "features": features,
            "views": b["impressions"],
            "impressions": b["impressions"],
            "member_impressions": b["member_impressions"],
            "median_read_time": (round(statistics.median(b["read_times"]), 2) if b["read_times"] else None),
            "reactions_total": reactions_total,
        })

    meta = {
        "generated_at": now.isoformat(),
        "window_days": args.days,
        "since_date": since_date,
        "data_source_errors": {"article_impressions": impr_err, "article_reactions": react_err},
        "feature_source_counts": source_counts,
    }
    payload, md = build_outputs(records, meta)

    n_conc = len(payload["qualified_conclusions"])
    n_insuf = len(payload["insufficient_samples"])
    print(f"[reader_preferences] window={since_date}..today  impressions={len(impressions)} "
          f"reactions={len(reactions)}  articles_with_features={len(records)} "
          f"(report={source_counts['report']} feed={source_counts['feed']} missing={source_counts['missing']})")
    print(f"[reader_preferences] qualified_conclusions={n_conc}  insufficient_buckets={n_insuf}")
    for c in payload["qualified_conclusions"]:
        print(f"    + {c['dimension']}: {c['higher_bucket']}({c['higher_value']}) > "
              f"{c['lower_bucket']}({c['lower_value']}) Δ={c['delta']}")

    if args.dry_run:
        print("[reader_preferences] --dry-run: not writing output files")
        return 0

    ANALYTICS_DIR.mkdir(parents=True, exist_ok=True)
    _write_atomic(JSON_OUT, json.dumps(payload, ensure_ascii=False, indent=2))
    _write_atomic(MD_OUT, md)
    print(f"[reader_preferences] wrote {JSON_OUT}")
    print(f"[reader_preferences] wrote {MD_OUT}")

    if impr_err and react_err and not records:
        print("[reader_preferences] BLOCKED: both source tables failed and no records built", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
