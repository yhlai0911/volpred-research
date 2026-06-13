"""Reproduce K1439 outputs and sanity-check the generated artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from k1439 import main


ROOT = Path(__file__).resolve().parent
RESULTS_PATH = ROOT / "k1439_results.json"


def run() -> dict:
    result = main()
    saved = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))

    if saved["k_id"] != "K1439":
        raise RuntimeError("Unexpected k_id in saved results")
    if saved["verdict"] != result["verdict"]:
        raise RuntimeError("Saved verdict does not match in-memory verdict")

    print(
        "[reproduce] K1439 complete:",
        f"verdict={saved['verdict']}",
        f"hac_sig={saved['robustness']['n_hac_bonferroni_sig_level']}/{saved['robustness']['n_tests']}",
    )
    return saved


if __name__ == "__main__":
    run()
