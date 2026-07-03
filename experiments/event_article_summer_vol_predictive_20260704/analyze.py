"""
Summer-calm → Autumn-storm predictive test.

Reader-facing event article (July 4 2026 holiday-week hook).
Question: 描述性「7 月最平靜」已知；但『夏季低波動 → 是否預示秋季波動放大』有無預測力？

Data: ^VIX (implied vol) + ^GSPC (realized vol from daily log returns), 2005-2026.
Tests:
  1. Monthly mean VIX + realized vol (confirm July calm; descriptive baseline)
  2. Per-year summer (Jun-Jul) mean vol vs autumn (Sep-Oct) mean vol → correlation + OLS (predictive test)
  3. Timing distribution of each year's max VIX spike (is Aug-Oct over-represented?)
  4. 2024 Aug case study (carry unwind)

All seeds fixed where randomness used. Honest reporting of null.
"""
import numpy as np
import pandas as pd
import yfinance as yf
import json
from scipy import stats

SEED = 42
np.random.seed(SEED)

START = "2005-01-01"
END = "2026-07-04"


def _close(df):
    """Robustly extract Close as a 1-D Series from yfinance output (handles MultiIndex)."""
    c = df["Close"]
    if isinstance(c, pd.DataFrame):
        c = c.iloc[:, 0]
    return c.dropna()


print("downloading...")
vix = _close(yf.download("^VIX", start=START, end=END, progress=False, auto_adjust=False))
spx = _close(yf.download("^GSPC", start=START, end=END, progress=False, auto_adjust=False))

# realized vol: 21-day rolling annualized stdev of daily log returns (%)
ret = np.log(spx / spx.shift(1)).dropna()
rv21 = ret.rolling(21).std() * np.sqrt(252) * 100
rv21 = rv21.dropna()

vix.index = pd.to_datetime(vix.index)
rv21.index = pd.to_datetime(rv21.index)

results = {
    "meta": {
        "experiment_id": "event_article_summer_vol_predictive_20260704",
        "generated_at": pd.Timestamp.utcnow().isoformat(),
        "data_source": "yfinance ^VIX (implied) + ^GSPC (realized 21d annualized)",
        "sample_start": str(vix.index.min().date()),
        "sample_end": str(vix.index.max().date()),
        "vix_n": int(len(vix)),
        "rv_n": int(len(rv21)),
        "seed": SEED,
    }
}

# ---- 1. Monthly seasonality (descriptive baseline) ----
vix_month = vix.groupby(vix.index.month).mean()
rv_month = rv21.groupby(rv21.index.month).mean()
results["monthly_mean_vix"] = {int(m): round(float(v), 2) for m, v in vix_month.items()}
results["monthly_mean_rv"] = {int(m): round(float(v), 2) for m, v in rv_month.items()}
results["calmest_month_vix"] = int(vix_month.idxmin())
results["calmest_month_vix_value"] = round(float(vix_month.min()), 2)
results["stormiest_month_vix"] = int(vix_month.idxmax())
results["stormiest_month_vix_value"] = round(float(vix_month.max()), 2)

# ---- 2. Predictive test: summer (Jun-Jul) vol → autumn (Sep-Oct) vol ----
def season_mean(series, months):
    d = series[series.index.month.isin(months)]
    return d.groupby(d.index.year).mean()

summer_vix = season_mean(vix, [6, 7])
autumn_vix = season_mean(vix, [9, 10])
summer_rv = season_mean(rv21, [6, 7])
autumn_rv = season_mean(rv21, [9, 10])

# align on years where both exist (autumn of same year as summer)
def pred_test(summer, autumn, label):
    yrs = sorted(set(summer.index) & set(autumn.index))
    s = np.array([summer[y] for y in yrs])
    a = np.array([autumn[y] for y in yrs])
    r, p = stats.pearsonr(s, a)
    sr, sp = stats.spearmanr(s, a)
    slope, intercept, rr, pp, se = stats.linregress(s, a)
    # also: does a CALM summer (below-median) predict a bigger autumn jump?
    med = np.median(s)
    calm_years = a[s <= med]
    hot_years = a[s > med]
    return {
        "label": label,
        "n_years": len(yrs),
        "years": [int(y) for y in yrs],
        "pearson_r": round(float(r), 3),
        "pearson_p": round(float(p), 4),
        "spearman_r": round(float(sr), 3),
        "spearman_p": round(float(sp), 4),
        "ols_slope": round(float(slope), 3),
        "ols_r2": round(float(rr ** 2), 3),
        "autumn_after_calm_summer_mean": round(float(calm_years.mean()), 2),
        "autumn_after_hot_summer_mean": round(float(hot_years.mean()), 2),
    }

results["predictive_test_vix"] = pred_test(summer_vix, autumn_vix, "summer_vix -> autumn_vix")
results["predictive_test_rv"] = pred_test(summer_rv, autumn_rv, "summer_rv -> autumn_rv")

# ---- 2b. Genuinely-calm summers (VIX < 15): what autumns followed? ----
CALM_THRESH = 15.0
_yrs = sorted(set(summer_vix.index) & set(autumn_vix.index))
calm_rows = [
    {"year": int(y), "summer_vix": round(float(summer_vix[y]), 2), "autumn_vix": round(float(autumn_vix[y]), 2)}
    for y in _yrs if summer_vix[y] < CALM_THRESH
]
calm_rows_sorted = sorted(calm_rows, key=lambda r: r["summer_vix"])
_worst = max(calm_rows, key=lambda r: r["autumn_vix"])
results["calm_summer_below15"] = {
    "threshold": CALM_THRESH,
    "n_years": len(calm_rows),
    "rows": calm_rows_sorted,
    "worst_autumn_year": _worst["year"],
    "worst_autumn_vix": _worst["autumn_vix"],
    "all_autumns_below": round(max(r["autumn_vix"] for r in calm_rows), 2),
}

# ---- 3. Timing of each year's max VIX spike ----
vix_by_year = vix.groupby(vix.index.year)
spike_months = {}
for y, grp in vix_by_year:
    if len(grp) < 100:  # skip partial years
        continue
    peak_date = grp.idxmax()
    spike_months.setdefault(int(peak_date.month), 0)
    spike_months[int(peak_date.month)] += 1
results["annual_max_vix_spike_month_counts"] = dict(sorted(spike_months.items()))
total_full_years = sum(spike_months.values())
results["annual_max_vix_spike_total_years"] = total_full_years
autumn_spikes = sum(v for m, v in spike_months.items() if m in (8, 9, 10))
results["annual_max_vix_spike_aug_oct_share"] = round(autumn_spikes / total_full_years, 3)
# uniform-null expectation for Aug-Oct (3 of 12 months)
results["annual_max_vix_spike_uniform_null_share"] = round(3 / 12, 3)

# ---- 4. 2024 Aug case study ----
aug2024 = vix[(vix.index >= "2024-07-01") & (vix.index <= "2024-08-31")]
jul2024_mean = vix[(vix.index >= "2024-07-01") & (vix.index <= "2024-07-31")].mean()
results["case_2024"] = {
    "jul_2024_mean_vix": round(float(jul2024_mean), 2),
    "aug_2024_peak_vix": round(float(aug2024.max()), 2),
    "aug_2024_peak_date": str(aug2024.idxmax().date()),
}

# ---- 5. current state ----
results["current"] = {
    "latest_date": str(vix.index.max().date()),
    "latest_vix": round(float(vix.iloc[-1]), 2),
    "recent_20d_mean_vix": round(float(vix.iloc[-20:].mean()), 2),
}

with open("experiments/event_article_summer_vol_predictive_20260704/results.json", "w") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

# console summary
print("\n=== MONTHLY MEAN VIX ===")
for m in range(1, 13):
    print(f"  {m:2d}月: VIX {results['monthly_mean_vix'][m]:5.2f} | RV {results['monthly_mean_rv'][m]:5.2f}")
print(f"\ncalmest={results['calmest_month_vix']}月 ({results['calmest_month_vix_value']}), stormiest={results['stormiest_month_vix']}月 ({results['stormiest_month_vix_value']})")
print("\n=== PREDICTIVE TEST (summer Jun-Jul -> autumn Sep-Oct) ===")
pt = results["predictive_test_vix"]
print(f"  VIX: n={pt['n_years']}yr pearson r={pt['pearson_r']} (p={pt['pearson_p']}) OLS R2={pt['ols_r2']}")
print(f"       autumn after CALM summer={pt['autumn_after_calm_summer_mean']} vs after HOT summer={pt['autumn_after_hot_summer_mean']}")
pr = results["predictive_test_rv"]
print(f"  RV : n={pr['n_years']}yr pearson r={pr['pearson_r']} (p={pr['pearson_p']}) OLS R2={pr['ols_r2']}")
print(f"       autumn after CALM summer={pr['autumn_after_calm_summer_mean']} vs after HOT summer={pr['autumn_after_hot_summer_mean']}")
print("\n=== ANNUAL MAX VIX SPIKE MONTH ===")
print(f"  counts: {results['annual_max_vix_spike_month_counts']}")
print(f"  Aug-Oct share={results['annual_max_vix_spike_aug_oct_share']} vs uniform-null={results['annual_max_vix_spike_uniform_null_share']} (N={total_full_years}yr)")
print(f"\n2024 case: Jul mean {results['case_2024']['jul_2024_mean_vix']} -> Aug peak {results['case_2024']['aug_2024_peak_vix']} ({results['case_2024']['aug_2024_peak_date']})")
print(f"current VIX {results['current']['latest_vix']} (20d mean {results['current']['recent_20d_mean_vix']}) @ {results['current']['latest_date']}")
print("\nOK results.json written")
