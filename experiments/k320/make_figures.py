"""K320 content audit figures (general-audience article)."""
from pathlib import Path
import json
import matplotlib.pyplot as plt
import matplotlib as mpl

mpl.rcParams['font.sans-serif'] = ['Heiti TC', 'PingFang TC', 'Arial Unicode MS', 'sans-serif']
mpl.rcParams['axes.unicode_minus'] = False
plt.rcParams.update({'figure.dpi': 160, 'savefig.dpi': 160})

ROOT = Path(__file__).parent
results = json.loads((ROOT / 'k320_content_audit_results.json').read_text())
summary = results['summary']
fig_dir = ROOT / 'figures'
fig_dir.mkdir(exist_ok=True)

# --- Figure 1: Severity breakdown ---
fig, ax = plt.subplots(figsize=(8, 5.2))
sev = summary['severity_breakdown']
labels = ['MISLEADING\n(誤導)', 'OUTDATED\n(過時)', 'STILL_VALID\n(自我修正範本)']
values = [sev['MISLEADING'], sev['OUTDATED'], sev['STILL_VALID']]
colors = ['#c0392b', '#e67e22', '#27ae60']
bars = ax.bar(labels, values, color=colors, edgecolor='black', linewidth=0.6)
for bar, v in zip(bars, values):
    ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.4,
            str(v), ha='center', fontsize=12, fontweight='bold')
ax.set_ylabel('文章數', fontsize=11)
ax.set_title(f"K320 內容稽核：{summary['total_findings']} 個發現的嚴重度分布\n"
             f"(掃描樣本：{summary['total_published_articles']} 篇已發佈文章)", fontsize=12)
ax.set_ylim(0, max(values) + 4)
ax.grid(axis='y', alpha=0.3)
plt.tight_layout()
fig.savefig(fig_dir / 'k320_severity_breakdown.png', bbox_inches='tight')
plt.close(fig)
print('saved k320_severity_breakdown.png')

# --- Figure 2: Issue type distribution ---
fig, ax = plt.subplots(figsize=(9.5, 5.2))
issues = summary['issue_breakdown']
order = sorted(issues.items(), key=lambda kv: -kv[1]['count'])
order = [(k, v) for k, v in order if v['count'] > 0]
zh_map = {
    'stub_content': '空殼文章 (<100 字)',
    'hybrid_vt_sharpe_2': 'Hybrid VT Sharpe 2.0\n(未扣交易成本)',
    'withdrawal_rate_doubles': 'VT 退休提領率\n4% → 8% (已被 K87 推翻)',
    'TSMOM_passes_Harvey': 'TSMOM 通過 Harvey\n(全樣本失敗)',
    'VT_91pct_trend_following': 'VT 91% 趨勢追蹤\n(K53 修正為 5.2%)',
}
labels = [zh_map.get(k, k) for k, _ in order]
counts = [v['count'] for _, v in order]
fix_refs = [v['correction_knowledge'] for _, v in order]
bars = ax.barh(labels, counts, color='#34495e', edgecolor='black', linewidth=0.6)
for bar, c, ref in zip(bars, counts, fix_refs):
    ax.text(bar.get_width() + 0.3, bar.get_y() + bar.get_height() / 2,
            f'{c} 篇  (修正出處: {ref})', va='center', fontsize=9.5)
ax.set_xlabel('文章數', fontsize=11)
ax.set_title('K320：依問題類型拆解 (regex 比對 + 14 篇人工深讀)', fontsize=12)
ax.set_xlim(0, max(counts) + 6)
ax.invert_yaxis()
ax.grid(axis='x', alpha=0.3)
plt.tight_layout()
fig.savefig(fig_dir / 'k320_issue_breakdown.png', bbox_inches='tight')
plt.close(fig)
print('saved k320_issue_breakdown.png')

# --- Figure 3: Content deficiency ---
fig, ax = plt.subplots(figsize=(8, 5))
total = summary['total_published_articles']
empty = summary['total_empty_articles_0_chars']
stub = summary['total_stub_articles_lt100_chars']
mislead = sev['MISLEADING']
healthy = total - empty - stub - mislead
parts = [healthy, empty, stub, mislead]
plabels = [f'內容完整\n{healthy} 篇',
           f'完全空白\n{empty} 篇 (0 字)',
           f'空殼 <100 字\n{stub} 篇',
           f'誤導性\n{mislead} 篇']
pcolors = ['#27ae60', '#7f8c8d', '#e67e22', '#c0392b']
explode = [0, 0.04, 0.04, 0.08]
wedges, texts, auto = ax.pie(parts, labels=plabels, colors=pcolors,
                              autopct='%1.1f%%', startangle=90,
                              explode=explode, textprops={'fontsize': 10},
                              wedgeprops={'edgecolor': 'white', 'linewidth': 1.2})
for a in auto:
    a.set_color('white')
    a.set_fontweight('bold')
ax.set_title(f'K320：{total} 篇文章內容健康度盤點', fontsize=12, pad=14)
plt.tight_layout()
fig.savefig(fig_dir / 'k320_content_health.png', bbox_inches='tight')
plt.close(fig)
print('saved k320_content_health.png')

print('\nDone. Figures in', fig_dir)
