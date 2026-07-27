#!/usr/bin/env python3
"""
Provenance reproduction: taiwan-vt paper Table 1 (Summary Statistics for Key Assets)
descriptive-statistics rows (Mean / Std / Skewness / Kurtosis).

起因: paper/PROVENANCE_SWEEP_20260710.md Finding 2 —— taiwan-vt Table 1 summary stats
(TWII mean/std/skew/kurt) 無活 JSON 來源 (23 untraceable 之一). 本 script 從論文 pinned
資料快照離線重現這些數字, 建立 dedicated results.json 給它們一個可驗證來源.

研究誠實:
  - 純描述統計 (mean/std/skew/kurt), 無 MLE / forecast / signal → 無 lookahead 風險.
  - 資料一律用論文 pinned 快照 (data/*.csv), 不 live-fetch → 無 yfinance vintage drift.
  - 不修改論文任何數字或 JSON; 只重現並分類 matched / drift / needs_signoff.
  - kurtosis / skew 慣例以「跑出來哪個 variant 對得上」實證判定, 不預設.

Data (論文自帶, pinned):
  - paper/taiwan-vt/data/0050_tw_twii_2330_tw_2317_tw_2454_tw_0056_tw_spy_vix_2008-2026.csv
  - paper/taiwan-vt/data/_twii_1997_2007_snapshot.csv  (TWII 1997-07-02..2007, close)

Log returns: r_t = ln(P_t / P_{t-1}) * 100  (per body_v3.tex line 41)
"""
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

PAPER_DIR = Path(__file__).resolve().parents[2] / "paper" / "taiwan-vt"
DATA_MAIN = PAPER_DIR / "data" / "0050_tw_twii_2330_tw_2317_tw_2454_tw_0056_tw_spy_vix_2008-2026.csv"
DATA_TWII_1997 = PAPER_DIR / "data" / "_twii_1997_2007_snapshot.csv"
OUT = Path(__file__).resolve().parent / "results.json"

# Paper Table 1 values (body_v3.tex tab:summary_stats) — 只取描述統計 4 欄, γ 另有 provenance.
PAPER = {
    "TWII (1997-2026)":       {"mean": 0.019, "std": 1.45, "skew": -0.31, "kurt": 5.82},
    "0050.TW (2009-2026)":    {"mean": 0.034, "std": 1.38, "skew": -0.47, "kurt": 4.73},
    "SPY (2008-2026)":        {"mean": 0.042, "std": 1.18, "skew": -0.52, "kurt": 12.30},
    "TSMC (2330.TW)":         {"mean": 0.051, "std": 1.92, "skew": -0.18, "kurt": 3.41},
}

# 相對容差 (描述統計 rounding + vintage): mean 用絕對容差 (值接近 0), 其餘相對.
TOL_MEAN_ABS = 0.005   # mean 印到小數 3 位, 容差半個 last digit 量級 + drift
TOL_REL = 0.05         # std/skew/kurt 相對 5% (rounding + benign vintage drift)


# 物理不可能的單日 log return (broad ETF/index) → 視為資料錯誤 (split-adj 斷點) 剔除並記錄.
IMPOSSIBLE_ABS = 40.0


def log_returns(prices: pd.Series) -> tuple[pd.Series, list]:
    p = prices.dropna().astype(float)
    p = p[p > 0]
    r = (np.log(p / p.shift(1)) * 100).dropna()
    bad = r[r.abs() > IMPOSSIBLE_ABS]
    dropped = [{"date": str(d.date()), "log_ret_pct": round(float(v), 2)} for d, v in bad.items()]
    return r[r.abs() <= IMPOSSIBLE_ABS], dropped


def describe(r: pd.Series) -> dict:
    """回傳所有 skew/kurt variant, 由 caller 判定哪個對上 paper 慣例."""
    x = r.to_numpy()
    return {
        "n_obs": int(x.size),
        "mean": float(np.mean(x)),
        "std_ddof1": float(np.std(x, ddof=1)),
        "std_ddof0": float(np.std(x, ddof=0)),
        # skew variants
        "skew_biased": float(stats.skew(x, bias=True)),      # population (g1)
        "skew_unbiased": float(stats.skew(x, bias=False)),   # sample-corrected (G1)
        # kurtosis variants
        "kurt_excess_biased": float(stats.kurtosis(x, fisher=True, bias=True)),
        "kurt_excess_unbiased": float(stats.kurtosis(x, fisher=True, bias=False)),
        "kurt_pearson_biased": float(stats.kurtosis(x, fisher=False, bias=True)),
        "kurt_pearson_unbiased": float(stats.kurtosis(x, fisher=False, bias=False)),
    }


def load_twii_full() -> pd.Series:
    """TWII 1997-07-02..2026: 1997-2007 snapshot (close) + main CSV twii_close (2008-2026)."""
    snap = pd.read_csv(DATA_TWII_1997, comment="#")
    snap["date"] = pd.to_datetime(snap["date"])
    snap = snap.set_index("date")["twii_close"].sort_index()
    main = pd.read_csv(DATA_MAIN)
    main["date"] = pd.to_datetime(main["date"])
    main = main.set_index("date")["twii_close"].sort_index()
    # snapshot 到 2007-12-31, main 從 2008-01-02; snapshot range 標到 2008-01-02, 去重取 main 2008+
    snap = snap[snap.index < "2008-01-01"]
    combined = pd.concat([snap, main]).sort_index()
    combined = combined[~combined.index.duplicated(keep="last")]
    return combined


def load_col(col: str) -> pd.Series:
    df = pd.read_csv(DATA_MAIN)
    df["date"] = pd.to_datetime(df["date"])
    s = df.set_index("date")[col].sort_index()
    # snapshot-dup guard (audit_snapshot_dup_20260721): load_twii_full() already dedups,
    # but this loader (used for the SPY row) did not, inflating n_obs 4668->4658 and
    # skewing kurtosis/mean. Dedup on the date index here too.
    s = s[~s.index.duplicated(keep="last")]
    return s


def pick_matching_variant(computed: dict, paper_val: float, keys: list[str]) -> tuple[str, float]:
    """從候選 variant 挑最接近 paper 的, 回傳 (variant_name, value)."""
    best_k, best_v, best_err = keys[0], computed[keys[0]], float("inf")
    for k in keys:
        err = abs(computed[k] - paper_val)
        if err < best_err:
            best_k, best_v, best_err = k, computed[k], err
    return best_k, best_v


def classify(computed_val: float, paper_val: float, is_mean: bool) -> tuple[str, float]:
    # sign flip on a signed moment (skew) = 結構性不符, 非 rounding drift.
    if not is_mean and paper_val * computed_val < 0 and abs(paper_val) > 0.1:
        denom = abs(paper_val) if abs(paper_val) > 1e-9 else 1.0
        return "mismatch_signflip", abs(computed_val - paper_val) / denom
    if is_mean:
        diff = abs(computed_val - paper_val)
        if diff <= TOL_MEAN_ABS:
            return "matched", diff
        # 超出絕對容差後, 用相對誤差分 drift / mismatch (與其他 metric 同標準)
        rel = diff / (abs(paper_val) if abs(paper_val) > 1e-9 else 1.0)
        return ("drift" if rel <= 0.30 else "mismatch"), diff
    denom = abs(paper_val) if abs(paper_val) > 1e-9 else 1.0
    rel = abs(computed_val - paper_val) / denom
    if rel <= TOL_REL:
        return "matched", rel
    return ("drift" if rel <= 0.30 else "mismatch"), rel


def main():
    series = {
        "TWII (1997-2026)": load_twii_full(),
        "0050.TW (2009-2026)": load_col("0050_tw_adj_close"),
        "SPY (2008-2026)": load_col("spy_adj_close"),
        "TSMC (2330.TW)": load_col("2330_tw_adj_close"),
    }

    rows = {}
    checks = []
    dropped_rows = {}
    for label, prices in series.items():
        r, dropped = log_returns(prices)
        if dropped:
            dropped_rows[label] = dropped
        d = describe(r)
        pv = PAPER[label]

        # 慣例判定: 對每個資產挑最接近 paper 的 skew/kurt variant
        skew_var, skew_val = pick_matching_variant(d, pv["skew"], ["skew_biased", "skew_unbiased"])
        kurt_var, kurt_val = pick_matching_variant(
            d, pv["kurt"],
            ["kurt_excess_biased", "kurt_excess_unbiased", "kurt_pearson_biased", "kurt_pearson_unbiased"],
        )
        std_val = d["std_ddof1"]  # pandas/樣本慣例

        row_result = {
            "n_obs": d["n_obs"],
            "date_start": str(r.index.min().date()),
            "date_end": str(r.index.max().date()),
            "computed": {
                "mean": round(d["mean"], 4),
                "std": round(std_val, 4),
                "skew": round(skew_val, 4),
                "kurt": round(kurt_val, 4),
            },
            "paper": pv,
            "skew_variant_matched": skew_var,
            "kurt_variant_matched": kurt_var,
            "all_variants": {k: round(v, 4) for k, v in d.items() if k not in ("n_obs",)},
        }
        for metric, comp, is_mean in [
            ("mean", d["mean"], True),
            ("std", std_val, False),
            ("skew", skew_val, False),
            ("kurt", kurt_val, False),
        ]:
            status, err = classify(comp, pv[metric], is_mean)
            checks.append({
                "asset": label, "metric": metric,
                "paper": pv[metric], "computed": round(comp, 4),
                "err": round(err, 4), "status": status,
            })
        rows[label] = row_result

    n_matched = sum(1 for c in checks if c["status"] == "matched")
    n_drift = sum(1 for c in checks if c["status"] == "drift")
    n_mismatch = sum(1 for c in checks if c["status"].startswith("mismatch"))

    # TSMC 子期間 mean 掃描 (self-contained: findings 引用的數字由此 regenerate, 非外部湊值)
    tsmc_r, _ = log_returns(series["TSMC (2330.TW)"])
    tsmc_subperiods = {}
    for start in ("2008", "2012", "2015", "2018"):
        rr = tsmc_r[tsmc_r.index >= start]
        tsmc_subperiods[f"{start}-2026"] = {"mean": round(float(rr.mean()), 4), "n": int(rr.size)}
    tsmc_means = [v["mean"] for v in tsmc_subperiods.values()]
    tsmc_mean_range = [min(tsmc_means), max(tsmc_means)]

    findings = [
        "只有 mean 部分重現 (SPY mean 準; 0050/TWII mean 近); std 部分 within-tol; "
        "skew/kurt 系統性不符 — 0050 與 TSMC skew 正負號翻轉 (paper 負, 重現正).",
        "0050_tw_adj_close 欄損毀: 2013-12-31=37.41 → 2014-01-02=9.33 的 split-adjustment "
        "斷點 (單日 -138.9% log return, 物理不可能); 剔除該 row 後 kurtosis 仍達 ~17.8 "
        "(paper 4.73), 顯示 adj_close 尚有殘留 adjustment artifacts, 此欄不可靠.",
        f"TSMC (2330.TW) mean 0.051 無法從 pinned 2008-2026 快照重現 (所有子期間 mean="
        f"{tsmc_mean_range[0]:.3f}-{tsmc_mean_range[1]:.3f}, 見 tsmc_subperiod_scan); "
        "paper 值更低 → 暗示 paper 的 TSMC 列用了此 CSV 未涵蓋的 pre-2008 較長期間資料.",
        "推論: Table 1 summary stats 的原始估計用了與此 pinned CSV 不同的資料 vintage / 期間 "
        "(較長 TSMC 史 + 未損毀的 0050 序列), 現有 pinned 快照不足以重現高階矩.",
    ]

    result = {
        "experiment_id": "paper2_table1_summary_stats_provenance",
        "title": "taiwan-vt Table 1 summary-stats (mean/std/skew/kurt) provenance reproduction",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_doc": "paper/PROVENANCE_SWEEP_20260710.md Finding 2",
        "data_sources": {
            "main_csv": str(DATA_MAIN.relative_to(PAPER_DIR.parents[1])),
            "twii_1997_snapshot": str(DATA_TWII_1997.relative_to(PAPER_DIR.parents[1])),
            "note": "論文 pinned 快照; 未 live-fetch, 無 yfinance vintage drift.",
        },
        "method": {
            "log_returns": "r_t = ln(P_t/P_{t-1}) * 100 (body_v3.tex L41)",
            "price_col": "adj_close for stocks/SPY; close for TWII index (adj==close for index)",
            "std": "sample std ddof=1",
            "skew_kurt_convention": "per-asset best-matching variant reported explicitly in row.*_variant_matched",
            "tolerance": {"mean_abs": TOL_MEAN_ABS, "rel_others": TOL_REL},
        },
        "scope_note": (
            "本 JSON 只覆蓋 Table 1 的 4 個直接可重現資產列 (TWII/0050.TW/SPY/TSMC) 的 "
            "mean/std/skew/kurt. Table 1 的 '9-stock average' / '10-security average' 需完整 "
            "9-10 檔個股 panel, 此 pinned CSV 僅含 2317/2454/0056 三檔個股 → 標 needs_signoff, "
            "待補完整 panel 或 sign-off. γ 欄另有 provenance (k892 / TWII γ disputed)."
        ),
        "summary": {
            "total_checks": len(checks),
            "matched": n_matched,
            "drift": n_drift,
            "mismatch": n_mismatch,
            "verdict": "NOT_REPRODUCIBLE_FROM_PINNED_SNAPSHOT",
        },
        "data_quality_issues": {
            "dropped_impossible_returns": dropped_rows,
            "note": "剔除 |log return| > 40% 的物理不可能單日報酬 (資料錯誤, 非真實波動).",
        },
        "tsmc_subperiod_scan": tsmc_subperiods,
        "findings": findings,
        "honest_conclusion": (
            "本輪未能從論文 pinned 快照重現 Table 1 的 mean/std/skew/kurt (僅 mean 部分對上). "
            "此為研究誠實揭露: 這些數字仍屬 untraceable, 且 pinned CSV 的 0050 adj_close 有資料品質 bug. "
            "未修改論文任何數字. 後續需 owner sign-off: (a) 取回原始估計 vintage 資料重現, 或 "
            "(b) 決定用乾淨資料重估並發 errata 更新 Table 1 (manuscript change, 需 sign-off)."
        ),
        "next_actions": [
            "escalate owner sign-off: Table 1 summary stats 無 reproducible pinned 來源.",
            "followup (compute_queue): 用乾淨 vintage 重抓 TSMC(pre-2008) + 修復 0050 adj 序列後重估, 作 errata 候選值.",
            "禁: 於 sign-off 前 silently 改寫 Table 1 任何數字.",
        ],
        "rows": rows,
        "checks": checks,
    }
    OUT.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"[table1-provenance] wrote {OUT}")
    print(f"[table1-provenance] matched={n_matched}/{len(checks)} drift={n_drift}")
    for c in checks:
        flag = "OK " if c["status"] == "matched" else "DRIFT"
        print(f"  {flag} {c['asset']:24s} {c['metric']:5s} paper={c['paper']:>8} computed={c['computed']:>8} err={c['err']}")


if __name__ == "__main__":
    main()
