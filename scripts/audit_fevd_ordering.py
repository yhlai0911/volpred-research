"""稽核 Cholesky-FEVD 排序假象（K865b class sweep, 2026-07-13）。

**為什麼有這支**：Diebold-Yilmaz 連通性的「方向性」結論（誰是淨傳染源 / 淨接收者）
在 Cholesky 正交化 FEVD 下**依賴變數排列順序**。K865 把 SPY 排第一，於是 SPY 在
52 個隨機排序中每個視窗都取到 NET 最大值（Spearman(位置, NET) = -0.78）；換成
order-invariant 的 GFEVD (KPPS) 後 SPY NET 只剩 1/8、關稅期翻為淨接收者。
整個 SPY-hub 敘事是排序假象。詳見 `experiments/k865b/README.md`。

**最陰險的變體**：`statsmodels` 的 `VARResults.fevd()` 是 **Cholesky** 正交化，
**沒有**內建 generalized FEVD。有腳本的註解 / docstring 寫著
「Generalized FEVD (Pesaran & Shin, 1998)」，底下卻直接呼叫 `results.fevd(h)`
—— 標籤說 order-invariant，程式是 order-dependent（k628b 即此例）。
所以本稽核**不信註解，只信呼叫**。

分類：
  VIOLATION  — 下了方向性結論（NET / transmitter / receiver）且 FEVD 是 Cholesky
               （直接吃 statsmodels `.fevd()`，且無手刻 KPPS 跡象）
  MISLABELED — 上述之外，還在註解 / docstring 宣稱自己是 generalized / KPPS（更嚴重：
               讀者與後續實驗會以為它已排序穩健）
  OK_GFEVD   — 手刻 KPPS（sigma_u + ma_rep / irf(orth=False) 自組），order-invariant
  OK_NO_DIR  — 有估 FEVD 但不下方向性結論（只用總溢出 / 變異數份額）

用法：
  uv run python scripts/audit_fevd_ordering.py                  # 全量
  uv run python scripts/audit_fevd_ordering.py --violations-only
  uv run python scripts/audit_fevd_ordering.py --json

Enforcement owner = `scripts/tests/test_fevd_ordering_ratchet.py`（凍結 baseline，只准變少）。
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EXPERIMENTS = REPO / "experiments"
BASELINE = REPO / "storage" / "ops" / "fevd_ordering_baseline.json"

# 直接吃 statsmodels 的 Cholesky FEVD
RE_SM_FEVD = re.compile(r"\.fevd\s*\(")
# 手刻 KPPS 的跡象：需要 sigma_u（誤差共變異）+ 非正交 MA 表示
RE_KPPS_SIGNAL = re.compile(
    r"sigma_u|ma_rep|irf\s*\([^)]*orth\s*=\s*False|orth\s*=\s*False", re.I
)
# 重用 canonical KPPS：從別的模組取得 order-invariant estimator，而非自己再刻一份。
# 2026-07-13 加：原本只認「檔案自己的文字裡有 sigma_u / ma_rep」，於是
# **複製貼上第二份實作 = 通過，import 既有正解 = 被判違規** —— 偵測器獎勵了會製造
# 分歧的行為，處罰了正確的行為（k1025b_v2.py 沿用 k1025_v3.generalized_fevd 卻被判
# MISLABELED）。這裡認的是「真的綁定了 canonical 符號」（module 屬性存取或 import），
# 不是散文裡提到 generalized —— 只寫註解宣稱自己是 GFEVD 仍然抓得到。
RE_KPPS_REUSE = re.compile(
    r"from\s+[\w.]*\s+import[^\n]*\bgeneralized_fevd\b"  # from x import generalized_fevd
    r"|\b\w+\.generalized_fevd\b"  # _v3.generalized_fevd
    r"|\bgeneralized_fevd\s*=\s*\w+\.\w+",  # generalized_fevd = _v3.generalized_fevd
)
# 方向性宣稱：淨傳染源 / 淨接收者
RE_DIRECTIONAL = re.compile(
    r"\bnet_|\bnet\s*=|['\"]net['\"]|transmitter|receiver|淨傳染|淨接收", re.I
)
# 註解裡宣稱自己是 generalized
RE_CLAIMS_GENERALIZED = re.compile(r"generalized\s+fevd|gfevd|kpps|pesaran", re.I)


@dataclass
class Site:
    path: str
    classification: str
    calls_statsmodels_fevd: bool
    has_kpps_implementation: bool
    makes_directional_claim: bool
    claims_generalized_in_prose: bool
    note: str


def classify(path: Path, root: Path = REPO) -> Site | None:
    # ``root`` is what the site key is made relative to; a linked worktree must
    # pass its own root or an already-baselined site reads as a new violation.
    src = path.read_text(encoding="utf-8", errors="ignore")

    calls_sm = bool(RE_SM_FEVD.search(src))
    # 只在「有估 FEVD」的檔案上判斷；沒碰 FEVD 的不入池
    if not calls_sm and not RE_KPPS_SIGNAL.search(src) and not RE_KPPS_REUSE.search(src):
        return None
    if not calls_sm and not RE_CLAIMS_GENERALIZED.search(src):
        # 有 sigma_u 但完全沒提 FEVD/GFEVD — 不是連通性實驗（例：GARCH 殘差共變異）
        if "fevd" not in src.lower() and "spillover" not in src.lower():
            return None

    # 判準是「有沒有手刻 KPPS」，**不是**「有沒有呼叫 .fevd()」。正確的排序穩健實驗
    # （k865b / k1025_v3）會刻意兩者都算：Cholesky 當對照組，KPPS 當正解。若因為
    # 它也呼叫了 .fevd() 就判它違規，等於處罰做對的人。
    hand_rolled_kpps = bool(RE_KPPS_SIGNAL.search(src))
    reuses_kpps = bool(RE_KPPS_REUSE.search(src))
    has_kpps = hand_rolled_kpps or reuses_kpps
    directional = bool(RE_DIRECTIONAL.search(src))
    claims_gen = bool(RE_CLAIMS_GENERALIZED.search(src))

    if has_kpps:
        cls = "OK_GFEVD"
        note = (
            "手刻 KPPS，order-invariant"
            if hand_rolled_kpps
            else "重用 canonical KPPS（import generalized_fevd），order-invariant — "
            "重用優於再刻一份，兩套實作分歧才是下一個 bug"
        )
    elif not directional:
        cls, note = (
            "OK_NO_DIR",
            "Cholesky FEVD 但無方向性結論（總溢出 / 變異數份額不受排序影響到同等程度）",
        )
    elif claims_gen:
        cls, note = (
            "MISLABELED",
            "註解宣稱 generalized/KPPS，實際呼叫 statsmodels Cholesky .fevd() — "
            "方向性結論仍是排序相依，且標籤會誤導下游",
        )
    else:
        cls, note = (
            "VIOLATION",
            "Cholesky FEVD + 方向性結論，未做排序置換 — NET 值無法區分「真傳染源」與「排在第一」",
        )

    return Site(
        path=str(path.relative_to(root)),
        classification=cls,
        calls_statsmodels_fevd=calls_sm,
        has_kpps_implementation=has_kpps,
        makes_directional_claim=directional,
        claims_generalized_in_prose=claims_gen,
        note=note,
    )


def sweep() -> list[Site]:
    sites: list[Site] = []
    for py in sorted(EXPERIMENTS.rglob("*.py")):
        if "__pycache__" in py.parts:
            continue
        site = classify(py)
        if site is not None:
            sites.append(site)
    return sites


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--violations-only", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument(
        "--write-baseline",
        action="store_true",
        help="凍結目前的 VIOLATION / MISLABELED 清單（只在首次建立時用）",
    )
    args = ap.parse_args()

    sites = sweep()
    bad = [s for s in sites if s.classification in ("VIOLATION", "MISLABELED")]

    if args.write_baseline:
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.write_text(
            json.dumps(
                {
                    "_doc": (
                        "K865b class sweep 凍結 backlog：Cholesky-FEVD 排序假象。"
                        "**只准變少** — 修好一個就從 sites 移除。新增站點會被 "
                        "scripts/tests/test_fevd_ordering_ratchet.py 擋下。"
                    ),
                    "frozen_at": "2026-07-13",
                    "sites": sorted(s.path for s in bad),
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"[baseline] 凍結 {len(bad)} 個站點 → {BASELINE.relative_to(REPO)}")
        return

    shown = bad if args.violations_only else sites
    if args.json:
        print(json.dumps([asdict(s) for s in shown], indent=2, ensure_ascii=False))
        return

    for s in shown:
        print(f"[{s.classification:10}] {s.path}")
        if s.classification in ("VIOLATION", "MISLABELED"):
            print(f"             {s.note}")

    counts: dict[str, int] = {}
    for s in sites:
        counts[s.classification] = counts.get(s.classification, 0) + 1
    print(f"\n總計 {len(sites)} 個 FEVD 站點：{counts}")
    if bad:
        print(f"⚠ 待修 {len(bad)} 個（VIOLATION + MISLABELED）")


if __name__ == "__main__":
    main()
