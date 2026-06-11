"""K1471 detector unit sanity (synthetic data; fixed seeds)."""
import importlib.util
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    'k1471', os.path.join(HERE, 'k1471_vt_crowding_redesign.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

rng = np.random.RandomState(0)
labels = ['10%', '30%', '40%', '50%', '60%', '70%', '100%']

# 1. clear break: levels 10-50% healthy (mean 1.0), 60%+ degraded (0.1)
#    → expect threshold='60%' (first level of post-break regime)
sh = {l: list(rng.normal(1.0 if i < 4 else 0.1, 0.3, 200))
      for i, l in enumerate(labels)}
d = m.detect_threshold_exogenous(sh, labels, perm_seed=1, boot_seed=2)
print('break case:', d['status'], d['threshold'], 'p=', d['p_value'],
      d['threshold_bootstrap_80pct_interval'])
assert d['threshold'] == '60%', d
assert d['p_value'] < 0.05

# 2. flat curve → expect no threshold (p large)
sh2 = {l: list(rng.normal(0.8, 0.3, 200)) for l in labels}
d2 = m.detect_threshold_exogenous(sh2, labels, perm_seed=1, boot_seed=2)
print('null case:', d2['status'], d2['threshold'], 'p=', d2['p_value'])
assert d2['threshold'] is None

# 3. saturated loss regime (e) → not applicable
sh3 = {l: list(rng.normal(-3.0, 0.3, 200)) for l in labels}
d3 = m.detect_threshold_exogenous(sh3, labels, perm_seed=1, boot_seed=2)
print('saturated case:', d3['status'], d3['threshold'])
assert d3['status'] == 'not_applicable_saturated_loss'

# 4. determinism (fixed seeds → identical output)
d4 = m.detect_threshold_exogenous(sh, labels, perm_seed=1, boot_seed=2)
assert d4['p_value'] == d['p_value'] and d4['threshold'] == d['threshold']
print('deterministic: True')

# 5. robustness descriptive grid
print('robustness grid:', m.robustness_drop_grid(sh, labels))

# 6. RandomRebalanceAgent turnover matching sanity
ag = m.RandomRebalanceAgent(freq=0.8, dw_mean=0.05, dw_std=0.03)
ag._rng = np.random.RandomState(7)
w = np.zeros(10)
dws, moves = [], 0
for t in range(1, 5001):
    new_w, dem = ag.update_target_weight(t, None, None, None, w)
    adw = abs(float(np.mean(new_w)) - float(np.mean(w)))
    if adw > 1e-12:
        moves += 1
        dws.append(adw)
    w = new_w
print(f'RR matched: freq={moves/5000:.3f} (target 0.8), '
      f'|dw| mean={np.mean(dws):.4f} (target ~0.05, clipping shrinks), '
      f'std={np.std(dws):.4f}')

print('ALL DETECTOR UNIT CHECKS PASS')
