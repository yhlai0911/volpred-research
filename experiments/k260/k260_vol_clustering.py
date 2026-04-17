"""
K260: Volatility Clustering Prediction — Can We Predict the LENGTH of Vol Clusters?

Background: GARCH predicts vol level, but not how long a vol cluster will last.
If we could predict cluster duration, we'd know when to re-enter after a vol spike.

Data: SPY, VIX daily from yfinance, 2005-2024.

Methodology:
1. Define vol clusters (|ret| > 2x rolling std triggers start, 5 consecutive calm days end)
2. Analyze cluster characteristics (duration distribution, VIX predictability)
3. Build predictive model for cluster duration (rolling OOS)
4. Strategy: short cluster → stay invested; long cluster → reduce position
5. Compare vs buy-and-hold and 50/50+VT baseline

[提出: User, 執行: Claude]
"""

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import accuracy_score, roc_auc_score, confusion_matrix
import json
import warnings
warnings.filterwarnings('ignore')

# ─── Data Download ────────────────────────────────────────────────────────────

print("=" * 80)
print("K260: Volatility Clustering Prediction")
print("Can We Predict the LENGTH of Vol Clusters?")
print("=" * 80)

print("\n[1] Downloading data from yfinance...")
spy = yf.download("SPY", start="2004-01-01", end="2025-01-01", progress=False)
vix = yf.download("^VIX", start="2004-01-01", end="2025-01-01", progress=False)

# Handle multi-level columns
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
if isinstance(vix.columns, pd.MultiIndex):
    vix.columns = vix.columns.get_level_values(0)

spy['Return'] = spy['Close'].pct_change()
spy['Abs_Return'] = spy['Return'].abs()

# Merge VIX
df = spy[['Close', 'Return', 'Abs_Return']].copy()
df.columns = ['SPY_Close', 'SPY_Return', 'SPY_Abs_Return']
df['VIX'] = vix['Close'].reindex(df.index)
df = df.dropna()

# Trim to 2005-2024
df = df.loc['2005-01-01':'2024-12-31']

print(f"  Data period: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")
print(f"  Total trading days: {len(df)}")

# ─── Cluster Identification ──────────────────────────────────────────────────

print("\n[2] Identifying volatility clusters...")

# Rolling 252-day standard deviation
df['Rolling_Std'] = df['SPY_Return'].rolling(252).std()
df = df.dropna(subset=['Rolling_Std'])

# Thresholds
df['High_Vol_Thresh'] = 2.0 * df['Rolling_Std']
df['Calm_Thresh'] = 1.0 * df['Rolling_Std']

# Identify high-vol days and calm days
df['Is_High_Vol'] = df['SPY_Abs_Return'] > df['High_Vol_Thresh']
df['Is_Calm'] = df['SPY_Abs_Return'] < df['Calm_Thresh']

# Build clusters using state machine
clusters = []
in_cluster = False
cluster_start_idx = None
cluster_start_date = None
calm_streak = 0

for i in range(len(df)):
    date = df.index[i]

    if not in_cluster:
        if df['Is_High_Vol'].iloc[i]:
            in_cluster = True
            cluster_start_idx = i
            cluster_start_date = date
            calm_streak = 0
    else:
        if df['Is_Calm'].iloc[i]:
            calm_streak += 1
        else:
            calm_streak = 0

        if calm_streak >= 5:
            # Cluster ended 5 days ago
            cluster_end_idx = i - 5
            cluster_end_date = df.index[cluster_end_idx]
            duration = cluster_end_idx - cluster_start_idx + 1

            # Cluster characteristics
            cluster_slice = df.iloc[cluster_start_idx:cluster_end_idx + 1]

            vix_at_start = df['VIX'].iloc[cluster_start_idx]
            vix_peak = cluster_slice['VIX'].max()

            # VIX speed: how fast VIX rose in the 5 days before/at cluster start
            lookback_start = max(0, cluster_start_idx - 5)
            vix_5d_before = df['VIX'].iloc[lookback_start]
            vix_speed = (vix_at_start - vix_5d_before) / vix_5d_before * 100 if vix_5d_before > 0 else 0

            # SPY drawdown at cluster start (from 20d high)
            lookback_20d = max(0, cluster_start_idx - 20)
            spy_20d_high = df['SPY_Close'].iloc[lookback_20d:cluster_start_idx + 1].max()
            spy_at_start = df['SPY_Close'].iloc[cluster_start_idx]
            drawdown_at_start = (spy_at_start - spy_20d_high) / spy_20d_high * 100

            # Realized vol during cluster
            cluster_vol = cluster_slice['SPY_Return'].std() * np.sqrt(252) if len(cluster_slice) > 1 else np.nan

            # Max drawdown during cluster
            cum_ret = (1 + cluster_slice['SPY_Return']).cumprod()
            running_max = cum_ret.cummax()
            cluster_mdd = ((cum_ret - running_max) / running_max).min() * 100

            # VIX term structure slope proxy: VIX level relative to 20d MA
            vix_20d_ma = df['VIX'].iloc[max(0, cluster_start_idx - 20):cluster_start_idx + 1].mean()
            vix_vs_ma = (vix_at_start - vix_20d_ma) / vix_20d_ma * 100 if vix_20d_ma > 0 else 0

            # Previous cluster memory: days since last cluster ended
            if len(clusters) > 0:
                prev_end_date = clusters[-1]['end_date']
                days_since_last = (cluster_start_date - prev_end_date).days
            else:
                days_since_last = 999

            clusters.append({
                'start_date': cluster_start_date,
                'end_date': cluster_end_date,
                'duration': duration,
                'vix_at_start': vix_at_start,
                'vix_peak': vix_peak,
                'vix_speed_5d': vix_speed,
                'drawdown_at_start': drawdown_at_start,
                'cluster_vol': cluster_vol,
                'cluster_mdd': cluster_mdd,
                'vix_vs_20d_ma': vix_vs_ma,
                'days_since_last_cluster': days_since_last,
                'start_idx': cluster_start_idx,
                'end_idx': cluster_end_idx,
            })

            in_cluster = False
            calm_streak = 0

# Handle cluster still ongoing at end
if in_cluster:
    cluster_end_idx = len(df) - 1
    cluster_end_date = df.index[cluster_end_idx]
    duration = cluster_end_idx - cluster_start_idx + 1
    cluster_slice = df.iloc[cluster_start_idx:cluster_end_idx + 1]
    vix_at_start = df['VIX'].iloc[cluster_start_idx]
    vix_peak = cluster_slice['VIX'].max()
    lookback_start = max(0, cluster_start_idx - 5)
    vix_5d_before = df['VIX'].iloc[lookback_start]
    vix_speed = (vix_at_start - vix_5d_before) / vix_5d_before * 100 if vix_5d_before > 0 else 0
    lookback_20d = max(0, cluster_start_idx - 20)
    spy_20d_high = df['SPY_Close'].iloc[lookback_20d:cluster_start_idx + 1].max()
    spy_at_start = df['SPY_Close'].iloc[cluster_start_idx]
    drawdown_at_start = (spy_at_start - spy_20d_high) / spy_20d_high * 100
    cluster_vol = cluster_slice['SPY_Return'].std() * np.sqrt(252) if len(cluster_slice) > 1 else np.nan
    cum_ret = (1 + cluster_slice['SPY_Return']).cumprod()
    running_max = cum_ret.cummax()
    cluster_mdd = ((cum_ret - running_max) / running_max).min() * 100
    vix_20d_ma = df['VIX'].iloc[max(0, cluster_start_idx - 20):cluster_start_idx + 1].mean()
    vix_vs_ma = (vix_at_start - vix_20d_ma) / vix_20d_ma * 100 if vix_20d_ma > 0 else 0
    if len(clusters) > 0:
        days_since_last = (cluster_start_date - clusters[-1]['end_date']).days
    else:
        days_since_last = 999
    clusters.append({
        'start_date': cluster_start_date,
        'end_date': cluster_end_date,
        'duration': duration,
        'vix_at_start': vix_at_start,
        'vix_peak': vix_peak,
        'vix_speed_5d': vix_speed,
        'drawdown_at_start': drawdown_at_start,
        'cluster_vol': cluster_vol,
        'cluster_mdd': cluster_mdd,
        'vix_vs_20d_ma': vix_vs_ma,
        'days_since_last_cluster': days_since_last,
        'start_idx': cluster_start_idx,
        'end_idx': cluster_end_idx,
    })

clusters_df = pd.DataFrame(clusters)
print(f"  Total vol clusters identified: {len(clusters_df)}")
print(f"  Period: {clusters_df['start_date'].iloc[0].strftime('%Y-%m-%d')} to {clusters_df['end_date'].iloc[-1].strftime('%Y-%m-%d')}")

# ─── Cluster Characteristics Analysis ────────────────────────────────────────

print("\n[3] Cluster Characteristics Analysis")
print("-" * 60)

durations = clusters_df['duration'].values

print(f"\n  Duration Statistics:")
print(f"    Count:    {len(durations)}")
print(f"    Mean:     {np.mean(durations):.1f} days")
print(f"    Median:   {np.median(durations):.1f} days")
print(f"    Std:      {np.std(durations):.1f} days")
print(f"    Min:      {np.min(durations)} days")
print(f"    Max:      {np.max(durations)} days")
print(f"    Skewness: {stats.skew(durations):.2f}")
print(f"    Kurtosis: {stats.kurtosis(durations):.2f}")

# Distribution percentiles
print(f"\n  Duration Percentiles:")
for p in [10, 25, 50, 75, 90, 95]:
    print(f"    P{p}: {np.percentile(durations, p):.0f} days")

# Classify clusters
short_threshold = 10  # days
clusters_df['Is_Long'] = (clusters_df['duration'] > short_threshold).astype(int)
n_short = (clusters_df['Is_Long'] == 0).sum()
n_long = (clusters_df['Is_Long'] == 1).sum()
print(f"\n  Short clusters (≤{short_threshold} days): {n_short} ({n_short/len(clusters_df)*100:.1f}%)")
print(f"  Long clusters (>{short_threshold} days):  {n_long} ({n_long/len(clusters_df)*100:.1f}%)")

# Heavy-tail test
print(f"\n  Heavy-tail Analysis:")
# Test if duration follows exponential (light tail) vs power law (heavy tail)
# Shapiro-Wilk test on log(duration)
if len(durations) >= 8:
    stat_sw, p_sw = stats.shapiro(np.log(durations + 1))
    print(f"    Shapiro-Wilk on log(duration): stat={stat_sw:.4f}, p={p_sw:.4f}")
    if p_sw < 0.05:
        print(f"    → Log-normal rejected → likely heavy-tailed")
    else:
        print(f"    → Consistent with log-normal")

# ─── Predictive Features at Cluster Start ─────────────────────────────────

print("\n[4] Feature Correlations with Duration")
print("-" * 60)

features = ['vix_at_start', 'vix_speed_5d', 'drawdown_at_start',
            'vix_vs_20d_ma', 'days_since_last_cluster']

print(f"\n  Correlation with Duration:")
for feat in features:
    valid = clusters_df[[feat, 'duration']].dropna()
    if len(valid) >= 5:
        r, p = stats.spearmanr(valid[feat], valid['duration'])
        sig = "***" if p < 0.01 else ("**" if p < 0.05 else ("*" if p < 0.10 else ""))
        print(f"    {feat:30s}: rho={r:+.3f}, p={p:.4f} {sig}")

# Correlation with Is_Long (binary)
print(f"\n  Point-Biserial Correlation with Is_Long (>{short_threshold}d):")
for feat in features:
    valid = clusters_df[[feat, 'Is_Long']].dropna()
    if len(valid) >= 5:
        r, p = stats.pointbiserialr(valid['Is_Long'], valid[feat])
        sig = "***" if p < 0.01 else ("**" if p < 0.05 else ("*" if p < 0.10 else ""))
        print(f"    {feat:30s}: r_pb={r:+.3f}, p={p:.4f} {sig}")

# ─── VIX Level vs Duration Binned Analysis ───────────────────────────────

print("\n[5] VIX Level at Start → Duration Relationship")
print("-" * 60)

# Bin VIX into quartiles
if len(clusters_df) >= 8:
    clusters_df['VIX_Quartile'] = pd.qcut(clusters_df['vix_at_start'], q=4, labels=['Q1(Low)', 'Q2', 'Q3', 'Q4(High)'])

    print(f"\n  Duration by VIX Quartile at Cluster Start:")
    for q in ['Q1(Low)', 'Q2', 'Q3', 'Q4(High)']:
        subset = clusters_df[clusters_df['VIX_Quartile'] == q]['duration']
        if len(subset) > 0:
            print(f"    {q}: mean={subset.mean():.1f}d, median={subset.median():.1f}d, n={len(subset)}")

# ─── VIX Speed Analysis ──────────────────────────────────────────────────

print("\n[6] VIX Speed (5d rise) → Duration Relationship")
print("-" * 60)

if len(clusters_df) >= 8:
    clusters_df['Speed_Group'] = pd.qcut(clusters_df['vix_speed_5d'], q=3, labels=['Slow', 'Medium', 'Fast'], duplicates='drop')

    print(f"\n  Duration by VIX Speed Group:")
    for g in ['Slow', 'Medium', 'Fast']:
        subset = clusters_df[clusters_df['Speed_Group'] == g]['duration']
        if len(subset) > 0:
            pct_long = (subset > short_threshold).mean() * 100
            print(f"    {g:8s}: mean={subset.mean():.1f}d, median={subset.median():.1f}d, %long={pct_long:.0f}%, n={len(subset)}")

# ─── Notable Clusters ────────────────────────────────────────────────────

print("\n[7] Notable Clusters (Top 10 by Duration)")
print("-" * 60)

top10 = clusters_df.nlargest(10, 'duration')
for _, row in top10.iterrows():
    print(f"    {row['start_date'].strftime('%Y-%m-%d')} → {row['end_date'].strftime('%Y-%m-%d')}: "
          f"{row['duration']:3d}d, VIX={row['vix_at_start']:.1f}→{row['vix_peak']:.1f}, "
          f"MDD={row['cluster_mdd']:.1f}%")

# ─── Predictive Model: Rolling OOS ───────────────────────────────────────

print("\n[8] Predictive Model: Rolling OOS Classification")
print("    Target: Will cluster last > 10 days?")
print("-" * 60)

# Prepare features
feature_cols = ['vix_at_start', 'vix_speed_5d', 'drawdown_at_start',
                'vix_vs_20d_ma', 'days_since_last_cluster']
X = clusters_df[feature_cols].copy()
y = clusters_df['Is_Long'].copy()

# Handle missing/inf values
X = X.replace([np.inf, -np.inf], np.nan)
for col in X.columns:
    X[col] = X[col].fillna(X[col].median())

# Rolling OOS: train on first N clusters, predict N+1
min_train = 15  # Need minimum training samples

if len(clusters_df) < min_train + 5:
    print(f"  WARNING: Only {len(clusters_df)} clusters, need at least {min_train + 5} for rolling OOS")
    print(f"  Falling back to leave-one-out cross-validation")

    # LOO-CV
    from sklearn.model_selection import LeaveOneOut
    loo = LeaveOneOut()
    predictions_lr = np.zeros(len(y))
    probas_lr = np.zeros(len(y))
    predictions_gb = np.zeros(len(y))
    probas_gb = np.zeros(len(y))

    for train_idx, test_idx in loo.split(X):
        X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
        y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]

        # Logistic Regression
        lr = LogisticRegression(random_state=42, max_iter=1000)
        lr.fit(X_train, y_train)
        predictions_lr[test_idx] = lr.predict(X_test)
        probas_lr[test_idx] = lr.predict_proba(X_test)[:, 1]

        # Gradient Boosting
        gb = GradientBoostingClassifier(n_estimators=50, max_depth=2, random_state=42)
        gb.fit(X_train, y_train)
        predictions_gb[test_idx] = gb.predict(X_test)
        probas_gb[test_idx] = gb.predict_proba(X_test)[:, 1]

    oos_method = "LOO-CV"
else:
    # Expanding window OOS
    predictions_lr = np.full(len(y), np.nan)
    probas_lr = np.full(len(y), np.nan)
    predictions_gb = np.full(len(y), np.nan)
    probas_gb = np.full(len(y), np.nan)

    for i in range(min_train, len(y)):
        X_train = X.iloc[:i]
        y_train = y.iloc[:i]
        X_test = X.iloc[i:i+1]

        # Logistic Regression
        lr = LogisticRegression(random_state=42, max_iter=1000)
        lr.fit(X_train, y_train)
        predictions_lr[i] = lr.predict(X_test)[0]
        probas_lr[i] = lr.predict_proba(X_test)[0, 1]

        # Gradient Boosting
        gb = GradientBoostingClassifier(n_estimators=50, max_depth=2, random_state=42)
        gb.fit(X_train, y_train)
        predictions_gb[i] = gb.predict(X_test)[0]
        probas_gb[i] = gb.predict_proba(X_test)[0, 1]

    # Only evaluate on OOS period
    oos_mask = ~np.isnan(predictions_lr)
    predictions_lr = predictions_lr[oos_mask]
    probas_lr = probas_lr[oos_mask]
    predictions_gb = predictions_gb[oos_mask]
    probas_gb = probas_gb[oos_mask]
    y_oos = y.iloc[min_train:].values
    y = pd.Series(y_oos)  # reassign for downstream

    oos_method = f"Expanding Window (train≥{min_train})"

print(f"\n  OOS Method: {oos_method}")
print(f"  OOS sample size: {len(y)}")
print(f"  Base rate (long clusters): {y.mean()*100:.1f}%")

# Evaluate models
for name, preds, probs in [("Logistic Regression", predictions_lr, probas_lr),
                             ("Gradient Boosting", predictions_gb, probas_gb)]:
    acc = accuracy_score(y, preds)

    # AUC only if both classes present
    if len(np.unique(y)) > 1 and len(np.unique(probs)) > 1:
        try:
            auc = roc_auc_score(y, probs)
        except:
            auc = np.nan
    else:
        auc = np.nan

    cm = confusion_matrix(y, preds)

    print(f"\n  {name}:")
    print(f"    Accuracy: {acc:.3f}")
    if not np.isnan(auc):
        print(f"    AUC-ROC:  {auc:.3f}")
    print(f"    Confusion Matrix:")
    if cm.shape == (2, 2):
        print(f"      Predicted:  Short  Long")
        print(f"      Short:      {cm[0,0]:4d}  {cm[0,1]:4d}")
        print(f"      Long:       {cm[1,0]:4d}  {cm[1,1]:4d}")
    else:
        print(f"      {cm}")

# Feature importance (train on all data for interpretation)
print(f"\n  Feature Importance (Logistic Regression coefficients, full sample):")
lr_full = LogisticRegression(random_state=42, max_iter=1000)
X_full = clusters_df[feature_cols].copy().replace([np.inf, -np.inf], np.nan)
for col in X_full.columns:
    X_full[col] = X_full[col].fillna(X_full[col].median())
y_full = clusters_df['Is_Long']
lr_full.fit(X_full, y_full)
for feat, coef in sorted(zip(feature_cols, lr_full.coef_[0]), key=lambda x: abs(x[1]), reverse=True):
    print(f"    {feat:30s}: {coef:+.4f}")

gb_full = GradientBoostingClassifier(n_estimators=50, max_depth=2, random_state=42)
gb_full.fit(X_full, y_full)
print(f"\n  Feature Importance (Gradient Boosting, full sample):")
for feat, imp in sorted(zip(feature_cols, gb_full.feature_importances_), key=lambda x: x[1], reverse=True):
    print(f"    {feat:30s}: {imp:.4f}")

# ─── Naive Baseline: Always Predict Majority Class ───────────────────────

print(f"\n  Naive Baseline (always predict majority class):")
majority_class = 0 if y_full.mean() < 0.5 else 1
naive_acc = max(y_full.mean(), 1 - y_full.mean())
print(f"    Accuracy: {naive_acc:.3f}")

# ─── Strategy Backtest ────────────────────────────────────────────────────

print("\n[9] Strategy Backtest")
print("    Short cluster → stay 100% invested")
print("    Long cluster → reduce to 50% at cluster start")
print("-" * 60)

# Re-train model on rolling basis for strategy
# We use the full df for returns
daily_returns = df['SPY_Return'].copy()

# Strategy returns
strat_returns = daily_returns.copy()  # Start fully invested
strat_returns_naive = daily_returns.copy()  # Naive: always reduce during clusters

# Mark cluster days with prediction
# For each cluster, at start predict duration, adjust position
cluster_positions = pd.Series(1.0, index=df.index)  # 1.0 = fully invested
cluster_positions_naive = pd.Series(1.0, index=df.index)  # naive: always reduce
cluster_positions_oracle = pd.Series(1.0, index=df.index)  # oracle: knows actual duration

for i, row in clusters_df.iterrows():
    start_idx = row['start_idx']
    end_idx = row['end_idx']
    duration = row['duration']

    cluster_days = df.index[start_idx:end_idx + 1]

    # Naive strategy: always reduce during clusters
    cluster_positions_naive.loc[cluster_days] = 0.5

    # Oracle strategy: only reduce for truly long clusters
    if duration > short_threshold:
        cluster_positions_oracle.loc[cluster_days] = 0.5

# Predictive strategy: use expanding window model prediction
cluster_positions_pred = pd.Series(1.0, index=df.index)

# We need enough clusters to train on
trained_clusters = 0
for i, row in clusters_df.iterrows():
    trained_clusters += 1
    if trained_clusters <= min_train:
        # Not enough training data yet, use naive (reduce)
        start_idx = row['start_idx']
        end_idx = row['end_idx']
        cluster_days = df.index[start_idx:end_idx + 1]
        cluster_positions_pred.loc[cluster_days] = 0.5
        continue

    # Train on previous clusters
    X_train = X_full.iloc[:i]
    y_train = y_full.iloc[:i]

    lr_strat = LogisticRegression(random_state=42, max_iter=1000)
    lr_strat.fit(X_train, y_train)

    X_test = X_full.iloc[i:i+1]
    pred_long = lr_strat.predict(X_test)[0]

    start_idx = row['start_idx']
    end_idx = row['end_idx']
    cluster_days = df.index[start_idx:end_idx + 1]

    if pred_long == 1:
        cluster_positions_pred.loc[cluster_days] = 0.5
    # else: stay fully invested (predicted short cluster)

# Compute strategy returns
ret_buyhold = daily_returns
ret_naive = daily_returns * cluster_positions_naive
ret_oracle = daily_returns * cluster_positions_oracle
ret_pred = daily_returns * cluster_positions_pred

# Performance metrics
def compute_metrics(returns, name):
    """Compute annualized performance metrics."""
    ann_ret = returns.mean() * 252
    ann_vol = returns.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    cum_ret = (1 + returns).cumprod()
    running_max = cum_ret.cummax()
    drawdown = (cum_ret - running_max) / running_max
    mdd = drawdown.min()

    # Calmar ratio
    calmar = ann_ret / abs(mdd) if mdd != 0 else 0

    # Sortino ratio
    downside_ret = returns[returns < 0]
    downside_vol = downside_ret.std() * np.sqrt(252) if len(downside_ret) > 0 else ann_vol
    sortino = ann_ret / downside_vol if downside_vol > 0 else 0

    total_ret = cum_ret.iloc[-1] - 1

    return {
        'name': name,
        'ann_return': ann_ret,
        'ann_vol': ann_vol,
        'sharpe': sharpe,
        'sortino': sortino,
        'mdd': mdd,
        'calmar': calmar,
        'total_return': total_ret,
    }

metrics = []
for ret, name in [(ret_buyhold, "Buy & Hold SPY"),
                   (ret_naive, "Naive: Always Reduce"),
                   (ret_oracle, "Oracle: Perfect Info"),
                   (ret_pred, "Predictive Model")]:
    m = compute_metrics(ret, name)
    metrics.append(m)

print(f"\n  Strategy Comparison (2005-2024):")
print(f"  {'Strategy':<25s} {'AnnRet':>8s} {'AnnVol':>8s} {'Sharpe':>8s} {'Sortino':>8s} {'MDD':>8s} {'Calmar':>8s} {'TotRet':>8s}")
print(f"  {'-'*25} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8}")
for m in metrics:
    print(f"  {m['name']:<25s} {m['ann_return']*100:>7.2f}% {m['ann_vol']*100:>7.2f}% "
          f"{m['sharpe']:>8.3f} {m['sortino']:>8.3f} {m['mdd']*100:>7.1f}% "
          f"{m['calmar']:>8.3f} {m['total_return']*100:>7.1f}%")

# ─── Statistical Significance Tests ──────────────────────────────────────

print("\n[10] Statistical Significance Tests")
print("-" * 60)

# Paired t-test on daily returns: Predictive vs Buy-and-Hold
diff = ret_pred - ret_buyhold
t_stat, p_val = stats.ttest_1samp(diff, 0)
print(f"\n  Predictive vs Buy&Hold (paired t-test):")
print(f"    Mean daily return diff: {diff.mean()*10000:.4f} bps")
print(f"    t-stat: {t_stat:.4f}, p-value: {p_val:.4f}")
print(f"    Harvey (2016) threshold t>3.0: {'PASS' if abs(t_stat) > 3.0 else 'FAIL'}")

diff2 = ret_pred - ret_naive
t_stat2, p_val2 = stats.ttest_1samp(diff2, 0)
print(f"\n  Predictive vs Naive Always-Reduce (paired t-test):")
print(f"    Mean daily return diff: {diff2.mean()*10000:.4f} bps")
print(f"    t-stat: {t_stat2:.4f}, p-value: {p_val2:.4f}")

# Value added: How many clusters did the model correctly STAY invested?
print(f"\n[11] Cluster-Level Decision Analysis")
print("-" * 60)

correct_stay = 0  # predicted short, was actually short → stayed invested, avoided missing rally
correct_reduce = 0  # predicted long, was actually long → reduced, avoided losses
wrong_stay = 0  # predicted short, was actually long → stayed invested during long cluster
wrong_reduce = 0  # predicted long, was actually short → reduced unnecessarily

for i, row in clusters_df.iterrows():
    if i < min_train:
        continue

    actual_long = row['Is_Long']

    # Get prediction
    X_test_row = X_full.iloc[i:i+1]
    X_train_row = X_full.iloc[:i]
    y_train_row = y_full.iloc[:i]

    if len(X_train_row) < 2:
        continue

    lr_check = LogisticRegression(random_state=42, max_iter=1000)
    lr_check.fit(X_train_row, y_train_row)
    pred = lr_check.predict(X_test_row)[0]

    if pred == 0 and actual_long == 0:
        correct_stay += 1
    elif pred == 1 and actual_long == 1:
        correct_reduce += 1
    elif pred == 0 and actual_long == 1:
        wrong_stay += 1
    elif pred == 1 and actual_long == 0:
        wrong_reduce += 1

total_decisions = correct_stay + correct_reduce + wrong_stay + wrong_reduce
if total_decisions > 0:
    print(f"  Correct STAY (short cluster, stayed invested):     {correct_stay}")
    print(f"  Correct REDUCE (long cluster, reduced position):   {correct_reduce}")
    print(f"  Wrong STAY (long cluster, but stayed invested):    {wrong_stay}")
    print(f"  Wrong REDUCE (short cluster, but reduced):         {wrong_reduce}")
    print(f"  Overall accuracy: {(correct_stay + correct_reduce) / total_decisions * 100:.1f}%")

    # Impact analysis
    print(f"\n  Impact Analysis:")
    print(f"    Correct stays → captured rally returns during short vol spikes")
    print(f"    Correct reduces → avoided losses during extended turbulence")
    print(f"    Wrong stays → exposed to extended drawdowns")
    print(f"    Wrong reduces → missed recovery after brief spikes")

# ─── Subperiod Analysis ──────────────────────────────────────────────────

print("\n[12] Subperiod Analysis")
print("-" * 60)

subperiods = [
    ("Pre-GFC", "2005-01-01", "2007-06-30"),
    ("GFC", "2007-07-01", "2009-06-30"),
    ("Post-GFC Recovery", "2009-07-01", "2012-12-31"),
    ("Low Vol Bull", "2013-01-01", "2017-12-31"),
    ("Vol Return 2018", "2018-01-01", "2019-12-31"),
    ("COVID Era", "2020-01-01", "2021-12-31"),
    ("Post-COVID", "2022-01-01", "2024-12-31"),
]

for name, start, end in subperiods:
    mask = (clusters_df['start_date'] >= start) & (clusters_df['start_date'] <= end)
    subset = clusters_df[mask]
    if len(subset) > 0:
        print(f"\n  {name} ({start[:4]}-{end[:4]}):")
        print(f"    Clusters: {len(subset)}, Mean dur: {subset['duration'].mean():.1f}d, "
              f"Median: {subset['duration'].median():.1f}d, %Long: {subset['Is_Long'].mean()*100:.0f}%")

# ─── Summary Statistics for Results JSON ──────────────────────────────────

print("\n" + "=" * 80)
print("SUMMARY")
print("=" * 80)

# Compute additional summary stats
summary = {
    "experiment": "K260",
    "title": "Volatility Clustering Prediction",
    "data_source": "yfinance (SPY, ^VIX)",
    "period": f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
    "total_trading_days": int(len(df)),
    "cluster_definition": {
        "start_trigger": "|return| > 2x rolling 252d std",
        "end_trigger": "5 consecutive days with |return| < 1x std",
    },
    "cluster_statistics": {
        "total_clusters": int(len(clusters_df)),
        "mean_duration": float(np.mean(durations)),
        "median_duration": float(np.median(durations)),
        "std_duration": float(np.std(durations)),
        "max_duration": int(np.max(durations)),
        "min_duration": int(np.min(durations)),
        "skewness": float(stats.skew(durations)),
        "kurtosis": float(stats.kurtosis(durations)),
        "pct_long_clusters": float(clusters_df['Is_Long'].mean() * 100),
    },
    "feature_correlations_with_duration": {},
    "model_oos_performance": {
        "method": oos_method,
    },
    "strategy_backtest": {m['name']: {
        'ann_return': round(m['ann_return'] * 100, 2),
        'sharpe': round(m['sharpe'], 3),
        'sortino': round(m['sortino'], 3),
        'mdd': round(m['mdd'] * 100, 1),
    } for m in metrics},
    "statistical_tests": {
        "pred_vs_buyhold_t": round(float(t_stat), 4),
        "pred_vs_buyhold_p": round(float(p_val), 4),
        "harvey_threshold_met": bool(abs(t_stat) > 3.0),
    },
    "cluster_decision_analysis": {
        "correct_stay": int(correct_stay),
        "correct_reduce": int(correct_reduce),
        "wrong_stay": int(wrong_stay),
        "wrong_reduce": int(wrong_reduce),
        "accuracy": round((correct_stay + correct_reduce) / max(total_decisions, 1) * 100, 1),
    },
}

# Add feature correlations
for feat in features:
    valid = clusters_df[[feat, 'duration']].dropna()
    if len(valid) >= 5:
        r, p = stats.spearmanr(valid[feat], valid['duration'])
        summary["feature_correlations_with_duration"][feat] = {
            "spearman_rho": round(float(r), 4),
            "p_value": round(float(p), 4),
        }

# Print key findings
print(f"""
KEY FINDINGS:
1. Identified {len(clusters_df)} volatility clusters over 2005-2024
2. Duration: mean={np.mean(durations):.1f}d, median={np.median(durations):.1f}d (right-skewed, skew={stats.skew(durations):.2f})
3. {clusters_df['Is_Long'].mean()*100:.0f}% of clusters lasted >10 days

FEATURE PREDICTIVENESS:""")

for feat in features:
    valid = clusters_df[[feat, 'duration']].dropna()
    if len(valid) >= 5:
        r, p = stats.spearmanr(valid[feat], valid['duration'])
        sig = "***" if p < 0.01 else ("**" if p < 0.05 else ("*" if p < 0.10 else "n.s."))
        print(f"  {feat}: rho={r:+.3f} ({sig})")

print(f"""
STRATEGY RESULTS:""")
for m in metrics:
    print(f"  {m['name']}: Sharpe={m['sharpe']:.3f}, MDD={m['mdd']*100:.1f}%")

print(f"""
STATISTICAL SIGNIFICANCE:
  Predictive vs B&H: t={t_stat:.4f}, p={p_val:.4f} → Harvey t>3: {'PASS' if abs(t_stat) > 3.0 else 'FAIL'}

LIMITATIONS:
  - Small sample ({len(clusters_df)} clusters) limits model training and statistical power
  - Cluster definition is parameterized (2x std trigger, 5-day calm exit) — results sensitive to thresholds
  - No transaction costs in strategy backtest
  - VIX speed proxy is simple (5d % change), could use more sophisticated measures
  - Out-of-sample period depends on minimum training window
  - Strategy assumes position change at cluster start (next-day execution in reality)
""")

# Save results
results_path = "experiments/k260_vol_clustering_results.json"
# Convert non-serializable types
for key in summary:
    if isinstance(summary[key], dict):
        for k2, v2 in summary[key].items():
            if isinstance(v2, (np.integer, np.int64)):
                summary[key][k2] = int(v2)
            elif isinstance(v2, (np.floating, np.float64)):
                summary[key][k2] = float(v2)

with open(results_path, 'w') as f:
    json.dump(summary, f, indent=2, default=str)

print(f"\nResults saved to {results_path}")
print("K260 complete.")
