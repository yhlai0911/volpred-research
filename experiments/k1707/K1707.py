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
import time
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
AGGREGATE_SNAPSHOT = DATA / "raw_aggregate_snapshot.json"

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
BENEFIT_OUTCOMES = ("PIMP_C", "EffectiveSpread_C", "EQ")

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


def _add_stats(target: dict[Any, list[float]], key: Any, values: pd.Series) -> None:
    x = pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if x.empty:
        return
    row = target[key]
    row[0] += float(len(x))
    row[1] += float(x.sum())
    row[2] += float(np.square(x.to_numpy(dtype=float)).sum())


def _stats_frame(stats: dict[Any, list[float]], key_names: list[str]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for key, (count, total, total_sq) in sorted(stats.items()):
        keys = key if isinstance(key, tuple) else (key,)
        mean = total / count
        variance = (
            max(0.0, (total_sq - total * total / count) / (count - 1))
            if count > 1
            else math.nan
        )
        row = dict(zip(key_names, keys, strict=True))
        row.update(
            {
                "n": int(count),
                "mean": mean,
                "sd": math.sqrt(variance) if count > 1 else math.nan,
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def aggregate_raw(path: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    needed = ["DATE", "SYMBOL_ONLY", "AUCTION_IND", *OUTCOMES]
    stats: dict[tuple[pd.Timestamp, int, str], list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
    pooled_stats: dict[tuple[int, str], list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
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
                _add_stats(pooled_stats, (a, outcome), group[outcome])

    panel = _stats_frame(stats, ["date", "auction", "outcome"])
    pooled = _stats_frame(pooled_stats, ["auction", "outcome"])
    date_roster = pd.DataFrame({"date": sorted(dates)})
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
    return panel, pooled, date_roster, audit


def build_stress_audit(date_roster: pd.DataFrame, vix_path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    vix = pd.read_csv(vix_path)
    if list(vix.columns) != ["observation_date", "VIXCLS"]:
        raise RuntimeError(f"unexpected FRED columns: {list(vix.columns)}")
    vix["observation_date"] = pd.to_datetime(vix["observation_date"], errors="raise")
    vix["VIXCLS"] = pd.to_numeric(vix["VIXCLS"], errors="coerce")
    date_min = min(date_roster["date"].min(), vix["observation_date"].min())
    date_max = max(date_roster["date"].max(), vix["observation_date"].max())
    calendar = pd.DataFrame({"date": pd.date_range(date_min, date_max, freq="D")})
    calendar = calendar.merge(
        vix.rename(columns={"observation_date": "date"}), on="date", how="left", validate="one_to_one"
    )
    # Explicit lookahead guard: the signal known on calendar day t is the last
    # available VIX close strictly before t. Weekend ffill occurs before lagging.
    calendar["vix_signal_lag1"] = calendar["VIXCLS"].ffill().shift(1)
    dates = date_roster.merge(
        calendar[["date", "vix_signal_lag1"]], on="date", how="left", validate="one_to_one"
    )
    if dates["vix_signal_lag1"].isna().any():
        raise RuntimeError("lagged VIX missing for one or more pseudo dates")
    dates["high_stress"] = (dates["vix_signal_lag1"] >= HIGH_STRESS_VIX).astype(int)

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
    return dates, audit


def support_gate(data_audit: dict[str, Any], vix_audit: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "distinct_dates_at_least_80": data_audit["distinct_dates"] >= MIN_DATES,
        "high_stress_dates_at_least_30": vix_audit["high_stress_dates"] >= MIN_HIGH_DATES,
        "distinct_symbols_at_least_10": data_audit["distinct_symbols"] >= MIN_SYMBOLS,
        "no_weekend_pseudo_dates": vix_audit["weekend_share"] == 0.0,
    }
    return {"passed": all(checks.values()), "checks": checks}


def descriptive_benefits(pooled: pd.DataFrame) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    overall: list[dict[str, Any]] = []
    for metric in ("mean", "sd"):
        for outcome in BENEFIT_OUTCOMES:
            subset = pooled[pooled["outcome"] == outcome].set_index("auction")
            if not {0, 1}.issubset(subset.index):
                raise RuntimeError(f"missing auction or continuous observations for {outcome}")
            sign = 1.0 if outcome == "PIMP_C" and metric == "mean" else -1.0
            overall.append(
                {
                    "outcome": outcome,
                    "statistic": metric,
                    "auction_benefit": float(sign * (subset.loc[1, metric] - subset.loc[0, metric])),
                    "auction_n": int(subset.loc[1, "n"]),
                    "continuous_n": int(subset.loc[0, "n"]),
                }
            )
    multiple = pooled[(pooled["outcome"] == "MULTIPLE_IND") & (pooled["auction"] == 1)]
    if len(multiple) != 1:
        raise RuntimeError("missing or duplicate auction-only MULTIPLE_IND statistics")
    auction_only = {
        "outcome": "MULTIPLE_IND",
        "statistic": "auction_only_rate",
        "rate": float(multiple.iloc[0]["mean"]),
        "n": int(multiple.iloc[0]["n"]),
    }
    return overall, auction_only


def write_panel(panel: pd.DataFrame) -> Path:
    path = DATA / "daily_auction_panel.csv.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    panel_out = panel.copy()
    panel_out["date"] = panel_out["date"].dt.strftime("%Y-%m-%d")
    panel_out.to_csv(tmp, index=False, compression={"method": "gzip", "mtime": 0})
    os.replace(tmp, path)
    return path


def write_aggregate_snapshot(
    *, pooled: pd.DataFrame, date_roster: pd.DataFrame, data_audit: dict[str, Any], panel_path: Path
) -> None:
    """Persist sufficient statistics so the analytical run needs no network."""
    atomic_json(
        AGGREGATE_SNAPSHOT,
        {
            "schema_version": "volpred.k1707.aggregate_snapshot.v1",
            "raw_source": {
                "file_id": RAW_FILE_ID,
                "md5": RAW_MD5,
                "bytes": RAW.stat().st_size,
            },
            "analysis_panel_sha256": sha256(panel_path),
            "data_audit": data_audit,
            "date_roster": [value.strftime("%Y-%m-%d") for value in date_roster["date"]],
            "pooled_records": pooled.to_dict(orient="records"),
        },
    )


def load_aggregate_snapshot() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Load and validate the committed source-materialization receipt."""
    with AGGREGATE_SNAPSHOT.open(encoding="utf-8") as fh:
        snapshot = json.load(fh)
    if snapshot.get("schema_version") != "volpred.k1707.aggregate_snapshot.v1":
        raise RuntimeError("unexpected aggregate snapshot schema")
    expected_raw = {"file_id": RAW_FILE_ID, "md5": RAW_MD5, "bytes": 420_675_584}
    if snapshot.get("raw_source") != expected_raw:
        raise RuntimeError("aggregate snapshot raw-source identity drift")
    panel_path = DATA / "daily_auction_panel.csv.gz"
    if sha256(panel_path) != snapshot.get("analysis_panel_sha256"):
        raise RuntimeError("aggregate snapshot panel identity drift")
    frozen_vix = DATA / "vix_fred_2020.csv"
    if sha256(frozen_vix) != VIX_SHA256:
        raise RuntimeError("aggregate snapshot VIX identity drift")
    pooled = pd.DataFrame(snapshot["pooled_records"])
    date_roster = pd.DataFrame(
        {"date": pd.to_datetime(snapshot["date_roster"], errors="raise")}
    )
    data_audit = dict(snapshot["data_audit"])
    return pooled, date_roster, data_audit


def make_figures(stress_dates: pd.DataFrame, gate: dict[str, Any], overall: list[dict[str, Any]]) -> list[Path]:
    FIGURES.mkdir(parents=True, exist_ok=True)
    dates = stress_dates.sort_values("date")

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    axes[0].plot(dates["date"], dates["vix_signal_lag1"], marker="o", color="#2563eb")
    axes[0].axhline(HIGH_STRESS_VIX, color="#dc2626", linestyle="--", label="fixed stress gate: 30")
    axes[0].set_title("Lagged VIX support on pseudo dates")
    axes[0].set_ylabel("VIX close known before pseudo date")
    axes[0].tick_params(axis="x", rotation=45)
    axes[0].legend(frameon=False)

    labels = [x.replace("_", "\n") for x in gate["checks"]]
    values = list(gate["checks"].values())
    colors = ["#16a34a" if passed else "#dc2626" for passed in values]
    markers = ["o" if passed else "x" for passed in values]
    for i, (passed, color, marker) in enumerate(zip(values, colors, markers, strict=True)):
        axes[1].scatter(i, 0, color=color, marker=marker, s=170, linewidths=3)
        axes[1].text(i, -0.15, "PASS" if passed else "FAIL", ha="center", color=color)
    axes[1].set_xticks(range(len(values)), labels, fontsize=8)
    axes[1].set_ylim(-0.35, 0.35)
    axes[1].set_yticks([])
    axes[1].set_title("Pre-registered data-support gates")
    fig.tight_layout()
    support_path = FIGURES / "k1707_stress_support.png"
    fig.savefig(support_path, dpi=170, bbox_inches="tight", metadata={"Software": "matplotlib"})
    plt.close(fig)

    means = [x for x in overall if x["statistic"] == "mean" and x["outcome"] != "MULTIPLE_IND"]
    fig, axes = plt.subplots(1, len(means), figsize=(11, 4.5))
    for ax, item in zip(axes, means, strict=True):
        value = item["auction_benefit"]
        ax.bar(["Auction benefit"], [value], color="#7c3aed", width=0.55)
        ax.axhline(0, color="black", linewidth=0.8)
        ax.set_title(item["outcome"])
        ax.set_ylabel("Cents" if item["outcome"] != "EQ" else "Ratio")
        ax.text(0, value, f"{value:.3f}", ha="center", va="bottom")
    fig.suptitle("Pseudo-data pooled auction benefit (descriptive only)\nPositive means auction is better")
    fig.tight_layout()
    desc_path = FIGURES / "k1707_descriptive_benefits.png"
    fig.savefig(desc_path, dpi=170, bbox_inches="tight", metadata={"Software": "matplotlib"})
    plt.close(fig)
    return [support_path, desc_path]


def materialize_sources() -> dict[str, Any]:
    """Fetch and reduce raw sources; never finalize the canonical experiment."""
    ensure_sources(refresh=True)
    panel, pooled, date_roster, data_audit = aggregate_raw(RAW)
    panel_path = write_panel(panel)
    frozen_vix = DATA / "vix_fred_2020.csv"
    DATA.mkdir(parents=True, exist_ok=True)
    frozen_vix_tmp = frozen_vix.with_name(f".{frozen_vix.name}.tmp")
    shutil.copyfile(VIX_CACHE, frozen_vix_tmp)
    os.replace(frozen_vix_tmp, frozen_vix)
    # Written last: a killed materializer leaves the old snapshot disagreeing
    # with the new panel/VIX, so the network-denied analytical run fails closed.
    write_aggregate_snapshot(
        pooled=pooled,
        date_roster=date_roster,
        data_audit=data_audit,
        panel_path=panel_path,
    )
    load_aggregate_snapshot()
    return {
        "status": "SOURCE_MATERIALIZED",
        "network": "allow",
        "raw_md5": md5(RAW),
        "raw_bytes": RAW.stat().st_size,
        "aggregate_snapshot_sha256": sha256(AGGREGATE_SNAPSHOT),
        "analysis_panel_sha256": sha256(panel_path),
        "vix_sha256": sha256(frozen_vix),
        "next_step": "run K1707.py without --refresh-source for canonical network-denied analysis",
    }


def run() -> dict[str, Any]:
    from volpred.research.reproduce_spec import finalize_experiment

    started_at = time.time()
    np.random.seed(SEED)
    frozen_vix = DATA / "vix_fred_2020.csv"
    panel_path = DATA / "daily_auction_panel.csv.gz"
    pooled, date_roster, data_audit = load_aggregate_snapshot()
    stress_dates, vix_audit = build_stress_audit(date_roster, frozen_vix)
    gate = support_gate(data_audit, vix_audit)
    if gate["passed"]:
        raise RuntimeError(
            "Pinned pseudo-data unexpectedly passed the support gate; the confirmatory "
            "interaction estimator must be implemented and independently reviewed before use."
        )
    overall, auction_only = descriptive_benefits(pooled)
    figures = make_figures(stress_dates, gate, overall)

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
            "raw_md5": RAW_MD5,
            "raw_bytes": 420_675_584,
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
            "auction_only_multiple_bidder_rate": auction_only,
            "weighting": "all available pseudo trades; pooled sufficient statistics, not date-equal weighting",
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
        "raw": {"file_id": RAW_FILE_ID, "md5": RAW_MD5, "bytes": 420_675_584},
        "vix_sha256": sha256(frozen_vix),
        "expected_vix_sha256": VIX_SHA256,
        "analysis_panel_sha256": sha256(panel_path),
        "script_sha256": sha256(Path(__file__)),
        "source_urls": {"dataverse": RAW_URL, "fred_vixcls": VIX_URL},
    }
    atomic_json(DATA / "source_manifest.json", manifest)
    result["artifacts"]["source_manifest"] = "experiments/k1707/data/source_manifest.json"
    finalize_experiment(
        results=result,
        entrypoint=__file__,
        canonical_result=RESULTS.name,
        inputs=[
            AGGREGATE_SNAPSHOT,
            panel_path,
            frozen_vix,
            ROOT / "src" / "volpred" / "research" / "reproduce_spec.py",
        ],
        outputs=[
            "data/source_manifest.json",
            "figures/k1707_descriptive_benefits.png",
            "figures/k1707_stress_support.png",
        ],
        seeds=[("numpy", SEED)],
        started_at=started_at,
        network="deny",
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--refresh-source",
        action="store_true",
        help="network-enabled source materialization only; does not finalize canonical results",
    )
    args = parser.parse_args()
    if args.refresh_source:
        print(json.dumps(materialize_sources(), indent=2))
        return 0
    result = run()
    print(
        json.dumps(
            {"status": result["status"], "gate": result["pre_registered_support_gate"]},
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
