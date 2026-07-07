# -*- coding: utf-8 -*-
"""懶人包海報 renderer（data-bound，數字全讀 evidence.json）。可復現。"""
import json, os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm
from matplotlib.patches import FancyBboxPatch

FP='/System/Library/Fonts/Supplemental/Arial Unicode.ttf'
prop=fm.FontProperties(fname=FP)
def f(sz,w='normal'): return fm.FontProperties(fname=FP, size=sz, weight=w)
plt.rcParams['axes.unicode_minus']=False

OUT='storage/trending_assets/ai_skew_2026_07_08/lazypack'
os.makedirs(OUT, exist_ok=True)
ev=json.load(open('storage/trending_assets/ai_skew_2026_07_08/evidence.json'))

INK='#1b2733'; SUB='#5b6b7b'; RED='#c0392b'; GREEN='#27ae60'; BLUE='#2c3e50'; BG='#ffffff'; CARD='#f4f6f8'
SRC=f'資料來源：CBOE SKEW / VIX 指數與各標的日報酬（yfinance），截至 {ev["skew_date"]}｜VolPred'

def base(title, sub):
    fig=plt.figure(figsize=(10.66,6.66), dpi=150); fig.patch.set_facecolor(BG)
    ax=fig.add_axes([0,0,1,1]); ax.set_xlim(0,100); ax.set_ylim(0,100); ax.axis('off')
    ax.add_patch(plt.Rectangle((0,92),100,8,color=INK,zorder=1))
    ax.text(4,95.6,title,fontproperties=f(20,'bold'),color='white',va='center')
    ax.text(4,88,sub,fontproperties=f(12),color=SUB,va='center')
    ax.text(4,2.3,SRC,fontproperties=f(8.5),color=SUB,va='center')
    return fig,ax

def card(ax,x,y,w,h,c=CARD):
    ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle="round,pad=0.4,rounding_size=1.5",
                fc=c,ec='none',zorder=2))

# ---- Poster 1: 兩個溫度計 ----
fig,ax=base('兩個「市場恐懼溫度計」現在說什麼','VIX 量會不會晃，SKEW 量會不會歪')
card(ax,4,44,44,38); card(ax,52,44,44,38)
ax.text(26,77,'VIX　現貨波動',fontproperties=f(15,'bold'),color=BLUE,ha='center')
ax.text(26,64,f'{ev["vix_last"]:.2f}',fontproperties=f(46,'bold'),color=BLUE,ha='center')
ax.text(26,53,f'兩年 {ev["vix_pctile_2y"]:.0f} 百分位　偏低',fontproperties=f(12.5),color=INK,ha='center')
ax.text(26,48,'現貨市場心跳很穩',fontproperties=f(11),color=SUB,ha='center')
ax.text(74,77,'SKEW　尾部保險',fontproperties=f(15,'bold'),color=RED,ha='center')
ax.text(74,64,f'{ev["skew_last"]:.2f}',fontproperties=f(46,'bold'),color=RED,ha='center')
ax.text(74,53,f'兩年 {ev["skew_pctile_2y"]:.0f} 百分位　中性',fontproperties=f(12.5),color=INK,ha='center')
ax.text(74,48,f'趴在兩年均值 {ev["skew_mean_2y"]:.0f} 附近',fontproperties=f(11),color=SUB,ha='center')
card(ax,4,12,92,26,'#fbeee9')
ax.text(50,32,'反直覺結論',fontproperties=f(13,'bold'),color=RED,ha='center')
ax.text(50,23,'從「隱含定價」看，市場並沒有低估尾部風險',fontproperties=f(16,'bold'),color=INK,ha='center')
ax.text(50,16,'SKEW 很正常、VIX 甚至偏低 —— 選擇權沒在恐慌',fontproperties=f(12.5),color=SUB,ha='center')
plt.savefig(f'{OUT}/01_concept.png'); plt.close()

# ---- Poster 2: 已實現偏態 ----
fig,ax=base('但「已實現」的偏態，開始分家了','近 63 交易日日報酬偏態｜負 = 下殺比上漲兇（左尾肥）')
rows=[('SOX 半導體',ev['tech']['^SOX']['realized_skew_63d']),
      ('QQQ 那斯達克100',ev['tech']['QQQ']['realized_skew_63d']),
      ('S&P 500',ev['tech']['^GSPC']['realized_skew_63d']),
      ('NVDA 輝達',ev['tech']['NVDA']['realized_skew_63d']),
      ('AMD',ev['tech']['AMD']['realized_skew_63d'])]
x0=34; zero=x0+ 0  # bar area 34..92, center at 63
cx=63; scale=32/0.9  # map skew to px, max ~0.9
ytop=78; dy=12.5
for i,(name,v) in enumerate(rows):
    y=ytop-i*dy
    ax.text(30,y,name,fontproperties=f(13,'bold'),color=INK,ha='right',va='center')
    col=RED if v<0 else GREEN
    ax.add_patch(plt.Rectangle((min(cx,cx+v*scale),y-3),abs(v*scale),6,color=col,zorder=3))
    lab=f'{v:+.2f}'
    # 數值標籤一律放 0 軸右側（負 bar 在左、標籤在右的空白區），避免與資產名稱碰撞
    lx=(cx+1.5) if v<0 else (cx+v*scale+1.5)
    ax.text(lx,y,lab,fontproperties=f(12.5,'bold'),color=col,ha='left',va='center')
ax.plot([cx,cx],[ytop-4*dy-6,ytop+6],color='#333',lw=1,zorder=2)
ax.text(cx,ytop+9,'0',fontproperties=f(10),color=SUB,ha='center')
ax.text(cx-14,17,'大盤指數已翻負',fontproperties=f(12,'bold'),color=RED,ha='center')
ax.text(cx+16,17,'龍頭仍對稱／偏正',fontproperties=f(12,'bold'),color=GREEN,ha='center')
plt.savefig(f'{OUT}/02_method_results.png'); plt.close()

# ---- Poster 3: takeaway ----
fig,ax=base('該看的不是單一數字，是「離散度」','一個免費就能自己算的健康檢查')
items=[('VIX 低 ≠ 安全','它可能只是被少數還在噴的龍頭壓住的平均值'),
       ('看偏態的「差距」','大盤指數偏態 vs 龍頭偏態，愈拉開＝撐盤愈集中＝愈脆弱'),
       ('免費可自算','抓 SOX／QQQ／S&P 與幾檔龍頭日報酬，量近 3 個月偏態係數')]
y=74
for t,d in items:
    card(ax,4,y-14,92,15)
    ax.add_patch(plt.Circle((10,y-6.5),2.6,color=INK,zorder=3))
    ax.text(10,y-6.5,'✓',fontproperties=f(13,'bold'),color='white',ha='center',va='center')
    ax.text(16,y-3,t,fontproperties=f(15,'bold'),color=INK,va='center')
    ax.text(16,y-9.5,d,fontproperties=f(11.5),color=SUB,va='center')
    y-=20
ax.text(50,8.5,'數據不會直接告訴你該不該慌，但會告訴你該把眼睛放在哪裡。非投資建議。',
        fontproperties=f(11),color=SUB,ha='center')
plt.savefig(f'{OUT}/03_takeaway.png'); plt.close()
print('lazypack rendered:', sorted(os.listdir(OUT)))
