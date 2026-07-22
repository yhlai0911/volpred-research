#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
STORAGE = ROOT / "storage"
OPS = STORAGE / "ops"
NEXT_TASKS = STORAGE / "next_tasks.json"
STATE_PATH = OPS / "daily_reader_facing_scan_state.json"
TRENDING_LOG = STORAGE / "reports" / "trending_repost_log.json"
FEED_PATH = STORAGE / "reports" / "feed.json"
RUNTIME_SCHEDULES = ROOT / "config" / "runtime_schedules.json"
LOCAL_TZ = ZoneInfo("Asia/Taipei")
TRENDING_SCAN_CMD_ENV = "VOLPRED_TRENDING_SCAN_CMD"
TRENDING_VERIFY_TIMEOUT_SECONDS = 20
# 90d, not 30d: the 2026-07-13 incident was the 5th same-theme piece within 90
# days, and the theme-saturation threshold (6) was calibrated on the 90d live
# corpus. A 30d window would have scored the incident below threshold and let it
# through again. At generation time a wider window is the cheap direction — a
# false positive costs one swapped topic.
ARC_DEDUP_WINDOW_DAYS = 90

sys.path.insert(0, str(ROOT / "src"))

from volpred.ops.timestamps import parse_iso_warn  # noqa: E402
from volpred.canonical_write import guard_canonical_write  # noqa: E402
from volpred.ops.diagnostics import warn  # noqa: E402
from volpred.ops.event_jobs import (  # noqa: E402
    build_pending_event_task,
    expand_due_event_jobs,
)
from volpred.ops.next_tasks import append_task_record, normalize_task_priority  # noqa: E402
from volpred.ops.topic_dedup import TopicScreen, log_decision, screen_topic  # noqa: E402

_diag_warn = warn  # legacy alias used by _warn_refill_reader (was undefined -> NameError)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _now_local() -> datetime:
    return _now_utc().astimezone(LOCAL_TZ)


def _today_local() -> str:
    return _now_local().date().isoformat()


def _warn_refill_reader(message: str, path: Path, exc: Exception) -> None:
    _diag_warn(
        "reader_facing_refill",
        message,
        path=str(path),
        err=f"{type(exc).__name__}: {exc}",
    )


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        _warn_refill_reader("JSON read failed; using default", path, exc)
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_next_tasks() -> list[dict[str, Any]]:
    return _load_json(NEXT_TASKS, [])


def _append_task(task: dict[str, Any]) -> bool:
    """WS-A1b: canonical append helper owns bootstrap + LOCK_EX + dup-skip +
    serialize-first (the old truncate-then-json.dump was the 2026-07-05
    truncation-incident pattern)."""
    normalize_task_priority(task)
    _record, created = append_task_record(task, path=NEXT_TASKS, if_exists="skip")
    return created


def _load_runtime_event_items() -> list[dict[str, Any]]:
    payload = _load_json(RUNTIME_SCHEDULES, {})
    event_jobs = payload.get("event_jobs") if isinstance(payload, dict) else None
    items = event_jobs.get("items") if isinstance(event_jobs, dict) else None
    return items if isinstance(items, list) else []


def _task_exists(task_id: str) -> bool:
    tasks = _load_next_tasks()
    return any(isinstance(item, dict) and item.get("id") == task_id for item in tasks)


def _event_task_id(event_type: str, event_date: str, slot: str) -> str:
    slot_norm = slot.lower().replace("+", "plus").replace("-", "minus")
    return f"event_article_{event_type.lower()}_{event_date}_{slot_norm}"


# --- Slot-aware event coverage (2026-07-03 NFP T+0 stale-duplicate fix) -------
# Root cause: refill deduped only by task_id, so a reaction (result-known) task
# (T+0/T-0/T+1) was regenerated even when a feed article already covered the
# event. The scheduled event_date is an ESTIMATE; when the data releases early
# and a reaction article publishes early, the estimated-date task becomes a
# stale duplicate (mile_35eef830 vs event_article_nfp_us_2026-07-03_tplus0,
# intercepted manually). Feed articles carry no event_key metadata yet (part-b
# follow-up), so coverage falls back to event-type alias + reaction-window title
# match. Only reaction slots are gated — forward slots (T-7/T-2) are distinct
# pre-event pieces and keep the existing task_id idempotency untouched so a real
# forward article is never suppressed. Risk asymmetry: a false-positive here
# would MISS a real event article (unrecoverable), whereas a false-negative only
# lets a duplicate through to the publish-time arc-dedup backstop (recoverable);
# so the check is conservative + fail-open + audit-logged (dedup-gate-audit rule).
DEDUP_LOG = STORAGE / "logs" / "dedup_decisions.jsonl"
REACTION_EARLY_RELEASE_DAYS = 3   # data can print up to N days before scheduled date
REACTION_POST_DAYS = 7            # reaction article publishes within N days after event
FORWARD_TITLE_SIGNALS = (
    "前瞻", "預告", "倒數", "前夕", "來臨", "即將", "展望",
    "前7天", "前 7 天", "前七天", "前2天", "前 2 天", "前兩天",
    "t-7", "t-2", "t-3", "t-5",
)
EVENT_TYPE_ALIASES = {
    "nfp": ("非農", "非農就業", "nonfarm", "payroll", "就業報告", "nfp"),
    "cpi": ("cpi", "消費者物價", "通膨", "通脹", "物價指數"),
    "pce": ("pce", "個人消費支出", "個人消費"),
    "ppi": ("ppi", "生產者物價"),
    "fomc": ("fomc", "聯準會", "利率決策", "點陣圖", "議息", "降息", "升息", "fed"),
    "gdp": ("gdp", "國內生產毛額", "經濟成長"),
    "tsmc_revenue": ("台積電", "tsmc", "營收"),
    "earnings": ("財報", "earnings"),
}


def _slot_is_reaction(slot: str) -> bool:
    """T+0 / T-0 / T+N are result-known reaction slots; T-N (N>=1) is forward.

    Unknown/unparseable slots are treated as forward (not gated) so we never
    suppress a real article on an unexpected slot label.
    """
    m = re.match(r"^t([+-])(\d+)", str(slot or "").strip().lower().replace(" ", ""))
    if not m:
        return False
    sign, num = m.group(1), int(m.group(2))
    return not (sign == "-" and num >= 1)


def _event_type_aliases(event_type: str) -> list[str]:
    et = str(event_type or "").strip().lower()
    aliases: set[str] = set()
    if et:
        aliases.add(et)
        aliases.add(et.split("_")[0])  # e.g. nfp_us -> nfp
    for key, vals in EVENT_TYPE_ALIASES.items():
        if et.startswith(key) or key in et:
            aliases.update(vals)
    return [a for a in aliases if a]


def _looks_forward(title: str) -> bool:
    t = str(title or "").lower()
    return any(sig in t for sig in FORWARD_TITLE_SIGNALS)


def _log_coverage_decision(target_id: str, decision: str, reason: str, dup_of: str = "") -> None:
    """Audit trail for the coverage gate (dedup-gate-audit rule). Never raises."""
    guard_canonical_write(DEDUP_LOG)
    try:
        DEDUP_LOG.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": _now_utc().isoformat(timespec="seconds"),
            "gate": "event_reaction_coverage",
            "target_id": target_id,
            "decision": decision,   # "skip" | "pass"
            "reason": reason,
            "dup_of": dup_of,
        }
        with DEDUP_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as exc:  # pragma: no cover - audit log must never block refill
        warn("reader_facing_refill", "coverage audit log failed",
             err=f"{type(exc).__name__}: {exc}")


def _reaction_already_covered(
    event_type: str, event_date: date | None, feed: list[dict[str, Any]]
) -> dict[str, str] | None:
    """Return the covering reaction article for this event, or None (fail-open).

    Matching (published articles only):
      1. EXACT metadata — article.event_type + event_date + a reaction slot
         (activates once the part-b publisher metadata write lands).
      2. Legacy fallback — an event-type alias appears explicitly in the title
         (tags are too broad to prove event identity), the article published within
         [event_date - EARLY, event_date + POST], and the title is NOT a
         forward-looking preview (excludes T-7/T-2 pieces).
    Any exception returns None so a real event task is still generated.
    """
    try:
        aliases = _event_type_aliases(event_type)
        if not aliases:
            return None
        et = str(event_type or "").strip().lower()
        ev_iso = event_date.isoformat() if event_date else None
        lo = event_date - timedelta(days=REACTION_EARLY_RELEASE_DAYS) if event_date else None
        hi = event_date + timedelta(days=REACTION_POST_DAYS) if event_date else None
        for art in feed:
            if not isinstance(art, dict):
                continue
            if art.get("status") not in (None, "published"):
                continue
            # 1. exact metadata match (future articles once part-b lands)
            a_type = str(art.get("event_type") or "").strip().lower()
            if a_type and et and a_type == et and ev_iso and art.get("event_date") == ev_iso:
                if _slot_is_reaction(art.get("event_series_slot") or ""):
                    return {"id": str(art.get("id") or ""), "match": "metadata"}
            # 2. legacy fallback on explicit title keyword + reaction window.
            # Tags are intentionally excluded: a generic `通膨` tag on an
            # oil/gold digest once suppressed an unrelated CPI T+0 article.
            title = str(art.get("title") or "")
            hay = title.lower()
            if not any(a in hay for a in aliases):
                continue
            if _looks_forward(title):
                continue  # forward preview, not a reaction — do not gate
            if lo is None or hi is None:
                continue
            pub_raw = art.get("published_at") or art.get("created_at")
            pub_dt = parse_iso_warn(
                pub_raw, tag="reader_facing_refill", field_name="published_at",
                fallback=None, item_id=str(art.get("id") or ""), path=str(FEED_PATH),
            ) if pub_raw else None
            if pub_dt is None:
                continue
            pub_date = pub_dt.astimezone(LOCAL_TZ).date()
            if lo <= pub_date <= hi:
                return {"id": str(art.get("id") or ""), "match": "title_keyword"}
        return None
    except Exception as exc:  # fail-open: never block generating a real article
        warn("reader_facing_refill", "reaction coverage check failed (fail-open)",
             err=f"{type(exc).__name__}: {exc}")
        return None


def _build_event_task(item: dict[str, Any]) -> dict[str, Any]:
    """Compatibility wrapper; event_jobs owns the canonical task schema.

    The feed MUST be passed: `build_pending_event_task` only runs the
    generation-time topic screen when it has a corpus, so omitting it here would
    silently leave this second event-task path unscreened — the exact "generator
    never looks at the feed" hole this change closes. Event lane screens in WARN
    mode, so this can annotate a task but never block one.
    """

    # Pass STORAGE explicitly: the callee's default is the relative "storage",
    # which resolves against the caller's cwd rather than the repo root.
    return build_pending_event_task(
        item, now=_now_utc(), feed=_load_feed_for_dedup(), storage_dir=str(STORAGE)
    )


def refill_event_candidates(*, horizon_days: int = 14) -> dict[str, Any]:
    """Delegate event eligibility and materialization to the hourly owner.

    ``horizon_days`` remains for API compatibility.  Eligibility now comes
    only from canonical ``not_before`` / ``deadline`` values, eliminating the
    second writer and its once-per-day scan gate.
    """

    _ = horizon_days
    result = expand_due_event_jobs(storage_dir=str(STORAGE), now=_now_utc())
    added = [
        str(entry["task"]["id"])
        for entry in result.get("created", [])
        if entry.get("queue_created") and isinstance(entry.get("task"), dict)
    ]
    return {
        "added": added,
        "skipped": result.get("skipped", []),
        "expired": result.get("expired_tasks", {}),
    }


def refill_member_qa() -> dict[str, Any]:
    try:
        import sys

        sys.path.insert(0, str(ROOT / "src"))
        from volpred.ops.questions import ensure_member_qa_task

        result = ensure_member_qa_task(source="user")
        return {"ok": True, "result": result}
    except Exception as exc:
        return {"ok": False, "error": repr(exc)}


def _extract_trending_candidates(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        items = payload.get("candidates")
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    return []


def _build_trending_task(candidate: dict[str, Any]) -> dict[str, Any]:
    task_id = str(candidate.get("id") or "").strip()
    if not task_id:
        topic = str(candidate.get("topic") or "trending")
        task_id = f"trending_repost_{_today_local().replace('-', '_')}_{topic.lower().replace(' ', '_')[:40]}"
    title = str(candidate.get("title") or candidate.get("topic") or "trending repost candidate")
    description = str(candidate.get("description") or candidate.get("brief") or "")
    return {
        "id": task_id,
        "title": f"[trending_repost] {title}",
        "description": description,
        "task_type": "trending_repost",
        "priority": 1,
        "status": "pending",
        "created_at": _now_utc().isoformat(timespec="seconds"),
        "source": "reader_facing_refill",
        "tags": ["trending_repost", "reader_facing", "auto_refill"],
    }


# --- Trending quantitative-claim primary-source gate -----------------------
# The scanner is an LLM and therefore cannot be the authority for a number it
# emitted.  Keep extraction deliberately narrow and conservative: the exact
# classes that have appeared in fabricated candidates (percent moves, index
# points, volume, and headline monetary/count amounts).  Dates are not claims.
_PERCENT_CLAIM_RE = re.compile(r"(?P<value>[+-]?\d[\d,]*(?:\.\d+)?)\s*(?:%|％)")
_POINT_CLAIM_RE = re.compile(r"(?P<value>[+-]?\d[\d,]*(?:\.\d+)?)\s*(?:點|points?)", re.I)
_VOLUME_CLAIM_RE = re.compile(
    r"(?:成交量|volume)[^\d+-]{0,12}(?P<value>[+-]?\d[\d,]*(?:\.\d+)?)\s*(?P<unit>兆|億|萬|[kmb])?",
    re.I,
)
_AMOUNT_CLAIM_RE = re.compile(
    r"(?P<value>[+-]?\d[\d,]*(?:\.\d+)?)\s*(?P<unit>兆|億|萬)"
)
_UNIT_SCALE = {"": 1.0, "k": 1e3, "m": 1e6, "b": 1e9, "萬": 1e4, "億": 1e8, "兆": 1e12}
_NEGATIVE_MOVE_RE = re.compile(
    r"(?:崩跌|重挫|挫跌|下跌|跌幅|跌了|大跌|下挫|跌|declin(?:e|ed)|fell|drop(?:ped)?)\s*$",
    re.I,
)
_YFINANCE_TEXT_ALIASES = {
    "^TWII": ("台股", "加權指數", "taiex", "twii"),
    "SPY": ("s&p 500", "s&p500", "標普500", "標普 500", "spy"),
    "^VIX": ("vix", "恐慌指數"),
    "^DJI": ("道瓊", "dow jones", "dji"),
    "^IXIC": ("那斯達克綜合", "納斯達克綜合", "nasdaq composite", "ixic"),
}


def _claim_value(raw: str, unit: str = "") -> float:
    return float(raw.replace(",", "")) * _UNIT_SCALE.get(unit.lower(), 1.0)


def _extract_quantitative_claims(text: str) -> list[dict[str, Any]]:
    """Return prose claims that require primary-source verification.

    Overlapping matches are collapsed in favour of the more specific class;
    e.g. ``成交量 3 億`` is one volume claim, not volume + amount.
    """
    claims: list[dict[str, Any]] = []
    occupied: list[tuple[int, int]] = []
    patterns = (
        ("volume", _VOLUME_CLAIM_RE),
        ("percent", _PERCENT_CLAIM_RE),
        ("points", _POINT_CLAIM_RE),
        ("amount", _AMOUNT_CLAIM_RE),
    )
    for kind, pattern in patterns:
        for match in pattern.finditer(text or ""):
            span = match.span()
            if any(span[0] < end and start < span[1] for start, end in occupied):
                continue
            unit = match.groupdict().get("unit") or ""
            value = _claim_value(match.group("value"), unit)
            if kind in {"percent", "points"} and not match.group("value").lstrip().startswith(("+", "-")):
                prefix = (text or "")[max(0, span[0] - 12):span[0]]
                if _NEGATIVE_MOVE_RE.search(prefix):
                    value = -abs(value)
            claims.append({
                "kind": kind,
                "value": value,
                "raw": match.group(0),
                "span": span,
            })
            occupied.append(span)
    return sorted(claims, key=lambda claim: claim["span"][0])


def _numbers_close(left: float, right: float, *, kind: str) -> bool:
    tolerance = {
        "percent": max(0.02, abs(left) * 0.002),
        "points": max(0.5, abs(left) * 0.0005),
        "volume": max(1.0, abs(left) * 0.001),
        "amount": max(1.0, abs(left) * 0.001),
    }.get(kind, max(1e-9, abs(left) * 1e-6))
    return math.isfinite(left) and math.isfinite(right) and abs(left - right) <= tolerance


def _named_yfinance_tickers(prose: str) -> set[str]:
    lowered = prose.lower()
    return {
        ticker
        for ticker, aliases in _YFINANCE_TEXT_ALIASES.items()
        if any(alias in lowered for alias in aliases)
    }


def _fetch_yfinance_claim(spec: dict[str, Any]) -> tuple[float | None, str]:
    ticker = str(spec.get("ticker") or "").strip()
    date_text = str(spec.get("date") or "").strip()
    metric = str(spec.get("metric") or "").strip()
    if not ticker or not date_text or metric not in {"close_change_pct", "close_change_points", "volume"}:
        return None, "invalid_yfinance_spec"
    try:
        import pandas as pd  # noqa: PLC0415
        import yfinance as yf  # noqa: PLC0415

        target = pd.Timestamp(date_text).normalize()
        frame = yf.download(
            ticker,
            start=(target - pd.Timedelta(days=10)).date().isoformat(),
            end=(target + pd.Timedelta(days=2)).date().isoformat(),
            auto_adjust=False,
            progress=False,
            threads=False,
            timeout=TRENDING_VERIFY_TIMEOUT_SECONDS,
        )
        if frame is None or frame.empty:
            return None, "primary_source_empty"
        if getattr(frame.columns, "nlevels", 1) > 1:
            frame.columns = frame.columns.get_level_values(0)
        frame.index = pd.to_datetime(frame.index).tz_localize(None).normalize()
        frame = frame[~frame.index.duplicated(keep="last")].sort_index()
        if target not in frame.index:
            return None, "target_date_missing"
        column = "Volume" if metric == "volume" else "Close"
        value = frame.loc[target, column]
        if hasattr(value, "iloc"):
            value = value.iloc[-1]
        if pd.isna(value) or not math.isfinite(float(value)):
            return None, "target_value_nan"
        if metric == "volume":
            return float(value), "verified"
        prior = frame.loc[frame.index < target, "Close"].dropna()
        if prior.empty:
            return None, "prior_close_missing"
        previous = prior.iloc[-1]
        if hasattr(previous, "iloc"):
            previous = previous.iloc[-1]
        previous = float(previous)
        if not math.isfinite(previous) or previous == 0:
            return None, "prior_close_invalid"
        delta = float(value) - previous
        actual = delta if metric == "close_change_points" else delta / previous * 100.0
        return actual, "verified"
    except Exception as exc:
        return None, f"primary_source_error:{type(exc).__name__}"


def _fetch_fred_claim(spec: dict[str, Any]) -> tuple[float | None, str]:
    series_id = str(spec.get("series_id") or "").strip()
    date_text = str(spec.get("date") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", series_id) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_text):
        return None, "invalid_fred_spec"
    query = urllib.parse.urlencode({"id": series_id, "cosd": date_text, "coed": date_text})
    try:
        with urllib.request.urlopen(
            f"https://fred.stlouisfed.org/graph/fredgraph.csv?{query}",
            timeout=TRENDING_VERIFY_TIMEOUT_SECONDS,
        ) as response:
            rows = list(csv.DictReader(io.StringIO(response.read().decode("utf-8"))))
        if not rows:
            return None, "target_date_missing"
        raw = rows[-1].get(series_id)
        value = float(raw) if raw not in (None, "", ".") else math.nan
        if not math.isfinite(value):
            return None, "target_value_nan"
        return value, "verified"
    except Exception as exc:
        return None, f"primary_source_error:{type(exc).__name__}"


def _fetch_primary_claim(spec: dict[str, Any]) -> tuple[float | None, str]:
    provider = str(spec.get("provider") or "").strip().lower()
    if provider == "yfinance":
        return _fetch_yfinance_claim(spec)
    if provider == "fred" and str(spec.get("metric") or "") == "observation":
        return _fetch_fred_claim(spec)
    # TAIFEX claims require a product-specific official endpoint/parser.  Never
    # silently substitute a prose or secondary-source value.
    return None, "unsupported_primary_source"


def _log_trending_verification(task_id: str, receipt: dict[str, Any]) -> None:
    path = STORAGE / "logs" / "trending_primary_source_verification.jsonl"
    guard_canonical_write(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"ts": _now_utc().isoformat(timespec="seconds"), "task_id": task_id, **receipt}
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception as exc:  # audit failure must be visible, but refill remains best-effort
        warn("reader_facing_refill", "trending verification audit log failed",
             err=f"{type(exc).__name__}: {exc}")


def _verify_trending_candidate(candidate: dict[str, Any], task_id: str) -> tuple[bool, dict[str, Any]]:
    prose = " ".join(str(candidate.get(key) or "") for key in ("title", "description", "brief"))
    prose_claims = _extract_quantitative_claims(prose)
    named_tickers = _named_yfinance_tickers(prose)
    if not prose_claims:
        receipt = {"decision": "pass", "reason": "no_quantitative_claims", "checks": []}
        _log_trending_verification(task_id, receipt)
        return True, receipt

    specs = candidate.get("quant_claims")
    if not isinstance(specs, list) or not specs:
        receipt = {"decision": "reject", "reason": "missing_quant_claim_specs", "claims": prose_claims}
        _log_trending_verification(task_id, receipt)
        return False, receipt

    unused = [spec for spec in specs if isinstance(spec, dict)]
    checks: list[dict[str, Any]] = []
    for claim in prose_claims:
        matched_index = None
        for index, spec in enumerate(unused):
            try:
                same_value = _numbers_close(
                    float(spec.get("value")), float(claim["value"]), kind=claim["kind"]
                )
            except (TypeError, ValueError):
                same_value = False
            if str(spec.get("kind") or "") == claim["kind"] and same_value:
                matched_index = index
                break
        if matched_index is None:
            receipt = {
                "decision": "reject", "reason": "unmapped_prose_claim",
                "claim": claim, "checks": checks,
            }
            _log_trending_verification(task_id, receipt)
            return False, receipt
        spec = unused.pop(matched_index)
        if (
            str(spec.get("provider") or "").lower() == "yfinance"
            and named_tickers
            and str(spec.get("ticker") or "") not in named_tickers
        ):
            receipt = {
                "decision": "reject",
                "reason": "series_identity_mismatch",
                "claim": claim,
                "named_tickers": sorted(named_tickers),
                "provided_ticker": spec.get("ticker"),
                "checks": checks,
            }
            _log_trending_verification(task_id, receipt)
            return False, receipt
        actual, source_reason = _fetch_primary_claim(spec)
        expected = float(spec["value"])
        check = {
            "kind": claim["kind"], "raw": claim["raw"], "provider": spec.get("provider"),
            "series": spec.get("ticker") or spec.get("series_id"), "date": spec.get("date"),
            "metric": spec.get("metric"), "expected": expected, "actual": actual,
            "source_reason": source_reason,
        }
        checks.append(check)
        if actual is None or not _numbers_close(expected, actual, kind=claim["kind"]):
            receipt = {
                "decision": "reject",
                "reason": source_reason if actual is None else "primary_source_mismatch",
                "checks": checks,
            }
            _log_trending_verification(task_id, receipt)
            return False, receipt

    if unused:
        receipt = {
            "decision": "reject",
            "reason": "unused_claim_specs",
            "unused_count": len(unused),
            "checks": checks,
        }
        _log_trending_verification(task_id, receipt)
        return False, receipt

    receipt = {"decision": "pass", "reason": "primary_source_verified", "checks": checks}
    _log_trending_verification(task_id, receipt)
    return True, receipt


def _screen_trending_topic(title: str, description: str, feed: list[dict] | None) -> TopicScreen:
    """Generation-time dedup screen for a trending candidate (BLOCK mode).

    Pre-write gate (release-layer recycling root cause, 2026-06-23): trending
    scan kept producing pending tasks for arcs already covered (Fed-pivot 22
    dups, AI capex 2 dups) because no upstream check existed. Publisher arc
    block fires only at publish time — the task still wastes a dispatch slot.

    2026-07-14: the previous version called `find_arc_duplicates` alone and
    swallowed every exception into `return None` (a silent fallback). It could
    not have caught the 2026-07-13 incident anyway — the arc gate is
    entity-anchored and the incident's five siblings do not arc-match each other
    (0 of 10 pairs; see volpred.publisher.arc_dedup.theme_saturation). The screen
    now also runs theme saturation, which does catch it (saturation 12 >= 5), and
    every decision — including a gate error — is logged, never swallowed.
    """
    return screen_topic(
        title,
        description,
        feed=feed,
        audience="general",
        days=ARC_DEDUP_WINDOW_DAYS,
        mode="block",
    )


def _load_feed_for_dedup() -> list[dict]:
    if not FEED_PATH.exists():
        return []
    try:
        data = json.loads(FEED_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    return data if isinstance(data, list) else []


def refill_trending_candidates() -> dict[str, Any]:
    cmd = os.environ.get(TRENDING_SCAN_CMD_ENV, "").strip()
    if not cmd:
        # Trending scan is best-effort: main pipeline relies on the trending_repost
        # agent doing WebSearch itself. Missing scan command is a skip, not an error.
        return {
            "ok": True,
            "skipped": True,
            "reason": "no_scan_cmd_configured",
            "hint": f"set {TRENDING_SCAN_CMD_ENV} to enable batch refill",
            "added": [],
        }
    proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=ROOT)
    if proc.returncode != 0:
        return {"ok": False, "reason": "scan_failed", "stderr": proc.stderr[-500:]}
    try:
        payload = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError as exc:
        return {"ok": False, "reason": "bad_json", "error": str(exc)}

    feed = _load_feed_for_dedup()
    added: list[str] = []
    skipped: list[dict[str, str]] = []
    clean: list[dict[str, Any]] = []
    near_miss: list[tuple[dict[str, Any], TopicScreen]] = []

    for candidate in _extract_trending_candidates(payload):
        task = _build_trending_task(candidate)
        verified, verification = _verify_trending_candidate(candidate, task["id"])
        if not verified:
            skipped.append({
                "id": task["id"],
                "reason": "primary_source_verification_failed",
                "detail": str(verification.get("reason") or "verification_failed"),
            })
            continue
        task["primary_source_verification"] = verification
        screen = _screen_trending_topic(task["title"], task.get("description", ""), feed)
        # Audit trail is written for EVERY verdict (pass / block / gate error),
        # so "why was this task never created?" is always answerable. Silent skip
        # is what let the 2026-07-13 dup sit in the pool for 20 hours.
        log_decision(str(STORAGE), "trending_repost", task["id"], screen)
        if screen.blocked:
            skipped.append({
                "id": task["id"],
                "reason": screen.verdict,
                "detail": screen.reason,
                "dup_of": ",".join(str(m.get("id")) for m in screen.matches[:3]),
            })
            continue
        task["dedup_screen"] = screen.as_task_field()
        # 2026-07-22: a non-blocking verdict that still NAMES matched articles is
        # not the same as a clean one. On 2026-07-16 all three of ai變現 /
        # 債市波動度 / ai支出 passed here as warn / unjudged_thin_signature, and
        # each screen record named the exact article the writer agent later cited
        # when it refused to write (mile_f5f4cb43 / mile_d12825bb / mile_0fa841ed).
        # The evidence was present at generation time and thrown away; the refusal
        # then cost a P1 dispatch each and landed as status=failed, which the
        # dreaming retry detector read as "needs a clearer brief" (it does not —
        # the arcs are permanently covered).
        # Fix is preference, not a new block: named-match candidates go to the back
        # of the queue and are only used when no clean candidate exists. The loop
        # already had other candidates to reach for. Hard-blocking them instead
        # would risk the content blackhole that got the publish-time arc gate
        # downgraded to warn-only on 2026-06-23.
        if screen.matches:
            near_miss.append((task, screen))
        else:
            clean.append(task)

    for task in clean:
        if _append_task(task):
            added.append(task["id"])
            break
        skipped.append({"id": task["id"], "reason": "already_exists"})

    if not added:
        for task, screen in near_miss:
            # Demoted: a writer agent must resolve the named arc before spending a
            # slot on it, so it must not outrank genuinely clean work.
            task["priority"] = max(int(task.get("priority", 1)), 2)
            task["dedup_followup_required"] = (
                "生成端查重點名了下列可能同 arc 的已發文章："
                + ", ".join(str(m.get("id")) for m in screen.matches[:3])
                + "。開寫前必做 3-layer 查重：確認撞 arc 就換軸或回報 arc-covered，不要硬寫。"
            )
            if _append_task(task):
                added.append(task["id"])
                skipped.append({
                    "id": task["id"],
                    "reason": "used_near_miss_fallback",
                    "detail": screen.reason,
                    "dup_of": ",".join(str(m.get("id")) for m in screen.matches[:3]),
                })
                break
            skipped.append({"id": task["id"], "reason": "already_exists"})

    return {"ok": True, "added": added, "skipped": skipped}


def _default_state() -> dict[str, Any]:
    return {
        "date": _today_local(),
        "scanned": False,
        "scanned_at": None,
        "trending_added": 0,
        "event_added": 0,
        "member_qa_added": 0,
        "errors": [],
    }


def run_refill(*, force: bool = False) -> dict[str, Any]:
    state = _load_json(STATE_PATH, _default_state())
    today = _today_local()
    if not force and state.get("date") == today and state.get("scanned") is True:
        return {
            "skip": True,
            "reason": "already_scanned_today",
            "state": state,
        }

    result = _default_state()
    result["scanned_at"] = _now_utc().isoformat(timespec="seconds")

    trending = refill_trending_candidates()
    if trending.get("ok"):
        result["trending_added"] = len(trending.get("added") or [])
        if trending.get("skipped"):
            result["trending_skipped"] = {
                "reason": trending.get("reason"),
                "hint": trending.get("hint"),
            }
    else:
        result["errors"].append({"source": "trending_scan", **trending})

    events = refill_event_candidates()
    result["event_added"] = len(events.get("added") or [])
    if events.get("skipped"):
        result["event_skipped"] = events["skipped"][:20]

    member = refill_member_qa()
    if member.get("ok") and isinstance(member.get("result"), dict) and member["result"].get("created"):
        result["member_qa_added"] = 1
    elif not member.get("ok"):
        result["errors"].append({"source": "member_qa_eval", **member})
    else:
        result["member_qa_result"] = member.get("result")

    result["scanned"] = True
    _write_json(STATE_PATH, result)
    return {"skip": False, "state": result}


def main() -> int:
    parser = argparse.ArgumentParser(description="Refill reader-facing task pool (event/trending/member_qa)")
    parser.add_argument("--force", action="store_true", help="Ignore daily state and scan again")
    args = parser.parse_args()

    outcome = run_refill(force=args.force)
    print(json.dumps(outcome, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
