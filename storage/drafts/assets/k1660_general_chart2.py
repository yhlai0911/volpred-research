import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
import json

# 中文字型
for fp in ["/System/Library/Fonts/PingFang.ttc","/System/Library/Fonts/STHeiti Medium.ttc"]:
    try:
        font_manager.fontManager.addfont(fp)
    except Exception:
        pass
plt.rcParams["font.sans-serif"] = ["PingFang HK","PingFang SC","Heiti TC","Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False

R = json.load(open("experiments/k1660_mz_calibration_audit/k1660_mz_calibration_audit_results.json"))
bc = R["flagship_bias_correction"]
fams = ["GARCH(1,1)","GJR-GARCH","EGARCH","CGARCH"]
imp = [bc[f]["bias_correction_expanding_OOS"]["qlike_improvement_pct"] for f in fams]
dmp = [bc[f]["bias_correction_expanding_OOS"]["dm_p"] for f in fams]

fig, ax = plt.subplots(figsize=(8,4.6))
colors = ["#4C72B0" if p>0.05 else "#C44E52" for p in dmp]
bars = ax.bar(fams, imp, color=colors, edgecolor="black", linewidth=0.6)
ax.axhline(0, color="#333", linewidth=0.8)
for b,v,p in zip(bars,imp,dmp):
    ax.text(b.get_x()+b.get_width()/2, v + (0.4 if v>=0 else -0.9),
            f"{v:+.1f}%\n(p={p:.2f})", ha="center", va="bottom" if v>=0 else "top", fontsize=9)
ax.set_ylabel("樣本外 QLIKE 改善 %（正=校正後更準）")
ax.set_title("事後線性校正在樣本外幾乎沒用：\n旗艦 SPY 四家族，唯一大改善（EGARCH +17%）統計上仍不顯著", fontsize=11)
ax.set_ylim(min(imp)-3, max(imp)+4)
ax.text(0.5,-0.22,"藍=DM 檢定不顯著（p>0.05）；改善多半是雜訊，不是真本事。資料：VolPred K1660，SPY 2023-24 OOS",
        transform=ax.transAxes, ha="center", fontsize=8, color="#666")
plt.tight_layout()
plt.savefig("storage/drafts/assets/k1660_general_biascorr.png", dpi=130, bbox_inches="tight")
print("saved", imp, dmp)
