"""K1471 full run wrapper for compute_queue (M=500, all cells).

Invoked by the compute worker:
    uv run python experiments/k1471_vt_crowding_redesign/run_full_m500.py

Equivalent to:
    k1471_vt_crowding_redesign.py --n-sims 500 --tag full
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

if __name__ == '__main__':
    cmd = [sys.executable,
           os.path.join(HERE, 'k1471_vt_crowding_redesign.py'),
           '--n-sims', '500', '--tag', 'full']
    raise SystemExit(subprocess.call(cmd))
