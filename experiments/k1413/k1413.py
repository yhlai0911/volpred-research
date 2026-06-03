"""
K1413 — AI 資本支出五層產業鏈的波動率 / 跨層相關性視角

動機：熱門財經自媒體在講「AI 五層蛋糕」（能源→晶片→基礎設施→模型→應用）的
資本支出產業鏈。VolPred 的差異化不是再講一次產業故事，而是用真數據回答：
這五層的代表類股，在「波動率」與「跨層相關性」上過去/現在怎麼互動？
哪一層是波動源頭、相關性 regime 怎麼變。

資料：yfinance 日資料，2023-01-01 至今（2026-06）。
五層等權 basket（依公開的 AI 五層框架歸類，等權 daily simple return）：
  L1 能源/電力基建: VST, CEG, VRT, ETN
  L2 晶片:          NVDA, TSM, AVGO, MRVL, MU
  L3 基礎設施/伺服器/網通: SMCI, DELL, ANET
  L4/L5 模型/應用(hyperscaler): MSFT, GOOGL, AMZN, META
  基準: SPY

方法（描述統計為主，固定 seed，無 lookahead）：
  1. 各層 basket 年化已實現波動率（rolling 63 交易日，回看窗口） -> chart 1
  2. 各層相關性矩陣，分三段期間（2023 / 2024 / 2025-至今）對比 -> chart 2
  3. lead-lag：各層 daily return 對晶片層 lag±k 的 cross-correlation
  4. caveats：basket 等權、樣本期間、yfinance 來源、非投資建議

防錯（依 docs/error_log.md）：
  - yfinance auto_adjust=True（return 計算含股息調整較合理），明確註記
  - 抓到的 raw close 存 CSV pin 住（yfinance 不可回溯）
  - rolling vol 用過去窗口，無 lookahead
  - 固定 seed
"""
import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import yfinance as yf

warnings.filterwarnings("ignore")

# CJK 字型（macOS）
plt.rcParams["font.sans-serif"] = ["Arial Unicode MS", "Heiti TC", "Hiragino Sans GB"]
plt.rcParams["axes.unicode_minus"] = False

SEED = 1413
np.random.seed(SEED)

HERE = Path(__file__).resolve().parent
START = "2023-01-01"
END = "2026-06-03"
TRADING_DAYS = 252
VOL_WINDOW = 63  # rolling realized vol 窗口（約一季）

LAYERS = {
    "L1 能源電力": ["VST", "CEG", "VRT", "ETN"],
    "L2 晶片": ["NVDA", "TSM", "AVGO", "MRVL", "MU"],
    "L3 基礎設施": ["SMCI", "DELL", "ANET"],
    "L4L5 模型應用": ["MSFT", "GOOGL", "AMZN", "META"],
}
LAYER_SHORT = {
    "L1 能源電力": "L1",
    "L2 晶片": "L2",
    "L3 基礎設施": "L3",
    "L4L5 模型應用": "L4/L5",
}
ALL_TICKERS = sorted({t for ts in LAYERS.values() for t in ts} | {"SPY"})


def fetch_prices():
    """抓 adjusted close（auto_adjust=True，含股息調整，註明於 README）。
    存 CSV pin 住歷史 snapshot（yfinance 不可回溯）。"""
    raw = yf.download(
        ALL_TICKERS,
        start=START,
        end=END,
        auto_adjust=True,  # adjusted close：return 計算含股息較合理
        progress=False,
    )
    close = raw["Close"].copy()
    close = close.dropna(how="all")
    # 全期間都有資料的 ticker 才保留（避免上市較晚污染早期 basket）
    close = close.ffill().dropna()
    close.to_csv(HERE / "k1413_prices.csv")
    return close


def basket_returns(close):
    """每層等權 basket 的 daily simple return（先算個股 return 再等權平均）。"""
    rets = close.pct_change().dropna()
    out = {}
    for layer, tks in LAYERS.items():
        avail = [t for t in tks if t in rets.columns]
        out[layer] = rets[avail].mean(axis=1)  # 等權
    out["SPY"] = rets["SPY"]
    return pd.DataFrame(out)


def rolling_annualized_vol(layer_rets):
    """rolling 63 交易日已實現波動率，年化。回看窗口，無 lookahead。"""
    rv = layer_rets.rolling(VOL_WINDOW).std() * np.sqrt(TRADING_DAYS)
    return rv.dropna()


def period_corr(layer_rets):
    """分三段期間的相關性矩陣。"""
    segs = {
        "2023": ("2023-01-01", "2023-12-31"),
        "2024": ("2024-01-01", "2024-12-31"),
        "2025至今": ("2025-01-01", END),
    }
    corrs = {}
    for name, (s, e) in segs.items():
        sub = layer_rets.loc[s:e]
        corrs[name] = sub.corr()
    return corrs, segs


def lead_lag(layer_rets, anchor="L2 晶片", max_lag=5):
    """各層 return 對晶片層 lag±k 的 cross-correlation。
    corr(other_t, anchor_{t-k})：k>0 表示晶片領先 other。"""
    res = {}
    a = layer_rets[anchor]
    for layer in layer_rets.columns:
        if layer == anchor:
            continue
        o = layer_rets[layer]
        series = {}
        for k in range(-max_lag, max_lag + 1):
            # k>0: anchor 領先 k 天 -> 用 anchor.shift(k) 對齊 o
            c = o.corr(a.shift(k))
            series[k] = float(c)
        # 找最大 |corr| 的 lag
        best_lag = max(series, key=lambda kk: abs(series[kk]))
        res[layer] = {
            "by_lag": series,
            "best_lag": best_lag,
            "best_corr": series[best_lag],
        }
    return res


def chart_vol(rv):
    fig, ax = plt.subplots(figsize=(11, 6))
    colors = {
        "L1 能源電力": "#2ca02c",
        "L2 晶片": "#d62728",
        "L3 基礎設施": "#ff7f0e",
        "L4L5 模型應用": "#1f77b4",
        "SPY": "#7f7f7f",
    }
    label_map = {
        "L1 能源電力": "L1 能源/電力",
        "L2 晶片": "L2 晶片",
        "L3 基礎設施": "L3 基礎設施",
        "L4L5 模型應用": "L4/L5 模型/應用",
        "SPY": "SPY（基準）",
    }
    x = rv.index.to_numpy()
    for col in rv.columns:
        style = "--" if col == "SPY" else "-"
        lw = 1.3 if col == "SPY" else 1.8
        ax.plot(x, (rv[col] * 100).to_numpy(), style, lw=lw, color=colors[col], label=label_map[col])
    ax.set_title("AI 五層產業鏈：各層年化已實現波動率（rolling 63 交易日）", fontsize=13)
    ax.set_ylabel("年化波動率 (%)")
    ax.set_xlabel("日期")
    ax.legend(loc="upper right", fontsize=9, ncol=2)
    ax.grid(alpha=0.3)
    ax.text(0.005, -0.13,
            "資料：yfinance 日 adjusted close 2023-01~2026-06；basket 等權；experiment K1413。非投資建議。",
            transform=ax.transAxes, fontsize=8, color="#666")
    fig.tight_layout()
    fig.savefig(HERE / "k1413_vol_timeseries.png", dpi=130, bbox_inches="tight")
    plt.close(fig)


def chart_corr(corrs, segs):
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    labels = [LAYER_SHORT.get(c, c) for c in list(corrs.values())[0].columns]
    im = None
    for ax, (name, mat) in zip(axes, corrs.items()):
        m = mat.values
        im = ax.imshow(m, vmin=0, vmax=1, cmap="YlOrRd")
        ax.set_xticks(range(len(labels)))
        ax.set_yticks(range(len(labels)))
        ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=9)
        ax.set_yticklabels(labels, fontsize=9)
        s, e = segs[name]
        ax.set_title(f"{name}\n({s[:7]}~{e[:7]})", fontsize=11)
        for i in range(len(labels)):
            for j in range(len(labels)):
                ax.text(j, i, f"{m[i, j]:.2f}", ha="center", va="center",
                        fontsize=8, color="black" if m[i, j] < 0.7 else "white")
    fig.colorbar(im, ax=axes, fraction=0.025, pad=0.02, label="相關係數")
    fig.suptitle("AI 五層產業鏈：跨層 daily return 相關性矩陣（分三段期間）", fontsize=13, y=1.02)
    fig.text(0.5, -0.04,
             "資料：yfinance 日 adjusted close；basket 等權 daily return；experiment K1413。非投資建議。",
             ha="center", fontsize=8, color="#666")
    fig.savefig(HERE / "k1413_corr_regime.png", dpi=130, bbox_inches="tight")
    plt.close(fig)


def main():
    close = fetch_prices()
    layer_rets = basket_returns(close)
    rv = rolling_annualized_vol(layer_rets)
    corrs, segs = period_corr(layer_rets)
    ll = lead_lag(layer_rets)

    full_vol = (layer_rets.std() * np.sqrt(TRADING_DAYS)).to_dict()

    def avg_cross_corr(mat):
        layers_only = [c for c in mat.columns if c != "SPY"]
        sub = mat.loc[layers_only, layers_only].values
        n = len(layers_only)
        off = [sub[i, j] for i in range(n) for j in range(n) if i != j]
        return float(np.mean(off))

    avg_corr_by_period = {name: avg_cross_corr(mat) for name, mat in corrs.items()}

    results = {
        "experiment_id": "k1413",
        "title": "AI 五層產業鏈的波動率 / 跨層相關性視角",
        "seed": SEED,
        "data": {
            "source": "yfinance (auto_adjust=True, adjusted close)",
            "period": {"start": str(layer_rets.index[0].date()),
                       "end": str(layer_rets.index[-1].date())},
            "n_trading_days": int(len(layer_rets)),
            "vol_window": VOL_WINDOW,
            "trading_days_per_year": TRADING_DAYS,
            "layers": LAYERS,
            "note": "basket 等權 daily simple return；adjusted close 含股息調整。",
        },
        "full_period_annualized_vol": {k: round(v, 4) for k, v in full_vol.items()},
        "rolling_vol_summary": {
            col: {
                "mean": round(float(rv[col].mean()), 4),
                "max": round(float(rv[col].max()), 4),
                "max_date": str(rv[col].idxmax().date()),
                "min": round(float(rv[col].min()), 4),
                "min_date": str(rv[col].idxmin().date()),
                "latest": round(float(rv[col].iloc[-1]), 4),
                "latest_date": str(rv.index[-1].date()),
            } for col in rv.columns
        },
        "correlation_by_period": {
            name: {f"{r}|{c}": round(float(mat.loc[r, c]), 4)
                   for r in mat.columns for c in mat.columns}
            for name, mat in corrs.items()
        },
        "avg_cross_layer_corr_by_period": {k: round(v, 4) for k, v in avg_corr_by_period.items()},
        "lead_lag_vs_chips": {
            layer: {
                "best_lag": d["best_lag"],
                "best_corr": round(d["best_corr"], 4),
                "lag0_corr": round(d["by_lag"][0], 4),
                "interpretation": (
                    "晶片領先" if d["best_lag"] > 0 else
                    ("晶片落後" if d["best_lag"] < 0 else "同期")
                ),
            } for layer, d in ll.items()
        },
        "caveats": [
            "basket 為等權，非市值加權；個股權重影響結果",
            "樣本期間 2023-01 至 2026-06，僅涵蓋 AI 資本支出上行週期，未含完整空頭",
            "yfinance adjusted close 不可回溯，本次 snapshot 已 pin 至 k1413_prices.csv",
            "相關性與 lead-lag 為描述統計，非因果；未做正式統計檢定",
            "非投資建議；不構成任何證券之買賣推薦",
        ],
    }

    with open(HERE / "k1413_results.json", "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    chart_vol(rv)
    chart_corr(corrs, segs)

    print("=== 全期間年化波動率 ===")
    for k, v in sorted(full_vol.items(), key=lambda x: -x[1]):
        print(f"  {k:14s}: {v*100:5.1f}%")
    print("\n=== 平均跨層相關（AI 主題集中度）===")
    for k, v in avg_corr_by_period.items():
        print(f"  {k:10s}: {v:.3f}")
    print("\n=== lead-lag vs 晶片層 ===")
    for layer, d in ll.items():
        print(f"  {layer:14s}: best_lag={d['best_lag']:+d} corr={d['best_corr']:.3f} (lag0={d['by_lag'][0]:.3f})")
    print(f"\n樣本：{results['data']['period']['start']} ~ {results['data']['period']['end']}, "
          f"N={results['data']['n_trading_days']} 交易日")
    print("圖：k1413_vol_timeseries.png, k1413_corr_regime.png")


if __name__ == "__main__":
    main()
