"""Generate K1118b charts from results JSON."""
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

OUT_DIR = Path(__file__).parent
RES = json.load(open(OUT_DIR / "k1118b_results.json"))

plt.rcParams["figure.dpi"] = 110
plt.rcParams["savefig.dpi"] = 140
plt.rcParams["font.family"] = "DejaVu Sans"


def fig1_dm_matrix():
    """Heatmap: IV vs AR1 DM t-stat, across (asset × IV source)."""
    assets = ["EUR_USD", "JPY_USD", "DXY"]
    iv_labels_by_asset = {
        "EUR_USD": ["Native_EVZ", "Cross_VIX", "Realized30"],
        "JPY_USD": ["Cross_VIX", "Cross_EVZ", "Realized30"],
        "DXY": ["Native_EVZ", "Cross_VIX", "Realized30"],
    }
    all_labels = ["Native_EVZ", "Cross_VIX", "Cross_EVZ", "Realized30"]
    M = np.full((len(assets), len(all_labels)), np.nan)
    for i, a in enumerate(assets):
        by_iv = RES["asset_results"][a]["by_iv"]
        for j, lbl in enumerate(all_labels):
            if lbl in by_iv:
                t = by_iv[lbl]["iv_vs_ar1_DM"]["t_stat"]
                if t is not None:
                    M[i, j] = t

    fig, ax = plt.subplots(figsize=(7.2, 3.8))
    vmax = max(abs(np.nanmin(M)), abs(np.nanmax(M)))
    im = ax.imshow(M, cmap="RdBu_r", vmin=-vmax, vmax=vmax, aspect="auto")
    for i in range(M.shape[0]):
        for j in range(M.shape[1]):
            v = M[i, j]
            if np.isnan(v):
                ax.text(j, i, "—", ha="center", va="center", color="gray", fontsize=9)
            else:
                color = "white" if abs(v) > vmax * 0.55 else "black"
                marker = "***" if abs(v) > 3.0 else ("**" if abs(v) > 2.0 else "")
                ax.text(
                    j, i, f"{v:+.2f}{marker}",
                    ha="center", va="center", color=color, fontsize=10, fontweight="bold",
                )
    ax.set_xticks(range(len(all_labels)))
    ax.set_xticklabels(all_labels, rotation=20)
    ax.set_yticks(range(len(assets)))
    ax.set_yticklabels(assets)
    cb = plt.colorbar(im, ax=ax)
    cb.set_label("DM-HLN t-statistic (positive = IV beats AR1)")
    ax.set_title(
        "K1118b: Does implied-vol beat AR(1) in FX weekly RV?\n"
        "Harvey |t|>2 (**), |t|>3 (***); gray dash = source unavailable",
        fontsize=10,
    )
    plt.tight_layout()
    plt.savefig(OUT_DIR / "k1118b_dm_heatmap.png")
    plt.close(fig)


def fig2_qlike_comparison():
    """OOS QLIKE per asset/IV, 5 models."""
    assets = ["EUR_USD", "JPY_USD", "DXY"]
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.2), sharey=False)
    for ax, asset in zip(axes, assets):
        ar = RES["asset_results"][asset]
        iv_list = list(ar["by_iv"].keys())
        width = 0.25
        xs = np.arange(5)
        model_order = ["M1_AR1", "M2_AR1_IV", "M3_AR1_EPU", "M4_AR1_FinStress", "M5_AR1_All"]
        for i, lbl in enumerate(iv_list):
            qs = [ar["by_iv"][lbl]["is_oos_comparison"][m]["OOS_QLIKE"] for m in model_order]
            ax.bar(xs + i * width, qs, width=width, label=lbl)
        ax.set_xticks(xs + width)
        ax.set_xticklabels([m.replace("_AR1", "") for m in model_order], rotation=20)
        ax.set_title(f"{asset} (n_OOS~323)")
        ax.set_ylabel("OOS QLIKE (lower better)")
        ax.legend(fontsize=8, loc="best")
        ax.grid(axis="y", alpha=0.3)
    fig.suptitle(
        "K1118b: OOS QLIKE across 3 FX × 5 models × 3 IV sources (2019-2025 weekly)",
        fontsize=11,
    )
    plt.tight_layout()
    plt.savefig(OUT_DIR / "k1118b_qlike_comparison.png")
    plt.close(fig)


def fig3_var_trinity():
    """VaR Trinity pass/fail matrix at 5% and 1%."""
    assets = ["EUR_USD", "JPY_USD", "DXY"]
    rows = []
    cols = ["alpha_0.05", "alpha_0.01"]
    labels = []
    for a in assets:
        for lbl in RES["asset_results"][a]["by_iv"]:
            vr = RES["asset_results"][a]["by_iv"][lbl].get("var_trinity_M2", {})
            labels.append(f"{a} / {lbl}")
            row = []
            for c in cols:
                v = vr.get(c, {})
                if not v:
                    row.append(np.nan)
                else:
                    # Encode: 2 = Green+trinity, 1 = Green only or trinity-P but light
                    # 0 = Yellow; -1 = Red
                    pass_ = v.get("trinity_PASS", False)
                    light = v.get("Basel_light", "")
                    kp = v.get("Kupiec_p", 0) or 0
                    cp = v.get("Christoffersen_p", 0) or 0
                    if pass_:
                        score = 2
                    elif light == "Green":
                        score = 1
                    elif light == "Yellow":
                        score = 0
                    else:
                        score = -1
                    row.append(score)
            rows.append(row)
    M = np.array(rows)
    fig, ax = plt.subplots(figsize=(7.5, 4.8))
    cmap = plt.cm.RdYlGn
    im = ax.imshow(M, cmap=cmap, vmin=-1, vmax=2, aspect="auto")
    for i in range(M.shape[0]):
        for j in range(M.shape[1]):
            v = M[i, j]
            if np.isnan(v):
                txt = "—"
            elif v == 2:
                txt = "Trinity\nPASS"
            elif v == 1:
                txt = "Green\n(partial)"
            elif v == 0:
                txt = "Yellow"
            else:
                txt = "RED"
            ax.text(j, i, txt, ha="center", va="center", fontsize=8, fontweight="bold")
    ax.set_xticks(range(len(cols)))
    ax.set_xticklabels(["5% VaR", "1% VaR"])
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(labels, fontsize=9)
    ax.set_title(
        "K1118b: VaR Trinity (Kupiec+Christoffersen+Basel) on M2 (AR1+IV) OOS",
        fontsize=10,
    )
    plt.tight_layout()
    plt.savefig(OUT_DIR / "k1118b_var_trinity.png")
    plt.close(fig)


if __name__ == "__main__":
    fig1_dm_matrix()
    fig2_qlike_comparison()
    fig3_var_trinity()
    print(f"Charts saved in {OUT_DIR}")
