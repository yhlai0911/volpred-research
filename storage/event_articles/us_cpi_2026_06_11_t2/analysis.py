"""
US CPI T-2 Preview: recent CPI reaction trend + VIX/VIX9D positioning
ERRATA RERUN 2026-07-17 — evidence pack behind mile_0fa9c7f5.

This reruns the original evidence pack; it is not a new study. What changed is
that the CPI release dates now come from the official FRED/ALFRED calendar
instead of a "CPI comes out around the 13th" proxy — plus the two method deltas
listed below, disclosed rather than waved off as "nothing else changed". Against
the official calendar, 7 of the original 13 hard-coded dates were wrong, and one
(2025-11-13) was a release that never happened: no CPI was published in November
2025 at all, because the October-2025 reference month — the one that November slot
would have carried — was cancelled during the shutdown (CPIAUCSL has no
observation for 2025-10-01). So the proxy scored non-event days as event days and
dumped real event days into the baseline, silently.

Sample falls from 13 to 12: the fabricated November release is gone. The
"earlier 9" comparison group is therefore now 8 releases.

Method deltas (disclosed rather than claimed absent — "we changed nothing else" is
exactly the kind of unchecked claim this errata exists to correct):
  1. Event-session alignment changed from the original's bidirectional +/-5-day
     nearest-match to forward-only, bounded (MAX_SNAP_DAYS), fail-closed. A
     behavioural change, not merely a guard: the old rule could map a release
     BACKWARD onto an earlier session. Inert here — all 12 official releases are
     trading days, so every mapping is an identity — but a method change, listed
     as one.
  2. Non-session rows are dropped against the XNYS calendar. yfinance returns a
     ^VIX quote for Memorial Day 2026-05-25, when the exchange was closed. Verified
     to change zero reported numbers here — ^VIX9D lacks that row, so the ratio
     series already excluded it via the index intersection, and all 12 events sit
     before it — but row-offset arithmetic assumes the index is the session list.
Both deltas are behavioural and both are verified inert on this data (primary
numbers are byte-identical with and without the session filter). The estimators,
tests, and data window are otherwise the original's.

Known inference limits, stated rather than papered over:
  - Reported std uses ddof=0 (descriptive, as in the original); the F-test uses
    ddof=1. The displayed sigmas therefore do not algebraically reconcile to F.
  - The F-test assumes normality. Four recent observations cannot support that
    assumption, and the classical F-test is notoriously sensitive to departures
    from it. p=0.0067 is therefore SUGGESTIVE OF, not evidence for, variance
    compression. Any reader-facing claim must carry that hedge — the point of
    this errata is not to trade one overclaim for another.

The article also previewed the wrong event: it was written as a T-2 preview of a
2026-06-11 release, but the official June-2026 release date was 2026-06-10. The
piece published 2026-06-09 was a T-1 preview, not T-2.

Date convention (stated explicitly — see README):
  - Event date t = official BLS news-release date (08:30 ET).
  - Reaction = t-1 close → t close. The 08:30 release precedes the 09:30 open, so
    measuring the same session is not lookahead.
  - Event-window offsets (T-5 … T-1) are TRADING days, not calendar days.
  - The pre-event run-up profile is measured RELATIVE TO the CPI-day VIX, which
    is not known in advance. It is descriptive only and is not a tradeable
    signal; do not read it as a forecast.
  - "T-2" in the article slot name is a calendar-day offset from the previewed
    release. Unrelated to the trading-day offsets above.

The data window is deliberately left at the original run's (2025-05-01 →
2026-06-09) so this rerun isolates the date fix rather than confounding it with
fresher data.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from plot_style import apply_cjk_style  # noqa: E402

apply_cjk_style()
import matplotlib.pyplot as plt
import yfinance as yf
import exchange_calendars as xcals
from scipy import stats
import warnings
warnings.filterwarnings('ignore')

from volpred.data.event_dates import cpi_release_dates  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent

# ─── 1. Data Download ────────────────────────────────────────────────────────

print("Downloading VIX, VIX9D, SPY data...")
start = "2025-05-01"
end = "2026-06-09"  # exclusive upper bound; last closed day = 2026-06-08


def load_sessions(symbol, start, end):
    """Download `symbol` and assert the result IS the XNYS session list for [start, end).

    Every offset here is row arithmetic, which silently assumes the index IS the
    trading calendar. The two ways that breaks are not symmetric:

      - An EXTRA non-session row is an upstream quirk — yfinance quotes ^VIX for
        2026-05-25, Memorial Day, when NYSE and CBOE were shut. Dropped, loudly.
      - A MISSING session, a duplicate, or an out-of-order index silently corrupts
        every offset: "5 rows later" stops meaning "5 sessions later". That raises.

    Expected sessions come from the REQUESTED window, not the data's own first/last
    row — otherwise a missing leading or trailing session defines itself away.
    """
    s = yf.download(symbol, start=start, end=end, auto_adjust=True, progress=False)['Close'].squeeze()
    expected = xcals.get_calendar("XNYS").sessions_in_range(
        pd.Timestamp(start), pd.Timestamp(end) - pd.Timedelta(days=1)  # yfinance end is exclusive
    )
    expected = pd.DatetimeIndex([d.tz_localize(None) if d.tz else d for d in expected])
    idx = pd.DatetimeIndex(s.index)

    dupes = idx[idx.duplicated()]
    if len(dupes):
        raise RuntimeError(f"{symbol}: duplicated rows {[str(d.date()) for d in dupes]}")

    junk = idx.difference(expected)
    if len(junk):
        print(f"  WARNING: {symbol} carried {len(junk)} non-session row(s), dropped: "
              f"{[str(d.date()) for d in junk]}")
        s = s[~idx.isin(junk)]

    got = pd.DatetimeIndex(s.index)
    missing = expected.difference(got)
    if len(missing):
        raise RuntimeError(
            f"{symbol}: {len(missing)} XNYS session(s) absent from the quote series "
            f"({[str(d.date()) for d in missing[:5]]}). Every offset here is row arithmetic; "
            f"it would walk straight past the hole. Refusing to run."
        )
    # Set equality is not enough: a permuted-but-complete index passes the missing,
    # extra and duplicate checks while corrupting every offset. Require order too.
    if not got.equals(expected):
        raise RuntimeError(f"{symbol}: index is not the XNYS session list in order")
    return s


vix_close = load_sessions("^VIX", start, end)
vix9d_close = load_sessions("^VIX9D", start, end)
spy_close = load_sessions("SPY", start, end)

print(f"VIX: {len(vix_close)} trading days, {vix_close.index[0].date()} to {vix_close.index[-1].date()}")
print(f"VIX9D: {len(vix9d_close)} trading days")
print(f"SPY: {len(spy_close)} trading days")

# ─── 2. CPI Release Dates — official calendar, not a guess ──────────────────

cpi_dates = cpi_release_dates(start, end)
cpi_dates = cpi_dates[(cpi_dates >= vix_close.index[0]) & (cpi_dates <= vix_close.index[-1])]

print(f"\nOfficial CPI release dates in sample: {len(cpi_dates)}")
for d in cpi_dates:
    print(f"  {d.date()}: {'trading day' if d in vix_close.index else 'NOT a trading day'}")

# Recent-4 subset (the T-2 angle)
recent4 = cpi_dates[-4:]

# ─── 3. Map each release to its reaction session ───────────────────────────

MAX_SNAP_DAYS = 4  # a holiday weekend is the only legitimate gap

date_mapping = []


def to_trading_day(release_date, index, record=True):
    """The session that absorbs the release.

    BLS publishes at 08:30 ET on business days, so this is normally an identity
    mapping. A release on a market holiday would push the reaction to the next
    session — legitimate, but bounded: only the next session within
    MAX_SNAP_DAYS counts. Anything further means the quote series has a hole, and
    mapping across a hole would silently relabel an unrelated day as the CPI
    reaction. We raise instead.

    The original searched +/-5 days in BOTH directions and took the first hit,
    which is how a wrong date still produced a plausible number.
    """
    if release_date in index:
        if record:
            date_mapping.append({"release": str(release_date.date()), "session": str(release_date.date()), "snapped": False})
        return release_date
    later = index[index > release_date]
    if len(later) == 0 or (later[0] - release_date).days > MAX_SNAP_DAYS:
        raise RuntimeError(
            f"release {release_date.date()} has no trading session within "
            f"{MAX_SNAP_DAYS} days; refusing to guess which day absorbed it"
        )
    nxt = later[0]
    print(f"  WARNING: release {release_date.date()} is not a trading day; reaction mapped to {nxt.date()}")
    if record:
        date_mapping.append({"release": str(release_date.date()), "session": str(nxt.date()), "snapped": True})
    return nxt

cpi_trading_days = [to_trading_day(d, vix_close.index) for d in cpi_dates]
recent4_td = [to_trading_day(d, vix_close.index, record=False) for d in recent4]

n_snapped = sum(1 for m in date_mapping if m["snapped"])
print(f"\nFull baseline N={len(cpi_trading_days)} ({n_snapped} snapped); recent-4 N={len(recent4_td)}")

# ─── 4. CPI Day VIX % Change ────────────────────────────────────────────────

def vix_pct(td):
    pos = vix_close.index.get_loc(td)
    if pos == 0:
        return None
    prev = vix_close.iloc[pos - 1]
    curr = vix_close.iloc[pos]
    return float((curr - prev) / prev * 100), float(prev), float(curr)

vix_changes_all = []
for td in cpi_trading_days:
    r = vix_pct(td)
    if r is not None:
        pct, prev, curr = r
        vix_changes_all.append({'date': td, 'pct': pct, 'prev': prev, 'curr': curr})

vix_changes_arr_all = np.array([x['pct'] for x in vix_changes_all])

# Recent 4 subset
vix_changes_recent4 = [x for x in vix_changes_all if x['date'] in recent4_td]
recent4_arr = np.array([x['pct'] for x in vix_changes_recent4])

# Earlier subset (was 9 releases under the proxy dates; 8 under the official ones)
earlier = [x for x in vix_changes_all if x['date'] not in recent4_td]
earlier_arr = np.array([x['pct'] for x in earlier])
n_earlier = len(earlier_arr)

print("\n=== Recent 4 CPI Day VIX % Change (T-2 focus) ===")
for x in vix_changes_recent4:
    print(f"  {x['date'].date()}  VIX {x['prev']:.2f} -> {x['curr']:.2f}  ({x['pct']:+.2f}%)")
print(f"Recent-4 mean:      {recent4_arr.mean():+.2f}%")
print(f"Recent-4 std:       {recent4_arr.std():.2f}%")
print(f"Earlier-{n_earlier} mean:     {earlier_arr.mean():+.2f}%")
print(f"Earlier-{n_earlier} std:      {earlier_arr.std():.2f}%")
print(f"Full-{len(vix_changes_arr_all)} std:        {vix_changes_arr_all.std():.2f}%")

# Variance compression F-test (one-sided: earlier > recent)
F_stat = earlier_arr.var(ddof=1) / recent4_arr.var(ddof=1)
df1 = len(earlier_arr) - 1
df2 = len(recent4_arr) - 1
F_pval = 1 - stats.f.cdf(F_stat, df1, df2)
print(f"F-test (var_earlier{n_earlier} / var_recent4): F={F_stat:.3f}, df=({df1},{df2}), one-sided p={F_pval:.4f}")

# ─── 5. Current VIX / VIX9D term structure (latest 10 trading days) ─────────

common_idx = vix_close.index.intersection(vix9d_close.index)
vix_a = vix_close.loc[common_idx]
vix9d_a = vix9d_close.loc[common_idx]
ratio = vix9d_a / vix_a  # >1 => short-dated higher (front-end stressed)

latest10_idx = common_idx[-10:]
latest5_idx = common_idx[-5:]

print("\n=== Latest 10 trading days VIX & VIX9D ===")
for d in latest10_idx:
    print(f"  {d.date()}  VIX={vix_a.loc[d]:.2f}  VIX9D={vix9d_a.loc[d]:.2f}  ratio={ratio.loc[d]:.3f}")

latest5_ratio = ratio.loc[latest5_idx].mean()
latest10_ratio = ratio.loc[latest10_idx].mean()

# Baseline ratio (non-CPI days, full sample)
non_cpi_mask = ~ratio.index.isin(cpi_trading_days)
baseline_ratio = ratio.loc[non_cpi_mask]

print(f"\nLatest-5 mean VIX9D/VIX:  {latest5_ratio:.4f}")
print(f"Latest-10 mean VIX9D/VIX: {latest10_ratio:.4f}")
print(f"Baseline (non-CPI all) mean: {baseline_ratio.mean():.4f}, std={baseline_ratio.std():.4f}")
print(f"Latest-5 z-score vs baseline: {(latest5_ratio - baseline_ratio.mean()) / baseline_ratio.std():.2f}")

# ─── 6. Pre-CPI VIX run-up profile (T-5 to T-1, trading days) ──────────────
# Descriptive only: measured against the CPI-day VIX, which is unknown ex ante.

print("\n=== Pre-CPI VIX run-up (T-5 to T-1, mean % vs CPI day) ===")
preevent_changes = {-5: [], -4: [], -3: [], -2: [], -1: []}
for td in cpi_trading_days:
    pos = vix_close.index.get_loc(td)
    base = vix_close.iloc[pos]
    for offset in range(-5, 0):
        ip = pos + offset
        if ip >= 0:
            preevent_changes[offset].append(float((vix_close.iloc[ip] - base) / base * 100))

for offset in sorted(preevent_changes.keys()):
    arr = np.array(preevent_changes[offset])
    print(f"  T{offset:+d}: mean diff vs CPI-day VIX = {arr.mean():+.2f}%, n={len(arr)}")

# ─── 7. Build T-2 specific summary table (recent 4) ────────────────────────

table_rows = []
for x in vix_changes_recent4:
    td = x['date']
    ratio_val = float(ratio.loc[td]) if td in ratio.index else None
    pos = vix_close.index.get_loc(td)
    if pos + 5 < len(vix_close):
        post5 = (vix_close.iloc[pos + 5] - vix_close.iloc[pos]) / vix_close.iloc[pos] * 100
    else:
        post5 = None
    table_rows.append({
        'CPI 發布日': td.strftime('%Y-%m-%d'),
        'VIX（T-1）': round(x['prev'], 2),
        'VIX（當日）': round(x['curr'], 2),
        'VIX 當日漲跌': f"{x['pct']:+.1f}%",
        'VIX9D/VIX 比值': f"{ratio_val:.3f}" if ratio_val else 'N/A',
        'VIX T+5 變化': f"{post5:+.1f}%" if post5 is not None else 'N/A',
    })

df_table = pd.DataFrame(table_rows)
print("\nT-2 Summary Table (recent 4 CPI):")
print(df_table.to_string(index=False))

# Current state (for article context, not historical)
current_vix = float(vix_close.iloc[-1])
current_vix9d = float(vix9d_close.iloc[-1])
current_ratio = current_vix9d / current_vix
current_date = vix_close.index[-1].strftime('%Y-%m-%d')
print(f"\nCurrent state ({current_date}):  VIX={current_vix:.2f}  VIX9D={current_vix9d:.2f}  ratio={current_ratio:.3f}")

# ─── 8. Figure 1: Recent 4 vs earlier releases, dispersion ─────────────────
# Filename keeps the legacy "earlier9" token so the published article's image URL
# does not 404 mid-errata; the group is 8 releases now and the chart says so.

span_lo = pd.Timestamp(earlier[0]['date']).strftime('%Y-%m')
span_hi_earlier = pd.Timestamp(earlier[-1]['date']).strftime('%Y-%m')
span_lo_recent = pd.Timestamp(vix_changes_recent4[0]['date']).strftime('%Y-%m')
span_hi = pd.Timestamp(vix_changes_recent4[-1]['date']).strftime('%Y-%m')

fig1, ax = plt.subplots(figsize=(9, 5))

x_recent = np.arange(len(recent4_arr)) + len(earlier_arr) + 1
x_earlier = np.arange(len(earlier_arr))

ax.scatter(x_earlier, earlier_arr,
           color='#90a4ae', alpha=0.85, s=80, edgecolor='white',
           label=f'前 {n_earlier} 次（{span_lo} ~ {span_hi_earlier}），σ={earlier_arr.std():.2f}%')
ax.scatter(x_recent, recent4_arr,
           color='#d32f2f', alpha=0.9, s=110, edgecolor='white',
           label=f'近 4 次（{span_lo_recent} ~ {span_hi}），σ={recent4_arr.std():.2f}%')

ax.axhline(0, color='black', linewidth=0.8, linestyle='--', alpha=0.5)

e_mean = earlier_arr.mean()
e_std = earlier_arr.std()
ax.axhspan(e_mean - e_std, e_mean + e_std, alpha=0.06, color='#90a4ae')

r_mean = recent4_arr.mean()
r_std = recent4_arr.std()
ax.axhspan(r_mean - r_std, r_mean + r_std, alpha=0.06, color='#d32f2f')

recent_labels = [x['date'].strftime('%Y-%m-%d') for x in vix_changes_recent4]
for xi, yi, lbl in zip(x_recent, recent4_arr, recent_labels):
    ax.annotate(f"{lbl}\n{yi:+.1f}%", (xi, yi),
                textcoords="offset points", xytext=(0, 12),
                ha='center', fontsize=8.5, color='#b71c1c')

all_labels = [x['date'].strftime('%y-%m-%d') for x in earlier] + [''] + [x['date'].strftime('%y-%m-%d') for x in vix_changes_recent4]
all_x = list(x_earlier) + [len(earlier_arr)] + list(x_recent)
ax.set_xticks(all_x)
ax.set_xticklabels(all_labels, rotation=45, ha='right', fontsize=8)

ax.set_xlabel('CPI 官方發布日', fontsize=11)
ax.set_ylabel('VIX 當日漲跌幅（%）', fontsize=11)
ax.set_title(f'US CPI 反應的離散度：近 4 次 vs 前 {n_earlier} 次\n（{span_lo} ~ {span_hi}，官方發布日，當日 VIX 收盤 vs T-1）',
             fontsize=12.5, fontweight='bold')
ax.legend(fontsize=9, loc='upper left')
ax.yaxis.grid(True, alpha=0.3)
ax.set_axisbelow(True)

fig1.text(0.99, 0.01, '資料來源：yfinance / CBOE ^VIX；發布日取自 FRED/ALFRED 官方發布日曆',
          ha='right', va='bottom', fontsize=7, color='grey')
plt.tight_layout()
fig1.savefig(OUT_DIR / 'fig1_recent4_vs_earlier9.png', dpi=150, bbox_inches='tight')
plt.close()
print("\nFig 1 saved.")

# ─── 9. Figure 2: Current VIX / VIX9D term structure (last 30 days) ────────

fig2, ax2 = plt.subplots(figsize=(9, 5))
last30 = common_idx[-30:]

ax2.plot(last30, vix_a.loc[last30], 'o-', color='#1565c0', linewidth=1.8, markersize=4, label='VIX')
ax2.plot(last30, vix9d_a.loc[last30], 's--', color='#d32f2f', linewidth=1.6, markersize=4, label='VIX9D')

ax2.axvspan(latest5_idx[0], latest5_idx[-1], alpha=0.12, color='#ffa000', label='近 5 交易日')

ax2.annotate(f"{current_date}\nVIX={current_vix:.2f}\nVIX9D={current_vix9d:.2f}\nratio={current_ratio:.3f}",
             (last30[-1], current_vix),
             textcoords="offset points", xytext=(10, -25),
             fontsize=9, color='#0d47a1',
             bbox=dict(boxstyle="round,pad=0.4", facecolor='#e3f2fd', edgecolor='#1565c0', alpha=0.9))

ax2.set_xlabel('日期', fontsize=11)
ax2.set_ylabel('指數水準', fontsize=11)
ax2.set_title(f'CPI 發布前的 VIX / VIX9D 結構（{last30[0].date()} ~ {last30[-1].date()}）\n比值 <1 表示短端隱含波動低於 30 天，前端定價較鬆',
              fontsize=12.5, fontweight='bold')
ax2.legend(fontsize=9, loc='upper left')
ax2.yaxis.grid(True, alpha=0.3)
ax2.set_axisbelow(True)
plt.xticks(rotation=45, ha='right', fontsize=8)

fig2.text(0.99, 0.01, '資料來源：yfinance / CBOE ^VIX ^VIX9D；VolPred 自製分析',
          ha='right', va='bottom', fontsize=7, color='grey')
plt.tight_layout()
fig2.savefig(OUT_DIR / 'fig2_current_vix_term.png', dpi=150, bbox_inches='tight')
plt.close()
print("Fig 2 saved.")

# ─── 10. Save evidence JSON ─────────────────────────────────────────────────

evidence = {
    "event": "US CPI (T-2 preview article, mile_0fa9c7f5)",
    "article_slot": "T-2",
    "errata_rerun": {
        "date": "2026-07-17",
        "reason": "original run hard-coded CPI release dates from a 13th-of-month proxy; 7 of 13 were wrong and the 2025-11-13 entry was a release that never happened (October-2025 reference month cancelled during the shutdown; CPIAUCSL has no 2025-10-01 observation)",
        "event_date_source": "FRED/ALFRED release calendar (release_id=10) via volpred.data.event_dates.cpi_release_dates",
        "data_window_unchanged": True,
        "method_unchanged": False,
        "method_deltas": [
            "event-session alignment changed from bidirectional +/-5-day nearest-match to forward-only, bounded (MAX_SNAP_DAYS=4), fail-closed; behavioural change, inert on this data (all 12 mappings are identities)",
            "enforces the complete requested XNYS session calendar before any analysis: drops extra non-session rows (yfinance returns a ^VIX quote for Memorial Day 2026-05-25 when the exchange was closed) and RAISES on missing, duplicate, or out-of-order sessions, with expected sessions derived from the requested window rather than the data's own bounds. Verified to change zero reported numbers, since ^VIX9D lacks that row and all 12 events precede it",
        ],
        "inference_limits": [
            "reported std uses ddof=0 (descriptive, as in original); F-test uses ddof=1, so displayed sigmas do not reconcile to F algebraically",
            "F-test assumes normality; n=4 in the recent group cannot support it and the classical F-test is highly sensitive to departures. p=0.0067 is suggestive of variance compression, not evidence for it",
        ],
        "previewed_event_date_was_wrong": {
            "article_assumed": "2026-06-11",
            "official": "2026-06-10",
            "consequence": "the piece published 2026-06-09 was a T-1 preview, not T-2",
        },
    },
    "data_period": f"{start} to {vix_close.index[-1].date()}",
    "latest_closed_trading_day": current_date,
    "official_release_dates": [d.strftime('%Y-%m-%d') for d in cpi_dates],
    "release_to_session_mapping": date_mapping,
    "cpi_dates_full_n": len(cpi_trading_days),
    "cpi_dates_recent4_n": len(recent4_td),
    "date_convention": {
        "event_date": "official BLS news-release date, published 08:30 ET",
        "reaction_window": "t-1 close to t close; release at 08:30 precedes the 09:30 open, so same-day measurement is not lookahead",
        "event_window_offsets": "trading days, not calendar days",
        "pre_event_runup": "descriptive only — measured against the CPI-day VIX, which is unknown ex ante; not a tradeable signal",
        "article_slot_naming": "T-2 is a calendar-day offset from the previewed release; unrelated to the trading-day offsets above",
    },
    "primary_numbers": {
        "recent4_vix_day_pct": {
            "values": [{"date": x['date'].strftime('%Y-%m-%d'), "pct": round(x['pct'], 3),
                        "vix_prev": round(x['prev'], 2), "vix_curr": round(x['curr'], 2)}
                       for x in vix_changes_recent4],
            "mean": round(float(recent4_arr.mean()), 3),
            "std": round(float(recent4_arr.std()), 3),
            "min": round(float(recent4_arr.min()), 3),
            "max": round(float(recent4_arr.max()), 3),
        },
        "earlier_vix_day_pct": {
            "mean": round(float(earlier_arr.mean()), 3),
            "std": round(float(earlier_arr.std()), 3),
            "min": round(float(earlier_arr.min()), 3),
            "max": round(float(earlier_arr.max()), 3),
            "n": n_earlier,
        },
        "variance_compression_ftest": {
            "F_stat": round(float(F_stat), 3),
            "df_earlier": df1,
            "df_recent": df2,
            "one_sided_pval": round(float(F_pval), 4),
            "interpretation": "小 p 值指向「近 4 次方差低於前 8 次」，但 n=4 撐不起 F 檢定的常態假設，且該檢定對偏離常態極敏感 —— 應讀為 suggestive，不可宣稱為顯著證據",
            "normality_assumption_supported": False,
        },
        "current_term_structure": {
            "as_of_date": current_date,
            "vix": round(current_vix, 2),
            "vix9d": round(current_vix9d, 2),
            "ratio_vix9d_vix": round(current_ratio, 4),
            "latest5_ratio_mean": round(float(latest5_ratio), 4),
            "latest10_ratio_mean": round(float(latest10_ratio), 4),
            "baseline_ratio_mean": round(float(baseline_ratio.mean()), 4),
            "baseline_ratio_std": round(float(baseline_ratio.std()), 4),
            "z_score_latest5_vs_baseline": round(float((latest5_ratio - baseline_ratio.mean()) / baseline_ratio.std()), 2),
        },
        "pre_cpi_runup": {
            f"T{offset:+d}": {
                "mean_pct_vs_cpi_day": round(float(np.mean(preevent_changes[offset])), 3),
                "n": len(preevent_changes[offset])
            }
            for offset in sorted(preevent_changes.keys())
        }
    },
    "table_rows_recent4": table_rows,
    "latest_10_days": [
        {"date": d.strftime('%Y-%m-%d'),
         "vix": round(float(vix_a.loc[d]), 2),
         "vix9d": round(float(vix9d_a.loc[d]), 2),
         "ratio": round(float(ratio.loc[d]), 4)}
        for d in latest10_idx
    ]
}

tmp = OUT_DIR / 'evidence.json.tmp'
tmp.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, default=str) + "\n")
json.loads(tmp.read_text())  # fail before replacing the real file, not after
tmp.replace(OUT_DIR / 'evidence.json')

print("\nEvidence saved to evidence.json")
print("\n=== KEY NUMBERS ===")
print(json.dumps({
    "recent4_mean": evidence['primary_numbers']['recent4_vix_day_pct']['mean'],
    "recent4_std": evidence['primary_numbers']['recent4_vix_day_pct']['std'],
    "earlier_mean": evidence['primary_numbers']['earlier_vix_day_pct']['mean'],
    "earlier_std": evidence['primary_numbers']['earlier_vix_day_pct']['std'],
    "earlier_n": evidence['primary_numbers']['earlier_vix_day_pct']['n'],
    "F_p": evidence['primary_numbers']['variance_compression_ftest']['one_sided_pval'],
    "latest5_ratio": evidence['primary_numbers']['current_term_structure']['latest5_ratio_mean'],
    "z_score": evidence['primary_numbers']['current_term_structure']['z_score_latest5_vs_baseline'],
    "current_vix": evidence['primary_numbers']['current_term_structure']['vix'],
    "current_vix9d": evidence['primary_numbers']['current_term_structure']['vix9d'],
}, ensure_ascii=False, indent=2))
