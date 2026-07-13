"""懶人包圖組 for digest 2026-07-13. All numbers read from results.json (no hand-keying)."""
import json
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
import numpy as np, os

for fp in ["/System/Library/Fonts/PingFang.ttc"]:
    try: font_manager.fontManager.addfont(fp)
    except Exception: pass  # silent-ok: 中文字型註冊失敗只影響圖表字型 fallback，不影響數據
plt.rcParams["font.sans-serif"] = ["PingFang HK", "PingFang TC", "Heiti TC", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False

R = json.load(open("experiments/digest_20260713/leading_signal_audit_results.json"))
OUT = "experiments/digest_20260713/digest_20260713_lazypack"
os.makedirs(OUT, exist_ok=True)
BG, INK, BLUE, RED, GREY = "#f8fafc", "#0f172a", "#2563eb", "#ef4444", "#94a3b8"

short = {"vix": "VIX 指數", "volume_z": "成交量擁擠度", "credit": "信用利差代理",
         "vxn_gap": "科技恐慌溢價", "bondvol_gap": "股債波動分歧", "vvix_proxy": "波動的波動"}

# --- panel 1: 四道體檢（概念）---
fig, ax = plt.subplots(figsize=(9, 11.5)); fig.patch.set_facecolor(BG); ax.axis("off")
ax.text(.5, .955, "預警訊號的四道體檢", ha="center", size=30, weight="bold", color=INK)
ax.text(.5, .915, "一個「先行指標」要能拿來做決定，四關缺一不可", ha="center", size=14, color="#475569")
gates = [
    ("① 它真的先動嗎？", "訊號要領先，不是同時發生。\n同時發生的叫描述，不叫預警。"),
    ("② 領先期久到你來得及做事嗎？", "領先半天，你來不及調倉。\n本文一律用「未來 5 個交易日」當標準。"),
    ("③ 扣掉噪音後還在嗎？", "同時測很多格，總會有幾格好看。\n必須做多重檢定校正（Holm）。"),
    ("④ 它只是把「當下波動」換句話說嗎？", "最常見的假訊號：訊號跟今天的波動高度重疊。\n要問的是「多告訴我什麼」，不是「像不像」。"),
]
y = .84
for t, s in gates:
    ax.add_patch(plt.Rectangle((.06, y - .155), .88, .145, facecolor="white", edgecolor="#cbd5e1", lw=1.4))
    ax.text(.10, y - .045, t, size=17, weight="bold", color=BLUE)
    ax.text(.10, y - .115, s, size=12.5, color="#334155", va="center")
    y -= .185
ax.text(.5, .085, "六個熱門訊號實測後：只有 VIX 四關全過", ha="center", size=17, weight="bold", color=RED)
ax.text(.5, .045, f"SPY {R['sample']['start']}–{R['sample']['end']}｜{R['sample']['n_days']:,} 個交易日",
        ha="center", size=11.5, color="#64748b")
fig.savefig(f"{OUT}/1_four_gates.png", dpi=150, facecolor=BG, bbox_inches="tight"); plt.close(fig)

# --- panel 2: 增量體檢結果 ---
fig, ax = plt.subplots(figsize=(9, 11.5)); fig.patch.set_facecolor(BG)
ax.set_position([.30, .10, .64, .70])
sig = sorted(R["signals"], key=lambda d: d["incremental_r2_pp"])
lab = [short[s["signal"]] for s in sig]
val = [s["incremental_r2_pp"] for s in sig]
ok = [s["holm_significant"] for s in sig]
ax.barh(lab, val, color=[BLUE if o else "#cbd5e1" for o in ok], height=.62)
for i, (v, o) in enumerate(zip(val, ok)):
    ax.text(v + .35, i, f"+{v:.2f} pp" + ("" if o else "  (不顯著)"), va="center", size=12,
            color=INK if o else "#94a3b8", weight="bold" if o else "normal")
ax.set_xlim(0, max(val) * 1.45)
ax.set_xlabel("增量解釋力（百分點）", size=12)
ax.tick_params(labelsize=13)
ax.grid(axis="x", alpha=.25); ax.set_facecolor("white")
fig.text(.5, .94, "扣掉「當下波動」之後，還剩多少？", ha="center", size=26, weight="bold", color=INK)
fig.text(.5, .90, "相對「只看過去 20 日已實現波動」的 R² 增加量", ha="center", size=13, color="#475569")
fig.text(.5, .055, "藍＝Holm 多重檢定校正後仍顯著；灰＝校正後不成立", ha="center", size=12, color="#475569")
fig.text(.5, .022, f"目標：SPY 未來 5 日已實現波動｜HAC lag={R['hac_lag']}｜n={R['sample']['n_days']:,}",
         ha="center", size=11, color="#64748b")
fig.savefig(f"{OUT}/2_incremental.png", dpi=150, facecolor=BG); plt.close(fig)

# --- panel 3: 體制 > 訊號 + 本週檢查表 ---
fig, ax = plt.subplots(figsize=(9, 11.5)); fig.patch.set_facecolor(BG); ax.axis("off")
ax.text(.5, .965, "先認體制，再看訊號", ha="center", size=28, weight="bold", color=INK)
ax.text(.5, .925, "VIX 三分位 → 接下來一週的震幅", ha="center", size=14, color="#475569")
sub = fig.add_axes([.16, .55, .72, .27]); sub.set_facecolor("white")
t = R["vix_tercile_forward_rv"]; keys = list(t.keys())
x = np.arange(len(keys))
sub.bar(x, [t[k]["mean"] for k in keys], .55, color=[BLUE, "#60a5fa", RED])
for i, k in enumerate(keys):
    sub.text(i, t[k]["mean"] + .4, f'{t[k]["mean"]:.1f}%', ha="center", size=13, weight="bold")
sub.set_xticks(x); sub.set_xticklabels(keys, size=11.5)
sub.set_ylabel("未來 5 日已實現波動（年化）", size=11)
sub.grid(axis="y", alpha=.25)
ax.text(.5, .50, "VIX 高的那三分之一日子，未來一週的震幅是\n"
                 f"安靜組的 {t[keys[2]]['mean']/t[keys[0]]['mean']:.1f} 倍。這比任何「先行指標」都穩定。",
        ha="center", size=13.5, color="#334155")
ax.text(.06, .40, "本週事件密集期，該做的三件事", size=18, weight="bold", color=INK)
todo = [
    "1. 先看體制（VIX 現在在哪一格），再看訊號。",
    "2. 事件日不要為了躲而砍倉。實測下來 Sharpe 只會變差。",
    "3. 訊號給你「多少」，不是「哪一天」。用它調部位大小，不是猜方向。",
]
yy = .335
for s in todo:
    ax.text(.08, yy, s, size=13.5, color="#334155"); yy -= .055
ax.text(.5, .11, "VolPred｜volpred.zeabur.app", ha="center", size=12, color="#64748b")
ax.text(.5, .07, "資料：yfinance daily｜本文不構成投資建議", ha="center", size=10.5, color="#94a3b8")
fig.savefig(f"{OUT}/3_regime_checklist.png", dpi=150, facecolor=BG); plt.close(fig)
print("lazypack ok")
