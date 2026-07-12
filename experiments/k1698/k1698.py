"""
K1698 — forecast-tail-divergence E1 v2: scale re-calibration gating experiment,
compliant rerun of K1684 (Codex review BLOCKED 2026-07-12).

Every blocker in experiments/k1684/CODEX_REVIEW_BLOCKED.md is addressed here:

  B1  Headline DM depended on an unstable 4-start GJR.
      -> fit_gjr_robust(): 120 seeded random starts per refit; convergence flags,
         objective values and the likelihood-basin distribution are stored per refit.
         ALL headline QLIKE / DM / VaR / ES numbers use the robust fit. The K1684
         fragility probe is re-run on the robust fit to demonstrate the instability
         is resolved (fragility_probe_v2).

  B2  RV construction did not provably cover close-to-close, used TX1 only, and
      left the 13:30/13:45 information sets overlapping.
      -> build_aligned_rv(): reads the ALL-contract TX files, selects the active
         contract EACH DAY by traded volume (experiment-preamble rule), builds ONE
         continuous 5-min price path per day for THAT contract over the window
             13:30(D-1)  ->  13:30(D)
         i.e. day-session tail of D-1 (13:30,13:45] + the 13:45->15:00 gap + the
         night session 15:00(D-1)->05:00(D) (PM->AM jump included) + the
         05:00->08:45 gap + the day session 08:45->13:30 of D. All session-boundary
         jumps enter as returns of the SAME contract (no roll jumps). The window
         ends exactly at the 0050.TW 13:30 close, so RV(t-1) used as a predictor
         ends exactly where the target return window starts: the information sets
         are disjoint BY CONSTRUCTION, verified mechanically by
         rv_window_boundary_audit().

  B3  implied_c identification and CI were wrong (decreasing transform assumed,
      Normal mapping applied to CF/HistSim, untested |dc|<0.10 threshold).
      -> The channel diagnostic now uses a DISTRIBUTION-FREE empirical scale:
             u_t = r_t / VaR_t ;  c_emp(alpha) = empirical (1-alpha)-quantile of u
         (r_t < c*VaR_t  <=>  u_t > c, so c_emp is exactly the multiplier on VaR --
         equivalently on sigma -- that delivers exact coverage). c_emp needs no
         distributional assumption, so it applies to every tail layer. Scale-vs-
         shape is decided by a PAIRED moving-block bootstrap of
         (c_emp(1%), c_emp(5%)) with a formal test of delta_c = 0 -- no fixed 0.10
         threshold. The Normal mapping Phi^-1(alpha)/Phi^-1(pi) is reported ONLY
         for +Normal cells, labelled as Normal-conditional, with the CI monotonicity
         FIXED (c is increasing in pi for pi < 0.5).

  B4  The placebo materially moved GJR and was reported as "near 1".
      -> GJRf / GJRf-a appear in EVERY table (VaR trinity at both alphas, ES, FZ0,
         c_emp bootstrap) with the same calibre as the HAR cells. The pre-registered
         placebo criterion compares the correction magnitudes (s_HAR vs s_GJR) and
         reports whether the machinery moves GJR's verdicts -- no "near 1" prose.
         The three theta estimators share the same r^2/RV data; their time-series
         correlation is reported and they are described as three estimators of the
         same wedge, NOT independent evidence.

  B5  Gate and reporting calibre were too strong / inconsistent.
      -> Formal DM conclusions use Harvey |t| > 3 (pre-registered below).
         decide_gate() now EXPLICITLY checks the leg-2 baseline pattern
         (HAR+CF trinity FAIL at 1% AND robust GJR+CF trinity PASS at 1%).
         Every DM pair uses its own pairwise common mask and reports n.
         1% + 5%, IN-SAMPLE + OOS VaR AND ES (McNeil-Frey + Acerbi-Szekely Z2)
         and the Fissler-Ziegel FZ0 joint VaR-ES loss are all reported.

  B6  Results were not written atomically.
      -> write_results_atomic(): tmp file in the same dir -> json.load parse
         verification -> os.replace.

PRE-REGISTERED GATE (fixed before the new numbers were seen; see GATE_RULES):
  leg 1 : HAR-RV (uncorrected) vs robust GJR, QLIKE on the ALIGNED target
          (0050 r^2, Patton proxy-robust cross-model target), canonical dm_test.
          "HAR wins" requires t < -3 (Harvey). |t| <= 3 = no significant win.
  leg 2 : baseline divergence pattern = HAR+CF trinity FAIL at 1% AND robust
          GJR+CF trinity PASS at 1% (both OOS).
  rescue: a corrected variant rescues HAR iff ANY of its tail layers passes the
          full trinity at BOTH alphas (Kupiec-only coverage reported separately).
  verdict:
      H2_SURVIVES  iff leg1 HAR Harvey-win AND leg2 pattern present AND
                       zero estimable variants rescue.
      H2_REJECTED  iff (leg1 fails) OR (leg2 pattern absent) OR
                       (leg2 present AND every estimable variant rescues).
      H2_PARTIAL   otherwise.
  route: H2_REJECTED -> FRL / Journal of Forecasting short note;
         H2_SURVIVES -> full IJF paper; H2_PARTIAL -> decomposition carries it.

Seeds: everything random is seeded from SEED = 20260712.
Usage:  uv run --extra dev python experiments/k1698/k1698.py
"""

import os
import re
import sys
import glob
import json
import time
import zlib
import shutil
import warnings
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from numba import njit
from scipy.optimize import minimize
from scipy.stats import norm, chi2, skew, kurtosis, beta as beta_dist
from scipy.stats import t as t_dist

warnings.filterwarnings('ignore')

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'experiments', 'k854'))

import k854_common_sample_var as k854  # noqa: E402  (pipeline anchor)
from volpred.stats.model_evaluation import dm_test, qlike_pointwise  # noqa: E402
from volpred.utils import clean_tw50_data  # noqa: E402

# ============================================================
# Configuration
# ============================================================
SEED = 20260712

DATA_DIR = os.path.join(SCRIPT_DIR, 'data')
RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k1698_results.json')
RV_ALIGNED_SNAPSHOT = os.path.join(DATA_DIR, 'tx_rv_aligned_1330_active_contract_2017_2025.csv')
RV_OLD_SNAPSHOT = os.path.join(DATA_DIR, 'tx1_rv_tradedate_convention_2017_2025.csv')
ETF_SNAPSHOT = os.path.join(DATA_DIR, 'tw0050_adjclose_2016_2025.csv')
K1684_DATA = os.path.join(PROJECT_ROOT, 'experiments', 'k1684', 'data')

RV_START = '2017-01-01'
OOS_START = '2023-01-01'
OOS_END = '2024-12-31'
IS_EVAL_START = '2019-01-01'     # in-sample evaluation window start (includes COVID)
BURNIN_START = '2018-01-01'      # long theta window / burn-in tail-pool sensitivity
REFIT_EVERY = 63
HAR_MIN_TRAIN = 250
ALPHA_LEVELS = [0.01, 0.05]
MIN_POOL = 30

GJR_STARTS = 120                 # blocker 1: >= 100 house rule
RGL_STARTS = 40
BOOT_B = 2000                    # paired moving-block bootstrap replications
BOOT_BLOCK = 25
AS_SIM_B = 500                   # Acerbi-Szekely Z2 simulation draws (primary run)
FRAGILITY_DRAWS = 6

TAIL_LAYERS = ['Normal', 'CF', 'HistSim']
HAR_VARIANTS = ['HAR', 'HAR-a', 'HAR-b', 'HAR-c']
PLACEBO_CELLS = ['GJRf+Normal', 'GJRf+CF', 'GJRf-a+Normal', 'GJRf-a+CF']
ANCHOR_CELLS = ['GJR+Normal', 'GJR+CF', 'GJR+Skewed-t', 'RGL+CF']

RUNS = [
    ('primary', 'long', 'oos_only', REFIT_EVERY,
     'GATE. Tail layer pinned to K854 convention (OOS-only pool, 63-day refresh); '
     'only sigma moves. theta estimated on a long real-time window (2018+)'),
    ('sens_theta_short', 'oos_only', 'oos_only', REFIT_EVERY,
     'Sensitivity: theta estimated on the short OOS-only pool too'),
    ('sens_daily_refresh', 'long', 'oos_only', 1,
     'Sensitivity: tail pool refreshed daily'),
    ('sens_burnin_tailpool', 'long', 'burnin', REFIT_EVERY,
     'DIAGNOSTIC (not a gate): tail pool widened to 2018 (contains COVID) — '
     'third-channel evidence, moves the uncorrected baseline on its own'),
]
PRIMARY_RUN = 'primary'

GATE_RULES = {
    'leg1_forecast_loss': (
        'HAR-RV (uncorrected) vs robust GJR, QLIKE scored on the ALIGNED target '
        '(0050 r^2), canonical volpred dm_test (h=1, HAC bandwidth ceil(h^(1/3) n^(1/3))). '
        'HAR wins iff t < -3 (Harvey). |t| <= 3 means no significant forecast-loss win '
        'and leg 1 FAILS. p<0.05 with |t|<=3 is reported but does NOT satisfy leg 1.'
    ),
    'leg2_baseline_pattern': (
        'The K850/K854 divergence pattern must be present under robust estimation: '
        'HAR+CF trinity FAIL at 1% AND GJR+CF trinity PASS at 1% (OOS). '
        'Explicitly checked in code (K1684 said this but never checked it).'
    ),
    'rescue': (
        'A corrected variant (HAR-a/b/c) rescues HAR iff ANY of its three tail layers '
        'passes the FULL trinity at BOTH alpha levels. Kupiec-only coverage at both '
        'alphas is reported separately as a secondary (weaker) criterion.'
    ),
    'verdict': (
        'H2_SURVIVES iff leg1 Harvey-win AND leg2 pattern AND 0/estimable variants rescue. '
        'H2_REJECTED iff (not leg1) OR (not leg2 pattern) OR (all estimable variants rescue). '
        'H2_PARTIAL otherwise.'
    ),
    'route': {
        'H2_REJECTED': 'FRL / Journal of Forecasting SHORT NOTE (divergence is a '
                       'construction artifact; the diagnostic is the contribution)',
        'H2_SURVIVES': 'Full IJF paper (residual orthogonality is real)',
        'H2_PARTIAL': 'Conditional — the H1 decomposition carries the paper either way',
    },
    'channel_classification': (
        'Distribution-free c_emp(alpha) = (1-alpha) empirical quantile of u = r/VaR, '
        'paired moving-block bootstrap (B=%d, block=%d, shared index draws across cells '
        'and alphas). Classification per cell: SHAPE if 95%% CI of delta_c = c(1%%)-c(5%%) '
        'excludes 0; else CALIBRATED if both c CIs contain 1; else SCALE if at least one '
        'c CI excludes 1; else AMBIGUOUS.' % (BOOT_B, BOOT_BLOCK)
    ),
}

TX_TIME = {
    'night_pm': (150000, 235959),
    'night_am': (0, 50000),
    'day_main': (84500, 133000),   # inclusive upper bound = the 13:30 anchor
    'day_tail_lo': 133000,         # exclusive
    'day_tail_hi': 134500,         # inclusive
}
DELIVERY_RE = re.compile(r'^\d{6}$')


def log(msg):
    print(msg, flush=True)


def stable_seed(*parts):
    """Deterministic seed from string parts (python hash() is process-randomized)."""
    return SEED + zlib.crc32('|'.join(str(p) for p in parts).encode()) % 10 ** 6


# ============================================================
# Part 1 — RV construction (blocker 2)
# ============================================================

def _bucket5(t_int):
    h = t_int // 10000
    m = (t_int % 10000) // 100
    return h * 100 + (m // 5) * 5


def _last_per_bucket(t_arr, p_arr):
    """5-min bar closes: last tick per bucket, chronological (rows are time-sorted)."""
    if len(t_arr) == 0:
        return np.array([], dtype=int), np.array([], dtype=float)
    order = np.argsort(t_arr, kind='stable')
    t_s, p_s = t_arr[order], p_arr[order]
    buckets = (t_s // 10000) * 100 + ((t_s % 10000) // 100) // 5 * 5
    change = np.nonzero(np.diff(buckets))[0]
    idx_last = np.concatenate([change, [len(buckets) - 1]])
    return buckets[idx_last], p_s[idx_last]


def parse_tx_file(filepath, top_k=4, only_delivery=None):
    """Parse one all-contract TX daily file into per-delivery session segments.

    Returns None on unreadable files, else
      {'file_date': str, 'volume_by_delivery': {d: vol},
       'seg': {delivery: {'night_pm': (bkt, px), 'night_am': ..., 'day_main': ...,
               'day_tail': ..., 'anchor_1330': float|None,
               'tmin_tmax': {segname: (tmin, tmax)}}},
       'pm_trade_dates_mode': int|None}
    """
    base = os.path.basename(filepath)
    try:
        parts = base.replace('Daily_', '').replace('TX.csv', '').split('_')
        file_date = f'{parts[0]}-{parts[1]}-{parts[2]}'
    except Exception:
        return None
    if os.path.getsize(filepath) < 100:
        return None
    try:
        df = pd.read_csv(filepath, encoding='big5', dtype=str, low_memory=False)
    except Exception:
        try:
            df = pd.read_csv(filepath, encoding='cp950', dtype=str, low_memory=False)
        except Exception:
            return None
    if len(df) < 10:
        return None
    try:
        delivery = df.iloc[:, 2].astype(str).str.strip()
        keep = delivery.str.match(DELIVERY_RE)   # monthly contracts only (no spreads/weeklies)
        df = df[keep]
        delivery = delivery[keep]
        t = pd.to_numeric(df.iloc[:, 3], errors='coerce')
        p = pd.to_numeric(df.iloc[:, 4], errors='coerce')
        v = pd.to_numeric(df.iloc[:, 5], errors='coerce').fillna(0.0)
        td = pd.to_numeric(df.iloc[:, 0], errors='coerce')
        ok = t.notna() & p.notna()
        t = t[ok].astype(int).values
        p = p[ok].astype(float).values
        v = v[ok].astype(float).values
        td = td[ok].values
        dl = delivery[ok].values
    except Exception:
        return None
    if len(t) < 10:
        return None

    vol_by = {}
    for d in np.unique(dl):
        vol_by[str(d)] = float(v[dl == d].sum())
    if only_delivery is not None:
        wanted = [only_delivery] if only_delivery in vol_by else []
    else:
        wanted = sorted(vol_by, key=vol_by.get, reverse=True)[:top_k]

    pm_mask_all = (t >= TX_TIME['night_pm'][0]) & (t <= TX_TIME['night_pm'][1])
    pm_dates = td[pm_mask_all]
    pm_mode = None
    if len(pm_dates) > 0:
        vals, counts = np.unique(pm_dates[np.isfinite(pm_dates)], return_counts=True)
        if len(vals) > 0:
            pm_mode = int(vals[np.argmax(counts)])

    seg = {}
    for d in wanted:
        m = dl == d
        td_, tp_ = t[m], p[m]
        masks = {
            'night_pm': (td_ >= TX_TIME['night_pm'][0]) & (td_ <= TX_TIME['night_pm'][1]),
            'night_am': (td_ >= TX_TIME['night_am'][0]) & (td_ <= TX_TIME['night_am'][1]),
            'day_main': (td_ >= TX_TIME['day_main'][0]) & (td_ <= TX_TIME['day_main'][1]),
            'day_tail': (td_ > TX_TIME['day_tail_lo']) & (td_ <= TX_TIME['day_tail_hi']),
        }
        entry = {'tmin_tmax': {}}
        for name, mm in masks.items():
            bkt, px = _last_per_bucket(td_[mm], tp_[mm])
            entry[name] = (bkt, px)
            if mm.sum() > 0:
                entry['tmin_tmax'][name] = (int(td_[mm].min()), int(td_[mm].max()))
        dm_mask = masks['day_main']
        if dm_mask.sum() > 0:
            order = np.argsort(td_[dm_mask], kind='stable')
            entry['anchor_1330'] = float(tp_[dm_mask][order][-1])   # last price at t <= 13:30
        else:
            entry['anchor_1330'] = None
        seg[d] = entry

    return {'file_date': file_date, 'volume_by_delivery': vol_by, 'seg': seg,
            'pm_trade_dates_mode': pm_mode}


def build_aligned_rv(limit=None):
    """Active-contract, gap-complete, 13:30-aligned daily RV.

    RV(D) = sum of squared 5-min log returns of ONE contract (the max-volume
    contract of trade date D) over the continuous path
        anchor 13:30(D-1) -> day tail(D-1) -> night PM -> night AM -> day(D) 13:30.
    """
    from concurrent.futures import ProcessPoolExecutor

    files = sorted(glob.glob(os.path.join(k854.DATA_DIR, 'Daily_*TX.csv')))
    cutoff = f"Daily_{RV_START.replace('-', '_')}"
    files = [f for f in files if cutoff <= os.path.basename(f) < 'Daily_2026']
    if limit:
        files = files[:limit]
    log(f'  {len(files)} all-contract TX files from {RV_START}')

    parsed = {}
    n_workers = min(8, os.cpu_count() or 4)
    with ProcessPoolExecutor(max_workers=n_workers) as ex:
        for i, res in enumerate(ex.map(parse_tx_file, files, chunksize=20)):
            if res is not None:
                parsed[res['file_date']] = res
            if (i + 1) % 400 == 0:
                log(f'    parsed {i + 1}/{len(files)}')
    dates = sorted(parsed)

    rows = []
    n_refetch = 0
    boundary_records = []
    for j in range(1, len(dates)):
        d_prev, d_cur = dates[j - 1], dates[j]
        cur = parsed[d_cur]
        if not cur['volume_by_delivery']:
            continue
        active = max(cur['volume_by_delivery'], key=cur['volume_by_delivery'].get)

        prev = parsed[d_prev]
        prev_seg = prev['seg'].get(active)
        if prev_seg is None:
            # active(D) was not in D-1's top-k: targeted re-read (rare)
            fp = os.path.join(k854.DATA_DIR, f"Daily_{d_prev.replace('-', '_')}TX.csv")
            re_parsed = parse_tx_file(fp, only_delivery=active)
            prev_seg = re_parsed['seg'].get(active) if re_parsed else None
            n_refetch += 1

        cur_seg = cur['seg'].get(active)
        if cur_seg is None:
            continue

        pieces = []
        anchor_ok = False
        if prev_seg is not None and prev_seg['anchor_1330'] is not None:
            pieces.append(np.array([prev_seg['anchor_1330']]))
            anchor_ok = True
        if prev_seg is not None:
            pieces.append(prev_seg['day_tail'][1])
        pieces.append(cur_seg['night_pm'][1])
        pieces.append(cur_seg['night_am'][1])
        pieces.append(cur_seg['day_main'][1])
        path = np.concatenate([p_ for p_ in pieces if len(p_) > 0])
        if len(path) < 30:
            continue
        rets = np.diff(np.log(path))
        rv = float(np.sum(rets ** 2))

        prev_active = None
        if j >= 2 and parsed[dates[j - 1]]['volume_by_delivery']:
            prev_active = max(parsed[d_prev]['volume_by_delivery'],
                              key=parsed[d_prev]['volume_by_delivery'].get)
        rows.append({
            'date': d_cur, 'rv_aligned': rv, 'active_delivery': active,
            'n_returns': int(len(rets)), 'anchor_ok': bool(anchor_ok),
            'rolled': bool(prev_active is not None and prev_active != active),
        })
        if len(boundary_records) < 60:
            rec = {'date': d_cur, 'active': active,
                   'prev_day_tail_span': prev_seg['tmin_tmax'].get('day_tail') if prev_seg else None,
                   'night_pm_span': cur_seg['tmin_tmax'].get('night_pm'),
                   'night_am_span': cur_seg['tmin_tmax'].get('night_am'),
                   'day_main_span': cur_seg['tmin_tmax'].get('day_main'),
                   'pm_trade_date_mode': cur['pm_trade_dates_mode']}
            boundary_records.append(rec)

    df = pd.DataFrame(rows)
    df['date'] = pd.to_datetime(df['date'])
    df = df.set_index('date').sort_index()
    log(f'  aligned RV days={len(df)}  roll days={int(df["rolled"].sum())}  '
        f'anchor_missing={int((~df["anchor_ok"]).sum())}  prev-file refetches={n_refetch}')
    return df, boundary_records


def rv_window_boundary_audit(boundary_records):
    """Mechanical proof that RV(D) uses nothing outside (13:30(D-1), 13:30(D)].

    Checks on sampled days: prev-day tail ticks in (13:30,13:45]; night PM in
    [15:00,24:00) and stamped with the PREVIOUS calendar date (trade-date
    convention); night AM in [00:00,05:00]; day session in [08:45,13:30].
    """
    checks = []
    for rec in boundary_records:
        row = {'date': rec['date'], 'active': rec['active']}
        ok = True
        s = rec['prev_day_tail_span']
        row['prev_tail_in_window'] = None if s is None else bool(
            s[0] > TX_TIME['day_tail_lo'] and s[1] <= TX_TIME['day_tail_hi'])
        if row['prev_tail_in_window'] is False:
            ok = False
        s = rec['night_pm_span']
        row['night_pm_in_window'] = None if s is None else bool(
            s[0] >= TX_TIME['night_pm'][0] and s[1] <= TX_TIME['night_pm'][1])
        if row['night_pm_in_window'] is False:
            ok = False
        s = rec['night_am_span']
        row['night_am_in_window'] = None if s is None else bool(
            s[0] >= 0 and s[1] <= TX_TIME['night_am'][1])
        if row['night_am_in_window'] is False:
            ok = False
        s = rec['day_main_span']
        row['day_main_in_window'] = None if s is None else bool(
            s[0] >= TX_TIME['day_main'][0] and s[1] <= TX_TIME['day_main'][1])
        if row['day_main_in_window'] is False:
            ok = False
        pmd = rec['pm_trade_date_mode']
        d_int = int(pd.Timestamp(rec['date']).strftime('%Y%m%d'))
        row['night_pm_stamped_before_file_date'] = None if pmd is None else bool(pmd < d_int)
        row['all_ok'] = ok
        checks.append(row)
    flat = [c['all_ok'] for c in checks]
    return {'n_days_checked': len(checks), 'all_passed': bool(all(flat)),
            'implication': 'RV(D) window is (13:30(D-1), 13:30(D)] with the anchor price AT '
                           '13:30(D-1): as a predictor, RV(t-1) ends exactly where the 0050 '
                           'close-to-close target window for day t begins — the information '
                           'sets are disjoint by construction (13:30/13:45 overlap sealed).',
            'checks': checks[:12]}


# ============================================================
# Part 2 — Data loaders (pinned snapshots)
# ============================================================

def load_rv_aligned():
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(RV_ALIGNED_SNAPSHOT):
        log(f'  [cache] {os.path.basename(RV_ALIGNED_SNAPSHOT)}')
        df = pd.read_csv(RV_ALIGNED_SNAPSHOT, parse_dates=['date']).set_index('date').sort_index()
        return df, None
    df, boundary = build_aligned_rv()
    df.to_csv(RV_ALIGNED_SNAPSHOT, index_label='date')
    log(f'  [pinned] {RV_ALIGNED_SNAPSHOT}')
    return df, boundary


def load_rv_old():
    """K854/K1684 trade-date-convention TX1 RV (bridge diagnostic)."""
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(RV_OLD_SNAPSHOT):
        src = os.path.join(K1684_DATA, 'tx_rv_5min_daily_2017_2025.csv')
        shutil.copy(src, RV_OLD_SNAPSHOT)
        log(f'  [pinned copy of k1684 snapshot] {RV_OLD_SNAPSHOT}')
    return pd.read_csv(RV_OLD_SNAPSHOT, parse_dates=['date']).set_index('date').sort_index()


def load_etf():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(ETF_SNAPSHOT):
        src = os.path.join(K1684_DATA, 'tw0050_adjclose_2016_2025.csv')
        if os.path.exists(src):
            shutil.copy(src, ETF_SNAPSHOT)
            log(f'  [pinned copy of k1684 snapshot] {ETF_SNAPSHOT}')
        else:
            import yfinance as yf
            raw = yf.download('0050.TW', start='2016-01-01', end='2026-01-01',
                              progress=False, auto_adjust=True)
            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = raw.columns.get_level_values(0)
            s = raw['Close'].squeeze()
            s.index = pd.to_datetime(s.index).tz_localize(None)
            s.name = 'adj_close'
            s.to_csv(ETF_SNAPSHOT, index_label='date')
    return pd.read_csv(ETF_SNAPSHOT, parse_dates=['date']).set_index('date')['adj_close'].sort_index()


# ============================================================
# Part 3 — Robust MLE (blocker 1)
# ============================================================

def fit_gjr_robust(returns, n_starts=GJR_STARTS, seed=0):
    """GJR-GARCH(1,1) MLE with >=100 seeded random starts + basin diagnostics."""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    if len(r) < 100:
        return None, None
    var_r = float(np.var(r))

    def negll(params):
        omega, alpha, beta, gamma = params
        if omega <= 0 or alpha < 0 or beta < 0 or gamma < 0:
            return 1e10
        if alpha + beta + 0.5 * gamma >= 1.0:
            return 1e10
        s2 = k854.gjr_filter(r, omega, alpha, beta, gamma)
        ll = -0.5 * np.sum(np.log(s2[1:]) + r[1:] ** 2 / s2[1:])
        return -ll if np.isfinite(ll) else 1e10

    rng = np.random.default_rng(seed)
    records = []
    best_res, best_nll = None, np.inf
    for _ in range(n_starts):
        a0 = rng.uniform(0.01, 0.20)
        g0 = rng.uniform(0.0, 0.30)
        b0 = rng.uniform(0.50, 0.985)
        if a0 + b0 + 0.5 * g0 >= 0.995:
            b0 = max(0.30, 0.985 - a0 - 0.5 * g0)
        o0 = max(1e-10, var_r * (1 - a0 - b0 - 0.5 * g0))
        res = minimize(negll, [o0, a0, b0, g0], method='L-BFGS-B',
                       bounds=[(1e-10, None), (0, 0.5), (0, 0.999), (0, 0.5)],
                       options={'maxiter': 3000})
        pers = float(res.x[1] + res.x[2] + 0.5 * res.x[3])
        records.append((float(res.fun), bool(res.success), pers))
        if res.fun < best_nll:
            best_nll, best_res = float(res.fun), res
    if best_res is None or best_nll >= 1e9:
        return None, None

    conv = [rec for rec in records if rec[0] < 1e9]
    nlls = np.array(sorted(rec[0] for rec in conv))
    # basin clustering: group converged objectives within 1e-3 LL units
    basins = []
    for f, ok, pers in sorted(conv):
        placed = False
        for b in basins:
            if abs(f - b['nll']) < 1e-3:
                b['count'] += 1
                placed = True
                break
        if not placed:
            basins.append({'nll': round(f, 6), 'count': 1, 'persistence': round(pers, 6)})
    diag = {
        'n_starts': n_starts,
        'n_converged': int(sum(1 for rec in records if rec[1])),
        'n_feasible': len(conv),
        'best_nll': round(best_nll, 6),
        'share_in_best_basin': round(basins[0]['count'] / max(len(conv), 1), 4) if basins else None,
        'll_gap_to_second_basin': (round(basins[1]['nll'] - basins[0]['nll'], 6)
                                   if len(basins) > 1 else None),
        'n_basins': len(basins),
        'top_basins': basins[:5],
    }
    omega, alpha, beta, gamma = best_res.x
    params = {'omega': float(omega), 'alpha': float(alpha), 'beta': float(beta),
              'gamma': float(gamma), 'persistence': float(alpha + beta + 0.5 * gamma)}
    return params, diag


def gjr_forecast_path_robust(r, start_idx, end_idx, seed_base):
    """K854's GJR OOS loop with the robust fit; per-refit basin diagnostics kept."""
    n = len(r)
    f = np.full(n, np.nan)
    z_by_refit = {}
    params_by_idx = np.empty(n, dtype=object)
    refit_diags = []
    cur, last = None, -REFIT_EVERY
    for i in range(start_idx, end_idx):
        d = i - start_idx
        if d - last >= REFIT_EVERY or cur is None:
            if len(r[:i]) < 500:
                continue
            p, diag = fit_gjr_robust(r[:i], seed=seed_base + i)
            if p is not None:
                cur, last = p, d
                diag['refit_origin_index'] = int(i)
                diag['persistence'] = round(p['persistence'], 6)
                refit_diags.append(diag)
                z_by_refit[i] = k854.compute_standardized_residuals(r[:i], p)
        if cur is None:
            continue
        f[i] = k854.gjr_one_step_forecast(r[:i], cur)
        params_by_idx[i] = cur
    return f, z_by_refit, params_by_idx, refit_diags


@njit(cache=True)
def _rgl_negll(r, log_rv, omega, beta, delta):
    T = r.shape[0]
    k = 22 if T >= 22 else T
    m = 0.0
    for i in range(k):
        m += log_rv[i]
    m /= k
    log_h_prev = omega / (1 - beta) + delta / (1 - beta) * m
    nll = 0.0
    for t in range(1, T):
        log_h = omega + beta * log_h_prev + delta * log_rv[t - 1]
        if log_h > 60.0 or log_h < -80.0:
            return 1e10
        h = np.exp(log_h)
        if h < 1e-16:
            h = 1e-16
        nll += 0.5 * (log_h + r[t] * r[t] / h)
        log_h_prev = log_h
    return nll


def fit_rgl_robust(returns, rv_arr, n_starts=RGL_STARTS, seed=0):
    """RealGARCH-Log MLE (K854 spec) with seeded multistart + basin diagnostics."""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    rv = np.ascontiguousarray(rv_arr, dtype=np.float64)
    if len(r) < 100:
        return None, None
    rv_clean = rv.copy()
    pos = rv_clean[rv_clean > 0]
    if len(pos) == 0:
        return None, None
    running_mean = float(np.nanmean(pos))
    rv_clean[(rv_clean <= 0) | ~np.isfinite(rv_clean)] = running_mean
    log_rv = np.log(rv_clean)

    def negll(params):
        omega, beta, delta = params
        if beta < -0.999 or beta > 0.999 or delta < 0 or delta > 2.0:
            return 1e10
        v = _rgl_negll(r, log_rv, omega, beta, delta)
        return v if np.isfinite(v) else 1e10

    rng = np.random.default_rng(seed)
    records = []
    best_res, best_nll = None, np.inf
    for _ in range(n_starts):
        omega0 = rng.uniform(-1.0, 0.5)
        beta0 = rng.uniform(0.1, 0.95)
        delta0 = rng.uniform(0.05, 0.9)
        res = minimize(negll, [omega0, beta0, delta0], method='L-BFGS-B',
                       bounds=[(-5, 5), (-0.999, 0.999), (0.001, 2.0)],
                       options={'maxiter': 3000})
        records.append((float(res.fun), bool(res.success)))
        if res.fun < best_nll:
            best_nll, best_res = float(res.fun), res
    if best_res is None or best_nll >= 1e9:
        return None, None
    conv = sorted(f for f, ok in records if f < 1e9)
    basins = []
    for fv in conv:
        if basins and abs(fv - basins[-1][0]) < 1e-3:
            basins[-1][1] += 1
        elif not any(abs(fv - b[0]) < 1e-3 for b in basins):
            basins.append([round(fv, 6), 1])
        else:
            for b in basins:
                if abs(fv - b[0]) < 1e-3:
                    b[1] += 1
                    break
    diag = {'n_starts': n_starts, 'best_nll': round(best_nll, 6),
            'n_basins': len(basins),
            'share_in_best_basin': round(basins[0][1] / max(len(conv), 1), 4) if basins else None}
    omega, beta, delta = best_res.x
    return {'omega': float(omega), 'beta': float(beta), 'delta': float(delta),
            'persistence': float(beta)}, diag


def rgl_forecast_path(r, rv, start_idx, end_idx, seed_base):
    n = len(r)
    f = np.full(n, np.nan)
    z_by_refit = {}
    diags = []
    cur, last = None, -REFIT_EVERY
    for i in range(start_idx, end_idx):
        d = i - start_idx
        if d - last >= REFIT_EVERY or cur is None:
            if len(r[:i]) < 500:
                continue
            p, diag = fit_rgl_robust(r[:i], rv[:i], seed=seed_base + i)
            if p is not None:
                cur, last = p, d
                diags.append(diag)
                z_by_refit[i] = k854.compute_std_residuals_real_log(r[:i], rv[:i], p)
        if cur is None:
            continue
        f[i] = k854.realgarch_log_one_step_forecast(r[:i], rv[:i], cur)
    return f, z_by_refit, diags


def har_insample_fitted(rv_vals, fit_upto):
    """HAR fitted (in-sample) values: one OLS on rv[:fit_upto], fitted at every t."""
    train = rv_vals[:fit_upto]
    nn = len(train)
    rv_d = np.full(nn, np.nan)
    rv_w = np.full(nn, np.nan)
    rv_m = np.full(nn, np.nan)
    for i in range(1, nn):
        rv_d[i] = train[i - 1]
    for i in range(5, nn):
        rv_w[i] = np.mean(train[i - 5:i])
    for i in range(22, nn):
        rv_m[i] = np.mean(train[i - 22:i])
    feat = np.column_stack([rv_d, rv_w, rv_m])
    valid = ~np.any(np.isnan(feat), axis=1) & ~np.isnan(train)
    beta, _, _ = k854.fit_har_ols(train[valid], feat[valid])
    out = np.full(nn, np.nan)
    if beta is None:
        return out
    X = np.column_stack([np.ones(nn), feat])
    fit = X @ beta
    out[valid] = np.maximum(fit[valid], 1e-10)
    return out


# ============================================================
# Part 4 — Correction parameters theta (ported from K1684, unchanged logic)
# ============================================================

def estimate_theta(pool_slice, r, s2_src, rv):
    idx = pool_slice[np.isfinite(s2_src[pool_slice]) & (s2_src[pool_slice] > 0)
                     & np.isfinite(r[pool_slice])]
    if len(idx) <= MIN_POOL:
        return None
    z = r[idx] / np.sqrt(s2_src[idx])
    s_a = float(np.std(z, ddof=1))
    m = np.isfinite(r[pool_slice]) & np.isfinite(rv[pool_slice]) & (rv[pool_slice] > 0)
    jj = pool_slice[m]
    k_c = float(np.sum(r[jj] ** 2) / np.sum(rv[jj])) if len(jj) > MIN_POOL else np.nan
    nz = idx[r[idx] != 0.0]
    mz = None
    if len(nz) >= MIN_POOL:
        x = np.log(s2_src[nz])
        y = np.log(r[nz] ** 2)
        X = np.column_stack([np.ones(len(x)), x])
        try:
            b = np.linalg.lstsq(X, y, rcond=None)[0]
            resid = y - X @ b
            smear = float(np.mean(np.exp(resid)))
            if np.isfinite(smear) and smear > 0:
                mz = {'a': float(b[0]), 'b': float(b[1]), 'smear': smear}
        except Exception:
            mz = None
    return {'pool_idx': idx, 'z': z, 's_a': s_a, 'k_c': k_c, 'mz': mz, 'n_pool': int(len(idx))}


def sigma2_variant(name, s2_har, theta):
    if name == 'HAR':
        return s2_har
    if name == 'HAR-a':
        return s2_har * theta['s_a'] ** 2
    if name == 'HAR-c':
        return s2_har * theta['k_c']
    if name == 'HAR-b':
        if theta['mz'] is None:
            return np.full_like(np.asarray(s2_har, dtype=float), np.nan)
        mz = theta['mz']
        return np.exp(mz['a'] + mz['b'] * np.log(s2_har)) * mz['smear']
    raise ValueError(name)


# ============================================================
# Part 5 — Tail layers: quantiles AND expected shortfall (z-space)
# ============================================================

_GLX, _GLW = np.polynomial.legendre.leggauss(64)


def cf_quantile_moments(S, K, u):
    z = norm.ppf(u)
    return (z + (z ** 2 - 1) * S / 6.0 + (z ** 3 - 3 * z) * K / 24.0
            - (2 * z ** 3 - 5 * z) * S ** 2 / 36.0)


def normal_es_z(alpha):
    return float(-norm.pdf(norm.ppf(alpha)) / alpha)


def cf_es_z(S, K, alpha):
    u = alpha * (_GLX + 1) / 2.0
    q = cf_quantile_moments(S, K, u)
    return float(np.sum(_GLW * q) * (alpha / 2.0) / alpha)


def hist_es_z(zpool, alpha):
    q = np.percentile(zpool, alpha * 100)
    tail = zpool[zpool <= q]
    if len(tail) == 0:
        return float(q)
    return float(np.mean(tail))


def skewt_es_z(df, xi, alpha):
    u = alpha * (_GLX + 1) / 2.0
    q = np.array([k854.skewt_ppf(float(ui), df=df, xi=xi) for ui in u])
    return float(np.sum(_GLW * q) * (alpha / 2.0) / alpha)


# ============================================================
# Part 6 — Backtests, implied scale, bootstrap, ES tests, FZ0
# ============================================================

def implied_c_normal(n_viol, n_total, alpha):
    """Normal-conditional mapping c = Phi^-1(alpha)/Phi^-1(pi).

    Valid ONLY under a Normal(0, sigma^2) return model, i.e. reported only for
    +Normal cells. c is INCREASING in pi for pi < 0.5 (K1684 assumed decreasing —
    that inverted 154 CIs); the CI now maps lo->lo, hi->hi.
    """
    def _c(pi):
        if pi is None or not np.isfinite(pi) or pi <= 0 or pi >= 0.5:
            return None
        return float(norm.ppf(alpha) / norm.ppf(pi))

    pi_hat = n_viol / n_total if n_total else np.nan
    lo = 0.0 if n_viol == 0 else float(beta_dist.ppf(0.025, n_viol, n_total - n_viol + 1))
    hi = 1.0 if n_viol == n_total else float(beta_dist.ppf(0.975, n_viol + 1, n_total - n_viol))
    return {'implied_c_normal': _c(pi_hat),
            'implied_c_normal_lo95': _c(lo), 'implied_c_normal_hi95': _c(hi),
            'pi_lo95': lo, 'pi_hi95': hi,
            'note': 'Normal-conditional; increasing in pi (monotonicity fixed vs K1684)'}


def c_emp_point(returns, var_arr, alpha):
    """Distribution-free implied scale: (1-alpha) empirical quantile of u = r/VaR."""
    ok = var_arr < 0
    if ok.sum() < 30:
        return None
    u = returns[ok] / var_arr[ok]
    return float(np.quantile(u, 1 - alpha))


def backtest_cell(returns, var_arr, alpha):
    bt = k854.var_backtest(returns, var_arr, alpha_var=alpha)
    lr_cc = float(bt['kupiec']['stat'] + bt['christoffersen']['stat'])
    p_cc = float(1 - chi2.cdf(lr_cc, df=2))
    bt['christoffersen_cc_joint'] = {
        'stat': round(lr_cc, 4), 'p_value': round(p_cc, 4), 'pass': bool(p_cc > 0.05),
        'note': 'LR_cc = LR_uc + LR_ind, df=2; "christoffersen" field = independence only',
    }
    lo = 0.0 if bt['n_violations'] == 0 else float(
        beta_dist.ppf(0.025, bt['n_violations'], bt['n_total'] - bt['n_violations'] + 1))
    hi = 1.0 if bt['n_violations'] == bt['n_total'] else float(
        beta_dist.ppf(0.975, bt['n_violations'] + 1, bt['n_total'] - bt['n_violations']))
    bt['violation_rate_ci95'] = [round(lo, 6), round(hi, 6)]
    bt['implied_c_empirical'] = c_emp_point(returns, var_arr, alpha)
    bt['n_var_nonnegative_days'] = int((var_arr >= 0).sum())
    return bt


def block_bootstrap_indices(n, B, block, seed):
    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(n / block))
    starts = rng.integers(0, n - block + 1, size=(B, n_blocks))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(B, -1)[:, :n]
    return idx


def bootstrap_c_emp(returns, var_by_alpha, boot_idx):
    """Paired moving-block bootstrap of (c_emp(1%), c_emp(5%)) and delta_c.

    var_by_alpha: {'1%': var_arr, '5%': var_arr}. The SAME bootstrap index draws
    are used for every cell and both alphas (paired), so delta_c and cross-cell
    contrasts are resampled coherently.
    """
    out = {}
    u = {}
    for ak, a in [('1%', 0.01), ('5%', 0.05)]:
        va = var_by_alpha[ak]
        if np.any(va >= 0):
            return {'error': f'{int((va >= 0).sum())} non-negative VaR days', 'classification': 'undefined'}
        u[ak] = returns / va
    c1 = np.quantile(u['1%'][boot_idx], 0.99, axis=1)
    c5 = np.quantile(u['5%'][boot_idx], 0.95, axis=1)
    dc = c1 - c5
    point1 = float(np.quantile(u['1%'], 0.99))
    point5 = float(np.quantile(u['5%'], 0.95))
    ci1 = [float(np.percentile(c1, 2.5)), float(np.percentile(c1, 97.5))]
    ci5 = [float(np.percentile(c5, 2.5)), float(np.percentile(c5, 97.5))]
    cid = [float(np.percentile(dc, 2.5)), float(np.percentile(dc, 97.5))]
    shape_sig = bool(cid[0] > 0 or cid[1] < 0)
    c1_off = bool(ci1[0] > 1 or ci1[1] < 1)
    c5_off = bool(ci5[0] > 1 or ci5[1] < 1)
    if shape_sig:
        cls = 'SHAPE (delta_c CI excludes 0)'
    elif not c1_off and not c5_off:
        cls = 'calibrated (both c CIs contain 1)'
    elif c1_off or c5_off:
        cls = 'SCALE (c != 1, delta_c CI contains 0)'
    else:
        cls = 'ambiguous'
    return {
        'c_emp_1pct': round(point1, 5), 'c_emp_1pct_ci95': [round(x, 5) for x in ci1],
        'c_emp_5pct': round(point5, 5), 'c_emp_5pct_ci95': [round(x, 5) for x in ci5],
        'delta_c': round(point1 - point5, 5), 'delta_c_ci95': [round(x, 5) for x in cid],
        'classification': cls,
    }


def mcneil_frey_test(returns, var_arr, es_arr, sigma_arr, seed):
    """McNeil-Frey (2000): exceedance residuals e = (r - ES)/sigma, H0 mean 0.

    One-sided alternative mean < 0 (losses beyond ES => ES insufficient).
    Bootstrap p-value; honest about tiny exceedance counts.
    """
    viol = returns < var_arr
    n_exc = int(viol.sum())
    if n_exc < 2:
        return {'n_exceedances': n_exc, 'p_value': None,
                'note': 'insufficient exceedances for the test'}
    e = (returns[viol] - es_arr[viol]) / sigma_arr[viol]
    rng = np.random.default_rng(seed)
    obs = float(np.mean(e))
    centered = e - obs
    boots = np.array([np.mean(centered[rng.integers(0, n_exc, n_exc)]) for _ in range(1000)])
    p_one_sided = float(np.mean(boots <= obs))     # P(mean* <= obs | H0 mean 0)
    return {'n_exceedances': n_exc, 'mean_exceedance_residual': round(obs, 5),
            'p_value_one_sided_es_insufficient': round(p_one_sided, 4),
            'pass': bool(p_one_sided > 0.05),
            'note': 'bootstrap under H0 (centred), B=1000; alternative: mean < 0'}


def fz0_loss(returns, var_arr, es_arr, alpha):
    """Fissler-Ziegel FZ0 joint VaR-ES loss (negative VaR/ES convention).

    Same formula as experiments/research_evt_pot_gpd_garch_filter_es_e_backtesting.
    Rows with es >= var or var >= 0 are invalid and dropped (counted).
    """
    valid = (es_arr < var_arr) & (var_arr < 0) & np.isfinite(es_arr) & np.isfinite(var_arr)
    loss = np.full(len(returns), np.nan)
    y, v, e = returns[valid], var_arr[valid], es_arr[valid]
    hit = (y <= v).astype(float)
    loss[valid] = -(hit * (v - y)) / (alpha * e) + v / e + np.log(-e) - 1.0
    return loss, int((~valid).sum())


def acerbi_szekely_z2(returns, var_arr, es_arr, sigma_arr, alpha, spec_list, seed):
    """AS (2014) Z2 with a simulation p-value under the cell's own tail model.

    Z2_obs = (1/(n*alpha)) * sum_t 1{r_t < VaR_t} * (r_t / ES_t) - 1   (both negative
    => ratio positive; Z2 > 0 means realized tail losses exceed the model ES).
    Under H0 the z_t are drawn from the cell's assumed standardized distribution
    (spec per day: ('normal',) | ('cf', S, K) | ('hist', pool) | ('skewt', df, xi)),
    scale-free because r = sigma*z and VaR/ES = sigma*(q_z, es_z).
    """
    n = len(returns)
    viol = returns < var_arr
    z2_obs = float(np.sum(np.where(viol, returns / es_arr, 0.0)) / (n * alpha) - 1.0)

    q_z = var_arr / sigma_arr
    es_z = es_arr / sigma_arr
    rng = np.random.default_rng(seed)
    contrib = np.zeros((AS_SIM_B, n))
    # group days by identical spec for vectorized simulation
    groups = {}
    for t, spec in enumerate(spec_list):
        key = (spec[0], id(spec[1]) if spec[0] == 'hist' else tuple(spec[1:]))
        groups.setdefault(key, {'spec': spec, 'days': []})['days'].append(t)
    for g in groups.values():
        days = np.array(g['days'])
        spec = g['spec']
        m = len(days)
        if spec[0] == 'normal':
            zs = rng.standard_normal((AS_SIM_B, m))
        elif spec[0] == 'cf':
            U = rng.uniform(1e-9, 1 - 1e-9, (AS_SIM_B, m))
            zs = cf_quantile_moments(spec[1], spec[2], U)
        elif spec[0] == 'hist':
            pool = spec[1]
            zs = pool[rng.integers(0, len(pool), (AS_SIM_B, m))]
        elif spec[0] == 'skewt':
            df_, xi_ = spec[1], spec[2]
            ugrid = np.linspace(1e-5, 1 - 1e-5, 2048)
            qgrid = np.array([k854.skewt_ppf(float(ui), df=df_, xi=xi_) for ui in ugrid])
            U = rng.uniform(1e-5, 1 - 1e-5, (AS_SIM_B, m))
            zs = np.interp(U, ugrid, qgrid)
        else:
            raise ValueError(spec[0])
        hit = zs < q_z[days][None, :]
        contrib[:, days] = np.where(hit, zs / es_z[days][None, :], 0.0)
    z2_sim = contrib.sum(axis=1) / (n * alpha) - 1.0
    p = float(np.mean(z2_sim >= z2_obs))     # one-sided: ES insufficient
    return {'z2_obs': round(z2_obs, 5), 'p_value_one_sided': round(p, 4),
            'pass': bool(p > 0.05), 'n_sim': AS_SIM_B,
            'note': 'simulation under the cell\'s own standardized tail model (z-space)'}


def acf1(x):
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) < 10:
        return None
    return float(np.corrcoef(x[:-1], x[1:])[0, 1])


def dm_pair(l1, l2, label1, label2):
    """Canonical DM on the PAIRWISE common mask, with n and Harvey calibre."""
    valid = np.isfinite(l1) & np.isfinite(l2)
    nd = int(valid.sum())
    if nd < 10:
        return {'t_stat': None, 'n': nd, 'note': 'pairwise mask too small'}
    t_stat, p_val = dm_test(l1[valid], l2[valid], h=1)
    d = l1[valid] - l2[valid]
    return {
        't_stat': round(float(t_stat), 4), 'p_value': round(float(p_val), 6), 'n': nd,
        'loss_diff_acf1': round(acf1(d), 4) if acf1(d) is not None else None,
        'harvey_significant_t_gt_3': bool(abs(t_stat) > 3.0),
        'better_model': label1 if t_stat < 0 else label2,
        'note': 'canonical volpred dm_test; pairwise common mask; formal calibre = Harvey |t|>3',
    }


# ============================================================
# Part 7 — VaR + ES evaluation loop (one run)
# ============================================================

def _family(cell):
    return cell.split('+')[0]


def run_var_es_eval(run_id, theta_window, tail_pool, refresh, role, stack, r, rv,
                    common_dates, eval_idx, oos_start_idx, burnin_idx,
                    gjr_ctx, rgl_ctx, boot_idx, collect_specs):
    n_eval = len(eval_idx)
    eval_r = r[eval_idx]
    har_level = stack['har_level']
    gjr_f = stack['gjr_f']
    rgl_f = stack['rgl_f']

    theta_start = oos_start_idx if theta_window == 'oos_only' else burnin_idx
    har_theta_src = har_level if theta_window == 'oos_only' else stack['har_pool_burnin']
    gjr_theta_src = gjr_f if theta_window == 'oos_only' else stack['gjr_pool_burnin']
    pool_start = oos_start_idx if tail_pool == 'oos_only' else burnin_idx
    har_tail_src = har_level if tail_pool == 'oos_only' else stack['har_pool_burnin']
    gjr_tail_src = gjr_f if tail_pool == 'oos_only' else stack['gjr_pool_burnin']

    all_cells = ([f'{v}+{t}' for v in HAR_VARIANTS for t in TAIL_LAYERS]
                 + PLACEBO_CELLS + ANCHOR_CELLS)
    var_arrays = {f'{int(a*100)}%': {c: np.full(n_eval, np.nan) for c in all_cells}
                  for a in ALPHA_LEVELS}
    es_arrays = {f'{int(a*100)}%': {c: np.full(n_eval, np.nan) for c in all_cells}
                 for a in ALPHA_LEVELS}
    sigma2_cell = {fam: np.full(n_eval, np.nan)
                   for fam in HAR_VARIANTS + ['GJRf', 'GJRf-a', 'GJR', 'RGL']}
    specs = {c: [None] * n_eval for c in all_cells} if collect_specs else None

    theta_trace = {'s_a': np.full(n_eval, np.nan), 'k_c': np.full(n_eval, np.nan),
                   'mz_b': np.full(n_eval, np.nan), 's_gjr': np.full(n_eval, np.nan),
                   'n_theta': np.zeros(n_eval, dtype=int),
                   'n_tail_pool': np.zeros(n_eval, dtype=int)}

    gjr_refits = sorted(gjr_ctx['z'])
    rgl_refits = sorted(rgl_ctx['z'])
    skewt_cache, anchor_cache = {}, {}

    def last_refit_pool(refits, store, i):
        avail = [k for k in refits if k <= i]
        return (avail[-1], store[avail[-1]]) if avail else (None, None)

    theta = theta_g = tail = tail_g = None
    last_refresh = -10 ** 9
    layer_cache = {}

    for k_ev, i in enumerate(eval_idx):
        if k_ev - last_refresh >= refresh or theta is None:
            th = estimate_theta(np.arange(theta_start, i), r, har_theta_src, rv)
            th_g = estimate_theta(np.arange(theta_start, i), r, gjr_theta_src, rv)
            tl = estimate_theta(np.arange(pool_start, i), r, har_tail_src, rv)
            tl_g = estimate_theta(np.arange(pool_start, i), r, gjr_tail_src, rv)
            if th is not None and tl is not None:
                theta, theta_g, tail, tail_g, last_refresh = th, th_g, tl, tl_g, k_ev
                layer_cache = {}
                s2_pool_har = har_tail_src[tail['pool_idx']]
                for v in HAR_VARIANTS:
                    s2_pool_v = sigma2_variant(v, s2_pool_har, theta)
                    okm = np.isfinite(s2_pool_v) & (s2_pool_v > 0)
                    z_v = r[tail['pool_idx'][okm]] / np.sqrt(s2_pool_v[okm])
                    if len(z_v) <= MIN_POOL:
                        continue
                    S, K = float(skew(z_v)), float(kurtosis(z_v, fisher=True))
                    ent = {'z': z_v, 'S': S, 'K': K, 'q': {}, 'es': {}}
                    for a in ALPHA_LEVELS:
                        ak = f'{int(a*100)}%'
                        ent['q'][ak] = {
                            'Normal': float(norm.ppf(a)),
                            'CF': float(cf_quantile_moments(S, K, a)),
                            'HistSim': float(np.percentile(z_v, a * 100)),
                        }
                        ent['es'][ak] = {
                            'Normal': normal_es_z(a),
                            'CF': cf_es_z(S, K, a),
                            'HistSim': hist_es_z(z_v, a),
                        }
                    layer_cache[v] = ent
                if theta_g is not None and tail_g is not None:
                    for pv in ['GJRf', 'GJRf-a']:
                        zz = tail_g['z'] if pv == 'GJRf' else tail_g['z'] / theta_g['s_a']
                        S, K = float(skew(zz)), float(kurtosis(zz, fisher=True))
                        ent = {'z': zz, 'S': S, 'K': K, 'q': {}, 'es': {}}
                        for a in ALPHA_LEVELS:
                            ak = f'{int(a*100)}%'
                            ent['q'][ak] = {'Normal': float(norm.ppf(a)),
                                            'CF': float(cf_quantile_moments(S, K, a))}
                            ent['es'][ak] = {'Normal': normal_es_z(a),
                                             'CF': cf_es_z(S, K, a)}
                        layer_cache[pv] = ent
        if theta is None or tail is None:
            continue

        theta_trace['s_a'][k_ev] = theta['s_a']
        theta_trace['k_c'][k_ev] = theta['k_c']
        theta_trace['mz_b'][k_ev] = theta['mz']['b'] if theta['mz'] else np.nan
        theta_trace['n_theta'][k_ev] = theta['n_pool']
        theta_trace['n_tail_pool'][k_ev] = tail['n_pool']
        if theta_g is not None:
            theta_trace['s_gjr'][k_ev] = theta_g['s_a']

        # HAR family
        for v in HAR_VARIANTS:
            if v not in layer_cache:
                continue
            s2_i = float(sigma2_variant(v, np.array([har_level[i]]), theta)[0])
            if not np.isfinite(s2_i) or s2_i <= 0:
                continue
            sigma2_cell[v][k_ev] = s2_i
            sd = np.sqrt(s2_i)
            ent = layer_cache[v]
            for a in ALPHA_LEVELS:
                ak = f'{int(a*100)}%'
                for t_ in TAIL_LAYERS:
                    var_arrays[ak][f'{v}+{t_}'][k_ev] = sd * ent['q'][ak][t_]
                    es_arrays[ak][f'{v}+{t_}'][k_ev] = sd * ent['es'][ak][t_]
            if collect_specs:
                for t_ in TAIL_LAYERS:
                    spec = (('normal',) if t_ == 'Normal'
                            else ('cf', ent['S'], ent['K']) if t_ == 'CF'
                            else ('hist', ent['z']))
                    specs[f'{v}+{t_}'][k_ev] = spec

        # placebo (GJR with forecast-standardized pool, +/- variant (a) correction)
        if theta_g is not None and tail_g is not None and np.isfinite(gjr_f[i]):
            for pv, s2_i in [('GJRf', float(gjr_f[i])),
                             ('GJRf-a', float(gjr_f[i]) * theta_g['s_a'] ** 2)]:
                if pv not in layer_cache or s2_i <= 0:
                    continue
                sigma2_cell[pv][k_ev] = s2_i
                sd = np.sqrt(s2_i)
                ent = layer_cache[pv]
                for a in ALPHA_LEVELS:
                    ak = f'{int(a*100)}%'
                    for t_ in ['Normal', 'CF']:
                        var_arrays[ak][f'{pv}+{t_}'][k_ev] = sd * ent['q'][ak][t_]
                        es_arrays[ak][f'{pv}+{t_}'][k_ev] = sd * ent['es'][ak][t_]
                if collect_specs:
                    specs[f'{pv}+Normal'][k_ev] = ('normal',)
                    specs[f'{pv}+CF'][k_ev] = ('cf', ent['S'], ent['K'])

        # K854 anchors (refit-based in-sample residual pools) with robust fits
        gk, gz = last_refit_pool(gjr_refits, gjr_ctx['z'], i)
        rk, rz = last_refit_pool(rgl_refits, rgl_ctx['z'], i)
        if gz is not None and len(gz) > MIN_POOL and np.isfinite(gjr_f[i]):
            sigma2_cell['GJR'][k_ev] = float(gjr_f[i])
            gsd = np.sqrt(gjr_f[i])
            if ('g', gk) not in anchor_cache:
                S, K = float(skew(gz)), float(kurtosis(gz, fisher=True))
                st = k854.estimate_skewt_params(gz)
                skewt_cache[gk] = st
                anchor_cache[('g', gk)] = {
                    'S': S, 'K': K,
                    'q_cf': {a: float(cf_quantile_moments(S, K, a)) for a in ALPHA_LEVELS},
                    'es_cf': {a: cf_es_z(S, K, a) for a in ALPHA_LEVELS},
                    'q_st': {a: float(k854.skewt_ppf(a, df=st['df'], xi=st['xi']))
                             for a in ALPHA_LEVELS},
                    'es_st': {a: skewt_es_z(st['df'], st['xi'], a) for a in ALPHA_LEVELS},
                }
            ac = anchor_cache[('g', gk)]
            st = skewt_cache[gk]
            for a in ALPHA_LEVELS:
                ak = f'{int(a*100)}%'
                var_arrays[ak]['GJR+Normal'][k_ev] = gsd * norm.ppf(a)
                es_arrays[ak]['GJR+Normal'][k_ev] = gsd * normal_es_z(a)
                var_arrays[ak]['GJR+CF'][k_ev] = gsd * ac['q_cf'][a]
                es_arrays[ak]['GJR+CF'][k_ev] = gsd * ac['es_cf'][a]
                var_arrays[ak]['GJR+Skewed-t'][k_ev] = gsd * ac['q_st'][a]
                es_arrays[ak]['GJR+Skewed-t'][k_ev] = gsd * ac['es_st'][a]
            if collect_specs:
                specs['GJR+Normal'][k_ev] = ('normal',)
                specs['GJR+CF'][k_ev] = ('cf', ac['S'], ac['K'])
                specs['GJR+Skewed-t'][k_ev] = ('skewt', st['df'], st['xi'])
        if rz is not None and len(rz) > MIN_POOL and np.isfinite(rgl_f[i]):
            sigma2_cell['RGL'][k_ev] = float(rgl_f[i])
            rsd = np.sqrt(rgl_f[i])
            if ('r', rk) not in anchor_cache:
                S, K = float(skew(rz)), float(kurtosis(rz, fisher=True))
                anchor_cache[('r', rk)] = {
                    'S': S, 'K': K,
                    'q_cf': {a: float(cf_quantile_moments(S, K, a)) for a in ALPHA_LEVELS},
                    'es_cf': {a: cf_es_z(S, K, a) for a in ALPHA_LEVELS},
                }
            ac = anchor_cache[('r', rk)]
            for a in ALPHA_LEVELS:
                ak = f'{int(a*100)}%'
                var_arrays[ak]['RGL+CF'][k_ev] = rsd * ac['q_cf'][a]
                es_arrays[ak]['RGL+CF'][k_ev] = rsd * ac['es_cf'][a]
            if collect_specs:
                specs['RGL+CF'][k_ev] = ('cf', ac['S'], ac['K'])

    # ---- common-sample guard ----
    incomplete = sorted({c for ak in var_arrays for c, arr in var_arrays[ak].items()
                         if not np.isfinite(arr).all()})
    if incomplete:
        if run_id == PRIMARY_RUN:
            raise RuntimeError(f'COMMON-SAMPLE VIOLATION in the GATE run: {incomplete}')
        for ak in list(var_arrays):
            for c in incomplete:
                var_arrays[ak].pop(c, None)
                es_arrays[ak].pop(c, None)
        log(f'  cells DROPPED (not estimable on the full window): {incomplete}')
    cells_unavailable = {'cells': incomplete,
                         'reason': None if not incomplete else
                         'Not estimable on every evaluation day under this run\'s windows; '
                         'dropped and declared rather than back-tested on a shorter sample.'}

    # ---- HistSim scale-equivariance (variants (a)/(c) cannot move it) ----
    equivariance = {}
    for v in ['HAR-a', 'HAR-c']:
        cn, cb = f'{v}+HistSim', 'HAR+HistSim'
        if any(cn not in var_arrays[ak] or cb not in var_arrays[ak] for ak in var_arrays):
            continue
        d = max(float(np.max(np.abs(var_arrays[ak][cn] - var_arrays[ak][cb])))
                for ak in var_arrays)
        equivariance[v] = {'max_abs_diff_vs_baseline_histsim': d, 'invariant': bool(d < 1e-10)}

    # ---- per-cell backtests: VaR trinity + ES + FZ0 ----
    results = {}
    fz_losses = {}
    for a in ALPHA_LEVELS:
        ak = f'{int(a*100)}%'
        results[ak] = {}
        fz_losses[ak] = {}
        for name, arr in var_arrays[ak].items():
            bt = backtest_cell(eval_r, arr, a)
            bt['avg_var'] = float(np.mean(arr))
            if name.endswith('+Normal'):
                bt.update(implied_c_normal(bt['n_violations'], bt['n_total'], a))
            es_arr = es_arrays[ak][name]
            sig = np.sqrt(sigma2_cell[_family(name)])
            bt['avg_es'] = float(np.nanmean(es_arr))
            bt['mcneil_frey'] = mcneil_frey_test(eval_r, arr, es_arr, sig,
                                                 seed=stable_seed(run_id, ak, name))
            fz, n_bad = fz0_loss(eval_r, arr, es_arr, a)
            fz_losses[ak][name] = fz
            bt['fz0_mean'] = float(np.nanmean(fz))
            bt['fz0_n_invalid_rows'] = n_bad
            results[ak][name] = bt

    # ---- FZ0 DM race vs the GJR+CF anchor (pairwise masks, Harvey calibre) ----
    fz_dm = {}
    for a in ALPHA_LEVELS:
        ak = f'{int(a*100)}%'
        fz_dm[ak] = {}
        if 'GJR+CF' not in fz_losses[ak]:
            continue
        anchor = fz_losses[ak]['GJR+CF']
        for name, fz in fz_losses[ak].items():
            if name == 'GJR+CF':
                continue
            fz_dm[ak][f'{name}_vs_GJR+CF'] = dm_pair(fz, anchor, name, 'GJR+CF')

    # ---- distribution-free implied-scale bootstrap (paired across cells/alphas) ----
    boot = {}
    for name in var_arrays['1%']:
        if name not in var_arrays['5%']:
            continue
        boot[name] = bootstrap_c_emp(eval_r, {'1%': var_arrays['1%'][name],
                                              '5%': var_arrays['5%'][name]}, boot_idx)

    # ---- QLIKE / DM on BOTH targets (pairwise masks) ----
    r2 = eval_r ** 2
    rv_ev = rv[eval_idx]
    models = {'HAR-RV': sigma2_cell['HAR'], 'HAR-a': sigma2_cell['HAR-a'],
              'HAR-b': sigma2_cell['HAR-b'], 'HAR-c': sigma2_cell['HAR-c'],
              'GJR': sigma2_cell['GJR'], 'RGL': sigma2_cell['RGL']}
    qlike_out, dm_out = {}, {}
    for tgt_name, tgt in [('rv_tx_aligned', rv_ev), ('r2_0050', r2)]:
        tvalid = np.isfinite(tgt) & (tgt > 0)
        qlike_out[tgt_name] = {}
        for mname, f_ in models.items():
            mvalid = tvalid & np.isfinite(f_) & (f_ > 0)
            if mvalid.sum() < 10:
                qlike_out[tgt_name][mname] = None
                continue
            qlike_out[tgt_name][mname] = {
                'qlike': float(np.mean(qlike_pointwise(tgt[mvalid], f_[mvalid]))),
                'n': int(mvalid.sum())}
        dm_out[tgt_name] = {}
        for m1, m2 in [('HAR-RV', 'GJR'), ('HAR-a', 'GJR'), ('HAR-b', 'GJR'),
                       ('HAR-c', 'GJR'), ('HAR-a', 'HAR-RV'), ('RGL', 'GJR')]:
            f1, f2 = models[m1], models[m2]
            pair_ok = tvalid & np.isfinite(f1) & (f1 > 0) & np.isfinite(f2) & (f2 > 0)
            l1 = np.full(n_eval, np.nan)
            l2 = np.full(n_eval, np.nan)
            l1[pair_ok] = qlike_pointwise(tgt[pair_ok], f1[pair_ok])
            l2[pair_ok] = qlike_pointwise(tgt[pair_ok], f2[pair_ok])
            dm_out[tgt_name][f'{m1}_vs_{m2}'] = dm_pair(l1, l2, m1, m2)

    # ---- correction-factor summary + shared-data dependence of the estimators ----
    def summ(arr, extra=None):
        if not np.isfinite(arr).any():
            return None
        d = {'mean': float(np.nanmean(arr)), 'min': float(np.nanmin(arr)),
             'max': float(np.nanmax(arr)), 'last': float(arr[-1])}
        if extra:
            d.update(extra)
        return d

    mz_scale = np.sqrt(sigma2_cell['HAR-b'] / sigma2_cell['HAR'])
    factors = {
        'HAR-a_scale_s': summ(theta_trace['s_a']),
        'HAR-c_scale_s': summ(np.sqrt(theta_trace['k_c'])),
        'HAR-b_MZ_slope_b': summ(theta_trace['mz_b']),
        'HAR-b_implied_scale': summ(mz_scale),
        'GJRf-a_scale_s_PLACEBO': summ(theta_trace['s_gjr']),
        'theta_window_obs_first_last': [int(theta_trace['n_theta'][0]),
                                        int(theta_trace['n_theta'][-1])],
        'tail_pool_obs_first_last': [int(theta_trace['n_tail_pool'][0]),
                                     int(theta_trace['n_tail_pool'][-1])],
    }
    est = np.column_stack([theta_trace['s_a'], np.sqrt(theta_trace['k_c']), mz_scale])
    okr = np.isfinite(est).all(axis=1)
    dep = None
    if okr.sum() > 30:
        cc = np.corrcoef(est[okr].T)
        dep = {'corr_s_a__s_c': round(float(cc[0, 1]), 4),
               'corr_s_a__s_mz': round(float(cc[0, 2]), 4),
               'corr_s_c__s_mz': round(float(cc[1, 2]), 4),
               'note': 'three estimators of the SAME wedge computed on shared r^2/RV data — '
                       'NOT statistically independent evidence (blocker 4)'}

    return {
        'role': role, 'theta_window': theta_window, 'tail_pool': tail_pool,
        'pool_refresh_days': refresh, 'n_eval': int(n_eval),
        'cells_unavailable': cells_unavailable,
        'var_results': results, 'fz0_dm_vs_gjr_cf': fz_dm,
        'implied_scale_bootstrap': boot,
        'qlike': qlike_out, 'dm_tests': dm_out,
        'correction_factors': factors, 'estimator_dependence': dep,
        'histsim_scale_equivariance_check': equivariance,
        '_var_arrays': var_arrays, '_es_arrays': es_arrays,
        '_sigma2_cell': sigma2_cell, '_specs': specs, '_eval_r': eval_r,
    }


# ============================================================
# Part 8 — In-sample evaluation (preamble: IS + OOS, both alphas, VaR + ES)
# ============================================================

def run_insample_eval(r, rv, common_dates, oos_start_idx):
    gjr_p, gjr_diag = fit_gjr_robust(r[:oos_start_idx], seed=SEED + 777)
    s2_gjr = k854.gjr_filter(np.ascontiguousarray(r[:oos_start_idx]),
                             gjr_p['omega'], gjr_p['alpha'], gjr_p['beta'], gjr_p['gamma'])
    har_fit = har_insample_fitted(rv, oos_start_idx)
    rgl_p, rgl_diag = fit_rgl_robust(r[:oos_start_idx], rv[:oos_start_idx], seed=SEED + 778)
    h_rgl = k854.realgarch_log_filter(r[:oos_start_idx], rv[:oos_start_idx], rgl_p)

    is_start = int(np.searchsorted(common_dates, pd.Timestamp(IS_EVAL_START)))
    cand = np.arange(is_start, oos_start_idx)
    ok = (np.isfinite(har_fit[cand]) & (har_fit[cand] > 0)
          & np.isfinite(s2_gjr[cand]) & np.isfinite(h_rgl[cand]) & np.isfinite(r[cand]))
    is_idx = cand[ok]
    n_is = len(is_idx)
    is_r = r[is_idx]

    full = np.arange(0, oos_start_idx)
    theta = estimate_theta(full, r, har_fit, rv)
    s2g_full = np.full(len(r), np.nan)
    s2g_full[:oos_start_idx] = s2_gjr
    theta_g = estimate_theta(full, r, s2g_full, rv)

    hrgl_full = np.full(len(r), np.nan)
    hrgl_full[:oos_start_idx] = h_rgl
    z_gjr = r[full][np.isfinite(s2g_full[full])] / np.sqrt(s2g_full[full][np.isfinite(s2g_full[full])])
    z_rgl_ok = np.isfinite(hrgl_full[full]) & (hrgl_full[full] > 0)
    z_rgl = r[full][z_rgl_ok] / np.sqrt(hrgl_full[full][z_rgl_ok])
    st_is = k854.estimate_skewt_params(z_gjr)

    cells = {}
    sig2 = {}
    for v in HAR_VARIANTS:
        s2 = sigma2_variant(v, har_fit, theta)
        s2_pool = sigma2_variant(v, har_fit[theta['pool_idx']], theta)
        okp = np.isfinite(s2_pool) & (s2_pool > 0)
        z_v = r[theta['pool_idx'][okp]] / np.sqrt(s2_pool[okp])
        if len(z_v) <= MIN_POOL:
            continue
        S, K = float(skew(z_v)), float(kurtosis(z_v, fisher=True))
        sig2[v] = s2[is_idx]
        cells[v] = {'z': z_v, 'S': S, 'K': K, 'layers': TAIL_LAYERS}
    placebo_specs = ([] if theta_g is None else
                     [('GJRf', 1.0), ('GJRf-a', theta_g['s_a'])])
    for pv, s_fac in placebo_specs:
        zz = (theta_g['z'] if pv == 'GJRf' else theta_g['z'] / theta_g['s_a'])
        S, K = float(skew(zz)), float(kurtosis(zz, fisher=True))
        sig2[pv] = s2g_full[is_idx] * s_fac ** 2
        cells[pv] = {'z': zz, 'S': S, 'K': K, 'layers': ['Normal', 'CF']}
    sig2['GJR'] = s2g_full[is_idx]
    cells['GJR'] = {'z': z_gjr, 'S': float(skew(z_gjr)), 'K': float(kurtosis(z_gjr, fisher=True)),
                    'layers': ['Normal', 'CF', 'Skewed-t'], 'skewt': st_is}
    sig2['RGL'] = hrgl_full[is_idx]
    cells['RGL'] = {'z': z_rgl, 'S': float(skew(z_rgl)), 'K': float(kurtosis(z_rgl, fisher=True)),
                    'layers': ['CF']}

    results = {f'{int(a*100)}%': {} for a in ALPHA_LEVELS}
    var_store = {f'{int(a*100)}%': {} for a in ALPHA_LEVELS}
    for fam, ent in cells.items():
        sd = np.sqrt(sig2[fam])
        for t_ in ent['layers']:
            cname = f'{fam}+{t_}'
            for a in ALPHA_LEVELS:
                ak = f'{int(a*100)}%'
                if t_ == 'Normal':
                    qz, ez = float(norm.ppf(a)), normal_es_z(a)
                elif t_ == 'CF':
                    qz = float(cf_quantile_moments(ent['S'], ent['K'], a))
                    ez = cf_es_z(ent['S'], ent['K'], a)
                elif t_ == 'HistSim':
                    qz = float(np.percentile(ent['z'], a * 100))
                    ez = hist_es_z(ent['z'], a)
                elif t_ == 'Skewed-t':
                    st = ent['skewt']
                    qz = float(k854.skewt_ppf(a, df=st['df'], xi=st['xi']))
                    ez = skewt_es_z(st['df'], st['xi'], a)
                var_arr = sd * qz
                es_arr = sd * ez
                bt = backtest_cell(is_r, var_arr, a)
                bt['avg_var'] = float(np.nanmean(var_arr))
                bt['avg_es'] = float(np.nanmean(es_arr))
                if t_ == 'Normal':
                    bt.update(implied_c_normal(bt['n_violations'], bt['n_total'], a))
                bt['mcneil_frey'] = mcneil_frey_test(is_r, var_arr, es_arr, sd,
                                                     seed=stable_seed('IS', ak, cname))
                fz, n_bad = fz0_loss(is_r, var_arr, es_arr, a)
                bt['fz0_mean'] = float(np.nanmean(fz))
                bt['fz0_n_invalid_rows'] = n_bad
                results[ak][cname] = bt
                var_store[ak][cname] = var_arr

    boot_idx = block_bootstrap_indices(n_is, BOOT_B, BOOT_BLOCK, SEED + 31)
    boot = {}
    for cname in var_store['1%']:
        boot[cname] = bootstrap_c_emp(is_r, {'1%': var_store['1%'][cname],
                                             '5%': var_store['5%'][cname]}, boot_idx)
    return {
        'definition': ('single fit on all pre-OOS data (models AND theta AND tail pools see '
                       'the full pre-OOS sample; that is what in-sample means), evaluated on '
                       f'{IS_EVAL_START}..{OOS_START} (includes COVID); Basel = last 250 days'),
        'n_is': int(n_is),
        'window': [str(common_dates[is_idx[0]].date()), str(common_dates[is_idx[-1]].date())],
        'gjr_fit_diag': gjr_diag, 'rgl_fit_diag': rgl_diag,
        'theta_insample': {'s_a': round(theta['s_a'], 5),
                           'k_c': round(theta['k_c'], 5),
                           'mz_b': round(theta['mz']['b'], 5) if theta['mz'] else None,
                           's_gjr_placebo': round(theta_g['s_a'], 5) if theta_g else None},
        'var_results': results, 'implied_scale_bootstrap': boot,
    }


# ============================================================
# Part 9 — Gate (pre-registered; blocker 5)
# ============================================================

def decide_gate_v2(cells, dm_aligned, dm_mismatched):
    def trinity(cell, ak):
        return bool(cells[ak][cell]['trinity_pass'])

    # leg 2 baseline pattern — EXPLICITLY checked (K1684 said it, never checked it)
    leg2_pattern = (not trinity('HAR+CF', '1%')) and trinity('GJR+CF', '1%')

    rescued = {}
    for v in ['HAR-a', 'HAR-b', 'HAR-c']:
        if any(f'{v}+{t}' not in cells['1%'] for t in TAIL_LAYERS):
            rescued[v] = {'rescued': None, 'note': 'variant not estimable in this run'}
            continue
        passing = [t for t in TAIL_LAYERS
                   if all(trinity(f'{v}+{t}', ak) for ak in ['1%', '5%'])]
        rescued[v] = {'tail_layers_passing_trinity_both_alphas': passing,
                      'rescued': bool(passing)}
    n_rescued = sum(1 for v in rescued if rescued[v]['rescued'] is True)
    n_estimable = sum(1 for v in rescued if rescued[v]['rescued'] is not None)

    aligned = dm_aligned['HAR-RV_vs_GJR']
    mismatched = dm_mismatched['HAR-RV_vs_GJR']
    t_al = aligned.get('t_stat')
    leg1_win = bool(t_al is not None and t_al < -3.0)          # Harvey calibre

    if not leg1_win:
        verdict = 'H2_REJECTED'
        why = ('leg 1 fails at the Harvey calibre: on the ALIGNED target (0050 r^2) HAR-RV '
               f'shows no Harvey-significant QLIKE win over the robust GJR (t={t_al}). '
               'Without a forecast-loss win on a common target there is no divergence to '
               'explain, whatever the tail layer does.')
    elif not leg2_pattern:
        verdict = 'H2_REJECTED'
        why = ('leg 2 baseline pattern absent under robust estimation: the K854 '
               '"HAR+CF FAIL / GJR+CF PASS" contrast does not hold at 1% on this sample, '
               'so the divergence claim has no tail-coverage leg either.')
    elif n_estimable > 0 and n_rescued == n_estimable:
        verdict = 'H2_REJECTED'
        why = 'legs 1-2 present, but every estimable scale correction rescues HAR\'s VaR.'
    elif n_rescued == 0:
        verdict = 'H2_SURVIVES'
        why = ('HAR beats GJR on the aligned target at the Harvey calibre AND still fails '
               'the trinity after every scale correction.')
    else:
        verdict = 'H2_PARTIAL'
        why = (f'HAR rescued under {n_rescued}/{n_estimable} estimable variants; the scale '
               'channel explains part but not all.')

    return {
        'verdict': verdict, 'reason': why, 'route': GATE_RULES['route'][verdict],
        'preregistered_rules': GATE_RULES,
        'leg1_qlike': {
            'aligned_target_r2_0050': dict(aligned,
                                           harvey_win_for_HAR=bool(leg1_win)),
            'mismatched_target_tx_rv': mismatched,
        },
        'leg2_tail': {
            'baseline_pattern_har_cf_fail_and_gjr_cf_pass_1pct': bool(leg2_pattern),
            'har_cf_trinity_1pct': trinity('HAR+CF', '1%'),
            'gjr_cf_trinity_1pct': trinity('GJR+CF', '1%'),
            'per_variant_rescue': rescued,
            'n_variants_rescuing_har': n_rescued,
            'n_variants_estimable': n_estimable,
            'coverage_only_kupiec_pass_both_alphas': {
                cell: bool(all(cells[ak][cell]['kupiec']['pass'] for ak in ['1%', '5%']))
                for cell in cells['1%'] if cell.startswith('HAR')
            },
        },
    }


# ============================================================
# Part 10 — Audits (lookahead, session convention, fragility v2)
# ============================================================

def verify_session_alignment(n_files=40):
    """Trade-date convention of the all-contract TX files (same finding as K1684)."""
    files = sorted(glob.glob(os.path.join(k854.DATA_DIR, 'Daily_*TX.csv')))
    files = [f for f in files if 'Daily_2023' <= os.path.basename(f) < 'Daily_2025']
    rng = np.random.default_rng(SEED)
    sample = [files[i] for i in rng.choice(len(files), size=min(n_files, len(files)),
                                           replace=False)]
    night_before, night_same, checked = 0, 0, 0
    for fp in sample:
        base = os.path.basename(fp)
        parts = base.replace('Daily_', '').replace('TX.csv', '').split('_')
        file_date = pd.Timestamp(f'{parts[0]}-{parts[1]}-{parts[2]}')
        try:
            df = pd.read_csv(fp, encoding='big5', dtype=str, low_memory=False)
        except Exception:
            continue
        trade_date = pd.to_numeric(df.iloc[:, 0], errors='coerce')
        t_int = pd.to_numeric(df.iloc[:, 3], errors='coerce')
        pm = (t_int >= 150000) & (t_int <= 235959)
        if pm.sum() == 0:
            continue
        checked += 1
        td = int(pd.Series(trade_date[pm]).mode().iloc[0])
        td = pd.Timestamp(f'{str(td)[:4]}-{str(td)[4:6]}-{str(td)[6:8]}')
        if td < file_date:
            night_before += 1
        elif td == file_date:
            night_same += 1
    verdict = 'night_precedes_day' if night_before > night_same else 'night_follows_day'
    return {'files_checked': checked,
            'evening_ticks_stamped_previous_calendar_day': night_before,
            'evening_ticks_stamped_same_calendar_day': night_same,
            'verdict': verdict}


def lookahead_perturbation_audit(rv_series, r, rv, har_level, gjr_forecasts,
                                 gjr_params_by_idx, pool_start, eval_idx, n_probe=6):
    """Multiply everything from the origin onward by 10; origin values must not move."""
    rng = np.random.default_rng(SEED)
    probes = sorted(rng.choice(eval_idx, size=min(n_probe, len(eval_idx)),
                               replace=False).tolist())
    checks = []
    for i in probes:
        pool = np.arange(pool_start, i)
        base = estimate_theta(pool, r, har_level, rv)
        r_c, rv_c, har_c = r.copy(), rv.copy(), har_level.copy()
        r_c[i:] *= 10.0
        rv_c[i:] *= 10.0
        har_c[i:] *= 10.0
        pert = estimate_theta(pool, r_c, har_c, rv_c)
        row = {'origin_index': int(i), 'origin_date': str(rv_series.index[i].date())}
        row['theta_s_a_unchanged'] = bool(base['s_a'] == pert['s_a'])
        row['theta_k_c_unchanged'] = bool(base['k_c'] == pert['k_c'])
        row['theta_mz_unchanged'] = bool(
            (base['mz'] is None and pert['mz'] is None)
            or (base['mz'] is not None and pert['mz'] is not None
                and base['mz']['a'] == pert['mz']['a']
                and base['mz']['b'] == pert['mz']['b']
                and base['mz']['smear'] == pert['mz']['smear']))
        rv_pert = rv_series.copy()
        rv_pert.iloc[i:] *= 10.0
        har_pert = k854.har_oos_forecasts(rv_pert, oos_start=OOS_START,
                                          refit_freq=REFIT_EVERY, min_train=HAR_MIN_TRAIN)
        row['har_forecast_unchanged'] = bool(har_pert.iloc[i] == har_level[i])
        p = gjr_params_by_idx[i]
        if isinstance(p, dict) and np.isfinite(gjr_forecasts[i]):
            row['gjr_forecast_unchanged'] = bool(
                k854.gjr_one_step_forecast(r_c[:i], p) == gjr_forecasts[i])
        else:
            row['gjr_forecast_unchanged'] = None
        checks.append(row)
    flat = [v for row in checks for kk, v in row.items()
            if kk.endswith('_unchanged') and v is not None]
    return {'method': 'x10 perturbation of every observation at index >= origin; origin '
                      'forecasts and correction parameters must return bit-identical',
            'probes': checks, 'n_assertions': len(flat), 'all_passed': bool(all(flat))}


def gjr_fragility_probe_v2(r, gjr_f, oos_start_idx, oos_end_idx, eval_idx):
    """K1684's 1e-6 data-revision probe re-run on the ROBUST (120-start) fit."""
    s0 = np.sqrt(gjr_f[eval_idx])
    base = {f'{int(a*100)}%': int((r[eval_idx] < s0 * norm.ppf(a)).sum())
            for a in ALPHA_LEVELS}
    counts = {f'{int(a*100)}%': [] for a in ALPHA_LEVELS}
    max_rel = 0.0
    for draw in range(FRAGILITY_DRAWS):
        rng = np.random.default_rng(SEED + draw)
        r_p = r * (1.0 + rng.normal(0, 1e-6, size=len(r)))
        f_p, _, _, _ = gjr_forecast_path_robust(r_p, oos_start_idx, oos_end_idx,
                                                seed_base=SEED)
        s1 = np.sqrt(f_p[eval_idx])
        max_rel = max(max_rel, float(np.max(np.abs(s1 - s0) / s0)))
        for a in ALPHA_LEVELS:
            counts[f'{int(a*100)}%'].append(int((r_p[eval_idx] < s1 * norm.ppf(a)).sum()))
    return {
        'perturbation': f'returns x (1 + N(0, 1e-6)), {FRAGILITY_DRAWS} seeded draws, '
                        'refit start seeds held fixed (isolates the data effect)',
        'n_draws': FRAGILITY_DRAWS,
        'sigma_change_max_pct_across_draws': round(max_rel * 100, 4),
        'gjr_normal_violations_base': base,
        'gjr_normal_violation_range': {a: [int(min(c)), int(max(c))]
                                       for a, c in counts.items()},
        'k1684_4start_reference': {'sigma_change_max_pct': 29.0277,
                                   'violation_range_5pct': [20, 21], 'violation_range_1pct': [8, 10]},
    }


# ============================================================
# Part 11 — Atomic results write (blocker 6)
# ============================================================

def write_results_atomic(obj, path):
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(k854.make_serializable(obj), f, indent=2, ensure_ascii=False)
    with open(tmp) as f:
        json.load(f)             # parse verification before the swap
    os.replace(tmp, path)


# ============================================================
# Part 12 — Figures
# ============================================================

def make_figures(primary):
    res = primary['var_results']
    boot = primary['implied_scale_bootstrap']

    # Fig 1: distribution-free implied scale across alpha, with bootstrap CIs
    fig, axes = plt.subplots(1, 2, figsize=(13.5, 5.6))
    ax = axes[0]
    groups = [
        (['HAR+Normal', 'HAR+CF', 'HAR+HistSim'], '#c0392b', 'Uncorrected HAR'),
        (['HAR-a+CF', 'HAR-b+CF', 'HAR-c+CF'], '#2980b9', 'Scale-corrected HAR'),
        (['GJR+CF', 'RGL+CF', 'GJRf-a+CF'], '#27ae60', 'Anchors / placebo'),
    ]
    for cells_, col, _ in groups:
        for j, cell in enumerate(cells_):
            b = boot.get(cell)
            if not b or 'c_emp_1pct' not in b:
                continue
            ax.plot([1, 5], [b['c_emp_1pct'], b['c_emp_5pct']], marker='o', color=col,
                    lw=1.9, alpha=0.9, ls=['-', '--', ':'][j % 3], label=cell)
            for xx, key in [(1, 'c_emp_1pct_ci95'), (5, 'c_emp_5pct_ci95')]:
                ax.plot([xx, xx], b[key], color=col, alpha=0.22, lw=7, solid_capstyle='butt')
    ax.axhline(1.0, color='k', lw=1.3)
    ax.set_xticks([1, 5])
    ax.set_xticklabels(['α = 1%', 'α = 5%'])
    ax.set_xlim(0.5, 5.6)
    ax.set_ylabel('empirical implied scale  c_emp = Q_{1-α}(r/VaR)')
    ax.set_title('Distribution-free implied scale (bands = paired block-bootstrap 95%)\n'
                 'flat & ≠1 ⇒ scale channel · sloped ⇒ tail-shape channel', fontsize=10)
    ax.legend(fontsize=7.5, ncol=2, loc='upper left')
    ax.grid(alpha=0.25)

    ax = axes[1]
    cells_ = [c for c in ['HAR+Normal', 'HAR+CF', 'HAR+HistSim', 'HAR-a+CF', 'HAR-b+CF',
                          'HAR-c+CF', 'GJR+CF', 'GJRf+CF', 'GJRf-a+CF'] if c in boot]
    dcs = [boot[c].get('delta_c') for c in cells_]
    cis = [boot[c].get('delta_c_ci95') for c in cells_]
    cols = ['#c0392b' if c.startswith('HAR+') else
            '#2980b9' if c.startswith('HAR-') else '#27ae60' for c in cells_]
    xs = np.arange(len(cells_))
    ax.bar(xs, [0 if d is None else d for d in dcs], color=cols, alpha=0.88,
           edgecolor='k', lw=0.5)
    for x, ci in zip(xs, cis):
        if ci:
            ax.plot([x, x], ci, color='k', lw=1.4)
    ax.axhline(0.0, color='k', lw=1.0)
    ax.set_xticks(xs)
    ax.set_xticklabels(cells_, rotation=32, ha='right', fontsize=8)
    ax.set_ylabel('Δc = c_emp(1%) − c_emp(5%)  (whisker = bootstrap 95% CI)')
    ax.set_title('Channel test: Δc CI excluding 0 ⇒ SHAPE; else scale/calibrated', fontsize=10)
    ax.grid(alpha=0.25, axis='y')
    fig.suptitle('K1698 Fig 1 — implied-scale channel diagnostic (distribution-free, '
                 'bootstrap-tested; replaces K1684\'s Normal mapping + 0.10 threshold)',
                 fontsize=11, y=0.99)
    fig.tight_layout()
    p = os.path.join(SCRIPT_DIR, 'fig1_implied_scale_bootstrap.png')
    fig.savefig(p, dpi=150)
    plt.close(fig)
    log(f'  -> {os.path.basename(p)}')

    # Fig 2: trinity before/after
    show = [c for c in ['HAR+Normal', 'HAR+CF', 'HAR+HistSim',
                        'HAR-a+Normal', 'HAR-a+CF', 'HAR-a+HistSim',
                        'HAR-b+CF', 'HAR-c+CF',
                        'GJR+CF', 'GJRf+CF', 'GJRf-a+CF', 'RGL+CF'] if c in res['1%']]
    basel_col = {'green': '#27ae60', 'yellow': '#f39c12', 'red': '#c0392b'}
    fig, axes = plt.subplots(1, 2, figsize=(13.5, 5.6))
    for ax, ak, a in zip(axes, ['1%', '5%'], [0.01, 0.05]):
        rates = [res[ak][c]['violation_rate'] * 100 for c in show]
        cols = [basel_col[res[ak][c]['basel_traffic_light']] for c in show]
        bars = ax.bar(np.arange(len(show)), rates, color=cols, alpha=0.9,
                      edgecolor='k', lw=0.6)
        for b_, c in zip(bars, show):
            if not res[ak][c]['trinity_pass']:
                b_.set_hatch('///')
        ax.axhline(a * 100, color='k', ls='--', lw=1.4)
        ax.set_xticks(np.arange(len(show)))
        ax.set_xticklabels(show, rotation=40, ha='right', fontsize=7.5)
        ax.set_ylabel('violation rate (%)')
        ax.set_title(f'{ak} VaR — colour = Basel light, hatched = trinity FAIL', fontsize=10)
        ax.grid(alpha=0.25, axis='y')
    fig.suptitle(f"K1698 Fig 2 — VaR trinity before vs after scale correction "
                 f"(identical {primary['n_eval']}-day sample; active-contract gap-complete "
                 f"aligned RV; robust GJR)", fontsize=11, y=0.99)
    fig.tight_layout()
    p = os.path.join(SCRIPT_DIR, 'fig2_trinity_before_after.png')
    fig.savefig(p, dpi=150)
    plt.close(fig)
    log(f'  -> {os.path.basename(p)}')

    # Fig 3: correction factors + placebo
    f = primary['correction_factors']
    names = ['HAR-a_scale_s', 'HAR-b_implied_scale', 'HAR-c_scale_s', 'GJRf-a_scale_s_PLACEBO']
    labels = ['(a) expanding std(z)', '(b) Mincer-Zarnowitz', '(c) Hansen-Lunde',
              'PLACEBO\nsame fix on GJR']
    cols = ['#2980b9', '#8e44ad', '#16a085', '#7f8c8d']
    keep = [j for j, n_ in enumerate(names) if f.get(n_)]
    names = [names[j] for j in keep]
    labels = [labels[j] for j in keep]
    cols = [cols[j] for j in keep]
    fig, ax = plt.subplots(figsize=(10.5, 5))
    xs = np.arange(len(names))
    means = [f[n]['mean'] for n in names]
    yerr = [[f[n]['mean'] - f[n]['min'] for n in names],
            [f[n]['max'] - f[n]['mean'] for n in names]]
    ax.bar(xs, means, color=cols, alpha=0.88, edgecolor='k', lw=0.6)
    ax.errorbar(xs, means, yerr=yerr, fmt='none', ecolor='k', capsize=5, lw=1.2)
    ax.axhline(1.0, color='k', ls='--', lw=1.4)
    for x, m in zip(xs, means):
        ax.text(x, m + 0.03, f'{m:.3f}', ha='center', fontsize=10, fontweight='bold')
    ax.set_xticks(xs)
    ax.set_xticklabels(labels, fontsize=9)
    ax.set_ylabel('scale factor s applied to σ (bar = OOS mean, whisker = min/max)')
    ax.set_title('K1698 Fig 3 — correction factors; the three estimators share the same '
                 'r²/RV data (NOT independent); placebo shown at identical calibre', fontsize=10)
    ax.grid(alpha=0.25, axis='y')
    fig.tight_layout()
    p = os.path.join(SCRIPT_DIR, 'fig3_scale_factors.png')
    fig.savefig(p, dpi=150)
    plt.close(fig)
    log(f'  -> {os.path.basename(p)}')


# ============================================================
# Part 13 — Main
# ============================================================

def main():
    t0 = time.time()
    log('=' * 78)
    log('K1698 — FTD E1 v2: scale re-calibration gating (compliant rerun of K1684)')
    log('=' * 78)

    log('\n[0] TAIFEX trade-date convention (all-contract TX files)')
    session = verify_session_alignment()
    log(f"  files={session['files_checked']}  verdict={session['verdict']}")

    log('\n[1] Aligned RV (active contract, gap-complete, 13:30 window)')
    rv_df, boundary = load_rv_aligned()
    audit_path = os.path.join(DATA_DIR, 'rv_boundary_audit.json')
    if boundary is not None:
        rv_boundary_audit = rv_window_boundary_audit(boundary)
        with open(audit_path, 'w') as fh:
            json.dump(k854.make_serializable(rv_boundary_audit), fh, indent=2)
    else:
        with open(audit_path) as fh:
            rv_boundary_audit = json.load(fh)
    log(f"  boundary audit: {rv_boundary_audit['n_days_checked']} days, "
        f"all_passed={rv_boundary_audit['all_passed']}")
    if not rv_boundary_audit['all_passed']:
        raise RuntimeError('RV WINDOW BOUNDARY AUDIT FAILED')

    rv_old_df = load_rv_old()
    etf = load_etf()
    _, clean_returns = clean_tw50_data(etf)
    etf_returns = clean_returns.dropna()
    etf_returns.index = pd.to_datetime(etf_returns.index).tz_localize(None)

    rv_new_s = rv_df['rv_aligned'].dropna()
    rv_old_s = rv_old_df['rv_total'].dropna()
    common_dates = (rv_new_s.index.intersection(rv_old_s.index)
                    .intersection(etf_returns.index).sort_values())
    rv_new_al = rv_new_s.loc[common_dates]
    rv_old_al = rv_old_s.loc[common_dates]
    ret_al = etf_returns.loc[common_dates]
    r = ret_al.values.astype(float)
    rv_new = rv_new_al.values.astype(float)
    rv_old = rv_old_al.values.astype(float)
    n = len(common_dates)
    log(f'  common days (new RV ∩ old RV ∩ ETF) = {n}')

    both = np.isfinite(rv_new) & np.isfinite(rv_old)
    rv_construction = {
        'method': 'per-day max-volume active TX contract; ONE continuous 5-min path over '
                  '(13:30(D-1), 13:30(D)] incl. day-tail, 13:45->15:00 gap, PM->AM night, '
                  '05:00->08:45 gap; no cross-contract returns',
        'n_days': int(len(rv_new_s)),
        'n_roll_days': int(rv_df['rolled'].sum()),
        'n_anchor_missing': int((~rv_df['anchor_ok']).sum()),
        'mean_n_returns_per_day': float(rv_df['n_returns'].mean()),
        'boundary_audit': {k: v for k, v in rv_boundary_audit.items() if k != 'checks'},
        'old_vs_new': {
            'corr': round(float(np.corrcoef(rv_new[both], rv_old[both])[0, 1]), 4),
            'mean_ratio_new_over_old': round(float(np.mean(rv_new[both] / rv_old[both])), 4),
            'note': 'old = K854 TX1 trade-date-convention RV (separate session sums, no '
                    'boundary jumps); new = aligned active-contract gap-complete RV',
        },
    }
    log(f"  new-vs-old RV: corr={rv_construction['old_vs_new']['corr']}, "
        f"mean ratio={rv_construction['old_vs_new']['mean_ratio_new_over_old']}")

    oos_start_idx = int(np.searchsorted(common_dates, pd.Timestamp(OOS_START)))
    oos_end_idx = int(np.searchsorted(common_dates, pd.Timestamp(OOS_END), side='right'))
    burnin_idx = int(np.searchsorted(common_dates, pd.Timestamp(BURNIN_START)))

    log('\n[2] HAR-RV forecasts (new + old RV; OOS pass + burn-in pass)')
    def har_pass(rv_series, start):
        return k854.har_oos_forecasts(rv_series, oos_start=start, refit_freq=REFIT_EVERY,
                                      min_train=HAR_MIN_TRAIN).values.astype(float)
    har_new = har_pass(rv_new_al, OOS_START)
    har_new_burn = har_pass(rv_new_al, BURNIN_START)
    har_old = har_pass(rv_old_al, OOS_START)
    har_old_burn = har_pass(rv_old_al, BURNIN_START)
    har_new_pool = np.where(np.arange(n) < oos_start_idx, har_new_burn, har_new)
    har_old_pool = np.where(np.arange(n) < oos_start_idx, har_old_burn, har_old)
    log(f'  new: {int(np.isfinite(har_new).sum())} OOS | old: {int(np.isfinite(har_old).sum())} OOS')

    log(f'\n[3] GJR-GARCH robust ({GJR_STARTS} starts/refit) + RealGARCH-Log robust')
    gjr_f, gjr_z, gjr_params_by_idx, gjr_diags = gjr_forecast_path_robust(
        r, oos_start_idx, oos_end_idx, seed_base=SEED)
    gjr_burn_f, _, _, _ = gjr_forecast_path_robust(r, burnin_idx, oos_end_idx,
                                                   seed_base=SEED + 50000)
    gjr_pool_burnin = np.where(np.arange(n) < oos_start_idx, gjr_burn_f, gjr_f)
    log(f'  GJR: {len(gjr_diags)} refits | basins/refit: '
        f'{[d["n_basins"] for d in gjr_diags]} | share best basin: '
        f'{[d["share_in_best_basin"] for d in gjr_diags]}')

    rgl_new_f, rgl_new_z, rgl_new_diags = rgl_forecast_path(
        r, rv_new, oos_start_idx, oos_end_idx, seed_base=SEED + 100)
    rgl_old_f, rgl_old_z, rgl_old_diags = rgl_forecast_path(
        r, rv_old, oos_start_idx, oos_end_idx, seed_base=SEED + 200)
    log(f'  RGL: new {int(np.isfinite(rgl_new_f).sum())} | old {int(np.isfinite(rgl_old_f).sum())} forecasts')

    log('\n[4] Evaluation sample (common across new-RV and old-RV pipelines)')
    cand = np.arange(oos_start_idx, oos_end_idx)
    pool_sizes = np.array([int(np.sum(np.isfinite(har_new[oos_start_idx:i])
                                      & np.isfinite(r[oos_start_idx:i]))) for i in cand])
    eval_idx = cand[np.isfinite(har_new[cand]) & np.isfinite(har_old[cand])
                    & (pool_sizes > MIN_POOL)
                    & np.isfinite(gjr_f[cand]) & np.isfinite(rgl_new_f[cand])
                    & np.isfinite(rgl_old_f[cand])]
    n_eval = len(eval_idx)
    eval_dates = common_dates[eval_idx]
    eval_r = r[eval_idx]
    log(f'  n={n_eval}  ({eval_dates[0].date()} ~ {eval_dates[-1].date()})')

    oos_stats = {
        'n': int(n_eval), 'start': str(eval_dates[0].date()), 'end': str(eval_dates[-1].date()),
        'mean': float(np.mean(eval_r)), 'std': float(np.std(eval_r)),
        'skewness': float(skew(eval_r)), 'kurtosis': float(kurtosis(eval_r, fisher=True)),
        'min': float(np.min(eval_r)), 'max': float(np.max(eval_r)),
    }

    log('\n[5] Lookahead perturbation audit')
    audit = lookahead_perturbation_audit(rv_new_al, r, rv_new, har_new, gjr_f,
                                         gjr_params_by_idx, oos_start_idx, eval_idx)
    log(f"  {audit['n_assertions']} assertions | all_passed={audit['all_passed']}")
    if not audit['all_passed']:
        raise RuntimeError('LOOKAHEAD AUDIT FAILED — refusing to report results')

    log('\n[5b] GJR fragility probe v2 (robust fit under 1e-6 data revision)')
    fragility = gjr_fragility_probe_v2(r, gjr_f, oos_start_idx, oos_end_idx, eval_idx)
    log(f"  sigma max drift {fragility['sigma_change_max_pct_across_draws']:.4f}% "
        f"(K1684 4-start: 29.03%) | violations 5%: "
        f"{fragility['gjr_normal_violation_range']['5%']}")

    boot_idx = block_bootstrap_indices(n_eval, BOOT_B, BOOT_BLOCK, SEED + 7)
    gjr_ctx = {'z': gjr_z}
    stacks = {
        'new': {'har_level': har_new, 'har_pool_burnin': har_new_pool,
                'gjr_f': gjr_f, 'gjr_pool_burnin': gjr_pool_burnin, 'rgl_f': rgl_new_f},
        'old': {'har_level': har_old, 'har_pool_burnin': har_old_pool,
                'gjr_f': gjr_f, 'gjr_pool_burnin': gjr_pool_burnin, 'rgl_f': rgl_old_f},
    }

    all_runs = {}
    for run_id, theta_window, tail_pool, refresh, role in RUNS:
        log(f"\n[6] Run '{run_id}' — {role[:80]}")
        out = run_var_es_eval(run_id, theta_window, tail_pool, refresh, role,
                              stacks['new'], r, rv_new, common_dates, eval_idx,
                              oos_start_idx, burnin_idx, gjr_ctx, {'z': rgl_new_z},
                              boot_idx, collect_specs=(run_id == PRIMARY_RUN))
        all_runs[run_id] = out
        for ak in ['1%', '5%']:
            log(f'  --- {ak} VaR ({run_id}, n={n_eval}) ---')
            log(f"  {'Cell':17s} {'Viol':>4s} {'Rate':>7s} {'Kupiec':>7s} {'Basel':>7s} "
                f"{'Trinity':>8s} {'c_emp':>6s} {'FZ0':>8s}")
            for name, bt in out['var_results'][ak].items():
                ce = bt['implied_c_empirical']
                log(f"  {name:17s} {bt['n_violations']:4d} {bt['violation_rate']*100:6.2f}% "
                    f"{bt['kupiec']['p_value']:7.3f} {bt['basel_traffic_light']:>7s} "
                    f"{str(bt['trinity_pass']):>8s} "
                    f"{('n/a' if ce is None else f'{ce:.3f}'):>6s} {bt['fz0_mean']:8.4f}")

    log("\n[6b] Bridge run 'bridge_old_rv' — primary settings on the OLD (K854) RV")
    bridge = run_var_es_eval('bridge_old_rv', 'long', 'oos_only', REFIT_EVERY,
                             'DIAGNOSTIC: isolates the effect of the RV rebuild — identical '
                             'settings to primary but K854 TX1 trade-date RV everywhere',
                             stacks['old'], r, rv_old, common_dates, eval_idx,
                             oos_start_idx, burnin_idx, gjr_ctx, {'z': rgl_old_z},
                             boot_idx, collect_specs=False)
    all_runs['bridge_old_rv'] = bridge

    log('\n[7] Acerbi-Szekely Z2 (primary run, simulation p-values)')
    prim = all_runs[PRIMARY_RUN]
    as_z2 = {}
    for a in ALPHA_LEVELS:
        ak = f'{int(a*100)}%'
        as_z2[ak] = {}
        for name in prim['var_results'][ak]:
            sig = np.sqrt(prim['_sigma2_cell'][_family(name)])
            spec_list = prim['_specs'][name]
            if any(s is None for s in spec_list):
                as_z2[ak][name] = {'note': 'spec missing on some days'}
                continue
            as_z2[ak][name] = acerbi_szekely_z2(
                eval_r, prim['_var_arrays'][ak][name], prim['_es_arrays'][ak][name],
                sig, a, spec_list, seed=stable_seed('AS', ak, name))
    for ak in as_z2:
        fails = [c for c, v in as_z2[ak].items() if v.get('pass') is False]
        log(f'  {ak}: AS-Z2 FAIL cells: {fails if fails else "none"}')

    log('\n[8] In-sample evaluation (single pre-OOS fit; window includes COVID)')
    insample = run_insample_eval(r, rv_new, common_dates, oos_start_idx)
    log(f"  n_IS={insample['n_is']} ({insample['window'][0]} ~ {insample['window'][1]})")
    for ak in ['1%', '5%']:
        rowfail = [c for c, bt in insample['var_results'][ak].items()
                   if not bt['trinity_pass']]
        log(f'  IS {ak} trinity FAIL: {rowfail}')

    log('\n[9] K854 replication bridge (old-RV run vs K854 published counts)')
    k854_json = os.path.join(PROJECT_ROOT, 'experiments', 'k854',
                             'k854_common_sample_var_results.json')
    replication = {'checked': False}
    if os.path.exists(k854_json):
        with open(k854_json) as f:
            ref_all = json.load(f)
        rows = []
        for ak in ['1%', '5%']:
            for name, ref in ref_all['var_results'][ak].items():
                if name not in bridge['var_results'][ak]:
                    continue
                got = bridge['var_results'][ak][name]
                rows.append({'alpha': ak, 'cell': name,
                             'k854_violations': ref['n_violations'],
                             'k1698_bridge_violations': got['n_violations'],
                             'n_k854': ref['n_total'], 'n_k1698': got['n_total'],
                             'match': bool(ref['n_violations'] == got['n_violations'])})
        n_match = sum(x['match'] for x in rows)
        replication = {
            'checked': True, 'n_cells': len(rows), 'n_matching': n_match,
            'match_rate': round(n_match / len(rows), 4) if rows else None, 'rows': rows,
            'note': 'Bridge run = old TX1 RV + ROBUST (120-start) GJR/RGL on the common '
                    'evaluation sample. Differences on GJR/RGL cells quantify what the '
                    '4-start MLE instability was worth; HAR-cell differences (if any) come '
                    'from the common-sample intersection with the new RV calendar.',
        }
        log(f'  {n_match}/{len(rows)} K854 cells match the robust bridge')

    log('\n[10] Figures')
    make_figures(prim)

    gate = decide_gate_v2(prim['var_results'], prim['dm_tests']['r2_0050'],
                          prim['dm_tests']['rv_tx_aligned'])

    def strip_private(run):
        return {k: v for k, v in run.items() if not k.startswith('_')}

    out = {
        'experiment_id': 'K1698',
        'title': 'K1698: FTD E1 v2 — scale re-calibration gating (compliant rerun of K1684)',
        'question': 'Is the K850/K854 QLIKE-vs-VaR divergence an artifact of the '
                    'variance-target mismatch, once every K1684 review blocker is fixed?',
        'proposer': 'Codex review of K1684 (BLOCKED 2026-07-12) + Fable deep review §5.1 E1',
        'parent_experiments': ['k850', 'k854', 'k1684'],
        'blockers_addressed': 'experiments/k1684/CODEX_REVIEW_BLOCKED.md — see README map',
        'asset': '0050.TW close-to-close (dividend-adjusted)',
        'rv_source': 'TAIFEX all-contract TX tick -> active-contract, gap-complete, '
                     '13:30-aligned 5-min RV',
        'oos_period': f"{oos_stats['start']} to {oos_stats['end']}",
        'n_oos': oos_stats['n'], 'refit_every': REFIT_EVERY, 'alpha_levels': ALPHA_LEVELS,
        'seed': SEED, 'gjr_multistart': GJR_STARTS, 'rgl_multistart': RGL_STARTS,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'elapsed_sec': round(time.time() - t0, 1),

        'GATE_VERDICT': gate['verdict'],
        'GATE_REASON': gate['reason'],
        'GATE_ROUTE': gate['route'],
        'gate': gate,
        'gate_rules_preregistered': GATE_RULES,

        'session_alignment_check': session,
        'rv_construction': rv_construction,
        'oos_stats': oos_stats,
        'lookahead_audit': audit,
        'gjr_robust_estimation': {'per_refit_diagnostics': gjr_diags,
                                  'fragility_probe_v2': fragility},
        'rgl_fit_diagnostics': {'new_rv': rgl_new_diags, 'old_rv': rgl_old_diags},
        'k854_replication_bridge': replication,
        'runs': {k: strip_private(v) for k, v in all_runs.items()},
        'acerbi_szekely_z2_primary': as_z2,
        'insample': insample,

        'basel_caliber': {
            '1pct': 'STANDARD Basel 250-day count rule (green <=4, yellow 5-9, red >=10) on '
                    'the last 250 days of the OOS window.',
            '5pct': 'CUSTOM alpha-scaled extension (green <=20, yellow <=45) — NOT canonical '
                    'Basel (defined at 1% only). Inherited from K854 and flagged as custom.',
        },
        'limitations': [
            f'n = {n_eval} < the >=500 house rule at the OOS stage; ~4.5 expected violations '
            'at 1% mean low Kupiec power and single-violation Basel flips. Exact CP bands and '
            'bootstrap CIs are reported everywhere. The IS window (n~1000, includes COVID) '
            'partially compensates but is in-sample by construction.',
            'One market (0050.TW), one calm OOS regime (2023-2024). External validity of the '
            'scale channel needs E2 (SPY) / E5 (third market).',
            'The three theta estimators share the same r^2/RV data — reported as three '
            'estimators of one wedge, not independent evidence.',
            'The 5% Basel light is a custom extension, not a regulatory standard.',
            'CF expected shortfall integrates the (possibly non-monotone) Cornish-Fisher '
            'quantile polynomial; FZ0 rows with es >= var are dropped and counted.',
            'Returns are simple pct_change on adjusted closes; RV uses log returns '
            '(second-order difference at daily frequency).',
            'Skewed-t anchor tail fit keeps K854\'s single-start estimator (2 params, '
            'bounded), unlike the >=100-start GJR/RGL variance MLEs.',
        ],
        'references': [
            'Hansen & Lunde (2005, JAE 20) — realized-to-c2c scaling',
            'Mincer & Zarnowitz (1969) — forecast efficiency regression',
            'Duan (1983, JASA 78) — smearing retransformation',
            'Corsi (2009, JFEC 7) — HAR-RV',
            'Patton (2011, J Econometrics 160) — proxy-robust loss',
            'Kupiec (1995); Christoffersen (1998) — VaR coverage tests',
            'McNeil & Frey (2000, J Empirical Finance 7) — ES exceedance residual test',
            'Acerbi & Szekely (2014, Risk) — direct ES backtests (Z2)',
            'Fissler & Ziegel (2016, Ann. Statist. 44) — joint VaR-ES elicitability (FZ0)',
            'Harvey, Liu & Zhu (2016, RFS 29) — |t| > 3 calibre',
            'Gonzalez-Rivera, Lee & Mishra (2004, IJF 20); Bams et al. (2017, IJF 33)',
        ],
    }
    write_results_atomic(out, RESULTS_PATH)

    log('\n' + '=' * 78)
    log(f"GATE VERDICT : {gate['verdict']}")
    log(f"REASON       : {gate['reason']}")
    log(f"ROUTE        : {gate['route']}")
    log('=' * 78)
    log(f'-> {RESULTS_PATH}')
    log(f'elapsed {time.time() - t0:.1f}s')
    return out


if __name__ == '__main__':
    main()
