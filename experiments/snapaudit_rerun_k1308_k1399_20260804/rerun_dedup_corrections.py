"""snapaudit_rerun_k1308_k1399_20260804 — dedup rerun of K1308 / K1399 at the published vintage.

Closes the "未竟" item recorded by snapaudit_quantify_unmeasured_exposure: row-level
exposure was measured there, but the *statistics* were never recomputed, so two
already-published articles still carry numbers built on duplicated rows.

Contract
--------
* Reruns the ORIGINAL experiment scripts (no forked arithmetic), with two pins:
    - the sample end is pinned to each experiment's published period end, because both
      inputs are append-only and an unpinned rerun would silently widen the sample;
    - the duplicate guard is on (K1308's VIX loader had none — that was the defect).
* Does NOT touch any published article. It only produces the corrected numbers that
  the erratum will quote.
* Preserves the contaminated values verbatim inside a `restatement` block on each
  results.json, so the before/after pair stays auditable after the file is rewritten.

Vintage equivalence (checked at runtime, not assumed): the working-tree CSVs are
compared row-for-row against the post-fix clean vintage 00b07f07f over each pinned
window. If they ever diverge, this script fails rather than quietly restating against
a different dataset.
"""
from __future__ import annotations

import copy
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent

CLEAN_REV = "00b07f07f"      # snapshot-dup fix commit
POLLUTED_REV = "d36a418cb"   # last polluted commit
DUP_DATES = ["2026-05-04", "2026-05-05", "2026-05-06", "2026-05-07", "2026-05-08",
             "2026-05-11", "2026-05-12", "2026-05-13", "2026-05-14", "2026-05-15"]

K1308_DIR = ROOT / "experiments/k1308"
K1399_DIR = ROOT / "experiments/k1399"
K1308_RESULTS = K1308_DIR / "k1308_results.json"
K1399_RESULTS = K1399_DIR / "k1399_vix_decomp_results.json"

K1308_PERIOD_END = "2026-05-20"   # stored k1308_results.json overall_stats.period
K1399_OOS_END = "2026-05-19"      # stored k1399 data_period.oos_end

VIX_TAIWAN = "paper/taiwan-vt/data/0050_tw_twii_2330_tw_2317_tw_2454_tw_0056_tw_spy_vix_2008-2026.csv"
SPY_VIX = "paper/leverage-direction/data/spy_vix_2004-2026.csv"

RESULTS_PATH = HERE / "snapaudit_rerun_k1308_k1399_20260804_results.json"


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args],
                          capture_output=True, text=True, check=True).stdout


def csv_at(rev: str, path: str) -> pd.DataFrame:
    return pd.read_csv(io.StringIO(git("show", f"{rev}:{path}")), parse_dates=["date"])


def verify_vintage(path: str, end: str, cols: list[str]) -> dict:
    """Prove the working tree equals the clean vintage over the pinned window.

    Scoped to the columns the consuming experiment actually reads. These CSVs carry
    many unrelated tickers that have been revised since the fix commit; requiring the
    whole file to be byte-stable would fail for reasons that cannot touch the numbers
    being restated. What must hold is that the consumed series are unchanged.
    """
    clean = csv_at(CLEAN_REV, path)
    polluted = csv_at(POLLUTED_REV, path)
    head = pd.read_csv(ROOT / path, parse_dates=["date"])
    cut = pd.Timestamp(end)

    def win(df: pd.DataFrame) -> pd.DataFrame:
        return df[df["date"] <= cut][cols].sort_values("date").reset_index(drop=True)

    c, h, p = win(clean), win(head), win(polluted)
    identical = c.shape == h.shape and c.equals(h)

    # Does the dedup keep= choice change the answer? For k1592 the duplicated rows
    # carried fabricated zero returns, so keep= was a real decision with a real effect.
    # If the same were true here, a rerun that only tries one keep= would be quietly
    # arbitrary. Check it rather than assume the k1592 case does or does not generalise.
    dup_ts = pd.to_datetime(DUP_DATES)
    dup_rows = p_all = polluted[polluted["date"].isin(dup_ts)][cols]
    pairs_identical = bool(len(p_all.drop_duplicates()) == len(dup_ts))
    keep_reproduces_clean = {}
    for keep in ("first", "last"):
        k = polluted[~polluted["date"].duplicated(keep=keep)]
        k = k[k["date"].isin(dup_ts)][cols].sort_values("date").reset_index(drop=True)
        ref = clean[clean["date"].isin(dup_ts)][cols].sort_values("date").reset_index(drop=True)
        keep_reproduces_clean[keep] = bool(k.equals(ref))
    if not identical:
        raise SystemExit(
            f"ABORT: {path} at HEAD differs from clean vintage {CLEAN_REV} within "
            f"<= {end}; restating against a different dataset is not a restatement."
        )
    return {
        "csv": path,
        "columns_verified": cols,
        "window_end": end,
        "rows_polluted_vintage": int(len(p)),
        "rows_clean_vintage": int(len(c)),
        "duplicate_rows_in_window": int(len(p) - len(c)),
        "head_equals_clean_vintage_in_window": True,
        "duplicate_pairs_value_identical": pairs_identical,
        "dedup_keep_reproduces_clean_vintage": keep_reproduces_clean,
        "dedup_keep_choice_is_immaterial": bool(
            pairs_identical and all(keep_reproduces_clean.values())),
        "clean_rev": CLEAN_REV,
        "polluted_rev": POLLUTED_REV,
    }


def run(script: Path, env_extra: dict) -> None:
    env = {**os.environ, **env_extra}
    proc = subprocess.run([sys.executable, str(script)], cwd=str(script.parent),
                          env=env, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(f"ABORT: {script.name} failed\n{proc.stdout[-2000:]}\n{proc.stderr[-3000:]}")


def original_record(results_path: Path) -> dict:
    """The contaminated record as published — the fixed point of any number of reruns.

    Rerunning this script overwrites the results.json it is comparing against, so a
    naive `before = read(results.json)` makes the second run diff the corrections
    against themselves and silently report "nothing changed", destroying the
    before/after pair the erratum depends on. Once a restatement exists, the baseline
    is the record it preserved, not whatever is on disk now.
    """
    current = json.loads(results_path.read_text(encoding="utf-8"))
    prior = current.get("restatement", {}).get("superseded_values")
    return copy.deepcopy(prior) if prior else current


def dig(obj, dotted: str):
    for part in dotted.split("."):
        if obj is None:
            return None
        obj = obj.get(part) if isinstance(obj, dict) else None
    return obj


def compare(before: dict, after: dict, fields: list[tuple[str, str]]) -> list[dict]:
    rows = []
    for path, label in fields:
        b, a = dig(before, path), dig(after, path)
        changed = b != a
        delta = None
        if isinstance(b, (int, float)) and isinstance(a, (int, float)) \
                and not isinstance(b, bool) and not isinstance(a, bool):
            delta = round(float(a) - float(b), 6)
        rows.append({"field": path, "reader_facing_label": label,
                     "before_contaminated": b, "after_clean": a,
                     "delta": delta, "changed": bool(changed)})
    return rows


K1308_FIELDS = [
    ("overall_stats.n", "正文『共 119 個交易日』"),
    ("overall_stats.mean", "平均比值 1.574"),
    ("overall_stats.median", "中位數"),
    ("overall_stats.std", "標準差"),
    ("overall_stats.cv", "CV"),
    ("overall_stats.min", "最小值"),
    ("overall_stats.max", "最大值"),
    ("overall_stats.period", "樣本期間"),
    ("rolling_summary.final_30d_mean", "最近 30 天 2.064"),
    ("rolling_summary.final_30d_cv", "最近 30 天 CV"),
    ("comparison_to_k1181.k1181_baseline_mean", "前一版基準 1.391"),
    ("comparison_to_k1181.mean_diff", "與基準差距"),
    ("comparison_to_k1181.t_stat_vs_baseline", "vs 基準 t"),
    ("comparison_to_k1181.p_vs_baseline", "vs 基準 p"),
    ("comparison_to_k1181.baseline_still_valid", "基準是否仍成立"),
    ("comparison_to_k1181.additional_days", "較 K1181 增加天數"),
    ("ols_trend.beta", "OLS 趨勢 β"),
    ("ols_trend.p_value", "OLS 趨勢 p"),
    ("ols_trend.trend_significant", "趨勢是否顯著"),
    ("midpoint_mean_shift_test.t_stat", "中點均值位移 t"),
    ("midpoint_mean_shift_test.p_value", "中點均值位移 p"),
    ("midpoint_mean_shift_test.mean_shift_detected", "是否偵測到位移"),
    ("progress_to_252d.pct_complete", "252 日進度 %"),
    ("stability_verdict.overall_stable", "穩定性判定"),
    ("conclusion", "結論句"),
]

K1399_FIELDS = (
    [("n_obs.is", "正文 IS n=3,522"), ("n_obs.oos", "正文 OOS n=1,865"),
     ("data_period.oos_end", "OOS 結束日")]
    + [(f"models.{m}.{f}", f"{m} {f}")
       for m in ["HAR_ABS", "HAR_VIX_L", "HAR_VIX_dV", "HAR_VIX_P", "HAR_VIX_T", "HAR_VIX_All"]
       for f in ["oos_qlike", "is_r2", "oos_rank", "dm_t_vs_baseline",
                 "dm_p_vs_baseline", "harvey_pass_vs_baseline"]]
    + [(f"pairwise_dm_vs_vix_l.{k}.{f}", f"{k} {f}")
       for k in ["HAR_VIX_dV_vs_L", "HAR_VIX_P_vs_L", "HAR_VIX_T_vs_L",
                 "HAR_VIX_All_vs_L", "HAR_VIX_All_vs_best_single"]
       for f in ["dm_t", "dm_p", "harvey_pass"]]
    + [(f"hypothesis_verdicts.{h}", f"{h} 判定")
       for h in ["H1_vix_level_significant", "H2_dvix_incremental", "H3_vol_premium_regime",
                 "H4_vix_trend_no_info", "H5_parsimony_all_vs_best"]]
    + [("verdict", "H1..H5 判定串")]
)

# The reader-facing numbers actually printed in the two published articles.
ARTICLE_CLAIMS = {
    "mile_02c71e74": {
        "k_id": "k1308",
        "title": "別再把美國 VIX 直接乘 1.4 來看台股風險了",
        "quoted": {"n_trading_days": "overall_stats.n",
                   "mean_ratio": "overall_stats.mean",
                   "last_30d_mean": "rolling_summary.final_30d_mean",
                   "prior_baseline": "comparison_to_k1181.k1181_baseline_mean"},
    },
    "mile_34157161": {
        "k_id": "k1399",
        "title": "VIX 四個分量裡，水準最強",
        "quoted": {"dm_t_level": "models.HAR_VIX_L.dm_t_vs_baseline",
                   "dm_t_ma5": "models.HAR_VIX_T.dm_t_vs_baseline",
                   "dm_t_T_vs_L": "pairwise_dm_vs_vix_l.HAR_VIX_T_vs_L.dm_t",
                   "dm_t_All_vs_L": "pairwise_dm_vs_vix_l.HAR_VIX_All_vs_L.dm_t",
                   "dm_p_All_vs_L": "pairwise_dm_vs_vix_l.HAR_VIX_All_vs_L.dm_p",
                   "n_is": "n_obs.is",
                   "n_oos": "n_obs.oos"},
    },
}


def restatement_block(kid: str, before: dict, vintage: dict, rows: list[dict], head_sha: str) -> dict:
    return {
        "reason": "snapshot duplicate contamination (audit_snapshot_dup_20260721); "
                  "row-level exposure measured by snapaudit_unmeasured_20260728, "
                  "statistics recomputed here",
        "task_id": "assign_ce6097bf",
        "rerun_experiment": "snapaudit_rerun_k1308_k1399_20260804",
        "rerun_date": os.environ["RERUN_DATE"],
        "rerun_commit_parent": head_sha,
        "sample_end_pinned_to": vintage["window_end"],
        "duplicate_rows_removed_from_sample": vintage["duplicate_rows_in_window"],
        "duplicate_dates": DUP_DATES,
        "vintage_check": vintage,
        "superseded_values": copy.deepcopy(before),
        "changed_field_count": sum(1 for r in rows if r["changed"]),
        "note": "`superseded_values` is the contaminated record as published; the "
                "top-level fields of this file are the corrected ones.",
    }


def main() -> None:
    os.environ.setdefault("RERUN_DATE", pd.Timestamp.now().strftime("%Y-%m-%d"))
    head_sha = git("rev-parse", "HEAD").strip()

    before_1308 = original_record(K1308_RESULTS)
    before_1399 = original_record(K1399_RESULTS)

    # Columns consumed: k1308.py load_vix -> vix_close; k1399 -> spy_adj_close, vix_close.
    vint_1308 = verify_vintage(VIX_TAIWAN, K1308_PERIOD_END, ["date", "vix_close"])
    vint_1399 = verify_vintage(SPY_VIX, K1399_OOS_END, ["date", "spy_adj_close", "vix_close"])

    run(K1308_DIR / "k1308.py",
        {"K1308_PERIOD_END": K1308_PERIOD_END, "K1308_RUN_DATE": os.environ["RERUN_DATE"]})
    run(K1399_DIR / "k1399_vix_decomp.py", {"K1399_OOS_END": K1399_OOS_END})

    after_1308 = json.loads(K1308_RESULTS.read_text(encoding="utf-8"))
    after_1399 = json.loads(K1399_RESULTS.read_text(encoding="utf-8"))

    rows_1308 = compare(before_1308, after_1308, K1308_FIELDS)
    rows_1399 = compare(before_1399, after_1399, K1399_FIELDS)

    for kid, results_path, after, before, vint, rows in (
        ("k1308", K1308_RESULTS, after_1308, before_1308, vint_1308, rows_1308),
        ("k1399", K1399_RESULTS, after_1399, before_1399, vint_1399, rows_1399),
    ):
        after["restatement"] = restatement_block(kid, before, vint, rows, head_sha)
        results_path.write_text(
            json.dumps(after, indent=2, ensure_ascii=False, default=str) + "\n",
            encoding="utf-8")

    # Did any qualitative verdict flip? A number moving is a numeric correction;
    # a verdict moving is a new finding and must be stated as one.
    verdict_fields_1308 = {"stability_verdict.overall_stable", "conclusion",
                           "comparison_to_k1181.baseline_still_valid",
                           "ols_trend.trend_significant",
                           "midpoint_mean_shift_test.mean_shift_detected"}
    flips_1308 = [r for r in rows_1308 if r["field"] in verdict_fields_1308 and r["changed"]]
    flips_1399 = [r for r in rows_1399
                  if (r["field"].startswith("hypothesis_verdicts.") or r["field"] == "verdict"
                      or r["field"].endswith("harvey_pass") or r["field"].endswith("harvey_pass_vs_baseline"))
                  and r["changed"]]

    erratum = {}
    for mile, spec in ARTICLE_CLAIMS.items():
        src_before = before_1308 if spec["k_id"] == "k1308" else before_1399
        src_after = after_1308 if spec["k_id"] == "k1308" else after_1399
        erratum[mile] = {
            "k_id": spec["k_id"], "title": spec["title"],
            "values": {name: {"published": dig(src_before, path),
                              "corrected": dig(src_after, path), "field": path}
                       for name, path in spec["quoted"].items()},
        }

    payload = {
        "audit_id": "snapaudit_rerun_k1308_k1399_20260804",
        "task_id": "assign_ce6097bf",
        "seed": 42,
        "run_date": os.environ["RERUN_DATE"],
        "parent_commit": head_sha,
        "purpose": "recompute K1308 / K1399 statistics on deduplicated input at the "
                   "published vintage, so the two affected articles' errata can quote "
                   "correct numbers",
        "does_not_modify_published_articles": True,
        "vintage_checks": {"k1308": vint_1308, "k1399": vint_1399},
        "k1308": {"n_before": dig(before_1308, "overall_stats.n"),
                  "n_after": dig(after_1308, "overall_stats.n"),
                  "changed_fields": sum(1 for r in rows_1308 if r["changed"]),
                  "verdict_flips": flips_1308,
                  "verdict_changed": bool(flips_1308),
                  "before_after": rows_1308},
        "k1399": {"n_is_before": dig(before_1399, "n_obs.is"),
                  "n_is_after": dig(after_1399, "n_obs.is"),
                  "n_oos_before": dig(before_1399, "n_obs.oos"),
                  "n_oos_after": dig(after_1399, "n_obs.oos"),
                  "changed_fields": sum(1 for r in rows_1399 if r["changed"]),
                  "verdict_flips": flips_1399,
                  "verdict_changed": bool(flips_1399),
                  "before_after": rows_1399},
        "erratum_fill_ins": erratum,
    }
    RESULTS_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n",
                            encoding="utf-8")

    print(f"K1308 n: {payload['k1308']['n_before']} -> {payload['k1308']['n_after']}  "
          f"({payload['k1308']['changed_fields']} fields changed, "
          f"verdict_flip={payload['k1308']['verdict_changed']})")
    print(f"K1399 IS n: {payload['k1399']['n_is_before']} -> {payload['k1399']['n_is_after']}, "
          f"OOS n: {payload['k1399']['n_oos_before']} -> {payload['k1399']['n_oos_after']}  "
          f"({payload['k1399']['changed_fields']} fields changed, "
          f"verdict_flip={payload['k1399']['verdict_changed']})")
    print(f"wrote {RESULTS_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
