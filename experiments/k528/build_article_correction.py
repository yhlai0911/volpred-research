"""Build and validate the in-place correction to mile_35eef830.

The article was published 2026-07-01 with headline numbers taken from K528,
which dated every NFP to the first Friday of the month. On the official BLS
calendar that proxy is wrong for ~20% of the sample, so every number moved a
little. This script restates them.

WHAT CHANGED SINCE THE VOIDED 2026-07-19 CORRECTION LIST
--------------------------------------------------------
An earlier 18-item list was built against a contaminated rerun and has been
VOIDED IN FULL. That rerun used an event-date accessor which, for the six
months where ALFRED returns two entries, picked the LATER one -- an off-cycle
seasonal-factor revision rather than the Employment Situation report. Six event
dates were therefore wrong (2006-05-08, 2012-12-12, 2013-05-06, 2020-05-11,
2024-01-10, 2024-08-21).

That mattered far more than six dates out of 253 suggests, because it moved the
NFP-vs-Friday test across the 5% line. The voided list told readers that a
result the article reported as significant was in fact not significant
(1.17x p=0.0335 -> "1.15x p=0.057, 差一點過線但沒過"). On correct dates the
comparison is 1.19x at p=0.020 -- significant, exactly as the article
originally said. Applying that list would have published a retraction of a
correct finding.

So: no claim in this article reverses direction. Every replacement below is a
numeric restatement, plus one estimand refinement that is disclosed in the note.

THE ONE ESTIMAND CHANGE
-----------------------
The event group is a weekday mixture while the control group is pure Friday, so
the Friday effect leaks into the estimate. The corrected test restricts the
event group to the 237 Friday releases.

Note against the tempting story: this defect was NOT introduced by the date
correction. The proxy CALENDAR was all-Friday by construction, but mapping
holiday-closed Fridays to the next open put 15 of its 254 events on a Monday
(239/254 = 94.1% Friday, against 237/253 = 93.7% now). The old spec was already
comparing a mixed group against a pure-Friday control; correcting the dates is
what made it visible, not what caused it.

Two consequences the article text must respect:
  1. The test now identifies the effect of an NFP release ON A FRIDAY. Prose
     quoting it says "在週五公布的 NFP", not "NFP".
  2. The restriction is not a neutral deletion — the excluded events are 16.3%
     quieter, so restricting RAISES the ratio (1.177x -> 1.189x). Both numbers
     are disclosed in the correction note rather than only the flattering one.

WHY THIS SCRIPT DOES NOT WRITE BY DEFAULT
-----------------------------------------
`storage/reports/feed.json` is shared canonical state. `.claude/rules/worktree.md`
forbids a worktree agent from touching it, and the reason is mechanical rather
than ceremonial: this worktree carries its own 15MB checkout of feed.json, so a
write here lands on a branch copy that is already stale the moment any other
article is published, and merging it would silently revert them.

So the split is: this script (run from the worktree) resolves and VALIDATES
every replacement against the canonical article, proving each matches exactly
once before anything is written. The main thread then runs it with --apply from
the repo root, where the write is legitimate.

    uv run python experiments/k528/build_article_correction.py            # validate, writes nothing
    uv run python experiments/k528/build_article_correction.py --apply    # write + sync

Validation uses `article_correction._splice`, the same resolver the writer
uses, so a plan that validates here cannot fail differently there.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ARTICLE_ID = "mile_35eef830"
AUDIT_PATH = Path(__file__).parent / "k528_nfp_official_dates_results.json"

# The 18-item list built on 2026-07-19 against the contaminated rerun. Kept as a
# record of what must NOT be applied, not as a fallback -- see the module
# docstring. Anything that resurrects these strings is reintroducing a
# retraction of a correct finding.
VOIDED_20260719_LIST_SIZE = 18

# (old, new). Each `old` must occur exactly once in the article body; the
# resolver rejects the whole batch otherwise. Ordered as they appear.
REPLACEMENTS: list[tuple[str, str]] = [
    # --- sample size: 254 -> 253 ---
    (
        "總共 254 次 NFP 公布日的資料算過一遍",
        "總共 253 次 NFP 公布日的資料算過一遍",
    ),
    # --- 1.10x -> 1.11x vs all non-NFP days (direction unchanged: NOT significant) ---
    (
        "NFP 當日 SPY 的平均絕對日報酬是 0.842%，非 NFP 交易日是 0.763%，兩者相除是 1.10 倍。",
        "NFP 當日 SPY 的平均絕對日報酬是 0.845%，非 NFP 交易日是 0.763%，兩者相除是 1.11 倍。",
    ),
    (
        "換句話說，這 1.10 倍的差距",
        "換句話說，這 1.11 倍的差距",
    ),
    # --- Friday baseline: 1.17x -> 1.19x, STILL significant; estimand made explicit ---
    (
        "VolPred 也把這層拿掉，改用「非 NFP 的週五」當基準：NFP 當日波動是這個基準的 1.17 倍，"
        "用 Welch t 檢定算下來，這個差距達到顯著水準。"
        "（另外拿全體非 NFP 日做一個只看排序、不看數值大小的無母數檢定，NFP 日的波動分佈同樣明顯偏高。）",
        "VolPred 也把這層拿掉，改用「非 NFP 的週五」當基準。253 場 NFP 裡有 237 場落在週五、"
        "16 場不是，所以這個比較只取在週五公布的那 237 場，讓兩邊的星期別一致："
        "這 237 場的當日波動是週五基準的 1.19 倍，用 Welch t 檢定算下來，這個差距達到顯著水準（p=0.021）。"
        "要注意這個數字講的是「**在週五公布的** NFP」，不是 NFP 一般而言；被排掉的那 16 場本身比較平靜，"
        "所以限定週五會把倍數墊高一些（不限定的話是 1.18 倍）。"
        "（另外拿全體非 NFP 日做一個只看排序、不看數值大小的無母數檢定，NFP 日的波動分佈同樣明顯偏高。）",
    ),
    (
        "所以精確的講法是：NFP 日確實比一般週五抖一點，差距顯著但不算誇張（1.17 倍）；"
        "但如果拿全部交易日當對照，這個放大效果（1.10 倍）連統計顯著都談不上。",
        "所以精確的講法是：在週五公布的 NFP 確實比一般週五抖一點，差距顯著但不算誇張（1.19 倍）；"
        "但如果拿全部交易日當對照，這個放大效果（1.11 倍）連統計顯著都談不上。",
    ),
    # --- regime split: threshold, group sizes, means, ratio ---
    (
        "那 254 次 NFP 日裡",
        "那 253 次 NFP 日裡",
    ),
    (
        "VolPred 把這 254 個 NFP 交易日，按公布前一個交易日收盤的 VIX 水準切成兩半，"
        "分界點是歷史中位數 16.71。VIX 高於中位數的 127 次 NFP，SPY 當日平均絕對報酬是 1.15%；"
        "VIX 低於中位數的 127 次，只有 0.53%。兩者相差 2.17 倍",
        "VolPred 把這 253 個 NFP 交易日，按公布前一個交易日收盤的 VIX 水準切成兩半，"
        "分界點是歷史中位數 16.69。VIX 高於中位數的 128 次 NFP，SPY 當日平均絕對報酬是 1.13%；"
        "VIX 低於中位數的 125 次，只有 0.56%。兩者相差 2.03 倍",
    ),
    # --- VIX correlation ---
    (
        "相關係數落在 0.45 左右（換另一種排序算法也給出一致的 0.38）",
        "相關係數落在 0.44 左右（換另一種排序算法也給出一致的 0.35）",
    ),
    (
        "VIX 每高 1 點，就業日的預期絕對報酬就多墊高約 0.044 個百分點。",
        "VIX 每高 1 點，就業日的預期絕對報酬就多墊高約 0.043 個百分點。",
    ),
    # --- figure caption ---
    (
        "![圖1：VIX 高低體制下的 NFP 日波動差距（2.17 倍）]",
        "![圖1：VIX 高低體制下的 NFP 日波動差距（2.03 倍）]",
    ),
    # --- the worked example: 2026-07-01 VIX 16.59 vs the threshold (still low regime) ---
    (
        "貼在歷史分界線 16.71 的下緣",
        "貼在歷史分界線 16.69 的下緣",
    ),
    (
        "落在低體制的 NFP，當日絕對報酬的 base case 約 0.53%，而不是高體制的 1.15%。",
        "落在低體制的 NFP，當日絕對報酬的 base case 約 0.56%，而不是高體制的 1.13%。",
    ),
    (
        "7/1 收盤的 16.59 距離 16.71 只差 0.12 點",
        "7/1 收盤的 16.59 距離 16.69 只差 0.10 點",
    ),
    # --- conclusions section (direction unchanged on both baselines) ---
    (
        "第一，NFP 事件本身的波動放大效果，對全體交易日基準是 1.10 倍、未達顯著水準，"
        "對週五基準是 1.17 倍、達到顯著水準。",
        "第一，NFP 事件本身的波動放大效果，對全體交易日基準是 1.11 倍、未達顯著水準；"
        "若只看在週五公布的那 237 場、拿非 NFP 的週五當基準，是 1.19 倍、達到顯著水準。",
    ),
    (
        "高低體制差 2.17 倍，事前 VIX 對就業日波動的預測相關係數約 0.45。",
        "高低體制差 2.03 倍，事前 VIX 對就業日波動的預測相關係數約 0.44。",
    ),
    (
        "這跟 k528 在 254 場歷史樣本上得到的傾向一致",
        "這跟 k528 在 253 場歷史樣本上得到的傾向一致",
    ),
    (
        "254 場歷史樣本加上 7/2 這場實測",
        "253 場歷史樣本加上 7/2 這場實測",
    ),
    # --- methodology section + reader-facing errata ---
    (
        "樣本為 2005 年 2 月 4 日至 2026 年 3 月 6 日期間、共 254 次 NFP 公布日，"
        "資料源為 yfinance 的 SPY 與 VIX 日頻數據。",
        "樣本為 2005 年 2 月 4 日至 2026 年 3 月 6 日期間、共 253 次 NFP 公布日，"
        "NFP 發布日期取自美國勞工統計局官方發布日曆（透過 FRED release id 50 取得），"
        "資料源為 yfinance 的 SPY 與 VIX 日頻數據。\n\n"
        "**2026-07-19 更正說明**：本文初版的 NFP 日期是用「每月第一個週五」推算的。"
        "與 BLS 官方發布日曆比對後，約兩成對不上——參考週較晚時 BLS 會改在第二個週五發布，"
        "遇到假期則會提前，2025 年 10 月更因聯邦政府關門根本沒有發布（初版把這天算成了事件日，"
        "但那天並不存在）。改用官方日曆重跑後，樣本從 254 場變成 253 場。\n\n"
        "**方向性結論全部維持不變**：對全體交易日基準未達顯著、對週五基準達到顯著、"
        "真正拉開差距的是進場 VIX 體制——這三點在官方日期下都成立，只有數值小幅調整"
        "（1.10→1.11 倍、1.17→1.19 倍、2.17→2.03 倍、相關係數 0.45→0.44）。\n\n"
        "另有一項口徑調整：週五基準的比較，事件組原本是全部樣本（星期別混合）、對照組卻只有週五，"
        "兩邊不對等。現改為只取在週五公布的 237 場，維持兩邊星期別一致，"
        "所以該數字講的是「在週五公布的 NFP」而非 NFP 一般而言。"
        "被排掉的 16 場本身比較平靜，因此限定週五會把倍數墊高一些（不限定為 1.18 倍、限定為 1.19 倍），"
        "兩個數字都列出以免只揭露比較好看的那個。\n\n"
        "**文中圖表與文末懶人包圖組仍是初版數據，正在重新產製**。"
        "逐項前後對照見 experiments/k528/k528_nfp_official_dates_results.json。",
    ),
    (
        "VIX 高低體制以歷史中位數 16.71 為切點，兩組樣本各 127 筆；",
        "VIX 高低體制以歷史中位數 16.69 為切點，兩組樣本分別為 128 與 125 筆；",
    ),
]


def load_article_content(storage_dir: Path) -> str:
    feed = json.loads((storage_dir / "reports" / "feed.json").read_text(encoding="utf-8"))
    art = next((a for a in feed if isinstance(a, dict) and a.get("id") == ARTICLE_ID), None)
    if art is None:
        raise KeyError(f"{ARTICLE_ID} not found in {storage_dir}/reports/feed.json")
    return art.get("content") or ""


def validate(storage_dir: Path) -> list[dict]:
    """Resolve every replacement against the live article. Raises if any does
    not match exactly once, before a single byte is written."""
    from volpred.publisher.article_correction import _splice

    content = load_article_content(storage_dir)
    spans = _splice(content, REPLACEMENTS)
    return [
        {"index": i, "hits": 1, "from": s["from"], "to": s["to"], "offset": s["start"]}
        for i, s in enumerate(sorted(spans, key=lambda x: x["start"]))
    ]


def _write_json_atomic(path: Path, payload) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass  # silent-ok: best-effort cleanup of our own temp file; the original error re-raises below
        raise


def record_plan(validated: list[dict], applied: dict | None) -> None:
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    audit["article_correction"] = {
        "article_id": ARTICLE_ID,
        "status": "applied" if applied else "validated_not_applied",
        "n_replacements": len(REPLACEMENTS),
        "all_matched_exactly_once": True,
        "supersedes": {
            "voided_list_size": VOIDED_20260719_LIST_SIZE,
            "voided_at": "2026-07-19",
            "reason": (
                "the 18-item list was built against a rerun whose accessor picked "
                "off-cycle ALFRED entries for six months, which pushed the "
                "NFP-vs-Friday test across the 5% line. It would have retracted a "
                "finding that is in fact correct."
            ),
        },
        "directional_claims_changed": 0,
        "replacements": [{"from": v["from"], "to": v["to"], "hits": v["hits"]} for v in validated],
        "apply_result": applied,
        "residual_gap": (
            "The two inline charts (nfp_20260703_regime.png, nfp_20260703_baseline.png) "
            "and the two lazypack images still render proxy-era numbers. Text and images "
            "now disagree; the article carries a visible note saying so. Regenerating and "
            "re-uploading them is follow-up work outside this worktree's scope."
        ),
    }
    _write_json_atomic(AUDIT_PATH, audit)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="write the correction (main thread, repo root only)")
    ap.add_argument("--record-plan", action="store_true",
                    help="record the validated plan into the audit JSON without applying it")
    ap.add_argument("--storage-dir", default=str(REPO_ROOT / "storage"))
    args = ap.parse_args()

    storage_dir = Path(args.storage_dir)
    validated = validate(storage_dir)
    print(f"validated {len(validated)}/{len(REPLACEMENTS)} replacements, each matched exactly once")
    for v in validated:
        head = v["from"].splitlines()[0][:64]
        print(f"  @{v['offset']:>6}  {head}...")

    applied = None
    if args.apply:
        from volpred.publisher.article_correction import apply_article_correction

        applied = apply_article_correction(
            ARTICLE_ID,
            content_replacements=REPLACEMENTS,
            summary=(
                "K528 event dates corrected from a first-Friday proxy to the official BLS "
                "release calendar. Sample 254 -> 253 events; headline numbers restated "
                "(1.10->1.11x vs all days, 1.17->1.19x vs Friday, 2.17->2.03x regime gap, "
                "r 0.45->0.44). No directional conclusion changes. The Friday comparison "
                "now restricts the event group to the 237 Friday releases so weekday is "
                "held fixed on both sides."
            ),
            action="content_correction",
            storage_dir=str(storage_dir),
        )
        print(f"\napplied: {len(applied['content_replacements'])} replacements, "
              f"synced={applied['synced']}")

    # A dry run that rewrites the audit file is not a dry run (k528 Codex v2
    # finding 7). Recording is opt-in and never implicit.
    if args.apply or args.record_plan:
        record_plan(validated, applied)
        print(f"plan recorded in {AUDIT_PATH.name}")
    else:
        print("\ndry run -- nothing written. Re-run with --apply from the repo root, "
              "or --record-plan to persist the validated plan only.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
