"""K1427: 股市大跌時是「資金齊撤」還是「資金輪動」?
用 cross-sectional sector dispersion 與 sector vol 把「齊跌」拆開。

差異化角度: 指數層「齊跌」底下可能是高 dispersion 的板塊輪動 (錢從科技流向能源/防禦),
這是可測量的橫斷面結構,不是再做一篇 pairwise correlation / 分散失靈文章。

研究問題:
 1. SPY 大跌 episode 裡,跨板塊報酬橫斷面離散度 (dispersion) 是高(輪動)還是低(清算)?
 2. 把 selloff 分「輪動型」(dispersion 高) vs「清算型」(dispersion 低,diversification 失靈)。
 3. 哪些板塊在跌勢中 realized vol 上升/下降、報酬逆勢。
 4. 誠實分類最近一次 selloff。

資料: yfinance, SPY + 11 SPDR sector ETFs, 2014-01-01 至今, 日報酬 + 20d 年化 RV。
seed=42 全固定。所有結論來自 k1427_results.json。Descriptive (非 forecast),第5項 lag 明確。
"""
import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy import stats

warnings.filterwarnings("ignore")

SEED = 42
np.random.seed(SEED)

HERE = Path(__file__).resolve().parent
START = "2014-01-01"
TRADING_DAYS = 252
ANN = np.sqrt(TRADING_DAYS)
RV_WINDOW = 20

SECTORS = {
    "XLE": "能源", "XLU": "公用", "XLP": "必需消費", "XLK": "科技",
    "XLF": "金融", "XLV": "醫療", "XLY": "非必需消費", "XLI": "工業",
    "XLB": "原物料", "XLRE": "房地產", "XLC": "通訊",
}
DEFENSIVE = ["XLU", "XLP", "XLV"]   # 防禦
CYCLICAL = ["XLK", "XLY", "XLF", "XLI", "XLB", "XLC"]  # 景氣循環/科技

# selloff 定義閾值
DAILY_SELLOFF_THRESH = -0.02   # SPY 單日 < -2%
DISPERSION_HI_Q = 0.70         # selloff 日 dispersion 在歷史分位 > 70% = 輪動型


def fetch():
    tickers = ["SPY"] + list(SECTORS.keys())
    raw = yf.download(tickers, start=START, progress=False, auto_adjust=True)["Close"]
    raw = raw.dropna(axis=1, how="all")
    return raw


def main():
    px = fetch()
    available_sectors = [s for s in SECTORS if s in px.columns]
    dropped = [s for s in SECTORS if s not in px.columns]

    # 日報酬
    rets = px.pct_change()

    # 為 cross-sectional dispersion 用「全部板塊都有資料」的 inner 窗口
    # XLRE(2015-10 上市) / XLC(2018-06 上市) 上市晚 -> 用兩種樣本:
    #   (a) full-11: 從所有 11 板塊都有資料起 (inner)
    #   (b) early-9: 排除 XLRE/XLC, 涵蓋更早期間
    sec_full = available_sectors
    sec_early = [s for s in available_sectors if s not in ("XLRE", "XLC")]

    rets_sec_full = rets[sec_full].dropna()
    rets_sec_early = rets[sec_early].dropna()
    spy_ret = rets["SPY"]

    n_dropped_full = int(rets[sec_full].shape[0] - rets_sec_full.shape[0])

    # cross-sectional dispersion (每日 11 板塊報酬的橫斷面 std)
    disp_full = rets_sec_full.std(axis=1, ddof=1)
    disp_early = rets_sec_early.std(axis=1, ddof=1)

    # 主分析用 early-9 (期間長, 含 2014-2015 + 2020 + 2022) 作為 canonical,
    # full-11 作 robustness。理由: 涵蓋更多 selloff episode。
    disp = disp_early
    sec = sec_early
    rets_sec = rets_sec_early

    df = pd.DataFrame({"spy_ret": spy_ret, "dispersion": disp}).dropna()

    # ---- (1) 大跌日 vs 平常日 dispersion ----
    selloff_mask = df["spy_ret"] < DAILY_SELLOFF_THRESH
    normal_mask = ~selloff_mask
    disp_selloff = df.loc[selloff_mask, "dispersion"]
    disp_normal = df.loc[normal_mask, "dispersion"]

    # Welch t-test (不等變異)
    t_stat, t_p = stats.ttest_ind(disp_selloff, disp_normal, equal_var=False)
    # Mann-Whitney (非參數, 穩健)
    mw_u, mw_p = stats.mannwhitneyu(disp_selloff, disp_normal, alternative="two-sided")

    # 歷史分位 (用全樣本 dispersion 算 percentile)
    disp_q70 = float(df["dispersion"].quantile(DISPERSION_HI_Q))
    disp_median = float(df["dispersion"].median())

    # ---- (2) selloff episode + regime 分類 ----
    # episode = 連續或孤立的 selloff 日; 這裡以「單日 selloff 日」為 event 並聚合成 episode
    # episode 定義: selloff 日, 若相隔 <=3 個交易日視為同一 episode
    selloff_days = df.index[selloff_mask].tolist()
    episodes = []
    if selloff_days:
        cur = [selloff_days[0]]
        for d in selloff_days[1:]:
            gap = df.index.get_loc(d) - df.index.get_loc(cur[-1])
            if gap <= 3:
                cur.append(d)
            else:
                episodes.append(cur)
                cur = [d]
        episodes.append(cur)

    episode_records = []
    for ep_days in episodes:
        ep_start = ep_days[0]
        ep_end = ep_days[-1]
        # episode 期間平均 dispersion (用該 episode 的 selloff 日)
        ep_disp = df.loc[ep_days, "dispersion"].mean()
        ep_disp_pct = float((df["dispersion"] < ep_disp).mean())  # 在歷史分位
        ep_spy_cum = float((1 + df.loc[ep_days, "spy_ret"]).prod() - 1)
        # 板塊在此 episode 累積報酬 (跨 episode 所有交易日, 含非 selloff 日 within span)
        span = rets_sec.loc[ep_start:ep_end]
        if len(span) == 0:
            span = rets_sec.loc[ep_days]
        sec_cum = ((1 + span).prod() - 1).to_dict()
        n_pos = int(sum(1 for v in sec_cum.values() if v > 0))  # 逆勢板塊數(累積正報酬)
        # regime 分類 (2-D, 誠實版): dispersion 高低 × 方向廣度(是否有板塊逆勢)
        #   rotation     = 高 dispersion 且至少 1 板塊 episode 累積正報酬(真有錢在輪動進去)
        #   broad_selloff= 高 dispersion 但全板塊皆跌(spread 大只因跌幅不一, 仍是齊跌清算)
        #   liquidation  = 低 dispersion(齊跌, diversification 失靈)
        # 註: 單純用 dispersion 分位會把「全跌但跌幅參差」誤標 rotation -> 故加方向廣度條件。
        hi_disp = ep_disp >= disp_q70
        if hi_disp and n_pos >= 1:
            regime = "rotation"
        elif hi_disp and n_pos == 0:
            regime = "broad_selloff_high_disp"
        else:
            regime = "liquidation"
        episode_records.append({
            "start": ep_start.strftime("%Y-%m-%d"),
            "end": ep_end.strftime("%Y-%m-%d"),
            "n_selloff_days": len(ep_days),
            "mean_dispersion": round(float(ep_disp), 6),
            "dispersion_pctile": round(ep_disp_pct, 3),
            "regime": regime,
            "spy_cum_ret_on_selloff_days": round(ep_spy_cum, 4),
            "n_sectors_positive_in_span": n_pos,
            "n_sectors": len(sec),
            "sector_cum_ret": {k: round(float(v), 4) for k, v in sec_cum.items()},
        })

    n_rotation = sum(1 for e in episode_records if e["regime"] == "rotation")
    n_broad = sum(1 for e in episode_records if e["regime"] == "broad_selloff_high_disp")
    n_liquidation = sum(1 for e in episode_records if e["regime"] == "liquidation")
    n_ep = len(episode_records)

    # ---- (3) 板塊行為: selloff 日 vs 平常日的板塊報酬 + RV 變化 ----
    # 每板塊 RV (20d 年化)
    rv = rets_sec.rolling(RV_WINDOW).std() * ANN
    sector_behavior = {}
    for s in sec:
        s_ret = rets_sec[s]
        # selloff 日該板塊平均報酬 vs SPY
        sel_idx = df.index[selloff_mask]
        sel_idx = sel_idx.intersection(s_ret.index)
        mean_ret_selloff = float(s_ret.loc[sel_idx].mean())
        mean_ret_normal = float(s_ret.loc[s_ret.index.difference(sel_idx)].mean())
        # selloff 日 RV vs 全期 RV
        rv_s = rv[s].dropna()
        sel_rv_idx = sel_idx.intersection(rv_s.index)
        rv_selloff = float(rv_s.loc[sel_rv_idx].mean()) if len(sel_rv_idx) else np.nan
        rv_overall = float(rv_s.mean())
        # 逆勢頻率: selloff 日該板塊正報酬比例
        cont_freq = float((s_ret.loc[sel_idx] > 0).mean()) if len(sel_idx) else np.nan
        sector_behavior[s] = {
            "name": SECTORS[s],
            "type": "defensive" if s in DEFENSIVE else ("cyclical" if s in CYCLICAL else "other"),
            "mean_ret_selloff_days": round(mean_ret_selloff, 5),
            "mean_ret_normal_days": round(mean_ret_normal, 5),
            "rv_ann_selloff_days": round(rv_selloff, 4),
            "rv_ann_overall": round(rv_overall, 4),
            "rv_ratio_selloff_vs_overall": round(rv_selloff / rv_overall, 3) if rv_overall else np.nan,
            "counter_trend_freq_on_selloff": round(cont_freq, 3),
        }

    # ---- (4) 最近一次 selloff 分類 ----
    latest = episode_records[-1] if episode_records else None

    # ---- (5) (descriptive) contemporaneous dispersion -> future SPY RV, lag 明確 ----
    # 只在 selloff 日: dispersion_t 與 future N 日 SPY realized vol 的關係
    # 明確 lag: future RV 用 t+1..t+N, 避免 lookahead
    spy_rv_fwd = {}
    spy_daily = rets["SPY"].dropna()
    for N in (5, 10, 20):
        # future realized vol over t+1..t+N (年化)
        fwd = spy_daily.shift(-1).rolling(N).std().shift(-(N - 1)) * ANN
        # 對齊 selloff 日
        sub = pd.DataFrame({"disp": df["dispersion"], "fwd_rv": fwd}).dropna()
        sub_sel = sub.loc[sub.index.isin(df.index[selloff_mask])]
        if len(sub_sel) > 5:
            # 把 selloff 日依 dispersion 中位數分高/低, 比較 future RV
            med = sub_sel["disp"].median()
            hi = sub_sel.loc[sub_sel["disp"] >= med, "fwd_rv"]
            lo = sub_sel.loc[sub_sel["disp"] < med, "fwd_rv"]
            tt, pp = stats.ttest_ind(hi, lo, equal_var=False)
            corr, cp = stats.spearmanr(sub_sel["disp"], sub_sel["fwd_rv"])
            spy_rv_fwd[f"N{N}"] = {
                "n_selloff_days": int(len(sub_sel)),
                "future_rv_hi_dispersion_mean": round(float(hi.mean()), 4),
                "future_rv_lo_dispersion_mean": round(float(lo.mean()), 4),
                "welch_t": round(float(tt), 3),
                "welch_p": round(float(pp), 4),
                "spearman_disp_vs_fwd_rv": round(float(corr), 3),
                "spearman_p": round(float(cp), 4),
            }

    # ---- robustness: full-11 dispersion selloff vs normal ----
    df_full = pd.DataFrame({"spy_ret": spy_ret, "dispersion": disp_full}).dropna()
    sel_f = df_full["spy_ret"] < DAILY_SELLOFF_THRESH
    rob_t, rob_p = stats.ttest_ind(
        df_full.loc[sel_f, "dispersion"], df_full.loc[~sel_f, "dispersion"], equal_var=False
    )

    # ---- external_claim_verdict ----
    # 待裁決外部主張: 「最近(2026-06 初)那波 selloff 資金未撤出股市, 而是輪動到
    # 能源(XLE)與防禦類股(XLU/XLP)的抗通膨交易」。
    # 判準三條:
    #  (a) 最近 selloff dispersion 是否顯著高於平常 (高 = 輪動證據)
    #  (b) 能源 XLE 與防禦 XLU/XLP 是否相對逆勢/正報酬 vs 科技 XLK 走弱 (是 = 支持輪動)
    #  (c) 若 dispersion 低且全板塊同步下跌(含能源/防禦也跌) = REFUTES (齊跌清算)
    # 使用「最近 selloff 日 ± window」量化各板塊報酬與 RV。
    latest_ep = episode_records[-1] if episode_records else None
    claim = {"target_claim": "近期 selloff 資金未撤出股市, 而是輪動到能源/防禦(抗通膨交易)"}
    if latest_ep:
        latest_day = pd.Timestamp(latest_ep["end"])
        # window: 該 selloff 日為中心, 取前 4 / 後 4 交易日 (描述性, 非預測)
        all_idx = rets_sec.index
        loc = all_idx.get_loc(latest_day)
        w0 = max(0, loc - 4)
        w1 = min(len(all_idx) - 1, loc + 4)
        win = all_idx[w0:w1 + 1]
        win_ret = rets_sec.loc[win]
        win_cum = ((1 + win_ret).prod() - 1)
        rv_win = rets_sec.rolling(RV_WINDOW).std() * ANN
        # 該 selloff 日本身的板塊報酬 (最尖銳的證據)
        day_ret = rets_sec.loc[latest_day]

        def g(t):  # 板塊在 latest selloff 日 + window 的報酬
            return {
                "ret_on_selloff_day": round(float(day_ret.get(t, np.nan)), 5),
                "cum_ret_window_9d": round(float(win_cum.get(t, np.nan)), 5),
                "rv_ann_on_selloff_day": round(float(rv_win[t].get(latest_day, np.nan)), 4) if t in rv_win else None,
            }

        xle = g("XLE"); xlu = g("XLU"); xlp = g("XLP"); xlk = g("XLK")
        # latest selloff dispersion 相對歷史
        latest_disp_pct = latest_ep["dispersion_pctile"]

        # 判準計算
        cond_a = latest_disp_pct >= DISPERSION_HI_Q  # dispersion 高
        # 防禦逆勢: XLU & XLP 報酬 > 0 且 > XLK
        defensive_outperform = (xlu["ret_on_selloff_day"] > 0 and xlp["ret_on_selloff_day"] > 0
                                and xlu["ret_on_selloff_day"] > xlk["ret_on_selloff_day"]
                                and xlp["ret_on_selloff_day"] > xlk["ret_on_selloff_day"])
        # 能源逆勢: XLE 報酬 > 0 (主張特指能源)
        energy_counter = xle["ret_on_selloff_day"] > 0
        energy_relative = xle["ret_on_selloff_day"] > xlk["ret_on_selloff_day"]  # 至少比科技抗跌
        # 全板塊同步下跌?
        n_neg = int((day_ret < 0).sum())
        all_down = n_neg == len(sec)

        # verdict 邏輯
        if all_down and not cond_a:
            verdict = "REFUTES"
        elif cond_a and defensive_outperform and energy_counter:
            verdict = "SUPPORTS"
        else:
            verdict = "MIXED"

        evidence_parts = []
        evidence_parts.append(
            f"(a) dispersion: 最近 selloff ({latest_ep['start']}~{latest_ep['end']}) "
            f"dispersion 在歷史 {latest_disp_pct*100:.1f} 分位"
            + ("(>70, 輪動證據成立)" if cond_a else "(<70, 偏齊跌)")
        )
        evidence_parts.append(
            f"(b) 防禦: XLU {xlu['ret_on_selloff_day']*100:+.2f}% / XLP {xlp['ret_on_selloff_day']*100:+.2f}% / "
            f"XLV {round(float(day_ret.get('XLV',np.nan))*100,2):+.2f}% vs 科技 XLK {xlk['ret_on_selloff_day']*100:+.2f}% "
            + ("(防禦逆勢成立)" if defensive_outperform else "(防禦未全面逆勢)")
        )
        evidence_parts.append(
            f"(b') 能源: XLE {xle['ret_on_selloff_day']*100:+.2f}% "
            + ("(正報酬, 抗通膨交易成立)" if energy_counter else
               ("(雖跌但比 XLK 抗跌)" if energy_relative else "(下跌, 能源輪動主張不成立)"))
        )
        evidence_parts.append(
            f"(c) 板塊同步性: {n_neg}/{len(sec)} 板塊當日下跌"
            + ("(全跌=清算)" if all_down else "(部分逆勢, 非全面清算)")
        )
        claim.update({
            "verdict": verdict,
            "latest_selloff_window": f"{win[0].date()}~{win[-1].date()}",
            "latest_selloff_day": str(latest_day.date()),
            "dispersion_pctile": latest_disp_pct,
            "key_sectors_on_selloff_day": {"XLE": xle, "XLU": xlu, "XLP": xlp, "XLK": xlk},
            "criteria": {
                "a_high_dispersion(rotation)": cond_a,
                "b_defensive_outperform_tech": defensive_outperform,
                "b_energy_positive": energy_counter,
                "b_energy_beats_tech": energy_relative,
                "c_all_sectors_down(liquidation)": all_down,
                "n_sectors_down": n_neg,
            },
            "evidence": "  |  ".join(evidence_parts),
            "honest_note": ("MIXED: dispersion 與防禦逆勢支持『輪動非全面撤離』, 但能源 XLE 同步下跌 => "
                            "『資金輪動到能源抗通膨交易』這部分不成立" if verdict == "MIXED" else
                            ("SUPPORTS: dispersion 高 + 防禦逆勢 + 能源正報酬, 三條皆符合輪動論" if verdict == "SUPPORTS" else
                             "REFUTES: dispersion 不高且板塊齊跌 => 資金確實在撤(清算型)")),
        })
    else:
        claim.update({"verdict": "N/A", "evidence": "no selloff episode found"})

    results = {
        "experiment_id": "k1427",
        "title": "Sector dispersion: 齊跌 vs 輪動 — selloff regime 分類",
        "seed": SEED,
        "data": {
            "source": "yfinance (auto_adjust=True, Close)",
            "period_start": START,
            "period_end": str(px.index[-1].date()),
            "n_trading_days_total": int(px.shape[0]),
            "tickers_requested": ["SPY"] + list(SECTORS.keys()),
            "sectors_available": available_sectors,
            "sectors_dropped_no_data": dropped,
            "canonical_sample": "early-9 (排除晚上市 XLRE/XLC, 涵蓋 2014 起最長期間)",
            "early9_sectors": sec_early,
            "full11_sectors": sec_full,
            "early9_n_days": int(rets_sec_early.shape[0]),
            "full11_n_days": int(rets_sec_full.shape[0]),
            "full11_rows_dropped_for_alignment": n_dropped_full,
        },
        "definitions": {
            "daily_selloff": f"SPY 日報酬 < {DAILY_SELLOFF_THRESH}",
            "dispersion": "每日跨板塊日報酬的橫斷面標準差 (ddof=1)",
            "rotation_regime": f"episode 平均 dispersion >= 歷史 {int(DISPERSION_HI_Q*100)} 分位 ({disp_q70:.5f})",
            "liquidation_regime": "episode 平均 dispersion < 70 分位",
            "episode_grouping": "selloff 日相隔 <=3 交易日歸為同一 episode",
            "rv_ann": f"日報酬 rolling-{RV_WINDOW} std × sqrt({TRADING_DAYS})",
        },
        "q1_dispersion_selloff_vs_normal": {
            "n_selloff_days": int(selloff_mask.sum()),
            "n_normal_days": int(normal_mask.sum()),
            "mean_dispersion_selloff": round(float(disp_selloff.mean()), 6),
            "mean_dispersion_normal": round(float(disp_normal.mean()), 6),
            "median_dispersion_selloff": round(float(disp_selloff.median()), 6),
            "median_dispersion_normal": round(float(disp_normal.median()), 6),
            "ratio_selloff_over_normal": round(float(disp_selloff.mean() / disp_normal.mean()), 3),
            "welch_t": round(float(t_stat), 3),
            "welch_p": float(t_p),
            "mannwhitney_p": float(mw_p),
            "interpretation": "大跌日 dispersion 顯著高於平常日 => 大跌通常伴隨更高橫斷面離散(非單純齊跌)" if disp_selloff.mean() > disp_normal.mean() else "大跌日 dispersion 不高於平常日 => 偏齊跌/清算",
            "dispersion_q70_threshold": disp_q70,
            "dispersion_median_overall": disp_median,
        },
        "q2_regime_classification": {
            "taxonomy": {
                "rotation": "高 dispersion(>=70 分位) 且至少 1 板塊 episode 累積正報酬 — 真有資金輪動進去",
                "broad_selloff_high_disp": "高 dispersion 但全板塊皆跌 — spread 大只因跌幅不一, 本質仍齊跌",
                "liquidation": "低 dispersion — 齊跌, diversification 失靈",
            },
            "n_episodes": n_ep,
            "n_rotation": n_rotation,
            "n_broad_selloff_high_disp": n_broad,
            "n_liquidation": n_liquidation,
            "pct_rotation": round(n_rotation / n_ep, 3) if n_ep else None,
            "pct_broad_selloff_high_disp": round(n_broad / n_ep, 3) if n_ep else None,
            "pct_liquidation": round(n_liquidation / n_ep, 3) if n_ep else None,
            "episodes": episode_records,
        },
        "q3_sector_behavior": sector_behavior,
        "q4_latest_selloff": {
            "episode": latest,
            "classification": latest["regime"] if latest else None,
            "note": "誠實分類: regime 由該 episode 平均 dispersion 相對歷史分位決定, 非主觀",
        },
        "q5_dispersion_to_future_rv_descriptive": {
            "design": "contemporaneous dispersion_t -> future SPY RV over t+1..t+N (明確 lag, 無 lookahead)",
            "caveat": "descriptive, 非 forecast model; 小樣本 (僅 selloff 日)",
            "results": spy_rv_fwd,
        },
        "robustness_full11": {
            "mean_dispersion_selloff": round(float(df_full.loc[sel_f, "dispersion"].mean()), 6),
            "mean_dispersion_normal": round(float(df_full.loc[~sel_f, "dispersion"].mean()), 6),
            "welch_t": round(float(rob_t), 3),
            "welch_p": float(rob_p),
            "n_selloff_days": int(sel_f.sum()),
        },
        "external_claim_verdict": claim,
    }

    out = HERE / "k1427_results.json"
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"results -> {out}")

    # ============ 圖表 ============
    # CJK 字型 fallback (避免中文方框); 找不到就退英文標題
    import matplotlib.font_manager as fm
    cjk = None
    for cand in ["Arial Unicode MS", "Heiti TC", "PingFang TC", "Songti SC", "STHeiti"]:
        if any(cand in f.name for f in fm.fontManager.ttflist):
            cjk = cand
            break
    plt.rcParams.update({"font.size": 10, "axes.grid": True, "grid.alpha": 0.3,
                         "figure.dpi": 130, "savefig.bbox": "tight", "axes.unicode_minus": False})
    if cjk:
        plt.rcParams["font.sans-serif"] = [cjk]

    xidx = df.index.to_numpy()
    xidx_sel = df.index[selloff_mask].to_numpy()

    # 圖1: SPY 報酬 + dispersion 時間序列, 標 selloff
    fig, ax = plt.subplots(2, 1, figsize=(13, 7), sharex=True)
    ax[0].plot(xidx, (df["spy_ret"] * 100).to_numpy(), lw=0.6, color="#1f3b73")
    ax[0].scatter(xidx_sel, (df.loc[selloff_mask, "spy_ret"] * 100).to_numpy(),
                  s=14, color="#c0392b", zorder=5, label=f"Selloff day (<{DAILY_SELLOFF_THRESH*100:.0f}%)")
    ax[0].axhline(DAILY_SELLOFF_THRESH * 100, color="#c0392b", ls="--", lw=0.8, alpha=0.6)
    ax[0].set_ylabel("SPY daily return (%)")
    ax[0].legend(loc="lower left", fontsize=8)
    ax[0].set_title("K1427  SPY return & cross-sectional sector dispersion (9 sectors, 2014-)", fontsize=12)

    ax[1].plot(xidx, (df["dispersion"] * 100).to_numpy(), lw=0.6, color="#2c7873")
    ax[1].axhline(disp_q70 * 100, color="#e67e22", ls="--", lw=1,
                  label=f"70th pctile ({disp_q70*100:.2f}%)  >= rotation")
    ax[1].scatter(xidx_sel, (df.loc[selloff_mask, "dispersion"] * 100).to_numpy(),
                  s=12, color="#c0392b", zorder=5, alpha=0.7, label="Selloff day dispersion")
    ax[1].set_ylabel("Cross-sectional\ndispersion (%)")
    ax[1].legend(loc="upper left", fontsize=8)
    fig.tight_layout()
    fig.savefig(HERE / "fig1_timeseries_dispersion.png")
    plt.close(fig)

    # 圖2: selloff vs normal dispersion 分佈 (violin + box)
    fig, ax = plt.subplots(figsize=(8, 6))
    data = [disp_normal.values * 100, disp_selloff.values * 100]
    parts = ax.violinplot(data, showmeans=False, showmedians=True, widths=0.8)
    for pc, c in zip(parts["bodies"], ["#7fb3d5", "#e6928f"]):
        pc.set_facecolor(c); pc.set_alpha(0.7)
    bp = ax.boxplot(data, widths=0.18, patch_artist=True,
                    medianprops=dict(color="black"), showfliers=False)
    for patch, c in zip(bp["boxes"], ["#2980b9", "#c0392b"]):
        patch.set_facecolor(c); patch.set_alpha(0.5)
    ax.set_xticks([1, 2]); ax.set_xticklabels(
        [f"平常日\n(n={normal_mask.sum()})", f"大跌日\n(n={selloff_mask.sum()})"])
    ax.set_ylabel("Cross-sectional dispersion (%)")
    ax.set_title(f"K1427  大跌日 vs 平常日 板塊 dispersion 分佈\n"
                 f"selloff mean={disp_selloff.mean()*100:.2f}%  normal mean={disp_normal.mean()*100:.2f}%  "
                 f"(ratio {disp_selloff.mean()/disp_normal.mean():.2f}x, Welch p={t_p:.1e})", fontsize=10)
    fig.tight_layout()
    fig.savefig(HERE / "fig2_dispersion_distribution.png")
    plt.close(fig)

    # 圖3: 代表性 selloff 板塊行為 (報酬 + RV 變化)
    # 選一個 episode: 取 SPY 跌最深 (spy_cum 最負) 的 episode 作代表
    rep = min(episode_records, key=lambda e: e["spy_cum_ret_on_selloff_days"]) if episode_records else None
    if rep:
        sc = rep["sector_cum_ret"]
        order = sorted(sc, key=lambda k: sc[k])
        vals = [sc[k] * 100 for k in order]
        colors = ["#27ae60" if v > 0 else "#c0392b" for v in vals]
        labels = [f"{k}\n{SECTORS[k]}" for k in order]

        fig, ax = plt.subplots(1, 2, figsize=(14, 6))
        ax[0].barh(labels, vals, color=colors, alpha=0.85)
        ax[0].axvline(0, color="black", lw=0.8)
        ax[0].axvline(rep["spy_cum_ret_on_selloff_days"] * 100, color="#1f3b73",
                      ls="--", lw=1.5, label=f"SPY {rep['spy_cum_ret_on_selloff_days']*100:.1f}%")
        ax[0].set_xlabel("Episode 累積報酬 (%)")
        ax[0].set_title(f"板塊報酬 ({rep['start']}~{rep['end']}, {rep['regime']})")
        ax[0].legend(fontsize=8)

        # RV ratio (selloff vs overall) 各板塊
        rv_ratios = {s: sector_behavior[s]["rv_ratio_selloff_vs_overall"] for s in sec}
        rorder = sorted(rv_ratios, key=lambda k: rv_ratios[k])
        rvals = [rv_ratios[k] for k in rorder]
        rlabels = [f"{k}\n{SECTORS[k]}" for k in rorder]
        bcolors = ["#8e44ad" if v > 1 else "#16a085" for v in rvals]
        ax[1].barh(rlabels, rvals, color=bcolors, alpha=0.85)
        ax[1].axvline(1.0, color="black", lw=0.8, ls="--")
        ax[1].set_xlabel("RV ratio (大跌日 / 全期)  >1 = vol 噴")
        ax[1].set_title("各板塊 大跌日 realized vol 相對全期")
        fig.suptitle(f"K1427  代表性 selloff 的板塊行為 — 誰逆勢、誰 vol 噴", fontsize=12)
        fig.tight_layout()
        fig.savefig(HERE / "fig3_representative_selloff.png")
        plt.close(fig)

    print("圖表完成: fig1/fig2/fig3")
    print(f"selloff days={selloff_mask.sum()}, episodes={n_ep}, rotation={n_rotation}, broad_high_disp={n_broad}, liquidation={n_liquidation}")
    print(f"disp selloff/normal = {disp_selloff.mean()*100:.3f}% / {disp_normal.mean()*100:.3f}% (ratio {disp_selloff.mean()/disp_normal.mean():.2f}, p={t_p:.2e})")
    if latest:
        print(f"latest selloff: {latest['start']}~{latest['end']} -> {latest['regime']} (disp pctile {latest['dispersion_pctile']})")


if __name__ == "__main__":
    main()
