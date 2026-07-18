#!/usr/bin/env python3
"""MOVE jump -> JPY carry unwind -> EM assets: transmission-chain event study.

Sample: 2016-01-04 .. 2026-07-10 (^MOVE last valid close on yfinance as of 2026-07-19)
Data: yfinance daily closes (auto_adjust=True) for ^MOVE, JPY=X (USDJPY), FXY, EEM, ^VIX, TLT, EWZ, EWY
Outputs: evidence.json + charts in this directory.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
START = "2016-01-04"

px = pd.read_csv(HERE / "raw_prices.csv", index_col=0, parse_dates=True)
move = px["^MOVE"].dropna()
END = move.index[-1]

px = px.loc[START:END]
move = move.loc[START:END]

# align on MOVE trading days
idx = move.index
ret = np.log(px[["JPY=X", "FXY", "EEM", "EWZ", "EWY", "TLT"]]).diff()
ret = ret.reindex(idx)

dmove = np.log(move).diff()

# ---- Event definition: MOVE daily log change >= trailing 252d 90th pct (no lookahead)
thr = dmove.rolling(252, min_periods=126).quantile(0.90).shift(1)
event = (dmove >= thr) & thr.notna()
event = event.fillna(False)

# de-clustered version: keep first event in any 10-day window
declust = []
last = -99
for i, (d, e) in enumerate(event.items()):
    if e and i - last >= 10:
        declust.append(d)
        last = i
declust = pd.DatetimeIndex(declust)

valid = thr.notna()
n_days = int(valid.sum())
n_events = int(event[valid].sum())


def fwd(series: pd.Series, h: int) -> pd.Series:
    """log return from t to t+h (cumulative), aligned at t."""
    c = series.cumsum()
    return (c.shift(-h) - c)


def hac_test(y: pd.Series, d: pd.Series, h: int):
    m = pd.concat([y, d.astype(float)], axis=1).dropna()
    m.columns = ["y", "d"]
    X = sm.add_constant(m["d"])
    res = sm.OLS(m["y"], X).fit(cov_type="HAC", cov_kwds={"maxlags": h + 5})
    return {
        "n_event": int(m["d"].sum()),
        "n_other": int((m["d"] == 0).sum()),
        "mean_event_pct": float(m.loc[m.d == 1, "y"].mean() * 100),
        "mean_other_pct": float(m.loc[m.d == 0, "y"].mean() * 100),
        "diff_pct": float(res.params["d"] * 100),
        "tstat": float(res.tvalues["d"]),
        "pval": float(res.pvalues["d"]),
    }


results = {}
for name, col, sign_note in [
    ("USDJPY", "JPY=X", "negative = yen appreciates (carry unwind direction)"),
    ("FXY", "FXY", "positive = yen appreciates"),
    ("EEM", "EEM", "negative = EM equity under pressure"),
    ("EWZ", "EWZ", "negative = Brazil under pressure"),
    ("EWY", "EWY", "negative = Korea under pressure"),
]:
    results[name] = {"note": sign_note, "horizons": {}}
    for h in (1, 5, 10):
        results[name]["horizons"][f"h{h}"] = hac_test(fwd(ret[col], h), event, h)

# de-clustered robustness for the three headline series
ev_dc = pd.Series(False, index=idx)
ev_dc.loc[declust] = True
results_dc = {}
for name, col in [("USDJPY", "JPY=X"), ("EEM", "EEM"), ("FXY", "FXY")]:
    results_dc[name] = {f"h{h}": hac_test(fwd(ret[col], h), ev_dc, h) for h in (1, 5, 10)}

# ---- Link B: yen surge -> EM  (does the second leg of the chain work at all?)
jpy5 = fwd(ret["JPY=X"], 5).shift(5)  # trailing 5d USDJPY move ending at t
yen_surge = (jpy5 <= np.log(1 - 0.02))  # USDJPY down >=2% over 5d = yen up
yen_surge = yen_surge.fillna(False)
link_b = {f"h{h}": hac_test(fwd(ret["EEM"], h), yen_surge, h) for h in (1, 5, 10)}
link_b_n = int(yen_surge.sum())

# ---- Conditional: MOVE jump WITH vs WITHOUT same-day yen appreciation
yen_up_today = ret["JPY=X"] < 0
ev_with = (event & yen_up_today).fillna(False)
ev_without = (event & ~yen_up_today).fillna(False)
cond = {}
for label, ev in [("move_jump_with_yen_up", ev_with), ("move_jump_with_yen_down", ev_without)]:
    cond[label] = {
        "n": int(ev.sum()),
        **{f"EEM_h{h}": hac_test(fwd(ret["EEM"], h), ev, h) for h in (5, 10)},
        **{f"USDJPY_h{h}": hac_test(fwd(ret["JPY=X"], h), ev, h) for h in (5, 10)},
    }

# ---- Contemporaneous correlation of dMOVE vs dUSDJPY, full + rolling
both = pd.concat([dmove.rename("dmove"), ret["JPY=X"].rename("djpy")], axis=1).dropna()
corr_full = float(both.corr().iloc[0, 1])
roll_corr = both["dmove"].rolling(252).corr(both["djpy"]).dropna()
corr_2024 = float(both.loc["2024"].corr().iloc[0, 1])

# ---- 2024-08 case study
case_win = px.loc["2024-07-10":"2024-08-16"]
def pct(s, a, b):
    return float((s.loc[b] / s.loc[a] - 1) * 100)
case = {
    "window": "2024-07-31 (BoJ hike) .. 2024-08-05",
    "MOVE_2024_07_31": float(move.loc["2024-07-31"]),
    "MOVE_2024_08_05": float(move.loc["2024-08-05"]),
    "MOVE_pct": pct(move, "2024-07-31", "2024-08-05"),
    "USDJPY_2024_07_31": float(px["JPY=X"].loc["2024-07-31"]),
    "USDJPY_2024_08_05": float(px["JPY=X"].loc["2024-08-05"]),
    "USDJPY_pct": pct(px["JPY=X"], "2024-07-31", "2024-08-05"),
    "EEM_pct": pct(px["EEM"], "2024-07-31", "2024-08-05"),
    "EWY_pct": pct(px["EWY"], "2024-07-31", "2024-08-05"),
    "EWZ_pct": pct(px["EWZ"], "2024-07-31", "2024-08-05"),
    "VIX_2024_08_05": float(px["^VIX"].loc["2024-08-05"]),
    "EEM_recovery_days_to_prior_level": None,
}
# recovery: days until EEM regains 2024-07-31 close
base = px["EEM"].loc["2024-07-31"]
after = px["EEM"].loc["2024-08-06":]
rec = after[after >= base]
if len(rec):
    case["EEM_recovery_date"] = str(rec.index[0].date())
    case["EEM_recovery_days_to_prior_level"] = int(
        px["EEM"].loc["2024-08-05":rec.index[0]].shape[0] - 1
    )

# ---- Did MOVE actually lead in 2024-08? Check whether 07-31..08-05 was a MOVE event day
ev_dates_2024_aug = [str(d.date()) for d in idx[(event.values) & (idx >= "2024-07-25") & (idx <= "2024-08-09")]]

# ---- Top-10 largest MOVE jumps: what did USDJPY/EEM do next 5d
top10 = dmove.loc[valid].nlargest(10)
top_tbl = []
for d in top10.index:
    top_tbl.append({
        "date": str(d.date()),
        "dMOVE_pct": float((np.exp(dmove.loc[d]) - 1) * 100),
        "MOVE_level": float(move.loc[d]),
        "USDJPY_fwd5_pct": float((np.exp(fwd(ret["JPY=X"], 5).loc[d]) - 1) * 100) if not np.isnan(fwd(ret["JPY=X"], 5).loc[d]) else None,
        "EEM_fwd5_pct": float((np.exp(fwd(ret["EEM"], 5).loc[d]) - 1) * 100) if not np.isnan(fwd(ret["EEM"], 5).loc[d]) else None,
    })

# ---- hit rates (direction consistency) for the chain
def hit_rate(col, h, direction):
    f = fwd(ret[col], h)[event].dropna()
    if direction == "neg":
        return float((f < 0).mean() * 100), int(len(f))
    return float((f > 0).mean() * 100), int(len(f))

hits = {
    "USDJPY_h5_down_pct": hit_rate("JPY=X", 5, "neg"),
    "EEM_h5_down_pct": hit_rate("EEM", 5, "neg"),
    "EEM_h10_down_pct": hit_rate("EEM", 10, "neg"),
}
base_hits = {
    "USDJPY_h5_down_pct_all": float((fwd(ret["JPY=X"], 5).dropna() < 0).mean() * 100),
    "EEM_h5_down_pct_all": float((fwd(ret["EEM"], 5).dropna() < 0).mean() * 100),
    "EEM_h10_down_pct_all": float((fwd(ret["EEM"], 10).dropna() < 0).mean() * 100),
}

# ---- realized vol change around events (EEM), 10d before vs 10d after
rv = ret["EEM"].rolling(10).std() * np.sqrt(252) * 100
rv_before = rv.copy()
rv_after = rv.shift(-10)
rvc = (rv_after - rv_before)
rv_res = hac_test(rvc, event, 10)

# ---- lead-lag: corr(dMOVE_t, dUSDJPY_{t+k})
lead_lag = {}
for k in range(-3, 4):
    s = pd.concat([both["dmove"], both["djpy"].shift(-k)], axis=1).dropna()
    lead_lag[f"k={k:+d}"] = float(s.corr().iloc[0, 1])

# ---- 2024-08 daily sequence (who moved first?)
seq_idx = px.loc["2024-07-29":"2024-08-07"].index
case_daily = []
for d in seq_idx:
    case_daily.append({
        "date": str(d.date()),
        "MOVE": float(move.loc[d]) if d in move.index else None,
        "MOVE_chg_pct": float((np.exp(dmove.loc[d]) - 1) * 100) if d in dmove.index and pd.notna(dmove.loc[d]) else None,
        "USDJPY": float(px["JPY=X"].loc[d]),
        "USDJPY_chg_pct": float((np.exp(ret["JPY=X"].loc[d]) - 1) * 100) if d in ret.index and pd.notna(ret["JPY=X"].loc[d]) else None,
        "EEM_chg_pct": float((np.exp(ret["EEM"].loc[d]) - 1) * 100) if d in ret.index and pd.notna(ret["EEM"].loc[d]) else None,
    })

evidence = {
    "meta": {
        "sample_start": START,
        "sample_end": str(END.date()),
        "n_trading_days_with_valid_threshold": n_days,
        "n_move_jump_events": n_events,
        "n_declustered_events": int(len(declust)),
        "event_rule": "dlnMOVE_t >= trailing-252d 90th percentile of dlnMOVE, threshold uses data up to t-1 only",
        "data_source": "yfinance daily close, auto_adjust=True; tickers ^MOVE, JPY=X, FXY, EEM, EWZ, EWY, ^VIX, TLT",
        "raw_csv": "raw_prices.csv",
        "move_as_of_note": "^MOVE last valid close 2026-07-10; later sessions unavailable on yfinance at time of writing",
        "test": "OLS on event dummy with Newey-West HAC SE (maxlags = h+5); overlapping windows acknowledged",
    },
    "event_study_all_events": results,
    "event_study_declustered": results_dc,
    "link_b_yen_surge_to_EEM": {"n_days_yen_surge": link_b_n, "definition": "trailing 5d USDJPY <= -2%", "results": link_b},
    "conditional_split": cond,
    "correlation": {
        "dMOVE_vs_dUSDJPY_full_sample": corr_full,
        "dMOVE_vs_dUSDJPY_2024": corr_2024,
        "rolling252_min": float(roll_corr.min()),
        "rolling252_max": float(roll_corr.max()),
        "rolling252_min_date": str(roll_corr.idxmin().date()),
        "rolling252_max_date": str(roll_corr.idxmax().date()),
    },
    "case_2024_08": case,
    "case_2024_08_daily": case_daily,
    "lead_lag_corr_dMOVE_vs_dUSDJPY": lead_lag,
    "move_event_dates_around_2024_08": ev_dates_2024_aug,
    "top10_move_jumps": top_tbl,
    "hit_rates_event": hits,
    "hit_rates_unconditional": base_hits,
    "eem_realized_vol_change_10d": rv_res,
}

(HERE / "evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")

# ================= charts =================
plt.rcParams.update({"font.size": 10, "axes.grid": True, "grid.alpha": 0.3})
import matplotlib.font_manager as fm
_avail = {f.name for f in fm.fontManager.ttflist}
for _c in ["Heiti TC", "PingFang TC", "PingFang HK", "Arial Unicode MS", "Songti TC", "STHeiti"]:
    if _c in _avail:
        plt.rcParams["font.sans-serif"] = [_c, "DejaVu Sans"]
        plt.rcParams["font.family"] = "sans-serif"
        plt.rcParams["axes.unicode_minus"] = False
        print("CJK font:", _c)
        break
else:
    print("WARNING: no CJK font found")

# Chart 1: average cumulative path after MOVE jump vs unconditional
fig, ax = plt.subplots(figsize=(9, 5.2))
hs = range(0, 16)
for name, col, c in [("USDJPY", "JPY=X", "#c0392b"), ("EEM", "EEM", "#2c7fb8"), ("FXY (yen ETF)", "FXY", "#27ae60")]:
    ev_path = [0.0] + [float(fwd(ret[col], h)[event].mean() * 100) for h in list(hs)[1:]]
    un_path = [0.0] + [float(fwd(ret[col], h).mean() * 100) for h in list(hs)[1:]]
    ax.plot(list(hs), ev_path, marker="o", ms=3.5, color=c, label=f"{name}: after MOVE jump")
    ax.plot(list(hs), un_path, ls="--", lw=1.2, color=c, alpha=0.65, label=f"{name}: all days")
ax.axhline(0, color="k", lw=0.8)
ax.set_xlabel("trading days after event (t=0)")
ax.set_ylabel("mean cumulative log return (%)")
ax.set_title(f"MOVE jump events (n={n_events}) vs unconditional average path\n{START} to {END.date()}, yfinance daily")
ax.legend(fontsize=8, ncol=2)
fig.tight_layout()
fig.savefig(HERE / "chart1_event_paths.png", dpi=150)
plt.close(fig)

# Chart 2: 2024-08 episode - normalized
fig, ax = plt.subplots(figsize=(9, 5.0))
w = px.loc["2024-07-15":"2024-08-30", ["JPY=X", "EEM", "EWY"]].dropna()
b = w.iloc[0]
ax.plot(w.index, w["JPY=X"] / b["JPY=X"] * 100, color="#c0392b", label="USDJPY")
ax.plot(w.index, w["EEM"] / b["EEM"] * 100, color="#2c7fb8", label="EEM")
ax.plot(w.index, w["EWY"] / b["EWY"] * 100, color="#8e44ad", label="EWY (Korea)")
ax2 = ax.twinx()
mm = move.loc["2024-07-15":"2024-08-30"]
ax2.plot(mm.index, mm.values, color="#7f8c8d", lw=1.4, ls=":", label="MOVE 指數（右軸）")
ax2.set_ylabel("MOVE index")
ax.axvline(pd.Timestamp("2024-07-31"), color="k", lw=1, ls="--")
ax.annotate("BoJ 升息 7/31", xy=(pd.Timestamp("2024-07-31"), 89.5),
            xytext=(pd.Timestamp("2024-07-17"), 89.0), fontsize=9,
            arrowprops=dict(arrowstyle="->", lw=0.9))
ax.set_ylabel("index, 2024-07-15 = 100")
ax.set_title("2024 年 8 月日圓套利平倉：USDJPY、EEM、EWY 與 MOVE")
h1, l1 = ax.get_legend_handles_labels()
h2, l2 = ax2.get_legend_handles_labels()
ax.legend(h1 + h2, l1 + l2, fontsize=8, loc="lower right")
fig.autofmt_xdate()
fig.tight_layout()
fig.savefig(HERE / "chart2_2024_08_episode.png", dpi=150)
plt.close(fig)

# Chart 3: rolling 252d correlation dMOVE vs dUSDJPY
fig, ax = plt.subplots(figsize=(9, 4.2))
ax.plot(roll_corr.index, roll_corr.values, color="#34495e")
ax.axhline(0, color="k", lw=0.8)
ax.axhline(corr_full, color="#e67e22", ls="--", lw=1, label=f"full-sample corr = {corr_full:+.3f}")
ax.set_ylabel("252d rolling corr")
ax.set_title("MOVE 日變動 vs USDJPY 日變動：滾動 252 日相關係數")
ax.legend(fontsize=8)
fig.tight_layout()
fig.savefig(HERE / "chart3_rolling_corr.png", dpi=150)
plt.close(fig)

print(json.dumps({
    "n_events": n_events, "n_days": n_days,
    "USDJPY_h5": results["USDJPY"]["horizons"]["h5"],
    "EEM_h5": results["EEM"]["horizons"]["h5"],
    "EEM_h10": results["EEM"]["horizons"]["h10"],
    "corr_full": corr_full, "corr_2024": corr_2024,
    "link_b_h5": link_b["h5"],
    "case": case,
    "hits": hits, "base_hits": base_hits,
}, ensure_ascii=False, indent=2))
