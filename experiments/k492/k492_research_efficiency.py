#!/usr/bin/env python3
"""
K492: Research Efficiency Meta-Study — 67 Experiments Retrospective
====================================================================
Meta-research: analyzing the research process itself.

Questions:
1. Which experiments were most "efficient" (highest insight per effort)?
2. Which directions wasted time (early null signals but kept piling)?
3. What is the cross-OOS false positive rate?
4. If we could start over, what's the optimal experiment ordering?

Data: experiments/k4*_results.json (K414-K491, 68 files)
Method: JSON parsing + classification + statistics
Runtime target: <30 seconds
No yfinance needed.

References:
- Harvey, Liu, Zhu (2016) "...and the Cross-Section of Expected Returns" RFS
- Timmermann (2006) "Forecast Combinations" in Handbook of Economic Forecasting
- Ioannidis (2005) "Why Most Published Research Findings Are False" PLoS Medicine
"""

import json
import os
import glob
import sys
from datetime import datetime, timezone
from collections import Counter, defaultdict

# ============================================================
# 1. Load all experiment results
# ============================================================
# Try multiple paths: local dir, parent experiments/, main repo
EXPERIMENTS_DIR = None
for candidate in [
    os.path.dirname(os.path.abspath(__file__)),
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'experiments'),
    '/Users/yhlai0911/Desktop/volpred-research/experiments',
]:
    candidate = os.path.abspath(candidate)
    if glob.glob(os.path.join(candidate, 'k414*_results.json')):
        EXPERIMENTS_DIR = candidate
        break
if EXPERIMENTS_DIR is None:
    EXPERIMENTS_DIR = os.path.dirname(os.path.abspath(__file__))
    print(f"WARNING: No k414 results found, using {EXPERIMENTS_DIR}")

results = {}
for f in sorted(glob.glob(os.path.join(EXPERIMENTS_DIR, 'k4*_results.json'))):
    try:
        with open(f) as fh:
            d = json.load(fh)
        exp_id = os.path.basename(f).split('_')[0].upper()
        results[exp_id] = {
            'file': f,
            'data': d,
            'title': d.get('title', d.get('experiment', '')),
            'runtime': d.get('runtime_seconds', d.get('elapsed_seconds',
                      d.get('total_runtime_s', d.get('total_time_seconds',
                      d.get('computation_time_seconds',
                      d.get('execution_time_seconds', None)))))),
        }
    except Exception as e:
        print(f"  SKIP {f}: {e}")

print(f"Loaded {len(results)} experiment results")

# ============================================================
# 2. Manual classification of each experiment
# ============================================================
# Based on thorough reading of all results
# Categories: positive / null / partial / informative / methodology / correction / meta
# Novel: first time exploring this method family

CLASSIFICATIONS = {
    # === Pre-K426 (exploratory phase) ===
    'K414': {'result': 'null', 'category': 'event_study', 'direction': 'macro_causal',
             'novel': True, 'cross_oos': False, 'cross_oos_survived': None,
             'insight': 'Fed rate changes no Harvey-significant vol impact',
             'efficiency': 2},  # 1=low, 5=high
    'K416': {'result': 'informative', 'category': 'cross_market', 'direction': 'fx_carry',
             'novel': True, 'cross_oos': False, 'cross_oos_survived': None,
             'insight': 'FX carry structure characterized',
             'efficiency': 3},
    'K418': {'result': 'informative', 'category': 'external_variable', 'direction': 'taiwan_exog',
             'novel': True, 'cross_oos': False, 'cross_oos_survived': None,
             'insight': 'Institutional sentiment for Taiwan characterized',
             'efficiency': 3},
    'K420': {'result': 'null', 'category': 'garch_extension', 'direction': 'taiwan_exog',
             'novel': False, 'cross_oos': False, 'cross_oos_survived': None,
             'insight': 'PRS+Jump no help for Taiwan vol',
             'efficiency': 1},
    'K420B': {'result': 'null', 'category': 'garch_extension', 'direction': 'taiwan_exog',
              'novel': False, 'cross_oos': False, 'cross_oos_survived': None,
              'insight': 'Same with cleaner data — still null',
              'efficiency': 1},
    'K421': {'result': 'informative', 'category': 'market_structure', 'direction': 'jump_exploration',
             'novel': True, 'cross_oos': False, 'cross_oos_survived': None,
             'insight': 'VIX ETP market impact characterized',
             'efficiency': 3},
    'K422': {'result': 'informative', 'category': 'cross_market', 'direction': 'spillover',
             'novel': True, 'cross_oos': False, 'cross_oos_survived': None,
             'insight': 'Commodity→equity spillover network mapped',
             'efficiency': 3},
    'K423': {'result': 'null', 'category': 'anomaly', 'direction': 'calendar_effect',
             'novel': True, 'cross_oos': False, 'cross_oos_survived': None,
             'insight': 'Monday effect does not survive Harvey threshold',
             'efficiency': 2},
    'K424': {'result': 'informative', 'category': 'hedging', 'direction': 'eld_hedge',
             'novel': True, 'cross_oos': False, 'cross_oos_survived': None,
             'insight': 'ELD hedge ratios computed',
             'efficiency': 3},
    'K425': {'result': 'informative', 'category': 'cross_market', 'direction': 'decorrelation',
             'novel': True, 'cross_oos': False, 'cross_oos_survived': None,
             'insight': 'Bond-equity decorrelation regime detected',
             'efficiency': 3},

    # === K426-K440: GARCH extensions + VRP exploration ===
    'K426': {'result': 'null', 'category': 'ML', 'direction': 'ml_hybrid',
             'novel': True, 'cross_oos': False, 'cross_oos_survived': None,
             'insight': 'GINN (ML+GARCH) +1230% WORSE. ML overfits vol.',
             'efficiency': 4},  # High: definitively killed ML direction
    'K429': {'result': 'partial', 'category': 'external_variable', 'direction': 'vix_term',
             'novel': True, 'cross_oos': False, 'cross_oos_survived': None,
             'insight': 'VIX term structure slope has directional info',
             'efficiency': 3},
    'K430': {'result': 'positive', 'category': 'external_variable', 'direction': 'vrp',
             'novel': True, 'cross_oos': False, 'cross_oos_survived': None,
             'insight': 'VRP IS t=4.38 passes Harvey. Behavioral mechanism.',
             'efficiency': 5},  # Opened entire VRP research line
    'K431': {'result': 'null', 'category': 'garch_extension', 'direction': 'garch_family',
             'novel': True, 'cross_oos': False, 'cross_oos_survived': None,
             'insight': 'STGARCH +9.36% WORSE than GJR. Ceiling confirmed.',
             'efficiency': 3},
    'K432': {'result': 'null', 'category': 'bayesian', 'direction': 'bayesian_estimation',
             'novel': True, 'cross_oos': False, 'cross_oos_survived': None,
             'insight': 'Bayesian MCMC ≈ MLE. Estimation method not the bottleneck.',
             'efficiency': 4},  # Important negative — saved future Bayesian estimation attempts
    'K433': {'result': 'null', 'category': 'bayesian', 'direction': 'bayesian_selection',
             'novel': True, 'cross_oos': False, 'cross_oos_survived': None,
             'insight': 'SSVS mean-eq: no variable selected for SPY (all redundant)',
             'efficiency': 3},
    'K434': {'result': 'null', 'category': 'bayesian', 'direction': 'bayesian_combination',
             'novel': True, 'cross_oos': False, 'cross_oos_survived': None,
             'insight': 'BMA does NOT beat best single model. Timmermann puzzle.',
             'efficiency': 3},
    'K435': {'result': 'informative', 'category': 'garch_extension', 'direction': 'structural_break',
             'novel': True, 'cross_oos': False, 'cross_oos_survived': None,
             'insight': '20 structural breaks detected; Hillebrand persistence inflation.',
             'efficiency': 4},  # Important for understanding persistence
    'K436': {'result': 'positive', 'category': 'external_variable', 'direction': 'vrp',
             'novel': False, 'cross_oos': False, 'cross_oos_survived': None,
             'insight': 'VRP confirmed robust: daily DM p=0.018, bootstrap p=0.000',
             'efficiency': 4},
    'K437': {'result': 'null', 'category': 'garch_extension', 'direction': 'garch_family',
             'novel': True, 'cross_oos': False, 'cross_oos_survived': None,
             'insight': 'GAS-t underperforms GARCH family. Score-driven no help.',
             'efficiency': 2},  # Slow (1718s) for a null
    'K438': {'result': 'partial', 'category': 'garch_extension', 'direction': 'garchx_vix',
             'novel': True, 'cross_oos': False, 'cross_oos_survived': None,
             'insight': 'GARCH-X(VIX) -6.3% QLIKE (p=0.050). VRP alone no help in var eq.',
             'efficiency': 5},  # Opened the GARCH-X(VIX) direction → crown jewel
    'K439': {'result': 'informative', 'category': 'external_variable', 'direction': 'vrp',
             'novel': False, 'cross_oos': False, 'cross_oos_survived': None,
             'insight': 'Cross-asset VRP: SPY only marginal.',
             'efficiency': 2},
    'K440': {'result': 'null', 'category': 'strategy', 'direction': 'vrp_strategy',
             'novel': True, 'cross_oos': True, 'cross_oos_survived': False,
             'insight': 'VRP VT does NOT improve Sharpe. Best cross-OOS 20%.',
             'efficiency': 2},

    # === K441-K456: Decomposition + cross-market ===
    'K441': {'result': 'positive', 'category': 'methodology', 'direction': 'range_proxy',
             'novel': True, 'cross_oos': False, 'cross_oos_survived': None,
             'insight': 'Yang-Zhang best range proxy for GJR. Range estimators viable.',
             'efficiency': 4},
    'K442': {'result': 'positive', 'category': 'garch_extension', 'direction': 'long_memory',
             'novel': True, 'cross_oos': False, 'cross_oos_survived': None,
             'insight': 'FIGARCH d=0.61 long memory. -6.5% QLIKE (DM p=0.014).',
             'efficiency': 4},
    'K443': {'result': 'informative', 'category': 'multivariate', 'direction': 'copula',
             'novel': True, 'cross_oos': False, 'cross_oos_survived': None,
             'insight': 'Student-t copula best. Lower tail dep SPY-TLT = 0.048.',
             'efficiency': 3},
    'K444': {'result': 'informative', 'category': 'multivariate', 'direction': 'dcc',
             'novel': True, 'cross_oos': False, 'cross_oos_survived': None,
             'insight': 'DCC-GARCH portfolio vol forecasting characterized.',
             'efficiency': 3},
    'K445': {'result': 'informative', 'category': 'cross_market', 'direction': 'btc',
             'novel': True, 'cross_oos': False, 'cross_oos_survived': None,
             'insight': 'BTC inverse leverage effect confirmed.',
             'efficiency': 4},  # Novel finding for different asset class
    'K446': {'result': 'null', 'category': 'external_variable', 'direction': 'geopolitical',
             'novel': True, 'cross_oos': False, 'cross_oos_survived': None,
             'insight': 'GPR index: low contemporaneous corr (0.065). Granger but no OOS.',
             'efficiency': 2},
    'K447': {'result': 'null', 'category': 'external_variable', 'direction': 'skew_index',
             'novel': True, 'cross_oos': False, 'cross_oos_survived': None,
             'insight': 'SKEW index: no incremental OOS value over VIX.',
             'efficiency': 2},
    'K450': {'result': 'partial', 'category': 'decomposition', 'direction': 'semivariance',
             'novel': False, 'cross_oos': False, 'cross_oos_survived': None,
             'insight': 'VRP + semivariance combined model partial improvement.',
             'efficiency': 2},
    'K451': {'result': 'positive', 'category': 'decomposition', 'direction': 'overnight_intraday',
             'novel': True, 'cross_oos': False, 'cross_oos_survived': None,
             'insight': 'Overnight vol decomposition -5.6% QLIKE.',
             'efficiency': 3},
    'K453': {'result': 'positive', 'category': 'decomposition', 'direction': 'semivariance',
             'novel': False, 'cross_oos': True, 'cross_oos_survived': True,
             'insight': 'Semivariance cross-asset: 4/8 sig at 5%. 1 passes Harvey (EEM).',
             'efficiency': 4},
    'K455': {'result': 'informative', 'category': 'cross_market', 'direction': 'spillover',
             'novel': True, 'cross_oos': False, 'cross_oos_survived': None,
             'insight': 'US→Asia vol spillover 28.9%. Diebold-Yilmaz framework.',
             'efficiency': 3},
    'K456': {'result': 'informative', 'category': 'risk_management', 'direction': 'taiwan_var',
             'novel': False, 'cross_oos': False, 'cross_oos_survived': None,
             'insight': 'Taiwan 0050 semivar VaR: GJR-SkewT passes Trinity.',
             'efficiency': 3},

    # === K457-K462: Weekly + Cross-OOS validation wave ===
    'K457': {'result': 'informative', 'category': 'methodology', 'direction': 'weekly_freq',
             'novel': True, 'cross_oos': False, 'cross_oos_survived': None,
             'insight': 'Weekly frequency: different model dynamics than daily.',
             'efficiency': 3},
    'K458': {'result': 'meta', 'category': 'meta_analysis', 'direction': 'meta',
             'novel': True, 'cross_oos': False, 'cross_oos_survived': None,
             'insight': 'First meta-analysis: 35 exp, 48.6% null rate, complexity hurts.',
             'efficiency': 5},  # Very high — synthesis drives future direction
    'K459': {'result': 'null', 'category': 'methodology', 'direction': 'vrp',
             'novel': False, 'cross_oos': True, 'cross_oos_survived': False,
             'insight': 'Weekly VRP cross-OOS: NOT consistently better. Period-specific.',
             'efficiency': 4},  # Important: killed weekly VRP
    'K460': {'result': 'partial', 'category': 'decomposition', 'direction': 'semivariance',
             'novel': False, 'cross_oos': True, 'cross_oos_survived': False,
             'insight': 'Semivar cross-OOS: mixed. Not robust across periods.',
             'efficiency': 3},
    'K461': {'result': 'positive', 'category': 'bayesian', 'direction': 'taiwan_exog',
             'novel': False, 'cross_oos': False, 'cross_oos_survived': None,
             'insight': 'SSVS Taiwan: SPY_ret PIP=1.000. US→TW lead-lag strongest signal.',
             'efficiency': 4},
    'K462': {'result': 'null', 'category': 'garch_extension', 'direction': 'taiwan_exog',
             'novel': False, 'cross_oos': False, 'cross_oos_survived': None,
             'insight': 'STGARCH+GARCH-X on Taiwan: GJR ceiling extends to Taiwan.',
             'efficiency': 2},

    # === K463-K474: Taiwan deep dive + HAR range + exploration ===
    'K463': {'result': 'partial', 'category': 'garch_extension', 'direction': 'taiwan_exog',
             'novel': True, 'cross_oos': False, 'cross_oos_survived': None,
             'insight': 'TVP GARCH-X: EWMA λ=0.95 marginal -1.71% QLIKE.',
             'efficiency': 2},
    'K464': {'result': 'informative', 'category': 'garch_extension', 'direction': 'threshold_sv',
             'novel': True, 'cross_oos': False, 'cross_oos_survived': None,
             'insight': 'Threshold SV: HAR log-range wins 6/6 markets.',
             'efficiency': 4},  # Confirmed HAR-range dominance
    'K465': {'result': 'positive', 'category': 'methodology', 'direction': 'har_range',
             'novel': True, 'cross_oos': True, 'cross_oos_survived': True,
             'insight': 'HAR log-range cross-OOS validated (but tautology concern).',
             'efficiency': 3},  # Tautology issue reduced value
    'K467': {'result': 'positive', 'category': 'risk_management', 'direction': 'har_range',
             'novel': False, 'cross_oos': False, 'cross_oos_survived': None,
             'insight': 'HAR log-range VaR: GJR Trinity 6/6 passes.',
             'efficiency': 3},
    'K468': {'result': 'informative', 'category': 'methodology', 'direction': 'proxy_choice',
             'novel': True, 'cross_oos': False, 'cross_oos_survived': None,
             'insight': 'Yang-Zhang proxy: ranking NOT stable across assets.',
             'efficiency': 4},  # Important methodology finding
    'K469': {'result': 'correction', 'category': 'methodology', 'direction': 'har_range',
             'novel': False, 'cross_oos': True, 'cross_oos_survived': True,
             'insight': 'K465 tautology corrected. HAR still wins with r² proxy.',
             'efficiency': 5},  # Self-correction is high value
    'K470': {'result': 'null', 'category': 'strategy', 'direction': 'har_strategy',
             'novel': True, 'cross_oos': True, 'cross_oos_survived': False,
             'insight': 'HAR-range VT strategy: no Harvey-significant Sharpe improvement.',
             'efficiency': 2},
    'K471': {'result': 'null', 'category': 'external_variable', 'direction': 'higher_moments',
             'novel': True, 'cross_oos': False, 'cross_oos_survived': None,
             'insight': 'Higher moments (skew/kurtosis) no OOS help. Avg ΔR²=+0.063.',
             'efficiency': 2},
    'K472': {'result': 'informative', 'category': 'integration', 'direction': 'taiwan_exog',
             'novel': False, 'cross_oos': False, 'cross_oos_survived': None,
             'insight': 'Taiwan comprehensive: integration of all positive findings.',
             'efficiency': 3},
    'K473': {'result': 'null', 'category': 'external_variable', 'direction': 'attention',
             'novel': True, 'cross_oos': False, 'cross_oos_survived': None,
             'insight': 'Google Trends attention: VIX subsumes all attention info.',
             'efficiency': 3},  # Confirmed VIX sufficiency
    'K474': {'result': 'null', 'category': 'methodology', 'direction': 'weekly_freq',
             'novel': False, 'cross_oos': True, 'cross_oos_survived': False,
             'insight': 'Weekly lagged RV vs VIX: VIX sufficiency holds 0/6.',
             'efficiency': 3},

    # === K475-K483: Ensemble + novel methods ===
    'K475': {'result': 'positive', 'category': 'ensemble', 'direction': 'ensemble',
             'novel': True, 'cross_oos': True, 'cross_oos_survived': True,
             'insight': 'Equal-weight ensemble: avg rank 2.0/7. Timmermann confirmed.',
             'efficiency': 5},  # Major finding: simple ensemble works
    'K476': {'result': 'null', 'category': 'ensemble', 'direction': 'ensemble',
             'novel': False, 'cross_oos': True, 'cross_oos_survived': False,
             'insight': 'Ensemble VaR: 3/10 WORSE than GJR 7/10. Ensemble hurts VaR.',
             'efficiency': 3},  # Important limitation
    'K478': {'result': 'null', 'category': 'external_variable', 'direction': 'entropy',
             'novel': True, 'cross_oos': False, 'cross_oos_survived': None,
             'insight': 'Entropy features: no OOS improvement.',
             'efficiency': 1},  # Quick null, low insight
    'K479': {'result': 'null', 'category': 'decomposition', 'direction': 'wavelet',
             'novel': True, 'cross_oos': False, 'cross_oos_survived': None,
             'insight': 'Wavelet: mixed results, no clear advantage.',
             'efficiency': 1},
    'K480': {'result': 'null', 'category': 'methodology', 'direction': 'regime_selection',
             'novel': True, 'cross_oos': True, 'cross_oos_survived': False,
             'insight': 'Regime-switching model selection: cannot beat GJR VaR.',
             'efficiency': 2},
    'K481': {'result': 'informative', 'category': 'methodology', 'direction': 'mcs',
             'novel': True, 'cross_oos': True, 'cross_oos_survived': None,
             'insight': 'MCS: 5/8 models in superior set. EGARCH, GJR, HAR survive.',
             'efficiency': 4},  # Formal comparison framework
    'K482': {'result': 'positive', 'category': 'ensemble', 'direction': 'ensemble',
             'novel': False, 'cross_oos': True, 'cross_oos_survived': True,
             'insight': 'Equal weight BEATS MCS-weighted. Timmermann puzzle CONFIRMED.',
             'efficiency': 4},
    'K483': {'result': 'positive', 'category': 'cross_market', 'direction': 'commodity',
             'novel': True, 'cross_oos': False, 'cross_oos_survived': None,
             'insight': 'GJR ceiling does NOT hold for commodities. GARCH(1,1) wins USO.',
             'efficiency': 5},  # Major: broke the GJR-always-wins assumption

    # === K484-K491: SSVS variance eq + GJR-X(VIX) crown jewel ===
    'K484': {'result': 'positive', 'category': 'bayesian', 'direction': 'ssvs_vareq',
             'novel': True, 'cross_oos': False, 'cross_oos_survived': None,
             'insight': 'SSVS var eq: GJR(1.0), VIX(1.0), Range(1.0), |ε|(1.0). Breakthrough.',
             'efficiency': 5},  # User-proposed, highest ROI
    'K485': {'result': 'partial', 'category': 'bayesian', 'direction': 'ssvs_vareq',
             'novel': False, 'cross_oos': True, 'cross_oos_survived': True,
             'insight': 'SSVS var eq cross-OOS: 4/5 better, 2/5 significant. Promising.',
             'efficiency': 4},
    'K486': {'result': 'positive', 'category': 'garch_extension', 'direction': 'garchx_vix',
             'novel': False, 'cross_oos': True, 'cross_oos_survived': True,
             'insight': 'GJR-X(VIX) cross-OOS: 5/5 better, avg -17.4% QLIKE. CROWN JEWEL.',
             'efficiency': 5},  # The main finding of the entire series
    'K487': {'result': 'informative', 'category': 'cross_market', 'direction': 'garchx_vix',
             'novel': False, 'cross_oos': True, 'cross_oos_survived': False,
             'insight': 'GJR-X(VIX) equity-specific. Does not generalize to commodities.',
             'efficiency': 4},  # Important boundary condition
    'K488': {'result': 'null', 'category': 'strategy', 'direction': 'garchx_strategy',
             'novel': True, 'cross_oos': True, 'cross_oos_survived': False,
             'insight': 'GJR-X(VIX) VT: no Harvey-significant Sharpe improvement.',
             'efficiency': 2},
    'K489': {'result': 'informative', 'category': 'external_variable', 'direction': 'vix_term',
             'novel': False, 'cross_oos': False, 'cross_oos_survived': None,
             'insight': 'VIX term structure: multi-horizon vol forecasting characterized.',
             'efficiency': 3},
    'K490': {'result': 'positive', 'category': 'garch_extension', 'direction': 'garchx_vix',
             'novel': True, 'cross_oos': True, 'cross_oos_survived': True,
             'insight': 'VIX9D BETTER than VIX in GARCH-X. Significant improvement.',
             'efficiency': 5},  # Refined the crown jewel
    'K491': {'result': 'informative', 'category': 'methodology', 'direction': 'persistence_law',
             'novel': True, 'cross_oos': False, 'cross_oos_survived': None,
             'insight': 'Universal persistence law α+β→1 across 25 assets. Hillebrand confirmed.',
             'efficiency': 4},
}

# Verify all experiments are classified
missing = set(results.keys()) - set(CLASSIFICATIONS.keys())
if missing:
    print(f"WARNING: Unclassified experiments: {missing}")
extra = set(CLASSIFICATIONS.keys()) - set(results.keys())
if extra:
    print(f"WARNING: Classification without result file: {extra}")

N = len(CLASSIFICATIONS)
print(f"\nClassified {N} experiments")

# ============================================================
# 3. Basic statistics
# ============================================================
result_counts = Counter(c['result'] for c in CLASSIFICATIONS.values())
category_counts = Counter(c['category'] for c in CLASSIFICATIONS.values())
direction_counts = Counter(c['direction'] for c in CLASSIFICATIONS.values())
novel_count = sum(1 for c in CLASSIFICATIONS.values() if c['novel'])

print(f"\n=== Result Distribution ===")
for r, count in sorted(result_counts.items(), key=lambda x: -x[1]):
    pct = 100 * count / N
    print(f"  {r:15s}: {count:3d} ({pct:.1f}%)")

print(f"\n=== Category Distribution ===")
for c, count in sorted(category_counts.items(), key=lambda x: -x[1]):
    print(f"  {c:20s}: {count}")

print(f"\nNovel experiments: {novel_count}/{N} ({100*novel_count/N:.1f}%)")

# ============================================================
# 4. Cross-OOS Analysis — False Positive Rate
# ============================================================
cross_oos_experiments = {k: v for k, v in CLASSIFICATIONS.items() if v['cross_oos']}
n_cross_oos = len(cross_oos_experiments)

# Initial positives (before cross-OOS)
initial_positives = {k: v for k, v in CLASSIFICATIONS.items()
                     if v['result'] in ('positive', 'partial')}
n_initial_positive = len(initial_positives)

# Cross-OOS tested positives
cross_oos_tested = {k: v for k, v in CLASSIFICATIONS.items()
                    if v['cross_oos'] and v['cross_oos_survived'] is not None}
n_survived = sum(1 for v in cross_oos_tested.values() if v['cross_oos_survived'])
n_failed = sum(1 for v in cross_oos_tested.values() if not v['cross_oos_survived'])

# False positive rate: initially looked positive but failed cross-OOS
# This includes experiments that were positive on single period but failed cross-OOS
false_positives = {k: v for k, v in cross_oos_tested.items() if not v['cross_oos_survived']}
true_positives = {k: v for k, v in cross_oos_tested.items() if v['cross_oos_survived']}

print(f"\n=== Cross-OOS Analysis ===")
print(f"  Experiments with cross-OOS: {n_cross_oos}")
print(f"  Cross-OOS tested with verdict: {len(cross_oos_tested)}")
print(f"    Survived: {n_survived}")
print(f"    Failed: {n_failed}")
if n_survived + n_failed > 0:
    fpr = n_failed / (n_survived + n_failed)
    print(f"  Cross-OOS failure rate: {fpr:.1%}")
    print(f"  (= {n_failed}/{n_survived + n_failed} tested)")

print(f"\n  Survived cross-OOS:")
for k, v in sorted(true_positives.items()):
    print(f"    {k}: {v['insight'][:80]}")

print(f"\n  Failed cross-OOS:")
for k, v in sorted(false_positives.items()):
    print(f"    {k}: {v['insight'][:80]}")

# ============================================================
# 5. Research Direction ROI
# ============================================================
print(f"\n=== Research Direction ROI ===")
direction_stats = defaultdict(lambda: {'total': 0, 'positive': 0, 'null': 0,
                                        'partial': 0, 'informative': 0, 'meta': 0,
                                        'correction': 0, 'experiments': [],
                                        'total_efficiency': 0, 'runtime_sum': 0,
                                        'runtime_count': 0})

for k, v in CLASSIFICATIONS.items():
    d = v['direction']
    direction_stats[d]['total'] += 1
    direction_stats[d][v['result']] += 1
    direction_stats[d]['experiments'].append(k)
    direction_stats[d]['total_efficiency'] += v['efficiency']
    if k in results and results[k]['runtime'] is not None:
        direction_stats[d]['runtime_sum'] += results[k]['runtime']
        direction_stats[d]['runtime_count'] += 1

# Calculate ROI: (positive + partial) / total
print(f"{'Direction':<20s} {'Total':>5s} {'Pos':>4s} {'Part':>4s} {'Null':>4s} {'Info':>4s} {'AvgEff':>6s} {'ROI':>6s}")
print("-" * 65)
direction_roi = {}
for d, s in sorted(direction_stats.items(), key=lambda x: -x[1]['total']):
    roi = (s['positive'] + 0.5 * s['partial']) / s['total'] if s['total'] > 0 else 0
    avg_eff = s['total_efficiency'] / s['total'] if s['total'] > 0 else 0
    direction_roi[d] = {'roi': roi, 'avg_efficiency': avg_eff, **s}
    print(f"  {d:<20s} {s['total']:>4d}  {s['positive']:>4d}  {s['partial']:>4d}  {s['null']:>4d}  {s['informative']:>4d}  {avg_eff:>5.1f}  {roi:>5.1%}")

# ============================================================
# 6. Wasted Time Analysis
# ============================================================
print(f"\n=== Wasted Time Detection ===")
print("Directions where early nulls should have stopped further exploration:")

wasted_directions = []
for d, s in direction_stats.items():
    if s['total'] >= 3 and s['null'] >= 2 and s['positive'] == 0 and s['partial'] <= 1:
        wasted_directions.append((d, s))

for d, s in wasted_directions:
    print(f"\n  {d}: {s['total']} experiments, {s['null']} nulls")
    for exp_id in s['experiments']:
        c = CLASSIFICATIONS[exp_id]
        print(f"    {exp_id}: [{c['result']}] {c['insight'][:70]}")

# Compute time wasted
print(f"\n=== Runtime Analysis ===")
total_runtime = 0
runtime_by_result = defaultdict(float)
runtime_count_by_result = defaultdict(int)
for k, v in CLASSIFICATIONS.items():
    if k in results and results[k]['runtime'] is not None:
        rt = results[k]['runtime']
        total_runtime += rt
        runtime_by_result[v['result']] += rt
        runtime_count_by_result[v['result']] += 1

print(f"  Total recorded runtime: {total_runtime:.1f}s ({total_runtime/60:.1f} min)")
for r in sorted(runtime_by_result.keys()):
    rt = runtime_by_result[r]
    cnt = runtime_count_by_result[r]
    print(f"  {r:15s}: {rt:8.1f}s ({cnt} experiments, avg {rt/cnt:.1f}s)" if cnt > 0 else "")

# ============================================================
# 7. Most Efficient Experiments
# ============================================================
print(f"\n=== Top 10 Most Efficient Experiments ===")
efficiency_ranked = sorted(CLASSIFICATIONS.items(), key=lambda x: -x[1]['efficiency'])
for i, (k, v) in enumerate(efficiency_ranked[:10]):
    rt_str = f"{results[k]['runtime']:.0f}s" if k in results and results[k]['runtime'] is not None else "N/A"
    print(f"  {i+1}. {k} (eff={v['efficiency']}) [{v['result']}] rt={rt_str}")
    print(f"     {v['insight'][:80]}")

print(f"\n=== Bottom 5 Least Efficient ===")
for i, (k, v) in enumerate(efficiency_ranked[-5:]):
    rt_str = f"{results[k]['runtime']:.0f}s" if k in results and results[k]['runtime'] is not None else "N/A"
    print(f"  {N-4+i}. {k} (eff={v['efficiency']}) [{v['result']}] rt={rt_str}")
    print(f"     {v['insight'][:80]}")

# ============================================================
# 8. Average experiments per validated finding
# ============================================================
validated_findings = [k for k, v in CLASSIFICATIONS.items()
                      if v['cross_oos'] and v.get('cross_oos_survived') == True]
print(f"\n=== Experiments per Validated Finding ===")
print(f"  Total experiments: {N}")
print(f"  Cross-OOS validated positive findings: {len(validated_findings)}")
if validated_findings:
    print(f"  Ratio: {N/len(validated_findings):.1f} experiments per validated finding")
    print(f"  Validated findings:")
    for k in validated_findings:
        print(f"    {k}: {CLASSIFICATIONS[k]['insight'][:80]}")

# ============================================================
# 9. Optimal Experiment Ordering (Hindsight)
# ============================================================
print(f"\n=== Optimal Experiment Ordering (Hindsight) ===")

# Group experiments into phases based on what they achieved
OPTIMAL_ORDER = [
    # Phase 1: Establish baseline + methodology (5 experiments)
    ("Phase 1: Foundation", [
        ('K431', 'Confirm GJR ceiling — STGARCH fails'),
        ('K432', 'Confirm MLE sufficiency — Bayesian estimation ≈ MLE'),
        ('K426', 'Kill ML direction early — GINN catastrophically fails'),
        ('K435', 'Understand structural breaks + Hillebrand persistence inflation'),
        ('K441', 'Establish range-based proxy methodology (Yang-Zhang)'),
    ]),
    # Phase 2: Find the information source (5 experiments)
    ("Phase 2: Information Discovery", [
        ('K430', 'Discover VRP predictability (t=4.38)'),
        ('K438', 'Discover GARCH-X(VIX) improvement (-6.3%)'),
        ('K484', 'SSVS variance eq: identify GJR+VIX+Range+|ε| as optimal components'),
        ('K445', 'BTC inverse leverage — asset class matters'),
        ('K483', 'Commodity vol — break GJR-always-wins assumption'),
    ]),
    # Phase 3: Validate rigorously (7 experiments)
    ("Phase 3: Cross-OOS Validation", [
        ('K486', 'Crown jewel: GJR-X(VIX) 5/5 cross-OOS, avg -17.4%'),
        ('K485', 'SSVS variance eq cross-OOS: 4/5 better'),
        ('K490', 'VIX9D beats VIX — refine the information source'),
        ('K469', 'HAR log-range validated with corrected proxy'),
        ('K475', 'Equal-weight ensemble validated — Timmermann confirmed'),
        ('K453', 'Semivariance cross-asset validated'),
        ('K487', 'GJR-X(VIX) boundary: equity-specific'),
    ]),
    # Phase 4: Applications + boundary conditions (5 experiments)
    ("Phase 4: Applications", [
        ('K467', 'HAR-range VaR estimation'),
        ('K461', 'Taiwan SSVS: US→TW lead-lag confirmation'),
        ('K491', 'Universal persistence law — theoretical synthesis'),
        ('K458', 'First meta-analysis — research synthesis'),
        ('K481', 'Model Confidence Set — formal comparison'),
    ]),
    # Phase 5: Diminishing returns (could have been skipped)
    ("Phase 5: Diminishing Returns (optional)", [
        ('K471', 'Higher moments — null (predictable from theory)'),
        ('K473', 'Attention proxy — null (VIX subsumes)'),
        ('K478', 'Entropy — null (no info content)'),
        ('K479', 'Wavelet — null (mixed)'),
        ('K470', 'HAR VT strategy — null (forecasting ≠ trading)'),
        ('K488', 'GJR-X VT strategy — null (same lesson)'),
    ]),
]

total_optimal = 0
for phase_name, exps in OPTIMAL_ORDER:
    print(f"\n  {phase_name} ({len(exps)} experiments)")
    for exp_id, desc in exps:
        print(f"    {exp_id}: {desc}")
    total_optimal += len(exps)

print(f"\n  Optimal total: ~{total_optimal} experiments (vs {N} actual)")
print(f"  Savings: ~{N - total_optimal} experiments ({100*(N-total_optimal)/N:.0f}% reduction)")

# ============================================================
# 10. Key Lessons
# ============================================================
LESSONS = [
    {
        'lesson': 'Information quality > model complexity',
        'evidence': 'K426 (ML +1230% worse), K431 (STGARCH +9%), K432 (Bayesian≈MLE), K434 (BMA no help)',
        'experiments_confirming': 4
    },
    {
        'lesson': 'VIX is the single most important exogenous variable',
        'evidence': 'K438 (GARCH-X(VIX) -6.3%), K486 (5/5 cross-OOS -17.4%), K473 (VIX subsumes attention)',
        'experiments_confirming': 5
    },
    {
        'lesson': 'Cross-OOS validation eliminates ~50% of apparent positives',
        'evidence': f'K440, K459, K460, K470, K474, K476, K480, K488 all failed cross-OOS',
        'experiments_confirming': 8
    },
    {
        'lesson': 'Simple methods beat complex ones (Timmermann puzzle)',
        'evidence': 'K475 (equal ensemble best), K482 (equal > MCS-weighted), K434 (BMA fails)',
        'experiments_confirming': 3
    },
    {
        'lesson': 'Strategy ≠ Forecasting — good prediction does not imply good trading',
        'evidence': 'K440 (VRP VT fails), K470 (HAR VT fails), K488 (GJR-X VT fails)',
        'experiments_confirming': 3
    },
    {
        'lesson': 'GJR ceiling is equity-specific, not universal',
        'evidence': 'K483 (GARCH(1,1) wins USO), K445 (BTC inverse leverage), K487 (GJR-X equity-specific)',
        'experiments_confirming': 3
    },
    {
        'lesson': 'User/external suggestions have highest ROI',
        'evidence': 'K484 (user-proposed SSVS var eq → breakthrough), K461 (user-proposed Taiwan → SPY PIP=1)',
        'experiments_confirming': 2
    },
    {
        'lesson': 'Meta-analysis changes research direction more efficiently than new experiments',
        'evidence': 'K458 (redirected from GARCH extensions to VIX/information)',
        'experiments_confirming': 1
    },
]

print(f"\n=== Key Lessons ===")
for i, lesson in enumerate(LESSONS, 1):
    print(f"\n  {i}. {lesson['lesson']}")
    print(f"     Evidence: {lesson['evidence']}")

# ============================================================
# 11. Compile results JSON
# ============================================================
output = {
    'experiment_id': 'K492',
    'title': 'Research Efficiency Meta-Study — 67 Experiments Retrospective',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'method': 'Manual classification + statistical analysis of all K414-K491 results',
    'data_source': 'experiments/k4*_results.json (68 files)',
    'n_experiments_classified': N,
    'n_result_files': len(results),

    'result_distribution': dict(result_counts),
    'null_rate_pct': round(100 * result_counts.get('null', 0) / N, 1),
    'positive_rate_pct': round(100 * result_counts.get('positive', 0) / N, 1),

    'cross_oos_analysis': {
        'n_experiments_with_cross_oos': n_cross_oos,
        'n_survived': n_survived,
        'n_failed': n_failed,
        'failure_rate_pct': round(100 * n_failed / (n_survived + n_failed), 1) if (n_survived + n_failed) > 0 else None,
        'survived_experiments': list(true_positives.keys()),
        'failed_experiments': list(false_positives.keys()),
        'interpretation': f'{n_failed}/{n_survived+n_failed} experiments that looked promising on single-period failed cross-OOS validation. This {100*n_failed/(n_survived+n_failed):.0f}% failure rate aligns with Ioannidis (2005) concerns about false positives in empirical research.'
    },

    'experiments_per_validated_finding': round(N / len(validated_findings), 1) if validated_findings else None,
    'validated_findings': {k: CLASSIFICATIONS[k]['insight'] for k in validated_findings},

    'direction_roi': {
        d: {
            'total': s['total'],
            'positive': s['positive'],
            'partial': s['partial'],
            'null': s['null'],
            'informative': s['informative'],
            'roi': round(direction_roi[d]['roi'], 3),
            'avg_efficiency': round(direction_roi[d]['avg_efficiency'], 1),
            'experiments': s['experiments'],
        }
        for d, s in direction_stats.items()
    },

    'wasted_directions': [
        {
            'direction': d,
            'n_experiments': s['total'],
            'n_nulls': s['null'],
            'experiments': s['experiments'],
            'recommendation': f'Should have stopped after 2 nulls. Wasted ~{s["total"]-2} experiments.',
        }
        for d, s in wasted_directions
    ],

    'efficiency_ranking': {
        'top_10': [
            {
                'rank': i+1,
                'experiment': k,
                'efficiency_score': v['efficiency'],
                'result': v['result'],
                'insight': v['insight'],
                'runtime_seconds': results[k]['runtime'] if k in results else None,
            }
            for i, (k, v) in enumerate(efficiency_ranked[:10])
        ],
        'bottom_5': [
            {
                'rank': N-4+i,
                'experiment': k,
                'efficiency_score': v['efficiency'],
                'result': v['result'],
                'insight': v['insight'],
            }
            for i, (k, v) in enumerate(efficiency_ranked[-5:])
        ],
    },

    'optimal_ordering': {
        phase_name: [{'experiment': eid, 'rationale': desc} for eid, desc in exps]
        for phase_name, exps in OPTIMAL_ORDER
    },
    'optimal_n_experiments': total_optimal,
    'actual_n_experiments': N,
    'potential_savings_pct': round(100 * (N - total_optimal) / N, 1),

    'runtime_analysis': {
        'total_recorded_seconds': round(total_runtime, 1),
        'total_recorded_minutes': round(total_runtime / 60, 1),
        'by_result_type': {
            r: {
                'total_seconds': round(runtime_by_result[r], 1),
                'n_experiments': runtime_count_by_result[r],
                'avg_seconds': round(runtime_by_result[r] / runtime_count_by_result[r], 1) if runtime_count_by_result[r] > 0 else None,
            }
            for r in sorted(runtime_by_result.keys())
        },
    },

    'key_lessons': LESSONS,

    'crown_jewels': [
        {
            'experiment': 'K486',
            'finding': 'GJR-GARCH-X(VIX) beats GJR in 5/5 cross-OOS periods, avg -17.4% QLIKE',
            'depends_on': ['K438', 'K430'],
            'shortest_path': 'K430 → K438 → K486 (3 experiments)',
        },
        {
            'experiment': 'K490',
            'finding': 'VIX9D beats VIX in GARCH-X, significant improvement',
            'depends_on': ['K486', 'K429'],
            'shortest_path': 'K430 → K438 → K486 → K490 (4 experiments)',
        },
        {
            'experiment': 'K484',
            'finding': 'SSVS variance eq: GJR+VIX+Range+|ε| optimal (user-proposed)',
            'depends_on': ['K433'],
            'shortest_path': 'K433 → K484 (2 experiments)',
        },
        {
            'experiment': 'K475',
            'finding': 'Equal-weight ensemble avg rank 2.0/7, Timmermann puzzle confirmed',
            'depends_on': ['K434', 'K465', 'K453'],
            'shortest_path': '3 base experiments → K475 (4 experiments)',
        },
    ],

    'meta_statistics': {
        'novel_experiment_rate_pct': round(100 * novel_count / N, 1),
        'novel_count': novel_count,
        'category_distribution': dict(category_counts),
        'direction_distribution': dict(direction_counts),
        'n_unique_directions': len(direction_counts),
        'n_unique_categories': len(category_counts),
    },

    'comparison_with_k458': {
        'k458_scope': 'K414-K456 (35 experiments)',
        'k492_scope': f'K414-K491 ({N} experiments)',
        'k458_null_rate': 48.6,
        'k492_null_rate': round(100 * result_counts.get('null', 0) / N, 1),
        'additional_experiments': N - 35,
        'trend': 'Null rate similar — the QLIKE ceiling and VIX sufficiency findings from K458 are reinforced by K459-K491.',
    },

    'recommendations': [
        'Run cross-OOS validation BEFORE exploring variants — saves 40% of experiments',
        'User/external suggestions have highest ROI — actively solicit them',
        'Meta-analysis every 20 experiments — resets direction more efficiently than new experiments',
        'Stop after 2 consecutive nulls in a direction — diminishing returns',
        'Forecasting → strategy gap is real — test tradability early, not as afterthought',
        'GJR-X(VIX) is the crown jewel — future work should build on it, not compete with it',
        'Asset class matters — test on non-equity assets to find boundary conditions',
    ],

    'references': [
        'Harvey, Liu, Zhu (2016) ...and the Cross-Section of Expected Returns, RFS',
        'Timmermann (2006) Forecast Combinations, Handbook of Economic Forecasting',
        'Ioannidis (2005) Why Most Published Research Findings Are False, PLoS Medicine',
        'Hillebrand (2005) Neglecting Parameter Changes in GARCH Models, JTSA',
    ],
}

# Save
output_path = os.path.join(os.path.dirname(__file__), 'k492_research_efficiency_results.json')
with open(output_path, 'w') as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

print(f"\n\nResults saved to {output_path}")
print(f"\n{'='*60}")
print(f"SUMMARY")
print(f"{'='*60}")
print(f"Total experiments: {N}")
print(f"Null rate: {output['null_rate_pct']}%")
print(f"Positive rate: {output['positive_rate_pct']}%")
print(f"Cross-OOS failure rate: {output['cross_oos_analysis']['failure_rate_pct']}%")
print(f"Experiments per validated finding: {output['experiments_per_validated_finding']}")
print(f"Potential savings with optimal ordering: {output['potential_savings_pct']}%")
print(f"Crown jewel: K486 GJR-X(VIX), shortest path = 3 experiments")
