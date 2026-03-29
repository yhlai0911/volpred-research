"""
Generate charts for K667 (Insurance Cost) and K668 (Retirement VT) articles.
"""
import sys
import json
sys.path.insert(0, 'src')
from volpred.charts import generate_bar_chart, generate_grouped_bar_chart, generate_line_chart, upload_chart, embed_chart

# === K667: Insurance Cost ===
# Chart 1: MDD comparison across strategies
labels_mdd = ['BH SPY', 'BH 60/40', 'BH 50/50', '12/VIX SPY', '50/50+VT']
values_mdd = [56.47, 35.47, 33.02, 28.61, 12.74]

path_mdd = generate_bar_chart(
    labels=labels_mdd,
    values=values_mdd,
    title='最大回撤（MDD）比較：各策略的下跌保護效果（2006–2026）',
    xlabel='策略',
    ylabel='最大回撤（%，絕對值）',
    filename='k667_mdd_comparison'
)
url_mdd = upload_chart(path_mdd)
print(f'K667 MDD chart: {url_mdd}')

# Chart 2: Annual premium cost (insurance cost) comparison
labels_premium = ['ATM Protective Put', '12/VIX SPY', '10% OTM Put\n（估算）', '50/50+VT']
values_premium = [26.1, 2.505, 2.0, 1.334]

path_premium = generate_bar_chart(
    labels=labels_premium,
    values=values_premium,
    title='保險成本比較：各方式的年化保費（%/年）',
    xlabel='保險工具',
    ylabel='年化保費（%/年）',
    filename='k667_premium_comparison'
)
url_premium = upload_chart(path_premium)
print(f'K667 premium chart: {url_premium}')

# === K668: Retirement VT ===
# Chart 3: Sequence of returns correlation (BH SPY vs 50/50+VT)
labels_corr = ['BH SPY', '80/20+VT', 'BH 60/40', '50/50+VT', 'Piecewise\nConservative']
values_corr = [0.961, 0.899, 0.422, 0.307, 0.354]

path_corr = generate_bar_chart(
    labels=labels_corr,
    values=values_corr,
    title='前三年報酬 vs 10年後資產的相關係數\n（越低＝退休結果越不依賴起始時間點）',
    xlabel='策略',
    ylabel='相關係數（前3年報酬 vs 終端財富）',
    filename='k668_sequence_correlation'
)
url_corr = upload_chart(path_corr)
print(f'K668 correlation chart: {url_corr}')

# Chart 4: GFC stress test min portfolio (% of initial)
labels_gfc = ['BH SPY', '80/20+VT', 'BH 60/40', '50/50+VT', 'Piecewise\nConservative']
values_gfc = [52.1, 84.1, 70.7, 85.7, 25.2]

path_gfc = generate_bar_chart(
    labels=labels_gfc,
    values=values_gfc,
    title='GFC 壓力測試（2008年9月開始退休）\n危機中保住的資產比例（%）',
    xlabel='策略',
    ylabel='最低資產比例（% of 初始$1M）',
    filename='k668_gfc_stress_test'
)
url_gfc = upload_chart(path_gfc)
print(f'K668 GFC stress test chart: {url_gfc}')

# Output all URLs as JSON
result = {
    'k667_mdd': url_mdd,
    'k667_premium': url_premium,
    'k668_corr': url_corr,
    'k668_gfc': url_gfc
}
print('\n=== CHART URLS ===')
print(json.dumps(result, indent=2))
