"""K1711 — zero-shot time-series foundation model (TSFM) forecasts of log variance.

Runs the two open-weight TSFMs over every forecast origin and dumps their raw
log-variance forecasts to CSV.  Nothing here fits, calibrates or evaluates: the
recalibration (Mincer-Zarnowitz), the combinations and every test live in
k1711.py, which reads these CSVs.  Splitting it this way is not cosmetic —
TSFM inference needs its own dependency set, so it runs under

    uv run --with 'timesfm[torch]' --with granite-tsfm python k1711_tsfm.py

while the analysis runs in the project environment.

Models
    TimesFM   google/timesfm-2.5-200m-pytorch  (decoder-only, patched)
    TTM       ibm-granite/granite-timeseries-ttm-r2, revision 512-192-r2 (0.9M params)

Both are fed the *log* variance series.  Log is the right space: it makes the
series roughly homoskedastic and symmetric, which is what these models saw in
pretraining, and it is the same space the log-HAR baseline works in — neither
side gets a representational handicap.

No-lookahead contract (the thing most likely to be wrong, so it is explicit):
    context for a forecast is series[i - CONTEXT + 1 : i + 1]  — ends at day i.
    the forecast produced from it is stored under target_date = date[i + 1].
Forecasts are therefore keyed by *the day they are predicting*, never by the day
they were made, so any join against realized variance downstream is aligned by
construction and an off-by-one would have to be visible in the index itself.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"

CONTEXT = 512          # days of history fed to the TSFM
HORIZON = 32           # steps requested; K1711 only uses the first 5
TSFM_START = "2012-01-01"   # first forecast origin (bounds inference cost)
BATCH = 128
SEED = 20260714

ASSETS = ("SPY", "0050.TW", "TX")


def _atomic_write_csv(df: pd.DataFrame, path: Path) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    df.to_csv(tmp, index_label="target_date")
    os.replace(tmp, path)


def _load_panel(asset: str) -> pd.DataFrame:
    f = DATA / f"panel_{asset.replace('.', '_')}.csv"
    return pd.read_csv(f, parse_dates=["date"]).set_index("date").sort_index()


def _build_contexts(
    log_rv: pd.Series,
) -> tuple[list[np.ndarray], pd.DatetimeIndex, pd.DatetimeIndex]:
    """Contexts ending at origin i, labelled by the date they predict (i + 1).

    Both dates are returned and both get written to the CSV.  Keying on target_date
    alone would let a later panel rebuild (one inserted or dropped trading day) silently
    re-pair a forecast with a different predecessor; carrying origin_date makes that
    corruption assertable instead of invisible.
    """
    start = log_rv.index.searchsorted(pd.Timestamp(TSFM_START))
    first_origin = max(CONTEXT - 1, start)
    values = log_rv.to_numpy(dtype=np.float32)

    contexts, target_dates, origin_dates = [], [], []
    # i is the origin; i + 1 must exist, so stop one short of the end.
    for i in range(first_origin, len(values) - 1):
        contexts.append(values[i - CONTEXT + 1 : i + 1])
        origin_dates.append(log_rv.index[i])
        target_dates.append(log_rv.index[i + 1])

    assert all(len(c) == CONTEXT for c in contexts), "ragged context"
    return (contexts,
            pd.DatetimeIndex(target_dates, name="target_date"),
            pd.DatetimeIndex(origin_dates, name="origin_date"))


# ── TimesFM 2.5 ───────────────────────────────────────────────────────────────

def run_timesfm(contexts: list[np.ndarray]) -> np.ndarray:
    import timesfm

    model = timesfm.TimesFM_2p5_200M_torch.from_pretrained(
        "google/timesfm-2.5-200m-pytorch"
    )
    model.compile(
        timesfm.ForecastConfig(
            max_context=CONTEXT,
            max_horizon=HORIZON,
            normalize_inputs=True,          # per-series standardisation of the context
            use_continuous_quantile_head=True,
            force_flip_invariance=True,
            infer_is_positive=False,        # log-variance is signed
            fix_quantile_crossing=True,
        )
    )

    out = []
    for s in range(0, len(contexts), BATCH):
        point, _ = model.forecast(horizon=HORIZON, inputs=contexts[s : s + BATCH])
        out.append(np.asarray(point, dtype=np.float64))
        print(f"  timesfm {min(s + BATCH, len(contexts))}/{len(contexts)}", flush=True)
    return np.concatenate(out, axis=0)


# ── IBM Granite TinyTimeMixer (TTM) ───────────────────────────────────────────

TTM_FREQ_TOKEN = 8      # DEFAULT_FREQUENCY_MAPPING["d"] — daily


def run_ttm(contexts: list[np.ndarray]) -> np.ndarray:
    import torch
    from tsfm_public.toolkit.get_model import get_model

    # Branch selection goes through IBM's official selector rather than a hand-picked
    # revision, because hand-picking got it wrong: TTM **r2 only supports minutely-to-
    # hourly resolutions — daily/weekly arrived in r2.1** (model card §Recommended Use).
    # And "-ft-" does NOT mean fine-tuned-on-target; it means *frequency prefix tuning*
    # (an extra embedding carrying the series' sampling frequency), so an -ft- branch is
    # still zero-shot.  Feeding daily RV to 512-192-r2 would have handicapped TTM — and
    # since a handicapped TSFM biases this experiment toward its own expected NULL, that
    # is exactly the kind of bug that would never have announced itself.
    model = get_model(
        "ibm-granite/granite-timeseries-ttm-r2",
        context_length=CONTEXT, prediction_length=96,
        freq_prefix_tuning=True, freq="d",
    )
    model.eval()

    # TTM's forward takes the raw context, so standardise each context on its own history
    # (mean/sd of the context only — no future value can enter) and invert on the way out.
    out = []
    with torch.no_grad():
        for s in range(0, len(contexts), BATCH):
            chunk = np.stack(contexts[s : s + BATCH]).astype(np.float64)
            mu = chunk.mean(axis=1, keepdims=True)
            sd = chunk.std(axis=1, keepdims=True)
            sd = np.where(sd < 1e-8, 1.0, sd)
            z = (chunk - mu) / sd

            x = torch.tensor(z, dtype=torch.float32).unsqueeze(-1)      # (B, 512, 1)
            freq = torch.full((len(chunk),), TTM_FREQ_TOKEN, dtype=torch.long)
            pred = model(past_values=x, freq_token=freq).prediction_outputs
            pred = pred.squeeze(-1).numpy().astype(np.float64)          # (B, 96)

            out.append(pred[:, :HORIZON] * sd + mu)
            print(f"  ttm {min(s + BATCH, len(contexts))}/{len(contexts)}", flush=True)
    return np.concatenate(out, axis=0)


RUNNERS = {"timesfm": run_timesfm, "ttm": run_ttm}


CHECKPOINTS = {
    "timesfm": {
        "repo": "google/timesfm-2.5-200m-pytorch",
        "params": "200M",
        # Straight off the model card. These cutoffs are what make the post-2024
        # sub-sample in k1711.py a vintage-respecting evaluation rather than a
        # backcast — see the pseudo-OOS discussion there.
        "pretraining_corpus": ["GiftEvalPretrain",
                               "Wikimedia Pageviews (cutoff Nov 2023)",
                               "Google Trends top queries (cutoff EoY 2022)",
                               "synthetic + augmented"],
        "documented_data_cutoff": "2023-11",
        "equity_or_index_volatility_in_corpus": "not listed",
    },
    "ttm": {
        "repo": "ibm-granite/granite-timeseries-ttm-r2",
        "revision": "512-96-ft-r2.1 (selected by the official get_model selector, freq='d')",
        "params": "0.86M",
        # The r2.1 corpus is fully enumerated on the model card: electricity, weather,
        # traffic, solar, sunspots, births, wind, Covid, Wikipedia traffic, NN5, Bitcoin.
        "pretraining_corpus": ["fully enumerated on the model card; the only financial "
                               "series is Bitcoin — no equity or index volatility"],
        "documented_data_cutoff": "not stated; corpus fully enumerated instead",
        "equity_or_index_volatility_in_corpus": "no",
    },
}


def _package_versions() -> dict:
    import importlib.metadata as md
    out = {}
    for p in ("torch", "timesfm", "granite-tsfm", "transformers", "numpy", "pandas"):
        try:
            out[p] = md.version(p)
        except md.PackageNotFoundError:
            # Record the absence rather than dropping the key: this dict is the
            # provenance of a forecast, and "not installed" and "we forgot to
            # record it" must not look the same to whoever replicates this.
            out[p] = "not installed"
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", choices=sorted(RUNNERS), required=True)
    args = ap.parse_args()

    np.random.seed(SEED)
    meta: dict = {"model": args.model, "context": CONTEXT, "horizon": HORIZON,
                  "tsfm_start": TSFM_START, "seed": SEED,
                  "checkpoint": CHECKPOINTS[args.model],
                  "package_versions": _package_versions(),
                  "assets": {}}

    for asset in ASSETS:
        panel = _load_panel(asset)
        log_rv = np.log(panel["rv"])
        contexts, target_dates, origin_dates = _build_contexts(log_rv)
        print(f"[{args.model}] {asset}: {len(contexts)} origins, "
              f"targets {target_dates[0].date()} → {target_dates[-1].date()}", flush=True)

        fc = RUNNERS[args.model](contexts)          # (n, HORIZON) log-variance steps
        assert fc.shape == (len(contexts), HORIZON), f"bad shape {fc.shape}"

        df = pd.DataFrame(
            fc, index=target_dates,
            columns=[f"step{h}" for h in range(1, HORIZON + 1)],
        )
        df.insert(0, "origin_date", origin_dates.astype(str))
        assert df.index.is_unique and df.index.is_monotonic_increasing

        path = DATA / f"tsfm_{args.model}_{asset.replace('.', '_')}.csv"
        _atomic_write_csv(df, path)

        meta["assets"][asset] = {
            "n_forecasts": int(len(df)),
            "first_target": str(target_dates[0].date()),
            "last_target": str(target_dates[-1].date()),
            "panel_sha256": _sha256(DATA / f"panel_{asset.replace('.', '_')}.csv"),
            "file": path.name,
        }
        print(f"  → {path.name}", flush=True)

    mpath = DATA / f"tsfm_{args.model}_meta.json"
    tmp = mpath.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(meta, indent=2))
    os.replace(tmp, mpath)


if __name__ == "__main__":
    main()
