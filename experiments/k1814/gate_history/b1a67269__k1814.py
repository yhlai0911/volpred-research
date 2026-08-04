#!/usr/bin/env python3
"""K1814 -- Where (if anywhere) does deep learning beat HAR? A horizon-boundary test.

The question this answers is NOT "is there a better architecture". K1310-K1330 already
ran four ML novel-method experiments (GARCH-Neural / HAR-GNN / Transformer / KAN /
Conformal) and all returned NULL at the 1-day horizon. What those NULLs left open is
whether the DL increment shows up further out. So: h in {1, 5, 22}, one honest HAR
baseline, and a formal DM-HLN test per horizon with BH-FDR across the family.

DATA CALIBRE (read this before reading any number below)
--------------------------------------------------------
This experiment uses a DAILY REALIZED-RANGE PROXY, not 5-minute realized variance.
That is a measured decision, not a convenience: yfinance returns exactly 60 trading
days of 5-minute bars (verified in `probe_intraday_limits`), which cannot support a
22-day-horizon rolling OOS at all. Route B of the task brief was therefore taken.
`proxy_validation` quantifies how the proxy tracks genuine 5-min RV on the 60-day
overlap and genuine 1-hour RV on the ~725-day overlap, so the substitution is
measured rather than asserted.

A second data fact forced the estimator choice: ^GSPC's `Open` on yfinance equals the
prior `Close` on 59% of days (97% in the 1960s). Garman-Klass and Rogers-Satchell both
depend on Open, so on the long sample they would silently degenerate. Parkinson (High,
Low only) is the primary estimator; GK and RS are run on SPY/QQQ, which have genuine
Opens, as an estimator-robustness arm.

LOOKAHEAD POLICY (the thing most likely to be wrong, so it is mechanically tested)
---------------------------------------------------------------------------------
1. Feature row t uses rv/return observations with index <= t. Target row t uses
   rv observations with index in [t+1, t+h]. Never any overlap.
2. Direct h-step training embargo: a model forecasting from origin T is fit only on
   rows t with t + h <= T, because row t's target is not yet observable at T
   otherwise. Applied identically to HAR and to the DL models.
3. Scalers (X and y) are fit on the training slice only, refit at every origin.
   No full-sample standardisation anywhere.
4. Hyperparameters are chosen once, at the FIRST origin, on a chronological
   validation tail inside that origin's training window. Never on OOS.
5. `lookahead_selftests` proves 1+2 by perturbation: mutating the future cannot move
   a feature, and mutating the past cannot move a target. It raises on violation.

All randomness is seeded from 42.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import time
import warnings
from dataclasses import dataclass, field, replace
from pathlib import Path

T0 = time.time()

import numpy as np
import pandas as pd

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import torch
import torch.nn as nn

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning)
warnings.filterwarnings("ignore", message=".*enable_nested_tensor.*")

EXP_DIR = Path(__file__).resolve().parent
DATA_DIR = EXP_DIR / "data"
BASE_SEED = 42
HORIZONS = (1, 5, 22)
TRADING_DAYS = 252

# Measured: 1 thread beats 2/4/8 on these tiny models (8.25s vs 8.81/8.80/9.71 for one
# LSTM+Transformer fit pair) -- thread overhead dominates at this size.
torch.set_num_threads(1)


# --------------------------------------------------------------------------------------
# config
# --------------------------------------------------------------------------------------
@dataclass
class Config:
    seq_len: int = 22          # DL lookback; == HAR's monthly window, so DL sees a superset
    train_len: int = 3000      # rolling training window, trading days (~12y)
    refit_every: int = 750     # re-estimate every N OOS days
    val_frac: float = 0.15     # chronological tail of the training window, for early stopping
    n_seeds: int = 5
    max_epochs: int = 100
    patience: int = 12
    batch_size: int = 128
    hidden: int = 32
    d_model: int = 32
    lr: float = 1e-3
    loss: str = "logmse"       # "logmse" | "qlike"
    channels: int = 1          # 1 = log RV only (information-matched to HAR-RV); 2 adds returns
    pilot: bool = False


# --------------------------------------------------------------------------------------
# data
# --------------------------------------------------------------------------------------
def _flatten(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    return df


def load_daily(ticker: str, start: str) -> pd.DataFrame:
    """Daily OHLC, cached to CSV so the run is byte-reproducible from `inputs`."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cache = DATA_DIR / f"{ticker.replace('^', '')}_daily.csv"
    if cache.exists():
        df = pd.read_csv(cache, index_col=0, parse_dates=True)
    else:
        import yfinance as yf

        df = yf.download(ticker, start=start, interval="1d", progress=False, auto_adjust=False)
        df = _flatten(df)[["Open", "High", "Low", "Close"]].dropna()
        df.to_csv(cache)
    return df[["Open", "High", "Low", "Close"]].astype(float)


def range_proxies(df: pd.DataFrame) -> dict[str, np.ndarray]:
    """Daily variance estimators from OHLC. All are intraday-only (no overnight gap)."""
    o, h, l, c = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
    hl = np.log(h / l)
    park = hl**2 / (4.0 * math.log(2.0))
    gk = 0.5 * hl**2 - (2.0 * math.log(2.0) - 1.0) * np.log(c / o) ** 2
    rs = np.log(h / c) * np.log(h / o) + np.log(l / c) * np.log(l / o)
    return {"parkinson": park, "garman_klass": gk, "rogers_satchell": rs}


# A FIXED, pre-specified floor: 1e-7 daily variance == 0.5% annualised. Deliberately not a
# sample quantile. A quantile computed over the whole series lets a 2020 observation change
# the floor applied to a 1963 one, which is full-sample leakage into both features and
# targets -- and it slips past a perturbation self-test that runs after flooring.
RV_FLOOR = 1e-7


def floor_positive(x: np.ndarray) -> tuple[np.ndarray, int]:
    """Zero/negative variance estimates cannot be logged. Replace with a fixed constant."""
    bad = int((x <= 0).sum())
    return np.where(x > 0, x, RV_FLOOR), bad


# --------------------------------------------------------------------------------------
# feature / target construction  (see LOOKAHEAD POLICY in the module docstring)
# --------------------------------------------------------------------------------------
@dataclass
class Panel:
    dates: pd.DatetimeIndex
    har_x: np.ndarray            # (n,3)  log rv_d, log rv_w, log rv_m   -- info <= t
    harl_x: np.ndarray           # (n,5)  + r_t and I(r_t<0)*r_t          -- info <= t
    lag_x: np.ndarray            # (n,L)  log rv_{t-L+1..t}               -- info <= t
    seq: np.ndarray              # (n,L,2) [log rv, r]                    -- info <= t
    logy: dict[int, np.ndarray]  # h -> log mean(rv_{t+1..t+h})           -- info in (t, t+h]
    levy: dict[int, np.ndarray]  # h -> mean(rv_{t+1..t+h})
    row_of: np.ndarray           # panel row -> index into the raw rv array
    n_raw: int
    seq_len: int = field(default=22)


def build_panel(rv: np.ndarray, ret: np.ndarray, seq_len: int, dates: pd.DatetimeIndex,
                channels: int = 1) -> Panel:
    n = len(rv)
    lrv = np.log(rv)
    # warm-up: need seq_len-1 lags for the sequence and 21 lags for HAR's monthly term
    start = max(seq_len - 1, 21)
    # tail: need rv[t+1 .. t+max(h)] for the longest target
    stop = n - max(HORIZONS)
    rows = np.arange(start, stop)

    # Backward means built as EXACT sums over the k values they depend on. Deliberately
    # not cumsum-differencing: over 16k rows that loses ~1e-12 relative precision to
    # catastrophic cancellation, which the perturbation self-test detects as a false
    # lookahead. Summing only the window makes both the value and the lag self-evident.
    def back_mean(k: int) -> np.ndarray:
        acc = np.zeros(len(rows))
        for i in range(k):
            acc += rv[rows - i]          # i=0 is day t -> strictly info <= t
        return acc / k

    w = np.log(back_mean(5))
    m = np.log(back_mean(22))

    har_x = np.column_stack([lrv[rows], w, m])
    neg = np.minimum(ret, 0.0)
    harl_x = np.column_stack([lrv[rows], w, m, ret[rows], neg[rows]])

    lag_x = np.column_stack([lrv[rows - k] for k in range(seq_len)])[:, ::-1].copy()
    # channels=1 (the PRIMARY setting) gives the DL models exactly HAR-RV's information set:
    # the last `seq_len` log RV values, of which HAR's d/w/m terms are three linear
    # aggregates. A DL win under channels=1 therefore cannot be an information advantage.
    # channels=2 adds the return path (leverage); that arm is compared against HAR-L, which
    # has the return term, not against HAR-RV, which has no return information at all.
    chans = [np.column_stack([lrv[rows - k] for k in range(seq_len)])[:, ::-1]]
    if channels == 2:
        chans.append(np.column_stack([ret[rows - k] for k in range(seq_len)])[:, ::-1])
    seq = np.stack(chans, axis=-1).copy()

    logy: dict[int, np.ndarray] = {}
    levy: dict[int, np.ndarray] = {}
    for h in HORIZONS:
        acc = np.zeros(len(rows))
        for i in range(1, h + 1):
            acc += rv[rows + i]          # i starts at 1 -> strictly info in (t, t+h]
        fut = acc / h
        levy[h] = fut
        logy[h] = np.log(fut)

    assert np.isfinite(har_x).all() and np.isfinite(seq).all()
    return Panel(
        dates=dates[rows], har_x=har_x, harl_x=harl_x, lag_x=lag_x, seq=seq,
        logy=logy, levy=levy, row_of=rows, n_raw=n, seq_len=seq_len,
    )


def lookahead_selftests(rv: np.ndarray, ret: np.ndarray, seq_len: int,
                        dates: pd.DatetimeIndex, rng: np.random.Generator) -> dict:
    """Perturbation proof of the two directions of the no-lookahead claim.

    (a) corrupt rv/ret strictly AFTER t  -> every feature at row t must be unchanged.
    (b) corrupt rv strictly AT OR BEFORE t -> every target at row t must be unchanged.
    Also re-derives one row's features/targets by naive slicing as an independent check.
    Flooring is applied INSIDE the perturbed rebuilds, so a data-dependent floor (the bug
    a full-sample quantile would introduce) would show up here as a violation.
    """
    base = build_panel(floor_positive(rv)[0], ret, seq_len, dates, channels=2)
    n = base.n_raw
    probes = sorted(rng.choice(len(base.row_of), size=min(40, len(base.row_of)), replace=False))
    checks = {"future_cannot_move_features": 0, "past_cannot_move_targets": 0, "naive_reconstruction": 0}

    for pi in probes:
        t = int(base.row_of[pi])

        rv_a, ret_a = rv.copy(), ret.copy()
        rv_a[t + 1:] *= 7.3
        ret_a[t + 1:] += 0.9
        pa = build_panel(floor_positive(rv_a)[0], ret_a, seq_len, dates, channels=2)
        pos = int(np.searchsorted(pa.row_of, t))
        for name, A, B in (("har", base.har_x, pa.har_x), ("harl", base.harl_x, pa.harl_x),
                           ("lag", base.lag_x, pa.lag_x), ("seq", base.seq, pa.seq)):
            # atol=0: windowed sums touch only in-window values, so equality is exact
            if not np.array_equal(A[pi], B[pos]):
                raise AssertionError(f"LOOKAHEAD: future data moved feature '{name}' at row {t}")
        checks["future_cannot_move_features"] += 1

        rv_b = rv.copy()
        rv_b[: t + 1] *= 5.1
        pb = build_panel(floor_positive(rv_b)[0], ret, seq_len, dates, channels=2)
        pos = int(np.searchsorted(pb.row_of, t))
        for h in HORIZONS:
            if base.logy[h][pi] != pb.logy[h][pos] or base.levy[h][pi] != pb.levy[h][pos]:
                raise AssertionError(f"LOOKAHEAD: past data moved the h={h} target at row {t}")
        checks["past_cannot_move_targets"] += 1

        # independent naive reconstruction
        assert abs(base.har_x[pi, 0] - math.log(rv[t])) < 1e-12
        assert abs(base.har_x[pi, 1] - math.log(rv[t - 4: t + 1].mean())) < 1e-10
        assert abs(base.har_x[pi, 2] - math.log(rv[t - 21: t + 1].mean())) < 1e-10
        for h in HORIZONS:
            assert abs(base.levy[h][pi] - rv[t + 1: t + h + 1].mean()) < 1e-12
        assert abs(base.seq[pi, -1, 0] - math.log(rv[t])) < 1e-12
        assert abs(base.seq[pi, 0, 0] - math.log(rv[t - (seq_len - 1)])) < 1e-12
        checks["naive_reconstruction"] += 1

    checks["n_probe_rows"] = len(probes)
    checks["n_raw"] = int(n)
    return checks


# --------------------------------------------------------------------------------------
# losses / tests
# --------------------------------------------------------------------------------------
def qlike(actual: np.ndarray, fc: np.ndarray) -> np.ndarray:
    """Patton (2011) QLIKE, normalised so 0 == perfect. The dropped -log(actual) term
    is model-free and cancels in every DM differential."""
    r = actual / fc
    return r - np.log(r) - 1.0


def nw_var(d: np.ndarray, lag: int) -> float:
    """Newey-West long-run variance of the mean of d, Bartlett kernel."""
    n = len(d)
    dm = d - d.mean()
    g0 = float(dm @ dm) / n
    tot = g0
    for k in range(1, lag + 1):
        gk = float(dm[k:] @ dm[:-k]) / n
        tot += 2.0 * (1.0 - k / (lag + 1.0)) * gk
    return max(tot, 1e-300)


def dm_hln(loss_base: np.ndarray, loss_alt: np.ndarray, h: int) -> dict:
    """Diebold-Mariano with the Harvey-Leybourne-Newbold small-sample correction.

    d = loss_base - loss_alt, so a POSITIVE statistic means the alternative (DL) wins.
    HAC lag = h-1 for the overlap induced by direct h-step targets.
    """
    from scipy import stats

    d = np.asarray(loss_base, float) - np.asarray(loss_alt, float)
    n = len(d)
    lag = h - 1
    v = nw_var(d, lag) / n
    dm = float(d.mean() / math.sqrt(v))
    corr = math.sqrt(max((n + 1 - 2 * h + h * (h - 1) / n) / n, 1e-12))
    stat = dm * corr
    p = float(2.0 * (1.0 - stats.t.cdf(abs(stat), df=n - 1)))

    # h-1 is the textbook truncation for the overlap that direct h-step targets induce, but
    # the loss differential also inherits dependence from volatility clustering and from
    # holding parameters fixed between refits. A data-driven bandwidth is reported alongside
    # so the verdict is not an artefact of one lag choice; ACF(1) of d shows what remains.
    auto = int(max(lag, math.floor(4.0 * (n / 100.0) ** (2.0 / 9.0))))
    v_a = nw_var(d, auto) / n
    dm_a = float(d.mean() / math.sqrt(v_a))
    stat_a = dm_a * corr
    p_a = float(2.0 * (1.0 - stats.t.cdf(abs(stat_a), df=n - 1)))
    dc = d - d.mean()
    acf1 = float(dc[1:] @ dc[:-1] / (dc @ dc)) if n > 2 else float("nan")
    return {"dm_raw": dm, "dm_hln": stat, "p_value": p, "n": int(n),
            "hac_lag": lag, "hln_factor": corr, "mean_loss_diff": float(d.mean()),
            "dm_hln_auto_lag": stat_a, "p_value_auto_lag": p_a, "hac_lag_auto": auto,
            "loss_diff_acf1": acf1}


def bh_fdr(pvals: list[float], q: float = 0.05) -> tuple[list[float], list[bool]]:
    p = np.asarray(pvals, float)
    m = len(p)
    order = np.argsort(p)
    adj = np.empty(m)
    prev = 1.0
    for rank in range(m - 1, -1, -1):
        i = order[rank]
        prev = min(prev, p[i] * m / (rank + 1))
        adj[i] = min(prev, 1.0)
    return adj.tolist(), (adj <= q).tolist()


# --------------------------------------------------------------------------------------
# models
# --------------------------------------------------------------------------------------
class Fitted:
    """A predictor plus the training-residual variance used for the log->level step."""

    def __init__(self, predict, resid_var: float):
        self.predict = predict
        self.resid_var = float(resid_var)


def fit_ols(X: np.ndarray, y: np.ndarray, ridge: float = 0.0) -> Fitted:
    A = np.column_stack([np.ones(len(X)), X])
    if ridge > 0:
        p = A.shape[1]
        pen = ridge * np.eye(p)
        pen[0, 0] = 0.0
        beta = np.linalg.solve(A.T @ A + pen, A.T @ y)
    else:
        beta, *_ = np.linalg.lstsq(A, y, rcond=None)
    resid = y - A @ beta
    rv = float(resid.var(ddof=A.shape[1]))
    return Fitted(lambda Z, b=beta: np.column_stack([np.ones(len(Z)), Z]) @ b, rv)


class LSTMNet(nn.Module):
    def __init__(self, n_feat: int, hidden: int):
        super().__init__()
        self.lstm = nn.LSTM(n_feat, hidden, num_layers=1, batch_first=True)
        self.head = nn.Linear(hidden, 1)

    def forward(self, x):
        out, _ = self.lstm(x)
        return self.head(out[:, -1, :]).squeeze(-1)


class TinyTransformer(nn.Module):
    def __init__(self, n_feat: int, d_model: int, seq_len: int, nhead: int = 4):
        super().__init__()
        self.proj = nn.Linear(n_feat, d_model)
        self.pos = nn.Parameter(torch.zeros(1, seq_len, d_model))
        layer = nn.TransformerEncoderLayer(
            d_model=d_model, nhead=nhead, dim_feedforward=2 * d_model,
            dropout=0.1, batch_first=True, norm_first=True,
        )
        self.enc = nn.TransformerEncoder(layer, num_layers=1)
        self.head = nn.Linear(d_model, 1)

    def forward(self, x):
        z = self.enc(self.proj(x) + self.pos)
        return self.head(z.mean(dim=1)).squeeze(-1)


def _qlike_torch(y_log_true: torch.Tensor, y_log_pred: torch.Tensor) -> torch.Tensor:
    """QLIKE in log space: with r = a/f, log r = log a - log f."""
    lr = y_log_true - y_log_pred
    return (torch.exp(lr) - lr - 1.0).mean()


def fit_dl(kind: str, seq_tr: np.ndarray, y_tr: np.ndarray, seq_va: np.ndarray,
           y_va: np.ndarray, cfg: Config, seed: int) -> Fitted:
    """Train one DL model. Scalers come from the training slice only."""
    torch.manual_seed(seed)
    np.random.seed(seed)
    torch.use_deterministic_algorithms(False)

    mu = seq_tr.reshape(-1, seq_tr.shape[-1]).mean(0)
    sd = seq_tr.reshape(-1, seq_tr.shape[-1]).std(0) + 1e-8
    ymu, ysd = float(y_tr.mean()), float(y_tr.std() + 1e-8)

    Xtr = torch.tensor((seq_tr - mu) / sd, dtype=torch.float32)
    Xva = torch.tensor((seq_va - mu) / sd, dtype=torch.float32)
    ttr = torch.tensor((y_tr - ymu) / ysd, dtype=torch.float32)
    tva = torch.tensor((y_va - ymu) / ysd, dtype=torch.float32)
    raw_tr = torch.tensor(y_tr, dtype=torch.float32)
    raw_va = torch.tensor(y_va, dtype=torch.float32)

    n_feat = seq_tr.shape[-1]
    net = (LSTMNet(n_feat, cfg.hidden) if kind == "lstm"
           else TinyTransformer(n_feat, cfg.d_model, seq_tr.shape[1]))
    opt = torch.optim.Adam(net.parameters(), lr=cfg.lr)
    mse = nn.MSELoss()

    gen = torch.Generator().manual_seed(seed)
    n = len(Xtr)
    best, best_state, bad = math.inf, None, 0
    for _ in range(cfg.max_epochs):
        net.train()
        perm = torch.randperm(n, generator=gen)
        for s in range(0, n, cfg.batch_size):
            idx = perm[s: s + cfg.batch_size]
            opt.zero_grad()
            out = net(Xtr[idx])
            if cfg.loss == "qlike":
                loss = _qlike_torch(raw_tr[idx], out * ysd + ymu)
            else:
                loss = mse(out, ttr[idx])
            loss.backward()
            nn.utils.clip_grad_norm_(net.parameters(), 1.0)
            opt.step()
        net.eval()
        with torch.no_grad():
            pv = net(Xva)
            vl = float(_qlike_torch(raw_va, pv * ysd + ymu) if cfg.loss == "qlike"
                       else mse(pv, tva))
        if vl < best - 1e-7:
            best, bad = vl, 0
            best_state = {k: v.detach().clone() for k, v in net.state_dict().items()}
        else:
            bad += 1
            if bad >= cfg.patience:
                break
    if best_state is not None:
        net.load_state_dict(best_state)
    net.eval()

    def predict(seq: np.ndarray) -> np.ndarray:
        with torch.no_grad():
            z = torch.tensor((seq - mu) / sd, dtype=torch.float32)
            return (net(z).numpy() * ysd + ymu).astype(float)

    # resid_var feeds the lognormal exp(m + s2/2) level conversion, so it must estimate
    # FORECAST error variance. For OLS the dof-adjusted in-sample estimate is unbiased; for
    # a flexible early-stopped net an in-sample estimate is badly optimistic, which would
    # under-inflate the DL level forecast and -- because QLIKE punishes under-prediction
    # far harder than over-prediction -- silently handicap the DL arm. Use the held-out
    # validation residuals instead. `qlike_no_lognormal_correction` reports the variant
    # that drops this step entirely, so the conclusion never rests on it.
    resid = y_va - predict(seq_va)
    return Fitted(predict, float(resid.var()))


# --------------------------------------------------------------------------------------
# rolling OOS engine
# --------------------------------------------------------------------------------------
def origins(n_rows: int, oos_start: int, refit_every: int) -> list[int]:
    return list(range(oos_start, n_rows, refit_every))


HP_GRID = [(16, 1e-3), (32, 1e-3), (64, 1e-3), (16, 3e-3), (32, 3e-3), (64, 3e-3)]


def select_hyperparams(panel: Panel, h: int, cfg: Config, oos_start: int,
                       kinds: tuple[str, ...], grid: list | None = None) -> dict:
    """Choose DL capacity and learning rate ONCE, at the first origin, on that origin's
    chronological validation tail.

    This exists so the eventual verdict cannot be dismissed as "you under-powered the
    network". The selection set is strictly pre-OOS: it is the validation tail of the
    first training window, which ends h rows before the first forecast origin. No OOS
    observation, and no later origin, influences the choice.
    """
    T = oos_start
    tr_end = T - h
    tr_beg = max(0, tr_end - cfg.train_len)
    n_tr = tr_end - tr_beg
    n_va = max(50, int(cfg.val_frac * n_tr))
    fit_sl = slice(tr_beg, tr_end - n_va)
    val_sl = slice(tr_end - n_va, tr_end)
    y = panel.logy[h]
    chosen: dict = {}
    for kind in kinds:
        trials = []
        for hid, lr in (grid or HP_GRID):
            c = replace(cfg, hidden=hid, d_model=hid, lr=lr)
            f = fit_dl(kind, panel.seq[fit_sl], y[fit_sl], panel.seq[val_sl],
                       y[val_sl], c, BASE_SEED)
            pv = f.predict(panel.seq[val_sl])
            vq = float(qlike(panel.levy[h][val_sl], to_level(pv, f.resid_var, True)).mean())
            trials.append({"hidden": hid, "lr": lr, "val_qlike": vq})
        best = min(trials, key=lambda d: d["val_qlike"])
        chosen[kind] = {"hidden": best["hidden"], "lr": best["lr"],
                        "val_qlike": best["val_qlike"], "grid": trials,
                        "selection_window": (f"rows[{val_sl.start}:{val_sl.stop}] "
                                             f"({panel.dates[val_sl.start].date()}"
                                             f"..{panel.dates[val_sl.stop - 1].date()})")}
    return chosen


def rolling_forecasts(panel: Panel, h: int, cfg: Config, oos_start: int,
                       models: tuple[str, ...], hp: dict | None = None) -> dict:
    """Produce OOS log-forecasts for every requested model.

    Origin T: fit on rows [T-h-train_len, T-h] (the h-row embargo makes every training
    target observable at T), then forecast rows [T, T+refit_every).
    """
    n = len(panel.row_of)
    y = panel.logy[h]
    out: dict[str, np.ndarray] = {}
    # s2 is stored PER ROW, not averaged over origins. Averaging the per-origin residual
    # variances and applying the mean to every OOS day would let a 2020 refit's residual
    # variance set the level correction for a 1975 forecast -- straightforward OOS leakage.
    s2: dict[str, np.ndarray] = {}
    for m in models:
        reps = cfg.n_seeds if m in ("lstm", "transformer") else 1
        out[m] = np.full((reps, n), np.nan)
        s2[m] = np.full((reps, n), np.nan)

    origs = origins(n, oos_start, cfg.refit_every)
    for T in origs:
        # Direct-h-step embargo: training rows t must satisfy t + h <= T, because row t's
        # h-step target spans raw days row_of(t)+1 .. row_of(t)+h and must be fully observed
        # at the origin. Row T-h qualifies (its target ends exactly at raw day row_of(T),
        # which the origin has seen), so the exclusive slice end is T-h+1.
        tr_end = min(T - h + 1, T)
        tr_beg = max(0, tr_end - cfg.train_len)
        if tr_end - tr_beg < 300:
            continue
        n_tr = tr_end - tr_beg
        n_va = max(50, int(cfg.val_frac * n_tr))
        # DL splits the window because early stopping needs a holdout. The linear models
        # have nothing to tune, so they get the WHOLE window -- withholding the validation
        # tail from OLS would handicap the baseline by ~15% of its sample for no reason,
        # which is precisely the "weakened baseline" failure mode this experiment must avoid.
        lin_sl = slice(tr_beg, tr_end)
        # PURGE h-1 rows between fit and validation. Without it the last fit rows and the
        # first validation rows share up to h-1 of the same future daily RV observations,
        # so the early-stopping and hyperparameter decisions would be made on targets that
        # partly overlap the data the weights were fit on.
        purge = h - 1
        val_sl = slice(tr_end - n_va, tr_end)
        fit_sl = slice(tr_beg, max(tr_beg, tr_end - n_va - purge))
        if fit_sl.stop - fit_sl.start < 200:
            continue
        te = slice(T, min(n, T + cfg.refit_every))

        for m in models:
            if m == "har":
                f = fit_ols(panel.har_x[lin_sl], y[lin_sl])
                out[m][0, te] = f.predict(panel.har_x[te]); s2[m][0, te] = f.resid_var
            elif m == "harl":
                f = fit_ols(panel.harl_x[lin_sl], y[lin_sl])
                out[m][0, te] = f.predict(panel.harl_x[te]); s2[m][0, te] = f.resid_var
            elif m == "ar1":
                f = fit_ols(panel.har_x[lin_sl, :1], y[lin_sl])
                out[m][0, te] = f.predict(panel.har_x[te, :1]); s2[m][0, te] = f.resid_var
            elif m == "ridge_lags":
                Z = panel.lag_x[lin_sl]
                zmu, zsd = Z.mean(0), Z.std(0) + 1e-9
                f = fit_ols((Z - zmu) / zsd, y[lin_sl], ridge=10.0)
                out[m][0, te] = f.predict((panel.lag_x[te] - zmu) / zsd)
                s2[m][0, te] = f.resid_var
            elif m in ("lstm", "transformer"):
                mcfg = cfg
                if hp and m in hp:
                    mcfg = replace(cfg, hidden=hp[m]["hidden"], d_model=hp[m]["hidden"],
                                   lr=hp[m]["lr"])
                for k in range(cfg.n_seeds):
                    f = fit_dl(m, panel.seq[fit_sl], y[fit_sl], panel.seq[val_sl],
                               y[val_sl], mcfg, BASE_SEED + k)
                    out[m][k, te] = f.predict(panel.seq[te]); s2[m][k, te] = f.resid_var
            else:
                raise ValueError(m)

    return {"log_fc": out, "resid_var": s2, "origins": origs, "oos_start": oos_start}


def to_level(log_fc: np.ndarray, s2: np.ndarray | float, correct: bool) -> np.ndarray:
    """E[RV] = exp(m + s2/2) under lognormality, with s2 taken from the origin that
    produced each row. Applied identically to every model; `correct=False` is the naive
    exp(m), reported alongside so no conclusion rests on this step."""
    if not correct:
        return np.exp(log_fc)
    return np.exp(log_fc + 0.5 * np.asarray(s2))


def score(panel: Panel, h: int, res: dict, models: tuple[str, ...], correct: bool = True) -> dict:
    actual = panel.levy[h]
    ref = res["log_fc"][models[0]][0]
    mask = np.isfinite(ref)
    for m in models:
        mask &= np.isfinite(res["log_fc"][m]).all(axis=0)
    idx = np.where(mask)[0]

    per_model: dict[str, dict] = {}
    losses: dict[str, np.ndarray] = {}
    level_fc: dict[str, np.ndarray] = {}
    for m in models:
        reps = res["log_fc"][m].shape[0]
        seed_q, seed_loss, seed_level = [], [], []
        for k in range(reps):
            f = to_level(res["log_fc"][m][k, idx], res["resid_var"][m][k, idx], correct)
            L = qlike(actual[idx], f)
            seed_level.append(f)
            seed_loss.append(L)
            seed_q.append(float(L.mean()))
        # Ensemble in LEVEL space: each seed is converted to its own E[RV] first, then the
        # expectations are averaged. Averaging log-forecasts and exponentiating once is a
        # different (Jensen-smaller) quantity and is not the ensemble's expectation.
        ens_f = np.mean(np.stack(seed_level, axis=0), axis=0)
        Lens = qlike(actual[idx], ens_f)
        losses[m] = Lens
        level_fc[m] = ens_f
        per_model[m] = {
            "qlike_ensemble": float(Lens.mean()),
            "qlike_seed_mean": float(np.mean(seed_q)),
            "qlike_seed_sd": float(np.std(seed_q, ddof=1)) if reps > 1 else 0.0,
            "qlike_per_seed": [round(v, 6) for v in seed_q],
            "mse": float(np.mean((actual[idx] - ens_f) ** 2)),
            "mae": float(np.mean(np.abs(actual[idx] - ens_f))),
            "n_seeds": reps,
        }
        per_model[m]["_seed_losses"] = seed_loss
    return {"idx": idx, "per_model": per_model, "losses": losses, "level_fc": level_fc,
            "n_oos": int(len(idx)),
            "oos_start_date": str(panel.dates[idx[0]].date()),
            "oos_end_date": str(panel.dates[idx[-1]].date())}


# --------------------------------------------------------------------------------------
# descriptive statistics
# --------------------------------------------------------------------------------------
def gph_d(x: np.ndarray, expo: float = 0.5) -> float:
    """Geweke-Porter-Hudak log-periodogram estimate of the long-memory parameter d.

    Reported as a descriptive statistic only. A single-bandwidth GPH is known to be biased
    in the presence of short-memory contamination and structural breaks, so `describe`
    records several bandwidths rather than one number.
    """
    n = len(x)
    m = int(n**expo)
    xd = x - x.mean()
    I = np.abs(np.fft.rfft(xd)) ** 2 / (2 * math.pi * n)
    freqs = 2 * math.pi * np.arange(1, m + 1) / n
    reg = np.log(4 * np.sin(freqs / 2) ** 2)
    yv = np.log(I[1: m + 1])
    A = np.column_stack([np.ones(m), reg])
    beta, *_ = np.linalg.lstsq(A, yv, rcond=None)
    return float(-beta[1])


def hurst_rs(x: np.ndarray) -> float:
    """Rescaled-range Hurst exponent via log-log regression over dyadic block sizes."""
    x = np.asarray(x, float)
    sizes, rs = [], []
    n = len(x)
    k = 32
    while k <= n // 4:
        vals = []
        for s in range(0, n - k + 1, k):
            seg = x[s: s + k]
            z = np.cumsum(seg - seg.mean())
            sd = seg.std()
            if sd > 0:
                vals.append((z.max() - z.min()) / sd)
        if vals:
            sizes.append(k); rs.append(np.mean(vals))
        k *= 2
    A = np.column_stack([np.ones(len(sizes)), np.log(sizes)])
    beta, *_ = np.linalg.lstsq(A, np.log(rs), rcond=None)
    return float(beta[1])


def describe(rv: np.ndarray, dates: pd.DatetimeIndex) -> dict:
    lrv = np.log(rv)
    ann = np.sqrt(TRADING_DAYS * rv) * 100
    acf_lags = [1, 5, 10, 22, 44, 66, 132, 250]
    lc = lrv - lrv.mean()
    denom = float(lc @ lc)
    acf = {str(k): float(lc[k:] @ lc[:-k] / denom) for k in acf_lags}
    q = np.quantile(ann, [0.01, 0.25, 0.5, 0.75, 0.99])
    from scipy import stats as st

    return {
        "n": int(len(rv)),
        "date_start": str(dates[0].date()),
        "date_end": str(dates[-1].date()),
        "annualised_vol_pct": {"mean": float(ann.mean()), "sd": float(ann.std()),
                               "p1": float(q[0]), "p25": float(q[1]), "median": float(q[2]),
                               "p75": float(q[3]), "p99": float(q[4]),
                               "min": float(ann.min()), "max": float(ann.max())},
        "log_rv": {"mean": float(lrv.mean()), "sd": float(lrv.std()),
                   "skew": float(st.skew(lrv)), "kurtosis_excess": float(st.kurtosis(lrv))},
        "rv_level": {"skew": float(st.skew(rv)), "kurtosis_excess": float(st.kurtosis(rv))},
        "acf_log_rv": acf,
        "gph_d": gph_d(lrv),
        "gph_d_bandwidth_sensitivity": {f"n^{e}": gph_d(lrv, e) for e in (0.4, 0.5, 0.6)},
        "hurst_rs": hurst_rs(lrv),
        "long_memory_caveat": ("GPH and classical R/S are descriptive here, not inferential: "
                              "both are biased by short-memory contamination, heteroskedasticity "
                              "and structural breaks, and no confidence interval or break test "
                              "is computed. The slow ACF decay is the primary evidence; the point "
                              "estimates only summarise it."),
        "jarque_bera_log_rv_p": float(st.jarque_bera(lrv).pvalue),
    }


# --------------------------------------------------------------------------------------
# data-calibre gate: what does yfinance actually return intraday?
# --------------------------------------------------------------------------------------
def probe_intraday_limits() -> dict:
    import yfinance as yf

    cache = DATA_DIR / "intraday_probe.json"
    if cache.exists():
        return json.loads(cache.read_text())
    out = {}
    for tk in ("^GSPC", "SPY", "QQQ"):
        for interval, period in (("5m", "60d"), ("1h", "730d")):
            key = f"{tk}|{interval}|{period}"
            try:
                df = yf.download(tk, period=period, interval=interval, progress=False,
                                 auto_adjust=False)
                df = _flatten(df).dropna()
                out[key] = {
                    "n_bars": int(len(df)),
                    "start": str(df.index[0]), "end": str(df.index[-1]),
                    "n_trading_days": int(df.index.normalize().nunique()),
                    "bars_per_day": round(len(df) / max(1, df.index.normalize().nunique()), 2),
                }
            except Exception as e:  # network / rate limit
                out[key] = {"error": repr(e)[:200]}
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(out, indent=2))
    return out


def proxy_validation(ticker: str = "SPY") -> dict:
    """Measure how the range proxies track GENUINE intraday RV where both exist."""
    import yfinance as yf

    cache = DATA_DIR / f"proxy_validation_{ticker}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    daily = load_daily(ticker, "1993-01-29")
    prox = range_proxies(daily)
    res: dict = {"ticker": ticker}
    from scipy import stats as st

    for interval, period, label in (("5m", "60d", "rv_5min"), ("1h", "730d", "rv_1hour")):
        try:
            bars = _flatten(yf.download(ticker, period=period, interval=interval,
                                        progress=False, auto_adjust=False)).dropna()
            px = bars["Close"]
            day_all = px.index.tz_convert("America/New_York").normalize().tz_localize(None)
            # Difference WITHIN each trading day. A plain global .diff() makes the first bar
            # of each day an overnight (prev close -> today's open) return, so the "intraday"
            # RV would include the overnight gap while Parkinson's range does not -- two
            # different calibres silently compared.
            r = np.log(px).groupby(day_all).diff().dropna()
            day = r.index.tz_convert("America/New_York").normalize().tz_localize(None)
            rv_true = r.pow(2).groupby(day).sum()
            nbar = r.groupby(day).count()
            rv_true = rv_true[nbar >= max(4, int(0.6 * nbar.median()))]
            entry: dict = {"n_days": int(len(rv_true)),
                           "start": str(rv_true.index[0].date()),
                           "end": str(rv_true.index[-1].date()),
                           "bars_per_day_median": float(nbar.median())}
            for pname, pv in prox.items():
                s = pd.Series(pv, index=daily.index).reindex(rv_true.index).dropna()
                both = pd.concat([rv_true.rename("t"), s.rename("p")], axis=1).dropna()
                both = both[(both > 0).all(axis=1)]
                lt, lp = np.log(both["t"].to_numpy()), np.log(both["p"].to_numpy())
                A = np.column_stack([np.ones(len(lp)), lp])
                beta, *_ = np.linalg.lstsq(A, lt, rcond=None)
                entry[pname] = {
                    "n": int(len(both)),
                    "pearson_log": float(np.corrcoef(lt, lp)[0, 1]),
                    "spearman_level": float(st.spearmanr(both["t"], both["p"]).statistic),
                    "mean_ratio_proxy_over_true": float((both["p"] / both["t"]).mean()),
                    "median_ratio_proxy_over_true": float((both["p"] / both["t"]).median()),
                    "ols_slope_logtrue_on_logproxy": float(beta[1]),
                }
            res[label] = entry
        except Exception as e:
            res[label] = {"error": repr(e)[:200]}
    cache.write_text(json.dumps(res, indent=2))
    return res


# --------------------------------------------------------------------------------------
# one full arm (asset x estimator)
# --------------------------------------------------------------------------------------
PRIMARY_MODELS = ("har", "harl", "ar1", "ridge_lags", "lstm", "transformer")


def run_arm(ticker: str, start: str, estimator: str, cfg: Config,
            models: tuple[str, ...] = PRIMARY_MODELS,
            oos_start_date: str | None = None, do_selftest: bool = False,
            label: str = "", select_hp: bool = True,
            hp_grid: list | None = None) -> dict:
    daily = load_daily(ticker, start)
    prox = range_proxies(daily)
    rv_raw = prox[estimator]
    rv, n_floored = floor_positive(rv_raw)
    ret = np.concatenate([[0.0], np.diff(np.log(daily["Close"].to_numpy(float)))])
    dates = daily.index

    if cfg.pilot:
        rv, ret, dates = rv[-2600:], ret[-2600:], dates[-2600:]

    panel = build_panel(rv, ret, cfg.seq_len, dates, channels=cfg.channels)
    arm: dict = {
        "label": label or f"{ticker}_{estimator}",
        "ticker": ticker, "estimator": estimator,
        "data": {"n_daily_bars": int(len(rv)), "start": str(dates[0].date()),
                 "end": str(dates[-1].date()), "n_floored_nonpositive": n_floored,
                 "n_panel_rows": int(len(panel.row_of))},
        "config": {k: v for k, v in cfg.__dict__.items()},
        "horizons": {},
    }
    if do_selftest:
        arm["lookahead_selftests"] = lookahead_selftests(
            rv, ret, cfg.seq_len, dates, np.random.default_rng(BASE_SEED))
        arm["descriptive"] = describe(rv, dates)

    n_rows = len(panel.row_of)
    if oos_start_date is not None:
        oos_start = int(np.searchsorted(panel.dates, pd.Timestamp(oos_start_date)))
    else:
        oos_start = cfg.train_len + max(HORIZONS) + 10
    oos_start = max(oos_start, cfg.train_len + max(HORIZONS) + 10)
    if oos_start >= n_rows - 60:
        oos_start = max(400, n_rows - max(300, cfg.refit_every))

    dl_kinds = tuple(m for m in models if m in ("lstm", "transformer"))
    arm["hyperparameter_selection"] = {}
    for h in HORIZONS:
        hp = None
        if dl_kinds and select_hp:
            hp = select_hyperparams(panel, h, cfg, oos_start, dl_kinds, grid=hp_grid)
            arm["hyperparameter_selection"][str(h)] = hp
            print(f"    [{arm['label']}] h={h} HP chosen: "
                  + ", ".join(f"{k}=hidden{v['hidden']}/lr{v['lr']}" for k, v in hp.items()),
                  flush=True)
        res = rolling_forecasts(panel, h, cfg, oos_start, models, hp=hp)
        sc = score(panel, h, res, models, correct=True)
        sc_naive = score(panel, h, res, models, correct=False)

        entry: dict = {
            "n_oos": sc["n_oos"], "oos_start": sc["oos_start_date"], "oos_end": sc["oos_end_date"],
            "n_refits": len(res["origins"]),
            "effective_independent_obs": round(sc["n_oos"] / h, 1),
            "models": {m: {k: v for k, v in sc["per_model"][m].items() if not k.startswith("_")}
                       for m in models},
            "qlike_no_lognormal_correction": {
                m: sc_naive["per_model"][m]["qlike_ensemble"] for m in models},
            "dm_vs_har": {},
        }
        for bname, key in (("har", "dm_vs_har"), ("harl", "dm_vs_harl")):
            if bname not in models:
                continue
            entry.setdefault(key, {})
            base = sc["losses"][bname]
            for m in models:
                if m == bname:
                    continue
                t = dm_hln(base, sc["losses"][m], h)
                if m in ("lstm", "transformer"):
                    per = [dm_hln(base, L, h) for L in sc["per_model"][m]["_seed_losses"]]
                    t["per_seed_dm_hln"] = [round(x["dm_hln"], 4) for x in per]
                    t["per_seed_p"] = [round(x["p_value"], 5) for x in per]
                    t["n_seeds_favouring_alt"] = int(sum(x["dm_hln"] > 0 for x in per))
                entry[key][m] = t
        # regime split on realised vol terciles of the OOS actuals
        a = panel.levy[h][sc["idx"]]
        cut = np.quantile(a, [1 / 3, 2 / 3])
        entry["qlike_by_vol_tercile"] = {}
        for nm, sel in (("low", a <= cut[0]), ("mid", (a > cut[0]) & (a <= cut[1])),
                        ("high", a > cut[1])):
            entry["qlike_by_vol_tercile"][nm] = {
                "n": int(sel.sum()),
                **{m: float(sc["losses"][m][sel].mean()) for m in models}}
        arm["horizons"][str(h)] = entry
        arm["horizons"][str(h)]["_losses"] = {m: sc["losses"][m] for m in models}
        arm["horizons"][str(h)]["_fc"] = sc["level_fc"]
        arm["horizons"][str(h)]["_idx"] = sc["idx"]
        arm["horizons"][str(h)]["_actual"] = panel.levy[h][sc["idx"]]
        arm["horizons"][str(h)]["_dates"] = panel.dates[sc["idx"]]
        g = lambda m: sc["per_model"].get(m, {}).get("qlike_ensemble", float("nan"))
        print(f"    [{arm['label']}] h={h:>2} n_oos={sc['n_oos']:>5} "
              f"HAR={g('har'):.4f} HARL={g('harl'):.4f} AR1={g('ar1'):.4f} "
              f"RIDGE={g('ridge_lags'):.4f} LSTM={g('lstm'):.4f} TRF={g('transformer'):.4f}",
              flush=True)
    return arm


def strip_private(obj):
    if isinstance(obj, dict):
        return {k: strip_private(v) for k, v in obj.items() if not k.startswith("_")}
    if isinstance(obj, list):
        return [strip_private(v) for v in obj]
    return obj


# --------------------------------------------------------------------------------------
# figures
# --------------------------------------------------------------------------------------
def figures(primary: dict, rv: np.ndarray, dates: pd.DatetimeIndex, pv: dict) -> list[str]:
    made = []

    # 1. long memory
    lrv = np.log(rv)
    lc = lrv - lrv.mean()
    denom = float(lc @ lc)
    lags = np.arange(1, 251)
    acf = np.array([lc[k:] @ lc[:-k] / denom for k in lags])
    fig, ax = plt.subplots(1, 2, figsize=(11, 4))
    ax[0].plot(lags, acf, lw=1.2, color="#2b6cb0")
    ax[0].axhline(0, color="0.6", lw=0.8)
    ax[0].axhline(1.96 / math.sqrt(len(lrv)), color="crimson", ls="--", lw=0.8, label="95% white-noise band")
    ax[0].set_xlabel("lag (trading days)"); ax[0].set_ylabel("ACF of log RV-proxy")
    ax[0].set_title("ACF of log RV-proxy: slow decay\n"
                    f"GPH d={primary['descriptive']['gph_d']:.3f}, "
                    f"R/S H={primary['descriptive']['hurst_rs']:.3f} (descriptive only)")
    ax[0].legend(fontsize=8)
    ann = np.sqrt(TRADING_DAYS * rv) * 100
    ax[1].plot(dates, pd.Series(ann, index=dates).rolling(22).mean(), lw=0.7, color="#2d3748")
    ax[1].set_yscale("log"); ax[1].set_ylabel("annualised vol %, 22d MA")
    ax[1].set_title(f"{primary['ticker']} Parkinson proxy, {primary['data']['start']}–{primary['data']['end']}")
    fig.tight_layout(); p = EXP_DIR / "fig1_longmemory_regimes.png"
    fig.savefig(p, dpi=140); plt.close(fig); made.append(p.name)

    # 2. QLIKE by horizon with seed error bars
    fig, ax = plt.subplots(figsize=(7.4, 4.4))
    hs = [1, 5, 22]
    xs = np.arange(len(hs))
    cols = {"har": "#1a202c", "harl": "#4a5568", "ridge_lags": "#a0aec0",
            "lstm": "#dd6b20", "transformer": "#3182ce"}
    for i, m in enumerate(["har", "harl", "ridge_lags", "lstm", "transformer"]):
        vals = [primary["horizons"][str(h)]["models"][m]["qlike_ensemble"] for h in hs]
        errs = [primary["horizons"][str(h)]["models"][m]["qlike_seed_sd"] for h in hs]
        ax.errorbar(xs + (i - 2) * 0.13, vals, yerr=errs, marker="o", ms=5, lw=1.4,
                    capsize=3, label=m.upper(), color=cols[m])
    ax.set_xticks(xs); ax.set_xticklabels([f"h={h}" for h in hs])
    ax.set_ylabel("OOS QLIKE (lower = better)")
    ax.set_title("H2 test: does the DL gap close at longer horizons?\n"
                 "error bars = sd across 5 seeds")
    ax.legend(fontsize=8); ax.grid(alpha=0.25)
    fig.tight_layout(); p = EXP_DIR / "fig2_qlike_by_horizon.png"
    fig.savefig(p, dpi=140); plt.close(fig); made.append(p.name)

    # 3. DM statistics
    fig, ax = plt.subplots(figsize=(7.4, 4.2))
    width = 0.35
    for i, m in enumerate(["lstm", "transformer"]):
        vals = [primary["horizons"][str(h)]["dm_vs_har"][m]["dm_hln"] for h in hs]
        ax.bar(xs + (i - 0.5) * width, vals, width, label=m.upper(),
               color=cols[m], edgecolor="white")
    ax.axhline(0, color="0.3", lw=1)
    ax.axhline(1.96, color="crimson", ls="--", lw=1, label="±1.96 (DL better above)")
    ax.axhline(-1.96, color="crimson", ls="--", lw=1)
    ax.set_xticks(xs); ax.set_xticklabels([f"h={h}" for h in hs])
    ax.set_ylabel("DM-HLN statistic vs HAR\n(>0 favours DL)")
    ax.set_title("Diebold-Mariano, Harvey-Leybourne-Newbold corrected")
    ax.legend(fontsize=8); ax.grid(alpha=0.25, axis="y")
    fig.tight_layout(); p = EXP_DIR / "fig3_dm_statistics.png"
    fig.savefig(p, dpi=140); plt.close(fig); made.append(p.name)

    # 4. forecast vs actual
    fig, axes = plt.subplots(2, 1, figsize=(11, 6), sharex=False)
    for ax_, h in zip(axes, (1, 22)):
        e = primary["horizons"][str(h)]
        d, a = e["_dates"], e["_actual"]
        sl = slice(max(0, len(d) - 1500), len(d))
        ax_.plot(d[sl], np.sqrt(TRADING_DAYS * a[sl]) * 100, lw=1.0, color="0.3",
                 label="realised", zorder=3)
        for m, c in (("har", "#dd6b20"), ("lstm", "#3182ce")):
            f = e["_fc"][m][sl]
            ax_.plot(d[sl], np.sqrt(TRADING_DAYS * f) * 100, lw=0.9, color=c,
                     alpha=0.85, label=m.upper())
        ax_.set_ylabel(f"h={h} annualised vol %")
        ax_.set_title(f"h={h}: realised vs forecast (last {min(1500,len(d))} OOS days)")
        ax_.legend(fontsize=8)
    fig.tight_layout(); p = EXP_DIR / "fig4_forecast_vs_actual.png"
    fig.savefig(p, dpi=140); plt.close(fig); made.append(p.name)

    # 5. proxy validation
    if "rv_5min" in pv and "parkinson" in pv.get("rv_5min", {}):
        fig, ax = plt.subplots(1, 2, figsize=(10, 4))
        for j, lab in enumerate(["rv_5min", "rv_1hour"]):
            if lab not in pv or "parkinson" not in pv[lab]:
                continue
            names = ["parkinson", "garman_klass", "rogers_satchell"]
            r = [pv[lab][n]["pearson_log"] for n in names]
            ratio = [pv[lab][n]["median_ratio_proxy_over_true"] for n in names]
            xx = np.arange(3)
            ax[j].bar(xx - 0.2, r, 0.4, label="Pearson corr (logs)", color="#3182ce")
            ax[j].bar(xx + 0.2, ratio, 0.4, label="median proxy/true", color="#dd6b20")
            ax[j].axhline(1.0, color="0.5", ls=":", lw=1)
            ax[j].set_xticks(xx); ax[j].set_xticklabels(["Park", "GK", "RS"])
            ax[j].set_title(f"vs {lab}  (n={pv[lab]['n_days']} days)")
            ax[j].legend(fontsize=7)
        fig.suptitle("Range proxy vs genuine intraday RV (SPY, overlapping window)")
        fig.tight_layout(); p = EXP_DIR / "fig5_proxy_validation.png"
        fig.savefig(p, dpi=140); plt.close(fig); made.append(p.name)
    return made


# --------------------------------------------------------------------------------------
def build_verdict(primary: dict) -> tuple[dict, int | None]:
    """Per-horizon accept/reject against BOTH the pre-registered baseline (HAR-RV) and
    the strong baseline (HAR-RV + leverage)."""
    verdict: dict = {}
    for h in HORIZONS:
        e = primary["horizons"][str(h)]
        best_dl = min(("lstm", "transformer"), key=lambda m: e["models"][m]["qlike_ensemble"])
        d = e["dm_vs_har"][best_dl]
        ds = e["dm_vs_harl"][best_dl]
        win = d["dm_hln"] > 0 and d["significant_after_fdr_q05"]
        win_strong = ds["dm_hln"] > 0 and ds["significant_after_fdr_q05"]
        verdict[f"h{h}"] = {
            "best_dl_model": best_dl,
            "qlike_har": e["models"]["har"]["qlike_ensemble"],
            "qlike_harl_strong_baseline": e["models"]["harl"]["qlike_ensemble"],
            "qlike_ridge_lags_linear_control": e["models"]["ridge_lags"]["qlike_ensemble"],
            "qlike_best_dl": e["models"][best_dl]["qlike_ensemble"],
            "qlike_diff_har_minus_dl": e["models"]["har"]["qlike_ensemble"]
            - e["models"][best_dl]["qlike_ensemble"],
            "qlike_diff_harl_minus_dl": e["models"]["harl"]["qlike_ensemble"]
            - e["models"][best_dl]["qlike_ensemble"],
            "dl_seed_sd": e["models"][best_dl]["qlike_seed_sd"],
            "dl_qlike_per_seed": e["models"][best_dl]["qlike_per_seed"],
            "dm_hln_vs_har": d["dm_hln"], "p_raw_vs_har": d["p_value"],
            "p_bh_fdr_vs_har": d["p_value_bh_fdr"],
            "dm_hln_vs_harl": ds["dm_hln"], "p_raw_vs_harl": ds["p_value"],
            "p_bh_fdr_vs_harl": ds["p_value_bh_fdr"],
            "n_oos": e["n_oos"], "effective_independent_obs": e["effective_independent_obs"],
            "decision_vs_har": "REJECT_H0_DL_BETTER" if win else (
                "REJECT_H0_HAR_BETTER" if d["significant_after_fdr_q05"] else "FAIL_TO_REJECT"),
            "decision_vs_harl_strong": "DL_BETTER" if win_strong else (
                "HARL_BETTER" if ds["significant_after_fdr_q05"] else "FAIL_TO_REJECT"),
            "dl_beats_both_baselines": bool(win and win_strong),
        }
    # h* is a BOUNDARY claim ("DL wins from h* onward"), so it requires the horizon itself
    # AND every longer tested horizon to win. Taking the first significant horizon would
    # let {h=5 wins, h=22 loses} be reported as "DL wins from 5 onward", which is false.
    h_star = None
    for i, h in enumerate(HORIZONS):
        if all(verdict[f"h{hh}"]["dl_beats_both_baselines"] for hh in HORIZONS[i:]):
            h_star = h
            break
    any_win = [h for h in HORIZONS if verdict[f"h{h}"]["dl_beats_both_baselines"]]
    return verdict, h_star, any_win


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", action="store_true")
    ap.add_argument("--skip-ablations", action="store_true")
    ap.add_argument("--skip-robustness", action="store_true")
    args = ap.parse_args()

    cfg = Config(pilot=args.pilot)
    if args.pilot:
        cfg.n_seeds, cfg.refit_every, cfg.train_len = 2, 900, 1200
        cfg.max_epochs, cfg.patience = 25, 5

    np.random.seed(BASE_SEED)
    torch.manual_seed(BASE_SEED)

    from volpred.research.reproduce_spec import finalize_experiment

    out: dict = {}
    stages: list[str] = []

    def checkpoint(stage: str, unresolved: list[str]) -> None:
        """Write the canonical artifact after every stage.

        This runs headless under a compute worker: if the process is cut mid-run, a
        partial artifact that is explicit about what is missing is collectable, whereas
        a missing artifact is a failed job. So the results file is rewritten at each
        stage boundary rather than once at the end.
        """
        stages.append(stage)
        out["stages_completed"] = list(stages)
        out["unresolved"] = unresolved
        # absolute: trace_file() resolves relative paths against the CWD, so a
        # repo-relative string here would break when the script is run from elsewhere
        inputs = sorted(str(p.resolve()) for p in DATA_DIR.glob("*") if p.is_file())
        finalize_experiment(
            results=out, entrypoint=__file__, canonical_result="K1814_results.json",
            inputs=inputs, outputs=out.get("figures", []),
            seeds=[("numpy", BASE_SEED), ("torch", BASE_SEED),
                   ("dl_seed_grid", f"{BASE_SEED}..{BASE_SEED + cfg.n_seeds - 1}")],
            started_at=T0,
        )
        print(f"    [checkpoint] wrote K1814_results.json after '{stage}' "
              f"({time.time() - T0:.0f}s elapsed)", flush=True)

    print("[1/6] data-calibre gate: probing yfinance intraday limits", flush=True)
    probe = probe_intraday_limits()
    for k, v in probe.items():
        print("   ", k, v, flush=True)

    print("[2/6] proxy validation vs genuine intraday RV", flush=True)
    pv = proxy_validation("SPY")

    print("[3/6] primary arm: ^GSPC Parkinson (this is the long stage)", flush=True)
    primary = run_arm("^GSPC", "1962-01-01", "parkinson", cfg, do_selftest=True,
                      label="GSPC_parkinson_primary")

    # BH-FDR within each baseline family separately: 3 horizons x 2 DL models.
    # `dm_vs_har` is the pre-registered primary family. `dm_vs_harl` is the strong-baseline
    # family, present because HAR-RV carries no return channel at all -- any DL edge that a
    # linear leverage term also captures must not be credited to deep learning.
    fam = [(h, m) for h in HORIZONS for m in ("lstm", "transformer")]
    fdr_families: dict = {}
    for key, bname in (("dm_vs_har", "HAR-RV"), ("dm_vs_harl", "HAR-RV+leverage")):
        praw = [primary["horizons"][str(h)][key][m]["p_value"] for h, m in fam]
        padj, rej = bh_fdr(praw, q=0.05)
        block = {}
        for (h, m), pr, pa, rj in zip(fam, praw, padj, rej):
            d = primary["horizons"][str(h)][key][m]
            d["p_value_bh_fdr"] = pa
            d["significant_after_fdr_q05"] = bool(rj)
            d["direction"] = "DL_better" if d["dm_hln"] > 0 else "baseline_better"
            block[f"h{h}_{m}"] = {"p_raw": pr, "p_bh": pa, "reject_at_q05": bool(rj),
                                  "dm_hln": d["dm_hln"], "direction": d["direction"]}
        fdr_families[key] = {"baseline": bname, "family_size": len(fam), "q": 0.05,
                             "results": block}

    print("[4/6] figures", flush=True)
    daily = load_daily("^GSPC", "1962-01-01")
    rv, _ = floor_positive(range_proxies(daily)["parkinson"])
    dts = daily.index
    if cfg.pilot:
        rv, dts = rv[-2600:], dts[-2600:]
    figs = figures(primary, rv, dts, pv)

    verdict, h_star, any_win = build_verdict(primary)

    out.update({
        "experiment_id": "K1814",
        "title": ("Deep learning vs HAR on a daily realized-range proxy: locating the "
                  "horizon at which a DL increment appears"),
        "question": ("Is there h* in {1,5,22} beyond which LSTM / small Transformer "
                     "significantly beat HAR-RV on QLIKE?"),
        "prior_context": ("K1310-K1330 ran four ML novel-method experiments and returned "
                          "NULL at h=1. This experiment tests the open question those NULLs "
                          "left: whether the DL increment appears at longer horizons. A NULL "
                          "here is a substantive answer, not a failure."),
        "data_calibre_gate": {
            "route_taken": "B_realized_range_proxy",
            "why": ("Route A (5-min RV) is arithmetically impossible for a 22-day-horizon "
                    "rolling OOS: yfinance returns exactly 60 trading days of 5-minute bars "
                    "(4680 bars, 78/day), i.e. 60 daily RV observations. Route B uses daily "
                    "OHLC range proxies, which reach back decades."),
            "headline_caveat": ("EVERY forecast number in this artifact is for a DAILY "
                                "REALIZED-RANGE PROXY (Parkinson), NOT 5-minute realized "
                                "variance. The two calibres are never mixed."),
            "measured_intraday_limits": probe,
            "estimator_choice": {
                "primary": "parkinson",
                "reason": ("Measured: ^GSPC Open equals the prior Close on 59% of days "
                           "overall and 97% in the 1960s, so Garman-Klass and "
                           "Rogers-Satchell -- both of which use Open -- degenerate on the "
                           "long sample. Parkinson needs only High/Low. GK and RS are run on "
                           "SPY/QQQ, which have genuine Opens (open==prevClose on 1.9%/1.2% "
                           "of days), as an estimator-robustness arm."),
            },
            "known_proxy_bias_direction": (
                "Range estimators measure INTRADAY variation only, so they omit the "
                "overnight gap and understate close-to-close variance; discrete sampling of "
                "the High/Low also biases the observed range downward. Both push the proxy "
                "below true total variation. `proxy_vs_true_rv` measures the realised "
                "magnitude against genuine 5-min and 1-hour RV on the overlapping windows."),
            "proxy_vs_true_rv": pv,
        },
        "lookahead_policy": {
            "feature_information_set": "row t uses rv/return with index <= t only",
            "target_information_set": "row t uses rv with index in [t+1, t+h] only",
            "direct_h_step_embargo": ("a model forecasting from origin T is fit only on rows "
                                      "t with t+h <= T, since row t's h-step target is not "
                                      "observable at T otherwise; identical for HAR and DL"),
            "scaler_policy": ("X and y scalers fit on the training slice only and refit at "
                              "every origin; no full-sample standardisation anywhere"),
            "fit_validation_purge": ("h-1 rows are purged between the fit slice and the "
                                     "validation slice, so early stopping and hyperparameter "
                                     "selection never score on targets that overlap the "
                                     "fitted rows' targets"),
            "level_correction_policy": ("the lognormal correction uses the residual variance "
                                        "of the ORIGIN that produced each row, stored per "
                                        "row; averaging it across origins would apply a "
                                        "future refit's residual variance to an early "
                                        "forecast"),
            "nonpositive_rv_policy": (f"fixed pre-specified floor RV_FLOOR={RV_FLOOR} (0.5% "
                                      "annualised), never a sample quantile -- a full-sample "
                                      "quantile would let later data set the floor applied "
                                      "to earlier observations"),
            "dl_information_set": ("PRIMARY DL arm consumes log RV only (channels=1), which "
                                   "is exactly HAR-RV's information set: HAR's d/w/m terms "
                                   "are three linear aggregates of the same 22 lags. A DL win "
                                   "here cannot be an information advantage. The return "
                                   "channel is a separate ablation judged against HAR-L."),
            "hyperparameter_policy": ("DL capacity and learning rate selected ONCE on the "
                                      "chronological validation tail of the FIRST training "
                                      "window (strictly pre-OOS), then held fixed; early "
                                      "stopping uses each origin's own validation tail; no "
                                      "OOS quantity touches model selection"),
            "baseline_fairness": ("linear models are fit on the FULL training window because "
                                  "they have nothing to early-stop; withholding the "
                                  "validation tail from OLS would handicap the baseline"),
            "mechanical_proof": ("lookahead_selftests: 40 probe rows, perturbation test in "
                                 "both directions, exact equality required (atol=0)"),
        },
        "primary": primary,
        "fdr_family": {"family": [f"h{h}_{m}" for h, m in fam], "q": 0.05,
                       "results": fdr_families["dm_vs_har"]["results"]},
        "fdr_families": fdr_families,
        "figures": figs,
        "verdict": {
            "per_horizon": verdict,
            "h_star": h_star,
            "horizons_with_dl_win": any_win,
            "h_star_definition": ("smallest h such that h AND every longer tested horizon "
                                  "show a DL win surviving BH-FDR against BOTH HAR-RV and "
                                  "HAR-RV+leverage"),
            "h_star_interpretation": (
                f"DL significantly beats both baselines from h={h_star} onward"
                if h_star is not None else
                ("No horizon boundary exists: no h in {1,5,22} has DL winning at that "
                 "horizon and every longer one, against both baselines."
                 + (f" Isolated (non-monotone) wins at h={any_win}." if any_win else ""))),
            "H1_short_horizon": verdict["h1"]["decision_vs_har"],
            "H2_boundary_exists": h_star is not None,
        },
        "robustness": {},
        "ablations": {},
    })
    checkpoint("primary", ["robustness arms not yet run", "ablations not yet run"])
    out["primary"] = strip_private(out["primary"])

    if not args.skip_robustness:
        print("[5/6] robustness: cross-asset and cross-estimator", flush=True)
        # Reduced settings vs the primary arm, stated explicitly rather than silently:
        # 3 seeds (not 5), refit_every=1500 (not 750), and a 2-point HP grid.
        rgrid = [(32, 1e-3), (64, 1e-3)]
        rcfg = Config(pilot=args.pilot, n_seeds=3, refit_every=1500,
                      train_len=cfg.train_len, max_epochs=cfg.max_epochs,
                      patience=cfg.patience)
        if args.pilot:
            rcfg.n_seeds, rcfg.refit_every, rcfg.train_len = 2, 900, 1200
            rcfg.max_epochs, rcfg.patience = 25, 5
        out["robustness"]["_settings_note"] = (
            f"reduced vs primary: n_seeds={rcfg.n_seeds}, refit_every={rcfg.refit_every}, "
            f"hp_grid={rgrid}")
        for tk, st, est, lab in (("SPY", "1993-01-29", "parkinson", "SPY_parkinson"),
                                 ("SPY", "1993-01-29", "garman_klass", "SPY_garman_klass"),
                                 ("QQQ", "1999-03-10", "parkinson", "QQQ_parkinson")):
            try:
                out["robustness"][lab] = strip_private(
                    run_arm(tk, st, est, rcfg, label=lab, hp_grid=rgrid))
            except Exception as e:
                out["robustness"][lab] = {"error": repr(e)[:300]}
            checkpoint(f"robustness:{lab}", ["ablations not yet run"])

    if not args.skip_ablations:
        print("[6/6] ablations", flush=True)
        # `channels_with_returns` is the mechanism ablation: the primary DL arm is
        # information-matched to HAR-RV (log RV only), so this arm is what isolates how much
        # of any DL edge is simply the return/leverage channel. Judge it against HAR-L, which
        # also has return information -- not against HAR-RV, which has none.
        # `refit_250` answers whether the verdict is an artefact of the sparse refit cadence.
        specs = {
            "channels_with_returns": (dict(channels=2), None),
            "refit_250": (dict(refit_every=250, n_seeds=1), ("har", "harl", "lstm")),
            "window_L66": (dict(seq_len=66), None),
            "train_len1500": (dict(train_len=1500), None),
            "loss_qlike_direct": (dict(loss="qlike"), None),
        }
        out["ablations"]["_settings_note"] = (
            "Reduced vs the primary arm, stated rather than silently applied: n_seeds=2 "
            "(refit_250 uses 1 seed and drops the Transformer, because 52 refits x 3 "
            "horizons x 2 models x 2 seeds did not fit the compute budget), "
            "refit_every=3000, select_hp=False (an ablation that re-selected capacity would "
            "not be an ablation of capacity; capacity is instead chosen on validation in the "
            "primary arm). Compare each ablation against ITS OWN har/harl columns, never the "
            "primary arm's: the OOS row set changes when seq_len or train_len changes.")
        for name, (over, mdls) in specs.items():
            acfg = Config(pilot=args.pilot, n_seeds=2, refit_every=3000,
                          train_len=cfg.train_len, max_epochs=cfg.max_epochs,
                          patience=cfg.patience, seq_len=cfg.seq_len)
            if args.pilot:
                acfg.n_seeds, acfg.refit_every, acfg.train_len = 2, 900, 1200
                acfg.max_epochs, acfg.patience = 25, 5
            for k, v in over.items():
                setattr(acfg, k, v)
            try:
                arm = run_arm("^GSPC", "1962-01-01", "parkinson", acfg,
                              models=mdls or ("har", "harl", "lstm", "transformer"),
                              label=f"ablation_{name}", select_hp=False)
                out["ablations"][name] = strip_private(arm)
            except Exception as e:
                out["ablations"][name] = {"error": repr(e)[:300]}
            checkpoint(f"ablation:{name}", [])

    checkpoint("complete", [])
    print(f"\ndone in {time.time() - T0:.1f}s  h*={h_star}", flush=True)
    for h in HORIZONS:
        v = verdict[f"h{h}"]
        print(f"  h={h:>2}: HAR={v['qlike_har']:.4f} HARL={v['qlike_harl_strong_baseline']:.4f} "
              f"DL({v['best_dl_model']})={v['qlike_best_dl']:.4f}+-{v['dl_seed_sd']:.4f}  "
              f"DM/HAR={v['dm_hln_vs_har']:+.2f} (q={v['p_bh_fdr_vs_har']:.4f})  "
              f"DM/HARL={v['dm_hln_vs_harl']:+.2f} (q={v['p_bh_fdr_vs_harl']:.4f})  "
              f"-> {v['decision_vs_har']}", flush=True)


if __name__ == "__main__":
    main()
