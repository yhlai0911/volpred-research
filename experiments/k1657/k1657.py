"""
k1657 — VRP (Variance Risk Premium) 交易時段 vs 隔夜分解（免付費代理版）

研究問題
--------
Q1 (描述): SPY 日盤段(open->close) vs 隔夜段(prev close->open) realized variance
           的相對大小、時變、佔比。
Q2 (VRP 分解): 免付費代理 VRP = 隱含變異數(VIX^2) - 已實現變異數(trailing 22d RV)。
           把 realized 拆成 day + overnight 兩成分，形成 day-VRP / overnight-VRP proxy
           (依 realized share 比例分配隱含變異數 — 這是明示的建模假設,VIX 本身不分時段定價)。
Q3 (可預測性,主 claim): day 成分 vs overnight 成分(以及 day-VRP vs on-VRP)對
           「未來 H 日 realized total variance」的預測內容是否不同?
           IN-SAMPLE 預測回歸 + HAC(Newey-West) SE 做係數差異推論;
           另加 OOS expanding-window 預測 + DM test(QLIKE) 做 OOS 驗證。

防錯 checklist
-------------
- Lookahead: 所有 predictor 都是 t 時點可觀測的 trailing 窗口(結束於 t);
  target fwd_RV 落在 [t+1, t+H],嚴格在 t 之後。
- OOS 嵌入(embargo): 在 origin i 預測 [i+1,i+H] 時,訓練列 j 的 label window 結束於 j+H,
  必須 j+H <= i  =>  j <= i-H。丟掉最後 H-1 列避免訓練尾端看到預測日之後的 return。
- 口徑一致: VIX^2/10000 = 年化 variance(decimal); RV 年化 = (252/22)*sum_22(r^2)。
  兩者皆年化 decimal variance。annualization factor = 252 (明示)。
- 每個 horizon H 的 HAC/DM inference lag = H(overlapping forward window => MA(H-1) 自相關),
  不同 H 不共用同一 lag。
- seed 固定 = 42(本實驗無隨機抽樣,但 block bootstrap CI 用到)。
- QLIKE 用 canonical 方向 actual/predicted (volpred.stats.model_evaluation.qlike_pointwise)。
  OOS 預測在 log-variance 空間做,exp 回來保證正值,避免 QLIKE 爆掉。

作者: VolPred 自主研究系統  |  seed=42
"""
from __future__ import annotations

import json
import os
import sys
import warnings
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from plot_style import apply_cjk_style  # noqa: E402

apply_cjk_style()

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np
import pandas as pd
import statsmodels.api as sm
import yfinance as yf

from volpred.stats.model_evaluation import qlike_pointwise

warnings.filterwarnings("ignore")

SEED = 42
np.random.seed(SEED)

HERE = os.path.dirname(os.path.abspath(__file__))
ANNUAL = 252
RV_WINDOW = 22  # 交易日,約當 VIX 的 30 日曆日 implied 窗口
HORIZONS = [5, 22, 66]  # 未來 H 日 realized total variance

START = "2004-01-01"
END = datetime.now().strftime("%Y-%m-%d")


# --------------------------------------------------------------------------
# 1. 抓資料 + 分解
# --------------------------------------------------------------------------
def fetch_ohlc(ticker: str, start: str = START, end: str = END) -> pd.DataFrame:
    df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    df = df[["Open", "High", "Low", "Close"]].dropna()
    df.index = pd.to_datetime(df.index)
    return df


def decompose(df: pd.DataFrame) -> pd.DataFrame:
    """把日 OHLC 分解成 overnight / day 收益與 variance proxy。"""
    out = pd.DataFrame(index=df.index)
    prev_close = df["Close"].shift(1)
    # overnight = ln(Open_t / Close_{t-1}); day = ln(Close_t / Open_t)
    out["r_on"] = np.log(df["Open"] / prev_close)
    out["r_day"] = np.log(df["Close"] / df["Open"])
    out["r_cc"] = np.log(df["Close"] / prev_close)  # = r_on + r_day (恆等)
    out["var_on"] = out["r_on"] ** 2
    out["var_day"] = out["r_day"] ** 2
    out["var_cc"] = out["r_cc"] ** 2
    # 交叉項: var_cc = var_on + var_day + 2*r_on*r_day
    out["cross"] = 2.0 * out["r_on"] * out["r_day"]
    return out.dropna()


def build_dataset(spy_ticker="SPY", vix_ticker="^VIX"):
    spy = fetch_ohlc(spy_ticker)
    dec = decompose(spy)
    vix = fetch_ohlc(vix_ticker)["Close"].rename("vix")
    df = dec.join(vix, how="inner").dropna()

    # trailing 22 日年化 realized variance(結束於 t,t 可觀測)
    scale = ANNUAL / RV_WINDOW
    df["rv_day"] = df["var_day"].rolling(RV_WINDOW).sum() * scale
    df["rv_on"] = df["var_on"].rolling(RV_WINDOW).sum() * scale
    df["rv_total"] = df["var_cc"].rolling(RV_WINDOW).sum() * scale
    # 用 var_on+var_day 的加總(忽略 cross)當作分時段可加版 total,供 share 計算
    df["rv_sum_components"] = (
        (df["var_day"] + df["var_on"]).rolling(RV_WINDOW).sum() * scale
    )
    # 隱含年化 variance(decimal)。VIX 為年化 vol 百分點 => (VIX/100)^2
    df["iv"] = (df["vix"] / 100.0) ** 2

    # VRP proxy(t 可觀測): implied - trailing realized
    df["vrp_total"] = df["iv"] - df["rv_total"]
    # 依 realized share 比例把 implied 分配到兩時段(明示假設)
    share_day = df["rv_day"] / df["rv_sum_components"]
    share_on = df["rv_on"] / df["rv_sum_components"]
    df["vrp_day"] = df["iv"] * share_day - df["rv_day"]
    df["vrp_on"] = df["iv"] * share_on - df["rv_on"]

    return df.dropna(), spy


# --------------------------------------------------------------------------
# 2. forward target
# --------------------------------------------------------------------------
def add_forward_targets(df: pd.DataFrame) -> pd.DataFrame:
    """fwd_rv_total_H = 年化 realized total variance over [t+1, t+H] (嚴格在 t 之後)。"""
    scale = ANNUAL  # 平均日 var * 252 = 年化
    v = df["var_cc"]
    for H in HORIZONS:
        # S_t = sum v[t+1..t+H] = rolling(H).sum() 在索引 t+H 的值 => shift(-H)。
        # rolling.sum() 在 m 涵蓋 v[m-H+1..m];取 m=t+H => v[t+1..t+H]。嚴格在 t 之後。
        fwd = v.rolling(H).sum().shift(-H)
        df[f"fwd_rv_{H}"] = fwd / H * scale
    return df


# --------------------------------------------------------------------------
# 3. IN-SAMPLE 預測回歸 + HAC
# --------------------------------------------------------------------------
def hac_regression(y, X_df, hac_lag, label):
    """OLS + HAC(Newey-West)。X_df 已 z-score 標準化。回傳 coef/t/p + 差異檢定。"""
    X = sm.add_constant(X_df)
    model = sm.OLS(y, X, missing="drop").fit(
        cov_type="HAC", cov_kwds={"maxlags": hac_lag}
    )
    res = {
        "label": label,
        "n": int(model.nobs),
        "r2": float(model.rsquared),
        "hac_lag": int(hac_lag),
        "coef": {k: float(v) for k, v in model.params.items()},
        "tstat": {k: float(v) for k, v in model.tvalues.items()},
        "pval": {k: float(v) for k, v in model.pvalues.items()},
    }
    return model, res


def zscore(s):
    return (s - s.mean()) / s.std(ddof=0)


def run_insample(df):
    results = {}
    for H in HORIZONS:
        tgt = f"fwd_rv_{H}"
        sub = df[
            [tgt, "rv_day", "rv_on", "rv_total", "vrp_total", "vrp_day", "vrp_on"]
        ].dropna()
        y = sub[tgt]
        hac = H  # inference horizon = target H

        # (1) 兩時段 realized 成分預測 future total
        Xa = pd.DataFrame(
            {"z_rv_day": zscore(sub["rv_day"]), "z_rv_on": zscore(sub["rv_on"])}
        )
        m1, r1 = hac_regression(y, Xa, hac, f"H{H}_rv_day_vs_rv_on")
        d1 = m1.t_test("z_rv_day - z_rv_on = 0")
        r1["diff_day_minus_on"] = {
            "estimate": float(np.ravel(d1.effect)[0]),
            "tstat": float(np.ravel(d1.tvalue)[0]),
            "pval": float(np.ravel(d1.pvalue)[0]),
        }

        # (2) aggregate VRP 是否在 RV 之上增加預測
        Xb = pd.DataFrame(
            {"z_rv_total": zscore(sub["rv_total"]), "z_vrp_total": zscore(sub["vrp_total"])}
        )
        _, r2 = hac_regression(y, Xb, hac, f"H{H}_rvtotal_plus_vrp")

        # (3) day-VRP vs on-VRP 預測內容差異(控制 RV 成分)
        Xc = pd.DataFrame(
            {
                "z_rv_day": zscore(sub["rv_day"]),
                "z_rv_on": zscore(sub["rv_on"]),
                "z_vrp_day": zscore(sub["vrp_day"]),
                "z_vrp_on": zscore(sub["vrp_on"]),
            }
        )
        m3, r3 = hac_regression(y, Xc, hac, f"H{H}_vrp_day_vs_vrp_on")
        d3 = m3.t_test("z_vrp_day - z_vrp_on = 0")
        r3["diff_vrpday_minus_vrpon"] = {
            "estimate": float(np.ravel(d3.effect)[0]),
            "tstat": float(np.ravel(d3.tvalue)[0]),
            "pval": float(np.ravel(d3.pvalue)[0]),
        }

        # (4) 單變量 R^2 比較
        uni = {}
        for name, col in [("vrp_day", "vrp_day"), ("vrp_on", "vrp_on")]:
            Xu = pd.DataFrame({f"z_{col}": zscore(sub[col])})
            _, ru = hac_regression(y, Xu, hac, f"H{H}_uni_{name}")
            uni[name] = {"r2": ru["r2"], "tstat": ru["tstat"], "pval": ru["pval"]}

        results[f"H{H}"] = {
            "reg1_rv_components": r1,
            "reg2_vrp_adds": r2,
            "reg3_vrp_components": r3,
            "reg4_univariate": uni,
        }
    return results


# --------------------------------------------------------------------------
# 4. OOS expanding-window 預測 + DM (QLIKE),含 embargo
# --------------------------------------------------------------------------
def run_oos(df, min_train=750):
    """
    在 log-variance 空間做 expanding OLS。origin i 預測 fwd_rv_H([i+1,i+H])。
    訓練列 j 需 j+H <= i (embargo H-1 列) 且 label 可得。
    baseline: log(rv_total);  full: + rv_day/rv_on/vrp_day/vrp_on。
    DM test(QLIKE) inference lag = H。
    """
    oos = {}
    feat_base = ["rv_total"]
    feat_full = ["rv_day", "rv_on", "vrp_day", "vrp_on"]
    for H in HORIZONS:
        tgt = f"fwd_rv_{H}"
        cols = list(set(feat_base + feat_full + [tgt]))
        sub = df[cols].copy()
        # 特徵取 log(正值);vrp 可負 => 用 signed-log transform 保留符號
        Xall = pd.DataFrame(index=sub.index)
        for c in feat_base + feat_full:
            v = sub[c].values.astype(float)
            if c.startswith("vrp"):
                Xall[c] = np.sign(v) * np.log1p(np.abs(v) * 1e4)  # signed log,scale-stable
            else:
                Xall[c] = np.log(np.maximum(v, 1e-10))
        ylog = np.log(np.maximum(sub[tgt].values.astype(float), 1e-12))
        y_actual = sub[tgt].values.astype(float)
        idx = sub.index

        n = len(sub)
        preds_base, preds_full, actuals, dates = [], [], [], []
        for i in range(min_train, n):
            # 最後可用訓練列: j <= i-H 且 label 非 NaN
            train_end = i - H
            if train_end < min_train // 2:
                continue
            tr = slice(0, train_end + 1)
            ytr = ylog[tr]
            mask = np.isfinite(ytr)
            if mask.sum() < min_train // 2:
                continue
            # baseline
            Xb = sm.add_constant(Xall[feat_base].values[tr])[mask]
            bb = np.linalg.lstsq(Xb, ytr[mask], rcond=None)[0]
            xb_i = np.concatenate([[1.0], Xall[feat_base].values[i]])
            pb = np.exp(xb_i @ bb)
            # full
            Xf = sm.add_constant(Xall[feat_base + feat_full].values[tr])[mask]
            bf = np.linalg.lstsq(Xf, ytr[mask], rcond=None)[0]
            xf_i = np.concatenate([[1.0], Xall[feat_base + feat_full].values[i]])
            pf = np.exp(xf_i @ bf)
            a = y_actual[i]
            if not np.isfinite(a) or a <= 0:
                continue
            preds_base.append(pb)
            preds_full.append(pf)
            actuals.append(a)
            dates.append(idx[i])

        actuals = np.array(actuals)
        preds_base = np.array(preds_base)
        preds_full = np.array(preds_full)
        if len(actuals) < 50:
            oos[f"H{H}"] = {"note": "insufficient OOS obs", "n": int(len(actuals))}
            continue

        q_base = qlike_pointwise(actuals, preds_base)
        q_full = qlike_pointwise(actuals, preds_full)
        d = q_base - q_full  # >0 => full 較優
        # DM test with HAC(Newey-West) lag=H, Harvey small-sample correction
        dm_stat, dm_p = dm_test(d, H)

        oos[f"H{H}"] = {
            "n_oos": int(len(actuals)),
            "oos_start": str(pd.Timestamp(dates[0]).date()),
            "oos_end": str(pd.Timestamp(dates[-1]).date()),
            "qlike_base": float(q_base.mean()),
            "qlike_full": float(q_full.mean()),
            "qlike_improve_pct": float((q_base.mean() - q_full.mean()) / abs(q_base.mean()) * 100),
            "dm_stat": float(dm_stat),
            "dm_pval": float(dm_p),
            "dm_lag": int(H),
            "verdict_full_better": bool(dm_stat > 3.0),  # Harvey(2016) |t|>3
        }
    return oos


def dm_test(d, h):
    """Diebold-Mariano on loss differential d,HAC var lag=h,Harvey(1997) correction。"""
    from scipy import stats

    d = np.asarray(d, dtype=float)
    n = len(d)
    dbar = d.mean()
    # Newey-West long-run variance
    gamma0 = np.mean((d - dbar) ** 2)
    lrv = gamma0
    for lag in range(1, h + 1):
        w = 1.0 - lag / (h + 1)
        cov = np.mean((d[lag:] - dbar) * (d[:-lag] - dbar))
        lrv += 2.0 * w * cov
    lrv = max(lrv, 1e-20)
    dm = dbar / np.sqrt(lrv / n)
    # Harvey, Leybourne & Newbold (1997) small-sample correction
    corr = np.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    dm_adj = dm * corr
    p = 2 * (1 - stats.t.cdf(abs(dm_adj), df=n - 1))
    return dm_adj, p


# --------------------------------------------------------------------------
# 5. 描述統計 (Q1) + block bootstrap CI on share
# --------------------------------------------------------------------------
def describe(df, dec_full):
    d = dec_full
    tot = d["var_day"] + d["var_on"]
    share_on = d["var_on"] / tot.replace(0, np.nan)
    desc = {
        "n_days": int(len(d)),
        "period": [str(d.index[0].date()), str(d.index[-1].date())],
        "mean_var_day": float(d["var_day"].mean()),
        "mean_var_on": float(d["var_on"].mean()),
        "mean_var_cc": float(d["var_cc"].mean()),
        "mean_cross_term": float(d["cross"].mean()),
        "cross_pct_of_cc": float(d["cross"].mean() / d["var_cc"].mean() * 100),
        # aggregate share (mean var_on / mean total)
        "overnight_share_aggregate": float(
            d["var_on"].mean() / (d["var_day"].mean() + d["var_on"].mean())
        ),
        # daily-ratio mean (每日先算比例再平均)
        "overnight_share_daily_mean": float(share_on.mean()),
        "overnight_share_daily_median": float(share_on.median()),
        "corr_day_on": float(d["var_day"].corr(d["var_on"])),
        "corr_r_day_r_on": float(d["r_day"].corr(d["r_on"])),
    }
    # block bootstrap CI for aggregate overnight share (seed=42, 2000 reps, block=22)
    rng = np.random.default_rng(SEED)
    von = d["var_on"].values
    vday = d["var_day"].values
    n = len(von)
    block = RV_WINDOW
    nblocks = n // block
    reps = 2000
    shares = np.empty(reps)
    for r in range(reps):
        starts = rng.integers(0, n - block, size=nblocks)
        idx = (starts[:, None] + np.arange(block)[None, :]).ravel()
        so = von[idx].mean()
        sd = vday[idx].mean()
        shares[r] = so / (so + sd)
    desc["overnight_share_ci95"] = [
        float(np.percentile(shares, 2.5)),
        float(np.percentile(shares, 97.5)),
    ]
    # 逐年 share
    yearly = {}
    dd = d.copy()
    dd["yr"] = dd.index.year
    for yr, g in dd.groupby("yr"):
        yearly[int(yr)] = float(
            g["var_on"].mean() / (g["var_day"].mean() + g["var_on"].mean())
        )
    desc["overnight_share_by_year"] = yearly
    return desc, share_on


# --------------------------------------------------------------------------
# 6. TWN 次要(短窗,描述性,禁正式顯著性)
# --------------------------------------------------------------------------
def run_twn():
    try:
        from volpred.utils import clean_tw50_data
    except Exception:
        clean_tw50_data = None
    vpath = os.path.join(HERE, "..", "..", "data", "vixtwn", "vixtwn_daily.csv")
    if not os.path.exists(vpath):
        return {"note": "vixtwn data not found"}
    vt = pd.read_csv(vpath, parse_dates=["date"]).set_index("date")
    start = (vt.index[0] - pd.Timedelta(days=10)).strftime("%Y-%m-%d")
    tw = fetch_ohlc("0050.TW", start=start, end=END)
    if len(tw) < 10:
        return {"note": "0050.TW fetch failed"}
    # 此窗口(2025-12+)整段在 2025-06 拆分之後 => 無 split artifact;
    # 仍走 clean_tw50_data 檢查 Close(對此窗口為 no-op)。
    if clean_tw50_data is not None:
        cp, _ = clean_tw50_data(tw["Close"])
        # 若被調整(理論上不會),同比例校正 OHLC
        ratio = (cp / tw["Close"]).reindex(tw.index).fillna(1.0)
        for c in ["Open", "High", "Low", "Close"]:
            tw[c] = tw[c] * ratio
    dec = decompose(tw)
    df = dec.join(vt["vixtwn_close"].rename("vix"), how="inner").dropna()
    if len(df) < 20:
        return {"note": "insufficient overlap", "n": int(len(df))}
    df["iv"] = (df["vix"] / 100.0) ** 2
    tot = df["var_day"] + df["var_on"]
    share_on = (df["var_on"] / tot).mean()
    # 短窗 VRP total (trailing 22d 若不足則用可得窗口,標明)
    w = min(RV_WINDOW, max(5, len(df) // 3))
    scale = ANNUAL / w
    rv_total = df["var_cc"].rolling(w).sum() * scale
    vrp_total = (df["iv"] - rv_total).dropna()
    return {
        "WARNING": "TWN 樣本 N 遠小於 500,僅供 forward-looking 描述觀察,禁任何正式顯著性結論",
        "n_days": int(len(df)),
        "period": [str(df.index[0].date()), str(df.index[-1].date())],
        "rv_window_used": int(w),
        "overnight_share_daily_mean": float(share_on),
        "mean_var_day": float(df["var_day"].mean()),
        "mean_var_on": float(df["var_on"].mean()),
        "mean_vrp_total_proxy": float(vrp_total.mean()) if len(vrp_total) else None,
        "vrp_positive_frac": float((vrp_total > 0).mean()) if len(vrp_total) else None,
    }


# --------------------------------------------------------------------------
# 7. 圖
# --------------------------------------------------------------------------
def make_plots(df, dec_full, share_on_series, desc):
    # (a) overnight share 時序 (rolling 63d)
    tot = dec_full["var_day"] + dec_full["var_on"]
    roll_share = (
        dec_full["var_on"].rolling(63).sum() / tot.rolling(63).sum()
    )
    fig, ax = plt.subplots(figsize=(11, 4.5))
    ax.plot(roll_share.index, roll_share.values, lw=0.8, color="#c0392b")
    ax.axhline(desc["overnight_share_aggregate"], ls="--", color="k", lw=1,
               label=f"全期聚合佔比 {desc['overnight_share_aggregate']:.1%}")
    ax.set_title("SPY 隔夜段 variance 佔總日內+隔夜之比 (63日滾動)  2004-2026")
    ax.set_ylabel("overnight share")
    ax.set_ylim(0, 1)
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "fig_a_overnight_share.png"), dpi=130)
    plt.close(fig)

    # (b) day-VRP vs on-VRP 時序 (annualized vol-point 尺度更直觀: 用 variance*100)
    fig, ax = plt.subplots(figsize=(11, 4.5))
    ax.plot(df.index, df["vrp_day"] * 100, lw=0.7, label="day-VRP proxy", color="#2c3e50")
    ax.plot(df.index, df["vrp_on"] * 100, lw=0.7, label="overnight-VRP proxy", color="#e67e22")
    ax.axhline(0, color="k", lw=0.6)
    ax.set_title("SPY day-VRP vs overnight-VRP proxy 時序 (年化 variance ×100)")
    ax.set_ylabel("VRP proxy (×100)")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "fig_b_vrp_components.png"), dpi=130)
    plt.close(fig)

    # (c) VRP 成分分布
    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.hist(df["vrp_day"] * 100, bins=80, alpha=0.55, label="day-VRP", color="#2c3e50", density=True)
    ax.hist(df["vrp_on"] * 100, bins=80, alpha=0.55, label="overnight-VRP", color="#e67e22", density=True)
    ax.axvline(0, color="k", lw=0.8)
    ax.set_title("day-VRP vs overnight-VRP proxy 分布 (年化 variance ×100)")
    ax.set_xlabel("VRP proxy (×100)")
    ax.set_ylabel("density")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "fig_c_vrp_dist.png"), dpi=130)
    plt.close(fig)


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def atomic_write_json(obj, path):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False, default=str)
    with open(tmp) as f:
        json.load(f)  # validate parseable
    os.replace(tmp, path)


def main():
    print("[k1657] fetching + decomposing ...")
    df, spy = build_dataset()
    dec_full = decompose(spy)  # 全期(不受 VIX join 縮短)供 Q1 描述
    df = add_forward_targets(df)

    print("[k1657] Q1 describe ...")
    desc, share_on_series = describe(df, dec_full)

    print("[k1657] Q3 in-sample HAC regressions ...")
    insample = run_insample(df)

    print("[k1657] Q3 OOS DM ...")
    oos = run_oos(df)

    print("[k1657] TWN secondary ...")
    twn = run_twn()

    print("[k1657] plots ...")
    make_plots(df, dec_full, share_on_series, desc)

    # Q2 summary
    q2 = {
        "mean_iv_annualized_var": float(df["iv"].mean()),
        "mean_rv_total_annualized_var": float(df["rv_total"].mean()),
        "mean_vrp_total": float(df["vrp_total"].mean()),
        "mean_vrp_day": float(df["vrp_day"].mean()),
        "mean_vrp_on": float(df["vrp_on"].mean()),
        "vrp_total_positive_frac": float((df["vrp_total"] > 0).mean()),
        "vrp_day_positive_frac": float((df["vrp_day"] > 0).mean()),
        "vrp_on_positive_frac": float((df["vrp_on"] > 0).mean()),
        "note": (
            "day-VRP/on-VRP 依 realized share 分配 implied,故兩者同號且量級比 = "
            "rv_day/rv_on。此為明示建模假設,VIX 不分時段定價。"
        ),
    }

    results = {
        "experiment_id": "k1657",
        "title": "VRP 交易時段 vs 隔夜分解(免付費代理版)",
        "run_at": datetime.now().isoformat(),
        "seed": SEED,
        "data": {
            "spy_ticker": "SPY",
            "vix_ticker": "^VIX",
            "period_full_decompose": desc["period"],
            "n_full_decompose": desc["n_days"],
            "n_with_vix_and_targets": int(len(df.dropna(subset=[f"fwd_rv_{HORIZONS[0]}"]))),
            "rv_window_trading_days": RV_WINDOW,
            "annualization_factor": ANNUAL,
            "horizons": HORIZONS,
            "source": "yfinance daily OHLC (SPY, ^VIX)",
        },
        "Q1_descriptive": desc,
        "Q2_vrp_decomposition": q2,
        "Q3_insample_hac": insample,
        "Q3_oos_dm": oos,
        "TWN_secondary": twn,
        "guards": {
            "lookahead": "predictors trailing(end at t); targets [t+1,t+H]; OOS embargo j<=i-H",
            "vix_alignment": "IV=(VIX/100)^2 annualized var; RV=(252/22)*sum22(r^2) annualized var",
            "hac_dm_horizon": "each H uses HAC/DM lag=H (no shared horizon)",
            "seed": SEED,
            "qlike": "canonical actual/predicted via volpred.stats.model_evaluation",
        },
    }
    atomic_write_json(results, os.path.join(HERE, "k1657_results.json"))
    print("[k1657] done. results + 3 figs written.")

    # 精簡 stdout 摘要
    print("\n=== SUMMARY ===")
    print(f"Q1 overnight share (agg) = {desc['overnight_share_aggregate']:.1%} "
          f"CI95 {desc['overnight_share_ci95']}")
    print(f"   corr(var_day,var_on) = {desc['corr_day_on']:.3f}")
    print(f"Q2 mean VRP_total = {q2['mean_vrp_total']:.5f}, "
          f"day = {q2['mean_vrp_day']:.5f}, on = {q2['mean_vrp_on']:.5f}")
    for H in HORIZONS:
        r1 = insample[f"H{H}"]["reg1_rv_components"]["diff_day_minus_on"]
        r3 = insample[f"H{H}"]["reg3_vrp_components"]["diff_vrpday_minus_vrpon"]
        o = oos[f"H{H}"]
        print(f"H{H}: rv_day-rv_on diff t={r1['tstat']:.2f} p={r1['pval']:.3f} | "
              f"vrp_day-vrp_on diff t={r3['tstat']:.2f} p={r3['pval']:.3f} | "
              f"OOS DM t={o.get('dm_stat', float('nan')):.2f} "
              f"full_better={o.get('verdict_full_better')}")


if __name__ == "__main__":
    main()
