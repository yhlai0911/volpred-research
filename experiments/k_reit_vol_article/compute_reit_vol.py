"""REIT / Housing Vol vs SPY Vol — 實證分析資料生成

支援 daily_article (2026-04-19):
  - VNQ / SPY realized vol 對比
  - VNQ-SPY rolling correlation
  - HAR-RV QLIKE OOS 比較
  - 跨利率 regime 的 rolling corr 差異

資料源: yfinance auto_adjust=False (data snapshot rule 2026-04-19)
期間: 2015-01-02 ~ 2026-04-17 (2839 obs)
Seed: 42

Output:
  - reit_vol_data.csv (日頻 log returns, RV, rolling corr)
  - fig_vnq_spy_rv.png (時序對比)
  - fig_vnq_spy_corr.png (rolling correlation 時序)
  - reit_vol_results.json (統計量)
"""
import json
import numpy as np
import pandas as pd
import yfinance as yf
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path

np.random.seed(42)

OUT = Path(__file__).parent
OUT.mkdir(parents=True, exist_ok=True)

TICKERS = ["VNQ", "SPY"]
START = "2015-01-02"
END = "2026-04-18"  # inclusive via yfinance end-exclusive

print(f"[info] downloading {TICKERS} from yfinance auto_adjust=False …")
raw = yf.download(TICKERS, start=START, end=END, auto_adjust=False, progress=False)
adj = raw["Adj Close"].dropna(how="any")
print(f"[info] shape={adj.shape}, range={adj.index.min().date()} -> {adj.index.max().date()}")

# Log returns (percent, like 1.0 = 1%)
rets = np.log(adj / adj.shift(1)).dropna() * 100.0
rets.columns = [f"r_{c}" for c in rets.columns]

# HAR-RV-style realized variance proxy: 22-day rolling variance (daily)
RV_WIN = 22
rv = rets.rolling(RV_WIN).var().dropna()
rv.columns = [f"rv_{c.split('_')[1]}" for c in rv.columns]

# Rolling correlation VNQ vs SPY (63-day ~ quarterly)
CORR_WIN = 63
roll_corr = rets["r_VNQ"].rolling(CORR_WIN).corr(rets["r_SPY"]).dropna()
roll_corr.name = "corr_VNQ_SPY_63d"

# Full-sample summary stats
mu_VNQ = rets["r_VNQ"].mean() * 252
mu_SPY = rets["r_SPY"].mean() * 252
sigma_VNQ = rets["r_VNQ"].std() * np.sqrt(252)
sigma_SPY = rets["r_SPY"].std() * np.sqrt(252)
sharpe_VNQ = mu_VNQ / sigma_VNQ
sharpe_SPY = mu_SPY / sigma_SPY
corr_full = rets["r_VNQ"].corr(rets["r_SPY"])

# Subsample: COVID crash (2020-02-19 to 2020-03-23) vs post-COVID calm (2021-06-01 to 2021-12-31)
covid_mask = (rets.index >= "2020-02-19") & (rets.index <= "2020-03-23")
calm_mask = (rets.index >= "2021-06-01") & (rets.index <= "2021-12-31")
rate_hike_mask = (rets.index >= "2022-03-16") & (rets.index <= "2023-07-26")  # Fed hiking cycle

sub_stats = {}
for label, mask in [("COVID_crash", covid_mask), ("post_COVID_calm", calm_mask), ("Fed_hike_2022_23", rate_hike_mask)]:
    sub = rets[mask]
    if len(sub) < 10:
        continue
    sub_stats[label] = {
        "n": int(len(sub)),
        "start": str(sub.index.min().date()),
        "end": str(sub.index.max().date()),
        "ann_vol_VNQ_pct": float(sub["r_VNQ"].std() * np.sqrt(252)),
        "ann_vol_SPY_pct": float(sub["r_SPY"].std() * np.sqrt(252)),
        "mean_ret_VNQ_ann_pct": float(sub["r_VNQ"].mean() * 252),
        "mean_ret_SPY_ann_pct": float(sub["r_SPY"].mean() * 252),
        "corr_VNQ_SPY": float(sub["r_VNQ"].corr(sub["r_SPY"])),
    }

# HAR-RV OOS QLIKE for VNQ vs SPY (simple HAR: daily RV regressed on lagged 1d/5d/22d RV)
def daily_rv(series):
    """Absolute 2-week daily estimate: daily squared return as RV proxy (no intraday)."""
    return (series ** 2)  # percent^2


def har_rv_oos_qlike(r, train_end="2022-12-31"):
    """HAR-RV OOS one-step forecast, QLIKE loss against realized (r^2)."""
    rv = daily_rv(r).rename("rv")
    df = pd.DataFrame({"rv": rv})
    df["rv_d"] = df["rv"].shift(1)
    df["rv_w"] = df["rv"].shift(1).rolling(5).mean()
    df["rv_m"] = df["rv"].shift(1).rolling(22).mean()
    df = df.dropna()
    train = df.loc[:train_end]
    test = df.loc[train_end:].iloc[1:]
    X_tr = np.column_stack([np.ones(len(train)), train["rv_d"], train["rv_w"], train["rv_m"]])
    y_tr = train["rv"].values
    beta, *_ = np.linalg.lstsq(X_tr, y_tr, rcond=None)
    X_te = np.column_stack([np.ones(len(test)), test["rv_d"], test["rv_w"], test["rv_m"]])
    fcst = X_te @ beta
    fcst = np.clip(fcst, 1e-8, None)
    realized = test["rv"].values
    # QLIKE loss (Patton 2011): sigma2/fcst - log(sigma2/fcst) - 1
    ratio = np.clip(realized / fcst, 1e-8, None)
    qlike = (ratio - np.log(ratio) - 1).mean()
    rmse = float(np.sqrt(((realized - fcst) ** 2).mean()))
    return {"qlike": float(qlike), "rmse": rmse, "n_oos": int(len(test)), "beta": beta.tolist()}


har_VNQ = har_rv_oos_qlike(rets["r_VNQ"])
har_SPY = har_rv_oos_qlike(rets["r_SPY"])

# Diebold-Mariano test on squared-error loss (HAR-VNQ vs HAR-SPY)
# Using absolute-error time series; HLN correction for short OOS
def dm_test(loss_A, loss_B):
    d = loss_A - loss_B
    n = len(d)
    if n < 10:
        return None
    mean_d = d.mean()
    se = d.std(ddof=1) / np.sqrt(n)
    if se == 0:
        return None
    t = mean_d / se
    from scipy.stats import t as tdist
    p = 2 * (1 - tdist.cdf(abs(t), df=n - 1))
    return {"t": float(t), "p_value": float(p), "n": int(n)}


# Dump data for chart / inspection
rets.to_csv(OUT / "returns.csv")
rv.to_csv(OUT / "rv_22d.csv")
roll_corr.to_csv(OUT / "rolling_corr_63d.csv")


# Figure 1: VNQ vs SPY 22-day annualized vol time series
fig, ax = plt.subplots(figsize=(10, 5))
ann_vol_VNQ = np.sqrt(rv["rv_VNQ"] * 252)
ann_vol_SPY = np.sqrt(rv["rv_SPY"] * 252)
ax.plot(ann_vol_VNQ.index, ann_vol_VNQ, label="VNQ (REIT)", color="#c0392b", linewidth=1.2, alpha=0.85)
ax.plot(ann_vol_SPY.index, ann_vol_SPY, label="SPY (美股大盤)", color="#2c3e50", linewidth=1.2, alpha=0.85)
ax.axvspan(pd.Timestamp("2020-02-19"), pd.Timestamp("2020-03-23"), color="gray", alpha=0.15, label="COVID 崩跌")
ax.axvspan(pd.Timestamp("2022-03-16"), pd.Timestamp("2023-07-26"), color="orange", alpha=0.10, label="Fed 升息循環")
ax.set_title("VNQ (REIT) vs SPY 年化 22 日實現波動率", fontsize=13)
ax.set_ylabel("年化波動率 (%)")
ax.set_xlabel("日期")
ax.legend(loc="upper left", fontsize=9)
ax.grid(True, alpha=0.3)
fig.tight_layout()
fig.savefig(OUT / "fig_vnq_spy_rv.png", dpi=130, bbox_inches="tight")
plt.close(fig)
print("[info] saved fig_vnq_spy_rv.png")


# Figure 2: Rolling correlation VNQ-SPY 63-day
fig, ax = plt.subplots(figsize=(10, 4.5))
ax.plot(roll_corr.index, roll_corr.values, color="#27ae60", linewidth=1.3)
ax.axhline(corr_full, linestyle="--", color="#7f8c8d", label=f"全樣本平均 ρ={corr_full:.3f}")
ax.axvspan(pd.Timestamp("2020-02-19"), pd.Timestamp("2020-03-23"), color="gray", alpha=0.15, label="COVID 崩跌")
ax.axvspan(pd.Timestamp("2022-03-16"), pd.Timestamp("2023-07-26"), color="orange", alpha=0.10, label="Fed 升息循環")
ax.set_title("VNQ-SPY 63 日滾動相關係數（利率敏感度觀察）", fontsize=13)
ax.set_ylabel("滾動相關係數 ρ")
ax.set_xlabel("日期")
ax.set_ylim(0.2, 1.0)
ax.legend(loc="lower right", fontsize=9)
ax.grid(True, alpha=0.3)
fig.tight_layout()
fig.savefig(OUT / "fig_vnq_spy_corr.png", dpi=130, bbox_inches="tight")
plt.close(fig)
print("[info] saved fig_vnq_spy_corr.png")


results = {
    "meta": {
        "tickers": TICKERS,
        "period": f"{adj.index.min().date()} -> {adj.index.max().date()}",
        "n_obs": int(len(rets)),
        "data_source": "yfinance auto_adjust=False (data snapshot rule 2026-04-19)",
        "seed": 42,
        "created_at": pd.Timestamp.now(tz="Asia/Taipei").isoformat(),
    },
    "fullsample_stats": {
        "ann_ret_VNQ_pct": float(mu_VNQ),
        "ann_ret_SPY_pct": float(mu_SPY),
        "ann_vol_VNQ_pct": float(sigma_VNQ),
        "ann_vol_SPY_pct": float(sigma_SPY),
        "sharpe_VNQ_naive": float(sharpe_VNQ),
        "sharpe_SPY_naive": float(sharpe_SPY),
        "corr_VNQ_SPY_full": float(corr_full),
        "mean_rolling_corr_63d": float(roll_corr.mean()),
        "min_rolling_corr_63d": float(roll_corr.min()),
        "max_rolling_corr_63d": float(roll_corr.max()),
    },
    "subperiod_stats": sub_stats,
    "har_rv_oos": {
        "VNQ": har_VNQ,
        "SPY": har_SPY,
        "QLIKE_ratio_VNQ_over_SPY": har_VNQ["qlike"] / har_SPY["qlike"] if har_SPY["qlike"] > 0 else None,
    },
}

# DM test on HAR-RV squared errors (need per-day forecasts to compute pointwise loss)
# Re-compute for DM
def har_rv_per_point_qlike(r, train_end="2022-12-31"):
    rv = daily_rv(r).rename("rv")
    df = pd.DataFrame({"rv": rv})
    df["rv_d"] = df["rv"].shift(1)
    df["rv_w"] = df["rv"].shift(1).rolling(5).mean()
    df["rv_m"] = df["rv"].shift(1).rolling(22).mean()
    df = df.dropna()
    train = df.loc[:train_end]
    test = df.loc[train_end:].iloc[1:]
    X_tr = np.column_stack([np.ones(len(train)), train["rv_d"], train["rv_w"], train["rv_m"]])
    y_tr = train["rv"].values
    beta, *_ = np.linalg.lstsq(X_tr, y_tr, rcond=None)
    X_te = np.column_stack([np.ones(len(test)), test["rv_d"], test["rv_w"], test["rv_m"]])
    fcst = np.clip(X_te @ beta, 1e-8, None)
    realized = test["rv"].values
    ratio = np.clip(realized / fcst, 1e-8, None)
    qlike_per = ratio - np.log(ratio) - 1
    return pd.Series(qlike_per, index=test.index)


qlike_VNQ = har_rv_per_point_qlike(rets["r_VNQ"])
qlike_SPY = har_rv_per_point_qlike(rets["r_SPY"])
# Align
aligned = pd.concat([qlike_VNQ.rename("VNQ"), qlike_SPY.rename("SPY")], axis=1).dropna()
dm = dm_test(aligned["VNQ"].values, aligned["SPY"].values)
results["dm_test_qlike_VNQ_minus_SPY"] = dm
if dm:
    results["dm_interpretation"] = (
        "t>0 = VNQ QLIKE > SPY QLIKE（VNQ 預測較難）；"
        "|t|>1.96 視為統計顯著（p<0.05）"
    )

(OUT / "reit_vol_results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False))
print("[info] saved reit_vol_results.json")
print(json.dumps(results, indent=2, ensure_ascii=False))
