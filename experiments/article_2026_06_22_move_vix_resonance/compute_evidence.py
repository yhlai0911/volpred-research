"""
MOVE vs VIX Cross-Asset Vol Resonance Evidence Package
Article: 2026-06-22
Context: Fed hawkish turn + inflation re-acceleration (CPI ~3.0%)
"""

import yfinance as yf
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import json
import os

SEED = 42
np.random.seed(SEED)

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

# ─── 1. Download data ────────────────────────────────────────────────────────
print("Downloading MOVE and VIX...")
move_raw = yf.download("^MOVE", start="2020-01-01", end="2026-06-22", auto_adjust=True, progress=False)
vix_raw  = yf.download("^VIX",  start="2020-01-01", end="2026-06-22", auto_adjust=True, progress=False)

move = move_raw["Close"].squeeze().dropna()
vix  = vix_raw["Close"].squeeze().dropna()

df = pd.concat([move, vix], axis=1, keys=["MOVE", "VIX"]).dropna()
print(f"Data range: {df.index[0].date()} to {df.index[-1].date()}, N={len(df)}")

# ─── 2. Log-changes ──────────────────────────────────────────────────────────
df["MOVE_chg"] = np.log(df["MOVE"] / df["MOVE"].shift(1))
df["VIX_chg"]  = np.log(df["VIX"]  / df["VIX"].shift(1))
df_chg = df.dropna()

# ─── 3. 60-day rolling correlation ───────────────────────────────────────────
roll_corr = df_chg["MOVE_chg"].rolling(60).corr(df_chg["VIX_chg"])
recent_corr = roll_corr.dropna().iloc[-1]
hist_median = roll_corr.dropna().median()
hist_p75    = roll_corr.dropna().quantile(0.75)
hist_p90    = roll_corr.dropna().quantile(0.90)

print(f"\n60-day Rolling Corr (log-chg):")
print(f"  Most recent: {recent_corr:.3f}")
print(f"  Historical median: {hist_median:.3f}")
print(f"  75th pct: {hist_p75:.3f}")
print(f"  90th pct: {hist_p90:.3f}")

# ─── 4. MOVE/VIX ratio ───────────────────────────────────────────────────────
df["ratio"] = df["MOVE"] / df["VIX"]
recent_ratio = df["ratio"].iloc[-1]
hist_ratio_median = df["ratio"].median()
hist_ratio_p75 = df["ratio"].quantile(0.75)
hist_ratio_p90 = df["ratio"].quantile(0.90)
hist_ratio_p10 = df["ratio"].quantile(0.10)

print(f"\nMOVE/VIX Ratio:")
print(f"  Most recent: {recent_ratio:.2f}")
print(f"  Hist median: {hist_ratio_median:.2f}")
print(f"  P10/P75/P90: {hist_ratio_p10:.2f} / {hist_ratio_p75:.2f} / {hist_ratio_p90:.2f}")

# ─── 5. Co-movement (resonance) indicator ────────────────────────────────────
# Both z-score > 1 on same day = resonance episode
move_z = (df["MOVE"] - df["MOVE"].rolling(252).mean()) / df["MOVE"].rolling(252).std()
vix_z  = (df["VIX"]  - df["VIX"].rolling(252).mean()) / df["VIX"].rolling(252).std()
valid_z = move_z.notna() & vix_z.notna()
resonance = ((move_z > 1.0) & (vix_z > 1.0)).where(valid_z).dropna().astype(bool)
resonance_rate_total = resonance.mean()

# Last 90 days
last_90 = resonance.iloc[-90:]
resonance_rate_recent = last_90.mean()
resonance_episodes_recent = last_90.sum()

print(f"\nCo-resonance (both z>1):")
print(f"  Full sample rate: {resonance_rate_total:.3f}")
print(f"  Last 90 days rate: {resonance_rate_recent:.3f}")
print(f"  Last 90 days episodes: {int(resonance_episodes_recent)}")

# ─── 6. Recent vs historical comparison (last 1-month vs 5-year baseline) ────
# "Last 1 month" ~ last 21 trading days
last_21_corr = roll_corr.dropna().iloc[-21:].mean()
five_year_median_corr = roll_corr.dropna().median()
five_year_p90_corr = roll_corr.dropna().quantile(0.90)

print(f"\nRecent vs Hist Corr:")
print(f"  Last 21-day avg corr: {last_21_corr:.3f}")
print(f"  5-yr median corr: {five_year_median_corr:.3f}")
print(f"  5-yr 90th pct corr: {five_year_p90_corr:.3f}")

# Current levels
move_latest = df["MOVE"].iloc[-1]
vix_latest  = df["VIX"].iloc[-1]
print(f"\nCurrent levels: MOVE={move_latest:.1f}, VIX={vix_latest:.1f}")

# ─── 7. Summary table (period stats) ─────────────────────────────────────────
def period_stats(df_sub, label):
    c = df_sub["MOVE_chg"].corr(df_sub["VIX_chg"])
    r = (df_sub["MOVE"] / df_sub["VIX"]).mean()
    valid_idx = df_sub.index[valid_z.reindex(df_sub.index).fillna(False)]
    if len(valid_idx) == 0:
        res_r = np.nan
        res_n = 0
    else:
        res_series = ((move_z.loc[valid_idx] > 1) & (vix_z.loc[valid_idx] > 1))
        res_r = res_series.mean()
        res_n = int(res_series.count())
    return {"period": label, "avg_corr": round(c, 3), "avg_MOVE_VIX_ratio": round(r, 2),
            "resonance_rate": None if pd.isna(res_r) else round(float(res_r), 3),
            "resonance_valid_n": res_n}

stats_2020 = period_stats(df_chg.loc["2020":"2020"], "2020 (COVID)")
stats_2022 = period_stats(df_chg.loc["2022":"2022"], "2022 (rate hike cycle)")
stats_2023 = period_stats(df_chg.loc["2023":"2023"], "2023 (plateau)")
stats_2024 = period_stats(df_chg.loc["2024":"2024"], "2024")
stats_2025 = period_stats(df_chg.loc["2025":"2025"], "2025")

last_90_slice = df_chg.iloc[-90:]
stats_recent = period_stats(last_90_slice, "2026 recent 90d")

summary_table = [stats_2020, stats_2022, stats_2023, stats_2024, stats_2025, stats_recent]
for row in summary_table:
    print(row)

# ─── 8. Figure 1: 60-day rolling correlation ─────────────────────────────────
fig, ax = plt.subplots(figsize=(11, 4))
roll_corr_plot = roll_corr.dropna()
ax.plot(roll_corr_plot.index, roll_corr_plot.values, color='#1a5276', lw=1.5, label='60日滾動相關係數')
ax.axhline(hist_median, color='gray', ls='--', lw=1, label=f'歷史中位數 {hist_median:.2f}')
ax.axhline(hist_p90, color='#e74c3c', ls=':', lw=1.2, label=f'歷史 90th pct {hist_p90:.2f}')
ax.fill_between(roll_corr_plot.index, hist_p75, roll_corr_plot.values,
                where=roll_corr_plot.values > hist_p75,
                alpha=0.18, color='#e74c3c', label=f'>75th pct 區間')
ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
ax.xaxis.set_major_locator(mdates.MonthLocator(interval=6))
plt.xticks(rotation=30, ha='right', fontsize=8)
ax.set_ylabel("Pearson correlation", fontsize=9)
ax.set_title("MOVE × VIX 日對數漲跌 — 60日滾動相關係數（2020-2026）", fontsize=10)
ax.legend(fontsize=8, loc='upper left')
ax.set_ylim(-0.1, 1.0)
ax.grid(alpha=0.3)
plt.tight_layout()
fig.savefig(os.path.join(OUT_DIR, "fig_rolling_corr.png"), dpi=150)
plt.close()
print("Saved fig_rolling_corr.png")

# ─── 9. Figure 2: MOVE/VIX ratio + regime ───────────────────────────────────
fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)

# Panel A: raw levels normalized to 100 at 2020-01-02
base_date = df.index[0]
move_norm = df["MOVE"] / df["MOVE"].iloc[0] * 100
vix_norm  = df["VIX"]  / df["VIX"].iloc[0] * 100
axes[0].plot(df.index, move_norm, color='#1a5276', lw=1.3, label='MOVE（標準化）')
axes[0].plot(df.index, vix_norm,  color='#e74c3c', lw=1.3, label='VIX（標準化）')
axes[0].set_ylabel("相對指數（2020=100）", fontsize=9)
axes[0].set_title("MOVE & VIX 水準走勢（2020-2026）", fontsize=10)
axes[0].legend(fontsize=8)
axes[0].grid(alpha=0.3)

# Panel B: MOVE/VIX ratio
ratio_series = df["ratio"]
axes[1].plot(ratio_series.index, ratio_series.values, color='#6c3483', lw=1.3, label='MOVE/VIX 比值')
axes[1].axhline(hist_ratio_median, color='gray', ls='--', lw=1, label=f'歷史中位數 {hist_ratio_median:.1f}')
axes[1].axhline(hist_ratio_p90, color='#e74c3c', ls=':', lw=1.2, label=f'90th pct {hist_ratio_p90:.1f}')
axes[1].axhline(hist_ratio_p10, color='#2980b9', ls=':', lw=1.2, label=f'10th pct {hist_ratio_p10:.1f}')
axes[1].fill_between(ratio_series.index, hist_ratio_p90, ratio_series.values,
                      where=ratio_series.values > hist_ratio_p90,
                      alpha=0.2, color='#e74c3c', label=f'>90th pct')
axes[1].xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
axes[1].xaxis.set_major_locator(mdates.MonthLocator(interval=6))
plt.xticks(rotation=30, ha='right', fontsize=8)
axes[1].set_ylabel("MOVE / VIX", fontsize=9)
axes[1].set_title("MOVE/VIX 比值（美債波動率 vs 美股波動率 regime indicator）", fontsize=10)
axes[1].legend(fontsize=8, loc='upper right')
axes[1].grid(alpha=0.3)
plt.tight_layout()
fig.savefig(os.path.join(OUT_DIR, "fig_regime.png"), dpi=150)
plt.close()
print("Saved fig_regime.png")

# ─── 10. Save results.json ───────────────────────────────────────────────────
results = {
    "meta": {
        "data_source": "Yahoo Finance (^MOVE, ^VIX)",
        "date_range": f"{df.index[0].date()} to {df.index[-1].date()}",
        "N_obs": len(df),
        "seed": SEED
    },
    "rolling_corr_60d": {
        "most_recent": round(float(recent_corr), 4),
        "hist_median": round(float(hist_median), 4),
        "hist_p75": round(float(hist_p75), 4),
        "hist_p90": round(float(hist_p90), 4),
        "last_21d_avg": round(float(last_21_corr), 4),
        "percentile_of_recent": round(float((roll_corr.dropna() <= recent_corr).mean() * 100), 1),
        "percentile_label": "2020-2026 retrospective percentile"
    },
    "move_vix_ratio": {
        "most_recent": round(float(recent_ratio), 2),
        "hist_median": round(float(hist_ratio_median), 2),
        "hist_p10": round(float(hist_ratio_p10), 2),
        "hist_p75": round(float(hist_ratio_p75), 2),
        "hist_p90": round(float(hist_ratio_p90), 2),
        "percentile_of_recent": round(float((df["ratio"] <= recent_ratio).mean() * 100), 1),
        "percentile_label": "2020-2026 retrospective percentile"
    },
    "resonance_both_z_gt1": {
        "full_sample_rate": round(float(resonance_rate_total), 4),
        "last_90d_rate": round(float(resonance_rate_recent), 4),
        "last_90d_episodes": int(resonance_episodes_recent),
        "valid_z_obs": int(resonance.count()),
        "invalid_z_obs_dropped": int((~valid_z).sum()),
        "definition": "Both MOVE and VIX are above their valid 252-trading-day rolling z-score +1 threshold; invalid rolling windows are excluded before comparison."
    },
    "current_levels": {
        "MOVE": round(float(move_latest), 1),
        "VIX": round(float(vix_latest), 1)
    },
    "period_summary_table": summary_table
}

with open(os.path.join(OUT_DIR, "results.json"), "w") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
print("\nSaved results.json")
print("\n=== KEY NUMBERS ===")
print(json.dumps(results, indent=2, ensure_ascii=False))
