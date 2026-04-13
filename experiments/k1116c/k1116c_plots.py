"""K1116c plots: DM t-stat heatmap across variants + PIT vs weekly-mean value diff."""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

HERE = Path(__file__).parent
DATA_DIR = HERE / "data"

plt.rcParams.update({"figure.dpi": 100, "font.size": 10})


def plot_dm_heatmap():
    with open(HERE / "k1116c_results.json") as f:
        res = json.load(f)
    dm = res["dm_vs_vix_baseline"]

    variants = ["orig_shift1", "corrected_shift2", "conservative_shift2",
                "pit_shift0", "pit_shift1", "multi_lag_3"]
    specs = ["base", "epu", "finstress", "all"]

    T = np.zeros((len(variants), len(specs)))
    for i, v in enumerate(variants):
        for j, s in enumerate(specs):
            cell = dm.get(v, {}).get(s, {})
            T[i, j] = cell.get("t") if cell.get("t") is not None else np.nan

    fig, ax = plt.subplots(figsize=(9, 5.5))
    # center at 0, red=negative (baseline wins), green=positive (alt-data wins)
    vmax = max(abs(np.nanmin(T)), abs(np.nanmax(T)), 4)
    im = ax.imshow(T, aspect="auto", cmap="RdYlGn", vmin=-vmax, vmax=vmax)
    ax.set_xticks(range(len(specs)))
    ax.set_xticklabels(specs)
    ax.set_yticks(range(len(variants)))
    ax.set_yticklabels(variants)
    for i in range(len(variants)):
        for j in range(len(specs)):
            val = T[i, j]
            if np.isnan(val):
                continue
            txt_color = "black" if abs(val) < vmax * 0.5 else "white"
            ax.text(j, i, f"{val:+.2f}", ha="center", va="center", color=txt_color, fontsize=10)

    # mark Harvey |t|>3 threshold cells with bold border
    for i in range(len(variants)):
        for j in range(len(specs)):
            if not np.isnan(T[i, j]) and abs(T[i, j]) > 3.0:
                rect = plt.Rectangle((j - 0.5, i - 0.5), 1, 1, fill=False,
                                     edgecolor="blue", linewidth=2)
                ax.add_patch(rect)

    ax.set_xlabel("Spec (vs M2_vix baseline)")
    ax.set_title("K1116c DM-HLN t-stats across lag/PIT variants\n"
                 "Blue border = Harvey |t|>3 ; Green = alt beats VIX ; Red = VIX wins")
    plt.colorbar(im, ax=ax, label="DM t-stat")
    plt.tight_layout()
    plt.savefig(HERE / "k1116c_dm_heatmap.png", dpi=120, bbox_inches="tight")
    plt.close()
    print(f"saved {HERE / 'k1116c_dm_heatmap.png'}")


def plot_vintage_vs_weekly_mean_diff():
    """Visualize the difference between weekly-mean and PIT values for each indicator."""
    indicators = ["USEPU", "WLEMU", "NFCI", "ANFCI", "STLFSI"]
    fig, axes = plt.subplots(len(indicators), 1, figsize=(10, 2.0 * len(indicators)), sharex=True)

    for ax, ind in zip(axes, indicators):
        rel = pd.read_csv(DATA_DIR / f"{ind}_with_release_date.csv",
                          parse_dates=["DATE", "RELEASE_DATE"])
        rel["week"] = rel["DATE"].dt.to_period("W-FRI").dt.to_timestamp("W-FRI")
        wm = rel.groupby("week")["VALUE"].mean()

        pit = pd.read_csv(DATA_DIR / f"{ind}_weekly_pit.csv",
                          parse_dates=["week_end", "obs_date", "release_date"])
        pit_s = pit.set_index("week_end")["value"]

        # Align and filter to 2018-2026
        merged = pd.concat([wm.rename("weekly_mean"), pit_s.rename("pit")], axis=1)
        merged = merged.loc["2018-01-01":"2026-04-13"]

        ax.plot(merged.index, merged["weekly_mean"], label="weekly-mean (K1116 style)",
                lw=0.8, alpha=0.8, color="steelblue")
        ax.plot(merged.index, merged["pit"], label="PIT (release-aware)", lw=0.8,
                alpha=0.8, color="darkorange", linestyle="--")
        ax.set_title(f"{ind}")
        ax.set_ylabel("value")
        ax.grid(alpha=0.3)
        if ax == axes[0]:
            ax.legend(loc="upper right", fontsize=9)
    axes[-1].set_xlabel("Date")
    plt.suptitle("K1116c: Weekly-mean vs Point-in-Time alignment\n"
                 "(difference = latent lookahead removed)", y=1.00)
    plt.tight_layout()
    plt.savefig(HERE / "k1116c_pit_vs_weekly.png", dpi=120, bbox_inches="tight")
    plt.close()
    print(f"saved {HERE / 'k1116c_pit_vs_weekly.png'}")


def main():
    plot_dm_heatmap()
    plot_vintage_vs_weekly_mean_diff()


if __name__ == "__main__":
    main()
