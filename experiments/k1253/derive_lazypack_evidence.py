"""K1253 lazypack 衍生 evidence 產生器（reproducible）。

從凍結的 k1253_results.json 忠實計算懶人包要用的少數 scalar：
- 把 pred_var / realized_var（單位：日報酬×100 的平方）開根號成「日波動率（fraction）」，
  供 lazypack `percent` 格式（預設 ×100）直接顯示成「X%」。
- 挑出 2025-04 關稅震盪那幾天，示範 GARCH 對 shock 的反應式適應（波動率叢聚）。

所有數字都來自 k1253_results.json，不新增任何估計。輸出寫回 experiments/k1253/，
不碰任何共享狀態（feed.json / knowledge.json / next_tasks.json / Supabase / Mirror）。

用法：uv run python experiments/k1253/derive_lazypack_evidence.py
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
SRC = HERE / "k1253_results.json"
OUT = HERE / "k1253_lazypack_derived.json"


def _sd_fraction(variance: float) -> float:
    """pred_var/realized_var 單位是（日報酬×100）^2 → 開根號得百分點，再 /100 成 fraction。"""
    return float(np.sqrt(variance)) / 100.0


def main() -> None:
    raw = SRC.read_bytes()
    src = json.loads(raw)
    rows = {r["date"]: r for r in src["rolling_results"]}

    def row(date: str) -> dict:
        return rows[date]

    derived = {
        "note": "derived faithfully from k1253_results.json; no new estimation",
        "source_file": "experiments/k1253/k1253_results.json",
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "n_oos_days": int(src["n_oos_days"]),
        "oos_start": src["oos_start"],
        "oos_end": src["rolling_results"][-1]["date"],
        "median_qlike": float(src["median_qlike"]),
        # 平靜日：整段測試期預測波動最低的一天
        "calm_predicted_daily_vol": min(
            _sd_fraction(r["pred_var"]) for r in src["rolling_results"]
        ),
        # 2025-04-03：第一擊，GARCH 還在低波動體制
        "shock_onset_date": "2025-04-03",
        "shock_onset_predicted_daily_vol": _sd_fraction(row("2025-04-03")["pred_var"]),
        "shock_onset_realized_daily_vol": _sd_fraction(row("2025-04-03")["realized_var"]),
        # 2025-04-09：測試期最大單日震盪（+9.99%）
        "peak_move_date": "2025-04-09",
        "peak_move_realized_daily_vol": _sd_fraction(row("2025-04-09")["realized_var"]),
        "peak_move_predicted_daily_vol": _sd_fraction(row("2025-04-09")["pred_var"]),
        # 2025-04-10：叢聚啟動，預測終於追上實際
        "adapt_date": "2025-04-10",
        "adapt_predicted_daily_vol": _sd_fraction(row("2025-04-10")["pred_var"]),
        "adapt_realized_daily_vol": _sd_fraction(row("2025-04-10")["realized_var"]),
    }

    OUT.write_text(json.dumps(derived, indent=2, ensure_ascii=False))
    print(f"✓ wrote {OUT}")
    for k, v in derived.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
