#!/usr/bin/env python3
"""Independent parameter/convergence audit for the orphaned K1685 result.

The orphaned compute artifact preserved forecast metrics but not fitted parameters.
This audit replays only the two full-OOS paths used by the headline (three starts and
the symmetric multistart robustness run), verifies their stored DM numbers, and
persists convergence and stationarity diagnostics for every refit.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import numpy as np

import k1685_garchx_oos_extension as experiment


HERE = Path(__file__).resolve().parent
RESULTS_PATH = HERE / "k1685_garchx_oos_extension_results.json"
AUDIT_PATH = HERE / "k1685_parameter_audit.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_json(path: Path, payload: dict) -> None:
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    try:
        with tmp.open("w") as handle:
            json.dump(payload, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        with tmp.open() as handle:
            json.load(handle)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def audit_run(label: str, panel, run_info: dict, stored: dict) -> dict:
    report = experiment.dm_report(panel, f"parameter audit / {label}")
    refit_by_step = {item["t_idx"]: item for item in run_info["refit_diag"]}
    rows = []

    for step, params in sorted(run_info["fitted_params"].items()):
        gjr = np.asarray(params["gjr"], dtype=float)
        a4f = np.asarray(params["a4f"], dtype=float)
        diag = refit_by_step[step]
        rows.append(
            {
                "t_idx": int(step),
                "date": diag["date"],
                "gjr": {
                    "params": gjr.tolist(),
                    "persistence": float(gjr[1] + gjr[2] / 2.0 + gjr[3]),
                    "n_converged_starts": int(diag["gjr"].get("n_converged", 0)),
                    "n_starts": int(diag["gjr"].get("n_starts", 0)),
                },
                "a4f": {
                    "params": a4f.tolist(),
                    "persistence": float(a4f[3] + a4f[4] / 2.0 + a4f[5]),
                    "n_converged_starts": int(diag["a4f"].get("n_converged", 0)),
                    "n_starts": int(diag["a4f"].get("n_starts", 0)),
                },
            }
        )

    gjr_persistence = [row["gjr"]["persistence"] for row in rows]
    a4f_persistence = [row["a4f"]["persistence"] for row in rows]
    dm_checks = {
        "n": report["n"] == stored["n"],
        "qlike_gjr": abs(
            report["qlike_mean_gjr_canonical"] - stored["qlike_mean_gjr_canonical"]
        ) < 1e-12,
        "qlike_a4f": abs(
            report["qlike_mean_a4f_canonical"] - stored["qlike_mean_a4f_canonical"]
        ) < 1e-12,
        "dm_t": abs(report["dm_t_canonical"] - stored["dm_t_canonical"]) < 1e-10,
        "dm_p": abs(report["dm_p_canonical"] - stored["dm_p_canonical"]) < 1e-12,
        "hac_lag": report["dm_hac_lag"] == stored["dm_hac_lag"],
    }
    convergence_checks = {
        "expected_refit_count": len(rows) == 30,
        "all_selected_params_finite": all(
            np.all(np.isfinite(row[model]["params"]))
            for row in rows
            for model in ("gjr", "a4f")
        ),
        "every_gjr_refit_has_converged_start": all(
            row["gjr"]["n_converged_starts"] >= 1 for row in rows
        ),
        "every_a4f_refit_has_converged_start": all(
            row["a4f"]["n_converged_starts"] >= 1 for row in rows
        ),
        "all_gjr_selected_fits_stationary": all(value < 1.0 for value in gjr_persistence),
        "all_a4f_selected_fits_inside_model_gate": all(
            value < 0.999 for value in a4f_persistence
        ),
    }
    passed = all(dm_checks.values()) and all(convergence_checks.values())

    return {
        "label": label,
        "status": "PASS" if passed else "FAIL",
        "dm_reproduction": {
            "checks": dm_checks,
            "recomputed": report,
        },
        "convergence_stationarity": {
            "checks": convergence_checks,
            "gjr_persistence_min": float(min(gjr_persistence)),
            "gjr_persistence_max": float(max(gjr_persistence)),
            "a4f_persistence_min": float(min(a4f_persistence)),
            "a4f_persistence_max": float(max(a4f_persistence)),
            "gjr_min_converged_starts": int(
                min(row["gjr"]["n_converged_starts"] for row in rows)
            ),
            "a4f_min_converged_starts": int(
                min(row["a4f"]["n_converged_starts"] for row in rows)
            ),
        },
        "refits": rows,
    }


def main() -> int:
    with RESULTS_PATH.open() as handle:
        stored_results = json.load(handle)

    snapshot_path = Path(experiment.SNAPSHOT_PATH)
    expected_hash = stored_results["data_provenance"]["snapshot_sha256"]
    actual_hash = sha256_file(snapshot_path)
    df = experiment.load_snapshot()
    last_date = str(df.index[-1].date())

    primary_panel, primary_info = experiment.run_rolling(
        df,
        experiment.OOS_START,
        last_date,
        "PARAMETER AUDIT / primary",
    )
    multistart_panel, multistart_info = experiment.run_rolling(
        df,
        experiment.OOS_START,
        last_date,
        "PARAMETER AUDIT / multistart",
        extra_starts=experiment.EXTRA_STARTS,
    )

    primary = audit_run(
        "primary_3start_full_oos",
        primary_panel,
        primary_info,
        stored_results["dm_reports"]["full_extended_oos"],
    )
    multistart = audit_run(
        "symmetric_12start_full_oos",
        multistart_panel,
        multistart_info,
        stored_results["dm_reports"]["multistart_full_extended_oos"],
    )
    provenance_checks = {
        "snapshot_sha256_matches": actual_hash == expected_hash,
        "snapshot_has_no_duplicate_dates": not df.index.has_duplicates,
        "snapshot_last_date_matches": last_date
        == stored_results["configuration"]["oos_end_extended"],
    }
    passed = (
        all(provenance_checks.values())
        and primary["status"] == "PASS"
        and multistart["status"] == "PASS"
    )
    payload = {
        "experiment_id": "K1685",
        "purpose": "post-hoc convergence and persistence verification of orphaned compute output",
        "source_result": RESULTS_PATH.name,
        "provenance_checks": provenance_checks,
        "primary": primary,
        "multistart": multistart,
        "overall_status": "PASS" if passed else "FAIL",
    }
    atomic_write_json(AUDIT_PATH, payload)
    print(f"parameter audit: {payload['overall_status']} -> {AUDIT_PATH}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
