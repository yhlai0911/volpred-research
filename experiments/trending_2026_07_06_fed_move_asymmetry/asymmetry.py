"""
trending_2026_07_06_fed_move_asymmetry

主題：美債隱含波動率（MOVE）對利率「上行 vs 下行」的非對稱反應。
角度差異化：不是 6/12 的 MOVE/VIX 跨資產比值，也不是 6/22 的 MOVE-VIX 滾動相關，
而是「higher-for-longer regime 下，債市波動率定價是否對利率上行 shock 更敏感」。

資料：Yahoo Finance ^MOVE（ICE BofA MOVE Index）、^TNX（CBOE 10Y Treasury yield ×10）。
方法：
  1. 同日條件化：以 10Y 殖利率日變動方向分組，比較當日 MOVE 日變動百分比（Welch t-test）。
  2. 殖利率半變異數非對稱（realized semivariance ratio）。
  3. 滾動 90 日條件均值差，看非對稱是否為近期 regime 特徵。

注意：這是「同期描述性」統計（contemporaneous），非可交易預測訊號 — 不做 lag，
明確標示為 descriptive；不宣稱 forecast。seed 固定（bootstrap CI）。
"""
import json
import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from pathlib import Path

SEED = 20260706
np.random.seed(SEED)
OUT = Path(__file__).parent

START = "2010-01-01"


def fetch():
    move = yf.download("^MOVE", start=START, progress=False, auto_adjust=True)["Close"]
    tnx = yf.download("^TNX", start=START, progress=False, auto_adjust=True)["Close"]
    df = pd.concat([move, tnx], axis=1)
    df.columns = ["MOVE", "TNX"]
    df = df.dropna()
    return df


def main():
    df = fetch()
    df["move_ret"] = df["MOVE"].pct_change() * 100.0        # MOVE 日變動 %
    df["yld_chg_bp"] = df["TNX"].diff() * 10.0              # 10Y 殖利率日變動 (TNX 已 ×10 → diff×10 = bp)
    d = df.dropna().copy()

    up = d[d["yld_chg_bp"] > 0]     # 殖利率上行日
    dn = d[d["yld_chg_bp"] < 0]     # 殖利率下行日

    mean_up = up["move_ret"].mean()
    mean_dn = dn["move_ret"].mean()
    # 用絕對殖利率變動控制 magnitude：非對稱 = 同樣 |Δy| 下 MOVE 反應差
    # beta_up / beta_dn：MOVE_ret 對 |yld_chg_bp| 的斜率，分別在上行/下行日
    def slope(g):
        x = g["yld_chg_bp"].abs().values
        y = g["move_ret"].values
        b = np.polyfit(x, y, 1)
        return float(b[0]), float(b[1])
    beta_up, a_up = slope(up)
    beta_dn, a_dn = slope(dn)

    # Welch t-test：上行日 vs 下行日的 MOVE 日變動
    t, p = stats.ttest_ind(up["move_ret"], dn["move_ret"], equal_var=False)

    # 殖利率半變異數非對稱（realized semivariance ratio, 全期）
    y = d["yld_chg_bp"].values
    rs_up = np.sum(np.square(y[y > 0]))
    rs_dn = np.sum(np.square(y[y < 0]))
    semivar_ratio = float(rs_up / rs_dn)

    # bootstrap 95% CI for (mean_up - mean_dn)
    diffs = []
    ua = up["move_ret"].values
    da = dn["move_ret"].values
    for _ in range(5000):
        diffs.append(np.random.choice(ua, len(ua), replace=True).mean()
                     - np.random.choice(da, len(da), replace=True).mean())
    ci = [float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))]

    # 近 90 日 regime：條件均值差
    recent = d.tail(90)
    r_up = recent[recent["yld_chg_bp"] > 0]["move_ret"].mean()
    r_dn = recent[recent["yld_chg_bp"] < 0]["move_ret"].mean()

    latest = d.iloc[-1]
    results = {
        "experiment_id": "trending_2026_07_06_fed_move_asymmetry",
        "seed": SEED,
        "data_source": "Yahoo Finance ^MOVE, ^TNX",
        "sample_period": [str(d.index[0].date()), str(d.index[-1].date())],
        "n_obs": int(len(d)),
        "n_yield_up_days": int(len(up)),
        "n_yield_down_days": int(len(dn)),
        "latest": {
            "date": str(d.index[-1].date()),
            "MOVE": round(float(latest["MOVE"]), 2),
            "TNX_yield_pct": round(float(latest["TNX"]), 3),
        },
        "conditional_move_response": {
            "mean_move_ret_on_yield_up_pct": round(mean_up, 4),
            "mean_move_ret_on_yield_down_pct": round(mean_dn, 4),
            "difference_pp": round(mean_up - mean_dn, 4),
            "bootstrap_95ci": [round(ci[0], 4), round(ci[1], 4)],
            "welch_t": round(float(t), 3),
            "welch_p": float(f"{p:.3e}"),
        },
        "magnitude_controlled_slope": {
            "beta_move_per_bp_yield_up": round(beta_up, 4),
            "beta_move_per_bp_yield_down": round(beta_dn, 4),
            "slope_ratio_up_over_down": round(beta_up / beta_dn, 3) if beta_dn else None,
        },
        "yield_realized_semivariance": {
            "up_semivar_bp2": round(rs_up, 1),
            "down_semivar_bp2": round(rs_dn, 1),
            "up_over_down_ratio": round(semivar_ratio, 4),
        },
        "recent_90d_regime": {
            "mean_move_ret_on_yield_up_pct": round(float(r_up), 4),
            "mean_move_ret_on_yield_down_pct": round(float(r_dn), 4),
            "difference_pp": round(float(r_up - r_dn), 4),
        },
        "interpretation_note": "Contemporaneous descriptive statistic (same-day MOVE change conditioned on same-day yield direction). NOT a lagged/tradeable forecast signal.",
    }

    with open(OUT / "results.json", "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    # 圖：條件均值 bar + 近90日對照
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    for fp in ["/System/Library/Fonts/PingFang.ttc",
               "/System/Library/Fonts/STHeiti Medium.ttc",
               "/Library/Fonts/Arial Unicode.ttf"]:
        if Path(fp).exists():
            font_manager.fontManager.addfont(fp)
            plt.rcParams["font.family"] = font_manager.FontProperties(fname=fp).get_name()
            break
    plt.rcParams["axes.unicode_minus"] = False
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    ax = axes[0]
    bars = ax.bar(["殖利率上行日", "殖利率下行日"], [mean_up, mean_dn],
                  color=["#c0392b", "#2980b9"])
    ax.axhline(0, color="#333", lw=0.8)
    ax.set_title(f"MOVE 當日平均變動（全期 {d.index[0].year}–{d.index[-1].year}）")
    ax.set_ylabel("MOVE 日變動 (%)")
    for b, v in zip(bars, [mean_up, mean_dn]):
        ax.text(b.get_x()+b.get_width()/2, v, f"{v:+.3f}%",
                ha="center", va="bottom" if v >= 0 else "top", fontsize=10)

    ax2 = axes[1]
    b2 = ax2.bar(["上行日", "下行日"], [r_up, r_dn], color=["#c0392b", "#2980b9"])
    ax2.axhline(0, color="#333", lw=0.8)
    ax2.set_title("近 90 交易日")
    ax2.set_ylabel("MOVE 日變動 (%)")
    for b, v in zip(b2, [r_up, r_dn]):
        ax2.text(b.get_x()+b.get_width()/2, v, f"{v:+.3f}%",
                 ha="center", va="bottom" if v >= 0 else "top", fontsize=10)
    plt.tight_layout()
    fig.savefig(OUT / "fig_move_asymmetry.png", dpi=130)

    # 第二張圖：magnitude-controlled 斜率（同 bp 不同反應）
    fig2, ax3 = plt.subplots(figsize=(7.2, 5))
    for g, col, lab, beta, a in [(up, "#c0392b", "殖利率上行日", beta_up, a_up),
                                 (dn, "#2980b9", "殖利率下行日", beta_dn, a_dn)]:
        x = g["yld_chg_bp"].abs().values
        y = g["move_ret"].values
        ax3.scatter(x, y, s=5, alpha=0.12, color=col)
        xs = np.linspace(0, np.percentile(x, 99), 50)
        ax3.plot(xs, beta * xs + a, color=col, lw=2.5,
                 label=f"{lab}：每 bp {beta:.2f}%")
    ax3.set_xlim(0, np.percentile(d["yld_chg_bp"].abs(), 99))
    ax3.set_ylim(-6, 8)
    ax3.axhline(0, color="#333", lw=0.6)
    ax3.set_xlabel("10 年期殖利率當日變動幅度（絕對值，bp）")
    ax3.set_ylabel("MOVE 當日變動 (%)")
    ax3.set_title("同樣的利率變動幅度，MOVE 對「往上」反應較大")
    ax3.legend(loc="upper left")
    plt.tight_layout()
    fig2.savefig(OUT / "fig_slope_asymmetry.png", dpi=130)

    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
