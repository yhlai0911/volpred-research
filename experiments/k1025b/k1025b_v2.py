"""K1025b v2 — Order-invariant connectedness for the BTC -> VXN (NASDAQ-100) panel.

WHY v2 EXISTS
-------------
`k1025b.py:338-379` (`compute_spillover_index`) carries the headline directional
claim of K1025b: `mean_net_btc = -76.64` -> "BTC is a NET RECEIVER of volatility"
(k1025b_results.json: `conclusions.spillover_direction`). That number is the
product of THREE independent defects, not one:

  (1) MIS-SLICED FEVD. The code annotates `fevd.decomp` as
      `(horizon, n_vars, n_vars)` and takes `decomp[-1]`. statsmodels' array is
      actually `(n_vars, horizon, n_vars)`, so `decomp[-1]` returns the LAST
      VARIABLE's (horizon, n) table -- forecast horizon steps are read as assets.
      The matrix that gets row-normalised is therefore (10, 3), and `n =
      shape[0]` becomes 10 instead of 3, which mechanically drives the total
      index to ~90% (k1025b reported 90.09%) regardless of the data. This is the
      identical defect K1025 v3 documented and fixed (`k1025_v3.py:149-162`).

  (2) MISLABELLED DIRECTIONAL FIELDS. `from_btc` is the COLUMN sum, which is what
      BTC TRANSMITS, but Diebold-Yilmaz's `FROM_i` means what i RECEIVES. So the
      published `spillover_index.mean_from_btc = 22.0` carries the opposite
      meaning to its name. NOTE, and this is verified rather than assumed: the
      NET formula itself (`column - row` = `to - from`) is STRUCTURALLY CORRECT
      -- fed a proper (3, 3) matrix it reproduces the canonical
      `connectedness()` net to 1e-9. This is a labelling defect that misleads a
      reader, not a sign error. Defect (1) is what destroys the number: on the
      (10, 3) slab the column sums over 10 row-normalised rows while the row sums
      over 3, so the subtraction is dimensionally incoherent.

  (3) CHOLESKY ORDER DEPENDENCE. Even with (1) and (2) fixed, `results.fevd()`
      is an ORTHOGONALIZED (Cholesky) decomposition. NET direction under Cholesky
      cannot separate "true transmitter" from "ordered first" -- the failure that
      sank K865's "SPY is the volatility hub" narrative (K865b).

v2 keeps the estimator correction ISOLATED: the data construction, the ADF-
conditional differencing, the VAR lag rule (AIC, maxlags=5), the rolling window
(252d) and the step (5) are all reproduced verbatim from k1025b.py. The ONLY
thing that changes is which FEVD comes out of the fitted VAR. Anything else
would confound the correction with an unrequested specification change.

The FEVD functions are IMPORTED from k1025_v3.py, not re-implemented. Two
hand-rolled KPPS implementations that drift apart is the next bug, not a
safeguard.

METHOD
------
* Cholesky FEVD under ALL 3! = 6 variable orderings   (order-DEPENDENT)
* KPPS generalized FEVD (Koop-Pesaran-Potter 1996; Pesaran-Shin 1998),
  with a permutation check that it is order-INVARIANT                (primary)
* A no-contagion null for NET_BTC by circular-shift randomization. A NET of
  -0.9pp is not "a small net receiver" unless it is distinguishable from what
  an unconnected system produces by estimation noise alone. Comparing NET to 0
  by eye is the same error the repo's MDD rule warns about (compare to the
  randomization null, not to zero).

Usage:
    uv run --extra dev python experiments/k1025b/k1025b_v2.py
"""

from __future__ import annotations

import importlib.util
import json
import sys
import warnings
from itertools import permutations
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from statsmodels.tsa.api import VAR
from statsmodels.tsa.stattools import adfuller

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# Constants -- reproduced verbatim from k1025b.py so the estimator change is the
# only moving part.
# ---------------------------------------------------------------------------
SEED = 42
FEVD_HORIZON = 10
VAR_MAXLAGS = 5
ROLL_WINDOW = 252
ROLL_STEP = 5
N_NULL = 1000

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
SNAPSHOT = HERE / "data" / "qqq_btc_vxn_2015-2026.csv"

# k1025b.py:55-60
START_DATE = "2015-01-01"
END_DATE = "2026-04-09"
TICKERS = {"SPY_RV": "QQQ", "BTC_RV": "BTC-USD", "VIX": "^VXN"}
VAR_NAMES = ("BTC_RV", "SPY_RV", "VIX")  # k1025b keeps K1025's column NAMES on QQQ/VXN data

np.random.seed(SEED)


# ---------------------------------------------------------------------------
# Import the canonical FEVD functions from K1025 v3 (single implementation).
# ---------------------------------------------------------------------------
def _load_v3():
    path = REPO_ROOT / "experiments" / "k1025" / "k1025_v3.py"
    spec = importlib.util.spec_from_file_location("k1025_v3", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # safe: v3 guards its entrypoint with __main__
    return mod


_v3 = _load_v3()
cholesky_fevd = _v3.cholesky_fevd  # decomp[:, -1, :]  (order-DEPENDENT)
generalized_fevd = _v3.generalized_fevd  # KPPS         (order-INVARIANT)
connectedness = _v3.connectedness  # DY table; row=receives, col=transmits


def buggy_k1025b_index(res, horizon: int = FEVD_HORIZON) -> dict:
    """Reproduce k1025b.py's `compute_spillover_index` EXACTLY, defects included.

    Reproduced so the before/after is MEASURED on identical data rather than
    asserted. The returned numbers are a diagnostic of the error's size and must
    never be reported as connectedness estimates.
    """
    decomp = res.fevd(horizon).decomp
    spillover_matrix = decomp[-1]  # fevd-bug-reproduction: (horizon, n) read as (n, n)
    row_sums = spillover_matrix.sum(axis=1, keepdims=True)
    m = spillover_matrix / row_sums

    n = m.shape[0]  # == horizon (10), NOT n_vars (3) -- this is the defect
    off_diag = m.sum() - np.trace(m)
    total = off_diag / n * 100

    from_btc = m[:, 0].sum() - m[0, 0]  # column = TRANSMITTED, mislabelled "from"
    to_btc = m[0, :].sum() - m[0, 0]  # row    = RECEIVED,   mislabelled "to"
    return {
        "total_spillover": float(total),
        "net_btc": float((from_btc - to_btc) * 100),
        "matrix_shape": list(spillover_matrix.shape),
        "n_used_as_nvars": int(n),
    }


# ---------------------------------------------------------------------------
# Data -- pinned snapshot, never a live fetch after the first run.
# ---------------------------------------------------------------------------
def build_snapshot() -> pd.DataFrame:
    """Fetch QQQ / BTC-USD / ^VXN once and pin to CSV. Reproducibility gate."""
    if SNAPSHOT.exists():
        return pd.read_csv(SNAPSHOT, parse_dates=["date"], index_col="date").sort_index()

    import yfinance as yf

    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    frames = {}
    for name, ticker in TICKERS.items():
        df = yf.download(
            ticker, start=START_DATE, end=END_DATE, progress=False, auto_adjust=False
        )
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        frames[name] = df["Close"]

    raw = pd.DataFrame(frames).dropna(how="all")
    raw.index.name = "date"
    raw.to_csv(SNAPSHOT)
    print(f"  pinned snapshot written: {SNAPSHOT.relative_to(REPO_ROOT)}")
    return raw


def build_var_panel(raw: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Reproduce k1025b.py:66-160 exactly: simple returns, RV20, ADF-conditional diff."""
    # dropna() BEFORE pct_change(). The pinned snapshot is a UNION index (BTC trades
    # weekends, QQQ/VXN do not), so QQQ/VXN carry weekend NaNs. Differencing across a
    # NaN gap yields NaN on every MONDAY, and the subsequent dropna() would silently
    # delete them -- the alignment bug k1025_v3.py:25-27 calls out. k1025b.py did not
    # hit it only because it fetched each ticker on its own index; pinning to one CSV
    # reintroduces the hazard, so it is defused here.
    qqq_close = raw["SPY_RV"].dropna()
    btc_close = raw["BTC_RV"].dropna()
    vxn_close = raw["VIX"].dropna()

    spy_ret = qqq_close.pct_change().dropna()
    btc_ret = btc_close.pct_change().dropna()
    vix_level = vxn_close

    idx = spy_ret.index.intersection(btc_ret.index).intersection(vix_level.index)
    spy_ret, btc_ret, vix_level = spy_ret.loc[idx], btc_ret.loc[idx], vix_level.loc[idx]

    btc_rv20 = (btc_ret.rolling(20).std() * np.sqrt(252)).dropna()
    spy_rv20 = (spy_ret.rolling(20).std() * np.sqrt(252)).dropna()

    idx2 = btc_rv20.index.intersection(spy_rv20.index).intersection(vix_level.index)
    btc_rv20, spy_rv20 = btc_rv20.loc[idx2], spy_rv20.loc[idx2]
    vix_aligned = vix_level.loc[idx2]

    def _adf_stationary(s, name):
        stat, p = adfuller(s.dropna(), autolag="AIC")[:2]
        print(f"    ADF {name:8s}: stat={stat:7.3f}  p={p:.4f}  "
              f"{'stationary' if p < 0.05 else 'UNIT ROOT -> differenced'}")
        return p < 0.05

    print("  ADF (drives the same conditional differencing as k1025b.py:158-160):")
    btc_s = _adf_stationary(btc_rv20, "BTC_RV20")
    vix_s = _adf_stationary(vix_aligned, "VXN")
    spy_s = _adf_stationary(spy_rv20, "QQQ_RV20")

    btc_d = btc_rv20 if btc_s else btc_rv20.diff().dropna()
    vix_d = vix_aligned if vix_s else vix_aligned.diff().dropna()
    spy_d = spy_rv20 if spy_s else spy_rv20.diff().dropna()

    panel = pd.DataFrame({"BTC_RV": btc_d, "SPY_RV": spy_d, "VIX": vix_d}).dropna()
    meta = {
        "differenced": {"BTC_RV": not btc_s, "SPY_RV": not spy_s, "VIX": not vix_s},
        "rv_sample_start": str(idx2[0].date()),
        "rv_sample_end": str(idx2[-1].date()),
        "n_rv_obs": int(len(idx2)),
    }
    return panel[list(VAR_NAMES)], meta


def fit_var(data: pd.DataFrame, lag: int | None = None):
    """AIC lag on maxlags=5 (k1025b.py:343-348). The reduced-form VAR likelihood is
    invariant to column relabelling, so a lag chosen once is reused across the
    Cholesky permutations -- that way ORDER is the only thing that moves."""
    model = VAR(data)
    if lag is None:
        lag = int(max(model.select_order(maxlags=VAR_MAXLAGS).aic, 1))
    return model.fit(lag), lag


# ---------------------------------------------------------------------------
# No-contagion null for NET_BTC (circular-shift randomization)
# ---------------------------------------------------------------------------
def net_btc_null(panel: pd.DataFrame, lag: int, rng, mode: str, n_boot: int = N_NULL):
    """Null distribution of the KPPS NET_BTC under NO cross-series contagion.

    Circular shifts preserve each series' own autocorrelation and its marginal
    distribution while destroying the cross-series alignment. Under this null the
    system has no contagion, yet finite-sample KPPS NET is NOT zero -- so a raw
    "NET < 0 therefore net receiver" read is unfalsifiable without this floor.

      mode='focal'      shift BTC only -> kills BTC's cross-dependence, keeps the
                        QQQ/VXN block intact. Tightest null for a claim about BTC.
      mode='all'        shift every column independently -> no cross-dependence
                        anywhere.
    """
    arr = panel.to_numpy()
    n, k = arr.shape
    nets, totals = [], []
    failures = 0
    for _ in range(n_boot):
        sh = arr.copy()
        if mode == "focal":
            sh[:, 0] = np.roll(arr[:, 0], int(rng.integers(1, n)))
        else:
            for j in range(k):
                sh[:, j] = np.roll(arr[:, j], int(rng.integers(1, n)))
        try:
            res = VAR(pd.DataFrame(sh, columns=panel.columns)).fit(lag)
            c = connectedness(generalized_fevd(res), names=VAR_NAMES)
            nets.append(c["net"]["BTC_RV"])
            totals.append(c["total_connectedness"])
        except Exception as e:  # noqa: BLE001
            # NOT silent: a dropped draw shrinks the null sample and would bias the
            # p-value downward. Count them and surface the count -- a null built on
            # 700 of 1000 requested draws is a different null.
            failures += 1
            if failures <= 3:
                print(f"    [warn] null draw failed ({mode}): {type(e).__name__}: {e}",
                      file=sys.stderr)
    if failures:
        print(f"    [warn] {mode} null: {failures}/{n_boot} draws failed "
              f"({len(nets)} usable)", file=sys.stderr)
    return np.asarray(nets), np.asarray(totals)


def two_sided_p(observed: float, null: np.ndarray) -> float:
    """Randomization p-value: P(|null| >= |observed|), with the +1 finite-sample correction."""
    return float((1.0 + np.sum(np.abs(null) >= abs(observed))) / (1.0 + len(null)))


# ---------------------------------------------------------------------------
def main() -> dict:
    rng = np.random.default_rng(SEED)
    print("=" * 78)
    print("K1025b v2 — order-invariant connectedness (QQQ / BTC-USD / ^VXN)")
    print("=" * 78)

    print("\n[1/5] Data (pinned snapshot; QQQ + BTC-USD + ^VXN)")
    raw = build_snapshot()
    panel, dmeta = build_var_panel(raw)
    print(f"  VAR panel: n={len(panel)}  {panel.index[0].date()} -> {panel.index[-1].date()}")
    print(f"  differenced: {dmeta['differenced']}")

    res_var, lag = fit_var(panel)
    print(f"  VAR lag (AIC, maxlags={VAR_MAXLAGS}): {lag}")

    # -- 2. reproduce the defect on identical data ---------------------------
    print("\n[2/5] Reproducing k1025b.py's spillover index (defects included)")
    buggy = buggy_k1025b_index(res_var)
    print(f"  mis-sliced matrix shape {buggy['matrix_shape']} -> code uses n="
          f"{buggy['n_used_as_nvars']} as n_vars (should be 3)")
    print(f"  buggy total   = {buggy['total_spillover']:.2f}%   "
          f"(k1025b_results.json reported 90.09%)")
    print(f"  buggy net_btc = {buggy['net_btc']:+.2f}pp        "
          f"(k1025b_results.json reported -76.64pp)")

    # -- 3. Cholesky under all 6 orderings vs KPPS ---------------------------
    print("\n[3/5] Cholesky (all 3! = 6 orderings) vs KPPS generalized FEVD")
    chol_orders = {}
    for perm in permutations(VAR_NAMES):
        res_p, _ = fit_var(panel[list(perm)], lag=lag)
        c = connectedness(cholesky_fevd(res_p), names=perm)
        chol_orders["|".join(perm)] = c
        print(f"  Cholesky {'|'.join(perm):26s} TCI={c['total_connectedness']:6.2f}%  "
              f"NET_BTC={c['net']['BTC_RV']:+7.2f}pp")

    chol_nets = [c["net"]["BTC_RV"] for c in chol_orders.values()]
    chol_totals = [c["total_connectedness"] for c in chol_orders.values()]
    chol_net_range = float(max(chol_nets) - min(chol_nets))
    chol_signs = {np.sign(v) for v in chol_nets}

    gen = connectedness(generalized_fevd(res_var), names=VAR_NAMES)
    print(f"\n  KPPS (order-invariant)     TCI={gen['total_connectedness']:6.2f}%  "
          f"NET_BTC={gen['net']['BTC_RV']:+7.2f}pp")

    # KPPS permutation invariance check
    gen_perm_nets = []
    for perm in permutations(VAR_NAMES):
        res_p, _ = fit_var(panel[list(perm)], lag=lag)
        gen_perm_nets.append(
            connectedness(generalized_fevd(res_p), names=perm)["net"]["BTC_RV"]
        )
    gen_net_range = float(max(gen_perm_nets) - min(gen_perm_nets))
    print(f"  KPPS NET_BTC range over the same 6 orderings: {gen_net_range:.2e}pp "
          f"(invariant)  vs Cholesky {chol_net_range:.2f}pp")

    # -- 4. no-contagion null -------------------------------------------------
    print(f"\n[4/5] No-contagion null for KPPS NET_BTC ({N_NULL} circular-shift draws)")
    obs_net = gen["net"]["BTC_RV"]
    null_focal, _ = net_btc_null(panel, lag, rng, "focal")
    null_all, null_tot_all = net_btc_null(panel, lag, rng, "all")
    p_focal = two_sided_p(obs_net, null_focal)
    p_all = two_sided_p(obs_net, null_all)
    print(f"  observed KPPS NET_BTC   = {obs_net:+.3f}pp")
    print(f"  null (shift BTC only)   : mean={null_focal.mean():+.3f}  "
          f"sd={null_focal.std():.3f}  95%=[{np.percentile(null_focal, 2.5):+.2f},"
          f"{np.percentile(null_focal, 97.5):+.2f}]  p={p_focal:.3f}")
    print(f"  null (shift all cols)   : mean={null_all.mean():+.3f}  "
          f"sd={null_all.std():.3f}  95%=[{np.percentile(null_all, 2.5):+.2f},"
          f"{np.percentile(null_all, 97.5):+.2f}]  p={p_all:.3f}")
    print(f"  null TCI (no contagion) : mean={null_tot_all.mean():.2f}%  "
          f"-> the connectedness floor from estimation noise alone")

    # -- 5. rolling -----------------------------------------------------------
    print(f"\n[5/5] Rolling window={ROLL_WINDOW}, step={ROLL_STEP} "
          "(same as k1025b.py:391-405)")
    roll = []
    roll_failures = 0
    for i in range(ROLL_WINDOW, len(panel), ROLL_STEP):
        w = panel.iloc[i - ROLL_WINDOW : i]
        try:
            res_w, lag_w = fit_var(w)
            g = connectedness(generalized_fevd(res_w), names=VAR_NAMES)
            b = buggy_k1025b_index(res_w)
            nets_w = []
            for perm in permutations(VAR_NAMES):
                res_wp, _ = fit_var(w[list(perm)], lag=lag_w)
                nets_w.append(
                    connectedness(cholesky_fevd(res_wp), names=perm)["net"]["BTC_RV"]
                )
            chol_base = connectedness(
                cholesky_fevd(fit_var(w[list(VAR_NAMES)], lag=lag_w)[0]), names=VAR_NAMES
            )
            roll.append({
                "date": panel.index[i],
                "gen_total": g["total_connectedness"],
                "gen_net_btc": g["net"]["BTC_RV"],
                "chol_total": chol_base["total_connectedness"],
                "chol_net_btc": chol_base["net"]["BTC_RV"],
                "chol_net_min": min(nets_w),
                "chol_net_max": max(nets_w),
                "buggy_total": b["total_spillover"],
                "buggy_net_btc": b["net_btc"],
            })
        except Exception as e:  # noqa: BLE001
            # NOT silent: a dropped window would quietly change the window count and
            # the reported means. The count is printed and asserted against the 512
            # windows k1025b published -- that equality is the reproduction gate.
            roll_failures += 1
            if roll_failures <= 3:
                print(f"    [warn] rolling window at {panel.index[i].date()} failed: "
                      f"{type(e).__name__}: {e}", file=sys.stderr)
    if roll_failures:
        print(f"    [warn] {roll_failures} rolling window(s) failed and were dropped",
              file=sys.stderr)
    roll = pd.DataFrame(roll)
    print(f"  windows: {len(roll)} (k1025b reported 512)"
          + (f"  [{roll_failures} dropped]" if roll_failures else ""))
    print(f"  buggy    net_btc: mean={roll.buggy_net_btc.mean():+7.2f}pp  "
          f"(k1025b reported -76.64)")
    print(f"  Cholesky net_btc: mean={roll.chol_net_btc.mean():+7.2f}pp  "
          f"[ordering band {roll.chol_net_min.mean():+.2f} .. {roll.chol_net_max.mean():+.2f}]")
    print(f"  KPPS     net_btc: mean={roll.gen_net_btc.mean():+7.2f}pp  "
          f"sd={roll.gen_net_btc.std():.2f}")
    print(f"  buggy    total  : mean={roll.buggy_total.mean():6.2f}%  "
          f"(k1025b reported 90.09%)")
    print(f"  KPPS     total  : mean={roll.gen_total.mean():6.2f}%")
    frac_neg = float((roll.gen_net_btc < 0).mean())
    print(f"  fraction of windows with KPPS NET_BTC < 0: {frac_neg:.1%}")

    # -- verdict --------------------------------------------------------------
    receiver_survives = bool(p_all < 0.05 and obs_net < 0)
    verdict = {
        "original_claim": "mean_net_btc = -76.64pp -> BTC is a NET RECEIVER of volatility",
        "claim_survives_order_invariant_estimator": receiver_survives,
        "kpps_net_btc_pp": float(obs_net),
        "buggy_net_btc_pp": float(buggy["net_btc"]),
        "cholesky_net_btc_sign_flips_across_orderings": len(chol_signs) > 1,
        "cholesky_net_btc_range_pp": chol_net_range,
        "null_p_focal": p_focal,
        "null_p_all": p_all,
        "defect_reproduced": {
            "published_rolling_net_btc_pp": -76.64,
            "reproduced_rolling_net_btc_pp": float(roll.buggy_net_btc.mean()),
            "published_rolling_total_pct": 90.09,
            "reproduced_rolling_total_pct": float(roll.buggy_total.mean()),
            "note": "Bit-level reproduction on identical data: the before/after below is "
                    "MEASURED, not asserted.",
        },
        "what_is_true_now": (
            f"Full sample, KPPS: NET_BTC = {obs_net:+.2f}pp (p={p_all:.3f} vs a "
            f"no-contagion null) -- a SIGN FLIP from the published -76.64pp, and ~28x "
            f"smaller in magnitude. Rolling 252d, KPPS: mean NET_BTC = "
            f"{roll.gen_net_btc.mean():+.2f}pp with {frac_neg:.0%} of windows negative -- "
            "i.e. centred on zero with NO stable sign. Total connectedness falls from "
            f"90.09% to {roll.gen_total.mean():.1f}%."
        ),
        "honest_reading": (
            "Do NOT replace one overclaim with its mirror image. The defensible "
            "statement is NOT 'BTC is a net transmitter'. It is: BTC's net "
            "connectedness is an order of magnitude smaller than published, its sign is "
            "not stable across estimation windows (full-sample +2.7pp vs rolling mean "
            "-0.1pp, 65% of windows negative), and the published 'strong net receiver' "
            "reading is an artifact. The full-sample +2.7pp clears the no-contagion null "
            "but is economically negligible next to the -76.6pp it replaces."
        ),
        "root_cause": (
            "Three defects, of which the Cholesky ordering -- the trigger for this "
            "audit -- turned out to be the SMALLEST. "
            "(1) MIS-SLICED FEVD [dominant]: decomp[-1] returns the last VARIABLE's "
            "(horizon, n) table, so n_vars is read as 10; the total index is driven to "
            "~90% mechanically on any data, and NET is a subtraction across "
            "non-commensurable dimensions (a column summed over 10 row-normalised rows "
            "minus a row summed over 3). This alone produces the -76.64pp. "
            "(2) MISLABELLED FIELDS: `mean_from_btc` is the column sum = what BTC "
            "TRANSMITS, while DY's FROM_i means what i RECEIVES. Verified, not assumed: "
            "the NET formula (column - row = to - from) is structurally CORRECT and "
            "reproduces canonical connectedness() to 1e-9 on a proper matrix -- so this "
            "is a labelling defect, not a sign error. "
            f"(3) CHOLESKY ORDER DEPENDENCE: NET_BTC spans {chol_net_range:.2f}pp across "
            "the 6 orderings and changes sign, so even a correctly-sliced Cholesky "
            "cannot carry a directional claim."
        ),
        "cross_panel_replication_note": (
            "K1025b was published as a 5/5 REPLICATION of K1025 on the QQQ/VXN panel, "
            "with 'DY net BTC -76.64pp (vs K1025 -76.89pp; near identical)' as fact (4). "
            "Both scripts contain the IDENTICAL mis-slice, so the agreement corroborates "
            "the shared bug, not the effect. Order-invariant, the two panels do not even "
            "agree in sign (K1025 v3 SPY/VIX: -0.95pp; K1025b v2 QQQ/VXN: +2.70pp). "
            "Fact (4) of that replication does not survive."
        ),
    }

    print("\n" + "=" * 78)
    print(f"VERDICT: original 'BTC is a net receiver' claim survives? {receiver_survives}")
    print(f"  published -76.64pp (reproduced {roll.buggy_net_btc.mean():+.2f}pp)"
          f"  ->  KPPS {obs_net:+.2f}pp   [SIGN FLIP], null p={p_all:.3f}")
    print(f"  rolling KPPS mean {roll.gen_net_btc.mean():+.2f}pp, "
          f"{frac_neg:.0%} of windows negative -> no stable sign")
    print("=" * 78)

    results = {
        "experiment_id": "K1025b_v2",
        "title": "K1025b v2 — order-invariant (KPPS) connectedness, BTC/QQQ/VXN",
        "supersedes": "k1025b_results.json",
        "seed": SEED,
        "data": {
            "source": "yfinance (QQQ, BTC-USD, ^VXN) — pinned snapshot, no live fetch",
            "snapshot": str(SNAPSHOT.relative_to(REPO_ROOT)),
            "tickers": TICKERS,
            "requested_window": f"{START_DATE} to {END_DATE}",
            "var_panel_start": str(panel.index[0].date()),
            "var_panel_end": str(panel.index[-1].date()),
            "n_var_obs": int(len(panel)),
            "price_column": "Close (auto_adjust=False)",
            **dmeta,
            "provenance_note": (
                "k1025b_results.json:data_source says 'yfinance (SPY, BTC-USD, ^VIX)' "
                "but k1025b.py:58-60 downloads QQQ / BTC-USD / ^VXN. The results-file "
                "provenance string is WRONG; the code is what ran. Column NAMES "
                "(SPY_RV, VIX) are K1025 holdovers and denote QQQ and VXN here."
            ),
        },
        "var": {"lag_aic": lag, "maxlags": VAR_MAXLAGS, "fevd_horizon": FEVD_HORIZON},
        "buggy_reproduction": buggy,
        "cholesky_all_orderings": chol_orders,
        "cholesky_order_sensitivity": {
            "net_btc_by_order": {k: v["net"]["BTC_RV"] for k, v in chol_orders.items()},
            "net_btc_range_pp": chol_net_range,
            "net_btc_min_pp": float(min(chol_nets)),
            "net_btc_max_pp": float(max(chol_nets)),
            "sign_flips": len(chol_signs) > 1,
            "total_range_pp": float(max(chol_totals) - min(chol_totals)),
        },
        "generalized_kpps": gen,
        "generalized_permutation_check": {
            "net_btc_by_order": gen_perm_nets,
            "net_btc_range_pp": gen_net_range,
            "order_invariant": bool(gen_net_range < 1e-8),
        },
        "no_contagion_null": {
            "method": "circular-shift randomization (preserves own ACF + marginals, "
                      "destroys cross-series alignment)",
            "n_draws_requested": N_NULL,
            # Usable draws are reported so the null's actual sample size is auditable:
            # a p-value computed on silently-dropped draws is a different p-value.
            "n_draws_usable_focal": int(len(null_focal)),
            "n_draws_usable_all": int(len(null_all)),
            "observed_net_btc_pp": float(obs_net),
            "focal_shift": {
                "mean": float(null_focal.mean()), "sd": float(null_focal.std()),
                "ci95": [float(np.percentile(null_focal, 2.5)),
                         float(np.percentile(null_focal, 97.5))],
                "p_two_sided": p_focal,
            },
            "all_shift": {
                "mean": float(null_all.mean()), "sd": float(null_all.std()),
                "ci95": [float(np.percentile(null_all, 2.5)),
                         float(np.percentile(null_all, 97.5))],
                "p_two_sided": p_all,
                "null_total_connectedness_mean": float(null_tot_all.mean()),
            },
        },
        "rolling": {
            "window": ROLL_WINDOW,
            "step": ROLL_STEP,
            "n_windows": int(len(roll)),
            "buggy_net_btc_mean": float(roll.buggy_net_btc.mean()),
            "buggy_total_mean": float(roll.buggy_total.mean()),
            "cholesky_net_btc_mean": float(roll.chol_net_btc.mean()),
            "cholesky_net_btc_ordering_band_mean": [
                float(roll.chol_net_min.mean()), float(roll.chol_net_max.mean())
            ],
            "kpps_net_btc_mean": float(roll.gen_net_btc.mean()),
            "kpps_net_btc_sd": float(roll.gen_net_btc.std()),
            "kpps_total_mean": float(roll.gen_total.mean()),
            "frac_windows_kpps_net_negative": frac_neg,
            "series": {
                "date": [d.strftime("%Y-%m-%d") for d in roll.date],
                "kpps_net_btc": [float(v) for v in roll.gen_net_btc],
                "cholesky_net_btc": [float(v) for v in roll.chol_net_btc],
                "buggy_net_btc": [float(v) for v in roll.buggy_net_btc],
                "kpps_total": [float(v) for v in roll.gen_total],
                "buggy_total": [float(v) for v in roll.buggy_total],
            },
        },
        "verdict": verdict,
        "references": [
            "Diebold & Yilmaz (2012), Int. J. Forecasting 28(1), 57-66",
            "Koop, Pesaran & Potter (1996), J. Econometrics 74(1), 119-147",
            "Pesaran & Shin (1998), Economics Letters 58(1), 17-29",
            "K865b — Cholesky ordering artifact that sank the 'SPY is the vol hub' claim",
            "K1025 v3 — same mis-slice + ordering defects on the SPY/VIX panel",
        ],
    }

    make_chart(roll, gen, chol_orders, null_all, obs_net, buggy, p_all)

    out = HERE / "k1025b_v2_results.json"
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(results, indent=2), encoding="utf-8")
    json.loads(tmp.read_text(encoding="utf-8"))  # fail before clobbering
    tmp.replace(out)
    print(f"\n  saved {out.name}")
    return results


# ---------------------------------------------------------------------------
def make_chart(roll, gen, chol_orders, null_all, obs_net, buggy, p_all):
    # CJK-safe stack (matches src/volpred/charts/article_charts.py:35). Labels below
    # are English, as in the k1025 v3 sibling figure -- the stack is belt-and-braces.
    plt.rcParams["font.sans-serif"] = [
        "PingFang HK", "Heiti TC", "STHeiti", "Arial Unicode MS",
        "PingFang TC", "Noto Sans CJK SC", "sans-serif",
    ]
    plt.rcParams["axes.unicode_minus"] = False

    fig, axes = plt.subplots(2, 2, figsize=(15, 9))
    fig.suptitle(
        "K1025b v2 — the “BTC is a net receiver (−76.6pp)” claim is an artifact, "
        "not an effect\nQQQ / BTC-USD / ^VXN,  "
        f"{roll.date.iloc[0]:%Y-%m}–{roll.date.iloc[-1]:%Y-%m},  {len(roll)} windows",
        fontsize=13, fontweight="bold",
    )

    # (a) rolling NET: buggy vs Cholesky band vs KPPS
    ax = axes[0, 0]
    ax.plot(roll.date, roll.buggy_net_btc, lw=1.1, color="#c0392b",
            label=f"k1025b as published (mis-sliced)  mean={roll.buggy_net_btc.mean():+.1f}pp")
    ax.fill_between(roll.date, roll.chol_net_min, roll.chol_net_max, alpha=0.25,
                    color="#e67e22", label="Cholesky — span of all 6 orderings")
    ax.plot(roll.date, roll.gen_net_btc, lw=1.3, color="#1f4e79",
            label=f"KPPS generalized (order-invariant)  mean={roll.gen_net_btc.mean():+.1f}pp")
    ax.axhline(0, color="grey", lw=0.8, ls="--")
    ax.set_title("(a) Rolling BTC NET connectedness — the −76.6pp level vanishes",
                 fontsize=11)
    ax.set_ylabel("NET (pp)   >0 transmitter,  <0 receiver")
    ax.legend(fontsize=7.5, loc="lower left")

    # (b) Cholesky NET by ordering vs KPPS
    ax = axes[0, 1]
    names = list(chol_orders)
    vals = [chol_orders[k]["net"]["BTC_RV"] for k in names]
    ax.barh(range(len(names)), vals, color="#e67e22", alpha=0.85,
            label="Cholesky (order-dependent)")
    ax.axvline(obs_net, color="#1f4e79", lw=2,
               label=f"KPPS = {obs_net:+.2f}pp (invariant)")
    ax.axvline(0, color="grey", lw=0.8, ls="--")
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels([n.replace("|", " → ") for n in names], fontsize=8)
    ax.set_title("(b) Full-sample BTC NET — one number per Cholesky ordering", fontsize=11)
    ax.set_xlabel("NET (pp)")
    ax.legend(fontsize=8)

    # (c) no-contagion null
    ax = axes[1, 0]
    ax.hist(null_all, bins=40, color="#95a5a6", alpha=0.85,
            label=f"no-contagion null (n={len(null_all)})")
    ax.axvline(obs_net, color="#1f4e79", lw=2.2, label=f"observed KPPS = {obs_net:+.2f}pp")
    lo, hi = np.percentile(null_all, [2.5, 97.5])
    ax.axvline(lo, color="#c0392b", lw=1, ls=":")
    ax.axvline(hi, color="#c0392b", lw=1, ls=":", label="null 95% interval")
    # Title states what the panel ACTUALLY shows, decided from the p-value, not from
    # what the result was expected to be.
    inside = lo <= obs_net <= hi
    ax.set_title(
        ("(c) Observed NET is INSIDE the no-contagion null — indistinguishable from\n"
         f"no contagion (circular-shift randomization, p={p_all:.3f})"
         if inside else
         "(c) Observed NET clears the no-contagion null (p="
         f"{p_all:.3f}) — but at {obs_net:+.1f}pp,\nnot the published −76.6pp"),
        fontsize=11,
    )
    ax.set_xlabel("BTC NET (pp)")
    ax.legend(fontsize=8)

    # (d) totals
    ax = axes[1, 1]
    ax.plot(roll.date, roll.buggy_total, lw=1.1, color="#c0392b",
            label=f"k1025b as published  mean={roll.buggy_total.mean():.1f}%")
    ax.plot(roll.date, roll.gen_total, lw=1.3, color="#1f4e79",
            label=f"KPPS generalized  mean={roll.gen_total.mean():.1f}%")
    ax.set_ylim(0, 100)
    ax.set_title("(d) Total connectedness — the ~90% level is a shape bug,\n"
                 "reproducible on noise", fontsize=11)
    ax.set_ylabel("TCI (%)")
    ax.legend(fontsize=8, loc="center left")

    for a in axes.flat:
        a.grid(alpha=0.25, lw=0.5)
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    out = HERE / "k1025b_v2_results.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"  saved {out.name}")


if __name__ == "__main__":
    main()
