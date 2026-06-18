"""K1416 — Paper 3 HLN small-sample DM correction retrofit (TW0050-N225).

Paper 3 submission blocker (research_program.md Open Question):
TW0050-N225 是 cross-market copula 10 pairs 中最強、也最需要排除
single-start type-I 的 pair (Student-t copula vs DCC, dm_t=3.92,
oos_start=2015-06-01). 原始 raw-DM 口徑曾標成唯一 Harvey-sig；2026-06-02
HLN retrofit 後 TW0050-HSI 也跨過臨界值，所以本實驗只驗證 TW0050-N225
本身是否對 OOS_START 選擇穩健，不再宣稱它是唯一 significant pair.

K1412 對 5 OOS starts (2014/2015/2016/2017/2018) 跑 OOS sensitivity:
Student-t DM_t = {3.24, 3.89, 3.66, 3.04, 3.09} (all > 3) 且 K1412
回報 ROBUST (5/5 Harvey-sig)。Codex review FAIL: K1412 retrofit_notes
用 worst-case n=10 推論而非正式套用 HLN(1997) small-sample
correction 公式。

K1416 retrofit (正式版本):
  (a) 每 OOS 明確記錄 n_oos_obs (TW0050+N225 交易日交集估算
      from paper3_E2 baseline n=2067 at OOS_START=2015-06-01)
  (b) 明確套用 HLN(1997) small-sample correction:
        factor = sqrt((n + 1 - 2h + h(h-1)/n) / n), h=1
              = sqrt((n - 1) / n)
  (c) 明確算 critical_value: scipy.stats.t.ppf(0.975, df=n-1)
  (d) Verify K1412 stored dm_dcc_vs_t 與 paper3_E2.dm_test 內建
      HLN 一致 (paper3_E2.py:783-785: t_stat = t_stat_raw * hln_factor)
  (e) 重算 robust_ratio with explicit HLN-corrected critical_value

如果 robust_ratio ≥ 0.8 (≥4/5 HLN-sig) → Paper 3 submission OK
否則 → 降級 TW0050-N225 robustness 主張。

References:
  - Harvey, D., Leybourne, S., & Newbold, P. (1997). Testing the equality
    of prediction mean squared errors. International Journal of Forecasting,
    13(2), 281-291.
  - K1412 (experiments/k1412/k1412_results.json)
  - Paper3_E2 (experiments/paper3_E2_cross_market_copula/paper3_E2.py:757-792)
  - research_program.md Open Question (TW0050-N225 strongest significant pair)
"""

import json
import math
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from scipy.stats import t as student_t

EXPERIMENT_ID = "K1416"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_PATH = os.path.join(SCRIPT_DIR, "k1416_results.json")
K1412_RESULTS = os.path.join(
    os.path.dirname(SCRIPT_DIR), "k1412", "k1412_results.json"
)
PAPER3_E2_RESULTS = os.path.join(
    os.path.dirname(SCRIPT_DIR),
    "paper3_E2_cross_market_copula",
    "paper3_E2_results.json",
)


def hln_factor(n: int, h: int = 1) -> float:
    """Harvey/Leybourne/Newbold (1997) small-sample DM correction factor.

    t_HLN = t_DM * sqrt((n + 1 - 2h + h(h-1)/n) / n)

    For h=1, simplifies to sqrt((n - 1) / n).
    """
    if n <= h:
        raise ValueError(f"n={n} too small for h={h}")
    numer = n + 1 - 2 * h + h * (h - 1) / n
    return math.sqrt(numer / n)


def estimate_n_oos(oos_start: str, baseline_n: int, baseline_start: str,
                   data_end: str) -> int:
    """Estimate n_oos for arbitrary OOS_START using TW0050+N225 calendar ratio.

    Anchor: paper3_E2 default OOS_START=2015-06-01 → n=2067 (stored).
    Trading-day ratio = n / calendar_days_elapsed.
    Other OOS_START n = ratio * (data_end - oos_start) calendar days.
    """
    base = pd.Timestamp(baseline_start)
    end = pd.Timestamp(data_end)
    ratio = baseline_n / (end - base).days
    start = pd.Timestamp(oos_start)
    cal_days = (end - start).days
    return int(round(cal_days * ratio))


def main():
    print(f"=== K1416 — HLN small-sample DM retrofit for TW0050-N225 ===")

    with open(K1412_RESULTS) as f:
        k1412 = json.load(f)
    with open(PAPER3_E2_RESULTS) as f:
        p3e2 = json.load(f)

    # paper3_E2 baseline: TW0050-N225 dm_qlike at OOS_START=2015-06-01, n=2067
    p3e2_pair = p3e2["pair_results"]["TW0050-N225"]
    p3e2_dm = p3e2_pair["dm_qlike"][
        "DCC-A4f-ASYM_vs_Copula-t-A4f-ASYM"
    ]
    baseline_n = int(p3e2_dm["n"])
    baseline_t_stored = float(p3e2_dm["t_stat"])
    baseline_t_raw = float(p3e2_dm["t_stat_raw"])
    baseline_hln_factor_stored = float(p3e2_dm["hln_factor"])
    baseline_critical_stored = float(p3e2_dm["critical_value"])

    # Cross-check: paper3_E2 internal HLN math
    computed_factor = hln_factor(baseline_n, h=1)
    computed_critical = float(student_t.ppf(0.975, df=baseline_n - 1))
    print(f"\n[Verification of paper3_E2 baseline (OOS_START=2015-06-01)]")
    print(f"  n = {baseline_n}")
    print(f"  stored hln_factor = {baseline_hln_factor_stored:.8f}")
    print(f"  computed hln_factor (this script) = {computed_factor:.8f}")
    print(f"  match = {math.isclose(baseline_hln_factor_stored, computed_factor, rel_tol=1e-6)}")
    print(f"  stored critical = {baseline_critical_stored:.6f}")
    print(f"  computed critical = {computed_critical:.6f}")
    print(f"  stored t_HLN = {baseline_t_stored:.6f}")
    print(f"  stored t_raw = {baseline_t_raw:.6f}")
    print(f"  t_raw * factor = {baseline_t_raw * computed_factor:.6f}  (should == t_HLN)")

    # K1412 5 OOS starts + dm_dcc_vs_t (already HLN-corrected per paper3_E2.dm_test)
    oos_starts = k1412["oos_starts"]
    per_oos_k1412 = k1412["per_oos"]
    data_end = "2026-05-28"  # paper3_E2 DATA_END
    baseline_start = "2015-06-01"

    per_oos_k1416 = {}
    n_pass = 0
    n_total = 0
    for oos in oos_starts:
        row = per_oos_k1412.get(oos, {})
        if "error" in row:
            per_oos_k1416[oos] = {
                "n_oos_obs_inferred": None,
                "hln_factor": None,
                "critical_value": None,
                "t_HLN_from_k1412": None,
                "t_raw_inferred": None,
                "hln_significant": False,
                "error": row["error"],
            }
            continue

        # Estimate n_oos
        if oos == baseline_start:
            n_est = baseline_n  # exact from paper3_E2
        else:
            n_est = estimate_n_oos(
                oos, baseline_n, baseline_start, data_end
            )

        factor = hln_factor(n_est, h=1)
        critical = float(student_t.ppf(0.975, df=n_est - 1))
        t_hln = float(row["dm_dcc_vs_t"])  # already HLN-corrected per paper3_E2
        t_raw_inferred = t_hln / factor  # back out raw for transparency

        pass_5pct = abs(t_hln) > critical
        n_total += 1
        if pass_5pct:
            n_pass += 1

        per_oos_k1416[oos] = {
            "n_oos_obs_inferred": int(n_est),
            "n_oos_obs_exact_from_paper3_E2": (
                baseline_n if oos == baseline_start else None
            ),
            "hln_factor": float(factor),
            "critical_value_5pct": critical,
            "t_HLN_from_k1412": t_hln,
            "t_raw_inferred": float(t_raw_inferred),
            "hln_significant_5pct": bool(pass_5pct),
            "hln_significant_1pct": bool(
                abs(t_hln) > float(student_t.ppf(0.995, df=n_est - 1))
            ),
            "abs_t_minus_critical": float(abs(t_hln) - critical),
        }
        print(
            f"\n  {oos}: n={n_est}, factor={factor:.6f}, "
            f"crit_5%={critical:.4f}, t_HLN={t_hln:.4f}, "
            f"t_raw={t_raw_inferred:.4f}, PASS@5%={pass_5pct}"
        )

    robust_ratio = n_pass / n_total if n_total else 0.0
    if robust_ratio >= 0.8:
        verdict = "ROBUST (≥4/5 HLN-sig at 5%) — Paper 3 OK to submit"
    elif robust_ratio >= 0.6:
        verdict = "PARTIAL (3/5 HLN-sig) — Caveat in Paper 3 discussion"
    else:
        verdict = "TYPE-I_SUSPECT (<3/5 HLN-sig) — Retract Harvey-sig claim"

    # Also check at 1% level for stronger evidence
    n_pass_1pct = sum(
        1 for r in per_oos_k1416.values()
        if r.get("hln_significant_1pct")
    )

    summary = {
        "n_oos_total": n_total,
        "n_hln_sig_5pct": n_pass,
        "n_hln_sig_1pct": n_pass_1pct,
        "robust_ratio_5pct": robust_ratio,
        "robust_ratio_1pct": (
            n_pass_1pct / n_total if n_total else 0.0
        ),
        "verdict": verdict,
        "paper3_E2_baseline_verification": {
            "stored_hln_factor": baseline_hln_factor_stored,
            "computed_hln_factor": computed_factor,
            "factors_match": math.isclose(
                baseline_hln_factor_stored, computed_factor, rel_tol=1e-6
            ),
            "stored_t_HLN": baseline_t_stored,
            "stored_t_raw": baseline_t_raw,
            "implied_factor": baseline_t_stored / baseline_t_raw,
            "implied_matches_computed": math.isclose(
                baseline_t_stored / baseline_t_raw,
                computed_factor,
                rel_tol=1e-4,
            ),
        },
    }

    out = {
        "experiment_id": EXPERIMENT_ID,
        "pair": "TW0050-N225",
        "parent_experiments": ["K1412", "Paper3_E2"],
        "data_end_used": data_end,
        "baseline_oos_start": baseline_start,
        "baseline_n_oos": baseline_n,
        "n_estimation_method": (
            "trading-day ratio from paper3_E2 baseline "
            "(TW0050+N225 calendar intersection); 2015-06-01 exact, "
            "others inferred (typical accuracy ±20 days for ~2000 obs, "
            "negligible impact on HLN factor)"
        ),
        "hln_correction_formula": "factor = sqrt((n + 1 - 2h + h(h-1)/n) / n), h=1 ⇒ sqrt((n-1)/n)",
        "critical_value_method": "scipy.stats.t.ppf(0.975, df=n-1)",
        "per_oos": per_oos_k1416,
        "summary": summary,
        "references": [
            "Harvey/Leybourne/Newbold (1997) IJF 13(2) 281-291",
            "K1412 (experiments/k1412/k1412_results.json)",
            "Paper3_E2 (paper3_E2.py:757-792 internal HLN math)",
            "research_program.md Paper 3 Open Question",
        ],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "codex_review_target": (
            "Verify: (1) HLN formula coded correctly; (2) n_est method "
            "documented and reasonable; (3) K1412 stored t IS HLN-corrected "
            "per paper3_E2.dm_test:783-785; (4) verdict logic matches "
            "Paper 3 submission rule."
        ),
        "codex_review_outcome": {
            "verdict": "CONDITIONAL_PASS",
            "reviewer": "codex-cli 0.135.0 (gpt-5.4 medium)",
            "timestamp": "2026-06-04",
            "core_logic": "PASS — HLN formula correct, critical_value correct, "
                          "K1412 stored t IS HLN-corrected (verified)",
            "outstanding_caveats": [
                "n_oos 為估算非實測 — 4 個非 baseline OOS 用 calendar-day "
                "ratio proxy；影響 negligible (factor 差 <4e-6 對 ±20 obs；"
                "最小 |t|=3.044 離 critical 還有 ~1.08 margin)，結論不翻",
                "5/5 是 sensitivity grid 不是 5 次獨立 replication — overlapping "
                "samples 不可視為 familywise-error 校正",
                "≥80% PASS gate 是 internal submission gate，不是 econometric "
                "evidence 本身；paper wording 不可包裝成統計定理",
            ],
            "paper_wording_required": (
                "The HLN-adjusted superiority is stable across 5 alternative "
                "OOS starts (5/5 significant at 5% AND 1%), supporting "
                "robustness (sensitivity grid, not independent replication)."
            ),
            "future_work_optional": (
                "paper3_E2.dm_test 上游加 per-OOS exact n storage；K1412 重跑帶 "
                "metadata；K1416 補 exact-n verification (post-submission)"
            ),
        },
    }

    with open(RESULTS_PATH, "w") as f:
        json.dump(out, f, indent=2, default=float)

    print(f"\n=== K1416 SUMMARY ===")
    print(f"  n_total = {n_total}")
    print(f"  HLN-sig @ 5% = {n_pass}/{n_total} ({robust_ratio:.0%})")
    print(f"  HLN-sig @ 1% = {n_pass_1pct}/{n_total}")
    print(f"  verdict: {verdict}")
    print(f"\nWrote {RESULTS_PATH}")


if __name__ == "__main__":
    main()
