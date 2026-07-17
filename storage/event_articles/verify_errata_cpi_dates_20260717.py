"""Independent cross-check of the 2026-07-17 CPI errata rerun.

A rerun that agrees with itself proves nothing. This recomputes every number the
two articles quote — except the T-7 block bootstrap, which is only checked for
internal consistency (see below) — along deliberately different code paths, and
asserts they match the evidence JSONs the analysis scripts wrote.

Independence, and — more importantly — its limits, per axis:

  - Event dates, path A: raw ALFRED /release/dates HTTP call with different params
    (descending sort, no include-with-no-data) and a dict-based dedup instead of
    the module's groupby. Catches an implementation bug in the module. Does NOT
    catch a shared conceptual error, since it applies the same last-per-month rule.
  - Event dates, path B: /series/vintagedates for CPIAUCSL. Per FRED's docs a
    vintage date is a date on which values were released OR revised — so this is
    NOT a pure first-release oracle, and its agreement here additionally assumes
    no extra revision vintages landed in this window. What it does give is a
    different endpoint with no last-per-month rule anywhere in it, which is the
    one thing path A cannot provide: if that dedup rule were conceptually wrong,
    the module and path A would agree with each other and disagree with B.
  - Reactions and event windows: recomputed with different pandas idioms
    (pct_change / shift + reindex) instead of the scripts' index.get_loc()/iloc
    walk. This catches implementation bugs — it is how the ratio-window wrong-bound
    defect would have surfaced.
    LIMIT, stated plainly: this is NOT a non-positional cross-check. pandas
    Series.shift(n) moves by row count, exactly like pos+offset does. Both sides
    share the premise that "N trading days later" means "N rows later". Pinning
    the release dates does NOT cover that premise — date agreement cannot see a
    missing session inside the VIX series. So the premise is tested directly
    against the XNYS session calendar (exchange_calendars): a missing or duplicated
    session fails the run, while a non-session row present in the raw feed is
    reported and must be absent from the filtered series the analysis uses.
  - The T-7 block bootstrap is seeded (20260717) and reproducible by rerunning the
    script; it is NOT independently reimplemented here. Only its presence,
    well-formedness, and internal consistency are checked. The global "reproduced"
    claim below therefore explicitly excludes it.

Exit code 0 = every check matched. Run:
    FRED_API_KEY=... uv run python storage/event_articles/verify_errata_cpi_dates_20260717.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import yfinance as yf
from scipy import stats

HERE = Path(__file__).resolve().parent
T2 = HERE / "us_cpi_2026_06_11_t2"
T7 = HERE / "us_cpi_2026_06_13_t7"

TOL = 0.01  # percentage points; the scripts round to 3dp

failures: list[str] = []


def api_key() -> str:
    key = os.environ.get("FRED_API_KEY")
    if key:
        return key
    # resolve upward from this file, not from an assumed home layout
    for root in Path(__file__).resolve().parents:
        for cand in (".env.local", ".env"):
            p = root / cand
            if p.exists():
                for line in p.read_text().splitlines():
                    if line.startswith("FRED_API_KEY"):
                        return line.split("=", 1)[1].strip().strip("\"'")
    raise RuntimeError("FRED_API_KEY not found in env or any ancestor .env/.env.local")


def _fred(path: str, **params):
    r = requests.get(
        f"https://api.stlouisfed.org/fred/{path}",
        params={"api_key": api_key(), "file_type": "json", **params},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def dates_via_release_calendar(start: str, end: str) -> list[str]:
    """Path A: release calendar, different params + different dedup than the module."""
    raw = sorted(d["date"] for d in _fred(
        "release/dates", release_id=10, realtime_start=start, realtime_end=end,
        limit=1000, sort_order="desc",
    )["release_dates"])
    last_per_month: dict[str, str] = {}
    for d in raw:
        last_per_month[d[:7]] = d
    return sorted(last_per_month.values())


def dates_via_vintages(start: str, end: str) -> list[str]:
    """Path B: vintage dates — different endpoint, no last-per-month rule.

    Per FRED's docs these are dates on which values were released *or revised*,
    so this is a corroborating diagnostic rather than a first-release oracle.
    """
    return sorted(_fred(
        "series/vintagedates", series_id="CPIAUCSL",
        realtime_start=start, realtime_end=end, limit=1000,
    )["vintage_dates"])


def _xnys_sessions(lo, hi) -> pd.DatetimeIndex:
    import exchange_calendars as xcals
    s = xcals.get_calendar("XNYS").sessions_in_range(lo, hi)
    return pd.DatetimeIndex([d.tz_localize(None) if d.tz else d for d in s])


_SERIES_CACHE: dict[tuple, pd.Series] = {}
_SESSION_NOTES: dict[tuple, list[str]] = {}


def load_vix(start: str, end: str, symbol: str = "^VIX") -> pd.Series:
    """Quotes for [start, end), validated against the XNYS calendar and cached.

    Validation lives HERE, not in a separate pass, so there is exactly one download
    per (window, symbol) and the series every check computes on IS the series that
    was validated. A separate validate-then-reload would prove a property of an
    instance nobody uses.

    Expected sessions come from the REQUESTED window, not the data's own first and
    last row — bounding by the data lets a missing leading or trailing session
    define itself away.

    Asymmetric by design:
      - EXTRA non-session row: upstream yfinance quirk (it quotes ^VIX on Memorial
        Day 2026-05-25, when CBOE and NYSE were shut). Dropped, noted.
      - MISSING session / duplicate / out-of-order: silently corrupts every row
        offset. Raises — no report could make computing on it safe.
    """
    key = (start, end, symbol)
    if key in _SERIES_CACHE:
        return _SERIES_CACHE[key]

    s = yf.download(symbol, start=start, end=end, auto_adjust=True, progress=False)["Close"].squeeze()
    expected = _xnys_sessions(pd.Timestamp(start), pd.Timestamp(end) - pd.Timedelta(days=1))
    idx = pd.DatetimeIndex(s.index)

    dupes = idx[idx.duplicated()]
    if len(dupes):
        raise RuntimeError(f"{symbol} {start}..{end}: duplicated rows {[str(d.date()) for d in dupes]}")

    junk = idx.difference(expected)
    if len(junk):
        _SESSION_NOTES[key] = [str(d.date()) for d in junk]
        s = s[~idx.isin(junk)]

    got = pd.DatetimeIndex(s.index)
    missing = expected.difference(got)
    if len(missing):
        raise RuntimeError(
            f"{symbol} {start}..{end}: {len(missing)} XNYS session(s) absent "
            f"({[str(d.date()) for d in missing[:5]]}); row offsets would walk past the hole"
        )
    # set equality is not enough: a permuted index passes missing/extra/dupe checks
    # and still corrupts every offset. Assert ordered equality.
    if not got.equals(expected):
        raise RuntimeError(f"{symbol} {start}..{end}: index is not the XNYS session list in order")

    _SERIES_CACHE[key] = s
    return s


def validate_sessions(start: str, end: str, label: str) -> None:
    """Report the session-integrity result for the series the checks actually use.

    The enforcement is in load_vix (which raises); this only surfaces what happened,
    including the extended reconciliation window, which load_vix validates too.
    """
    expected = _xnys_sessions(pd.Timestamp(start), pd.Timestamp(end) - pd.Timedelta(days=1))
    got = pd.DatetimeIndex(load_vix(start, end).index)     # cached: no second download
    junk = _SESSION_NOTES.get((start, end, "^VIX"), [])
    if junk:
        print(f"  [note] {label} raw feed carried {len(junk)} non-session row(s): {junk[:5]}"
              f" — dropped by both the analysis and this check")
    print(f"  [OK ] {label} session integrity: index == XNYS session list for the requested "
          f"window, in order ({len(got)} rows, {len(expected)} expected)")


def reactions(vix: pd.Series, dates: list[str]) -> pd.Series:
    """CPI-day VIX % change via pct_change + reindex, not the scripts' get_loc/iloc.

    A different implementation, not a different concept — pct_change is row-adjacent
    just as iloc[pos-1] is. See the module docstring.
    """
    pct = vix.pct_change() * 100
    idx = pd.to_datetime(dates)
    idx = idx[idx.isin(pct.index)]
    return pct.reindex(idx).dropna()


def window_change(vix: pd.Series, dates: list[str], offset: int) -> np.ndarray:
    """VIX % change at trading-day `offset` relative to each release day.

    Different idiom from the scripts (shift + reindex vs get_loc + iloc), so an
    implementation slip on either side shows up. Note this is still a row-count
    offset — see the module docstring; it does not test the "N rows == N trading
    days" premise that both sides share.
    """
    shifted = vix.shift(-offset)
    rel = (shifted / vix - 1.0) * 100
    idx = pd.to_datetime([d for d in dates if pd.Timestamp(d) in vix.index])
    return rel.reindex(idx).dropna().values


def series_at_offset(vix: pd.Series, series: pd.Series, dates: list[str], offset: int) -> np.ndarray:
    """Values of `series` at trading-day `offset` around each release, by reindex."""
    idx = pd.to_datetime([d for d in dates if pd.Timestamp(d) in vix.index])
    pos = [vix.index.get_indexer([d])[0] + offset for d in idx]
    days = [vix.index[p] for p in pos if 0 <= p < len(vix.index)]
    return series.reindex(pd.DatetimeIndex(days)).dropna().values


def check(label: str, got: float, want: float, tol: float = TOL) -> None:
    ok = abs(got - want) <= tol
    print(f"  [{'OK ' if ok else 'MISMATCH'}] {label}: independent={got:.4f} vs evidence={want:.4f}")
    if not ok:
        failures.append(label)


def check_eq(label: str, got, want) -> None:
    ok = got == want
    print(f"  [{'OK ' if ok else 'MISMATCH'}] {label}: independent={got} vs evidence={want}")
    if not ok:
        failures.append(label)


print("=== Independent cross-check of CPI errata rerun (2026-07-17) ===\n")

# ── Dates: two independent paths must agree with each other AND the evidence ──
print("Event dates — three-way agreement (module output vs release calendar vs vintages)")
ev7 = json.loads((T7 / "evidence.json").read_text())
ev2 = json.loads((T2 / "evidence.json").read_text())

for label, ev, lo, hi in (("T-7", ev7, "2025-05-01", "2026-05-26"), ("T-2", ev2, "2025-05-01", "2026-06-08")):
    a = [d for d in dates_via_release_calendar(lo, hi) if lo <= d <= hi]
    b = [d for d in dates_via_vintages(lo, hi) if lo <= d <= hi]
    check_eq(f"{label} release-calendar vs evidence", a, ev["official_release_dates"])
    check_eq(f"{label} vintage-dates vs evidence", b, ev["official_release_dates"])

# The phantom release, checked at the source: no October-2025 CPI value exists.
obs = {o["date"]: o["value"] for o in _fred(
    "series/observations", series_id="CPIAUCSL",
    observation_start="2025-09-01", observation_end="2025-12-01")["observations"]}
oct_val = obs.get("2025-10-01")
ok = oct_val == "."
print(f"  [{'OK ' if ok else 'MISMATCH'}] 2025-10 reference month has no CPI value: got {oct_val!r}")
if not ok:
    failures.append("2025-10 phantom-release premise")

# ── T-7 ────────────────────────────────────────────────────────────────────
print("\nT-7 (mile_ebb5d6f5), window 2025-05-01 → 2026-05-26")
d7 = ev7["official_release_dates"]
vix7 = load_vix("2025-05-01", "2026-05-26")
validate_sessions("2025-05-01", "2026-05-26", "T-7")
r7 = reactions(vix7, d7)
p7 = ev7["primary_numbers"]["cpi_day_vix_pct_change"]

check_eq("N", len(r7), p7["n"])
check("cpi_day mean", float(r7.mean()), p7["mean"])
check("cpi_day median", float(np.median(r7.values)), p7["median"])
check("cpi_day std", float(r7.std(ddof=0)), p7["std"])
check("cpi_day p5", float(np.percentile(r7.values, 5)), p7["p5"])
check("cpi_day p95", float(np.percentile(r7.values, 95)), p7["p95"])
check("cpi_day min", float(r7.min()), p7["min"])
check("cpi_day max", float(r7.max()), p7["max"])

t0, pp0 = stats.ttest_1samp(r7.values, 0.0)
check("cpi_day t-vs-0 stat", float(t0), p7["ttest_vs_zero_stat"])
check("cpi_day t-vs-0 pval", float(pp0), p7["ttest_vs_zero_pval"], tol=0.001)

# T+1..T+5, recomputed by label-shift
print("  post-CPI window (label-shift recompute):")
for lag in range(1, 6):
    arr = window_change(vix7, d7, lag)
    want = ev7["primary_numbers"]["post_cpi_5day_vix"][f"T+{lag}"]
    check(f"    T+{lag} mean", float(arr.mean()), want["mean"])
    check(f"    T+{lag} median", float(np.median(arr)), want["median"])
    check_eq(f"    T+{lag} n", len(arr), want["n"])

# VIX9D/VIX ratio comparison
vix9d7 = load_vix("2025-05-01", "2026-05-26", symbol="^VIX9D")
common7 = vix7.index.intersection(vix9d7.index)
ratio7 = (vix9d7.loc[common7] / vix7.loc[common7])
ev_dates7 = pd.to_datetime(d7)
cpi_ratio7 = ratio7.reindex(ev_dates7).dropna()
base_ratio7 = ratio7[~ratio7.index.isin(ev_dates7)]
pr7 = ev7["primary_numbers"]["vix9d_vix_ratio"]
check("ratio cpi-day mean", float(cpi_ratio7.mean()), pr7["cpi_day_mean"], tol=0.001)
check("ratio baseline mean", float(base_ratio7.mean()), pr7["baseline_mean"], tol=0.001)
check("ratio difference", float(cpi_ratio7.mean() - base_ratio7.mean()), pr7["difference"], tol=0.001)
check("ratio cpi-day std", float(cpi_ratio7.std(ddof=0)), pr7["cpi_day_std"], tol=0.001)
check("ratio baseline std", float(base_ratio7.std(ddof=0)), pr7["baseline_std"], tol=0.001)
tr, pr = stats.ttest_ind(cpi_ratio7.values, base_ratio7.values)
check("ratio t-stat", float(tr), pr7["ttest_stat"], tol=0.01)
check("ratio p-val", float(pr), pr7["ttest_pval"], tol=0.001)

# Bootstrap: seeded and reproducible by rerun, NOT reimplemented here. Check only
# that it is present, well-formed, and coarsely self-consistent.
#
# "p<0.05 iff |obs| > critical" is NOT an exact equivalence: the p-value carries the
# +1 finite-replication correction and tests >=, while the critical value is an
# interpolated quantile. Near the boundary they can legitimately disagree, so a
# disagreement there is reported, not failed. Only a gross contradiction — the two
# rules pointing opposite ways with |obs| nowhere near the critical value — is a
# real inconsistency.
bp = pr7.get("bootstrap_pval")
crit = pr7.get("bootstrap_abs_95_critical")
bobs = pr7.get("bootstrap_observed_diff")
if bp is None or crit is None or bobs is None:
    failures.append("bootstrap fields missing")
    print("  [MISMATCH] bootstrap_pval / bootstrap_abs_95_critical / bootstrap_observed_diff absent")
else:
    check("bootstrap observed_diff vs reported difference", float(bobs), pr7["difference"], tol=0.001)
    agree = (bp < 0.05) == (abs(bobs) > crit)
    near_boundary = abs(abs(bobs) - crit) < 0.1 * crit  # where the two rules may differ
    if agree:
        print(f"  [OK ] bootstrap coarse consistency: |diff|={abs(bobs):.4f} vs |diff| 95% "
              f"critical={crit:.4f}, p={bp:.4f} — both rules agree")
    elif near_boundary:
        print(f"  [note] bootstrap rules disagree but |diff|={abs(bobs):.4f} is within 10% of the "
              f"critical value {crit:.4f} — expected near the boundary, not an inconsistency")
    else:
        print(f"  [MISMATCH] bootstrap gross inconsistency: |diff|={abs(bobs):.4f}, critical="
              f"{crit:.4f}, p={bp:.4f} — rules disagree far from the boundary")
        failures.append("bootstrap p-value grossly inconsistent with its critical value")

# T-7 ratio event window — the article quotes T+3 and T+4 from this
print("  ratio event window (article quotes T+3, T+4):")
for off_s, want in ev7["ratio_event_window"].items():
    arr = series_at_offset(vix7, ratio7, d7, int(off_s))
    check(f"    T{int(off_s):+d} mean", float(arr.mean()), want["mean"], tol=0.001)
    check_eq(f"    T{int(off_s):+d} n", len(arr), want["n"])

# T-7 per-row table values — the article prints this whole table, every column
print("  per-row table values (all columns):")
for row in ev7["table_rows"]:
    d = pd.Timestamp(row["CPI 發布日"])
    lbl = row["CPI 發布日"]
    check(f"    {lbl} VIX(T-1)", float(vix7.shift(1)[d]), row["VIX（T-1）"], tol=0.01)
    check(f"    {lbl} VIX(day)", float(vix7[d]), row["VIX（當日）"], tol=0.01)
    check(f"    {lbl} pct", float(r7[d]), float(row["VIX 當日漲跌"].rstrip('%')), tol=0.06)
    if row["VIX9D/VIX 比值"] != "N/A":
        check(f"    {lbl} ratio", float(ratio7[d]), float(row["VIX9D/VIX 比值"]), tol=0.001)
    if row["VIX T+5 變化"] != "N/A":
        pos = vix7.index.get_indexer([d])[0]
        got = (vix7.iloc[pos + 5] / vix7.iloc[pos] - 1) * 100
        check(f"    {lbl} T+5", float(got), float(row["VIX T+5 變化"].rstrip('%')), tol=0.06)

# ── T-2 ────────────────────────────────────────────────────────────────────
print("\nT-2 (mile_0fa9c7f5), window 2025-05-01 → 2026-06-09")
d2 = ev2["official_release_dates"]
vix2 = load_vix("2025-05-01", "2026-06-09")
validate_sessions("2025-05-01", "2026-06-09", "T-2")
r2 = reactions(vix2, d2)
recent4 = r2.iloc[-4:]
earlier = r2.iloc[:-4]

p2r = ev2["primary_numbers"]["recent4_vix_day_pct"]
p2e = ev2["primary_numbers"]["earlier_vix_day_pct"]
check("recent4 mean", float(recent4.mean()), p2r["mean"])
check("recent4 std", float(recent4.std(ddof=0)), p2r["std"])
check("recent4 min", float(recent4.min()), p2r["min"])
check("recent4 max", float(recent4.max()), p2r["max"])
check("earlier mean", float(earlier.mean()), p2e["mean"])
check("earlier std", float(earlier.std(ddof=0)), p2e["std"])
check_eq("earlier n", len(earlier), p2e["n"])

# per-event values quoted in the article table
for row in p2r["values"]:
    got = float(r2[pd.Timestamp(row["date"])])
    check(f"  {row['date']} reaction", got, row["pct"])

F_ind = earlier.var(ddof=1) / recent4.var(ddof=1)
p_ind = 1 - stats.f.cdf(F_ind, len(earlier) - 1, len(recent4) - 1)
pf = ev2["primary_numbers"]["variance_compression_ftest"]
check("F stat", float(F_ind), pf["F_stat"], tol=0.05)
check("F pval", float(p_ind), pf["one_sided_pval"], tol=0.001)
check_eq("F df_earlier", len(earlier) - 1, pf["df_earlier"])
check_eq("F df_recent", len(recent4) - 1, pf["df_recent"])

# pre-event run-up, by label-shift
print("  pre-CPI run-up (label-shift recompute):")
for off in range(-5, 0):
    arr = window_change(vix2, d2, off)
    want = ev2["primary_numbers"]["pre_cpi_runup"][f"T{off:+d}"]
    check(f"    T{off:+d} mean", float(arr.mean()), want["mean_pct_vs_cpi_day"])
    check_eq(f"    T{off:+d} n", len(arr), want["n"])

# term structure / z-score
vix9d2 = load_vix("2025-05-01", "2026-06-09", symbol="^VIX9D")
common2 = vix2.index.intersection(vix9d2.index)
ratio2 = (vix9d2.loc[common2] / vix2.loc[common2])
base2 = ratio2[~ratio2.index.isin(pd.to_datetime(d2))]
pt = ev2["primary_numbers"]["current_term_structure"]
check("latest5 ratio mean", float(ratio2.iloc[-5:].mean()), pt["latest5_ratio_mean"], tol=0.001)
check("latest10 ratio mean", float(ratio2.iloc[-10:].mean()), pt["latest10_ratio_mean"], tol=0.001)
check("baseline ratio mean", float(base2.mean()), pt["baseline_ratio_mean"], tol=0.001)
check("baseline ratio std", float(base2.std()), pt["baseline_ratio_std"], tol=0.001)
z = (ratio2.iloc[-5:].mean() - base2.mean()) / base2.std()
check("latest5 z-score", float(z), pt["z_score_latest5_vs_baseline"], tol=0.01)
# current-state values the article quotes in prose and in the fig2 annotation
check("current VIX", float(vix2.iloc[-1]), pt["vix"], tol=0.01)
check("current VIX9D", float(vix9d2.iloc[-1]), pt["vix9d"], tol=0.01)
check("current ratio", float(vix9d2.iloc[-1] / vix2.iloc[-1]), pt["ratio_vix9d_vix"], tol=0.001)
check_eq("as-of date", str(vix2.index[-1].date()), pt["as_of_date"])

# T-2 per-row recent-4 table: ratio + T+5 columns the article prints
print("  per-row recent-4 table (ratio / T+5 columns):")
for row in ev2["table_rows_recent4"]:
    d = pd.Timestamp(row["CPI 發布日"])
    check(f"    {row['CPI 發布日']} VIX(T-1)", float(vix2.shift(1)[d]), row["VIX（T-1）"], tol=0.01)
    check(f"    {row['CPI 發布日']} VIX(day)", float(vix2[d]), row["VIX（當日）"], tol=0.01)
    if row["VIX9D/VIX 比值"] != "N/A":
        check(f"    {row['CPI 發布日']} ratio", float(ratio2[d]), float(row["VIX9D/VIX 比值"]), tol=0.001)
    if row["VIX T+5 變化"] != "N/A":
        pos = vix2.index.get_indexer([d])[0]
        got = (vix2.iloc[pos + 5] / vix2.iloc[pos] - 1) * 100
        check(f"    {row['CPI 發布日']} T+5", float(got), float(row["VIX T+5 變化"].rstrip('%')), tol=0.06)

# latest-10 table quoted in the evidence pack
print("  latest-10 days:")
for row in ev2["latest_10_days"]:
    d = pd.Timestamp(row["date"])
    check(f"    {row['date']} vix", float(vix2[d]), row["vix"], tol=0.01)
    check(f"    {row['date']} vix9d", float(vix9d2[d]), row["vix9d"], tol=0.01)
    check(f"    {row['date']} ratio", float(ratio2[d]), row["ratio"], tol=0.001)

# ── Reconciliation with the already-published -0.847% ──────────────────────
# The 2026-07-12 errata article (mile_9560b9cc) reported -0.847% on official
# dates. That is a different window: it runs through the 2026-06-10 release,
# which the T-7 article (published 2026-05-26) could not have contained. Confirm
# the two reconcile, so nobody "fixes" one to match the other.
print("\nReconciliation with published -0.847% (mile_9560b9cc, window through 2026-06-10)")
d_ext = [d for d in dates_via_vintages("2025-05-01", "2026-06-30") if "2025-05-13" <= d <= "2026-06-10"]
vix_ext = load_vix("2025-05-01", "2026-06-30")
r_ext = reactions(vix_ext, d_ext)
print(f"  extended window: N={len(r_ext)}, mean={r_ext.mean():.3f}%")
check("extended-window mean vs published", float(r_ext.mean()), -0.847, tol=0.02)
june = r_ext[r_ext.index == pd.Timestamp("2026-06-10")]
if len(june):
    print(f"  the extra event: 2026-06-10 VIX {float(june.iloc[0]):+.2f}% "
          f"— this single release is the whole gap between -1.90% and -0.847%")

# ── Verdict ────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
if failures:
    print(f"FAILED — {len(failures)} mismatch(es): {failures}")
    sys.exit(1)
print("ALL CHECKS PASSED — every number the articles quote, except the T-7 bootstrap,")
print("was reproduced via a separate implementation; the bootstrap was checked for")
print("internal consistency only. VIX session integrity validated against XNYS.")
