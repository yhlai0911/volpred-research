"""Diagnostic: corrected DY spillover on the paper-local pinned snapshot.

Replicates k1025_v2.py pipeline (auto_adjust=True equivalent = adj_close columns,
SPY simple ret, BTC log ret, 20d rolling std * sqrt(252), levels VAR) but fixes
the FEVD slicing bug: statsmodels FEVD.decomp shape is (neqs, periods, neqs);
the h=10 cross-variable matrix is decomp[:, -1, :], NOT decomp[-1].
Runs both orderings to gauge Cholesky ordering sensitivity.
"""
import numpy as np
import pandas as pd
from statsmodels.tsa.api import VAR

CSV = "/Users/yhlai0911/volpred-research/paper/crypto-fear-channel/data/spy_btc_usd_vix_2015-2026.csv"

df = pd.read_csv(CSV, parse_dates=["date"], index_col="date")
spy_ret = df["spy_adj_close"].pct_change().dropna()
btc_ret = np.log(df["btc_usd_adj_close"] / df["btc_usd_adj_close"].shift(1)).dropna()
vix_level = df["vix_adj_close"].dropna()

common = spy_ret.index.intersection(btc_ret.index).intersection(vix_level.index)
spy_ret, btc_ret, vix_level = spy_ret.loc[common], btc_ret.loc[common], vix_level.loc[common]

btc_rv20 = (btc_ret.rolling(20).std() * np.sqrt(252)).dropna()
spy_rv20 = (spy_ret.rolling(20).std() * np.sqrt(252)).dropna()
common2 = btc_rv20.index.intersection(spy_rv20.index).intersection(vix_level.index)
btc_rv20, spy_rv20, vix_lv = btc_rv20.loc[common2], spy_rv20.loc[common2], vix_level.loc[common2]
print(f"N = {len(common2)}  ({common2[0].date()} .. {common2[-1].date()})")


def dy_correct(data, btc_col, horizon=10):
    """Correct DY index: 3x3 FEVD matrix at final horizon."""
    try:
        model = VAR(data)
        opt = max(model.select_order(maxlags=5).aic, 1)
        res = model.fit(opt)
        m = res.fevd(horizon).decomp[:, -1, :]  # (neqs, neqs): row=eq, col=shock
        m = m / m.sum(axis=1, keepdims=True)
        n = m.shape[0]
        total = (m.sum() - np.trace(m)) / n * 100
        j = data.columns.get_loc(btc_col)
        to_btc = m[:, j].sum() - m[j, j]      # transmitted BY btc to others
        from_btc = m[j, :].sum() - m[j, j]    # received by btc from others
        return total, to_btc * 100, from_btc * 100, (to_btc - from_btc) * 100
    except Exception:
        return None


for name, cols in [
    ("code order {BTC,SPY,VIX}", ["BTC_RV", "SPY_RV", "VIX"]),
    ("paper order {VIX,SPY,BTC}", ["VIX", "SPY_RV", "BTC_RV"]),
]:
    var_data = pd.DataFrame({"BTC_RV": btc_rv20, "SPY_RV": spy_rv20, "VIX": vix_lv}).dropna()[cols]
    rows = []
    for i in range(252, len(var_data), 5):
        r = dy_correct(var_data.iloc[i - 252 : i], "BTC_RV")
        if r is not None:
            rows.append((var_data.index[i], *r))
    out = pd.DataFrame(rows, columns=["date", "total", "to_btc", "from_btc", "net_btc"]).set_index("date")
    print(f"\n== {name} ==  n_windows={len(out)}")
    print(f"total spillover: mean={out.total.mean():.2f}%  std={out.total.std():.2f}  "
          f"min={out.total.min():.2f}  max={out.total.max():.2f}")
    print(f"to_btc:   mean={out.to_btc.mean():.2f}   from_btc: mean={out.from_btc.mean():.2f}")
    print(f"net_btc:  mean={out.net_btc.mean():.2f}  min={out.net_btc.min():.2f}  max={out.net_btc.max():.2f}")
    share_recv = (out.net_btc < 0).mean() * 100
    print(f"windows with BTC net receiver: {share_recv:.1f}%")
    peak = out.total.idxmax()
    print(f"total-index peak at {peak.date()} = {out.total.max():.2f}%")
