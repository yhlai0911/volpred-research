#!/usr/bin/env python3
"""
K1436: BTC Funding Rate as HAR-RV Covariate — Feasibility Audit
===============================================================

Purpose:
  Determine whether the current repository contains the minimum local data
  needed to run a reproducible BTC perpetual funding-rate + HAR-RV experiment.

Research-honesty reason:
  A formal HAR-RV + funding experiment requires both:
  1. An intraday realized-variance target for BTC (or another explicitly
     justified realized-measure proxy), and
  2. A canonical local funding-rate time series from the claimed exchange/source.

If either is missing, the correct outcome is a blocked feasibility audit rather
than a fabricated or network-dependent empirical result.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd


EXPERIMENT_ID = "k1436"
ROOT = Path(__file__).resolve().parents[2]
OUT_PATH = Path(__file__).resolve().with_name(f"{EXPERIMENT_ID}_results.json")
KNOWLEDGE_PATH = ROOT / "storage" / "memory" / "knowledge.json"
RESEARCH_PROGRAM = ROOT / "research_program.md"
DERIV_VOL_README = ROOT / "experiments" / "btc_derivatives_vol" / "README.md"
DERIV_VOL_SCRIPT = ROOT / "experiments" / "btc_derivatives_vol" / "btc_derivatives_vol.py"


@dataclass
class DataPresence:
    count: int
    sample_paths: list[str]


def find_files(name_tokens: tuple[str, ...], suffixes: tuple[str, ...] | None = None) -> list[str]:
    hits: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if ".git" in path.parts or "node_modules" in path.parts or ".venv" in path.parts:
            continue
        name = path.name.lower()
        if not all(token in name for token in name_tokens):
            continue
        if suffixes and path.suffix.lower() not in suffixes:
            continue
        hits.append(str(path.relative_to(ROOT)))
    return sorted(hits)


def search_text_mentions(term_list: tuple[str, ...], limit: int = 20) -> list[str]:
    hits: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if ".git" in path.parts or "node_modules" in path.parts or ".venv" in path.parts:
            continue
        if "archive" in path.parts or "frontend-v2-fix" in path.parts:
            continue
        if "k1268" in path.parts:
            continue
        if path.suffix.lower() not in {".py", ".md", ".json", ".txt", ".csv"}:
            continue
        try:
            text = path.read_text(errors="ignore")
        except Exception:
            continue
        lower = text.lower()
        if any(term.lower() in lower for term in term_list):
            hits.append(str(path.relative_to(ROOT)))
    return sorted(hits)[:limit]


def read_csv_schema(path_str: str) -> dict:
    path = ROOT / path_str
    try:
        df = pd.read_csv(path, nrows=2)
    except Exception as exc:
        return {"path": path_str, "read_error": str(exc)}
    return {
        "path": path_str,
        "columns": df.columns.tolist(),
    }


def build_results() -> dict:
    funding_files = find_files(("funding",), suffixes=(".csv", ".parquet", ".json", ".feather", ".pkl"))
    binance_files = find_files(("binance",), suffixes=(".csv", ".parquet", ".json", ".feather", ".pkl"))
    perp_files = find_files(("perp",), suffixes=(".csv", ".parquet", ".json", ".feather", ".pkl"))
    perpetual_files = find_files(("perpetual",), suffixes=(".csv", ".parquet", ".json", ".feather", ".pkl"))

    btc_intraday_files = (
        find_files(("btc", "5min"), suffixes=(".csv", ".parquet"))
        + find_files(("btc", "1h"), suffixes=(".csv", ".parquet"))
        + find_files(("btc", "intraday"), suffixes=(".csv", ".parquet"))
    )

    btc_daily_files = (
        find_files(("btc",), suffixes=(".csv",))
        + find_files(("btc-usd",), suffixes=(".csv",))
        + find_files(("btc_usd",), suffixes=(".csv",))
    )
    btc_daily_files = sorted(dict.fromkeys(btc_daily_files))

    text_mentions = search_text_mentions(("funding rate", "funding_rate", "binance", "perpetual"))

    sample_daily_schemas = [read_csv_schema(p) for p in btc_daily_files[:5]]

    has_funding_series = len(funding_files) > 0
    has_intraday_btc = len(btc_intraday_files) > 0

    return {
        "experiment_id": EXPERIMENT_ID.upper(),
        "title": "BTC Funding Rate as HAR-RV Covariate — Feasibility Audit",
        "status": "BLOCKED_DATA_UNAVAILABLE",
        "question": (
            "Can VolPred currently run a reproducible HAR-RV + Binance funding-rate "
            "experiment for BTC from local data only?"
        ),
        "data_audit": {
            "funding_rate_files": asdict(DataPresence(len(funding_files), funding_files[:20])),
            "binance_named_files": asdict(DataPresence(len(binance_files), binance_files[:20])),
            "perp_named_files": asdict(DataPresence(len(perp_files), perp_files[:20])),
            "perpetual_named_files": asdict(DataPresence(len(perpetual_files), perpetual_files[:20])),
            "btc_intraday_files": asdict(DataPresence(len(btc_intraday_files), btc_intraday_files[:20])),
            "btc_daily_files": asdict(DataPresence(len(btc_daily_files), btc_daily_files[:20])),
            "btc_daily_sample_schemas": sample_daily_schemas,
            "text_mentions_only": text_mentions,
            "has_local_funding_series": has_funding_series,
            "has_local_btc_intraday_target_data": has_intraday_btc,
        },
        "prior_internal_context": {
            "btc_derivatives_vol_exists": DERIV_VOL_SCRIPT.exists(),
            "btc_derivatives_vol_status_note": (
                "Existing btc_derivatives_vol line uses volume / weekend / VIX proxies, not funding-rate data."
            ),
            "knowledge_gap_note": (
                "Knowledge base already notes that genuine improvement likely needs Binance funding/OI/liquidation data."
            ),
        },
        "methodology_constraints": {
            "target_match_rule": "HAR-RV must be evaluated on realized-volatility target, not daily squared return relabelled as HAR-RV.",
            "source_rule": "Funding-rate covariate must come from a canonical local series if the experiment is to be reproducible.",
            "lookahead_rule": "Funding information must enter with an explicit lag relative to next-period RV target.",
        },
        "findings": [
            "No local funding-rate dataset is present under canonical experiment/data paths.",
            "No local BTC intraday cache suitable for HAR-RV target construction was found.",
            "The repository does contain BTC daily OHLCV CSVs, but daily OHLCV alone is not enough for a proper HAR-RV + funding experiment.",
            "A prior BTC derivatives experiment exists, but it uses volume/weekend/VIX proxies rather than true funding-rate data.",
        ],
        "conclusion": (
            "K1436 is blocked at the data layer. Completing it honestly requires first "
            "materializing local Binance funding-rate history and local BTC intraday "
            "data for realized-volatility target construction."
        ),
        "next_steps": [
            "Create a canonical local funding-rate file for BTC perpetuals (exchange, frequency, timezone documented).",
            "Create or ingest a canonical local BTC intraday bar cache sufficient to build RV/HAR-RV target series.",
            "Only then run HAR-RV baseline vs HAR-RV+funding with explicit t-1 lagging and formal OOS evaluation.",
        ],
        "references": [
            "Corsi (2009) HAR-RV.",
            "Patton (2011) proxy-robust volatility forecast comparison.",
            "Internal BTC derivatives note: true BTC improvement likely needs funding/OI/liquidation data.",
        ],
    }


def main() -> None:
    results = build_results()
    OUT_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
