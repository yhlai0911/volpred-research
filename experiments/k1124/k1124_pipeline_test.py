"""Quick pipeline test after Codex bug fixes."""
import sys
import pandas as pd
sys.path.insert(0, "/Users/yhlai0911/Desktop/volpred-research/.claude/worktrees/agent-k1124/experiments/k1124")
from k1124 import load_all_bars, make_model_data, fit_ols, predict_ols, qlike_loss, dm_hln
import numpy as np

start = pd.Timestamp("2020-04-01")
end = pd.Timestamp("2020-06-30")
bars = load_all_bars(start, end, cache=False)
print(f"Bars: {len(bars)}, days: {bars['date'].nunique()}")
print(f"bar range: min={bars['bar'].min()}, max={bars['bar'].max()}")
print(f"Active contracts: {bars['active_contract'].unique()}")

md = make_model_data(bars)
print(f"After features: {len(md)}")
print(md[["date", "bar_idx", "rv_next", "har_lag1", "abs_ofi", "abs_ofi_lag1", "ofi_signed_lag1"]].head(15))

# Check bar=60 no longer exists
print(f"\nAny bar>=60? {(bars['bar'] >= 60).any()}")
# Check bar_idx range
print(f"bar_idx max: {md['bar_idx'].max()}")
# Sanity: rv_next should be nan for last bar of each day
last_bars = bars.groupby('date').tail(1)
print(f"Last bars (should NOT appear in md): {len(last_bars)}")
last_bars_in_md = md.groupby('date').tail(1)
print(f"  max bar_idx of last kept rows per day: {last_bars_in_md['bar_idx'].max()}")

split = len(md) // 2
md_is = md.iloc[:split]
md_oos = md.iloc[split:]

# Run all 6 OFI-related models quickly
def test_model(feats):
    X_is = md_is[feats].values
    y_is = md_is["rv_next"].values
    X_oos = md_oos[feats].values
    y_oos = md_oos["rv_next"].values
    b = fit_ols(X_is, y_is)
    pred = np.clip(predict_ols(X_oos, b), 1e-12, None)
    q = qlike_loss(y_oos, pred)
    return q, b, q.mean()

har_feats = ["har_lag1", "har_lag6", "har_lag12"]
q_m2, b_m2, qm2 = test_model(har_feats)
print(f"\nM2 HAR OOS QLIKE: {qm2:.4f}")

for name, extra in [("M3 |OFI|", "abs_ofi"),
                     ("M4 OFI signed", "ofi_signed"),
                     ("M5 OFI_pers", "ofi_pers"),
                     ("M6 |OFI_lag1|", "abs_ofi_lag1"),
                     ("M7 OFI_signed_lag1", "ofi_signed_lag1")]:
    q_m, b_m, qm = test_model(har_feats + [extra])
    dm, p = dm_hln(q_m2, q_m)
    print(f"{name}: beta={b_m[-1]:+.2e}, OOS QLIKE={qm:.4f}, DM={dm:+.2f} (p={p:.3f})")
