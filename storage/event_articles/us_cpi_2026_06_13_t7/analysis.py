"""
US CPI T-7 Preview: VIX event study analysis — ERRATA RERUN 2026-07-17

This is a rerun of the evidence pack behind mile_ebb5d6f5, not a new study. What
changed is where the event dates come from — plus the deltas listed below, which
are disclosed rather than waved off as "nothing else changed".

The original run hard-coded 13 CPI release dates inferred from a "CPI comes out
around the 13th" calendar proxy. Against the official FRED/ALFRED release
calendar, 7 of those 13 were wrong, and one (2025-11-13) was a release that never
happened: no CPI was published in November 2025 at all, because the October-2025
reference month — the one that November slot would have carried — was cancelled
during the shutdown (CPIAUCSL has no observation for 2025-10-01). The proxy
therefore did both halves of the damage at once: it scored non-event days as
event days, and it dropped real event days into the non-event baseline.

Nothing about that failure was visible in the output. No exception, no NaN, and
the figures rendered fine. That is the whole reason this rerun exists.

Sample size falls from 13 to 12 because the fabricated November release is gone.

Method deltas (this rerun is NOT purely a date swap — disclosing rather than
claiming "method unchanged", which would repeat the sin this errata corrects):
  1. Event-session alignment changed from the original's bidirectional +/-5-day
     nearest-match to forward-only, bounded (MAX_SNAP_DAYS), fail-closed. This is
     a behavioural change, not just a guard: the old rule could map a release
     BACKWARD onto an earlier session. It happens to be inert here — all 12
     official releases are trading days, so every mapping is an identity — but it
     is a method change and is listed as one.
  2. Added a one-sample t-test of the CPI-day mean against zero. It adds a
     statistic; it changes none of the pre-existing ones.
  3. Fixed a latent off-by-one in the ratio event window: the original bounded
     the offset against len(ratio.index) (267) while indexing vix_close.index
     (268). Benign on this data, wrong in general.
  4. Added a null-imposed stationary block bootstrap for the CPI-vs-baseline ratio
     comparison (see below). The original IID p-value is retained alongside it for
     comparability; the bootstrap is what any significance claim should rest on.
  5. Non-session rows are dropped against the XNYS calendar. yfinance returns a
     ^VIX quote for Memorial Day 2026-05-25, when the exchange was closed. Verified
     to change zero reported numbers here — ^VIX9D lacks that row, so the ratio
     series already excluded it via the index intersection, and all 12 events sit
     before it — but row-offset arithmetic assumes the index is the session list,
     and leaving a phantom session in it is a landmine for any future rerun.
Everything else — data window, estimators, tests — is untouched, so the
before/after diff is attributable to the dates.

Known inference limits, stated rather than papered over:
  - Reported std uses ddof=0 (descriptive, as in the original). No F-test is run
    in this script (that is the T-2 pack); the sigmas here are purely descriptive.
  - The CPI-vs-baseline ratio comparison's ttest_ind assumes equal-variance IID
    draws, but the baseline is an autocorrelated daily series, which understates
    the standard error. Disclosure alone is not enough when a conclusion rests on
    it, so a null-imposed stationary block bootstrap (Politis & Romano 1994) is
    computed and is the number any "(not) significant" statement should cite. It
    resamples the full ratio series and reapplies the same fixed CPI mask, so the
    null preserves both the serial dependence and the ~monthly event spacing.

Date convention (stated explicitly — see README):
  - Event date t = official BLS news-release date (08:30 ET).
  - The release precedes the 09:30 open, so the t-1 close → t close change is the
    reaction window. Same-day measurement here is not lookahead.
  - Event-window offsets (T+1 … T+5, T-2 …) are TRADING days, not calendar days.
  - The "T-7" in the article slot name is a CALENDAR-day offset from the release
    the article previewed. The two conventions are unrelated; do not mix them.

Data period is deliberately left at the original run's window (2025-05-01 →
2026-05-26) so this rerun isolates the date fix. Extending the data would
confound "we fixed the dates" with "we added two months of data".
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

# ─── 1. Data Download ───────────────────────────────────────────────────────

print("Downloading VIX, VIX9D, SPY data...")
start = "2025-05-01"
end = "2026-05-26"

def load_sessions(symbol, start, end):
    """Download `symbol` and assert the result IS the XNYS session list for [start, end).

    Every offset in this script is row arithmetic, which silently assumes the index
    IS the trading calendar. Both ways that can break get handled, and they are not
    symmetric:

      - An EXTRA non-session row is an upstream quirk — yfinance quotes ^VIX for
        2026-05-25, Memorial Day, when NYSE and CBOE were shut. Dropped, loudly.
      - A MISSING session, a duplicate, or an out-of-order index silently corrupts
        every offset: "5 rows later" stops meaning "5 sessions later". No warning could
        make that safe, so it raises.

    The expected calendar is derived from the REQUESTED window, not from the data's
    own first/last row — otherwise a missing leading or trailing session defines
    itself away and becomes invisible.
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

# ─── 3. Map each release to its reaction session ───────────────────────────

MAX_SNAP_DAYS = 4  # a holiday weekend is the only legitimate gap

date_mapping = []


def to_trading_day(release_date, index):
    """The session that absorbs the release.

    BLS publishes at 08:30 ET on business days, so the release date is normally
    itself a trading day and this is an identity mapping. A release on a market
    holiday would push the reaction to the next session — legitimate, but bounded:
    only the next session within MAX_SNAP_DAYS counts. Anything further means the
    quote series has a hole, and mapping across a hole would silently relabel some
    unrelated day as the CPI reaction. We raise instead.

    The original searched +/-5 days in BOTH directions and took the first hit,
    which is precisely how a wrong date still produced a plausible number.
    """
    if release_date in index:
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
    date_mapping.append({"release": str(release_date.date()), "session": str(nxt.date()), "snapped": True})
    return nxt

cpi_trading_days = []
for d in cpi_dates:
    td = to_trading_day(d, vix_close.index)
    cpi_trading_days.append(td)
    print(f"  CPI {d.date()} → trading day {td.date()}")

n_snapped = sum(1 for m in date_mapping if m["snapped"])
print(f"\nMatched {len(cpi_trading_days)} CPI releases to trading days ({n_snapped} snapped)")

# ─── 4. Primary Evidence Numbers ────────────────────────────────────────────

# 4.1: CPI release day VIX % change
print("\n=== 4.1 CPI Day VIX % Change ===")
vix_pct_changes = []
for td in cpi_trading_days:
    pos = vix_close.index.get_loc(td)
    if pos > 0:
        prev = vix_close.iloc[pos - 1]
        curr = vix_close.iloc[pos]
        pct = (curr - prev) / prev * 100
        vix_pct_changes.append({
            'date': td,
            'vix_prev': float(prev),
            'vix_cpi_day': float(curr),
            'vix_pct_change': float(pct)
        })

vix_changes_arr = np.array([x['vix_pct_change'] for x in vix_pct_changes])
print(f"N CPI days with prev: {len(vix_changes_arr)}")
print(f"Mean VIX % change on CPI day: {vix_changes_arr.mean():.2f}%")
print(f"Median: {np.median(vix_changes_arr):.2f}%")
print(f"Std: {vix_changes_arr.std():.2f}%")
print(f"5th pct: {np.percentile(vix_changes_arr, 5):.2f}%")
print(f"95th pct: {np.percentile(vix_changes_arr, 95):.2f}%")
print(f"Min: {vix_changes_arr.min():.2f}%")
print(f"Max: {vix_changes_arr.max():.2f}%")

# Is the CPI-day mean distinguishable from zero at all?
t_zero, p_zero = stats.ttest_1samp(vix_changes_arr, 0.0)
print(f"One-sample t-test vs 0: t={t_zero:.3f}, p={p_zero:.4f}")

# 4.2: VIX/VIX9D ratio on CPI days vs non-event baseline
print("\n=== 4.2 VIX9D/VIX Ratio on CPI Days vs Baseline ===")
common_idx = vix_close.index.intersection(vix9d_close.index)
vix_aligned = vix_close.loc[common_idx]
vix9d_aligned = vix9d_close.loc[common_idx]
ratio = vix9d_aligned / vix_aligned  # VIX9D/VIX ratio

cpi_ratio_vals = []
for td in cpi_trading_days:
    if td in ratio.index:
        cpi_ratio_vals.append(float(ratio.loc[td]))

non_cpi_mask = ~ratio.index.isin(cpi_trading_days)
baseline_ratio = ratio.loc[non_cpi_mask]

cpi_ratio_arr = np.array(cpi_ratio_vals)
baseline_ratio_arr = baseline_ratio.values

print(f"CPI day VIX9D/VIX ratio: mean={cpi_ratio_arr.mean():.4f}, std={cpi_ratio_arr.std():.4f}, n={len(cpi_ratio_arr)}")
print(f"Non-CPI baseline ratio: mean={baseline_ratio_arr.mean():.4f}, std={baseline_ratio_arr.std():.4f}, n={len(baseline_ratio_arr)}")
print(f"Ratio difference (CPI - baseline): {cpi_ratio_arr.mean() - baseline_ratio_arr.mean():.4f}")

tstat, pval = stats.ttest_ind(cpi_ratio_arr, baseline_ratio_arr)
print(f"t-test (IID assumption, retained from original): t={tstat:.3f}, p={pval:.4f}")

# The t-test above treats 255 autocorrelated daily ratios as independent draws,
# which understates the standard error.
#
# The null we actually need: "the CPI mask carries no information about the ratio."
# So impose it. Each replicate stationary-bootstraps the WHOLE ratio series
# (Politis & Romano 1994, geometric block lengths, circular wrap), then applies the
# SAME fixed CPI positions and recomputes mask-mean minus complement-mean. That
# preserves two things at once: the serial dependence, and the actual geometry of
# the event mask — 12 dates roughly a month apart, not a contiguous 12-day clump.
# Resampling only a 12-long pseudo-sample of adjacent blocks would answer a
# different question and inflate the null spread.
BOOT_REPS = 10_000
BOOT_MEAN_BLOCK = 5  # trading days; geometric p = 1/5
rng = np.random.default_rng(20260717)  # seeded: reruns must reproduce exactly

ratio_vals = ratio.values
cpi_mask = ratio.index.isin(cpi_trading_days)


def _stationary_bootstrap_series(series, mean_block, rng):
    """Resample a full-length series, preserving serial dependence."""
    n = len(series)
    out = np.empty(n)
    i = 0
    while i < n:
        start = rng.integers(0, n)
        length = min(int(rng.geometric(1.0 / mean_block)), n - i)
        idx = (start + np.arange(length)) % n  # wrap: blocks stay contiguous in time
        out[i:i + length] = series[idx]
        i += length
    return out


observed_diff = float(ratio_vals[cpi_mask].mean() - ratio_vals[~cpi_mask].mean())
boot_diffs = np.empty(BOOT_REPS)
for b in range(BOOT_REPS):
    s = _stationary_bootstrap_series(ratio_vals, BOOT_MEAN_BLOCK, rng)
    boot_diffs[b] = s[cpi_mask].mean() - s[~cpi_mask].mean()

# Both summaries use the same absolute tail, so they agree in practice, but not
# identically by construction: the p-value carries the +1 finite-replication
# correction and tests >=, while np.percentile interpolates between order
# statistics. Near the boundary the two rules can disagree — here |obs| sits far
# inside, so nothing hinges on it. +1 correction: a Monte Carlo p of exactly 0 is
# not a real p-value.
boot_abs_crit = float(np.percentile(np.abs(boot_diffs), 95))
boot_pval = float((np.sum(np.abs(boot_diffs) >= abs(observed_diff)) + 1) / (BOOT_REPS + 1))
print(f"stationary block bootstrap ({BOOT_REPS} reps, mean block {BOOT_MEAN_BLOCK}d, seed 20260717):")
print(f"  null imposed on full series, fixed CPI mask ({int(cpi_mask.sum())} event days)")
print(f"  observed diff={observed_diff:+.4f}, |diff| 95% critical={boot_abs_crit:.4f}, two-sided p={boot_pval:.4f}")

# 4.3: VIX revert/persist after CPI (5 trading days)
print("\n=== 4.3 VIX Post-CPI 5-Day Behavior ===")
post_cpi_changes = {1: [], 2: [], 3: [], 4: [], 5: []}
post_cpi_vix9d_ratio = {-2: [], -1: [], 0: [], 1: [], 2: [], 3: [], 4: [], 5: []}

for td in cpi_trading_days:
    if td not in vix_close.index:
        continue
    pos = vix_close.index.get_loc(td)
    cpi_vix = vix_close.iloc[pos]

    for lag in range(1, 6):
        if pos + lag < len(vix_close):
            future_vix = vix_close.iloc[pos + lag]
            pct = (future_vix - cpi_vix) / cpi_vix * 100
            post_cpi_changes[lag].append(float(pct))

    # Ratio event window: -2 to +5 trading days around the release
    for offset in range(-2, 6):
        idx_pos = pos + offset
        if 0 <= idx_pos < len(vix_close):
            day = vix_close.index[idx_pos]
            if day in ratio.index:
                post_cpi_vix9d_ratio[offset].append(float(ratio.loc[day]))

print("VIX % change from release day:")
for lag in range(1, 6):
    arr = np.array(post_cpi_changes[lag])
    if len(arr) > 0:
        print(f"  T+{lag}: mean={arr.mean():.2f}%, median={np.median(arr):.2f}%, n={len(arr)}")

print("\nVIX9D/VIX ratio event window (relative to CPI day):")
for offset in sorted(post_cpi_vix9d_ratio.keys()):
    arr = np.array(post_cpi_vix9d_ratio[offset])
    if len(arr) > 0:
        print(f"  T{offset:+d}: mean={arr.mean():.4f}, n={len(arr)}")

# ─── 5. Build Summary Table ─────────────────────────────────────────────────

table_rows = []
for row in vix_pct_changes:
    td = row['date']
    ratio_val = float(ratio.loc[td]) if td in ratio.index else None
    pos = vix_close.index.get_loc(td)
    if pos + 5 < len(vix_close):
        post5 = (vix_close.iloc[pos + 5] - vix_close.iloc[pos]) / vix_close.iloc[pos] * 100
    else:
        post5 = None

    table_rows.append({
        'CPI 發布日': td.strftime('%Y-%m-%d'),
        'VIX（T-1）': round(row['vix_prev'], 2),
        'VIX（當日）': round(row['vix_cpi_day'], 2),
        'VIX 當日漲跌': f"{row['vix_pct_change']:+.1f}%",
        'VIX9D/VIX 比值': f"{ratio_val:.3f}" if ratio_val else 'N/A',
        'VIX T+5 變化': f"{post5:+.1f}%" if post5 is not None else 'N/A',
    })

df_table = pd.DataFrame(table_rows)
print("\nSummary Table:")
print(df_table.to_string(index=False))

# ─── 6. Figure 1: CPI Day VIX % Change Distribution ────────────────────────

n_events = len(vix_changes_arr)
span_lo = pd.Timestamp(vix_pct_changes[0]['date']).strftime('%Y-%m')
span_hi = pd.Timestamp(vix_pct_changes[-1]['date']).strftime('%Y-%m')

fig1, ax = plt.subplots(figsize=(9, 5))
colors = ['#d32f2f' if x > 0 else '#1565c0' for x in vix_changes_arr]
bars = ax.bar(range(len(vix_changes_arr)), vix_changes_arr, color=colors, alpha=0.8, edgecolor='white')
ax.axhline(0, color='black', linewidth=0.8, linestyle='--', alpha=0.5)
ax.axhline(vix_changes_arr.mean(), color='#ff6f00', linewidth=2, linestyle='-',
           label=f'平均值 {vix_changes_arr.mean():+.1f}%')
ax.axhline(np.median(vix_changes_arr), color='#7b1fa2', linewidth=2, linestyle='--',
           label=f'中位數 {np.median(vix_changes_arr):+.1f}%')

p5, p95 = np.percentile(vix_changes_arr, 5), np.percentile(vix_changes_arr, 95)
ax.axhspan(p5, p95, alpha=0.07, color='grey', label=f'5th–95th 區間 ({p5:.1f}% ~ {p95:.1f}%)')

labels = [pd.Timestamp(r['date']).strftime('%y-%m-%d') for r in vix_pct_changes]
ax.set_xticks(range(len(vix_changes_arr)))
ax.set_xticklabels(labels, rotation=45, ha='right', fontsize=8)

ax.set_xlabel('CPI 官方發布日', fontsize=11)
ax.set_ylabel('VIX 當日漲跌幅（%）', fontsize=11)
ax.set_title(f'US CPI 官方發布日的 VIX 漲跌幅\n（{span_lo} 至 {span_hi}，共 {n_events} 次官方發布）',
             fontsize=13, fontweight='bold')
ax.legend(fontsize=9, loc='upper left')
ax.yaxis.grid(True, alpha=0.3)
ax.set_axisbelow(True)

for i, v in enumerate(vix_changes_arr):
    ax.text(i, v + (0.3 if v >= 0 else -0.5), f'{v:+.1f}', ha='center', va='bottom' if v >= 0 else 'top',
            fontsize=7.5, color='#333')

fig1.text(0.99, 0.01, '資料來源：yfinance / CBOE ^VIX；發布日取自 FRED/ALFRED 官方發布日曆',
          ha='right', va='bottom', fontsize=7, color='grey')
plt.tight_layout()
fig1.savefig(OUT_DIR / 'fig1_cpi_day_vix_dist.png', dpi=150, bbox_inches='tight')
plt.close()
print("\nFig 1 saved: fig1_cpi_day_vix_dist.png")

# ─── 7. Figure 2: VIX9D/VIX Ratio Event Window ──────────────────────────────

fig2, ax2 = plt.subplots(figsize=(9, 5))
offsets = sorted([k for k in post_cpi_vix9d_ratio.keys() if len(post_cpi_vix9d_ratio[k]) >= 3])
means = [np.mean(post_cpi_vix9d_ratio[o]) for o in offsets]
stds = [np.std(post_cpi_vix9d_ratio[o]) / np.sqrt(len(post_cpi_vix9d_ratio[o])) for o in offsets]  # SE

ax2.plot(offsets, means, 'o-', color='#1565c0', linewidth=2.2, markersize=7, label='CPI 事件窗口平均')
ax2.fill_between(offsets,
                 np.array(means) - np.array(stds),
                 np.array(means) + np.array(stds),
                 alpha=0.2, color='#1565c0', label='±1 SE 信賴帶')

ax2.axhline(baseline_ratio_arr.mean(), color='#ff6f00', linewidth=1.8, linestyle='--',
            label=f'非 CPI 日基準 {baseline_ratio_arr.mean():.3f}')

ax2.axvline(0, color='red', linewidth=1.2, linestyle=':', alpha=0.8)
ax2.text(0.1, ax2.get_ylim()[0] + 0.001, 'CPI 發布日', color='red', fontsize=9, rotation=90, va='bottom')

ax2.set_xlabel('相對 CPI 發布日的交易日（0=發布日）', fontsize=11)
ax2.set_ylabel('VIX9D / VIX 比值', fontsize=11)
ax2.set_title(f'CPI 事件窗口 VIX9D/VIX 比值路徑\n（{span_lo} 至 {span_hi}，{n_events} 次官方發布平均）',
              fontsize=13, fontweight='bold')
ax2.legend(fontsize=9)
ax2.yaxis.grid(True, alpha=0.3)
ax2.xaxis.set_major_locator(plt.MultipleLocator(1))
ax2.set_axisbelow(True)

fig2.text(0.99, 0.01, '資料來源：yfinance / CBOE ^VIX ^VIX9D；發布日取自 FRED/ALFRED 官方發布日曆',
          ha='right', va='bottom', fontsize=7, color='grey')
plt.tight_layout()
fig2.savefig(OUT_DIR / 'fig2_vix_term_event_window.png', dpi=150, bbox_inches='tight')
plt.close()
print("Fig 2 saved: fig2_vix_term_event_window.png")

# ─── 8. Save evidence JSON ──────────────────────────────────────────────────

evidence = {
    "event": "US CPI (T-7 preview article, mile_ebb5d6f5)",
    "article_slot": "T-7",
    "errata_rerun": {
        "date": "2026-07-17",
        "reason": "original run hard-coded CPI release dates from a 13th-of-month proxy; 7 of 13 were wrong and the 2025-11-13 entry was a release that never happened (October-2025 reference month cancelled during the shutdown; CPIAUCSL has no 2025-10-01 observation)",
        "event_date_source": "FRED/ALFRED release calendar (release_id=10) via volpred.data.event_dates.cpi_release_dates",
        "data_window_unchanged": True,
        "method_unchanged": False,
        "method_deltas": [
            "event-session alignment changed from bidirectional +/-5-day nearest-match to forward-only, bounded (MAX_SNAP_DAYS=4), fail-closed; behavioural change, inert on this data (all 12 mappings are identities)",
            "added one-sample t-test of CPI-day mean vs zero (new statistic; changes no pre-existing number)",
            "fixed latent off-by-one in ratio event window: original bounded offset against len(ratio.index)=267 while indexing vix_close.index=268",
            "added null-imposed stationary block bootstrap for the CPI-vs-baseline ratio comparison; the original IID t-test is retained alongside for comparability",
            "enforces the complete requested XNYS session calendar before any analysis: drops extra non-session rows (yfinance returns a ^VIX quote for Memorial Day 2026-05-25 when the exchange was closed) and RAISES on missing, duplicate, or out-of-order sessions, with expected sessions derived from the requested window rather than the data's own bounds. Verified to change zero reported numbers, since ^VIX9D lacks that row and all 12 events precede it",
        ],
        "inference_limits": [
            "reported std uses ddof=0 and is purely descriptive; this script runs no F-test (that is the T-2 pack)",
            "vix9d_vix_ratio ttest_pval assumes equal-variance IID against an autocorrelated daily series and understates the standard error; cite bootstrap_pval instead for any significance claim",
        ],
    },
    "data_period": f"{start} to {end}",
    "official_release_dates": [d.strftime('%Y-%m-%d') for d in cpi_dates],
    "release_to_session_mapping": date_mapping,
    "cpi_dates_n": len(cpi_trading_days),
    "date_convention": {
        "event_date": "official BLS news-release date, published 08:30 ET",
        "reaction_window": "t-1 close to t close; release at 08:30 precedes the 09:30 open, so same-day measurement is not lookahead",
        "event_window_offsets": "trading days, not calendar days",
        "article_slot_naming": "T-7 is a calendar-day offset from the previewed release; unrelated to the trading-day offsets above",
    },
    "primary_numbers": {
        "cpi_day_vix_pct_change": {
            "mean": round(float(vix_changes_arr.mean()), 3),
            "median": round(float(np.median(vix_changes_arr)), 3),
            "std": round(float(vix_changes_arr.std()), 3),
            "p5": round(float(np.percentile(vix_changes_arr, 5)), 3),
            "p95": round(float(np.percentile(vix_changes_arr, 95)), 3),
            "min": round(float(vix_changes_arr.min()), 3),
            "max": round(float(vix_changes_arr.max()), 3),
            "n": len(vix_changes_arr),
            "ttest_vs_zero_stat": round(float(t_zero), 3),
            "ttest_vs_zero_pval": round(float(p_zero), 4),
        },
        "vix9d_vix_ratio": {
            "cpi_day_mean": round(float(cpi_ratio_arr.mean()), 4),
            "cpi_day_std": round(float(cpi_ratio_arr.std()), 4),
            "baseline_mean": round(float(baseline_ratio_arr.mean()), 4),
            "baseline_std": round(float(baseline_ratio_arr.std()), 4),
            "difference": round(float(cpi_ratio_arr.mean() - baseline_ratio_arr.mean()), 4),
            "ttest_stat": round(float(tstat), 3),
            "ttest_pval": round(float(pval), 4),
            "ttest_caveat": "assumes equal-variance IID draws from an autocorrelated daily baseline; understates SE. Retained for comparability with the original run. Use bootstrap_pval for inference.",
            "bootstrap_pval": round(boot_pval, 4),
            "bootstrap_abs_95_critical": round(boot_abs_crit, 4),
            "bootstrap_observed_diff": round(observed_diff, 4),
            "bootstrap_spec": (
                f"stationary block bootstrap (Politis & Romano 1994), {BOOT_REPS} reps, "
                f"geometric mean block {BOOT_MEAN_BLOCK} trading days, seed 20260717. "
                "Null imposed by resampling the FULL ratio series and reapplying the same fixed "
                "CPI mask each replicate, so both the serial dependence and the ~monthly event "
                f"spacing are preserved. p = (#|boot| >= |obs| + 1)/(reps + 1). "
                "bootstrap_abs_95_critical is the 95th percentile of |boot| — same absolute tail, "
                "but an interpolated quantile against a +1-corrected p, so 'p<0.05' and "
                "'|obs| > critical' are a coarse consistency check, not an exact equivalence. "
                "Here |obs| sits far inside, so the distinction does not bite."
            ),
        },
        "post_cpi_5day_vix": {
            f"T+{lag}": {
                "mean": round(float(np.mean(post_cpi_changes[lag])), 3),
                "median": round(float(np.median(post_cpi_changes[lag])), 3),
                "n": len(post_cpi_changes[lag])
            }
            for lag in range(1, 6) if post_cpi_changes[lag]
        }
    },
    "table_rows": table_rows,
    "ratio_event_window": {
        str(k): {
            "mean": round(float(np.mean(v)), 4),
            "n": len(v)
        }
        for k, v in post_cpi_vix9d_ratio.items() if v
    }
}

tmp = OUT_DIR / 'evidence.json.tmp'
tmp.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, default=str) + "\n")
json.loads(tmp.read_text())  # fail before replacing the real file, not after
tmp.replace(OUT_DIR / 'evidence.json')

print("\nEvidence saved to evidence.json")
print("\n=== SUMMARY OF PRIMARY NUMBERS ===")
print(json.dumps(evidence['primary_numbers'], ensure_ascii=False, indent=2))
