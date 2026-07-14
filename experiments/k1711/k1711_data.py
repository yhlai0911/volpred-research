"""K1711 data layer — daily *open-to-close* variance panels for SPY / 0050.TW / TX.

Every model in K1711 forecasts the same object for a given asset, and across the
three assets that object is conceptually the same: **intraday (open-to-close)
variance**.  That alignment is deliberate — the experiment-preamble rule on
model/target matching only has bite if the target is fixed before the models are.

    TX       true 5-min realized variance of the *day session* (TAIFEX tick data).
             Active contract picked by same-day max total volume, so there is no
             roll gap at settlement.  Night session is excluded on purpose: it
             only exists from 2017-05, and folding it in would put a structural
             break in the middle of the evaluation window.

    SPY      Garman-Klass open-to-close variance from daily OHLC (yfinance).
    0050.TW  the same, after clean_tw50_data() repairs the 2014 split artefact.

Why a proxy for the two equities: yfinance serves at most 60 days of 5-min bars,
so a *long* true-RV history for SPY / 0050.TW does not exist in this repo.  The
accumulated 5-min files (data/intraday/, ~110 days from 2026-01) are used here
only to validate the GK proxy against true RV on the overlap — never to fit.

Each asset also gets a second variance proxy, r2_oc = log(C/O)^2.  It is far
noisier than RV/GK but conditionally unbiased for the same open-to-close
integrated variance.  Patton (2011) says QLIKE model *rankings* survive that
swap; K1711 uses it to check whether the MCS superior set survives it too.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from volpred.data.preprocessing import compute_garman_klass_vol  # noqa: E402
from volpred.utils import clean_tw50_data  # noqa: E402

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"


def _source_root() -> Path:
    """Repo root that actually holds data/intraday/.

    data/intraday/*.csv is gitignored, so it exists only in the *main* working
    tree — a worktree checkout does not see it.  Anchor to the shared git dir so
    this resolves from either place.  The derived panels are committed under
    experiments/k1711/data/, so everything downstream reproduces without it.
    """
    if (REPO / "data" / "intraday").is_dir():
        return REPO
    common = subprocess.run(
        ["git", "-C", str(REPO), "rev-parse", "--path-format=absolute", "--git-common-dir"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return Path(common).parent


SOURCE_ROOT = _source_root()
TAIFEX_RV = SOURCE_ROOT / "data" / "intraday" / "taifex_5min_rv.csv"
SPY_RV_5MIN = SOURCE_ROOT / "data" / "intraday" / "SPY_daily_rv.csv"
TW50_RV_5MIN = SOURCE_ROOT / "data" / "intraday" / "0050_TW_daily_rv.csv"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

# Downloads are pinned so a re-run reproduces the same panel.
DOWNLOAD_START = "1999-01-01"
DOWNLOAD_END = "2026-07-14"

ASSETS = ("SPY", "0050.TW", "TX")


def _atomic_write(path: Path, writer) -> None:
    """Write via temp file + os.replace so a mid-run death cannot truncate output."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    writer(tmp)
    os.replace(tmp, path)


# ── yfinance-backed equities ──────────────────────────────────────────────────

def _download_ohlc(ticker: str) -> pd.DataFrame:
    """Daily OHLC, cached to disk so the panel is reproducible after the fact."""
    cache = DATA / f"ohlc_{ticker.replace('.', '_')}.csv"
    if cache.exists():
        df = pd.read_csv(cache, parse_dates=["date"]).set_index("date")
        return df

    raw = yf.download(
        ticker,
        start=DOWNLOAD_START,
        end=DOWNLOAD_END,
        auto_adjust=False,
        progress=False,
    )
    if raw is None or raw.empty:
        raise RuntimeError(f"yfinance returned no rows for {ticker}")
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    df = raw[["Open", "High", "Low", "Close"]].copy()
    df.columns = ["open", "high", "low", "close"]
    df.index.name = "date"
    df = df.dropna()

    DATA.mkdir(parents=True, exist_ok=True)
    _atomic_write(cache, lambda p: df.reset_index().to_csv(p, index=False))
    return df


def _equity_panel(ticker: str) -> tuple[pd.DataFrame, dict]:
    df = _download_ohlc(ticker)
    diag: dict = {}

    if ticker == "0050.TW":
        # Yahoo back-applies the 2025 1:4 split only from 2014-01-02, printing a fake
        # -75% day.  Both K1711 targets are built from *within-day* ratios (H/L and
        # C/O), and that artefact is a pure cross-day rescaling — so it cannot reach
        # them.  Running the canonical repair column-by-column would be actively
        # harmful: its extreme-return safety net rebuilds each column from that
        # column's own cumprod, which breaks H >= L across columns (measured: 2,489
        # non-positive GK days).  So apply the canonical repair to close, and use it
        # to *prove* the artefact is gone rather than to rewrite the OHLC.
        _, clean_ret = clean_tw50_data(df["close"])
        raw_ret = df["close"].pct_change()
        diag["split_artefact"] = {
            "canonical_repair": "clean_tw50_data() applied to close series",
            "raw_worst_daily_return": float(raw_ret.min()),
            "repaired_worst_daily_return": float(clean_ret.min()),
            "targets_are_scale_invariant": True,
            "why": "GK and log(C/O)^2 use only within-day ratios; a cross-day "
                   "rescaling cancels out of both.",
        }

    # Bad OHLC rows: yfinance prints open == 0 on a handful of TW days, and H == L
    # on no-range days.  Both make the target or its log undefined; drop, don't fudge.
    ok = (df["open"] > 0) & (df["low"] > 0) & (df["high"] > df["low"])
    diag["n_dropped_bad_ohlc"] = int((~ok).sum())
    df = df[ok]

    gk = compute_garman_klass_vol(df["open"], df["high"], df["low"], df["close"])
    ret = np.log(df["close"] / df["open"])          # signed open-to-close return

    panel = pd.DataFrame({"rv": gk, "ret": ret, "r2": ret ** 2}, index=df.index)
    panel = panel[np.isfinite(panel["rv"]) & np.isfinite(panel["r2"])]
    return panel, diag


# ── TAIFEX TX ─────────────────────────────────────────────────────────────────

def _tx_panel() -> pd.DataFrame:
    if not TAIFEX_RV.exists():
        raise FileNotFoundError(
            f"{TAIFEX_RV} missing — run scripts/collect_taifex_tick.py first"
        )
    raw = pd.read_csv(TAIFEX_RV, parse_dates=["date"]).set_index("date").sort_index()

    # rv_day is the 5-min RV of the day session only; day_return is its open-to-close
    # log return, so r2 below is the *same* object measured with one observation.
    panel = pd.DataFrame(
        {"rv": raw["rv_day"], "ret": raw["day_return"],
         "r2": raw["day_return"] ** 2},
        index=raw.index,
    )
    panel = panel[np.isfinite(panel["rv"]) & np.isfinite(panel["r2"])]
    return panel


# ── proxy validation (GK vs true 5-min RV, overlap only) ──────────────────────

def _validate_gk_proxy(panels: dict[str, pd.DataFrame]) -> dict:
    """GK is a proxy; say out loud how well it tracks true 5-min RV where both exist.

    This is a diagnostic. It never feeds a forecast — the overlap is ~110 days,
    which is far too short to fit or evaluate anything.
    """
    out: dict[str, dict] = {}
    for ticker, path in (("SPY", SPY_RV_5MIN), ("0050.TW", TW50_RV_5MIN)):
        if not path.exists():
            out[ticker] = {"status": "no_true_rv_file"}
            continue
        true_rv = pd.read_csv(path)
        date_col = true_rv.columns[0]
        true_rv[date_col] = pd.to_datetime(true_rv[date_col])
        true_rv = true_rv.set_index(date_col)["rv_5min"].sort_index()

        gk = panels[ticker]["rv"]
        joined = pd.concat([np.log(true_rv), np.log(gk)], axis=1, join="inner").dropna()
        joined.columns = ["log_true_rv", "log_gk"]
        if len(joined) < 30:
            out[ticker] = {"status": "overlap_too_short", "n": int(len(joined))}
            continue

        # Level ratio matters as much as correlation: GK measures the same
        # open-to-close variance, so a systematic scale gap would be a red flag.
        ratio = (gk.reindex(joined.index) / true_rv.reindex(joined.index)).median()
        out[ticker] = {
            "status": "ok",
            "n_overlap_days": int(len(joined)),
            "overlap_start": str(joined.index.min().date()),
            "overlap_end": str(joined.index.max().date()),
            "pearson_log": float(joined["log_true_rv"].corr(joined["log_gk"])),
            "spearman_log": float(
                joined["log_true_rv"].corr(joined["log_gk"], method="spearman")
            ),
            "median_gk_over_true_rv": float(ratio),
        }
    return out


# ── build ─────────────────────────────────────────────────────────────────────

def build() -> dict:
    DATA.mkdir(parents=True, exist_ok=True)

    spy, spy_diag = _equity_panel("SPY")
    tw, tw_diag = _equity_panel("0050.TW")
    panels = {"SPY": spy, "0050.TW": tw, "TX": _tx_panel()}
    diags = {"SPY": spy_diag, "0050.TW": tw_diag, "TX": {}}

    meta: dict = {
        "assets": {},
        "proxy_validation": _validate_gk_proxy(panels),
        "source_provenance": {
            "taifex_5min_rv_csv": {
                "path": str(TAIFEX_RV),
                "sha256": _sha256(TAIFEX_RV),
                "note": "gitignored local artefact; derived panels below are committed",
            },
            "yfinance_download_window": [DOWNLOAD_START, DOWNLOAD_END],
        },
    }

    for name, panel in panels.items():
        # A zero-variance day makes log(rv) and QLIKE undefined.  Drop rather than
        # floor here; the floor that protects the *evaluation* target is set later
        # from training data only (see k1711.py), so it cannot leak.
        n_raw = len(panel)
        panel = panel[panel["rv"] > 0]
        fname = DATA / f"panel_{name.replace('.', '_')}.csv"
        _atomic_write(fname, lambda p, pl=panel: pl.to_csv(p, index_label="date"))

        meta["assets"][name] = {
            "n_days": int(len(panel)),
            "n_dropped_zero_rv": int(n_raw - len(panel)),
            "start": str(panel.index.min().date()),
            "end": str(panel.index.max().date()),
            "rv_source": (
                "TAIFEX 5-min RV, day session, volume-selected active contract"
                if name == "TX"
                else "Garman-Klass open-to-close variance from daily OHLC (yfinance)"
            ),
            "r2_source": "log(close/open)^2 — noisy but unbiased for the same target",
            "rv_median": float(panel["rv"].median()),
            "r2_median": float(panel["r2"].median()),
            "n_zero_r2": int((panel["r2"] == 0).sum()),
            "file": str(fname.relative_to(HERE)),
            "diagnostics": diags[name],
        }

    _atomic_write(DATA / "panel_meta.json", lambda p: p.write_text(json.dumps(meta, indent=2)))
    return meta


if __name__ == "__main__":
    m = build()
    print(json.dumps(m, indent=2))
