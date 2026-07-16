"""Compute panic half-life evidence for digest_20260716 (real yfinance data)."""
import json
import numpy as np
import pandas as pd

OUT = "/Users/yhlai0911/volpred-research/storage/drafts/assets/digest_20260716"

vix = pd.read_csv(f"{OUT}/vix_close.csv", index_col=0, parse_dates=True)["Close"]
ovx = pd.read_csv(f"{OUT}/ovx_close.csv", index_col=0, parse_dates=True)["Close"]
wti = pd.read_csv(f"{OUT}/wti_close.csv", index_col=0, parse_dates=True)["Close"]


def half_life(series, event_start, window_start, window_end):
    """baseline = median of 20 trading days strictly before event_start;
    peak = max close in [window_start, window_end];
    half_life = trading days from peak date to first close < (peak+baseline)/2."""
    pre = series[series.index < pd.Timestamp(event_start)].tail(20)
    baseline = float(pre.median())
    win = series[window_start:window_end]
    peak = float(win.max())
    peak_date = win.idxmax()
    half_level = (peak + baseline) / 2.0
    after = series[series.index > peak_date]
    hl_days = None
    hl_date = None
    for i, (dt, v) in enumerate(after.items(), start=1):
        if v < half_level:
            hl_days = i
            hl_date = dt
            break
    # sustained crossing: first close < half_level with no later close >= half_level
    # (evaluated over all available data after the peak)
    sus_days = None
    sus_date = None
    vals = after.values
    dts = after.index
    for i in range(len(vals)):
        if vals[i] < half_level and (vals[i:] < half_level).all():
            sus_days = i + 1
            sus_date = dts[i]
            break
    # return to baseline: first close <= baseline after peak
    base_days = None
    base_date = None
    for i, (dt, v) in enumerate(after.items(), start=1):
        if v <= baseline:
            base_days = i
            base_date = dt
            break
    return {
        "event_start": str(pd.Timestamp(event_start).date()),
        "window": [str(pd.Timestamp(window_start).date()), str(pd.Timestamp(window_end).date())],
        "baseline_median_20d_pre_event": round(baseline, 2),
        "peak_close": round(peak, 2),
        "peak_date": str(peak_date.date()),
        "half_level": round(half_level, 2),
        "half_life_trading_days": hl_days,
        "half_life_hit_date": str(hl_date.date()) if hl_date is not None else None,
        "completed": hl_days is not None,
        "sustained_half_life_trading_days": sus_days,
        "sustained_half_life_date": str(pd.Timestamp(sus_date).date()) if sus_date is not None else None,
        "return_to_baseline_trading_days": base_days,
        "return_to_baseline_date": str(base_date.date()) if base_date is not None else None,
        "days_elapsed_since_peak": int((series.index > peak_date).sum()),
    }


last_vix_date = vix.index[-1]
last_ovx_date = ovx.index[-1]
last_wti_date = wti.index[-1]

ev1 = half_life(vix, "2025-04-02", "2025-04-01", "2025-07-31")
ev1["label"] = "2025-04 關稅戰"

ev2 = half_life(vix, "2026-06-05", "2026-06-01", "2026-07-10")
ev2["label"] = "2026-06 中東衝突"

ev3 = half_life(vix, "2026-07-13", "2026-07-13", str(last_vix_date.date()))
ev3["label"] = "2026-07 油市衝擊"

# Supplementary: the real vol spike this week is in OVX, not VIX
ovx_ev = half_life(ovx, "2026-07-13", "2026-07-13", str(last_ovx_date.date()))
ovx_ev["label"] = "2026-07 油市衝擊（OVX，補充）"

evidence = {
    "generated_at_taipei": "2026-07-16 (data as of latest available close)",
    "data_source": "Yahoo Finance via yfinance, auto_adjust=True, daily close",
    "tickers": {"vix": "^VIX", "ovx": "^OVX", "wti": "CL=F"},
    "sample": {
        "vix": {"start": str(vix.index[0].date()), "end": str(last_vix_date.date()), "n": int(len(vix))},
        "ovx": {"start": str(ovx.index[0].date()), "end": str(last_ovx_date.date()), "n": int(len(ovx))},
        "wti": {"start": str(wti.index[0].date()), "end": str(last_wti_date.date()), "n": int(len(wti))},
    },
    "latest": {
        "vix_close": round(float(vix.iloc[-1]), 2), "vix_date": str(last_vix_date.date()),
        "ovx_close": round(float(ovx.iloc[-1]), 2), "ovx_date": str(last_ovx_date.date()),
        "wti_close": round(float(wti.iloc[-1]), 2), "wti_date": str(last_wti_date.date()),
        "vix_recent_high_close": round(float(vix["2026-07-01":].max()), 2),
        "vix_recent_high_date": str(vix["2026-07-01":].idxmax().date()),
        "ovx_recent_high_close": round(float(ovx["2026-07-01":].max()), 2),
        "ovx_recent_high_date": str(ovx["2026-07-01":].idxmax().date()),
    },
    "half_life_definition": (
        "baseline = 事件起始日前 20 個交易日收盤中位數; peak = 事件窗口內最高收盤; "
        "half_level = (peak+baseline)/2; half_life = 峰值日之後首次收盤 < half_level 所需交易日數。"
        "補充指標: sustained_half_life = 首次收破 half_level 且此後不再收回其上; "
        "return_to_baseline = 峰值後首次收盤 <= baseline 所需交易日數"
    ),
    "events": [ev1, ev2, ev3],
    "supplementary_ovx_event": ovx_ev,
    "caveats": [],
}

# --- honesty caveats, driven by data ---
cavs = evidence["caveats"]
if ev1["half_life_trading_days"] != ev1["sustained_half_life_trading_days"]:
    cavs.append(
        f"2025-04 關稅戰：依定義的首次跌破 half_level 只花 {ev1['half_life_trading_days']} 天"
        f"（4/9 暫停關稅 90 天消息使 VIX 單日崩落），但 4/10、4/11 又收回 half_level 之上，"
        f"持續性跌破（sustained）為 {ev1['sustained_half_life_trading_days']} 天，"
        f"回到基線更需 {ev1['return_to_baseline_trading_days']} 個交易日。首次跌破指標對單日政策反轉敏感。"
    )
cavs.append("VIX/OVX 最新收盤為 2026-07-15（美股 7/16 尚未收盤）；WTI (CL=F) 最新值為 2026-07-16 盤中/最近成交價。")
cavs.append(
    f"任務假設 2026-07-15 有 VIX 峰值，但實際資料顯示 VIX 近期高點在 {evidence['latest']['vix_recent_high_date']}"
    f"（收 {evidence['latest']['vix_recent_high_close']}），且 7/15 收 {evidence['latest']['vix_close']} 已低於事件前基線水準；"
    "本次事件的波動率衝擊主要體現在 OVX（原油波動率），非 VIX。"
)
if ev3["completed"]:
    peak_over_base = ev3["peak_close"] / ev3["baseline_median_20d_pre_event"] - 1
    cavs.append(
        f"2026-07 事件的 VIX 峰值僅高於基線 {peak_over_base*100:.1f}%，spike 幅度極小，"
        f"半衰期 {ev3['half_life_trading_days']} 天在統計上意義有限（雜訊等級），解讀需保守。"
    )
if not ovx_ev["completed"]:
    cavs.append(
        f"OVX 半衰期尚未完成：峰值 {ovx_ev['peak_close']}（{ovx_ev['peak_date']}），"
        f"half_level={ovx_ev['half_level']}，截至 {evidence['latest']['ovx_date']} 收 {evidence['latest']['ovx_close']} 仍在其上；"
        f"進行中，目前已 {ovx_ev['days_elapsed_since_peak']} 個交易日。"
    )
if not ev2["completed"]:
    cavs.append("2026-06 中東衝突事件 VIX 半衰期未在窗口內完成。")
peak2_over_base = ev2["peak_close"] / ev2["baseline_median_20d_pre_event"] - 1
if peak2_over_base < 0.5:
    cavs.append(
        f"2026-06 中東衝突的 VIX 峰值 {ev2['peak_close']}（{ev2['peak_date']}）僅高於基線 "
        f"{peak2_over_base*100:.1f}%，屬中等偏小的 spike（對比 2025-04 關稅戰峰值高於基線 "
        f"{(ev1['peak_close']/ev1['baseline_median_20d_pre_event']-1)*100:.0f}%）。"
    )

with open(f"{OUT}/evidence.json", "w") as f:
    json.dump(evidence, f, ensure_ascii=False, indent=2)

print(json.dumps(evidence, ensure_ascii=False, indent=2))
