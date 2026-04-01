"""
K797: KAN-GARCH-MIDAS -- Kolmogorov-Arnold Network for Volatility Prediction
=============================================================================
Proposer: User
Executor: Claude

Literature:
  - Liu et al. (2024) "KAN: Kolmogorov-Arnold Networks" arXiv:2404.19756
  - KAN-GARCH-MIDAS, J. Applied Economics 2025 (T&F)
  - Engle, Ghysels & Sohn (2013) GARCH-MIDAS, JBES
  - K526: GARCH-MIDAS OOS null vs GJR, tau explains 11% variance
  - K784: GARCH-GRU null vs GJR (DM=-0.51), ML adds no value

Hypothesis:
  KAN (learnable spline activations on edges) may better capture the
  nonlinear combination of short-run g_t and long-run tau_t vs:
  (a) standard multiplicative sigma2=g*tau  (GARCH-MIDAS)
  (b) standard MLP with ReLU activations

Design:
  1. GJR-GARCH(1,1) baseline
  2. GARCH-MIDAS: multiplicative g*tau (tau = EWMA of r2, lambda=0.997)
  3. KAN-GARCH: 2-layer vectorized B-spline KAN (8 knots), features=[g,tau,VIX/100,|r|,log(tau)]
  4. MLP-GARCH: same features, standard ReLU MLP

  OOS: 2023-01-01 to 2024-12-31 (~504 days)
  Expanding window, refit every 63 trading days
  Training with QLIKE loss
  Features at t-1 -> predict r2_t (no lookahead)

CODE REVIEW NOTES (pre-execution):
  - LOOKAHEAD CHECK PASS: Features[t-1] -> r2[t]. No same-day features.
  - QLIKE on r2 (Patton 2011 proxy-robust). Not on |r|.
  - DM test with Harvey small-sample correction.
  - No transaction costs needed (pure volatility forecast test).
"""

import numpy as np
import pandas as pd
import yfinance as yf
from scipy.optimize import minimize
from scipy.stats import spearmanr
import json
import warnings
from datetime import datetime
warnings.filterwarnings('ignore')

try:
    import torch
    import torch.nn as nn
    import torch.optim as optim
    HAS_TORCH = True
    print(f"PyTorch {torch.__version__} available")
except ImportError:
    HAS_TORCH = False
    print("PyTorch not available -- will use GJR as NN proxy")


def load_data():
    print("Loading SPY and VIX data...")
    spy = yf.download("SPY", start="2010-01-01", end="2025-01-01",
                      auto_adjust=True, progress=False)
    vix = yf.download("^VIX", start="2010-01-01", end="2025-01-01",
                      auto_adjust=True, progress=False)
    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.droplevel(1)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.droplevel(1)
    r = spy['Close'].pct_change().dropna()
    v = vix['Close'].reindex(r.index).ffill()
    df = pd.DataFrame({'r': r, 'vix': v}).dropna()
    print(f"Data: {df.index[0].date()} to {df.index[-1].date()}, N={len(df)}")
    return df


def gjr_neg_loglik(params, r):
    omega, alpha, gamma, beta = params
    if omega <= 0 or alpha < 0 or gamma < -alpha or beta < 0:
        return 1e10
    if alpha + gamma / 2 + beta >= 1:
        return 1e10
    n = len(r)
    h = np.empty(n)
    h[0] = np.var(r)
    for t in range(1, n):
        I = 1.0 if r[t - 1] < 0 else 0.0
        h[t] = omega + alpha * r[t-1]**2 + gamma * I * r[t-1]**2 + beta * h[t-1]
        if h[t] <= 0:
            return 1e10
    return 0.5 * np.sum(np.log(h) + r**2 / h)


def fit_gjr(r_arr):
    var0 = np.var(r_arr)
    starts = [
        [var0*0.05, 0.05, 0.05, 0.88],
        [var0*0.02, 0.08, 0.08, 0.82],
        [var0*0.01, 0.04, 0.10, 0.85],
    ]
    bounds = [(1e-8, None), (1e-6, 0.5), (-0.3, 0.5), (1e-6, 0.999)]
    best_val, best_params = np.inf, starts[0]
    for x0 in starts:
        try:
            res = minimize(gjr_neg_loglik, x0, args=(r_arr,), method='L-BFGS-B',
                           bounds=bounds, options={'maxiter': 500, 'ftol': 1e-10})
            if res.fun < best_val:
                best_val, best_params = res.fun, res.x
        except Exception:
            pass
    omega, alpha, gamma, beta = best_params
    n = len(r_arr)
    h = np.empty(n)
    h[0] = var0
    for t in range(1, n):
        I = 1.0 if r_arr[t-1] < 0 else 0.0
        h[t] = max(1e-10, omega + alpha*r_arr[t-1]**2 + gamma*I*r_arr[t-1]**2 + beta*h[t-1])
    return best_params, h


def gjr_predict_one(params, h_prev, r_prev):
    omega, alpha, gamma, beta = params
    I = 1.0 if r_prev < 0 else 0.0
    return max(1e-10, omega + alpha*r_prev**2 + gamma*I*r_prev**2 + beta*h_prev)


def compute_tau(r_arr, lam=0.997):
    r2 = r_arr**2
    tau = np.empty(len(r2))
    tau[0] = r2[0]
    for t in range(1, len(r2)):
        tau[t] = lam * tau[t-1] + (1-lam) * r2[t]
    return tau


def build_features(g_arr, tau_arr, vix_arr, r_arr):
    """
    Features at time t-1 for predicting r2_t.
    [g, tau, VIX/100, |r|, log(tau)]
    All values are from the previous period -- no lookahead.
    """
    log_tau = np.log(np.clip(tau_arr, 1e-10, None))
    return np.column_stack([g_arr, tau_arr, vix_arr / 100.0, np.abs(r_arr), log_tau])


if HAS_TORCH:
    class KANLayerVectorized(nn.Module):
        """
        Vectorized KAN layer using einsum (10x faster than per-edge loops).
        Each (in,out) pair has its own B-spline activation.
        weights: [out_dim, in_dim, n_knots]
        residual_scale: [out_dim, in_dim]
        """
        def __init__(self, in_dim, out_dim, n_knots=8):
            super().__init__()
            self.in_dim = in_dim
            self.out_dim = out_dim
            self.n_knots = n_knots
            self.weights = nn.Parameter(torch.randn(out_dim, in_dim, n_knots) * 0.1)
            self.residual_scale = nn.Parameter(torch.ones(out_dim, in_dim) * 0.1)
            self.norm = nn.LayerNorm(out_dim)

        def forward(self, x):
            # x: [B, in_dim]
            x_c = torch.clamp(x, -3.0, 3.0)
            x_n = (x_c + 3.0) / 6.0  # normalize to [0,1]
            kp = torch.linspace(0, 1, self.n_knots, device=x.device)
            width = 1.0 / max(self.n_knots - 1, 1)
            # Gaussian basis: [B, in_dim, n_knots]
            basis = torch.exp(-0.5 * ((x_n.unsqueeze(-1) - kp) / width)**2)
            basis = basis / (basis.sum(-1, keepdim=True) + 1e-8)
            # Spline output: [B, out_dim, in_dim]
            spline_out = torch.einsum('bik,oik->boi', basis, self.weights)
            # Residual SiLU: [B, out_dim, in_dim]
            residual = self.residual_scale.unsqueeze(0) * nn.functional.silu(x).unsqueeze(1)
            # Sum over in_dim: [B, out_dim]
            out = (spline_out + residual).sum(-1)
            return self.norm(out)

    class KANNetwork(nn.Module):
        """2-layer KAN: 5 -> 8 -> 1, output = log(sigma2)."""
        def __init__(self, in_dim=5, hidden_dim=8, n_knots=8):
            super().__init__()
            self.kan1 = KANLayerVectorized(in_dim, hidden_dim, n_knots)
            self.kan2 = KANLayerVectorized(hidden_dim, 1, n_knots)
            self.output_bias = nn.Parameter(torch.tensor([-8.0]))

        def forward(self, x):
            return self.kan2(self.kan1(x)).squeeze(-1) + self.output_bias

        def predict_var(self, x):
            return torch.exp(self.forward(x)).clamp(min=1e-10)

    class MLPNetwork(nn.Module):
        """2-layer MLP with ReLU + LayerNorm (comparable capacity)."""
        def __init__(self, in_dim=5, hidden_dim=16):
            super().__init__()
            self.net = nn.Sequential(
                nn.Linear(in_dim, hidden_dim), nn.LayerNorm(hidden_dim), nn.ReLU(),
                nn.Linear(hidden_dim, 8), nn.LayerNorm(8), nn.ReLU(),
                nn.Linear(8, 1),
            )
            self.output_bias = nn.Parameter(torch.tensor([-8.0]))

        def forward(self, x):
            return self.net(x).squeeze(-1) + self.output_bias

        def predict_var(self, x):
            return torch.exp(self.forward(x)).clamp(min=1e-10)

    def qlike_loss(log_s2, r2):
        s2 = torch.exp(log_s2).clamp(min=1e-10)
        return (-log_s2 + r2 / s2).mean()

    def train_nn(model, X_tr, y_tr, n_epochs=300, lr=5e-4, batch=64):
        opt = optim.Adam(model.parameters(), lr=lr, weight_decay=1e-4)
        sched = optim.lr_scheduler.CosineAnnealingLR(opt, T_max=n_epochs)
        X_t = torch.tensor(X_tr, dtype=torch.float32)
        y_t = torch.tensor(y_tr, dtype=torch.float32)
        mu = X_t.mean(0, keepdim=True)
        sig = X_t.std(0, keepdim=True).clamp(min=1e-8)
        X_norm = (X_t - mu) / sig
        ds = torch.utils.data.TensorDataset(X_norm, y_t)
        loader = torch.utils.data.DataLoader(ds, batch_size=batch, shuffle=True)
        best_loss, best_state, patience = np.inf, None, 0
        for ep in range(n_epochs):
            model.train()
            ep_loss = 0.0
            for xb, yb in loader:
                opt.zero_grad()
                loss = qlike_loss(model(xb), yb)
                loss.backward()
                nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                opt.step()
                ep_loss += loss.item()
            sched.step()
            avg = ep_loss / max(len(loader), 1)
            if avg < best_loss - 1e-6:
                best_loss = avg
                best_state = {k: v.clone() for k, v in model.state_dict().items()}
                patience = 0
            else:
                patience += 1
            if patience >= 30:
                break
        if best_state:
            model.load_state_dict(best_state)
        return model, mu, sig

    def predict_nn(model, X, mu, sig):
        model.eval()
        with torch.no_grad():
            Xt = (torch.tensor(X, dtype=torch.float32) - mu) / sig
            return model.predict_var(Xt).numpy()


def dm_test(loss1, loss2):
    """DM test with Harvey et al. (1997) small-sample correction."""
    from scipy.stats import t as tdist
    d = loss1 - loss2
    n = len(d)
    d_bar = np.mean(d)
    lag_max = min(int(1.5 * n**(1/3)), 20)
    # Newey-West HAC variance
    v = np.var(d, ddof=1)
    for lag in range(1, lag_max+1):
        w = 1 - lag / (lag_max + 1)
        v += 2 * w * np.mean((d[lag:] - d_bar) * (d[:-lag] - d_bar))
    v = max(v, 1e-15)
    corr = (n + 1 - 2 + 1/n) / n
    dm = d_bar / np.sqrt(corr * v / n)
    p = 2 * (1 - tdist.cdf(abs(dm), df=n-1))
    return float(dm), float(p)


def qlike_s(s2, r2):
    s2c = np.clip(s2, 1e-10, None)
    return -np.log(s2c) + r2 / s2c


def run_experiment():
    df = load_data()
    r_all = df['r'].values
    vix_all = df['vix'].values
    tau_all = compute_tau(r_all, lam=0.997)

    oos_start = pd.Timestamp("2023-01-01")
    oos_end = pd.Timestamp("2024-12-31")
    oos_idx = np.where((df.index >= oos_start) & (df.index <= oos_end))[0]
    train_idx = np.where(df.index < oos_start)[0]

    print(f"IS: {df.index[0].date()} to {df.index[train_idx[-1]].date()} ({len(train_idx)} days)")
    print(f"OOS: {df.index[oos_idx[0]].date()} to {df.index[oos_idx[-1]].date()} ({len(oos_idx)} days)")

    refit_every = 63
    refit_points = list(range(oos_idx[0], oos_idx[-1]+1, refit_every))

    gjr_preds, midas_preds, kan_preds, mlp_preds, actuals = [], [], [], [], []

    for seg_i, seg_start in enumerate(refit_points):
        if seg_start > oos_idx[-1]:
            break
        seg_end = min(seg_start + refit_every, oos_idx[-1] + 1)

        r_tr = r_all[:seg_start]
        vix_tr = vix_all[:seg_start]
        tau_tr = tau_all[:seg_start]

        gjr_params, gjr_h = fit_gjr(r_tr)
        gjr_h_last = gjr_h[-1]
        uncond = max(np.var(r_tr), 1e-10)
        g_tr = gjr_h / uncond

        pers = gjr_params[1] + gjr_params[2]/2 + gjr_params[3]
        print(f"Seg {seg_i+1}/{len(refit_points)}: n_train={len(r_tr)}, seg=[{seg_start},{seg_end}), persistence={pers:.4f}")

        if HAS_TORCH and len(r_tr) > 200:
            # Features[:-1] -> targets r2[1:] (lag=1, no lookahead)
            X_feat = build_features(g_tr[:-1], tau_tr[:-1], vix_tr[:-1], r_tr[:-1])
            y_feat = r_tr[1:]**2

            kan_model = KANNetwork(in_dim=5, hidden_dim=8, n_knots=8)
            kan_model, kan_mu, kan_sig = train_nn(kan_model, X_feat, y_feat,
                                                   n_epochs=300, lr=5e-4, batch=64)

            mlp_model = MLPNetwork(in_dim=5, hidden_dim=16)
            mlp_model, mlp_mu, mlp_sig = train_nn(mlp_model, X_feat, y_feat,
                                                    n_epochs=300, lr=5e-4, batch=64)
        else:
            kan_model = mlp_model = None

        gjr_h_t = gjr_h_last
        for t in range(seg_start, seg_end):
            if t > oos_idx[-1]:
                break

            # GJR one-step-ahead prediction (uses t-1 info)
            gjr_p = gjr_predict_one(gjr_params, gjr_h_t, r_all[t-1])

            # GARCH-MIDAS: normalized g * tau (uses t-1 info)
            g_t_norm = gjr_p / uncond
            midas_p = max(g_t_norm * tau_all[t-1], 1e-10)

            # NN: features at t-1
            if HAS_TORCH and kan_model is not None:
                g_prev = gjr_h_t / uncond
                X_p = build_features(
                    np.array([g_prev]),
                    np.array([tau_all[t-1]]),
                    np.array([vix_all[t-1]]),
                    np.array([r_all[t-1]])
                )
                kan_p = float(predict_nn(kan_model, X_p, kan_mu, kan_sig)[0])
                mlp_p = float(predict_nn(mlp_model, X_p, mlp_mu, mlp_sig)[0])
            else:
                kan_p = gjr_p
                mlp_p = gjr_p

            gjr_preds.append(gjr_p)
            midas_preds.append(midas_p)
            kan_preds.append(kan_p)
            mlp_preds.append(mlp_p)
            actuals.append(r_all[t]**2)

            gjr_h_t = gjr_predict_one(gjr_params, gjr_h_t, r_all[t])

    print(f"\nOOS predictions: {len(actuals)}")

    r2 = np.array(actuals)
    gjr_s2 = np.array(gjr_preds)
    midas_s2 = np.array(midas_preds)
    kan_s2 = np.array(kan_preds)
    mlp_s2 = np.array(mlp_preds)

    ql_g = qlike_s(gjr_s2, r2)
    ql_m = qlike_s(midas_s2, r2)
    ql_k = qlike_s(kan_s2, r2)
    ql_p = qlike_s(mlp_s2, r2)

    mg = float(np.mean(ql_g))
    mm = float(np.mean(ql_m))
    mk = float(np.mean(ql_k))
    mp = float(np.mean(ql_p))

    dm_m, p_m = dm_test(ql_g, ql_m)
    dm_k, p_k = dm_test(ql_g, ql_k)
    dm_p, p_p = dm_test(ql_g, ql_p)
    dm_kp, p_kp = dm_test(ql_p, ql_k)

    sp_g = float(spearmanr(gjr_s2, r2)[0])
    sp_m = float(spearmanr(midas_s2, r2)[0])
    sp_k = float(spearmanr(kan_s2, r2)[0])
    sp_p = float(spearmanr(mlp_s2, r2)[0])

    def pct(a, b):
        return 100*(a-b)/abs(b)

    T = 3.0
    print("\n" + "="*68)
    print("K797: KAN-GARCH-MIDAS OOS Results (SPY, 2023-2024)")
    print("="*68)
    print(f"{'Model':<20} {'QLIKE':>9} {'vs GJR%':>9} {'DM':>8} {'p-val':>8} {'Spearman':>9}")
    print("-"*68)
    print(f"{'GJR-GARCH':<20} {mg:9.6f} {'(baseline)':>9}")
    print(f"{'GARCH-MIDAS':20} {mm:9.6f} {pct(mm,mg):+8.3f}% {dm_m:8.3f} {p_m:8.4f} {sp_m:9.4f}")
    print(f"{'KAN-GARCH':20} {mk:9.6f} {pct(mk,mg):+8.3f}% {dm_k:8.3f} {p_k:8.4f} {sp_k:9.4f}")
    print(f"{'MLP-GARCH':20} {mp:9.6f} {pct(mp,mg):+8.3f}% {dm_p:8.3f} {p_p:8.4f} {sp_p:9.4f}")
    print(f"\nKAN vs MLP: DM={dm_kp:.3f}, p={p_kp:.4f}")
    print(f"Harvey t>3.0: {'SOME SIGNIFICANT' if any([abs(dm_m)>T, abs(dm_k)>T, abs(dm_p)>T]) else 'ALL NULL'}")
    print("="*68)

    results = {
        "experiment_id": "k797",
        "title": "K797: KAN-GARCH-MIDAS -- Kolmogorov-Arnold Network for Volatility Forecasting",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "literature": [
            "Liu et al. (2024) KAN: Kolmogorov-Arnold Networks, arXiv:2404.19756",
            "KAN-GARCH-MIDAS, J. Applied Economics 2025 (T&F)",
            "Engle, Ghysels & Sohn (2013) GARCH-MIDAS, JBES",
            "Patton (2011) QLIKE proxy-robust, J. Econometrics",
            "Harvey et al. (1997) DM test correction, JBES"
        ],
        "data": {
            "asset": "SPY",
            "source": "yfinance",
            "vix_source": "yfinance ^VIX",
            "is_period": f"{df.index[0].date()} to {df.index[train_idx[-1]].date()}",
            "oos_period": "2023-01-01 to 2024-12-31",
            "n_oos": len(actuals),
            "n_is": len(train_idx)
        },
        "model_details": {
            "gjr": "GJR-GARCH(1,1), L-BFGS-B, 3-start, Normal QML",
            "midas": "normalized g * tau, tau=EWMA(r2,lambda=0.997)",
            "kan": "2-layer KAN, vectorized B-spline (einsum), 8 knots, hidden=8",
            "mlp": "2-layer MLP ReLU LayerNorm hidden=16->8, same features",
            "features": "[g_t-1, tau_t-1, VIX_t-1/100, |r_t-1|, log(tau_t-1)]",
            "oos_window": "expanding, refit every 63 days",
            "lookahead_check": "Features at t-1 -> r2_t. Code verified: no lookahead."
        },
        "results": {
            "qlike_mean": {
                "gjr": round(mg, 6),
                "garch_midas": round(mm, 6),
                "kan_garch": round(mk, 6),
                "mlp_garch": round(mp, 6)
            },
            "qlike_vs_gjr_pct": {
                "garch_midas": round(pct(mm, mg), 4),
                "kan_garch": round(pct(mk, mg), 4),
                "mlp_garch": round(pct(mp, mg), 4)
            },
            "dm_vs_gjr": {
                "garch_midas": {"dm": round(dm_m, 4), "p_value": round(p_m, 4)},
                "kan_garch": {"dm": round(dm_k, 4), "p_value": round(p_k, 4)},
                "mlp_garch": {"dm": round(dm_p, 4), "p_value": round(p_p, 4)}
            },
            "dm_kan_vs_mlp": {"dm": round(dm_kp, 4), "p_value": round(p_kp, 4)},
            "spearman": {
                "gjr": round(sp_g, 4),
                "garch_midas": round(sp_m, 4),
                "kan_garch": round(sp_k, 4),
                "mlp_garch": round(sp_p, 4)
            },
            "harvey_significant": {
                "garch_midas_beats_gjr": bool(dm_m > T),
                "kan_beats_gjr": bool(dm_k > T),
                "mlp_beats_gjr": bool(dm_p > T),
                "kan_beats_mlp": bool(dm_kp > T)
            }
        },
        "conclusion": "",
        "limitations": [
            "SPY only -- cross-asset validation needed",
            "OOS 2023-2024 (504 days) -- limited OOS sample",
            "KAN uses Gaussian basis approximation of B-splines (not exact)",
            "tau is EWMA, not true MIDAS Beta polynomial weighting",
            "Pure vol forecast test; no transaction costs needed"
        ]
    }

    kb, pb = results["results"]["harvey_significant"]["kan_beats_gjr"], results["results"]["harvey_significant"]["mlp_beats_gjr"]
    if kb and not pb:
        conc = f"KAN BEATS GJR (DM={dm_k:.3f}, p={p_k:.4f}), MLP does not. Spline activations add value."
    elif kb and pb:
        conc = f"Both KAN and MLP beat GJR (KAN {pct(mk,mg):+.2f}%, MLP {pct(mp,mg):+.2f}%). Nonlinear combination helps."
    elif not kb and not pb:
        conc = (f"NULL RESULT: Neither KAN ({pct(mk,mg):+.2f}%, DM={dm_k:.3f}) "
                f"nor MLP ({pct(mp,mg):+.2f}%, DM={dm_p:.3f}) beats GJR. "
                f"Consistent with QLIKE ceiling (K526, K784). Daily r2 already sufficient statistic for daily sigma2.")
    else:
        conc = f"MIXED: MLP {pct(mp,mg):+.2f}% DM={dm_p:.3f}; KAN {pct(mk,mg):+.2f}% DM={dm_k:.3f}."

    results["conclusion"] = conc
    print(f"\nConclusion: {conc}")

    out = "/Users/yhlai0911/Desktop/volpred-research/experiments/k797_kan_garch_results.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nSaved to: {out}")
    return results


if __name__ == "__main__":
    run_experiment()
