#!/usr/bin/env python3
"""常設 token 分析：逐角色 × 逐 task_type × 固定/變動成本 × 是否耗 token。

老闆 2026-08-05：「平常就要做好 token 使用的詳細分析，這樣需要節省時才知道優先改善
／降檔哪邊。」所以這支工具的輸出必須直接回答「砍哪個最有效」，而不是報一個總數。

四個維度（每個都標明是量測還是推斷）：
  1. 角色（7 部門＋經理＋主線程＋dispatch worker＋subagent）
     — 目錄類別是量測；部門身分是**推斷**（見 role_attribution_quality）
  2. 固定 vs 變動成本 — **量測**
     fixed_first_load  = 每個 session 第一個 turn 的 input + cache_creation
                         （system prompt ＋ brief ＋ 工具定義，一次載入）
     standing_repaid   = 各 turn 的 cache_read 總和（每輪重付的常駐脈絡）
     variable          = output ＋ 首輪之後的非快取 input（真正在做事的部分）
  3. 耗 token 的工作 vs 不耗 token 的程式運算 — **量測**
     compute queue／回測／模擬只吃 CPU，緊縮時照跑；本報表把它獨立成
     non_token_compute 區塊，**永遠不進「可節省項目」**（老闆指令）
  4. config/token_conservation.json 分層對照 — **量測**（exempt / overrides 逐項）

用法：
    uv run python storage/org/departments/resource_monitor/tools/usage_breakdown.py \
        --date 2026-08-05 [--out PATH]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

def _find_repo() -> Path:
    """往上找帶 scripts/token_usage_report.py 的目錄；找不到才用固定路徑。

    寫成搜尋而不是 parents[N]，是因為這支工具會被從不同深度呼叫（部門 tools/、
    scratchpad、CI），數層數的寫法換個位置就靜默指到錯的 repo。
    """
    for d in [Path(__file__).resolve(), *Path(__file__).resolve().parents]:
        if (d / "scripts" / "token_usage_report.py").is_file():
            return d
    return Path("/Users/yhlai0911/volpred-research")


REPO = _find_repo()
sys.path.insert(0, str(REPO / "scripts"))

from token_usage_report import (  # noqa: E402
    _billable_total, _scan_jsonl, _deduplicated_turns, discover_claude_project_dirs,
    _claude_project_slug, DISPATCH_WORKDIR_ROOT, _usage_breakdown,
)

TPE = timezone(timedelta(hours=8))
DEPTS = ["resource_monitor", "platform_eng", "research", "content",
         "publications", "member_success", "governance", "manager"]
DEPT_PATH_RE = re.compile(r"departments/([a-z_]+)")
DEPT_WORD_RE = re.compile("|".join(DEPTS))


# ---------- 角色歸屬 -------------------------------------------------------
def dir_class(name: str) -> str:
    """目錄類別：這一層是量測，Claude Code 以 cwd 決定 project 目錄。"""
    if name == _claude_project_slug(REPO):
        return "main_checkout"
    if name.startswith(_claude_project_slug(REPO / ".claude" / "worktrees") + "-"):
        return "worktree_agent"
    if name.startswith(_claude_project_slug(DISPATCH_WORKDIR_ROOT) + "-"):
        return "dispatch_worker"
    return "other"


def guess_role(first_user_text: str, all_text: str) -> tuple[str, str]:
    """回傳 (role, quality)。quality ∈ exact / strong / weak / unknown。

    telemetry **沒有**角色欄位（身分經 --append-system-prompt 傳入，不寫進 transcript），
    所以這層是推斷不是量測。優先序：
      strong  — 第一則 user 訊息裡 departments/<x> 路徑唯一
      weak    — 全文部門字詞計數的眾數
      unknown — 兩者皆無
    """
    paths = Counter(DEPT_PATH_RE.findall(first_user_text))
    if len(paths) == 1:
        return next(iter(paths)), "strong"
    if paths:
        top, second = paths.most_common(2)
        if top[1] >= second[1] * 2:
            return top[0], "weak"
    # 只認 departments/<x> 路徑：裸字詞比對會把 repo 路徑 volpred-research
    # 當成研究部，實測讓 research 吃掉 65.6% 的量，是假的。
    words = Counter(DEPT_PATH_RE.findall(all_text))
    if words:
        top = words.most_common(1)[0]
        return top[0], "weak"
    return "unattributed", "unknown"


# ---------- 主分析 ---------------------------------------------------------
def blank():
    return {"billable": 0, "turns": 0, "fixed_first_load": 0,
            "standing_repaid": 0, "variable": 0, "output": 0}


def add(b, turn, is_first):
    # raw turn usage 用的是 API 原始鍵名（cache_creation_input_tokens）；
    # _billable_total 讀的是正規化後的 cache_create_tokens。跳過這一步會少算
    # 整個 cache creation —— 實測 08-04 少算 9.8 倍。平台每一處都先正規化。
    u = _usage_breakdown(turn.get("usage") or {})
    inp = int(u.get("input_tokens") or 0)
    out = int(u.get("output_tokens") or 0)
    cc = int(u.get("cache_create_tokens") or 0)
    cr = int(u.get("cache_read_tokens") or 0)
    b["billable"] += _billable_total(u)
    b["turns"] += 1
    b["output"] += out
    b["standing_repaid"] += cr
    if is_first:
        b["fixed_first_load"] += inp + cc
        b["variable"] += out
    else:
        b["fixed_first_load"] += cc          # 後續 cache 續建仍是脈絡成本
        b["variable"] += out + inp


def analyze(target: date) -> dict:
    by_role = defaultdict(blank)
    by_dirclass = defaultdict(blank)
    by_model = defaultdict(blank)
    by_session = {}
    quality = Counter()
    total = blank()

    d0, d1 = target - timedelta(days=1), target + timedelta(days=1)
    seen: set[str] = set()

    for pdir in discover_claude_project_dirs():
        klass = dir_class(pdir.name)
        srcs = [(p, False) for p in sorted(pdir.glob("*.jsonl"))]
        srcs += [(p, True) for p in sorted(pdir.glob("*/subagents/*.jsonl"))]
        for jp, is_sub in srcs:
            sid = jp.stem if not is_sub else jp.parent.parent.name + "/" + jp.stem
            recs = []
            for r in _scan_jsonl(jp, sid, is_sub, d0, d1):
                rid = r.get("record_id")
                if isinstance(rid, str) and rid:
                    if rid in seen:
                        continue
                    seen.add(rid)
                recs.append(r)
            turns = [t for t in _deduplicated_turns(recs)
                     if _ts_local(t) and _ts_local(t).date() == target]
            if not turns:
                continue

            first_user, all_text = _texts(jp)
            if is_sub:
                role, q = f"{klass}:subagent", "exact"
            elif klass == "dispatch_worker":
                role, q = "dispatch_worker", "exact"
            elif klass == "worktree_agent":
                role, q = "worktree_agent", "exact"
            else:
                role, q = guess_role(first_user, all_text)
            quality[q] += 1

            sb = blank()
            for i, t in enumerate(sorted(turns, key=lambda x: x.get("timestamp") or "")):
                for bucket in (by_role[role], by_dirclass[klass],
                               by_model[t.get("model") or "?"], sb, total):
                    add(bucket, t, i == 0)
            by_session[sid] = {**sb, "role": role, "quality": q, "dir_class": klass}

    return {
        "by_role": {k: v for k, v in sorted(by_role.items(), key=lambda x: -x[1]["billable"])},
        "by_dir_class": dict(by_dirclass),
        "by_model": {k: v for k, v in sorted(by_model.items(), key=lambda x: -x[1]["billable"])},
        "by_session": dict(sorted(by_session.items(), key=lambda x: -x[1]["billable"])[:25]),
        "role_attribution_quality": dict(quality),
        "total": total,
    }


def _ts_local(turn):
    ts = turn.get("timestamp")
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone(TPE)
    except ValueError:
        return None


_TEXT_CACHE: dict[Path, tuple[str, str]] = {}


def _texts(jp: Path) -> tuple[str, str]:
    if jp in _TEXT_CACHE:
        return _TEXT_CACHE[jp]
    first_user, chunks = "", []
    try:
        with jp.open(encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh):
                if i > 400:
                    break
                chunks.append(line)
                if not first_user and '"type":"user"' in line.replace(" ", ""):
                    first_user = line
    except OSError:
        pass
    val = (first_user, "".join(chunks))
    _TEXT_CACHE[jp] = val
    return val


# ---------- 固定成本：brief 是可直接量的 ------------------------------------
def brief_costs() -> dict:
    """runtime/<role>.brief.md 是實際交給該角色的文字，位元組數可直接量。

    token 換算是**估計**（中文約 1 token/字、UTF-8 3 bytes/字）；真值請看
    by_role.fixed_first_load（那是 telemetry 量到的）。
    """
    out = {}
    rt = REPO / "storage" / "org" / "runtime"
    for p in sorted(rt.glob("*.brief.md")):
        b = p.stat().st_size
        out[p.stem.replace(".brief", "")] = {
            "bytes": b,
            "approx_tokens": round(b / 3),
            "mtime": datetime.fromtimestamp(p.stat().st_mtime, TPE).isoformat(),
        }
    return dict(sorted(out.items(), key=lambda x: -x[1]["bytes"]))


# ---------- 不耗 token 的程式運算 ------------------------------------------
def non_token_compute(target: date) -> dict:
    """compute queue／回測／模擬：吃 CPU 不吃 token。永不進「可節省項目」。"""
    logs = REPO / "storage" / "logs" / "compute"
    jobs = []
    if logs.is_dir():
        for p in logs.glob("*.stdout"):
            m = datetime.fromtimestamp(p.stat().st_mtime, TPE)
            if m.date() == target:
                jobs.append({"job": p.stem, "finished": m.isoformat(),
                             "stdout_bytes": p.stat().st_size})
    return {
        "policy": "老闆 2026-08-05：緊縮時照跑。暫停它只損失研究進度，省不到額度。",
        "jobs_today": len(jobs),
        "billable_tokens": 0,
        "note": "這些 job 不經 LLM，token 帳上為 0；只有『需要 LLM 判讀結果』那一段才受 tier 規則管。",
        "sample": sorted(jobs, key=lambda j: j["finished"], reverse=True)[:10],
    }


# ---------- 節流分層對照 ---------------------------------------------------
def conservation_view() -> dict:
    p = REPO / "config" / "token_conservation.json"
    if not p.exists():
        return {"active": False, "note": "config/token_conservation.json 不存在"}
    c = json.loads(p.read_text(encoding="utf-8"))
    return {
        "active": c.get("active"),
        "expires_at": c.get("expires_at"),
        "reason": c.get("reason"),
        "exempt_task_types": c.get("exempt"),
        "downgraded_task_types": c.get("overrides"),
        "deferred_departments": c.get("deferred_departments"),
        "signal_of_record": "Claude Code /usage（All models 週用量 %）——billable 不可用來回答還剩多少",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="台灣日期 YYYY-MM-DD（預設今天）")
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args()
    target = (datetime.strptime(a.date, "%Y-%m-%d").date() if a.date
              else datetime.now(TPE).date())

    payload = {
        "date_local": target.isoformat(),
        "generated_at": datetime.now(TPE).isoformat(),
        **analyze(target),
        "fixed_cost_briefs": brief_costs(),
        "non_token_compute": non_token_compute(target),
        "conservation": conservation_view(),
        "measurement_notes": {
            "exact": ["fixed_first_load / standing_repaid / variable（telemetry usage 欄位）",
                      "dir_class（Claude Code 以 cwd 決定 project 目錄）",
                      "brief bytes", "compute job 計數", "conservation 分層"],
            "inferred": ["部門身分（telemetry 無角色欄位，身分經 --append-system-prompt "
                         "傳入且不寫進 transcript）——見 role_attribution_quality"],
        },
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if a.out:
        a.out.write_text(text, encoding="utf-8")
        print("written", a.out)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
