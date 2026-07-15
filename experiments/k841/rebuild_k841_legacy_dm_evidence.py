"""Rebuild K841's pre-repair pointwise DM losses from the pinned legacy source.

This helper exists only to isolate the HAC correction from the later timing,
cost, and session repairs. It executes the exact committed legacy program,
reconstructs its strategy returns on the frozen Yahoo snapshot, verifies that
the published pre-repair metrics and iid DM statistics are reproduced, and
atomically stores the positive squared-return loss streams. The corrected K841
program consumes that immutable artifact instead of hard-coding HAC-only t
statistics.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import subprocess
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
LEGACY_COMMIT = "76aa426d0fee034cf012d21c89489c033cdae58e"
LEGACY_PATH = "experiments/k841/k841_futures_realtime_vt.py"
LEGACY_SOURCE_SHA256 = "96a37c1791bdd8f719972acdc3326659c702c211c081b1d7166bfb650f5fb229"
ANALYSIS_END = 20260402
OUTPUT_PATH = HERE / "k841_legacy_dm_losses.npz"

PAIRS = (
    ("s2", "s1"),
    ("s2", "s0"),
    ("s3", "s0"),
    ("s3", "s1"),
    ("s4", "s0"),
    ("s4", "s1"),
    ("s5", "s1"),
)

EXPECTED_OLD_T = {
    "s2_vs_s1": 10.8213,
    "s2_vs_s0": -7.1306,
    "s3_vs_s0": -1.9712,
    "s3_vs_s1": 14.0087,
    "s4_vs_s0": -4.4320,
    "s4_vs_s1": 12.1384,
    "s5_vs_s1": -0.7583,
}

_LEGACY_WORKER: dict | None = None


def _legacy_source() -> str:
    source = subprocess.check_output(
        ["git", "show", f"{LEGACY_COMMIT}:{LEGACY_PATH}"],
        cwd=REPO_ROOT,
        text=True,
    )
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    if digest != LEGACY_SOURCE_SHA256:
        raise RuntimeError(
            f"Pinned legacy source hash changed: expected {LEGACY_SOURCE_SHA256}, got {digest}"
        )
    return source


def _load_legacy_namespace(source: str) -> dict:
    namespace = {
        "__name__": "k841_pinned_legacy",
        "__file__": str(REPO_ROOT / LEGACY_PATH),
    }
    exec(compile(source, namespace["__file__"], "exec"), namespace)
    return namespace


def _worker_init(source: str) -> None:
    global _LEGACY_WORKER
    _LEGACY_WORKER = _load_legacy_namespace(source)


def _worker_parse(path: str):
    if _LEGACY_WORKER is None:
        raise RuntimeError("legacy parser worker was not initialised")
    return _LEGACY_WORKER["parse_single_tx_file"](path)


def _current_module():
    spec = importlib.util.spec_from_file_location(
        "k841_current", HERE / "k841_futures_realtime_vt.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _legacy_files(legacy: dict) -> list[str]:
    import glob

    paths: list[str] = []
    pattern = os.path.join(legacy["TAIFEX_DIR"], "Daily_*TX.csv")
    for path in glob.glob(pattern):
        stem = os.path.basename(path).replace("Daily_", "").replace("TX.csv", "")
        try:
            file_date = int(stem.replace("_", ""))
        except ValueError:  # silent-ok: malformed noncanonical filenames are not legacy inputs.
            continue
        if legacy["NIGHT_SESSION_START"] <= file_date <= ANALYSIS_END:
            paths.append(path)
    return sorted(paths)


def main() -> None:
    source = _legacy_source()
    legacy = _load_legacy_namespace(source)
    current = _current_module()
    paths = _legacy_files(legacy)
    if len(paths) != 2163:
        raise RuntimeError(f"Expected 2163 frozen TAIFEX files, found {len(paths)}")

    with ProcessPoolExecutor(
        max_workers=8,
        initializer=_worker_init,
        initargs=(source,),
    ) as executor:
        rows = list(executor.map(_worker_parse, paths, chunksize=8))
    rows = [row for row in rows if row is not None]
    tx_df = pd.DataFrame(rows).sort_values("file_date").reset_index(drop=True)
    tx_df["date"] = pd.to_datetime(tx_df["file_date"].astype(str), format="%Y%m%d")

    vix, close, returns, _, _, snapshot_hash = current.load_vix_and_0050()
    if snapshot_hash != current.EXPECTED_YFINANCE_SNAPSHOT_SHA256:
        raise RuntimeError("legacy reconstruction did not use the frozen Yahoo snapshot")
    merged = legacy["compute_strategies"](tx_df, vix, close, returns)
    if (
        len(merged) != 2157
        or merged.index[0] != pd.Timestamp("2017-05-16")
        or merged.index[-1] != pd.Timestamp("2026-04-02")
        or merged.index.duplicated().any()
    ):
        raise RuntimeError("legacy reconstruction sample identity changed")

    arrays: dict[str, np.ndarray] = {
        "date_ordinal": merged.index.to_numpy(dtype="datetime64[D]").astype(np.int64)
    }
    for left, right in PAIRS:
        key = f"{left}_vs_{right}"
        loss1 = merged[f"{left}_ret"].to_numpy(dtype=np.float64) ** 2
        loss2 = merged[f"{right}_ret"].to_numpy(dtype=np.float64) ** 2
        old_t, _ = legacy["dm_test"](
            merged[f"{left}_ret"] ** 2,
            merged[f"{right}_ret"] ** 2,
            h=1,
        )
        # The legacy helper rounded its reported t to four decimals and the
        # committed JSON dropped trailing zeroes. Allow only that display-level
        # tolerance; larger drift means the published stream did not reproduce.
        if not np.isclose(old_t, EXPECTED_OLD_T[key], atol=2e-4):
            raise RuntimeError(
                f"Legacy published DM did not reproduce for {key}: {old_t}"
            )
        arrays[f"{key}_loss1"] = loss1
        arrays[f"{key}_loss2"] = loss2

    digest = current.atomic_save_npz(OUTPUT_PATH, **arrays)
    print(f"wrote {OUTPUT_PATH}")
    print(f"sha256={digest}")
    for left, right in PAIRS:
        key = f"{left}_vs_{right}"
        t_stat, p_value = current.canonical_dm_test(
            arrays[f"{key}_loss1"], arrays[f"{key}_loss2"], h=1
        )
        print(f"{key}: t={t_stat:.15f}, p={p_value:.15g}")


if __name__ == "__main__":
    main()
