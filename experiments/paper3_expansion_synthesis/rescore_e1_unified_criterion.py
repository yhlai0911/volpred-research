"""把 E1 的 DM 顯著性改用 E2 的判準重評分，讓兩臂的計數可以並列比較。

背景（assign_f3419501）：E1 (`paper3_E1.py:717`) 用硬編 `abs(t) > 3.0` 且完全未套 HLN
小樣本修正，E2 (`paper3_E2.py:784-791`) 用 HLN 修正後比 `t.ppf(0.975, df)`。兩者共用
同一個欄位名 `significant_harvey`，於是「E1 有 k 個顯著」與「E2 有 m 個顯著」根本不是
同一個問題的答案 —— 並列報這兩個數字是錯的。

為什麼是重評分而不是重跑：E1 的 results.json 已經存了**未修正的原始 NW t 統計量**與
`n`，而 E2 的判準是這兩者的純函數（`t_adj = t_raw * hln(n, h)`，臨界值 `t.ppf(0.975, n-1)`）。
所以統一判準不需要任何重新估計 —— 重跑只會多燒數小時算力去得到同一組 t。

為什麼不直接改 E1 的腳本：`paper3_E1.py` 是已歸檔實驗的可重現來源，改掉它會讓它不再
重現自己那份 archived results.json。原始產物保持不動，本腳本另出一份重評分 artifact。

**口徑警告（不要跟 synthesis 的數字並列）**：本腳本報的是**逐對、未做多重檢定修正**的
5% 顯著計數，目的只有一個 —— 量化「換一把尺會差多少」。synthesis README 的主結論走的是
統一重算 p 之後再 BH-FDR，那才是對外可引用的口徑。本檔的 23 不是 synthesis 的 23。

用法：python3 experiments/paper3_expansion_synthesis/rescore_e1_unified_criterion.py
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from scipy.stats import t as student_t

ROOT = Path(__file__).resolve().parents[2]
E1_RESULTS = ROOT / "experiments/paper3_E1_individual_stocks_copula/paper3_E1_results.json"
OUT = Path(__file__).resolve().parent / "e1_rescored_unified_criterion.json"

HORIZON = 1  # E1 與 E2 都是 1-step-ahead


def hln_small_sample_factor(n: int, h: int = 1) -> float:
    """Harvey-Leybourne-Newbold (1997) 小樣本修正因子；與 paper3_E2.py:757 逐字相同。"""
    if n <= 1:
        return 1.0
    return float(np.sqrt((n + 1 - 2 * h + (h * (h - 1)) / n) / n))


def rescore(entry: dict) -> dict:
    """用 E2 判準重算一筆 DM 結果的顯著性；回傳新舊並陳的紀錄。"""
    t_raw = float(entry["t_stat"])
    n = int(entry["n"])
    factor = hln_small_sample_factor(n, h=HORIZON)
    t_adj = t_raw * factor
    df = max(n - 1, 1)
    crit = float(student_t.ppf(0.975, df=df))
    return {
        "t_stat_raw": t_raw,
        "n": n,
        "hln_factor": factor,
        "t_stat_hln": float(t_adj),
        "p_value_unified": float(2 * student_t.cdf(-abs(t_adj), df=df)),
        "critical_value": crit,
        "significant_e1_original": bool(entry["significant_harvey"]),
        "significant_unified": bool(abs(t_adj) > crit),
    }


def main() -> int:
    payload = json.loads(E1_RESULTS.read_text(encoding="utf-8"))
    rows: list[dict] = []

    for pair_name, pair in payload["pair_results"].items():
        for block_name, block in (("dm_qlike", pair.get("dm_qlike")), ("dm_fz", pair.get("dm_fz"))):
            if not block:
                continue
            # dm_qlike 是 {comparison: entry}；dm_fz 多一層 {alpha: {comparison: entry}}
            if block_name == "dm_qlike":
                nested = {"": block}
            else:
                nested = block
            for alpha, comparisons in nested.items():
                for comparison, entry in comparisons.items():
                    if not isinstance(entry, dict) or "t_stat" not in entry:
                        continue
                    row = {
                        "pair": pair_name,
                        "loss": block_name,
                        "alpha": alpha or None,
                        "comparison": comparison,
                    }
                    row.update(rescore(entry))
                    rows.append(row)

    flipped = [r for r in rows if r["significant_unified"] != r["significant_e1_original"]]
    out = {
        "experiment_id": "paper3_expansion_synthesis/rescore_e1_unified_criterion",
        "source_artifact": str(E1_RESULTS.relative_to(ROOT)),
        "criterion_original": "abs(t_raw) > 3.0, normal p-value, no HLN correction (paper3_E1.py:717)",
        "criterion_unified": "abs(t_raw * hln(n,h=1)) > t.ppf(0.975, n-1) (paper3_E2.py:784-791)",
        "scope_caveat": (
            "逐對未修正的 5% 計數，僅用於量化換尺的影響幅度；synthesis 主結論用統一 p + BH-FDR，"
            "兩組數字不可並列引用。"
        ),
        "n_tests": len(rows),
        "n_significant_original": sum(r["significant_e1_original"] for r in rows),
        "n_significant_unified": sum(r["significant_unified"] for r in rows),
        "n_flipped": len(flipped),
        "flipped_direction": {
            "false_to_true": sum(1 for r in flipped if r["significant_unified"]),
            "true_to_false": sum(1 for r in flipped if not r["significant_unified"]),
        },
        "rows": rows,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"tests={out['n_tests']}")
    print(f"significant original(|t|>3.0)={out['n_significant_original']}")
    print(f"significant unified(HLN+t.ppf)={out['n_significant_unified']}")
    print(f"flipped={out['n_flipped']} {out['flipped_direction']}")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
