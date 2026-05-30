#!/usr/bin/env python3
"""K1406 — 投資時機策略 conditional block bootstrap.

兩組「投資時機」策略在真實 SPY + 0050.TW 日資料上的可復現比較：

Group A — 定期定額(DCA) vs 單筆投入(Lump Sum)
  * Lump Sum: t0 一次全投入固定資金
  * DCA: 分 12 期（每月，每 ~21 交易日）平均投入
  * 指標: 終值/總報酬率、IRR(money-weighted)、各 regime + 整體勝率
  * 命題 A: 總報酬率 Lump Sum 通常勝；但 IRR(資金效率) 兩者本質接近相等

Group B — 固定配置(Stay-invested) vs 逢低買進(dip-buying)
  * Fixed: 每期可投入現金立即投入
  * Dip-buying: 囤現金，僅當價格從近期高點回檔 >= 門檻(5/10/15%)才一次性投入囤積現金
  * 指標: 終值/總報酬率、勝率、平均閒置現金時間比例(cash drag)、等不到回檔比例
  * 命題 B: 囤現金等回檔通常輸給持續投入（cash drag > timing 利益）

方法:
  * conditional block bootstrap, block=20 交易日, seed=20260530
  * horizon: 1 年(252 交易日) + 3 年(756 交易日)
  * regime: 依路徑年化報酬 純多頭(>+10%)/純空頭(<-10%)/中性
  * 各 regime 至少累積 >=500 條；每資產每 horizon >= 2000 條
  * lag-correctness: dip 觸發用 t-1 及更早的 rolling high (.shift(1) 等效)

資料: 優先 yfinance (SPY 2005-, 0050.TW 2008-)，失敗則 fallback experiments/k1090/data/
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.optimize import brentq

# ----------------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------------
SEED = 20260530
BLOCK = 20  # 交易日
HORIZONS = {"1y": 252, "3y": 756}
N_BOOT_TARGET = 2000  # 每資產每 horizon 最少路徑
REGIME_MIN = 500  # 各 regime 最少累積路徑
MAX_EXTRA_ROUNDS = 30  # 補跑上限
IRR_SUBSAMPLE = 2000  # IRR grid-scan 較慢：只對前 N 條路徑算 IRR；FV 勝率/drag 用全樣本
DCA_PERIODS = 12
DCA_STEP = 21  # 約一個月的交易日
DIP_THRESHOLDS = [0.05, 0.10, 0.15]
DIP_HIGH_WINDOW = 63  # 近期高點回看窗(交易日, ~3個月)

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
FIG_DIR = HERE / "figures"
FALLBACK_DIR = HERE.parent / "k1090" / "data"
DATA_DIR.mkdir(exist_ok=True)
FIG_DIR.mkdir(exist_ok=True)

ASSETS = {
    "SPY": {"yf": "SPY", "start": "2005-01-01"},
    "0050.TW": {"yf": "0050.TW", "start": "2008-01-01"},
}

plt.rcParams["font.sans-serif"] = [
    "Heiti TC",
    "Arial Unicode MS",
    "PingFang TC",
    "Microsoft JhengHei",
    "sans-serif",
]
plt.rcParams["axes.unicode_minus"] = False


# ----------------------------------------------------------------------------
# Data loading
# ----------------------------------------------------------------------------
def load_prices(name: str, cfg: dict) -> tuple[pd.Series, dict]:
    """回傳 (Close 序列, 來源 meta)。優先 yfinance，失敗 fallback k1090。"""
    cache = DATA_DIR / f"{name}.csv"
    meta = {"asset": name}
    if cache.exists():
        df = pd.read_csv(cache, parse_dates=["Date"]).set_index("Date")
        meta["source"] = "yfinance_cached"
        s = df["Close"].dropna()
        meta.update(_span(s))
        return s, meta
    try:
        import yfinance as yf

        df = yf.download(
            cfg["yf"],
            start=cfg["start"],
            end="2026-05-30",
            progress=False,
            auto_adjust=True,
            timeout=25,
        )
        if df is None or len(df) < 300:
            raise RuntimeError(f"yfinance returned too few rows: {0 if df is None else len(df)}")
        close = df["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        s = close.dropna()
        s.index.name = "Date"
        out = s.rename("Close").to_frame()
        out.to_csv(cache)
        meta["source"] = "yfinance_live"
        meta.update(_span(s))
        return s, meta
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] yfinance failed for {name}: {exc!r} -> fallback k1090")
    fb = FALLBACK_DIR / f"{name}.csv"
    df = pd.read_csv(fb, parse_dates=["Date"]).set_index("Date")
    s = df["Close"].dropna()
    meta["source"] = "fallback_k1090"
    meta["fallback_note"] = (
        "yfinance 不可用，改用 experiments/k1090/data (2018-2024，含 2020 崩盤 + 2022 空頭，"
        "樣本期較短，bootstrap 母體有限)"
    )
    meta.update(_span(s))
    return s, meta


def _span(s: pd.Series) -> dict:
    return {
        "n_days": int(len(s)),
        "start": str(s.index.min().date()),
        "end": str(s.index.max().date()),
    }


# ----------------------------------------------------------------------------
# Block bootstrap of daily simple returns
# ----------------------------------------------------------------------------
def daily_returns(prices: pd.Series) -> np.ndarray:
    return prices.pct_change().dropna().to_numpy()


def bootstrap_path(rets: np.ndarray, length: int, rng: np.random.Generator) -> np.ndarray:
    """以 block=BLOCK 拼接出長度 length 的日報酬路徑（circular block bootstrap）。"""
    n = len(rets)
    out = np.empty(length, dtype=float)
    filled = 0
    while filled < length:
        start = int(rng.integers(0, n))
        take = min(BLOCK, length - filled)
        idx = (start + np.arange(take)) % n  # circular wrap
        out[filled : filled + take] = rets[idx]
        filled += take
    return out


def path_to_prices(path_rets: np.ndarray, p0: float = 100.0) -> np.ndarray:
    """日報酬 -> 價格序列，長度 = len(path_rets)+1，price[0]=p0。"""
    prices = np.empty(len(path_rets) + 1, dtype=float)
    prices[0] = p0
    prices[1:] = p0 * np.cumprod(1.0 + path_rets)
    return prices


def path_annualized(path_rets: np.ndarray) -> float:
    """全路徑年化報酬（用於 regime 分類）。"""
    total = float(np.prod(1.0 + path_rets))
    years = len(path_rets) / 252.0
    if total <= 0:
        return -1.0
    return total ** (1.0 / years) - 1.0


def classify_regime(ann: float) -> str:
    if ann > 0.10:
        return "bull"
    if ann < -0.10:
        return "bear"
    return "neutral"


# ----------------------------------------------------------------------------
# IRR (money-weighted), period = trading day, then annualize
# ----------------------------------------------------------------------------
def irr_periodic(cashflows: np.ndarray) -> float | None:
    """求每期(每交易日) IRR：sum(cf_t / (1+r)^t) = 0。回傳每期 r，無解回 None。

    每期 IRR 必然很小（日報酬量級），故在 (-0.5, +0.5) 的安全範圍掃描 sign-change：
    過低的下界（如 -0.9999）會讓 (1+r)^t overflow → npv=NaN，破壞 bracket 判斷（此處
    曾踩坑：lo=-0.9999 使所有 IRR 回 None）。
    """
    cf = np.asarray(cashflows, dtype=float)
    if not (np.any(cf > 0) and np.any(cf < 0)):
        return None
    t = np.arange(len(cf))

    def npv(r: float) -> float:
        with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
            val = float(np.sum(cf / (1.0 + r) ** t))
        return val if np.isfinite(val) else np.nan

    # 在安全範圍掃描格點找 sign change（避開 npv=NaN 的極端 r）
    grid = np.linspace(-0.5, 0.5, 401)
    try:
        prev_r, prev_v = None, None
        for r in grid:
            v = npv(float(r))
            if not np.isfinite(v):
                prev_r, prev_v = None, None
                continue
            if prev_v is not None and prev_v * v <= 0 and prev_v != v:
                root = float(brentq(npv, prev_r, float(r), maxiter=200, xtol=1e-12))
                return root
            prev_r, prev_v = float(r), v
        return None
    except Exception:  # noqa: BLE001
        return None


def annualize_periodic(r_period: float | None) -> float | None:
    if r_period is None:
        return None
    base = 1.0 + r_period
    if base <= 0:
        return None
    return base ** 252.0 - 1.0


# ----------------------------------------------------------------------------
# Group A: DCA vs Lump Sum on one bootstrap price path
# ----------------------------------------------------------------------------
def group_a_one_path(prices: np.ndarray, capital: float = 12000.0, compute_irr: bool = True) -> dict:
    """prices: 長度 = horizon_days + 1（含 t0）。投資期末為 prices[-1]。
    投入時點外生固定（無 lookahead）。
    compute_irr=False 時跳過 IRR grid-scan（FV 勝率/報酬仍用全樣本，IRR 用子樣本省時）。
    """
    n_days = len(prices) - 1
    p0 = prices[0]
    pT = prices[-1]

    units_lump = capital / p0
    fv_lump = units_lump * pT

    per = capital / DCA_PERIODS
    buy_days = [min(k * DCA_STEP, n_days) for k in range(DCA_PERIODS)]
    units_dca = 0.0
    cf_dca = np.zeros(n_days + 1)
    for d in buy_days:
        units_dca += per / prices[d]
        cf_dca[d] += -per
    fv_dca = units_dca * pT

    if compute_irr:
        cf_lump = np.zeros(n_days + 1)
        cf_lump[0] = -capital
        cf_lump[-1] = fv_lump
        irr_lump = annualize_periodic(irr_periodic(cf_lump))
        cf_dca_full = cf_dca.copy()
        cf_dca_full[-1] += fv_dca
        irr_dca = annualize_periodic(irr_periodic(cf_dca_full))
    else:
        irr_lump = None
        irr_dca = None

    ret_lump = fv_lump / capital - 1.0
    ret_dca = fv_dca / capital - 1.0
    return {
        "fv_lump": fv_lump,
        "fv_dca": fv_dca,
        "ret_lump": ret_lump,
        "ret_dca": ret_dca,
        "irr_lump": irr_lump,
        "irr_dca": irr_dca,
        "lump_wins_fv": fv_lump > fv_dca,
        "lump_wins_irr": (irr_lump is not None and irr_dca is not None and irr_lump > irr_dca),
    }


# ----------------------------------------------------------------------------
# Group B: Fixed (stay-invested) vs Dip-buying on one bootstrap price path
# ----------------------------------------------------------------------------
def group_b_one_path(prices: np.ndarray, threshold: float, per_period_cash: float = 1000.0) -> dict:
    """每期(每 DCA_STEP 交易日)收到 per_period_cash 現金。

    Fixed: 收到立即投入。
    Dip-buying: 現金囤積，僅當『價格從近期高點(只用 t-1 及更早) 回檔 >= threshold』
                才一次性投入所有囤積現金。lag-correct: rolling high 用過去資料。
    末日剩餘現金以面值結算（不投入，計閒置，無報酬）。
    """
    n_days = len(prices) - 1
    pT = prices[-1]
    cash_days = [k * DCA_STEP for k in range(DCA_PERIODS)]
    cash_days = [d for d in cash_days if d <= n_days]
    total_cash = per_period_cash * len(cash_days)

    # lag-correct rolling high：high_lag[t] = max(prices[max(0,t-W):t]) 不含 t -> 無 lookahead
    high_lag = np.empty(n_days + 1, dtype=float)
    high_lag[0] = prices[0]
    for t in range(1, n_days + 1):
        lo = max(0, t - DIP_HIGH_WINDOW)
        high_lag[t] = prices[lo:t].max()

    cash_in = np.zeros(n_days + 1)
    for d in cash_days:
        cash_in[d] += per_period_cash

    units_fixed = 0.0
    for d in cash_days:
        units_fixed += per_period_cash / prices[d]
    fv_fixed = units_fixed * pT

    units_dip = 0.0
    hoard = 0.0
    idle_cash_day_sum = 0.0
    deployed_ever = False
    n_dip_triggers = 0
    for t in range(0, n_days + 1):
        hoard += cash_in[t]
        if t >= 1 and hoard > 0:
            dd = 1.0 - prices[t] / high_lag[t]
            if dd >= threshold:
                units_dip += hoard / prices[t]
                hoard = 0.0
                deployed_ever = True
                n_dip_triggers += 1
        idle_cash_day_sum += hoard
    fv_dip = units_dip * pT + hoard

    received_cash_day_sum = 0.0
    running = 0.0
    for t in range(0, n_days + 1):
        running += cash_in[t]
        received_cash_day_sum += running
    cash_drag = idle_cash_day_sum / received_cash_day_sum if received_cash_day_sum > 0 else 0.0

    ret_fixed = fv_fixed / total_cash - 1.0
    ret_dip = fv_dip / total_cash - 1.0
    return {
        "fv_fixed": fv_fixed,
        "fv_dip": fv_dip,
        "ret_fixed": ret_fixed,
        "ret_dip": ret_dip,
        "dip_wins_fv": fv_dip > fv_fixed,
        "cash_drag": cash_drag,
        "never_triggered": not deployed_ever,
        "n_dip_triggers": n_dip_triggers,
        "total_cash": total_cash,
    }


# ----------------------------------------------------------------------------
# Driver per asset / horizon
# ----------------------------------------------------------------------------
def run_asset_horizon(name: str, rets: np.ndarray, horizon_days: int, rng: np.random.Generator) -> dict:
    rows_a: list[dict] = []
    rows_b: dict[float, list[dict]] = {th: [] for th in DIP_THRESHOLDS}
    regimes: list[str] = []

    def regime_counts() -> dict:
        c = {"bull": 0, "bear": 0, "neutral": 0}
        for r in regimes:
            c[r] += 1
        return c

    n_paths = 0
    rounds = 0
    while True:
        batch = max(N_BOOT_TARGET, 1000)
        for _ in range(batch):
            path_rets = bootstrap_path(rets, horizon_days, rng)
            ann = path_annualized(path_rets)
            reg = classify_regime(ann)
            regimes.append(reg)
            prices = path_to_prices(path_rets)
            a = group_a_one_path(prices, compute_irr=(n_paths < IRR_SUBSAMPLE))
            a["regime"] = reg
            a["path_ann"] = ann
            rows_a.append(a)
            for th in DIP_THRESHOLDS:
                b = group_b_one_path(prices, th)
                b["regime"] = reg
                rows_b[th].append(b)
            n_paths += 1
        rounds += 1
        c = regime_counts()
        enough_regime = all(c[k] >= REGIME_MIN for k in c)
        enough_total = n_paths >= N_BOOT_TARGET
        if (enough_regime and enough_total) or rounds >= MAX_EXTRA_ROUNDS:
            break

    c = regime_counts()
    result = {
        "asset": name,
        "horizon_days": horizon_days,
        "n_paths": n_paths,
        "regime_counts": c,
        "regime_min_satisfied": all(c[k] >= REGIME_MIN for k in c),
        "block_size": BLOCK,
        "seed": SEED,
    }

    df_a = pd.DataFrame(rows_a)
    ga: dict = {"overall": _summarize_group_a(df_a)}
    for reg in ["bull", "bear", "neutral"]:
        sub = df_a[df_a["regime"] == reg]
        ga[reg] = _summarize_group_a(sub) if len(sub) else None
    result["group_a"] = ga

    gb: dict = {}
    for th in DIP_THRESHOLDS:
        df_b = pd.DataFrame(rows_b[th])
        key = f"dip_{int(th*100)}pct"
        entry = {"overall": _summarize_group_b(df_b)}
        for reg in ["bull", "bear", "neutral"]:
            sub = df_b[df_b["regime"] == reg]
            entry[reg] = _summarize_group_b(sub) if len(sub) else None
        gb[key] = entry
    result["group_b"] = gb

    result["_raw_a"] = df_a
    result["_raw_b"] = {th: pd.DataFrame(rows_b[th]) for th in DIP_THRESHOLDS}
    return result


def _summarize_group_a(df: pd.DataFrame) -> dict:
    n = len(df)
    # irr 欄位可能是 object dtype（含 Python None），強制轉 numeric 才能做數值運算
    df = df.copy()
    df["irr_lump"] = pd.to_numeric(df["irr_lump"], errors="coerce")
    df["irr_dca"] = pd.to_numeric(df["irr_dca"], errors="coerce")
    irr_l = df["irr_lump"].dropna()
    irr_d = df["irr_dca"].dropna()
    paired = df.dropna(subset=["irr_lump", "irr_dca"])
    # IRR 勝率只在有有效 IRR 的子樣本計算（IRR 用子樣本，FV 用全樣本）
    irr_win = (paired["irr_lump"] > paired["irr_dca"]).mean() if len(paired) else None
    return {
        "n": int(n),
        "n_irr": int(len(paired)),
        "lump_win_rate_fv": float(df["lump_wins_fv"].mean()),
        "lump_win_rate_irr": float(irr_win) if irr_win is not None else None,
        "median_ret_lump": float(df["ret_lump"].median()),
        "median_ret_dca": float(df["ret_dca"].median()),
        "median_fv_ratio_lump_over_dca": float((df["fv_lump"] / df["fv_dca"]).median()),
        "median_irr_lump": float(irr_l.median()) if len(irr_l) else None,
        "median_irr_dca": float(irr_d.median()) if len(irr_d) else None,
        "median_irr_diff_lump_minus_dca": float((paired["irr_lump"] - paired["irr_dca"]).median())
        if len(paired)
        else None,
        "mean_irr_diff_lump_minus_dca": float((paired["irr_lump"] - paired["irr_dca"]).mean())
        if len(paired)
        else None,
    }


def _summarize_group_b(df: pd.DataFrame) -> dict:
    n = len(df)
    return {
        "n": int(n),
        "dip_win_rate_fv": float(df["dip_wins_fv"].mean()),
        "median_ret_fixed": float(df["ret_fixed"].median()),
        "median_ret_dip": float(df["ret_dip"].median()),
        "median_fv_ratio_dip_over_fixed": float((df["fv_dip"] / df["fv_fixed"]).median()),
        "mean_cash_drag": float(df["cash_drag"].mean()),
        "median_cash_drag": float(df["cash_drag"].median()),
        "never_triggered_rate": float(df["never_triggered"].mean()),
        "mean_n_dip_triggers": float(df["n_dip_triggers"].mean()),
    }


# ----------------------------------------------------------------------------
# Verdicts
# ----------------------------------------------------------------------------
def build_verdicts(all_results: dict) -> dict:
    a_fv_wins, a_irr_diffs, a_irr_win = [], [], []
    for res in all_results.values():
        ov = res["group_a"]["overall"]
        if ov.get("lump_win_rate_fv") is not None:
            a_fv_wins.append(ov["lump_win_rate_fv"])
        if ov.get("lump_win_rate_irr") is not None:
            a_irr_win.append(ov["lump_win_rate_irr"])
        if ov.get("median_irr_diff_lump_minus_dca") is not None:
            a_irr_diffs.append(ov["median_irr_diff_lump_minus_dca"])
    a_fv = float(np.mean(a_fv_wins)) if a_fv_wins else float("nan")
    a_irr_diff = float(np.median(a_irr_diffs)) if a_irr_diffs else None
    a_irr_winrate = float(np.mean(a_irr_win)) if a_irr_win else float("nan")
    prop_a_confirmed = (a_fv > 0.55) and (a_irr_diff is not None and abs(a_irr_diff) < 0.02)
    a_irr_diff_str = f"{a_irr_diff:+.4f}" if a_irr_diff is not None else "NA"

    b_dip_wins, b_drags, b_never = [], [], []
    for res in all_results.values():
        rep = res["group_b"]["dip_10pct"]["overall"]
        b_dip_wins.append(rep["dip_win_rate_fv"])
        b_drags.append(rep["mean_cash_drag"])
        b_never.append(rep["never_triggered_rate"])
    b_dip = float(np.mean(b_dip_wins))
    b_drag = float(np.mean(b_drags))
    b_nev = float(np.mean(b_never))
    prop_b_confirmed = (b_dip < 0.5) and (b_drag > 0.05)

    return {
        "proposition_A": {
            "statement": "總報酬率 Lump Sum 通常勝；但 IRR(資金效率)兩者本質接近相等",
            "mean_lump_win_rate_fv": a_fv,
            "mean_lump_win_rate_irr": a_irr_winrate,
            "median_irr_diff_lump_minus_dca_annualized": a_irr_diff,
            "verdict": "confirmed" if prop_a_confirmed else "mixed",
            "note": (
                f"Lump 終值勝率 {a_fv:.1%}（>55% 確認本金在市場時間長佔優）；"
                f"IRR 年化中位差 {a_irr_diff_str}"
                + (
                    "（<2pp，資金效率接近相等，命題成立）"
                    if (a_irr_diff is not None and abs(a_irr_diff) < 0.02)
                    else "（IRR 差距偏大，需檢視）"
                )
            ),
        },
        "proposition_B": {
            "statement": "囤現金等回檔通常輸給持續投入(cash drag > timing 利益)，time in market > timing",
            "mean_dip_win_rate_fv_at_10pct": b_dip,
            "mean_cash_drag_at_10pct": b_drag,
            "mean_never_triggered_rate_at_10pct": b_nev,
            "verdict": "confirmed" if prop_b_confirmed else "mixed",
            "note": (
                f"10% 門檻 dip-buying 勝率 {b_dip:.1%}（<50% 即輸 fixed）；"
                f"平均閒置現金時間比例 {b_drag:.1%}；"
                f"等不到回檔比例 {b_nev:.1%}。"
                + ("cash drag 成本壓過擇時利益，time-in-market 勝。" if prop_b_confirmed else "結果分歧，需細看 regime。")
            ),
        },
    }


# ----------------------------------------------------------------------------
# Figures
# ----------------------------------------------------------------------------
def fig_a_winrate(all_results: dict, path: Path) -> None:
    regimes = ["bull", "neutral", "bear", "overall"]
    labels = {"bull": "純多頭", "neutral": "中性", "bear": "純空頭", "overall": "整體"}
    keys = list(all_results.keys())
    fig, axes = plt.subplots(1, len(keys), figsize=(4.2 * len(keys), 5), sharey=True)
    if len(keys) == 1:
        axes = [axes]
    for ax, key in zip(axes, keys):
        ga = all_results[key]["group_a"]
        vals = [(ga.get(reg)["lump_win_rate_fv"] * 100 if ga.get(reg) else 0) for reg in regimes]
        x = np.arange(len(regimes))
        bars = ax.bar(x, vals, color=["#c0392b", "#7f8c8d", "#2980b9", "#27ae60"])
        ax.axhline(50, ls="--", c="k", lw=1, alpha=0.6)
        ax.set_xticks(x)
        ax.set_xticklabels([labels[r] for r in regimes])
        ax.set_title(f"{key}\n單筆投入終值勝率(%)")
        ax.set_ylim(0, 100)
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v + 1, f"{v:.0f}", ha="center", fontsize=9)
    axes[0].set_ylabel("單筆投入勝率 (%)")
    fig.suptitle("圖(a) 單筆投入 vs 定期定額：各市場情境終值勝率", fontsize=13)
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    fig.savefig(path, dpi=120)
    plt.close(fig)


def fig_a_dist(all_results: dict, path: Path) -> None:
    keys = list(all_results.keys())
    fig, axes = plt.subplots(2, len(keys), figsize=(4.6 * len(keys), 9))
    if len(keys) == 1:
        axes = axes.reshape(2, 1)
    for j, key in enumerate(keys):
        df = all_results[key]["_raw_a"]
        ax = axes[0, j]
        ax.hist(df["ret_lump"] * 100, bins=60, alpha=0.55, label="單筆投入", color="#2980b9")
        ax.hist(df["ret_dca"] * 100, bins=60, alpha=0.55, label="定期定額", color="#e67e22")
        ax.axvline(df["ret_lump"].median() * 100, c="#2980b9", ls="--", lw=1.5)
        ax.axvline(df["ret_dca"].median() * 100, c="#e67e22", ls="--", lw=1.5)
        ax.set_title(f"{key} 終值總報酬率分布")
        ax.set_xlabel("總報酬率 (%)")
        ax.set_ylabel("路徑數")
        ax.legend()
        ax2 = axes[1, j]
        irr_l = pd.to_numeric(df["irr_lump"], errors="coerce").dropna().to_numpy() * 100
        irr_d = pd.to_numeric(df["irr_dca"], errors="coerce").dropna().to_numpy() * 100
        # 防呆：空陣列不可餵 violinplot（np.min over zero-size 會 crash）
        if len(irr_l) > 1 and len(irr_d) > 1:
            ax2.violinplot([irr_l, irr_d], showmedians=True)
        else:
            if len(irr_l):
                ax2.hist(irr_l, bins=30, alpha=0.55, label="單筆投入", color="#2980b9")
            if len(irr_d):
                ax2.hist(irr_d, bins=30, alpha=0.55, label="定期定額", color="#e67e22")
        ax2.set_xticks([1, 2])
        ax2.set_xticklabels(["單筆投入", "定期定額"])
        ax2.set_title(f"{key} IRR(年化資金效率)對比")
        ax2.set_ylabel("IRR 年化 (%)")
        _il = pd.to_numeric(df["irr_lump"], errors="coerce")
        _id = pd.to_numeric(df["irr_dca"], errors="coerce")
        med_diff = (_il - _id).dropna().median() * 100
        ax2.text(
            0.5, 0.96, f"IRR 中位差(單筆−定額)={med_diff:+.2f}pp",
            transform=ax2.transAxes, ha="center", va="top", fontsize=9,
            bbox=dict(boxstyle="round", fc="white", alpha=0.7),
        )
    fig.suptitle("圖(b) 單筆投入 vs 定期定額：終值報酬率分布 + IRR 資金效率對比", fontsize=13)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(path, dpi=120)
    plt.close(fig)


def fig_b_winrate_drag(all_results: dict, path: Path) -> None:
    keys = list(all_results.keys())
    fig, axes = plt.subplots(1, len(keys), figsize=(4.8 * len(keys), 5.5))
    if len(keys) == 1:
        axes = [axes]
    ths = [f"dip_{int(t*100)}pct" for t in DIP_THRESHOLDS]
    th_lab = [f"{int(t*100)}%" for t in DIP_THRESHOLDS]
    for ax, key in zip(axes, keys):
        gb = all_results[key]["group_b"]
        winrates = [gb[t]["overall"]["dip_win_rate_fv"] * 100 for t in ths]
        drags = [gb[t]["overall"]["mean_cash_drag"] * 100 for t in ths]
        x = np.arange(len(ths))
        w = 0.35
        b1 = ax.bar(x - w / 2, winrates, w, label="逢低買進勝率(%)", color="#8e44ad")
        b2 = ax.bar(x + w / 2, drags, w, label="平均閒置現金時間(%)", color="#16a085")
        ax.axhline(50, ls="--", c="k", lw=1, alpha=0.6)
        ax.set_xticks(x)
        ax.set_xticklabels([f"回檔門檻 {l}" for l in th_lab])
        ax.set_title(f"{key}")
        ax.set_ylim(0, 100)
        for bb in (b1, b2):
            for r in bb:
                ax.text(r.get_x() + r.get_width() / 2, r.get_height() + 1, f"{r.get_height():.0f}", ha="center", fontsize=8)
        ax.legend(fontsize=9)
    fig.suptitle("圖(c) 逢低買進 vs 持續投入：勝率(<50% 即輸) + 現金閒置成本", fontsize=13)
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    fig.savefig(path, dpi=120)
    plt.close(fig)


def fig_b_dist_never(all_results: dict, path: Path) -> None:
    keys = list(all_results.keys())
    fig, axes = plt.subplots(2, len(keys), figsize=(4.6 * len(keys), 9))
    if len(keys) == 1:
        axes = axes.reshape(2, 1)
    rep_th = 0.10
    ths = [f"dip_{int(t*100)}pct" for t in DIP_THRESHOLDS]
    th_lab = [f"{int(t*100)}%" for t in DIP_THRESHOLDS]
    for j, key in enumerate(keys):
        df = all_results[key]["_raw_b"][rep_th]
        ax = axes[0, j]
        ax.hist(df["ret_fixed"] * 100, bins=60, alpha=0.55, label="持續投入", color="#16a085")
        ax.hist(df["ret_dip"] * 100, bins=60, alpha=0.55, label="逢低買進(10%)", color="#8e44ad")
        ax.axvline(df["ret_fixed"].median() * 100, c="#16a085", ls="--", lw=1.5)
        ax.axvline(df["ret_dip"].median() * 100, c="#8e44ad", ls="--", lw=1.5)
        ax.set_title(f"{key} 終值報酬率分布(10% 門檻)")
        ax.set_xlabel("總報酬率 (%)")
        ax.set_ylabel("路徑數")
        ax.legend()
        ax2 = axes[1, j]
        gb = all_results[key]["group_b"]
        nevers = [gb[t]["overall"]["never_triggered_rate"] * 100 for t in ths]
        x = np.arange(len(ths))
        bars = ax2.bar(x, nevers, color="#c0392b")
        ax2.set_xticks(x)
        ax2.set_xticklabels([f"門檻 {l}" for l in th_lab])
        ax2.set_title(f"{key} 「等不到回檔」路徑比例")
        ax2.set_ylabel("等不到回檔比例 (%)")
        ax2.set_ylim(0, max(nevers) * 1.3 + 5)
        for b, v in zip(bars, nevers):
            ax2.text(b.get_x() + b.get_width() / 2, v + 0.5, f"{v:.1f}", ha="center", fontsize=9)
    fig.suptitle("圖(d) 逢低買進：終值分布 + 等不到回檔比例", fontsize=13)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(path, dpi=120)
    plt.close(fig)


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main() -> None:
    rng = np.random.default_rng(SEED)
    data_meta, rets_map = {}, {}
    for name, cfg in ASSETS.items():
        s, meta = load_prices(name, cfg)
        data_meta[name] = meta
        rets_map[name] = daily_returns(s)
        print(f"[DATA] {name}: {meta['source']} n={meta['n_days']} {meta['start']}..{meta['end']}")

    all_results: dict[str, dict] = {}
    for name in ASSETS:
        for hkey, hdays in HORIZONS.items():
            key = f"{name}_{hkey}"
            print(f"[RUN] {key} horizon_days={hdays} ...")
            res = run_asset_horizon(name, rets_map[name], hdays, rng)
            all_results[key] = res
            print(
                f"      n_paths={res['n_paths']} regimes={res['regime_counts']} "
                f"A.lump_fv_win={res['group_a']['overall']['lump_win_rate_fv']:.3f} "
                f"B10.dip_win={res['group_b']['dip_10pct']['overall']['dip_win_rate_fv']:.3f} "
                f"B10.drag={res['group_b']['dip_10pct']['overall']['mean_cash_drag']:.3f}"
            )

    try:
        verdicts = build_verdicts(all_results)
    except Exception as exc:  # noqa: BLE001 — verdict assembly must never lose core results/figures
        print(f"[WARN] build_verdicts failed: {exc!r} -> verdicts=error, core results still saved")
        verdicts = {"error": f"{type(exc).__name__}: {exc}"}

    # ---- 先寫 JSON（核心結果不可被畫圖失敗拖垮）----
    out = {
        "experiment_id": "k1406",
        "title": "投資時機策略 conditional block bootstrap：DCA vs Lump Sum，逢低買進 vs 持續投入",
        "seed": SEED,
        "block_size": BLOCK,
        "horizons": HORIZONS,
        "n_boot_target": N_BOOT_TARGET,
        "regime_min": REGIME_MIN,
        "irr_subsample": IRR_SUBSAMPLE,
        "regime_definition": {
            "bull": "路徑年化報酬 > +10%",
            "bear": "路徑年化報酬 < -10%",
            "neutral": "其間",
        },
        "dip_thresholds": DIP_THRESHOLDS,
        "dip_high_window_days": DIP_HIGH_WINDOW,
        "dca_periods": DCA_PERIODS,
        "dca_step_days": DCA_STEP,
        "lag_correctness_note": (
            "dip 觸發 rolling high 用 prices[max(0,t-W):t]（不含 t），等同 .shift(1)，"
            "決策只用 t-1 及更早；DCA/LumpSum 投入時點外生固定，無 lookahead。"
        ),
        "irr_note": (
            f"FV 勝率/報酬/cash-drag 用全 bootstrap 樣本；IRR(grid-scan 較慢)只對每 horizon "
            f"前 {IRR_SUBSAMPLE} 條路徑計算（n_irr 欄位記實際有效樣本）。"
        ),
        "execution_timing_assumption": (
            "Dip-buying 在 day t 觀察回檔（high 只用 t-1 及更早）後以同日 prices[t] 收盤價成交"
            "（收盤觀察、收盤可交易，與 PRG/PRS 系列一致），非跨日 lookahead。"
        ),
        "codex_review": "CONDITIONAL_PASS — 無硬性跨期 lookahead 或 paired-comparison bug；唯一 caveat 為上述同日成交假設（已明示）。",
        "data": data_meta,
        "results": {},
        "verdicts": verdicts,
    }
    for key, res in all_results.items():
        out["results"][key] = {k: v for k, v in res.items() if not k.startswith("_")}

    out_path = HERE / "k1406_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("[JSON] wrote", out_path)

    # ---- 再畫圖（每張各自 try/except，一張失敗不拖垮其他與 json）----
    figure_jobs = [
        (fig_a_winrate, "fig_a_dca_vs_lump_winrate.png"),
        (fig_a_dist, "fig_b_dca_vs_lump_dist_irr.png"),
        (fig_b_winrate_drag, "fig_c_dip_vs_fixed_winrate_drag.png"),
        (fig_b_dist_never, "fig_d_dip_dist_never.png"),
    ]
    n_ok = 0
    for fn, fname in figure_jobs:
        try:
            fn(all_results, FIG_DIR / fname)
            n_ok += 1
            print(f"[FIG] OK {fname}")
        except Exception as exc:  # noqa: BLE001
            print(f"[FIG] FAILED {fname}: {type(exc).__name__}: {exc}")
    print(f"[FIG] {n_ok}/{len(figure_jobs)} figures saved to {FIG_DIR}")

    print("\n=== VERDICTS ===")
    if "proposition_A" in verdicts:
        print("Prop A:", verdicts["proposition_A"]["verdict"], "|", verdicts["proposition_A"]["note"])
        print("Prop B:", verdicts["proposition_B"]["verdict"], "|", verdicts["proposition_B"]["note"])
    else:
        print("verdicts error:", verdicts.get("error"))


if __name__ == "__main__":
    main()
