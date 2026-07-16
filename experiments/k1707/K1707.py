#!/usr/bin/env python3
"""K1707: option-auction stress-support audit on author pseudo-data.

The public Dataverse file is independently noised pseudo-data and explicitly
cannot reproduce the paper.  The confirmatory interaction is therefore guarded
by pre-registered support gates and is not run when stress support is absent.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import tempfile
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
EXP = ROOT / "experiments" / "k1707"
DATA = EXP / "data"
FIGURES = EXP / "figures"
CACHE = ROOT / "storage" / "cache" / "k1707"
RAW = CACHE / "opra_pseudo.sas7bdat"
VIX_CACHE = CACHE / "vix_fred_2020.csv"
RESULTS = EXP / "K1707_results.json"

SEED = 42
RAW_FILE_ID = 10844401
RAW_URL = f"https://dataverse.harvard.edu/api/access/datafile/{RAW_FILE_ID}"
RAW_MD5 = "f15b6286a6954f059bb59c31227eeb66"
DATAVERSE_DOI = "doi:10.7910/DVN/LMB13N"
VIX_URL = (
    "https://fred.stlouisfed.org/graph/fredgraph.csv?"
    "id=VIXCLS&cosd=2020-08-01&coed=2020-12-31"
)
VIX_SHA256 = "cc3575202272b4cf18a43b4ab95fc6cabd82195e224999a2da39337341bffb78"
HIGH_STRESS_VIX = 30.0
MIN_DATES = 80
MIN_HIGH_DATES = 30
MIN_SYMBOLS = 10
CHUNK_SIZE = 250_000
OUTCOMES = ("PIMP_C", "EffectiveSpread_C", "EQ", "MULTIPLE_IND")

REFERENCES = [
    {
        "authors": "Khan, Hendershott, Riordan",
        "year": 2026,
        "title": "Option Auctions",
        "journal": "Review of Financial Studies 39(3):783-834",
        "doi": "10.1093/rfs/hhaf043",
    },
    {
        "authors": "Bryzgalova, Pavlova, Sikorskaya",
        "year": 2023,
        "title": "Retail Trading in Options and the Rise of the Big Three Wholesalers",
        "journal": "Journal of Finance",
        "doi": "10.1111/jofi.13285",
    },
    {
        "authors": "Anand, Muravyev",
        "year": 2024,
        "title": "Does Internalization Impact Quote Competition?",
        "journal": "SSRN",
        "ssrn": "4891227",
    },
    {
        "authors": "Battalio, Jennings",
        "year": 2024,
        "title": "On the Potential Cost of Mandating Qualified Auctions for Marketable Retail Orders",
        "journal": "Journal of Investing 33(1):69-99",
        "doi": "10.3905/joi.2023.1.287",
    },
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def md5(path: Path) -> str:
    h = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2, allow_nan=False)
            fh.flush()
            os.fsync(fh.fileno())
        with open(tmp_name, encoding="utf-8") as fh:
            json.load(fh)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def download(url: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".download")
    os.close(fd)
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "volpred-k1707/1.0"})
        with urllib.request.urlopen(request, timeout=90) as response, open(tmp_name, "wb") as out:
            shutil.copyfileobj(response, out, length=1024 * 1024)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def ensure_sources(refresh: bool = False) -> None:
    if refresh or not RAW.exists():
        download(RAW_URL, RAW)
    observed = md5(RAW)
    if observed != RAW_MD5:
        raise RuntimeError(f"raw MD5 mismatch: expected={RAW_MD5} observed={observed}")
    if refresh or not VIX_CACHE.exists():
        download(VIX_URL, VIX_CACHE)
    observed_vix = sha256(VIX_CACHE)
    if observed_vix != VIX_SHA256:
        raise RuntimeError(
            f"FRED VIX SHA256 mismatch: expected={VIX_SHA256} observed={observed_vix}"
        )


def _add_stats(target: dict[tuple[pd.Timestamp, int, str], list[float]], key: tuple[pd.Timestamp, int, str], values: pd.Series) -> None:
    x = pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if x.empty:
        return
    row = target[key]
    row[0] += float(len(x))
    row[1] += float(x.sum())
    row[2] += float(np.square(x.to_numpy(dtype=float)).sum())


def aggregate_raw(path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    needed = ["DATE", "SYMBOL_ONLY", "AUCTION_IND", *OUTCOMES]
    stats: dict[tuple[pd.Timestamp, int, str], list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
    dates: set[pd.Timestamp] = set()
    symbols: set[str] = set()
    total_rows = 0
    auction_rows = 0

    reader = pd.read_sas(
        path,
        format="sas7bdat",
        iterator=True,
        chunksize=CHUNK_SIZE,
        encoding="latin1",
    )
    for chunk in reader:
        missing = sorted(set(needed) - set(chunk.columns))
        if missing:
            raise RuntimeError(f"raw dataset missing required columns: {missing}")
        chunk = chunk[needed].copy()
        chunk["DATE"] = pd.to_datetime(chunk["DATE"], errors="coerce").dt.normalize()
        chunk["AUCTION_IND"] = pd.to_numeric(chunk["AUCTION_IND"], errors="coerce")
        if chunk["DATE"].isna().any():
            raise RuntimeError("missing or invalid DATE in pseudo-data")
        if chunk["AUCTION_IND"].isna().any() or not chunk["AUCTION_IND"].isin([0, 1]).all():
            raise RuntimeError("missing or invalid AUCTION_IND in pseudo-data")
        if chunk["SYMBOL_ONLY"].isna().any() or (chunk["SYMBOL_ONLY"].astype(str).str.strip() == "").any():
            raise RuntimeError("missing SYMBOL_ONLY in pseudo-data")
        total_rows += len(chunk)
        auction_rows += int((chunk["AUCTION_IND"] == 1).sum())
        dates.update(chunk["DATE"].unique().tolist())
        symbols.update(str(x) for x in chunk["SYMBOL_ONLY"].dropna().unique())
        for (date, auction), group in chunk.groupby(["DATE", "AUCTION_IND"], sort=False):
            a = int(auction)
            for outcome in OUTCOMES:
                _add_stats(stats, (pd.Timestamp(date), a, outcome), group[outcome])

    rows: list[dict[str, Any]] = []
    for (date, auction, outcome), (count, total, total_sq) in sorted(stats.items()):
        mean = total / count
        variance = max(0.0, (total_sq - total * total / count) / (count - 1)) if count > 1 else math.nan
        rows.append(
            {
                "date": date,
                "auction": auction,
                "outcome": outcome,
                "n": int(count),
                "mean": mean,
                "sd": math.sqrt(variance) if count > 1 else math.nan,
            }
        )
    panel = pd.DataFrame(rows)
    audit = {
        "raw_rows": total_rows,
        "auction_rows": auction_rows,
        "auction_share": auction_rows / total_rows,
        "distinct_dates": len(dates),
        "date_min": min(dates).strftime("%Y-%m-%d"),
        "date_max": max(dates).strftime("%Y-%m-%d"),
        "distinct_symbols": len(symbols),
        "symbols": sorted(symbols),
    }
    return panel, audit


def attach_lagged_vix(panel: pd.DataFrame, vix_path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    vix = pd.read_csv(vix_path)
    if list(vix.columns) != ["observation_date", "VIXCLS"]:
        raise RuntimeError(f"unexpected FRED columns: {list(vix.columns)}")
    vix["observation_date"] = pd.to_datetime(vix["observation_date"], errors="raise")
    vix["VIXCLS"] = pd.to_numeric(vix["VIXCLS"], errors="coerce")
    date_min = min(panel["date"].min(), vix["observation_date"].min())
    date_max = max(panel["date"].max(), vix["observation_date"].max())
    calendar = pd.DataFrame({"date": pd.date_range(date_min, date_max, freq="D")})
    calendar = calendar.merge(
        vix.rename(columns={"observation_date": "date"}), on="date", how="left", validate="one_to_one"
    )
    # Explicit lookahead guard: the signal known on calendar day t is the last
    # available VIX close strictly before t. Weekend ffill occurs before lagging.
    calendar["vix_signal_lag1"] = calendar["VIXCLS"].ffill().shift(1)
    panel = panel.merge(calendar[["date", "vix_signal_lag1"]], on="date", how="left", validate="many_to_one")
    if panel["vix_signal_lag1"].isna().any():
        raise RuntimeError("lagged VIX missing for one or more pseudo dates")
    panel["high_stress"] = (panel["vix_signal_lag1"] >= HIGH_STRESS_VIX).astype(int)

    dates = panel[["date", "vix_signal_lag1", "high_stress"]].drop_duplicates()
    weekend = dates[dates["date"].dt.dayofweek >= 5]
    audit = {
        "signal_formula": "VIXCLS.ffill().shift(1)",
        "threshold": HIGH_STRESS_VIX,
        "high_stress_dates": int(dates["high_stress"].sum()),
        "vix_min": float(dates["vix_signal_lag1"].min()),
        "vix_max": float(dates["vix_signal_lag1"].max()),
        "vix_median": float(dates["vix_signal_lag1"].median()),
        "weekend_dates": [d.strftime("%Y-%m-%d") for d in weekend["date"]],
        "weekend_share": len(weekend) / len(dates),
    }
    return panel, audit


def support_gate(data_audit: dict[str, Any], vix_audit: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "distinct_dates_at_least_80": data_audit["distinct_dates"] >= MIN_DATES,
        "high_stress_dates_at_least_30": vix_audit["high_stress_dates"] >= MIN_HIGH_DATES,
        "distinct_symbols_at_least_10": data_audit["distinct_symbols"] >= MIN_SYMBOLS,
        "no_weekend_pseudo_dates": vix_audit["weekend_share"] == 0.0,
    }
    return {"passed": all(checks.values()), "checks": checks}


def descriptive_benefits(panel: pd.DataFrame) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    overall: list[dict[str, Any]] = []
    daily: list[dict[str, Any]] = []
    for metric in ("mean", "sd"):
        for outcome in OUTCOMES:
            subset = panel[panel["outcome"] == outcome]
            pivot = subset.pivot(index="date", columns="auction", values=metric)
            if not {0, 1}.issubset(pivot.columns):
                continue
            sign = 1.0 if outcome == "PIMP_C" and metric == "mean" else -1.0
            benefit = sign * (pivot[1] - pivot[0])
            vix = subset.drop_duplicates("date").set_index("date")["vix_signal_lag1"].reindex(benefit.index)
            valid = benefit.notna() & vix.notna()
            overall.append(
                {
                    "outcome": outcome,
                    "statistic": metric,
                    "auction_benefit_mean": float(benefit[valid].mean()),
                    "n_dates": int(valid.sum()),
                }
            )
            for date in benefit.index[valid]:
                daily.append(
                    {
                        "date": date.strftime("%Y-%m-%d"),
                        "outcome": outcome,
                        "statistic": metric,
                        "auction_benefit": float(benefit.loc[date]),
                        "vix_signal_lag1": float(vix.loc[date]),
                    }
                )
    return overall, daily


def write_panel(panel: pd.DataFrame) -> Path:
    path = DATA / "daily_auction_panel.csv.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    panel_out = panel.copy()
    panel_out["date"] = panel_out["date"].dt.strftime("%Y-%m-%d")
    panel_out.to_csv(tmp, index=False, compression={"method": "gzip", "mtime": 0})
    os.replace(tmp, path)
    return path


def make_figures(panel: pd.DataFrame, gate: dict[str, Any], overall: list[dict[str, Any]]) -> list[Path]:
    FIGURES.mkdir(parents=True, exist_ok=True)
    dates = panel[["date", "vix_signal_lag1"]].drop_duplicates().sort_values("date")

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    axes[0].plot(dates["date"], dates["vix_signal_lag1"], marker="o", color="#2563eb")
    axes[0].axhline(HIGH_STRESS_VIX, color="#dc2626", linestyle="--", label="fixed stress gate: 30")
    axes[0].set_title("Lagged VIX support on pseudo dates")
    axes[0].set_ylabel("VIX close known before pseudo date")
    axes[0].tick_params(axis="x", rotation=45)
    axes[0].legend(frameon=False)

    labels = [x.replace("_", "\n") for x in gate["checks"]]
    values = [1 if x else 0 for x in gate["checks"].values()]
    colors = ["#16a34a" if x else "#dc2626" for x in values]
    axes[1].bar(range(len(values)), values, color=colors)
    axes[1].set_xticks(range(len(values)), labels, fontsize=8)
    axes[1].set_ylim(0, 1.15)
    axes[1].set_yticks([0, 1], ["FAIL", "PASS"])
    axes[1].set_title("Pre-registered data-support gates")
    fig.tight_layout()
    support_path = FIGURES / "k1707_stress_support.png"
    fig.savefig(support_path, dpi=170, bbox_inches="tight", metadata={"Software": "matplotlib"})
    plt.close(fig)

    means = [x for x in overall if x["statistic"] == "mean" and x["outcome"] != "MULTIPLE_IND"]
    fig, ax = plt.subplots(figsize=(8, 4.8))
    ax.bar([x["outcome"] for x in means], [x["auction_benefit_mean"] for x in means], color="#7c3aed")
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_title("Pseudo-data auction benefit (descriptive only)")
    ax.set_ylabel("Benefit; positive means auction is better")
    ax.tick_params(axis="x", rotation=20)
    fig.tight_layout()
    desc_path = FIGURES / "k1707_descriptive_benefits.png"
    fig.savefig(desc_path, dpi=170, bbox_inches="tight", metadata={"Software": "matplotlib"})
    plt.close(fig)
    return [support_path, desc_path]


def run(refresh_source: bool = False) -> dict[str, Any]:
    np.random.seed(SEED)
    ensure_sources(refresh=refresh_source)
    panel, data_audit = aggregate_raw(RAW)
    panel, vix_audit = attach_lagged_vix(panel, VIX_CACHE)
    gate = support_gate(data_audit, vix_audit)
    if gate["passed"]:
        raise RuntimeError(
            "Pinned pseudo-data unexpectedly passed the support gate; the confirmatory "
            "interaction estimator must be implemented and independently reviewed before use."
        )
    overall, daily = descriptive_benefits(panel)
    panel_path = write_panel(panel)
    DATA.mkdir(parents=True, exist_ok=True)
    frozen_vix = DATA / "vix_fred_2020.csv"
    shutil.copyfile(VIX_CACHE, frozen_vix)
    figures = make_figures(panel, gate, overall)

    verdict = "INSUFFICIENT_STRESS_SUPPORT"
    result: dict[str, Any] = {
        "experiment_id": "K1707",
        "status": verdict,
        "methodology_type": "descriptive pseudo-data adequacy audit",
        "run_timestamp_policy": "omitted_for_byte_reproducibility",
        "seed": SEED,
        "research_question": "Does option-auction execution-quality benefit collapse in pre-known high-VIX states?",
        "data": {
            "source": "Harvard Dataverse author pseudo-data",
            "doi": DATAVERSE_DOI,
            "license": "CC0-1.0",
            "raw_datafile_id": RAW_FILE_ID,
            "raw_md5": md5(RAW),
            "raw_bytes": RAW.stat().st_size,
            "author_caveat": "Randomized, independently noised, anonymized and smaller pseudo-data; cannot reproduce paper results; timestamps differ from original OPRA.",
            **data_audit,
            **vix_audit,
        },
        "pre_registered_support_gate": gate,
        "confirmatory_analysis": {
            "executed": False,
            "fixed_high_stress_threshold": HIGH_STRESS_VIX,
            "interaction": "AUCTION_IND x 1[VIX_signal_lag1 >= 30]",
            "reason_not_executed": "One or more pre-registered data-support checks failed.",
            "holm_family": ["PIMP_C", "EffectiveSpread_C", "EQ", "dispersion"],
            "placebo_and_randomization_inference": "required only if support gate passes",
        },
        "descriptive_only": {
            "auction_benefits": overall,
            "daily_benefits": daily,
            "warning": "No VIX slopes or p-values. These values describe independently noised pseudo-data and are not evidence about real option-market stress states.",
        },
        "lookahead_policy": {
            "explicit_signal_code": "calendar['vix_signal_lag1'] = calendar['VIXCLS'].ffill().shift(1)",
            "same_day_vix_used": False,
        },
        "limitations": [
            "Public file is pseudo-data, not original OPRA observations.",
            "Only 16 pseudo dates and 3 anonymized underlyings are present.",
            "Pseudo dates include weekends and differ from original timestamps.",
            "No pseudo date reaches the fixed pre-registered VIX>=30 stress threshold.",
            "Absence of support is not a null estimate and cannot establish that auction benefits persist or collapse in stress.",
        ],
        "references": REFERENCES,
        "artifacts": {
            "analysis_panel": str(panel_path.relative_to(ROOT)),
            "vix": str(frozen_vix.relative_to(ROOT)),
            "figures": [str(p.relative_to(ROOT)) for p in figures],
        },
    }

    manifest = {
        "experiment_id": "K1707",
        "raw": {"file_id": RAW_FILE_ID, "md5": RAW_MD5, "bytes": RAW.stat().st_size},
        "vix_sha256": sha256(frozen_vix),
        "expected_vix_sha256": VIX_SHA256,
        "analysis_panel_sha256": sha256(panel_path),
        "script_sha256": sha256(Path(__file__)),
        "source_urls": {"dataverse": RAW_URL, "fred_vixcls": VIX_URL},
    }
    atomic_json(DATA / "source_manifest.json", manifest)
    result["artifacts"]["source_manifest"] = "experiments/k1707/data/source_manifest.json"
    atomic_json(RESULTS, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh-source", action="store_true")
    args = parser.parse_args()
    result = run(refresh_source=args.refresh_source)
    print(json.dumps({"status": result["status"], "gate": result["pre_registered_support_gate"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
