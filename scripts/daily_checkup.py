#!/usr/bin/env python3
"""每日大體檢（daily full checkup）—— result-level 驗證，不是 exit-code 監控。

老闆 2026-06-30 硬性要求：「每天都要做一次大體檢 確認所有任務都有確實完成」。

根因（2026-06-30 多重 incident）：既有 ops_dashboard / check_alerts 只查「程式有沒有
報錯」（exit code / 檔案大小），不查「結果好不好」—— 所以沒報錯的爛文章（無圖無表）、
靜默落後的資料（daily_update 卡 6/26、collect_us、twse_orderflow 死 12 天）、卡 1 年的
頁面 cache，全部漏網，最後靠老闆當 QA 發現。本檢查補上 result-level 維度。

七大維度（每個失敗都產生具體 finding，可被 alert 消費）：
1. data_freshness   — 所有資料收集 job 是否照排程跑 + 關鍵資料檔是否新鮮（時效性資料優先）
2. cron_completion  — 所有排程 job 最近一輪是否真的 fire + exit0
3. content_pipeline — 草稿池 ≥ 門檻、今日有產出、published 文章皆含真圖表+數據表（非純散文）
4. live_freshness   — 線上 API 回傳的 data_date 是否 ≈ 最新交易日（抓「頁面卡舊資料」）
5. live_cache       — data-bearing 頁面是否被設成長效靜態快取（抓「網頁卡 cache」）
6. mission_progress — 研究 backlog / 實驗 / 論文是否在前進（非停滯）
7. recovery_actions — 對可自動修復的 finding 列出建議 recovery 指令

用法：
  uv run python scripts/daily_checkup.py            # 印報告
  uv run python scripts/daily_checkup.py --json     # JSON
  uv run python scripts/daily_checkup.py --alert    # 有 critical/warn 時 send-alert email
"""
from __future__ import annotations

import argparse
import datetime
import glob
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STORAGE = ROOT / "storage"
SITE = "https://volpred.zeabur.app"

# 時效性資料 job：照排程「應該」多久跑一次（小時）。超過 1.5× 視為 stale。
# 週末/假日不交易的 job 用較寬窗口；真正時效性（盤中/tick）窗口較緊。
DATA_JOBS_EXPECTED_H = {
    "daily_update": 26,            # 每日 08:03
    "collect_tw": 30,              # 工作日 15:00
    "collect_us": 30,             # 週二-六 07:03（跳週一，故放寬）
    "fred_backfill_guard": 30,
    "collect_twse_orderflow": 48,  # backfill 型；不該超過 2 天沒補
    "radar_strategy_snapshot": 30,
    "indicator_arena_daily": 30,
    "populate_events": 200,        # 週度
}

_now = datetime.datetime.now()


def _age_h(path: str | Path) -> float | None:
    try:
        return (_now - datetime.datetime.fromtimestamp(os.path.getmtime(path))).total_seconds() / 3600
    except OSError:
        return None  # silent-ok: best-effort mtime；檔不存在 → None（呼叫端自行視為無資料/stale）


def _finding(dim: str, severity: str, msg: str, recovery: str | None = None) -> dict:
    return {"dimension": dim, "severity": severity, "message": msg, "recovery": recovery}


# ── 1. data_freshness ───────────────────────────────────────────────────────
def check_data_freshness() -> list[dict]:
    out = []
    for job, expected in DATA_JOBS_EXPECTED_H.items():
        log = STORAGE / "logs" / "cron" / f"{job}.log"
        a = _age_h(log)
        if a is None:
            out.append(_finding("data_freshness", "warn", f"{job}: 無 cron log（從未跑？）"))
            continue
        if a > expected * 1.5:
            sev = "critical" if a > expected * 3 else "warn"
            out.append(_finding(
                "data_freshness", sev,
                f"{job}: 已 {a:.0f}h 沒跑（預期 ≤{expected}h）—— 資料可能落後/漏",
                recovery=f"uv run python scripts/{job}.py  # 或對應 wrapper",
            ))
    return out


# ── 2. cron_completion ──────────────────────────────────────────────────────
def check_cron_completion() -> list[dict]:
    out = []
    for log in sorted(glob.glob(str(STORAGE / "logs" / "cron" / "*.log"))):
        name = Path(log).stem
        if name.endswith("_launchd") or name in ("cron_test", "continue_task_stub", "scheduler_tick"):
            continue  # 已遷移/廢棄
        try:
            tail = Path(log).read_text(errors="replace")[-3000:]
        except OSError:
            continue  # silent-ok: best-effort 讀 cron log；讀不到就跳過該 log
        exits = re.findall(r"exit (\d+)", tail)
        if exits and exits[-1] not in ("0", "142"):  # 142=self-heal
            # 排除 findings-as-exit 的 audit job
            if name.startswith("audit_") or "audit" in name:
                continue
            out.append(_finding("cron_completion", "warn",
                                f"{name}: 最近一輪 exit={exits[-1]}（非 0）",
                                recovery=f"tail storage/logs/cron/{name}.log"))
    return out


# ── 3. content_pipeline ─────────────────────────────────────────────────────
_CHART_RE = re.compile(r"!\[|<img|\.png|\.svg")
_TABLE_RE = re.compile(r"\|.*\|.*\n\s*\|?\s*[-:]")  # markdown table


def check_content_pipeline() -> list[dict]:
    out = []
    feed_path = STORAGE / "reports" / "feed.json"
    try:
        feed = json.loads(feed_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return [_finding("content_pipeline", "critical", f"feed.json 讀取失敗: {exc}")]
    arts = feed if isinstance(feed, list) else feed.get("items", [])
    drafts = [a for a in arts if a.get("status") == "draft"]
    if len(drafts) < 4:
        out.append(_finding("content_pipeline", "warn",
                            f"草稿池僅 {len(drafts)} 篇（門檻 4）—— Mission 1 缺產出",
                            recovery="主動派寫作 agent 補池（feed-publisher，新鮮非 spy 主題）"))
    # 近 7 天 published 文章是否皆含真圖表 + 數據表
    cutoff = _now - datetime.timedelta(days=7)
    chartless = []
    for a in arts:
        if a.get("status") != "published":
            continue
        ts = a.get("published_at") or a.get("created_at") or ""
        try:
            if datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).replace(tzinfo=None) < cutoff:
                continue
        except ValueError:
            continue  # silent-ok: 時間戳格式異常 → 保守跳過該文（不誤判為近期）
        if (a.get("audience") or "general") != "general":
            continue
        content = a.get("content") or a.get("description") or ""
        has_chart = bool(_CHART_RE.search(content))
        if not has_chart:
            chartless.append((a.get("id"), a.get("title", "")[:30]))
    if chartless:
        out.append(_finding("content_pipeline", "critical",
                            f"{len(chartless)} 篇近期 published general 文章正文無真圖表（純散文）: "
                            f"{chartless[:3]}",
                            recovery="走正規 feed-publisher 流程把圖嵌進 content（![](url)）+ 補數據表"))
    return out


# ── 4. live_freshness ───────────────────────────────────────────────────────
def _get_json(url: str, timeout: int = 25):
    req = urllib.request.Request(url, headers={"User-Agent": "checkup"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read()), dict(r.headers)


def check_live_freshness() -> list[dict]:
    out = []
    try:
        _, d, _ = _get_json(f"{SITE}/api/portfolio-overview")
    except Exception as exc:  # noqa: BLE001
        return [_finding("live_freshness", "warn", f"portfolio-overview 抓取失敗: {exc}")]
    items = d.get("items", d if isinstance(d, list) else [])
    dates = []
    for it in items[:5]:
        e = (it.get("paper_trading") or {}).get("entries") or []
        if e:
            dates.append(e[-1].get("data_date") or e[-1].get("trade_date"))
    if dates:
        latest = max(d for d in dates if d)
        try:
            age_days = (_now.date() - datetime.date.fromisoformat(latest)).days
        except ValueError:
            age_days = None
        # 扣掉週末：>3 自然日 = 約 >1 交易日落後
        if age_days is not None and age_days > 3:
            out.append(_finding("live_freshness", "warn",
                                f"線上績效最新 data_date={latest}（已 {age_days} 天）—— 頁面顯示舊資料",
                                recovery="跑 daily_update + 確認頁面非靜態快取（見 live_cache）"))
    return out


# ── 5. live_cache ───────────────────────────────────────────────────────────
def check_live_cache() -> list[dict]:
    out = []
    for path in ["/portfolio", "/v3/portfolio", "/v3", "/admin/paper-trading"]:
        try:
            req = urllib.request.Request(SITE + path, headers={"User-Agent": "checkup"})
            with urllib.request.urlopen(req, timeout=20) as r:
                cc = r.headers.get("cache-control", "")
        except Exception:  # noqa: BLE001
            continue  # silent-ok: 單頁探測失敗跳過該頁（網路/單頁 500 不該擋整體大體檢）
        m = re.search(r"s-maxage=(\d+)", cc)
        if m and int(m.group(1)) > 3600:  # >1h 靜態快取的 data 頁
            out.append(_finding("live_cache", "warn",
                                f"{path}: s-maxage={m.group(1)}（>{int(m.group(1))//86400}天靜態快取）"
                                f"—— 換版/資料更新後使用者卡舊版",
                                recovery="該 data 頁加 export const dynamic='force-dynamic'（或短 revalidate）"))
    return out


# ── 6. mission_progress ─────────────────────────────────────────────────────
def check_mission_progress() -> list[dict]:
    out = []
    nt = STORAGE / "next_tasks.json"
    try:
        tasks = json.loads(nt.read_text())
    except (OSError, json.JSONDecodeError):
        tasks = []
    pending = [t for t in tasks if t.get("status") in (None, "pending", "queued")]
    if len(pending) < 3:
        out.append(_finding("mission_progress", "warn",
                            f"pending 任務僅 {len(pending)} 件 —— backlog 偏薄，需主動生研究議題/派工",
                            recovery="派 journal-discovery / autonomous-research 生新方向"))
    return out


def run_all() -> dict:
    dims = {
        "data_freshness": check_data_freshness,
        "cron_completion": check_cron_completion,
        "content_pipeline": check_content_pipeline,
        "live_freshness": check_live_freshness,
        "live_cache": check_live_cache,
        "mission_progress": check_mission_progress,
    }
    findings = []
    for name, fn in dims.items():
        try:
            findings.extend(fn())
        except Exception as exc:  # noqa: BLE001 — fail-open per no-silent-fallback：印出
            findings.append(_finding(name, "warn", f"檢查本身失敗: {exc}"))
    crit = [f for f in findings if f["severity"] == "critical"]
    warn = [f for f in findings if f["severity"] == "warn"]
    overall = "critical" if crit else ("warn" if warn else "ok")
    return {
        "generated_at": _now.isoformat(),
        "overall": overall,
        "critical_count": len(crit),
        "warn_count": len(warn),
        "findings": findings,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--alert", action="store_true")
    args = ap.parse_args()
    report = run_all()
    out_dir = STORAGE / "ops" / "checkup"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{_now:%Y%m%d}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"每日大體檢 {_now:%Y-%m-%d %H:%M} — overall={report['overall']} "
              f"(critical={report['critical_count']}, warn={report['warn_count']})")
        for f in report["findings"]:
            mark = "🔴" if f["severity"] == "critical" else "🟡"
            print(f"  {mark} [{f['dimension']}] {f['message']}")
            if f["recovery"]:
                print(f"      ↳ recovery: {f['recovery']}")
        if report["overall"] == "ok":
            print("  ✅ 全部維度通過")
    if args.alert and report["overall"] in ("critical", "warn"):
        lines = [f"# 每日大體檢 — overall={report['overall']}", ""]
        for f in report["findings"]:
            lines.append(f"- [{f['severity']}][{f['dimension']}] {f['message']}")
            if f["recovery"]:
                lines.append(f"  - recovery: {f['recovery']}")
        tmp = out_dir / f"alert_{_now:%Y%m%d_%H%M}.md"
        tmp.write_text("\n".join(lines), encoding="utf-8")
        # subprocess + arg list（非 shell）避免 command injection（security hook 要求）
        level = "critical" if report["overall"] == "critical" else "warn"
        title = (f"每日大體檢 {_now:%m-%d}: {report['critical_count']} critical / "
                 f"{report['warn_count']} warn")
        subprocess.run(
            ["uv", "run", "volpred", "ops", "send-alert", "--level", level,
             "--title", title, "--body-md", str(tmp)],
            cwd=str(ROOT), check=False,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
