"""Reconstruct k1135_results.json from run.log when SIGPIPE interrupted stdout."""
import re
import json
import os
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(SCRIPT_DIR, 'run.log')

with open(LOG) as f:
    log = f.read()

# Extract blocks per ticker
# We have: USO (treatment), UNG (control), GLD (treatment), SLV (treatment)
tickers_order = ['USO', 'UNG', 'GLD', 'SLV']
groups = {'USO': 'treatment', 'UNG': 'control', 'GLD': 'treatment', 'SLV': 'treatment'}
skews = {'USO': -0.578, 'UNG': 0.103, 'GLD': -0.310, 'SLV': -1.064}
kurts = {'USO': 9.62, 'UNG': 3.23, 'GLD': 6.75, 'SLV': 13.02}

# IS diag lines: "IS diag: ν̂_M1=7.89, ν̂_M2=7.86, λ̂_M2=-0.050"
is_diag_re = re.compile(r'IS diag: ν̂_M1=(\-?\d+\.\d+), ν̂_M2=(\-?\d+\.\d+), λ̂_M2=([+\-]\d+\.\d+)')
is_diags = [(float(a), float(b), float(c)) for a, b, c in is_diag_re.findall(log)]

# QLIKE per model: "    M0 (GARCH-N): QLIKE=1.412237, rho=0.266"
qlike_re = re.compile(r'(M0|M1|M2) \((GARCH-N|GAS-t \(sym\)|GAS-skewt)\): QLIKE=(\d+\.\d+), rho=(\-?\d+\.\d+)')
# DM lines: "    DM-HLN M2_vs_M0: t=-1.995, p=4.623e-02, rel_impr=-1.79%"
dm_re = re.compile(r'DM-HLN (M1_vs_M0|M2_vs_M0|M2_vs_M1): t=([+\-]?\d+\.\d+), p=([\d.eE+\-]+), rel_impr=([+\-]\d+\.\d+)%')
# VaR: "    M0 @ 1%: viol=1.52% (exp 1%), Kupiec_p=0.053, CC_p=0.023, DQ_p=0.007"
var_re = re.compile(r'(M0|M1|M2) @ (1|5)%: viol=(\d+\.\d+)% \(exp [15]%\), Kupiec_p=(\d+\.\d+), CC_p=(\d+\.\d+), DQ_p=(\d+\.\d+)')
# ES: "    M0 @ 1%: Z1=+2.765 (p=0.006), Z2=+2.199 (p=0.028)"
es_re = re.compile(r'(M0|M1|M2) @ (1|5)%: Z1=([+\-]\d+\.\d+) \(p=(\d+\.\d+)\), Z2=([+\-]\d+\.\d+) \(p=(\d+\.\d+)\)')
# BH: "  USO: DM_p=0.0462, BH_p=0.1849"
bh_re = re.compile(r'([A-Z]+): DM_p=(\d+\.\d+), BH_p=(\d+\.\d+)')

# Split log by ticker processing blocks
parts = re.split(r'={60}\n  Processing: ([A-Z]+) \([a-z]+\)\n={60}\n', log)
# parts = ['header', 'USO', 'block_USO', 'UNG', 'block_UNG', ...]
ticker_blocks = {}
for i in range(1, len(parts), 2):
    tk = parts[i]
    block = parts[i+1]
    ticker_blocks[tk] = block

all_results = {}
for tk in tickers_order:
    block = ticker_blocks[tk]
    # n_oos: "  OOS: 2020-01-02 ~ 2026-04-10 (1576 obs)"
    m_oos = re.search(r'OOS: (\S+) ~ (\S+) \((\d+) obs\)', block)
    oos_start = m_oos.group(1)
    oos_end = m_oos.group(2)
    n_oos = int(m_oos.group(3))
    # IS diag
    m_is = is_diag_re.search(block)
    nu_m1 = float(m_is.group(1))
    nu_m2 = float(m_is.group(2))
    lam_m2 = float(m_is.group(3))

    # QLIKE
    qlikes = {}
    for m, label, q, rho in qlike_re.findall(block):
        qlikes[m] = {'QLIKE': float(q), 'Spearman_rho': float(rho), 'Spearman_p': None}
    # DM tests
    dms = {}
    for cmp, t, p, rel in dm_re.findall(block):
        # Determine which model won
        better = cmp.split('_vs_')[0] if float(t) > 0 else cmp.split('_vs_')[1]
        dms[cmp] = {
            'DM_HLN_t': float(t),
            'DM_HLN_p': float(p),
            'n_used': n_oos,
            'QLIKE_rel_improvement_pct': float(rel),
            'better': better,
        }
    # VaR backtests
    var_bt = {'alpha_0.01': {}, 'alpha_0.05': {}}
    for m, a, viol, kup, cc, dq in var_re.findall(block):
        alpha_lvl = 0.01 if a == '1' else 0.05
        vr = float(viol) / 100
        kup_p = float(kup)
        cc_p = float(cc)
        dq_p = float(dq)
        n_viols = int(round(vr * n_oos))
        var_bt[f'alpha_{alpha_lvl}'][m] = {
            'violation_rate': vr,
            'n_violations': n_viols,
            'expected_violations': alpha_lvl * n_oos,
            'Kupiec_LR': None,
            'Kupiec_p': kup_p,
            'Christoffersen_CC_LR': None,
            'Christoffersen_CC_p': cc_p,
            'DQ_stat': None,
            'DQ_p': dq_p,
            'Trinity_PASS': bool(kup_p > 0.05 and cc_p > 0.05 and dq_p > 0.05),
        }
    # ES backtests
    es_bt = {'alpha_0.01': {}, 'alpha_0.05': {}}
    for m, a, z1, p1, z2, p2 in es_re.findall(block):
        alpha_lvl = 0.01 if a == '1' else 0.05
        es_bt[f'alpha_{alpha_lvl}'][m] = {
            'Z1': float(z1),
            'Z1_p': float(p1),
            'Z1_PASS': bool(float(p1) > 0.05),
            'Z2': float(z2),
            'Z2_p': float(p2),
            'Z2_PASS': bool(float(p2) > 0.05),
            'n_violations_used': None,
        }

    all_results[tk] = {
        'n_oos': n_oos,
        'oos_start': oos_start,
        'oos_end': oos_end,
        'group': groups[tk],
        'full_skew': skews[tk],
        'full_kurt': kurts[tk],
        'is_diagnostic': {
            'nu_M1_sym': nu_m1,
            'nu_M2_skewt': nu_m2,
            'lam_M2_skewt': lam_m2,
        },
        'model_metrics': qlikes,
        'dm_tests': dms,
        'var_backtests': var_bt,
        'es_backtests': es_bt,
    }

# BH from log
for tk, dm_p, bh_p in bh_re.findall(log):
    if tk in all_results:
        all_results[tk]['dm_tests']['M2_vs_M0']['BH_p'] = float(bh_p)

# Aggregate hypothesis counts
h1_pass_count = sum(1 for t in tickers_order
                    if all_results[t]['dm_tests']['M2_vs_M0']['DM_HLN_t'] > 2
                    and all_results[t]['dm_tests']['M2_vs_M0']['BH_p'] < 0.05)
h2_pass_1 = sum(1 for t in tickers_order
                if all_results[t]['var_backtests']['alpha_0.01']['M2']['Trinity_PASS'])
h2_pass_5 = sum(1 for t in tickers_order
                if all_results[t]['var_backtests']['alpha_0.05']['M2']['Trinity_PASS'])
h3_pass_1 = sum(1 for t in tickers_order
                if all_results[t]['es_backtests']['alpha_0.01']['M2']['Z1_PASS']
                and all_results[t]['es_backtests']['alpha_0.01']['M2']['Z2_PASS'])
h3_pass_5 = sum(1 for t in tickers_order
                if all_results[t]['es_backtests']['alpha_0.05']['M2']['Z1_PASS']
                and all_results[t]['es_backtests']['alpha_0.05']['M2']['Z2_PASS'])

h1_PASS = h1_pass_count >= 2
h2_PASS = max(h2_pass_1, h2_pass_5) >= 2
h3_PASS = max(h3_pass_1, h3_pass_5) >= 2

if h1_PASS and h2_PASS and h3_PASS:
    SCENARIO, desc = 'A', 'Skew-t PASS on vol AND tail'
elif not h1_PASS and h2_PASS and h3_PASS:
    SCENARIO, desc = 'B', 'Only VaR/ES improved, QLIKE NULL'
elif h1_PASS and not (h2_PASS and h3_PASS):
    SCENARIO, desc = 'C', 'Vol only, tail NULL'
else:
    SCENARIO, desc = 'D', 'Skew-t FAIL everywhere'

results_output = {
    'experiment_id': 'K1135',
    'title': 'Skew-t GAS on negatively skewed commodities',
    'description': ('Test whether Hansen (1994) skew-t GAS recovers VaR/ES '
                    'performance on commodities (USO/UNG treatment; GLD/SLV '
                    'controls) where K1129 symmetric-t was NULL. Completes Paper 4 '
                    'Channel 3 "GAS family" narrative block.'),
    'methodology': {
        'models': ['M0 GARCH-N', 'M1 symmetric Student-t GAS (K1129 reference)',
                   'M2 Hansen skew-t GAS (static lambda)'],
        'assets': tickers_order,
        'is_start': '2010-01-01',
        'oos_start': '2020-01-01',
        'window': 1500,
        'refit_every': 63,
        'evaluation_target': 'r² for QLIKE (Patton 2011); VaR/ES on returns',
        'hypotheses': {
            'H1': 'QLIKE DM-HLN M2 vs M0',
            'H2': 'VaR 1%&5% Kupiec + Christoffersen CC (joint uc+ind) + Engle-Manganelli DQ',
            'H3': 'ES 1%&5% Acerbi-Szekely (2014) Z1 + Z2 joint PASS',
        },
        'multiple_testing': 'Benjamini-Hochberg FDR across 4 commodities for H1',
    },
    'data_source': 'yfinance',
    'seed': 42,
    'references': [
        'Creal, Koopman, Lucas (2013) JASA 108(501) — GAS framework',
        'Hansen (1994) IER 35(3):705-730 — skew-t density',
        'Gonzalez-Rivera et al (2014) IJF 30(3):529-550 — time-varying skew/kurt',
        'Patton (2011) J Econometrics 160 — QLIKE proxy-robust',
        'Harvey-Leybourne-Newbold (1997) IJF 13 — DM small-sample correction',
        'Kupiec (1995); Christoffersen (1998); Engle-Manganelli (2004) JBES 22',
        'Acerbi, Szekely (2014) Risk — ES backtest',
        'Benjamini-Hochberg (1995) JRSS B 57 — FDR control',
    ],
    'prior_experiments': {
        'K1129': 'commodity symmetric GAS-t → NULL on all 4 assets',
        'K1138': 'equity GAS-t → HARMFUL (SPY DM t=-3.27, QQQ t=-2.81)',
        'K1143': 'equity static skew-t → did not rescue harm; architectural incompat',
    },
    'results': all_results,
    'verdict': {
        'scenario': SCENARIO,
        'description': desc,
        'H1_pass_count': h1_pass_count,
        'H2_pass_count_1pct': h2_pass_1,
        'H2_pass_count_5pct': h2_pass_5,
        'H3_pass_count_1pct': h3_pass_1,
        'H3_pass_count_5pct': h3_pass_5,
        'paper4_channel3_implication': {
            'A': 'Commodity-specific subsection: skew-t captures commodity downside',
            'B': 'Commodity-specific subsection: skew-t for tail risk only',
            'C': 'Narrative ambiguous — partial fix',
            'D': 'Paper 4 Channel 3 narrative "GAS-t universally inappropriate" complete',
        }[SCENARIO],
    },
    'charts': ['commodity_skew_vs_gauss.png', 'var_es_backtest.png'],
    'created_at': datetime.now(timezone.utc).isoformat(),
    'note': ('Reconstructed from run.log because the original run was piped to '
             '`head -200` which caused SIGPIPE termination of the Python stdout '
             'writer before json.dump could write the results file. All numbers '
             'here are from the Python-printed log — not regenerated. Charts '
             '(commodity_skew_vs_gauss.png, var_es_backtest.png) were saved '
             'before the pipe closed. Full re-run is reproducible via seed=42.'),
}

out_path = os.path.join(SCRIPT_DIR, 'k1135_results.json')
with open(out_path, 'w') as f:
    json.dump(results_output, f, indent=2, default=str)
print(f'Written: {out_path}')
print(f'Verdict: Scenario {SCENARIO} — {desc}')
print(f'  H1: {h1_pass_count}/4  H2@1%: {h2_pass_1}/4  H2@5%: {h2_pass_5}/4  '
      f'H3@1%: {h3_pass_1}/4  H3@5%: {h3_pass_5}/4')
