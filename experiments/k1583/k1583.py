"""K1583 — Conditional / Sequential MCS Evaluation.

Pure ex-post meta-analysis: reuses existing K1380_v4 OOS daily QLIKE loss
matrix (17 GARCH-X-VIX specs on SPY; the corrected matrix covers OOS
2019-01-02 → 2026-07-21, 1900 days — the superseded one stopped at 1866)
and re-evaluates Hansen-Lunde-Nason (2011) Model Confidence Set under two
conditioning regimes (VIX level, NBER recession) plus rolling-window
sequential drift detection.

No new model fitting, no new data collection, no lookahead risk
(losses already realized; conditioning variables are contemporaneous
realized state, not forecasts; rolling-window MCS uses only past loss
differentials at each origin).

Loss inventory limitation: only K1380_v4's 17 SPY specs are used as the
primary inventory because (a) they share the same OOS window / proxy
(Patton 2011 r²), (b) the K1378/K1379 standalone arrays are duplicates
of subsets of K1380_v4 (same A4f / GJR / HAR), and (c) per K1355 rule,
no cross-asset stacked-day pooled inference is allowed — therefore
K1258's multi-asset 6-model panels cannot be merged into a single
loss matrix; they are recorded in `loss_inventory` for completeness but
not pooled.

Methodological caveats:
- Subsample MCS is a coarse approximation of true Conditional MCS
  (JRSS-B 2025 qkag066 uses kernel-weighted loss differentials).
  README documents this limitation explicitly.
- Rolling-window top-1 is a feasible proxy for full Sequential SPA;
  documented as such.

Seed = 42, B = 1000 bootstrap, alpha = 0.10.
"""

from __future__ import annotations

import json
import logging
import math
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

# Repo imports
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from volpred.research.reproduce_spec import finalize_experiment  # type: ignore
from volpred.stats.mcs import model_confidence_set  # type: ignore


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("k1583")


# ----------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
SEED = 42
N_BOOTSTRAP = 1000
ALPHA = 0.10

# VIX regime thresholds (per task spec)
VIX_HIGH_THRESH = 20.0
VIX_LOW_THRESH = 15.0

# Sequential drift detection
ROLLING_WINDOW = 252        # ~1 trading year
ROLLING_STRIDE = 21         # ~monthly recalculation (cheaper, still dense)

# K1380_v4 loss matrix
K1380_DIR = PROJECT_ROOT / "experiments" / "K1380_v4"
LOSS_MATRIX_PATH = K1380_DIR / "k1380_v4_losses_all.npy"
SPY_DATA_CSV = (
    PROJECT_ROOT / "paper" / "garch-x-vix" / "data"
    / "spy_vix_qqq_eem_fez_2000-2026.csv"
)
OOS_START = "2019-01-01"

# K1380_v4 spec labels (must match its SPEC_LABELS order)
SPEC_LABELS = [
    "A1", "A2", "A3", "A4", "A5",
    "A2f", "A4f", "A3f", "A2n", "A4n",
    "B1", "B2", "B3",
    "C1", "C2", "C3",
    "B0",   # GJR benchmark
]

# Specs to exclude from MCS (100% NaN coverage in K1380_v4 loss matrix —
# K1380_v4 metadata: ineligible_specs = ["C1"]).
INELIGIBLE_SPECS = ["C1"]

# K1258 multi-asset inventory (NOT pooled — only inventoried per K1355 rule)
K1258_DIR = PROJECT_ROOT / "experiments" / "k1258"
K1258_ASSETS = ["SPY", "0050_TW", "GLD"]
K1258_MODELS = [
    "sigma2_GARCH_N", "sigma2_GJR_N", "sigma2_GJR_t",
    "sigma2_EGARCH_N", "sigma2_HAR_ABS", "sigma2_A4f_IV2",
]


# ----------------------------------------------------------------------
# Step 1: Loss inventory
# ----------------------------------------------------------------------

def build_loss_inventory() -> tuple[list[dict], pd.DataFrame, list[str]]:
    """Load primary K1380_v4 loss matrix + aligned OOS dates.

    Also enumerates K1258 SPY/0050_TW/GLD as supplementary inventory
    (not pooled — recorded for transparency only).

    Returns
    -------
    inventory : list of {model_id, source, date_start, date_end, n_obs}
    losses_df : DataFrame indexed by OOS date, columns = SPEC_LABELS
    model_ids : list of column names (= SPEC_LABELS)
    """
    log.info("Loading K1380_v4 loss matrix from %s", LOSS_MATRIX_PATH)
    losses = np.load(LOSS_MATRIX_PATH)
    n_specs, n_days = losses.shape
    assert n_specs == len(SPEC_LABELS), (
        f"loss matrix has {n_specs} rows but {len(SPEC_LABELS)} spec labels"
    )
    log.info("  loss matrix shape: %s (specs × days)", losses.shape)

    df = pd.read_csv(SPY_DATA_CSV, parse_dates=["date"], index_col="date")
    oos_mask = df.index >= OOS_START
    oos_dates_full = df.index[oos_mask]
    # The saved loss matrix was generated with a smaller OOS slice (CSV
    # has grown since). Take the first n_days OOS dates to match the
    # positional order K1380_v4 used when it wrote the npy. The CSV may
    # contain duplicate trailing dates (recent backfill bug — 2026-05-04
    # … 2026-05-15 duplicated 10 rows); preserve the positional order
    # then drop duplicates keeping the first occurrence so the loss
    # matrix and the index stay aligned.
    oos_dates = oos_dates_full[:n_days]
    log.info(
        "  OOS dates aligned (raw positional): %s → %s (%d rows)",
        oos_dates[0].date(), oos_dates[-1].date(), len(oos_dates),
    )

    losses_df = pd.DataFrame(losses.T, index=oos_dates, columns=SPEC_LABELS)
    n_dupes = losses_df.index.duplicated().sum()
    if n_dupes:
        log.warning(
            "OOS index has %d duplicate dates — dropping later copies "
            "to preserve K1380_v4 positional alignment",
            n_dupes,
        )
        losses_df = losses_df[~losses_df.index.duplicated(keep="first")]

    # Drop ineligible specs (100% NaN coverage) before downstream MCS.
    drop_cols = [c for c in INELIGIBLE_SPECS if c in losses_df.columns]
    if drop_cols:
        log.info("Dropping ineligible specs (per K1380_v4 metadata): %s",
                 drop_cols)
        losses_df = losses_df.drop(columns=drop_cols)
    eligible_specs = [c for c in SPEC_LABELS if c not in INELIGIBLE_SPECS]

    inventory = [
        {
            "model_id": f"K1380_v4::{name}",
            "source": "K1380_v4 SPY GARCH-X-VIX horse race (Patton r² QLIKE)",
            "date_start": str(losses_df.index[0].date()),
            "date_end": str(losses_df.index[-1].date()),
            "n_obs_raw": int(losses.shape[1]),
            "n_obs_valid": int(np.sum(~np.isnan(losses[i]))),
            "eligible": name not in INELIGIBLE_SPECS,
        }
        for i, name in enumerate(SPEC_LABELS)
    ]

    # K1258 supplementary inventory (NOT pooled)
    for asset in K1258_ASSETS:
        path = K1258_DIR / f"forecasts_{asset}.parquet"
        if not path.exists():
            log.warning("K1258 supplementary file missing: %s", path)
            continue
        try:
            kdf = pd.read_parquet(path)
        except Exception as e:
            log.warning("K1258 read failed for %s: %s", path, e)
            continue
        for mcol in K1258_MODELS:
            if mcol not in kdf.columns:
                continue
            valid = kdf[mcol].dropna()
            if len(valid) == 0:
                continue
            inventory.append({
                "model_id": f"K1258::{asset}::{mcol}",
                "source": (
                    "K1258 multi-asset HAR/GARCH panel — INVENTORIED ONLY, "
                    "not pooled into MCS (K1355 rule: no cross-asset stacked-day "
                    "inference)"
                ),
                "date_start": str(valid.index.min().date()),
                "date_end": str(valid.index.max().date()),
                "n_obs_raw": int(len(kdf)),
                "n_obs_valid": int(len(valid)),
            })

    return inventory, losses_df, eligible_specs


# ----------------------------------------------------------------------
# Step 2: Conditioning variables
# ----------------------------------------------------------------------

def load_vix_regime(oos_dates: pd.DatetimeIndex) -> pd.Series:
    """VIX close on each OOS date → regime label."""
    log.info("Loading VIX from SPY data CSV")
    df = pd.read_csv(SPY_DATA_CSV, parse_dates=["date"], index_col="date")
    # CSV has duplicate trailing dates; keep first occurrence for alignment
    df = df[~df.index.duplicated(keep="first")]
    vix = df.loc[oos_dates, "vix_close"].astype(float)

    def label(v: float) -> str:
        if v >= VIX_HIGH_THRESH:
            return "high"
        if v >= VIX_LOW_THRESH:
            return "mid"
        return "low"

    regime = vix.apply(label)
    log.info("  VIX regime counts: %s", regime.value_counts().to_dict())
    return regime


def load_recession_indicator(
    oos_dates: pd.DatetimeIndex, fred_key: str
) -> pd.Series:
    """FRED USRECD daily 0/1 → label {recession, expansion}."""
    log.info("Fetching FRED USRECD")
    start = oos_dates[0].strftime("%Y-%m-%d")
    end = oos_dates[-1].strftime("%Y-%m-%d")
    url = (
        f"https://api.stlouisfed.org/fred/series/observations"
        f"?series_id=USRECD&api_key={fred_key}"
        f"&file_type=json&observation_start={start}&observation_end={end}"
    )
    try:
        raw = urllib.request.urlopen(url, timeout=30).read()
    except Exception as e:
        log.error("FRED fetch failed: %s", e)
        raise
    payload = json.loads(raw)
    obs = payload["observations"]
    # Build a daily Series; FRED USRECD is daily 0/1
    rec_df = pd.DataFrame(obs)
    rec_df["date"] = pd.to_datetime(rec_df["date"])
    rec_df = rec_df.set_index("date")
    rec_df["v"] = pd.to_numeric(rec_df["value"], errors="coerce")
    # Align to OOS trading dates (forward-fill ok — recession state is monthly persistent)
    rec_series = rec_df["v"].reindex(oos_dates, method="ffill")
    if rec_series.isna().any():
        # Fill any leading NaN as 0 (no recession reported)
        rec_series = rec_series.fillna(0)
    labels = rec_series.apply(
        lambda v: "recession" if v >= 0.5 else "expansion"
    )
    log.info("  Recession label counts: %s", labels.value_counts().to_dict())
    return labels


def fred_api_key() -> str:
    key = os.environ.get("FRED_API_KEY")
    if key:
        return key
    env_path = PROJECT_ROOT / ".env.local"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("FRED_API_KEY="):
                return line.split("=", 1)[1].strip()
    raise RuntimeError("FRED_API_KEY missing — cannot fetch USRECD")


# ----------------------------------------------------------------------
# Step 3 helper: clean loss matrix for MCS
# ----------------------------------------------------------------------

def clean_for_mcs(
    losses_df: pd.DataFrame, mask: pd.Series | None = None
) -> tuple[dict[str, np.ndarray], int, int]:
    """Drop rows where ANY model has NaN; return dict suitable for MCS.

    Parameters
    ----------
    losses_df : DataFrame (T × M)
    mask : optional boolean Series aligned to losses_df.index

    Returns
    -------
    losses_dict, n_rows_used, n_rows_dropped
    """
    df = losses_df.copy()
    if mask is not None:
        df = df.loc[mask.reindex(df.index).fillna(False).astype(bool)]
    before = len(df)
    df = df.dropna(axis=0, how="any")
    after = len(df)
    return ({c: df[c].to_numpy() for c in df.columns}, after, before - after)


def run_mcs_safe(
    losses_dict: dict[str, np.ndarray],
    label: str,
    *,
    seed: int = SEED,
    n_boot: int = N_BOOTSTRAP,
    alpha: float = ALPHA,
) -> dict:
    """Wrapper that logs context and protects against degenerate inputs."""
    T = len(next(iter(losses_dict.values()))) if losses_dict else 0
    M = len(losses_dict)
    log.info("MCS[%s]: T=%d  M=%d  B=%d", label, T, M, n_boot)
    if T < 30 or M < 2:
        log.warning(
            "MCS[%s]: insufficient data (T=%d, M=%d) — returning trivial",
            label, T, M,
        )
        return {
            "mcs_models": list(losses_dict.keys()),
            "eliminated": [],
            "p_values": {k: float("nan") for k in losses_dict},
            "T": T,
            "M": M,
            "trivial": True,
        }
    res = model_confidence_set(
        losses_dict, alpha=alpha, n_boot=n_boot, seed=seed
    )
    res["T"] = T
    res["M"] = M
    res["trivial"] = False
    return res


# ----------------------------------------------------------------------
# Step 4: Sequential rolling-window MCS top-1
# ----------------------------------------------------------------------

def sequential_drift(
    losses_df: pd.DataFrame,
    *,
    window: int = ROLLING_WINDOW,
    stride: int = ROLLING_STRIDE,
    seed: int = SEED,
    n_boot: int = 500,  # cheaper for inner loops
    alpha: float = ALPHA,
) -> tuple[list[dict], list[tuple[str, str]]]:
    """Roll a window, run MCS on each window, record top-1 winner.

    Top-1 = single model with the highest MCS p-value (most likely to stay
    in the MCS through elimination). Ties broken by lowest mean QLIKE.

    Returns
    -------
    timeline : list of {date, top_model, mcs_size, top_p, mcs_models}
    change_points : list of (date, new_top_model)
    """
    timeline: list[dict] = []
    df = losses_df.dropna(axis=0, how="any")
    T = len(df)
    if T < window + stride:
        log.warning(
            "sequential_drift: not enough valid rows (T=%d < window=%d)",
            T, window,
        )
        return [], []

    # Iterate origins from `window` to T (origin = right edge, inclusive)
    origins = list(range(window, T, stride))
    if origins[-1] != T - 1:
        origins.append(T - 1)

    last_top = None
    change_points: list[tuple[str, str]] = []

    for k, origin in enumerate(origins):
        sub = df.iloc[origin - window: origin]
        losses_dict = {c: sub[c].to_numpy() for c in sub.columns}
        res = run_mcs_safe(
            losses_dict,
            label=f"roll@{sub.index[-1].date()}",
            seed=seed + k,  # vary seed per window to avoid bootstrap correlation
            n_boot=n_boot,
            alpha=alpha,
        )
        p_values = res["p_values"]
        mean_q = {c: float(np.mean(losses_dict[c])) for c in losses_dict}
        # Top-1: max MCS p-value; tie-break = min mean QLIKE
        ranked = sorted(
            p_values.items(),
            key=lambda kv: (-kv[1], mean_q.get(kv[0], np.inf)),
        )
        top_model, top_p = ranked[0]
        end_date = sub.index[-1]
        timeline.append({
            "date": str(end_date.date()),
            "top_model": top_model,
            "top_p": float(top_p),
            "mcs_size": len(res["mcs_models"]),
            "mcs_models": list(res["mcs_models"]),
        })
        if last_top is not None and top_model != last_top:
            change_points.append((str(end_date.date()), top_model))
        last_top = top_model

    return timeline, change_points


# ----------------------------------------------------------------------
# Plotting (optional)
# ----------------------------------------------------------------------

def make_plots(
    losses_df: pd.DataFrame,
    conditional_results: dict,
    timeline: list[dict],
) -> list[str]:
    out: list[str] = []
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:
        log.warning("matplotlib unavailable: %s — skipping plots", e)
        return out

    # ---- Heatmap: conditional MCS membership ----
    cond_groups: list[tuple[str, str]] = []
    cond_groups.append(("unconditional", "ALL"))
    for k in conditional_results.get("vix", {}):
        cond_groups.append(("vix", k))
    for k in conditional_results.get("recession", {}):
        cond_groups.append(("recession", k))

    members = np.zeros((len(losses_df.columns), len(cond_groups)), dtype=float)
    col_labels: list[str] = []
    for j, (kind, key) in enumerate(cond_groups):
        if kind == "unconditional":
            in_mcs = set(conditional_results["unconditional"]["mcs_models"])
            col_labels.append("uncond")
        else:
            in_mcs = set(conditional_results[kind][key]["mcs_models"])
            col_labels.append(f"{kind}:{key}")
        for i, m in enumerate(losses_df.columns):
            members[i, j] = 1.0 if m in in_mcs else 0.0

    fig, ax = plt.subplots(figsize=(8, 7))
    im = ax.imshow(members, aspect="auto", cmap="RdYlGn", vmin=0, vmax=1)
    ax.set_xticks(range(len(col_labels)))
    ax.set_xticklabels(col_labels, rotation=45, ha="right")
    ax.set_yticks(range(len(losses_df.columns)))
    ax.set_yticklabels(list(losses_df.columns))
    ax.set_title("K1583 Conditional MCS membership (green = in 90% MCS)")
    plt.colorbar(im, ax=ax, fraction=0.04)
    plt.tight_layout()
    p = SCRIPT_DIR / "k1583_conditional_mcs_heatmap.png"
    plt.savefig(p, dpi=130)
    plt.close(fig)
    out.append(str(p.relative_to(PROJECT_ROOT)))

    # ---- Sequential top-1 winner timeline ----
    if timeline:
        fig, ax = plt.subplots(figsize=(11, 4))
        dates = [pd.to_datetime(t["date"]) for t in timeline]
        winners = [t["top_model"] for t in timeline]
        unique_winners = sorted(set(winners))
        ymap = {w: i for i, w in enumerate(unique_winners)}
        y = [ymap[w] for w in winners]
        ax.step(dates, y, where="post", linewidth=1.5, marker="o", markersize=3)
        ax.set_yticks(range(len(unique_winners)))
        ax.set_yticklabels(unique_winners)
        ax.set_title(
            f"K1583 Sequential 252d-rolling MCS top-1 winner "
            f"(stride={ROLLING_STRIDE}d)"
        )
        ax.set_xlabel("Window end date")
        ax.set_ylabel("Top-1 model")
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        p = SCRIPT_DIR / "k1583_sequential_winner_timeline.png"
        plt.savefig(p, dpi=130)
        plt.close(fig)
        out.append(str(p.relative_to(PROJECT_ROOT)))

    return out


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

def _json_safe(value: object) -> object:
    """Replace non-finite floats with None so the output is standard JSON.

    ``json.dumps`` writes bare ``NaN`` / ``Infinity`` by default. Those are
    valid Python but not valid JSON, and a strict reader refuses the entire
    file — one trivial-MCS regime is enough to make every other number in the
    results unreadable to downstream tooling.
    """
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, np.floating):
        f = float(value)
        return f if math.isfinite(f) else None
    if isinstance(value, np.integer):
        return int(value)
    return value


def main() -> int:
    started_at = time.time()
    rng = np.random.default_rng(SEED)  # global anchor (not strictly needed)
    log.info("=" * 70)
    log.info("K1583 Conditional / Sequential MCS")
    log.info("=" * 70)

    # ----- Step 1 -----
    inventory, losses_df, model_ids = build_loss_inventory()

    # ----- Step 2 -----
    vix_regime = load_vix_regime(losses_df.index)
    recession = load_recession_indicator(losses_df.index, fred_api_key())

    # Align the loss matrix to non-NaN rows once for the unconditional run
    # (conditional runs handle their own intersection).
    log.info("Cleaning loss matrix for unconditional MCS")
    uncond_losses, n_used, n_dropped = clean_for_mcs(losses_df)
    log.info("  unconditional: %d rows used, %d dropped (NaN)", n_used, n_dropped)

    # ----- Step 3a: Unconditional MCS -----
    uncond_res = run_mcs_safe(uncond_losses, "unconditional")

    # ----- Step 3b: Conditional MCS (VIX regime) -----
    vix_results = {}
    for regime in ["high", "mid", "low"]:
        mask = (vix_regime == regime)
        ld, T, dropped = clean_for_mcs(losses_df, mask=mask)
        log.info("VIX[%s]: %d rows used, %d dropped", regime, T, dropped)
        vix_results[regime] = run_mcs_safe(ld, f"vix:{regime}")

    # ----- Step 3c: Conditional MCS (Recession) -----
    rec_results = {}
    for state in ["recession", "expansion"]:
        mask = (recession == state)
        ld, T, dropped = clean_for_mcs(losses_df, mask=mask)
        log.info("Recession[%s]: %d rows used, %d dropped", state, T, dropped)
        rec_results[state] = run_mcs_safe(ld, f"recession:{state}")

    # ----- Step 4: Sequential drift -----
    log.info("Sequential rolling-window MCS (window=%d stride=%d)",
             ROLLING_WINDOW, ROLLING_STRIDE)
    timeline, change_points = sequential_drift(losses_df)
    log.info("  timeline length = %d, change points = %d",
             len(timeline), len(change_points))

    # ----- Step 5: Plots -----
    plot_paths = make_plots(
        losses_df,
        {
            "unconditional": uncond_res,
            "vix": vix_results,
            "recession": rec_results,
        },
        timeline,
    )

    # ----- Step 6: Write results -----
    def _strip(res: dict) -> dict:
        return {
            "mcs_models": list(res["mcs_models"]),
            "eliminated_order": [
                (m, float(p)) for m, p in res.get("eliminated", [])
            ],
            "p_values": {k: float(v) for k, v in res["p_values"].items()},
            "T": int(res.get("T", 0)),
            "M": int(res.get("M", 0)),
            "trivial": bool(res.get("trivial", False)),
        }

    out = {
        "experiment_id": "k1583",
        "title": "Conditional / Sequential MCS — meta-evaluation of K1380_v4 17-spec SPY horse race",
        "metadata": {
            "seed": SEED,
            "n_bootstrap": N_BOOTSTRAP,
            "alpha": ALPHA,
            "rolling_window_days": ROLLING_WINDOW,
            "rolling_stride_days": ROLLING_STRIDE,
            "vix_thresholds": {"high>=": VIX_HIGH_THRESH, "low<": VIX_LOW_THRESH},
            # Derived from the loaded matrix, never hard-coded: this string was
            # frozen at "2019-01-02 → 2026-05-20" while the corrected K1380_v4
            # matrix already covered 1900 days ending 2026-07-21, so the results
            # JSON was describing a sample it had not evaluated.
            "primary_inventory": (
                f"K1380_v4 SPY {len(SPEC_LABELS)} specs, OOS "
                f"{losses_df.index[0].date()} → {losses_df.index[-1].date()} "
                f"({len(losses_df)} days)"
            ),
            "loss_proxy": "Patton (2011) r² QLIKE",
            "conditioning_variables": {
                "vix": "spy_vix_qqq_eem_fez_2000-2026.csv vix_close (contemporaneous, not lagged — characterizes the day's regime)",
                "recession": "FRED USRECD daily, ffill across non-trading days",
            },
            "lookahead_policy": "ex-post meta-analysis on already-realized losses; conditioning variables describe the day's realized state (not future); rolling-window MCS at origin t uses only past 252 differentials",
            "cross_asset_pooling": "DISABLED per K1355 rule — K1258 multi-asset panels are inventoried only, never stacked into a single MCS",
            "implementation_notes": [
                "Subsample MCS is a coarse approximation of true conditional MCS (JRSS-B 2025 qkag066 weighted-loss-differential approach); documented as a limitation, not a substitute.",
                "Rolling-window MCS top-1 is a proxy for full sequential SPA (Hansen 2005) — change-point = winner switch.",
                "B=1000 for static MCS (task budget); B=500 for inner rolling loops to keep runtime bounded.",
                "MCS implementation reused from src/volpred/stats/mcs.py (HLN 2011 T_R variant, stationary bootstrap, HAC SE).",
            ],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        "loss_inventory": inventory,
        "mcs_unconditional": _strip(uncond_res),
        "mcs_conditional_vix": {k: _strip(v) for k, v in vix_results.items()},
        "mcs_conditional_recession": {k: _strip(v) for k, v in rec_results.items()},
        "sequential_drift": {
            "timeline": timeline,
            "change_points": [
                {"date": d, "new_top_model": m} for d, m in change_points
            ],
            "n_change_points": len(change_points),
        },
        "plots": plot_paths,
        "limitations": [
            "Loss inventory is restricted to a single asset (SPY) and a single OOS sample. The K1258 multi-asset panels are inventoried but NOT pooled (K1355 rule against asset-day stacked inference); cross-market conditional results would require per-asset MCS or a panel-HAC re-design (out of scope here).",
            "Conditional MCS via subsample slicing is a coarse approximation. A proper conditional MCS (Liu, Pelger & Yang 2025 JRSS-B, qkag066) uses kernel-weighted loss differentials; reproducing it would require a separate implementation pass.",
            # Derived, not hard-coded: this sentence used to state "61 raw / 43 used"
            # from an earlier run and kept saying so after the corrected loss matrix
            # cut the usable recession sample to a fraction of that.
            (
                f"NBER recession sample in OOS is small ({int((recession == 'recession').sum())} raw "
                f"regime-labeled trading days, {rec_results['recession']['T']} days actually used in "
                "the MCS after joint NaN cleaning; covers only COVID 2020-03 to 2020-04). The "
                "recession-regime MCS is therefore underpowered; results should be read as "
                "descriptive, not inferential."
            ),
            "Sequential drift detection here is rolling-window MCS top-1 with a 252-day window and 21-day stride. This is not equivalent to Inoue, Jin & Rossi-style online SPA tests; change-points should be read as visualization aids, not formal break-tests.",
            "Tie-breaking in 'top-1' uses min mean QLIKE within tied MCS p-values, which biases the winner toward low-mean models; alternative tie-breaks (e.g. mean rank) would shift the timeline marginally.",
        ],
    }

    # Python's json module happily emits bare NaN, which is not JSON. The
    # repository's strict readers (scripts/reproduce_check.py) reject the file
    # outright, so a single trivial-MCS regime -- where every p-value is NaN by
    # design -- was enough to make the whole result unreadable downstream.
    # Non-finite floats become null, which is what they mean here: no value.
    out = _json_safe(out)

    # Results and reproduce_spec are written together so that code_trace and
    # spec.entrypoint describe the same bytes by construction (K1708 lesson: a
    # spec assembled after the fact drifts from the run it claims to describe).
    out_path, _spec = finalize_experiment(
        results=out,
        entrypoint=__file__,
        canonical_result="k1583_results.json",
        exp_dir=SCRIPT_DIR,
        inputs=[LOSS_MATRIX_PATH, SPY_DATA_CSV],
        # declared outputs are resolved against exp_dir, so pass bare filenames —
        # plot_paths carries repo-relative paths for the results JSON's own use.
        outputs=sorted(
            Path(p).name
            for p in (plot_paths.values() if isinstance(plot_paths, dict) else plot_paths)
        ),
        seeds=[("numpy_default_rng", SEED), ("mcs_bootstrap", SEED)],
        started_at=started_at,
    )
    log.info("Wrote %s (+ reproduce_spec.json)", out_path.relative_to(PROJECT_ROOT))

    # Pretty summary to stdout
    print("\n" + "=" * 70)
    print("K1583 SUMMARY")
    print("=" * 70)
    print(f"Unconditional MCS (T={uncond_res['T']}): {uncond_res['mcs_models']}")
    print("By VIX regime:")
    for r, res in vix_results.items():
        print(f"  {r:5s} (T={res['T']}): {res['mcs_models']}")
    print("By NBER state:")
    for s, res in rec_results.items():
        print(f"  {s:10s} (T={res['T']}): {res['mcs_models']}")
    print(f"Sequential drift: {len(change_points)} winner switches detected")
    for d, m in change_points[:20]:
        print(f"  {d}  →  {m}")
    if len(change_points) > 20:
        print(f"  ... +{len(change_points) - 20} more")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
