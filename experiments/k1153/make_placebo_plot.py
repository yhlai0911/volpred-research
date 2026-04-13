#!/usr/bin/env python3
"""K1153 placebo distribution histogram + observed overlay."""
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

BASE = Path(__file__).resolve().parent
with open(BASE / 'k1153_placebo_results.json') as f:
    d = json.load(f)

placebo = np.array(d['placebo_thetas'])
observed = d['observed_theta_eav']
mean_p = d['placebo_mean']
se_p = d['placebo_se']
z = d['z_observed_relative_to_placebo']

fig, ax = plt.subplots(1, 1, figsize=(9, 4.5))
ax.hist(placebo, bins=25, color='steelblue', edgecolor='black', alpha=0.75,
        label=f'Placebo draws (N={len(placebo)})')
ax.axvline(observed, color='red', linewidth=2.2,
           label=f'Observed θ_EAV = {observed:+.3e}\n(z = {z:+.2f}σ)')
ax.axvline(mean_p, color='gray', linestyle='--',
           label=f'Placebo mean = {mean_p:+.3e}')
ax.axvline(mean_p - 1.96 * se_p, color='gray', linestyle=':', alpha=0.7)
ax.axvline(mean_p + 1.96 * se_p, color='gray', linestyle=':', alpha=0.7,
           label=f'Placebo ±1.96 SE')
ax.set_xlabel(r'$\theta_{EAV}$')
ax.set_ylabel('Frequency')
ax.set_title('K1153 EU: Within-stock EAV permutation placebo vs observed')
ax.legend(loc='upper left', fontsize=9)
plt.tight_layout()
out = BASE / 'k1153_placebo_distribution.png'
plt.savefig(out, dpi=120)
plt.close()
print(f'Saved {out}')
