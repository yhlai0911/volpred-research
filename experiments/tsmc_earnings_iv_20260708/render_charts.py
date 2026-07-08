"""Data-bound charts for TSMC earnings IV article. All numbers read from results.json."""
import json, numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

# CJK font
for fp in ["/System/Library/Fonts/PingFang.ttc","/System/Library/Fonts/STHeiti Medium.ttc"]:
    try:
        font_manager.fontManager.addfont(fp); break
    except Exception: pass
plt.rcParams["font.sans-serif"]=["PingFang HK","Heiti TC","Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"]=False

R=json.load(open("experiments/tsmc_earnings_iv_20260708/tsmc_earnings_iv_results.json"))
NAVY="#0f2740"; BLUE="#2f6db5"; ORANGE="#e08a1e"; GREY="#8a97a5"; RED="#c0392b"; GREEN="#2e8b57"
OUT="experiments/tsmc_earnings_iv_20260708"

# ---- Chart 1: main result — earnings hump + IV vs RV ----
fig,(ax1,ax2)=plt.subplots(1,2,figsize=(11,4.6))
labels=["7/10\n(法說前)","7/17\n(含法說 7/16)"]
ivs=[R["front_atm_iv_pct"],R["back_atm_iv_pct"]]
b=ax1.bar(labels,ivs,color=[GREY,BLUE],width=0.55)
ax1.set_ylim(0,max(ivs)*1.25); ax1.set_ylabel("平價隱含波動率 (%)")
ax1.set_title("法說會凸起：含法說到期日多 %.1f 個百分點"%R["earnings_vol_premium_pp"],fontsize=11,color=NAVY)
for r,v in zip(b,ivs): ax1.text(r.get_x()+r.get_width()/2,v+1,f"{v:.1f}%",ha="center",fontweight="bold")
ax1.annotate("",xy=(1,R["back_atm_iv_pct"]),xytext=(1,R["front_atm_iv_pct"]),
             arrowprops=dict(arrowstyle="<->",color=ORANGE,lw=2))
ax1.text(1.08,(ivs[0]+ivs[1])/2,f"+{R['earnings_vol_premium_pp']}pp",color=ORANGE,fontweight="bold")

cats=["隱含波動率\n(含法說 7/17)","已實現波動率\n(近20日)"]
vals=[R["back_atm_iv_pct"],R["rv20_pct"]]
b2=ax2.bar(cats,vals,color=[BLUE,ORANGE],width=0.55)
ax2.set_ylim(0,max(vals)*1.25); ax2.set_ylabel("年化波動率 (%)")
ax2.set_title(f"溢價幾乎歸零：IV − RV = {R['iv_rv_gap_back_pp']} 個百分點",fontsize=11,color=NAVY)
for r,v in zip(b2,vals): ax2.text(r.get_x()+r.get_width()/2,v+1,f"{v:.1f}%",ha="center",fontweight="bold")
fig.suptitle(f"台積電(TSM) 法說會前隱含波動率定價 — 截點 {R['as_of']}，現價 ${R['spot']}",
             fontsize=12.5,fontweight="bold",color=NAVY)
plt.tight_layout(rect=[0,0,1,0.95])
plt.savefig(f"{OUT}/chart_main.png",dpi=140,bbox_inches="tight"); plt.close()

# ---- Lazypack: 3 posters ----
def poster(fn,title,lines,accent):
    fig,ax=plt.subplots(figsize=(6.4,6.4)); ax.axis("off")
    fig.patch.set_facecolor("white")
    ax.add_patch(plt.Rectangle((0,0.88),1,0.12,transform=ax.transAxes,color=accent,zorder=0))
    ax.text(0.5,0.94,title,transform=ax.transAxes,ha="center",va="center",
            fontsize=17,fontweight="bold",color="white")
    y=0.80
    for head,body in lines:
        ax.text(0.07,y,head,transform=ax.transAxes,fontsize=14,fontweight="bold",color=accent)
        y-=0.075
        for bl in body:
            ax.text(0.10,y,bl,transform=ax.transAxes,fontsize=12,color=NAVY)
            y-=0.062
        y-=0.03
    ax.text(0.5,0.03,"VolPred · volpred.zeabur.app · 波動率定價觀察，非投資建議",
            transform=ax.transAxes,ha="center",fontsize=8.5,color=GREY)
    plt.savefig(f"{OUT}/{fn}",dpi=140,bbox_inches="tight",facecolor="white"); plt.close()

h=R["hist_earnings_moves"]; sk=R["skew_5pct_back"]
poster("lazypack_1_concept.png","懶人包①　法說會前在看什麼",
 [("問題",["法說會這種大事前，","選擇權貴不貴？"]),
  ("貴 = 市場預期會大震",["便宜 = 沒人覺得會有意外"]),
  ("量法",["比較「含法說會」與「不含」","兩張到期日的隱含波動率"]),
  ("台積電 ADR (TSM)",[f"現價 ${R['spot']}｜法說會 {R['earnings_date']}"])],BLUE)

poster("lazypack_2_method.png","懶人包②　怎麼拆法說會溢價",
 [("步驟 1",[f"7/10 到期(法說前) IV = {R['front_atm_iv_pct']}%"]),
  ("步驟 2",[f"7/17 到期(含法說) IV = {R['back_atm_iv_pct']}%"]),
  ("步驟 3 · 法說凸起",[f"差 = +{R['earnings_vol_premium_pp']} 個百分點"]),
  ("步驟 4 · 變異數拆解",[f"還原成單日跳動 ≈ ±{R['earnings_isolated_implied_move_pct']}%"]),
  ("對照歷史",[f"近 {h['n']} 次法說單日 均 {h['avg_abs_1d_pct']}%、中位 {h['median_abs_1d_pct']}%"])],ORANGE)

poster("lazypack_3_results.png","懶人包③　三個數字帶走",
 [("① 法說溢價很淡",[f"+{R['earnings_vol_premium_pp']}pp ≈ 單日±{R['earnings_isolated_implied_move_pct']}%","低於歷史平均 "+str(h['avg_abs_1d_pct'])+"%"]),
  ("② 溢價幾乎歸零",[f"IV {R['back_atm_iv_pct']}% ≈ 已實現 {R['rv20_pct']}%","差 "+str(R['iv_rv_gap_back_pp'])+"pp，股票本來就在狂震"]),
  ("③ 偏斜偏買權端",[f"賣權 {sk['otm_put_iv']}% < 買權 {sk['otm_call_iv']}%","市場擔憂在上檔，不在毛利崩"])],GREEN)
print("charts+lazypack rendered")
import os
for f in ["chart_main.png","lazypack_1_concept.png","lazypack_2_method.png","lazypack_3_results.png"]:
    print(f, os.path.getsize(f"{OUT}/{f}"), "bytes")
