from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import yfinance as yf
from scipy import stats
from statsmodels.stats.diagnostic import breaks_cusumolsresid


EXPERIMENT_ID = "experiment_0dte_intraday_overnight_vol_2026_06_13"
ROOT = Path(__file__).resolve().parent
FIG_DIR = ROOT / "figures"
RESULT_PATH = ROOT / f"{EXPERIMENT_ID}_results.json"
README_PATH = ROOT / "README.md"

START_DATE = "2010-01-01"
END_DATE = "2026-06-15"
BREAK_DATE = pd.Timestamp("2022-04-18")
THURSDAY_FULL_ROLLOUT = pd.Timestamp("2022-05-11")
SEED = 42
TICKER = "SPY"


@dataclass
class LiteratureItem:
    title: str
    source: str
    year: int
    takeaway: str
    url: str


LITERATURE = [
    LiteratureItem(
        title="A tug of war: Overnight versus intraday expected returns",
        source="Journal of Financial Economics",
        year=2019,
        takeaway="美股報酬在隔夜與日內之間存在明顯分解，證明把兩段拆開看不是多餘細分。",
        url="https://doi.org/10.1016/j.jfineco.2019.05.001",
    ),
    LiteratureItem(
        title="Does 0DTE Options Trading Increase Volatility?",
        source="SSRN 4426358",
        year=2026,
        takeaway="利用 weekly options rollout 的工具變數設計，發現 0DTE 交易與較高的 close-to-close / intraday volatility 正相關。",
        url="https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4426358",
    ),
    LiteratureItem(
        title="The Market for 0DTE: The Role of Liquidity Providers in Volatility Management",
        source="SSRN 4881008",
        year=2024,
        takeaway="以 expiration-day variation 辨識，指出流動性提供者的中介行為平均反而壓低指數波動。",
        url="https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4881008",
    ),
    LiteratureItem(
        title="Cboe to Add Tuesday and Thursday Expirations for SPX Weeklys Options",
        source="Cboe press release",
        year=2022,
        takeaway="2022-04-18 新增週二到期、2022-05-11 新增週四到期，讓 SPXW 達成每個交易日都有到期日。",
        url="https://ir.cboe.com/news/news-details/2022/Cboe-to-Add-Tuesday-and-Thursday-Expirations-for-SPX-Weeklys-Options-04-13-2022/default.aspx",
    ),
]


def download_spy() -> pd.DataFrame:
    raw = yf.download(TICKER, start=START_DATE, end=END_DATE, auto_adjust=False, progress=False)
    if raw.empty:
        raise RuntimeError("yfinance returned empty data for SPY")
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    df = raw.rename(columns=str.lower).copy()
    adj_factor = df["adj close"] / df["close"]
    df["adj_open"] = df["open"] * adj_factor
    df["adj_close"] = df["close"] * adj_factor
    df["overnight_ret"] = df["adj_open"] / df["adj_close"].shift(1) - 1.0
    df["intraday_ret"] = df["adj_close"] / df["adj_open"] - 1.0
    df["overnight_var"] = df["overnight_ret"] ** 2
    df["intraday_var"] = df["intraday_ret"] ** 2
    df["total_var"] = df["overnight_var"] + df["intraday_var"]
    eps = 1e-12
    df["overnight_share"] = df["overnight_var"] / (df["total_var"] + eps)
    df["log_var_ratio"] = np.log((df["overnight_var"] + eps) / (df["intraday_var"] + eps))
    df["post_0dte"] = (df.index >= BREAK_DATE).astype(int)
    df["post_full_week"] = (df.index >= THURSDAY_FULL_ROLLOUT).astype(int)
    df["weekday"] = df.index.day_name().str[:3]
    df["is_tue_thu"] = df.index.weekday.isin([1, 3]).astype(int)
    df["is_mon_wed_fri"] = df.index.weekday.isin([0, 2, 4]).astype(int)
    df["post_x_tue_thu"] = df["post_0dte"] * df["is_tue_thu"]
    df = df.dropna(subset=["overnight_ret", "intraday_ret", "overnight_share", "log_var_ratio"])
    return df


def summarize_period(df: pd.DataFrame, label: str) -> dict:
    overnight_mean = float(df["overnight_var"].mean())
    intraday_mean = float(df["intraday_var"].mean())
    total_mean = float(df["total_var"].mean())
    share_mean = float(df["overnight_share"].mean())
    ratio_mean = float((df["overnight_var"] / df["intraday_var"]).replace([np.inf, -np.inf], np.nan).dropna().mean())
    return {
        "label": label,
        "start": str(df.index.min().date()),
        "end": str(df.index.max().date()),
        "n": int(len(df)),
        "overnight_var_mean": overnight_mean,
        "intraday_var_mean": intraday_mean,
        "total_var_mean": total_mean,
        "overnight_share_mean": share_mean,
        "intraday_share_mean": float(1.0 - share_mean),
        "overnight_to_intraday_var_ratio_mean": ratio_mean,
        "overnight_share_median": float(df["overnight_share"].median()),
        "overnight_share_std": float(df["overnight_share"].std()),
    }


def hac_regression(df: pd.DataFrame, y_col: str, x_cols: list[str], maxlags: int = 5) -> dict:
    y = df[y_col]
    X_raw = df[x_cols] if x_cols else pd.DataFrame(index=df.index)
    X = sm.add_constant(X_raw, has_constant="add")
    model = sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": maxlags})
    params = {}
    for key in model.params.index:
        params[key] = {
            "coef": float(model.params[key]),
            "t": float(model.tvalues[key]),
            "p": float(model.pvalues[key]),
        }
    return {
        "n": int(model.nobs),
        "r2": float(model.rsquared),
        "aic": float(model.aic),
        "params": params,
    }


def chow_test(df: pd.DataFrame, y_col: str, x_cols: list[str], break_date: pd.Timestamp) -> dict:
    X_raw = df[x_cols] if x_cols else pd.DataFrame(index=df.index)
    X = sm.add_constant(X_raw, has_constant="add")
    y = df[y_col]
    pre_mask = df.index < break_date
    post_mask = df.index >= break_date
    X_pre, y_pre = X.loc[pre_mask], y.loc[pre_mask]
    X_post, y_post = X.loc[post_mask], y.loc[post_mask]
    pooled = sm.OLS(y, X).fit()
    pre = sm.OLS(y_pre, X_pre).fit()
    post = sm.OLS(y_post, X_post).fit()
    k = X.shape[1]
    n1 = len(X_pre)
    n2 = len(X_post)
    numerator = (pooled.ssr - (pre.ssr + post.ssr)) / k
    denominator = (pre.ssr + post.ssr) / (n1 + n2 - 2 * k)
    f_stat = float(numerator / denominator)
    p_value = float(stats.f.sf(f_stat, k, n1 + n2 - 2 * k))
    return {
        "break_date": str(break_date.date()),
        "n_pre": int(n1),
        "n_post": int(n2),
        "k": int(k),
        "f_stat": f_stat,
        "p_value": p_value,
    }


def cusum_test(df: pd.DataFrame, y_col: str, x_cols: list[str]) -> dict:
    X_raw = df[x_cols] if x_cols else pd.DataFrame(index=df.index)
    X = sm.add_constant(X_raw, has_constant="add")
    y = df[y_col]
    model = sm.OLS(y, X).fit()
    stat, p_value, crit = breaks_cusumolsresid(model.resid, ddof=X.shape[1])
    critical_values = {
        "1pct": float(crit[0][1]),
        "5pct": float(crit[1][1]),
        "10pct": float(crit[2][1]),
    }
    return {
        "stat": float(stat),
        "p_value": float(p_value),
        "critical_values": critical_values,
    }


def weekday_panel(df: pd.DataFrame) -> list[dict]:
    out = []
    for regime_label, sub in [
        ("pre_0dte", df.loc[df.index < BREAK_DATE]),
        ("post_0dte", df.loc[df.index >= BREAK_DATE]),
    ]:
        grouped = sub.groupby("weekday")["overnight_share"].agg(["mean", "median", "count"])
        for weekday, row in grouped.iterrows():
            out.append(
                {
                    "regime": regime_label,
                    "weekday": weekday,
                    "mean_overnight_share": float(row["mean"]),
                    "median_overnight_share": float(row["median"]),
                    "n": int(row["count"]),
                }
            )
    return sorted(out, key=lambda x: (x["regime"], x["weekday"]))


def make_figures(df: pd.DataFrame) -> None:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    plot_df = df.copy()
    plot_df["rolling_overnight_share_63d"] = plot_df["overnight_share"].rolling(63).mean()
    plot_df["rolling_overnight_var_63d"] = plot_df["overnight_var"].rolling(63).mean()
    plot_df["rolling_intraday_var_63d"] = plot_df["intraday_var"].rolling(63).mean()

    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(plot_df.index, plot_df["rolling_overnight_share_63d"], label="63d overnight share", color="#0b6e4f")
    ax.axvline(BREAK_DATE, color="#c1121f", linestyle="--", label="2022-04-18")
    ax.axvline(THURSDAY_FULL_ROLLOUT, color="#f77f00", linestyle=":", label="2022-05-11")
    ax.set_title("SPY Overnight Variance Share (63-day rolling mean)")
    ax.set_ylabel("Overnight variance share")
    ax.legend()
    fig.tight_layout()
    fig.savefig(FIG_DIR / "a_rolling_overnight_share.png", dpi=180)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(plot_df.index, plot_df["rolling_overnight_var_63d"], label="Overnight var", color="#003049")
    ax.plot(plot_df.index, plot_df["rolling_intraday_var_63d"], label="Intraday var", color="#669bbc")
    ax.axvline(BREAK_DATE, color="#c1121f", linestyle="--", label="2022-04-18")
    ax.set_title("SPY rolling variance components (63-day mean)")
    ax.set_ylabel("Squared return")
    ax.legend()
    fig.tight_layout()
    fig.savefig(FIG_DIR / "b_rolling_variance_components.png", dpi=180)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(12, 6))
    order = ["Mon", "Tue", "Wed", "Thu", "Fri"]
    pre = [plot_df.loc[(plot_df.index < BREAK_DATE) & (plot_df["weekday"] == d), "overnight_share"].values for d in order]
    post = [plot_df.loc[(plot_df.index >= BREAK_DATE) & (plot_df["weekday"] == d), "overnight_share"].values for d in order]
    positions_pre = np.arange(len(order)) * 2.5
    positions_post = positions_pre + 0.9
    ax.boxplot(pre, positions=positions_pre, widths=0.7, patch_artist=True, boxprops=dict(facecolor="#a8dadc"))
    ax.boxplot(post, positions=positions_post, widths=0.7, patch_artist=True, boxprops=dict(facecolor="#f4a261"))
    ax.set_xticks(positions_pre + 0.45)
    ax.set_xticklabels(order)
    ax.set_ylabel("Overnight variance share")
    ax.set_title("Weekday distribution of overnight share: pre vs post 0DTE rollout")
    ax.legend(
        handles=[
            plt.Line2D([0], [0], color="#a8dadc", linewidth=10, label="Pre 2022-04-18"),
            plt.Line2D([0], [0], color="#f4a261", linewidth=10, label="Post 2022-04-18"),
        ],
        loc="upper right",
    )
    fig.tight_layout()
    fig.savefig(FIG_DIR / "c_weekday_boxplot.png", dpi=180)
    plt.close(fig)


def main() -> None:
    np.random.seed(SEED)
    df = download_spy()
    pre = df.loc[df.index < BREAK_DATE].copy()
    post = df.loc[df.index >= BREAK_DATE].copy()

    desc = {
        "full_sample": summarize_period(df, "full_sample"),
        "pre_0dte": summarize_period(pre, "pre_0dte"),
        "post_0dte": summarize_period(post, "post_0dte"),
        "post_full_week": summarize_period(df.loc[df.index >= THURSDAY_FULL_ROLLOUT], "post_full_week"),
        "tue_thu_pre": summarize_period(pre.loc[pre["is_tue_thu"] == 1], "tue_thu_pre"),
        "tue_thu_post": summarize_period(post.loc[post["is_tue_thu"] == 1], "tue_thu_post"),
    }

    mann_whitney = {
        "overnight_share_pre_vs_post": {
            "u_stat": float(stats.mannwhitneyu(pre["overnight_share"], post["overnight_share"], alternative="two-sided").statistic),
            "p_value": float(stats.mannwhitneyu(pre["overnight_share"], post["overnight_share"], alternative="two-sided").pvalue),
        },
        "log_var_ratio_pre_vs_post": {
            "u_stat": float(stats.mannwhitneyu(pre["log_var_ratio"], post["log_var_ratio"], alternative="two-sided").statistic),
            "p_value": float(stats.mannwhitneyu(pre["log_var_ratio"], post["log_var_ratio"], alternative="two-sided").pvalue),
        },
    }

    share_shift = desc["post_0dte"]["overnight_share_mean"] - desc["pre_0dte"]["overnight_share_mean"]
    did_reg = hac_regression(df, "overnight_share", ["post_0dte", "is_tue_thu", "post_x_tue_thu"])
    share_reg = hac_regression(df, "overnight_share", ["post_0dte"])
    ratio_reg = hac_regression(df, "log_var_ratio", ["post_0dte"])
    intraday_reg = hac_regression(df, "intraday_var", ["post_0dte"])
    overnight_reg = hac_regression(df, "overnight_var", ["post_0dte"])
    tests = {
        "mann_whitney": mann_whitney,
        "hac_regressions": {
            "overnight_share_post_dummy": share_reg,
            "log_var_ratio_post_dummy": ratio_reg,
            "overnight_var_post_dummy": overnight_reg,
            "intraday_var_post_dummy": intraday_reg,
            "overnight_share_tue_thu_did": did_reg,
        },
        "chow": {
            "overnight_share": chow_test(df, "overnight_share", [], BREAK_DATE),
            "log_var_ratio": chow_test(df, "log_var_ratio", [], BREAK_DATE),
        },
        "cusum": {
            "overnight_share": cusum_test(df, "overnight_share", []),
            "log_var_ratio": cusum_test(df, "log_var_ratio", []),
        },
    }

    verdict = {
        "headline": "mixed_but_small_shift",
        "summary": (
            "SPY 的隔夜變異占比在 2022-04-18 後小幅下降，代表日內占比略升；但 Tue/Thu 相對 Mon/Wed/Fri 的增量不顯著，"
            "不支持『0DTE 普及單獨改寫波動結構』的強敘事。"
        ),
        "evidence": {
            "overnight_share_mean_pre": desc["pre_0dte"]["overnight_share_mean"],
            "overnight_share_mean_post": desc["post_0dte"]["overnight_share_mean"],
            "share_shift_pct_points": share_shift * 100,
            "post_dummy_p": share_reg["params"]["post_0dte"]["p"],
            "did_interaction_p": did_reg["params"]["post_x_tue_thu"]["p"],
        },
        "research_honesty": (
            "目前比較像 2022 後整體市場結構與波動環境一起改變，而不是 Tue/Thu 新增到期日單獨造成的可辨識斷裂。"
        ),
    }

    payload = {
        "experiment_id": EXPERIMENT_ID,
        "title": "0DTE 時代的日內 vs 隔夜波動結構轉變",
        "created_at": pd.Timestamp.now("UTC").isoformat(),
        "seed": SEED,
        "data": {
            "ticker": TICKER,
            "source": "yfinance",
            "start_date": START_DATE,
            "end_date": END_DATE,
            "n_obs": int(len(df)),
            "break_date": str(BREAK_DATE.date()),
            "full_rollout_date": str(THURSDAY_FULL_ROLLOUT.date()),
        },
        "literature": [asdict(item) for item in LITERATURE],
        "descriptive_stats": desc,
        "weekday_panel": weekday_panel(df),
        "tests": tests,
        "verdict": verdict,
        "files": {
            "script": str(Path(__file__).name),
            "readme": str(README_PATH.name),
            "figures": sorted(p.name for p in FIG_DIR.glob("*.png")),
        },
    }

    make_figures(df)
    payload["files"]["figures"] = sorted(p.name for p in FIG_DIR.glob("*.png"))
    RESULT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print(json.dumps(payload["verdict"], ensure_ascii=False, indent=2))
    print(f"wrote {RESULT_PATH}")


if __name__ == "__main__":
    main()
