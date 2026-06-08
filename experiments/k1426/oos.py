"""K1426 follow-up — expanding-window OOS hedging for Partial Cointegration.

This script is intended for async execution via scripts/compute_queue.py.

Scope:
- 6 pairs: original 3 + GLD/SLV, XLE/USO, XLF/XLK
- Expanding-window estimation with strict t-1 information set
- Refit cadence defaults to every 21 trading days to keep compute tractable
- PCH uses 100 multistarts on each refit
- OOS comparison: unhedged vs OLS / EG-VECM / PCH hedged returns
- Inference:
    * HE = 1 - Var(hedged) / Var(unhedged)
    * block-bootstrap CI for HE_PCH - HE_OLS
    * DM test on squared hedged returns (variance-loss comparison)

Reproduce:
    uv run python experiments/k1426/oos.py
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np

from k1426 import SEED, fetch_pair, fit_eg_vecm_hedge, fit_ols_hedge, fit_pch
from volpred.stats.model_evaluation import dm_test

OUT_DIR = Path(__file__).resolve().parent
RESULT_PATH = OUT_DIR / "k1426_oos_results.json"

START = "2015-01-01"
END = "2024-12-31"
PAIRS: List[Tuple[str, str, str]] = [
    ("pair_1_SPY_IVV", "SPY", "IVV"),
    ("pair_2_USO_BNO", "USO", "BNO"),
    ("pair_3_GLD_IAU", "GLD", "IAU"),
    ("pair_4_GLD_SLV", "GLD", "SLV"),
    ("pair_5_XLE_USO", "XLE", "USO"),
    ("pair_6_XLF_XLK", "XLF", "XLK"),
]


@dataclass
class RefitSnapshot:
    oos_date: str
    train_end_date: str
    train_n: int
    beta_ols: float
    beta_eg: float
    beta_pch: float
    rho_pch: float
    r2_mr_pch: float
    half_life_days: float | None
    n_starts_converged: int


def hedge_effectiveness_from_returns(
    unhedged_returns: np.ndarray, hedged_returns: np.ndarray
) -> float:
    var_un = float(np.var(unhedged_returns, ddof=1))
    var_he = float(np.var(hedged_returns, ddof=1))
    if not np.isfinite(var_un) or var_un <= 1e-12:
        return float("nan")
    return 1.0 - var_he / var_un


def moving_block_bootstrap_indices(
    n: int, block_len: int, rng: np.random.Generator
) -> np.ndarray:
    starts = rng.integers(0, n - block_len + 1, size=int(np.ceil(n / block_len)))
    idx = np.concatenate([np.arange(s, s + block_len) for s in starts])[:n]
    return idx


def bootstrap_he_diff_ci(
    unhedged_returns: np.ndarray,
    hedged_returns_pch: np.ndarray,
    hedged_returns_ols: np.ndarray,
    block_len: int,
    n_boot: int,
    seed: int,
) -> Dict[str, float | List[float]]:
    rng = np.random.default_rng(seed)
    n = len(unhedged_returns)
    diffs = np.empty(n_boot, dtype=np.float64)
    for i in range(n_boot):
        idx = moving_block_bootstrap_indices(n, block_len, rng)
        he_pch = hedge_effectiveness_from_returns(
            unhedged_returns[idx], hedged_returns_pch[idx]
        )
        he_ols = hedge_effectiveness_from_returns(
            unhedged_returns[idx], hedged_returns_ols[idx]
        )
        diffs[i] = he_pch - he_ols

    lo, med, hi = np.nanpercentile(diffs, [2.5, 50.0, 97.5])
    return {
        "point_diff": float(
            hedge_effectiveness_from_returns(unhedged_returns, hedged_returns_pch)
            - hedge_effectiveness_from_returns(unhedged_returns, hedged_returns_ols)
        ),
        "ci_95": [float(lo), float(hi)],
        "bootstrap_median": float(med),
        "n_boot": int(n_boot),
        "block_len": int(block_len),
        "seed": int(seed),
    }


def pch_diagnostics(pch_fit) -> Tuple[float, float | None]:
    r2_mr = float(
        pch_fit.sigma_M**2 / max(pch_fit.sigma_M**2 + pch_fit.sigma_R**2, 1e-16)
    )
    if 0 < pch_fit.rho < 0.999:
        return r2_mr, float(-np.log(2.0) / np.log(pch_fit.rho))
    return r2_mr, None


def analyze_pair(
    pair_name: str,
    sym_x: str,
    sym_y: str,
    *,
    min_train: int,
    refit_every: int,
    n_starts: int,
    n_boot: int,
    block_len: int,
    seed: int,
) -> Dict:
    print(
        f"[{pair_name}] Fetching {sym_x}/{sym_y} start={START} end={END} "
        f"min_train={min_train} refit_every={refit_every} n_starts={n_starts}",
        flush=True,
    )
    df = fetch_pair(sym_x, sym_y, START, END)
    log_x = df["log_x"].to_numpy()
    log_y = df["log_y"].to_numpy()
    dates = df.index
    n = len(df)
    if n <= min_train:
        raise RuntimeError(f"{pair_name}: insufficient observations n={n} <= {min_train}")

    current = None
    last_refit_idx = -1
    refits: List[RefitSnapshot] = []
    unhedged_returns: List[float] = []
    hedged_ols_returns: List[float] = []
    hedged_eg_returns: List[float] = []
    hedged_pch_returns: List[float] = []
    oos_dates: List[str] = []

    for i in range(min_train, n):
        need_refit = current is None or (i - last_refit_idx) >= refit_every
        if need_refit:
            train_x = log_x[:i]
            train_y = log_y[:i]
            mu_ols, beta_ols, _ = fit_ols_hedge(train_x, train_y)
            _, beta_eg, _, _ = fit_eg_vecm_hedge(train_x, train_y)
            pch = fit_pch(train_x, train_y, n_starts=n_starts, seed=seed)
            r2_mr, half_life = pch_diagnostics(pch)
            current = {
                "mu_ols": mu_ols,
                "beta_ols": beta_ols,
                "beta_eg": beta_eg,
                "pch": pch,
                "r2_mr": r2_mr,
                "half_life": half_life,
            }
            last_refit_idx = i
            refits.append(
                RefitSnapshot(
                    oos_date=str(dates[i].date()),
                    train_end_date=str(dates[i - 1].date()),
                    train_n=int(i),
                    beta_ols=float(beta_ols),
                    beta_eg=float(beta_eg),
                    beta_pch=float(pch.beta),
                    rho_pch=float(pch.rho),
                    r2_mr_pch=float(r2_mr),
                    half_life_days=float(half_life) if half_life is not None else None,
                    n_starts_converged=int(pch.n_starts_converged),
                )
            )
            print(
                f"[{pair_name}] Refit @{dates[i].date()} train_n={i} "
                f"beta_pch={pch.beta:.4f} rho={pch.rho:.4f} r2_mr={r2_mr:.4f}",
                flush=True,
            )

        ret_x = float(log_x[i] - log_x[i - 1])
        ret_y = float(log_y[i] - log_y[i - 1])

        unhedged_returns.append(ret_x)
        hedged_ols_returns.append(ret_x - float(current["beta_ols"]) * ret_y)
        hedged_eg_returns.append(ret_x - float(current["beta_eg"]) * ret_y)
        hedged_pch_returns.append(ret_x - float(current["pch"].beta) * ret_y)
        oos_dates.append(str(dates[i].date()))

    unhedged = np.asarray(unhedged_returns, dtype=np.float64)
    hedged_ols = np.asarray(hedged_ols_returns, dtype=np.float64)
    hedged_eg = np.asarray(hedged_eg_returns, dtype=np.float64)
    hedged_pch = np.asarray(hedged_pch_returns, dtype=np.float64)

    he_ols = hedge_effectiveness_from_returns(unhedged, hedged_ols)
    he_eg = hedge_effectiveness_from_returns(unhedged, hedged_eg)
    he_pch = hedge_effectiveness_from_returns(unhedged, hedged_pch)
    dm_t, dm_p = dm_test(hedged_pch**2, hedged_ols**2, h=1)
    ci = bootstrap_he_diff_ci(
        unhedged,
        hedged_pch,
        hedged_ols,
        block_len=block_len,
        n_boot=n_boot,
        seed=seed,
    )

    mean_r2_mr = float(np.mean([snap.r2_mr_pch for snap in refits]))
    valid_half_lives = [snap.half_life_days for snap in refits if snap.half_life_days is not None]
    summary = {
        "symbols": {"x": sym_x, "y": sym_y},
        "date_start": str(dates[0].date()),
        "date_end": str(dates[-1].date()),
        "n_obs_total": int(n),
        "n_obs_oos": int(len(unhedged)),
        "min_train": int(min_train),
        "refit_every": int(refit_every),
        "n_refits": int(len(refits)),
        "n_multistart": int(n_starts),
        "oos_window": {"start": oos_dates[0], "end": oos_dates[-1]},
        "hedge_effectiveness": {
            "ols": float(he_ols),
            "eg_vecm": float(he_eg),
            "pch": float(he_pch),
            "pch_minus_ols": float(he_pch - he_ols),
        },
        "dm_squared_hedge_loss_pch_vs_ols": {
            "t_stat": float(dm_t),
            "p_value": float(dm_p),
            "harvey_threshold_note": "Use |t| > 3.0 for strong claim under multiple testing.",
        },
        "bootstrap_he_diff": ci,
        "pch_refit_diagnostics": {
            "mean_beta": float(np.mean([snap.beta_pch for snap in refits])),
            "mean_rho": float(np.mean([snap.rho_pch for snap in refits])),
            "mean_r2_mr": mean_r2_mr,
            "median_half_life_days": (
                float(np.median(valid_half_lives)) if valid_half_lives else None
            ),
        },
        "refit_snapshots_head": [asdict(snap) for snap in refits[:10]],
    }
    print(
        f"[{pair_name}] OOS HE ols={he_ols:.4f} eg={he_eg:.4f} pch={he_pch:.4f} "
        f"DM_t={dm_t:.3f} CI={ci['ci_95']}",
        flush=True,
    )
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-train", type=int, default=756)
    parser.add_argument("--refit-every", type=int, default=21)
    parser.add_argument("--n-starts", type=int, default=100)
    parser.add_argument("--n-boot", type=int, default=1000)
    parser.add_argument("--block-len", type=int, default=20)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--result-path", type=Path, default=RESULT_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    results: Dict[str, Dict] = {}
    for pair_name, sym_x, sym_y in PAIRS:
        try:
            results[pair_name] = analyze_pair(
                pair_name,
                sym_x,
                sym_y,
                min_train=args.min_train,
                refit_every=args.refit_every,
                n_starts=args.n_starts,
                n_boot=args.n_boot,
                block_len=args.block_len,
                seed=args.seed,
            )
        except Exception as exc:
            results[pair_name] = {"error": str(exc)}
            print(f"[{pair_name}] ERROR {exc}", flush=True)

    payload = {
        "experiment_id": "k1426_oos",
        "title": "K1426 follow-up — expanding-window OOS partial cointegration hedging",
        "seed": int(args.seed),
        "data_range": {"start": START, "end": END},
        "spec": {
            "min_train": int(args.min_train),
            "refit_every": int(args.refit_every),
            "n_starts": int(args.n_starts),
            "n_boot": int(args.n_boot),
            "block_len": int(args.block_len),
            "lookahead_rule": "Train on [:t-1], apply hedge beta to return t via shift(1).",
        },
        "pairs": results,
        "notes": [
            "OOS HE is computed from hedged daily returns, not in-sample spread variance.",
            "EG-VECM hedge ratio equals stage-1 OLS beta here; alpha is omitted because OOS return hedge uses beta only.",
            "DM uses squared hedged returns as variance-loss proxy; negative t means PCH lower variance than OLS.",
            "Monthly (21-day) refit cadence is a compute tractability choice; parameters remain strictly lagged.",
        ],
        "reproduce": "uv run python experiments/k1426/oos.py",
    }
    args.result_path.write_text(json.dumps(payload, indent=2))
    print(f"Wrote {args.result_path}", flush=True)


if __name__ == "__main__":
    main()
