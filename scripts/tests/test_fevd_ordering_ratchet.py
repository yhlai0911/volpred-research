"""機械 gate：Cholesky-FEVD 排序假象不得新增站點（K865b class sweep, 2026-07-13）。

**這是本 bug class 的唯一 enforcement owner**（anti-stacking：勿再加第二層 watchdog）。

背景：Diebold-Yilmaz 的方向性結論（誰是淨傳染源）在 Cholesky FEVD 下依賴變數排序。
K865 把 SPY 排第一 → SPY 在 52 個隨機排序中每個視窗都取到 NET 最大值 → 整個
「SPY 是波動樞紐」敘事是排序假象（K865b 推翻，已回溯更正 knowledge + live 文章）。

`statsmodels` 的 `.fevd()` 是 **Cholesky**，沒有內建 GFEVD。要 order-invariant 必須
手刻 KPPS（`sigma_u` + `ma_rep`）。有腳本註解寫「Generalized FEVD (Pesaran & Shin)」
卻直接呼叫 `results.fevd()` —— 標籤說安全、程式不安全（k628b）。

baseline 凍結在 `storage/ops/fevd_ordering_baseline.json`，**只准變少**：
修好一個站點就把它從 baseline 移除；**新增站點會讓本測試 FAIL**。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
BASELINE = REPO / "storage" / "ops" / "fevd_ordering_baseline.json"


def _current_bad_sites() -> set[str]:
    out = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "audit_fevd_ordering.py"), "--json"],
        capture_output=True,
        text=True,
        check=True,
        cwd=REPO,
    ).stdout
    return {
        s["path"]
        for s in json.loads(out)
        if s["classification"] in ("VIOLATION", "MISLABELED")
    }


def test_no_new_cholesky_fevd_ordering_sites() -> None:
    """新的 Cholesky-FEVD 方向性結論站點 = FAIL（baseline 只准變少）。"""
    baseline = set(json.loads(BASELINE.read_text(encoding="utf-8"))["sites"])
    current = _current_bad_sites()

    new_sites = current - baseline
    assert not new_sites, (
        "新增 Cholesky-FEVD 排序假象站點：\n"
        + "\n".join(f"  - {p}" for p in sorted(new_sites))
        + "\n\n方向性結論（NET / transmitter / receiver）不可建在 Cholesky FEVD 上 —— "
        "NET 值無法區分『真傳染源』與『排在第一』（K865 即栽在此）。\n"
        "解法：手刻 KPPS generalized FEVD（sigma_u + ma_rep，見 "
        "experiments/k865b/k865b_gfevd_robustness.py），或改報不依賴排序的總溢出指數。\n"
        "註解寫 'generalized' 不算數 —— statsmodels 的 .fevd() 就是 Cholesky。"
    )


def test_baseline_only_shrinks() -> None:
    """baseline 裡已修好的站點必須從 baseline 移除（否則 backlog 永遠不會歸零）。"""
    baseline = set(json.loads(BASELINE.read_text(encoding="utf-8"))["sites"])
    current = _current_bad_sites()

    fixed_but_still_listed = baseline - current
    assert not fixed_but_still_listed, (
        "以下站點已修好（或已刪除），但仍留在 baseline —— 請從 "
        f"{BASELINE.relative_to(REPO)} 的 sites 移除：\n"
        + "\n".join(f"  - {p}" for p in sorted(fixed_but_still_listed))
    )
