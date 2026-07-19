"""Build and validate the in-place correction to mile_35eef830.

The article was published 2026-07-01 with six headline numbers taken from
K528, which dated every NFP to the first Friday of the month. On the official
BLS calendar 46 of its 254 events were the wrong day. Every one of those six
numbers moved, and one changed a stated conclusion: the NFP-vs-Friday gap was
reported as statistically significant and is not (p 0.0335 -> 0.0571).

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

    uv run python experiments/k528/build_article_correction.py            # validate
    uv run python experiments/k528/build_article_correction.py --apply    # write + sync

Validation uses `article_correction._splice`, the same resolver the writer
uses, so a plan that validates here cannot fail differently there.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ARTICLE_ID = "mile_35eef830"
AUDIT_PATH = Path(__file__).parent / "k528_nfp_official_dates_results.json"

# (old, new). Each `old` must occur exactly once in the article body; the
# resolver rejects the whole batch otherwise. Ordered as they appear.
REPLACEMENTS: list[tuple[str, str]] = [
    # --- sample size: 254 -> 253 (and 46 of the survivors are different days) ---
    (
        "總共 254 次 NFP 公布日的資料算過一遍",
        "總共 253 次 NFP 公布日的資料算過一遍",
    ),
    # --- 1.10x vs all non-NFP days ---
    (
        "NFP 當日 SPY 的平均絕對日報酬是 0.842%，非 NFP 交易日是 0.763%，兩者相除是 1.10 倍。",
        "NFP 當日 SPY 的平均絕對日報酬是 0.828%，非 NFP 交易日是 0.764%，兩者相除是 1.08 倍。",
    ),
    (
        "換句話說，這 1.10 倍的差距",
        "換句話說，這 1.08 倍的差距",
    ),
    # --- 1.17x vs Friday baseline: THE CONCLUSION FLIP ---
    (
        "NFP 當日波動是這個基準的 1.17 倍，用 Welch t 檢定算下來，這個差距達到顯著水準。"
        "（另外拿全體非 NFP 日做一個只看排序、不看數值大小的無母數檢定，NFP 日的波動分佈同樣明顯偏高。）",
        "NFP 當日波動是這個基準的 1.15 倍，但用 Welch t 檢定算下來，這個差距並沒有達到顯著水準"
        "（p=0.057，差一點過線但沒過）。"
        "（另外拿全體非 NFP 日做一個只看排序、不看數值大小的無母數檢定，NFP 日的波動分佈仍然明顯偏高。）",
    ),
    (
        "所以精確的講法是：NFP 日確實比一般週五抖一點，差距顯著但不算誇張（1.17 倍）；"
        "但如果拿全部交易日當對照，這個放大效果（1.10 倍）連統計顯著都談不上。",
        "所以精確的講法是：NFP 日看起來比一般週五抖一點（1.15 倍），但這個差距沒有通過顯著性檢定；"
        "拿全部交易日當對照，放大效果（1.08 倍）同樣談不上統計顯著。兩個基準指向同一件事——"
        "以平均絕對報酬來看，NFP 日的放大效果站不住統計檢定。",
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
        "分界點是歷史中位數 16.69。VIX 高於中位數的 127 次 NFP，SPY 當日平均絕對報酬是 1.11%；"
        "VIX 低於中位數的 126 次，只有 0.54%。兩者相差 2.04 倍",
    ),
    # --- VIX correlation ---
    (
        "相關係數落在 0.45 左右（換另一種排序算法也給出一致的 0.38）",
        "相關係數落在 0.44 左右（換另一種排序算法也給出一致的 0.34）",
    ),
    (
        "VIX 每高 1 點，就業日的預期絕對報酬就多墊高約 0.044 個百分點。",
        "VIX 每高 1 點，就業日的預期絕對報酬就多墊高約 0.042 個百分點。",
    ),
    # --- figure caption ---
    (
        "![圖1：VIX 高低體制下的 NFP 日波動差距（2.17 倍）]",
        "![圖1：VIX 高低體制下的 NFP 日波動差距（2.04 倍）]",
    ),
    # --- the worked example: 2026-07-01 VIX 16.59 vs the threshold ---
    (
        "貼在歷史分界線 16.71 的下緣",
        "貼在歷史分界線 16.69 的下緣",
    ),
    (
        "7/1 收盤的 16.59 距離 16.71 只差 0.12 點",
        "7/1 收盤的 16.59 距離 16.69 只差 0.10 點",
    ),
    # --- conclusions section ---
    (
        "第一，NFP 事件本身的波動放大效果，對全體交易日基準是 1.10 倍、未達顯著水準，"
        "對週五基準是 1.17 倍、達到顯著水準。這兩個數字合起來說的是同一件事：放大效果存在，"
        "但幅度有限，遠不到「本月最危險的一天」的地步。",
        "第一，NFP 事件本身的波動放大效果，對全體交易日基準是 1.08 倍、對週五基準是 1.15 倍，"
        "兩個基準都沒有達到顯著水準。這兩個數字合起來說的是同一件事：放大效果就算存在，"
        "幅度也有限，遠不到「本月最危險的一天」的地步。",
    ),
    (
        "高低體制差 2.17 倍，事前 VIX 對就業日波動的預測相關係數約 0.45。",
        "高低體制差 2.04 倍，事前 VIX 對就業日波動的預測相關係數約 0.44。",
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
        "遇到假期則會提前，2025 年 10 月更因聯邦政府關門根本沒有發布。"
        "改用官方日曆重跑後，原本 254 場樣本中有 46 場換成了不同的日子。"
        "本文正文數字已全部同步更正；**文中圖表與文末懶人包圖組仍是初版數據，正在重新產製**。"
        "方向性結論不變（決定波動的是進場 VIX 體制，不是 NFP 本身），"
        "但有一項判讀翻轉：NFP 對「非 NFP 週五」基準的差距原本報為統計顯著（1.17 倍），"
        "改用官方日期後為 1.15 倍且未達顯著（p=0.057）。"
        "逐項前後對照見 experiments/k528/k528_nfp_official_dates_results.json。",
    ),
    (
        "VIX 高低體制以歷史中位數 16.71 為切點，兩組樣本各 127 筆；",
        "VIX 高低體制以歷史中位數 16.69 為切點，兩組樣本分別為 127 與 126 筆；",
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


def record_plan(validated: list[dict], applied: dict | None) -> None:
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    audit["article_correction"] = {
        "article_id": ARTICLE_ID,
        "status": "applied" if applied else "validated_not_applied",
        "n_replacements": len(REPLACEMENTS),
        "all_matched_exactly_once": True,
        "replacements": [{"from": v["from"], "to": v["to"], "hits": v["hits"]} for v in validated],
        "apply_result": applied,
        "residual_gap": (
            "The two inline charts (nfp_20260703_regime.png, nfp_20260703_baseline.png) "
            "and the two lazypack images still render proxy-era numbers. Text and images "
            "now disagree; the article carries a visible note saying so. Regenerating and "
            "re-uploading them is follow-up work outside this worktree's scope."
        ),
    }
    AUDIT_PATH.write_text(json.dumps(audit, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="write the correction (main thread, repo root only)")
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
                "release calendar (46 of 254 dates were wrong). All six headline numbers "
                "restated; the NFP-vs-Friday gap is no longer statistically significant "
                "(1.17x p=0.0335 -> 1.15x p=0.0571)."
            ),
            action="content_correction",
            storage_dir=str(storage_dir),
        )
        print(f"\napplied: {len(applied['content_replacements'])} replacements, "
              f"synced={applied['synced']}")
    else:
        print("\ndry run -- nothing written. Re-run with --apply from the repo root.")

    record_plan(validated, applied)
    print(f"plan recorded in {AUDIT_PATH.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
