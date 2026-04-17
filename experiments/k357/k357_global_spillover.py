#!/usr/bin/env python3
"""
K357: Global Volatility Spillover Network — Which Countries Export Fear?
========================================================================
Jump exploration: Build a directed volatility spillover graph across countries.

Data: yfinance country ETFs (~15-20 years)
  SPY (US), EWJ (Japan), VGK (Europe), EEM (Emerging), EWZ (Brazil),
  FXI (China), EWY (South Korea), EWT (Taiwan), EWA (Australia), ^VIX

Methodology:
  1. 22-day rolling realized vol for each country ETF
  2. Pairwise Granger causality (lags 1-5, p<0.01)
  3. Directed spillover graph: who exports / imports vol?
  4. Regime split: calm vs crisis causal structure
  5. Time-zone chain analysis (US→Asia→Europe→US)
  6. Crisis "Patient Zero" identification (GFC, COVID, 2022 rate hike)

[Proposed: User, Executed: Claude]
"""

import json
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
from itertools import combinations
from statsmodels.tsa.stattools import grangercausalitytests

warnings.filterwarnings("ignore")

# ── Configuration ──────────────────────────────────────────────────────
COUNTRY_ETFS = {
    "US": "SPY",
    "Japan": "EWJ",
    "Europe": "VGK",
    "EM": "EEM",
    "Brazil": "EWZ",
    "China": "FXI",
    "S.Korea": "EWY",
    "Taiwan": "EWT",
    "Australia": "EWA",
}

VOL_WINDOW = 22  # 1-month realized vol
GRANGER_MAX_LAG = 5
GRANGER_PVALUE = 0.01
START_DATE = "2007-01-01"  # FXI launched 2004, VGK 2005
END_DATE = "2026-03-20"

# Time zone groups for chain analysis
TZ_GROUPS = {
    "Asia": ["Japan", "China", "S.Korea", "Taiwan", "Australia"],
    "Europe": ["Europe"],
    "Americas": ["US", "Brazil", "EM"],
}

# Crisis periods
CRISIS_PERIODS = {
    "GFC": ("2008-09-01", "2009-03-31"),
    "Euro_Crisis": ("2011-07-01", "2012-01-31"),
    "COVID": ("2020-01-15", "2020-04-30"),
    "Rate_Hike_2022": ("2022-01-01", "2022-10-31"),
}

# Calm period for comparison
CALM_PERIOD = ("2013-01-01", "2017-12-31")


def download_data():
    """Download all country ETF data + VIX from yfinance."""
    print("=" * 80)
    print("K357: Global Volatility Spillover Network")
    print("=" * 80)
    print(f"\nDownloading data from {START_DATE} to {END_DATE}...")

    tickers = list(COUNTRY_ETFS.values()) + ["^VIX"]
    data = yf.download(tickers, start=START_DATE, end=END_DATE, auto_adjust=True)

    # Extract close prices
    if isinstance(data.columns, pd.MultiIndex):
        close = data["Close"]
    else:
        close = data

    # Rename columns to country names
    rename_map = {v: k for k, v in COUNTRY_ETFS.items()}
    rename_map["^VIX"] = "VIX"
    close = close.rename(columns=rename_map)

    print(f"\nData shape: {close.shape}")
    print(f"Date range: {close.index[0].strftime('%Y-%m-%d')} to {close.index[-1].strftime('%Y-%m-%d')}")
    print(f"\nSample counts per country:")
    for col in close.columns:
        print(f"  {col}: {close[col].dropna().shape[0]} trading days")

    return close


def compute_realized_vol(close_prices):
    """Compute 22-day rolling realized volatility (annualized) for each country."""
    log_returns = np.log(close_prices / close_prices.shift(1))
    realized_vol = log_returns.rolling(window=VOL_WINDOW).std() * np.sqrt(252) * 100
    return realized_vol.dropna(how="all")


def run_granger_test(data, cause_col, effect_col, max_lag=GRANGER_MAX_LAG):
    """
    Run Granger causality test: does `cause_col` Granger-cause `effect_col`?
    Returns (best_lag, min_p_value) across all tested lags.
    """
    df = data[[effect_col, cause_col]].dropna()
    if len(df) < max_lag * 3 + 10:
        return None, 1.0

    try:
        result = grangercausalitytests(df.values, maxlag=max_lag, verbose=False)
        # Find minimum p-value across all lags and all tests
        min_p = 1.0
        best_lag = 1
        for lag in range(1, max_lag + 1):
            # Use ssr_ftest p-value (most standard)
            p_val = result[lag][0]["ssr_ftest"][1]
            if p_val < min_p:
                min_p = p_val
                best_lag = lag
        return best_lag, min_p
    except Exception:
        return None, 1.0


def build_spillover_network(vol_data, countries, label="Full Sample"):
    """
    Build directed spillover network via pairwise Granger causality.
    Returns adjacency dict and summary stats.
    """
    print(f"\n{'─' * 60}")
    print(f"Granger Causality Network: {label}")
    print(f"{'─' * 60}")

    n = len(countries)
    adjacency = {}  # (cause, effect) -> (lag, p_value)
    outgoing = {c: 0 for c in countries}  # count of significant outgoing arrows
    incoming = {c: 0 for c in countries}  # count of significant incoming arrows
    out_strength = {c: 0.0 for c in countries}  # sum of -log(p) for outgoing
    in_strength = {c: 0.0 for c in countries}

    results_matrix = pd.DataFrame(
        np.ones((n, n)), index=countries, columns=countries
    )

    for cause in countries:
        for effect in countries:
            if cause == effect:
                results_matrix.loc[effect, cause] = np.nan
                continue

            lag, p = run_granger_test(vol_data, cause, effect)
            results_matrix.loc[effect, cause] = p

            if p < GRANGER_PVALUE:
                adjacency[(cause, effect)] = (lag, p)
                outgoing[cause] += 1
                incoming[effect] += 1
                out_strength[cause] += -np.log10(max(p, 1e-20))
                in_strength[effect] += -np.log10(max(p, 1e-20))

    # Print p-value matrix
    print(f"\nP-value matrix (rows=effect, cols=cause, p<{GRANGER_PVALUE} = significant):")
    print("(Read: column Granger-causes row)")
    pd.set_option("display.float_format", lambda x: f"{x:.4f}" if not np.isnan(x) else "---")
    print(results_matrix.to_string())

    # Print significant edges
    sig_edges = [(k, v) for k, v in adjacency.items()]
    sig_edges.sort(key=lambda x: x[1][1])  # sort by p-value

    print(f"\nSignificant edges (p < {GRANGER_PVALUE}): {len(sig_edges)}")
    for (cause, effect), (lag, p) in sig_edges:
        print(f"  {cause:>10} → {effect:<10}  lag={lag}, p={p:.6f}")

    # Export/Import ranking
    print(f"\n{'Vol Exporters (outgoing arrows)':>40}  |  {'Vol Importers (incoming arrows)'}")
    print(f"{'─' * 42}|{'─' * 42}")
    export_rank = sorted(outgoing.items(), key=lambda x: -x[1])
    import_rank = sorted(incoming.items(), key=lambda x: -x[1])
    for i in range(n):
        ex_name, ex_count = export_rank[i]
        im_name, im_count = import_rank[i]
        ex_str = f"  {ex_name:>10}: {ex_count} edges (strength={out_strength[ex_name]:.1f})"
        im_str = f"  {im_name:>10}: {im_count} edges (strength={in_strength[im_name]:.1f})"
        print(f"{ex_str:>42}|{im_str}")

    return {
        "adjacency": {f"{k[0]}->{k[1]}": {"lag": v[0], "p_value": v[1]} for k, v in adjacency.items()},
        "outgoing": outgoing,
        "incoming": incoming,
        "out_strength": {k: round(v, 2) for k, v in out_strength.items()},
        "in_strength": {k: round(v, 2) for k, v in in_strength.items()},
        "n_significant": len(sig_edges),
        "n_possible": n * (n - 1),
    }


def regime_analysis(vol_data, countries):
    """Compare spillover structure in calm vs crisis regimes."""
    print("\n" + "=" * 80)
    print("REGIME ANALYSIS: Calm vs Crisis Spillover Structure")
    print("=" * 80)

    results = {}

    # Calm period
    calm_vol = vol_data.loc[CALM_PERIOD[0]:CALM_PERIOD[1]]
    print(f"\nCalm period: {CALM_PERIOD[0]} to {CALM_PERIOD[1]} ({len(calm_vol)} obs)")
    results["calm"] = build_spillover_network(calm_vol, countries, "Calm (2013-2017)")

    # Crisis periods
    for crisis_name, (start, end) in CRISIS_PERIODS.items():
        crisis_vol = vol_data.loc[start:end]
        print(f"\n{crisis_name}: {start} to {end} ({len(crisis_vol)} obs)")
        if len(crisis_vol) > 50:
            results[crisis_name] = build_spillover_network(
                crisis_vol, countries, crisis_name
            )
        else:
            print(f"  Skipped: insufficient data ({len(crisis_vol)} < 50)")
            results[crisis_name] = {"skipped": True, "reason": f"insufficient data ({len(crisis_vol)})"}

    # Compare density
    print(f"\n{'─' * 60}")
    print("Network Density Comparison (significant edges / possible edges)")
    print(f"{'─' * 60}")
    for period, res in results.items():
        if "skipped" not in res:
            density = res["n_significant"] / res["n_possible"]
            print(f"  {period:>20}: {res['n_significant']}/{res['n_possible']} = {density:.2%}")

    return results


def timezone_chain_analysis(vol_data, countries):
    """
    Analyze volatility propagation along the time-zone chain:
    US closes (21:00 UTC) → Asia opens (00:00 UTC) → Europe opens (07:00 UTC) → US opens (14:30 UTC)
    """
    print("\n" + "=" * 80)
    print("TIME-ZONE CHAIN ANALYSIS")
    print("=" * 80)
    print("Does vol propagate along: US → Asia → Europe → US?")

    results = {}

    # Test each link in the chain
    chain_links = [
        ("US → Asia", ["US"], ["Japan", "China", "S.Korea", "Taiwan", "Australia"]),
        ("Asia → Europe", ["Japan", "China", "S.Korea", "Taiwan", "Australia"], ["Europe"]),
        ("Europe → US", ["Europe"], ["US"]),
        ("US → Europe (skip Asia)", ["US"], ["Europe"]),
        ("China → Asia (ex-China)", ["China"], ["Japan", "S.Korea", "Taiwan", "Australia"]),
    ]

    for link_name, causes, effects in chain_links:
        print(f"\n  {link_name}:")
        sig_count = 0
        total_count = 0
        for cause in causes:
            for effect in effects:
                if cause == effect:
                    continue
                if cause not in vol_data.columns or effect not in vol_data.columns:
                    continue
                lag, p = run_granger_test(vol_data, cause, effect)
                total_count += 1
                marker = "***" if p < 0.01 else "**" if p < 0.05 else "*" if p < 0.1 else ""
                if p < GRANGER_PVALUE:
                    sig_count += 1
                print(f"    {cause:>10} → {effect:<10}: lag={lag}, p={p:.6f} {marker}")

        pct = sig_count / total_count * 100 if total_count > 0 else 0
        print(f"    Significant: {sig_count}/{total_count} ({pct:.0f}%)")
        results[link_name] = {
            "significant": sig_count,
            "total": total_count,
            "pct": round(pct, 1),
        }

    return results


def crisis_patient_zero(vol_data, countries):
    """
    Identify which country's vol spiked FIRST in each crisis.
    Look at first big vol shock (>2 std dev above trailing mean).
    """
    print("\n" + "=" * 80)
    print("CRISIS 'PATIENT ZERO' ANALYSIS")
    print("=" * 80)
    print("Which country's vol spiked first in each crisis?")

    # Compute vol z-scores (relative to trailing 126-day mean/std)
    vol_zscore = pd.DataFrame(index=vol_data.index, columns=countries)
    for c in countries:
        if c not in vol_data.columns:
            continue
        rolling_mean = vol_data[c].rolling(126).mean()
        rolling_std = vol_data[c].rolling(126).std()
        vol_zscore[c] = (vol_data[c] - rolling_mean) / rolling_std

    vol_zscore = vol_zscore.astype(float)

    results = {}
    for crisis_name, (start, end) in CRISIS_PERIODS.items():
        # Look at the 60 days BEFORE crisis start to find early movers
        pre_start = pd.Timestamp(start) - pd.Timedelta(days=60)
        window = vol_zscore.loc[str(pre_start):end]

        if window.empty:
            continue

        print(f"\n  {crisis_name} ({start} to {end}):")
        print(f"  Looking for first vol spike (z > 2.0) from {pre_start.strftime('%Y-%m-%d')}:")

        first_spike = {}
        for c in countries:
            if c not in window.columns:
                continue
            spike = window[c] > 2.0
            if spike.any():
                first_date = spike.idxmax()
                first_spike[c] = first_date

        # Sort by first spike date
        sorted_spikes = sorted(first_spike.items(), key=lambda x: x[1])

        for i, (country, date) in enumerate(sorted_spikes):
            z_at_spike = vol_zscore.loc[date, country]
            label = " ← PATIENT ZERO" if i == 0 else ""
            print(f"    {i + 1}. {country:>10}: first spike {date.strftime('%Y-%m-%d')} (z={z_at_spike:.2f}){label}")

        if sorted_spikes:
            results[crisis_name] = {
                "patient_zero": sorted_spikes[0][0],
                "first_spike_date": sorted_spikes[0][1].strftime("%Y-%m-%d"),
                "propagation_order": [
                    {"country": c, "date": d.strftime("%Y-%m-%d")} for c, d in sorted_spikes
                ],
                "spread_days": (sorted_spikes[-1][1] - sorted_spikes[0][1]).days
                if len(sorted_spikes) > 1
                else 0,
            }

    return results


def vol_correlation_heatmap(vol_data, countries):
    """Compute pairwise vol correlation matrix."""
    print("\n" + "=" * 80)
    print("VOLATILITY CORRELATION MATRIX")
    print("=" * 80)

    vol_changes = vol_data[countries].diff().dropna()
    corr = vol_changes.corr()
    print("\nCorrelation of vol CHANGES (daily):")
    pd.set_option("display.float_format", lambda x: f"{x:.3f}")
    print(corr.to_string())

    # Average correlation by country
    print("\nAverage correlation with all others:")
    for c in countries:
        others = [x for x in countries if x != c]
        avg = corr.loc[c, others].mean()
        print(f"  {c:>10}: {avg:.3f}")

    return corr.to_dict()


def net_spillover_index(vol_data, countries):
    """
    Compute Diebold-Yilmaz style net spillover for each country.
    Positive = net exporter, Negative = net importer.
    Uses simple Granger strength as proxy.
    """
    print("\n" + "=" * 80)
    print("NET SPILLOVER INDEX (Granger-based proxy)")
    print("=" * 80)
    print("Positive = net vol exporter, Negative = net vol importer")

    net_scores = {}
    for c in countries:
        export_strength = 0.0
        import_strength = 0.0
        for other in countries:
            if c == other:
                continue
            # c causes other?
            _, p_out = run_granger_test(vol_data, c, other)
            if p_out < 0.05:
                export_strength += -np.log10(max(p_out, 1e-20))
            # other causes c?
            _, p_in = run_granger_test(vol_data, other, c)
            if p_in < 0.05:
                import_strength += -np.log10(max(p_in, 1e-20))
        net = export_strength - import_strength
        net_scores[c] = {
            "export": round(export_strength, 2),
            "import": round(import_strength, 2),
            "net": round(net, 2),
        }

    # Sort by net score
    sorted_net = sorted(net_scores.items(), key=lambda x: -x[1]["net"])
    print(f"\n{'Country':>10} | {'Export':>8} | {'Import':>8} | {'Net':>8} | Role")
    print(f"{'─' * 55}")
    for c, scores in sorted_net:
        role = "EXPORTER" if scores["net"] > 0 else "IMPORTER"
        print(
            f"  {c:>8} | {scores['export']:>8.2f} | {scores['import']:>8.2f} | {scores['net']:>+8.2f} | {role}"
        )

    return net_scores


def main():
    # ── Step 1: Download data ──
    close = download_data()
    countries = list(COUNTRY_ETFS.keys())

    # ── Step 2: Compute realized volatility ──
    print("\n" + "=" * 80)
    print("REALIZED VOLATILITY (22-day rolling, annualized %)")
    print("=" * 80)
    vol_data = compute_realized_vol(close)

    # Descriptive stats
    vol_stats = vol_data[countries].describe()
    print(vol_stats.to_string())

    # Include VIX for reference
    if "VIX" in close.columns:
        vix = close["VIX"].dropna()
        print(f"\nVIX reference: mean={vix.mean():.1f}, std={vix.std():.1f}, max={vix.max():.1f}")

    # ── Step 3: Full-sample spillover network ──
    full_network = build_spillover_network(vol_data, countries, "Full Sample (2007-2026)")

    # ── Step 4: Net spillover index ──
    net_spillover = net_spillover_index(vol_data, countries)

    # ── Step 5: Vol correlation ──
    vol_corr = vol_correlation_heatmap(vol_data, countries)

    # ── Step 6: Time-zone chain ──
    tz_results = timezone_chain_analysis(vol_data, countries)

    # ── Step 7: Regime analysis ──
    regime_results = regime_analysis(vol_data, countries)

    # ── Step 8: Patient Zero ──
    patient_zero = crisis_patient_zero(vol_data, countries)

    # ── Summary ──
    print("\n" + "=" * 80)
    print("K357 SUMMARY: Global Volatility Spillover Network")
    print("=" * 80)

    # Top exporters
    export_rank = sorted(full_network["outgoing"].items(), key=lambda x: -x[1])
    print("\nTop Vol Exporters (full sample):")
    for c, count in export_rank[:3]:
        print(f"  {c}: {count} outgoing Granger edges")

    # Top importers
    import_rank = sorted(full_network["incoming"].items(), key=lambda x: -x[1])
    print("\nTop Vol Importers (full sample):")
    for c, count in import_rank[:3]:
        print(f"  {c}: {count} incoming Granger edges")

    # Network density
    density = full_network["n_significant"] / full_network["n_possible"]
    print(f"\nNetwork density: {full_network['n_significant']}/{full_network['n_possible']} = {density:.2%}")

    # Patient Zero summary
    print("\nCrisis Patient Zero:")
    for crisis, info in patient_zero.items():
        print(
            f"  {crisis}: {info['patient_zero']} ({info['first_spike_date']}), "
            f"spread to all in {info['spread_days']} days"
        )

    # Net spillover
    sorted_net = sorted(net_spillover.items(), key=lambda x: -x[1]["net"])
    print("\nNet Spillover Ranking:")
    for c, s in sorted_net:
        role = "EXPORTER" if s["net"] > 0 else "IMPORTER"
        print(f"  {c}: {s['net']:+.2f} ({role})")

    # ── Save results ──
    all_results = {
        "experiment": "K357",
        "title": "Global Volatility Spillover Network",
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "data_source": "yfinance",
        "data_period": f"{START_DATE} to {END_DATE}",
        "methodology": {
            "vol_window": VOL_WINDOW,
            "granger_max_lag": GRANGER_MAX_LAG,
            "granger_pvalue_threshold": GRANGER_PVALUE,
            "countries": countries,
            "etfs": COUNTRY_ETFS,
        },
        "full_sample_network": full_network,
        "net_spillover": net_spillover,
        "timezone_chain": tz_results,
        "regime_analysis": {
            k: v for k, v in regime_results.items()
            if "skipped" not in v
        },
        "patient_zero": patient_zero,
        "key_findings": [],  # filled below
    }

    # Compile key findings
    findings = []
    top_exporter = export_rank[0][0]
    findings.append(f"Top vol exporter: {top_exporter} ({export_rank[0][1]} outgoing edges)")
    top_importer = import_rank[0][0]
    findings.append(f"Top vol importer: {top_importer} ({import_rank[0][1]} incoming edges)")
    findings.append(f"Network density: {density:.2%}")

    # China finding
    china_net = net_spillover.get("China", {}).get("net", 0)
    findings.append(f"China net spillover: {china_net:+.2f} ({'exporter' if china_net > 0 else 'importer'})")

    for crisis, info in patient_zero.items():
        findings.append(
            f"{crisis} patient zero: {info['patient_zero']} (spread in {info['spread_days']} days)"
        )

    all_results["key_findings"] = findings

    output_path = "experiments/k357_global_spillover_results.json"
    with open(output_path, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\nResults saved to {output_path}")


if __name__ == "__main__":
    main()
