#!/usr/bin/env python3
"""K1489: feasibility audit for GPR Acts/Threats volatility forecasting."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

import pandas as pd


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RESULTS_PATH = HERE / "k1489_results.json"

GPR_DAILY_URL = "https://www.matteoiacoviello.com/gpr_files/data_gpr_daily_recent.xls"
REQUESTED_ASSETS = ("SPY", "GLD", "XLE", "ITA")

KNOWN_PRICE_SNAPSHOTS = [
    ROOT / "paper" / "volatility-absorption" / "data" / "spy_gld_tlt_qqq_eem_vix_2005-2026.csv",
    ROOT / "paper" / "leverage-direction" / "data" / "spy_qqq_gld_tlt_eem_iwm_slv_btc_usd_vix_2010-2026.csv",
    ROOT / "paper" / "garch-x-vix" / "data" / "spy_vix_qqq_eem_fez_2000-2026.csv",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def check_url(url: str, timeout: int = 10) -> dict:
    try:
        with urlopen(url, timeout=timeout) as response:
            sample = response.read(64)
        return {"ok": True, "sample_bytes": len(sample), "error": None}
    except Exception as exc:  # network is often disabled in automation sandboxes
        return {"ok": False, "sample_bytes": 0, "error": f"{type(exc).__name__}: {exc}"}


def local_gpr_candidates() -> list[str]:
    matches: list[str] = []
    for base_name in ("experiments", "storage", "paper", "data", "/tmp", "/private/tmp"):
        base = Path(base_name)
        if not base.is_absolute():
            base = ROOT / base
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            lowered = path.name.lower()
            if any(token in lowered for token in ("gpr", "geopolit", "iacoviello", "caldara")):
                try:
                    matches.append(str(path.relative_to(ROOT)))
                except ValueError:
                    matches.append(str(path))
    return sorted(matches)


def inspect_price_snapshot(path: Path) -> dict:
    if not path.exists():
        return {"path": str(path.relative_to(ROOT)), "exists": False, "assets": {}}
    df = pd.read_csv(path, nrows=5)
    columns = {str(c).lower() for c in df.columns}
    assets = {}
    for asset in REQUESTED_ASSETS:
        token = asset.lower()
        has_close = any(c in columns for c in (f"{token}_close", f"{token}_adj_close"))
        assets[asset] = bool(has_close)
    return {
        "path": str(path.relative_to(ROOT)),
        "exists": True,
        "assets": assets,
        "columns_checked": len(columns),
    }


def summarize_price_availability() -> dict:
    snapshots = [inspect_price_snapshot(path) for path in KNOWN_PRICE_SNAPSHOTS]
    by_asset = {asset: [] for asset in REQUESTED_ASSETS}
    for snapshot in snapshots:
        for asset, available in snapshot.get("assets", {}).items():
            if available:
                by_asset[asset].append(snapshot["path"])
    return {
        "snapshots": snapshots,
        "by_asset": {
            asset: {
                "available": bool(paths),
                "paths": paths,
            }
            for asset, paths in by_asset.items()
        },
    }


def prior_k446_summary() -> dict:
    path = ROOT / "experiments" / "k446" / "k446_gpr_vol_results.json"
    if not path.exists():
        return {"available": False, "path": str(path.relative_to(ROOT))}
    data = json.loads(path.read_text(encoding="utf-8"))
    corr = data.get("diagnostics", {}).get("correlations", {}).get("contemporaneous", {})
    key = data.get("key_findings", {})
    rv5_decomp = data.get("forecasting_rv5_fwd", {}).get("gpr_decomposed", {})
    rv21_decomp = data.get("forecasting_rv21_fwd", {}).get("gpr_decomposed", {})
    return {
        "available": True,
        "path": str(path.relative_to(ROOT)),
        "sample_period": data.get("data_sources", {}).get("sample_period"),
        "n_observations": data.get("data_sources", {}).get("n_observations"),
        "gpr_act_corr_vix": corr.get("gpr_act", {}).get("vix"),
        "gpr_threat_corr_vix": corr.get("gpr_threat", {}).get("vix"),
        "gpr_act_corr_rv21": corr.get("gpr_act", {}).get("rv21"),
        "gpr_threat_corr_rv21": corr.get("gpr_threat", {}).get("rv21"),
        "gpr_adds_to_vix_for_5d_rv": key.get("gpr_adds_to_vix_for_5d_rv"),
        "partial_corr_gpr_controlling_vix_5d": key.get("partial_corr_gpr_controlling_vix_5d"),
        "gpr_decomposed_rv5_oos": {
            "n_oos": rv5_decomp.get("n_oos"),
            "r2_oos": rv5_decomp.get("r2_oos"),
            "dm_vs_baseline": rv5_decomp.get("dm_vs_baseline"),
        },
        "gpr_decomposed_rv21_oos": {
            "n_oos": rv21_decomp.get("n_oos"),
            "r2_oos": rv21_decomp.get("r2_oos"),
            "dm_vs_baseline": rv21_decomp.get("dm_vs_baseline"),
        },
    }


def build_results() -> dict:
    gpr_candidates = local_gpr_candidates()
    price_availability = summarize_price_availability()
    has_raw_gpr = any(
        Path(path).name.lower().endswith((".xls", ".xlsx", ".csv", ".parquet"))
        and "gpr" in Path(path).name.lower()
        for path in gpr_candidates
    )
    missing_assets = [
        asset
        for asset, info in price_availability["by_asset"].items()
        if not info["available"]
    ]
    gpr_download = check_url(GPR_DAILY_URL)

    blockers = []
    if not has_raw_gpr and not gpr_download["ok"]:
        blockers.append(
            {
                "type": "missing_raw_gpr_acts_threats",
                "detail": (
                    "No canonical local GPRD/GPRA/GPRT raw file was found, and the official "
                    "daily XLS could not be downloaded in this sandbox."
                ),
            }
        )
    if missing_assets:
        blockers.append(
            {
                "type": "missing_requested_asset_prices",
                "detail": f"Local reusable snapshots lack close prices for: {', '.join(missing_assets)}.",
            }
        )

    can_run_full = not blockers
    return {
        "experiment_id": "k1489",
        "title": "GPR daily Acts vs Threats decomposition feasibility for volatility forecasting",
        "run_timestamp": utc_now(),
        "verdict": {
            "overall": "BLOCKED_ON_DATA" if not can_run_full else "READY_TO_RUN",
            "can_honestly_run_full_har_rv_now": can_run_full,
            "plain_english": (
                "The design is valid and differentiated from K446, but the current local "
                "environment lacks a reproducible raw GPRD/Acts/Threats file and lacks XLE/ITA "
                "price snapshots. Running HAR-RV forecasts now would require live downloads, "
                "which fail under the current DNS-restricted sandbox."
            )
            if not can_run_full
            else "All required data inputs are available for a lag-respected HAR-RV run.",
        },
        "proposed_design": {
            "research_question": (
                "Do daily GPR Acts and Threats components add asymmetric predictive power for "
                "SPY/GLD/XLE/ITA realized volatility beyond own RV and VIX?"
            ),
            "target_assets": list(REQUESTED_ASSETS),
            "candidate_models": [
                "HAR-RV baseline: RV_1d, RV_5d, RV_22d, all lagged one trading day",
                "HAR-RV + VIX_lag1 where VIX is available",
                "HAR-RV + GPRD_ACT_lag1 + GPRD_THREAT_lag1",
                "HAR-RV + VIX_lag1 + ACT_lag1 + THREAT_lag1",
            ],
            "forecast_horizons": [1, 5, 22],
            "tests": [
                "DM test on QLIKE/MSE loss differentials",
                "stationary block bootstrap with fixed seed",
                "Harvey-style high-threshold screen for multiple testing caution",
            ],
            "lookahead_rule": "All predictors must be shifted by at least one trading day before forecasting RV_t or forward RV.",
            "random_seed": 42,
        },
        "literature_checked": [
            {
                "source": "Caldara and Iacoviello (2022), American Economic Review",
                "url": "https://www.aeaweb.org/articles?id=10.1257/aer.20191823",
                "use_in_design": "Primary GPR index and Acts/Threats decomposition motivation.",
            },
            {
                "source": "IMF Global Financial Stability Report, April 2025, Chapter 2",
                "url": "https://www.imf.org/en/publications/gfsr/issues/2025/04/22/global-financial-stability-report-april-2025",
                "use_in_design": "Motivates asset-price and financial-stability relevance of major geopolitical events.",
            },
            {
                "source": "Dai, Dai, and Zhou (2024), GJR-GARCH-MIDAS geopolitical risk and agricultural volatility",
                "url": "https://arxiv.org/abs/2404.01641",
                "use_in_design": "Supports testing geopolitical risk as a low-frequency volatility driver, while keeping OOS tests strict.",
            },
        ],
        "local_input_audit": {
            "official_gpr_download": {
                "url": GPR_DAILY_URL,
                **gpr_download,
            },
            "local_gpr_related_files": gpr_candidates,
            "has_canonical_raw_gpr_acts_threats": has_raw_gpr,
            "price_availability": price_availability,
        },
        "prior_evidence": {
            "knowledge_hits": [
                "K100: generic geopolitical proxies added little incremental volatility information beyond VIX.",
                "K446: broad daily GPR showed weak/reversed predictive content; VIX->GPR stronger than GPR->RV.",
            ],
            "k446_results_summary": prior_k446_summary(),
        },
        "blocking_conditions": blockers,
        "required_to_unlock": [
            {
                "artifact": "experiments/k1489/data/gpr_daily_recent.csv",
                "columns": ["date", "GPRD", "GPRD_ACT", "GPRD_THREAT"],
                "source": GPR_DAILY_URL,
                "rule": "Pin the downloaded file locally; do not rely on live download inside the experiment.",
            },
            {
                "artifact": "experiments/k1489/data/prices_spy_gld_xle_ita_vix.csv",
                "columns": [
                    "date",
                    "spy_close",
                    "gld_close",
                    "xle_close",
                    "ita_close",
                    "vix_close",
                ],
                "rule": "Use adjusted closes if available; document vendor and download timestamp.",
            },
        ],
        "honesty_note": (
            "No regression coefficients, DM statistics, or article-ready claims were produced in this run. "
            "The only empirical quantities reused are from the already committed K446 results artifact."
        ),
    }


def main() -> None:
    results = build_results()
    RESULTS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Saved {RESULTS_PATH}")


if __name__ == "__main__":
    main()
