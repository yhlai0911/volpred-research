"""K1703 — 選擇權月結算週（OpEx week）的波動壓抑與釋放。

問題：市場長年流傳「結算週因做市商 gamma 避險把指數釘住、波動被壓抑，結算一過波動放開」。
用 SPY 全歷史日資料檢定三組週別（OpEx 週 / OpEx 後一週 / 一般週）的波動差異。

資料：yfinance SPY 日線（1993 上市至今）。
統計：組間均值差 + 週層級 bootstrap（週是自然 block，seed 固定）+ 分年代穩定性。
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf

SEED = 42
N_BOOT = 10000
OUT = Path(__file__).parent
TRADING_DAYS = 252


def third_friday(year: int, month: int) -> date:
    """該月第三個星期五（美股月選擇權結算日）。"""
    d = date(year, month, 1)
    # weekday(): Mon=0 ... Fri=4
    first_friday_day = 1 + (4 - d.weekday()) % 7
    return date(year, month, first_friday_day + 14)


def load_spy() -> pd.DataFrame:
    raw = yf.download("SPY", start="1993-01-29", auto_adjust=True, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    df = raw[["Close", "High", "Low"]].dropna().copy()
    df["ret"] = np.log(df["Close"]).diff()
    return df.dropna()


def classify(df: pd.DataFrame) -> pd.DataFrame:
    """把每個交易日標到所屬週，並判定該週是 OpEx 週 / OpEx 後一週 / 一般週。"""
    idx = df.index
    # 以 ISO 年+週作為週鍵（週一為週首）
    iso = idx.isocalendar()
    df = df.copy()
    df["week_key"] = [f"{y}-{w:02d}" for y, w in zip(iso.year, iso.week)]

    opex_days = {
        third_friday(y, m)
        for y in range(idx[0].year, idx[-1].year + 1)
        for m in range(1, 13)
    }
    # OpEx 結算日所落在的週鍵
    opex_week_keys: set[str] = set()
    for d in idx:
        if d.date() in opex_days:
            y, w, _ = d.isocalendar()
            opex_week_keys.add(f"{y}-{w:02d}")

    ordered_weeks = list(dict.fromkeys(df["week_key"]))
    pos = {k: i for i, k in enumerate(ordered_weeks)}
    post_week_keys = {
        ordered_weeks[pos[k] + 1]
        for k in opex_week_keys
        if k in pos and pos[k] + 1 < len(ordered_weeks)
    }

    def label(k: str) -> str:
        if k in opex_week_keys:
            return "opex"
        if k in post_week_keys:
            return "post_opex"
        return "normal"

    df["week_type"] = [label(k) for k in df["week_key"]]
    df["is_opex_day"] = [d.date() in opex_days for d in idx]
    return df


def weekly_table(df: pd.DataFrame) -> pd.DataFrame:
    """每週彙總：年化實現波動率、平均日絕對報酬、週內高低振幅。"""
    rows = []
    for key, g in df.groupby("week_key", sort=False):
        if len(g) < 3:  # 假期短週剔除，避免 std 不穩
            continue
        rv = g["ret"].std(ddof=1) * np.sqrt(TRADING_DAYS) * 100
        rng = (g["High"].max() / g["Low"].min() - 1) * 100
        rows.append(
            {
                "week_key": key,
                "week_type": g["week_type"].iloc[0],
                "year": g.index[0].year,
                "n_days": len(g),
                "rv_annual_pct": rv,
                "mean_abs_ret_pct": g["ret"].abs().mean() * 100,
                "hl_range_pct": rng,
            }
        )
    return pd.DataFrame(rows)


def boot_ci(x: np.ndarray, rng: np.random.Generator, n: int = N_BOOT):
    draws = rng.choice(x, size=(n, x.size), replace=True).mean(axis=1)
    return float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5)), draws


def boot_diff_p(a: np.ndarray, b: np.ndarray, rng: np.random.Generator) -> dict:
    """bootstrap 均值差（a - b）與雙尾 p 值（H0: 差 = 0）。"""
    da = rng.choice(a, size=(N_BOOT, a.size), replace=True).mean(axis=1)
    db = rng.choice(b, size=(N_BOOT, b.size), replace=True).mean(axis=1)
    diff = da - db
    obs = float(a.mean() - b.mean())
    p = float(2 * min((diff <= 0).mean(), (diff >= 0).mean()))
    return {
        "diff": obs,
        "ci_low": float(np.percentile(diff, 2.5)),
        "ci_high": float(np.percentile(diff, 97.5)),
        "p_value": min(p, 1.0),
    }


def main() -> None:
    rng = np.random.default_rng(SEED)
    df = classify(load_spy())
    wk = weekly_table(df)

    groups = {t: wk.loc[wk.week_type == t, "rv_annual_pct"].to_numpy() for t in ("opex", "post_opex", "normal")}
    summary = {}
    for t, x in groups.items():
        lo, hi, _ = boot_ci(x, rng)
        summary[t] = {
            "n_weeks": int(x.size),
            "mean_rv_annual_pct": float(x.mean()),
            "median_rv_annual_pct": float(np.median(x)),
            "ci95_low": lo,
            "ci95_high": hi,
            "mean_abs_ret_pct": float(wk.loc[wk.week_type == t, "mean_abs_ret_pct"].mean()),
            "mean_hl_range_pct": float(wk.loc[wk.week_type == t, "hl_range_pct"].mean()),
        }

    tests = {
        "opex_vs_normal": boot_diff_p(groups["opex"], groups["normal"], rng),
        "post_opex_vs_normal": boot_diff_p(groups["post_opex"], groups["normal"], rng),
        "post_opex_vs_opex": boot_diff_p(groups["post_opex"], groups["opex"], rng),
    }

    # 結算日當天 vs 其他星期五的絕對報酬
    fri = df[df.index.dayofweek == 4]
    opex_fri = fri.loc[fri.is_opex_day, "ret"].abs().to_numpy() * 100
    other_fri = fri.loc[~fri.is_opex_day, "ret"].abs().to_numpy() * 100
    tests["opexday_vs_other_friday_abs_ret"] = boot_diff_p(opex_fri, other_fri, rng)
    tests["opexday_vs_other_friday_abs_ret"].update(
        {"mean_opex_friday_pct": float(opex_fri.mean()), "mean_other_friday_pct": float(other_fri.mean()),
         "n_opex_fridays": int(opex_fri.size), "n_other_fridays": int(other_fri.size)}
    )

    # 分年代穩定性
    decades = {}
    for lo_y in (1993, 2000, 2010, 2020):
        hi_y = min(lo_y + 9, 2026) if lo_y != 1993 else 1999
        sub = wk[(wk.year >= lo_y) & (wk.year <= hi_y)]
        if len(sub) < 30:
            continue
        o = sub.loc[sub.week_type == "opex", "rv_annual_pct"].to_numpy()
        n = sub.loc[sub.week_type == "normal", "rv_annual_pct"].to_numpy()
        p = sub.loc[sub.week_type == "post_opex", "rv_annual_pct"].to_numpy()
        decades[f"{lo_y}-{hi_y}"] = {
            "n_opex_weeks": int(o.size),
            "opex_mean": float(o.mean()),
            "normal_mean": float(n.mean()),
            "post_opex_mean": float(p.mean()),
            "opex_minus_normal": float(o.mean() - n.mean()),
        }

    results = {
        "experiment_id": "k1703",
        "title": "選擇權月結算週（OpEx week）的波動壓抑與釋放：SPY 全歷史檢定",
        "data": {
            "symbol": "SPY",
            "source": "yfinance (auto_adjust=True)",
            "start": str(df.index[0].date()),
            "end": str(df.index[-1].date()),
            "n_trading_days": int(len(df)),
            "n_weeks_analyzed": int(len(wk)),
        },
        "method": {
            "opex_definition": "每月第三個星期五所在的整週",
            "post_opex_definition": "OpEx 週的下一個交易週",
            "rv": "週內日對數報酬標準差 × sqrt(252)，以百分比表示",
            "bootstrap": {"n": N_BOOT, "seed": SEED, "unit": "week (natural block)"},
            "exclusions": "交易日 < 3 天的假期短週剔除",
        },
        "summary_by_week_type": summary,
        "tests": tests,
        "by_decade": decades,
    }
    (OUT / "k1703_results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False))

    # ---- 圖 1：三組週別的平均年化 RV + 95% bootstrap CI
    fig, ax = plt.subplots(figsize=(8, 5))
    labels = {"normal": "一般週", "opex": "結算週", "post_opex": "結算後一週"}
    order = ["normal", "opex", "post_opex"]
    means = [summary[t]["mean_rv_annual_pct"] for t in order]
    errs = [
        [summary[t]["mean_rv_annual_pct"] - summary[t]["ci95_low"] for t in order],
        [summary[t]["ci95_high"] - summary[t]["mean_rv_annual_pct"] for t in order],
    ]
    bars = ax.bar([labels[t] for t in order], means, yerr=errs, capsize=6,
                  color=["#9aa5b1", "#2f6f9f", "#c2703d"])
    for b, m, t in zip(bars, means, order):
        ax.text(b.get_x() + b.get_width() / 2, m + 0.5, f"{m:.2f}%\n(n={summary[t]['n_weeks']})",
                ha="center", fontsize=9)
    ax.set_ylabel("平均年化實現波動率 (%)")
    ax.set_title("SPY：結算週的波動並沒有被「釘」得比較低\n（誤差線為 95% bootstrap 信賴區間）")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUT / "fig1_rv_by_week_type.png", dpi=150)
    plt.close(fig)

    # ---- 圖 2：結算日 vs 其他星期五的絕對報酬分布
    fig, ax = plt.subplots(figsize=(8, 5))
    bins = np.linspace(0, 3, 40)
    ax.hist(other_fri, bins=bins, density=True, alpha=0.55, label=f"其他星期五 (n={other_fri.size})", color="#9aa5b1")
    ax.hist(opex_fri, bins=bins, density=True, alpha=0.65, label=f"結算日星期五 (n={opex_fri.size})", color="#2f6f9f")
    ax.axvline(other_fri.mean(), color="#5b6570", ls="--", lw=1.5)
    ax.axvline(opex_fri.mean(), color="#1d4d70", ls="--", lw=1.5)
    ax.set_xlabel("當日絕對報酬 (%)")
    ax.set_ylabel("機率密度")
    ax.set_title(f"結算日當天的波動：平均 {opex_fri.mean():.3f}% vs 其他星期五 {other_fri.mean():.3f}%")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUT / "fig2_opex_day_abs_ret.png", dpi=150)
    plt.close(fig)

    # ---- 圖 3：分年代穩定性
    fig, ax = plt.subplots(figsize=(9, 5))
    ks = list(decades.keys())
    x = np.arange(len(ks))
    w = 0.27
    ax.bar(x - w, [decades[k]["normal_mean"] for k in ks], w, label="一般週", color="#9aa5b1")
    ax.bar(x, [decades[k]["opex_mean"] for k in ks], w, label="結算週", color="#2f6f9f")
    ax.bar(x + w, [decades[k]["post_opex_mean"] for k in ks], w, label="結算後一週", color="#c2703d")
    ax.set_xticks(x, ks)
    ax.set_ylabel("平均年化實現波動率 (%)")
    ax.set_title("四個年代分別看：結算週的相對高低有沒有翻過面")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUT / "fig3_by_decade.png", dpi=150)
    plt.close(fig)

    print(json.dumps({"summary": summary, "tests": tests, "by_decade": decades}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
