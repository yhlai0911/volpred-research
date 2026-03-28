"""
Shared chart generation + Supabase upload for feed articles.

Usage:
    from volpred.charts import generate_bar_chart, upload_chart, embed_chart

    # 1. Generate
    path = generate_bar_chart(
        labels=["GJR", "HAR", "EWMA"],
        values=[0.56, 0.74, 0.62],
        title="QLIKE Comparison",
        ylabel="QLIKE (lower = better)",
        filename="qlike_comparison",
    )

    # 2. Upload to Supabase Storage
    url = upload_chart(path)

    # 3. Embed in article content
    content = embed_chart(content, url, "QLIKE 模型比較圖")
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


# ─── Style defaults ─────────────────────────────────────────
_FONT_CANDIDATES = ["PingFang HK", "PingFang TC", "Heiti TC", "Arial Unicode MS", "Noto Sans CJK SC", "STHeiti", "sans-serif"]
_COLORS = ["#2196F3", "#FF9800", "#4CAF50", "#F44336", "#9C27B0", "#00BCD4", "#795548", "#607D8B"]
_DPI = 150
_CHART_DIR = Path("/tmp/volpred_charts")


def _setup_style():
    """Configure matplotlib for CJK + clean style."""
    plt.rcParams["font.sans-serif"] = _FONT_CANDIDATES
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["figure.facecolor"] = "white"
    plt.rcParams["axes.facecolor"] = "white"
    plt.rcParams["axes.grid"] = True
    plt.rcParams["grid.alpha"] = 0.3


def _save(fig, filename: str) -> str:
    """Save figure and return path."""
    _CHART_DIR.mkdir(exist_ok=True)
    uid = uuid.uuid4().hex[:6]
    path = _CHART_DIR / f"{filename}_{uid}.png"
    fig.savefig(path, dpi=_DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return str(path)


# ─── Chart generators ────────────────────────────────────────

def generate_bar_chart(
    labels: list[str],
    values: list[float],
    title: str = "",
    ylabel: str = "",
    xlabel: str = "",
    filename: str = "bar_chart",
    figsize: tuple = (10, 6),
    highlight_best: bool = True,
    horizontal: bool = False,
) -> str:
    """Generate a bar chart. Returns PNG file path."""
    _setup_style()
    fig, ax = plt.subplots(figsize=figsize)

    colors = [_COLORS[i % len(_COLORS)] for i in range(len(labels))]
    if highlight_best and values:
        best_idx = np.argmin(values) if "lower" in ylabel.lower() or "qlike" in ylabel.lower() else np.argmax(values)
        colors[best_idx] = "#E91E63"

    if horizontal:
        bars = ax.barh(labels, values, color=colors, edgecolor="white", linewidth=0.5)
        ax.set_xlabel(xlabel or ylabel)
    else:
        bars = ax.bar(labels, values, color=colors, edgecolor="white", linewidth=0.5)
        ax.set_ylabel(ylabel)
        ax.set_xlabel(xlabel)
        plt.xticks(rotation=45, ha="right")

    if title:
        ax.set_title(title, fontsize=14, fontweight="bold", pad=15)

    # Value labels
    for bar, val in zip(bars, values):
        if horizontal:
            ax.text(bar.get_width() + max(values) * 0.01, bar.get_y() + bar.get_height() / 2,
                    f"{val:.3f}" if abs(val) < 10 else f"{val:.1f}",
                    va="center", fontsize=9)
        else:
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + max(values) * 0.01,
                    f"{val:.3f}" if abs(val) < 10 else f"{val:.1f}",
                    ha="center", va="bottom", fontsize=9)

    fig.tight_layout()
    return _save(fig, filename)


def generate_grouped_bar_chart(
    labels: list[str],
    group_data: dict[str, list[float]],
    title: str = "",
    ylabel: str = "",
    filename: str = "grouped_bar",
    figsize: tuple = (12, 6),
) -> str:
    """Generate grouped bar chart. group_data = {'Group A': [v1,v2,...], 'Group B': [...]}."""
    _setup_style()
    fig, ax = plt.subplots(figsize=figsize)

    x = np.arange(len(labels))
    n_groups = len(group_data)
    width = 0.8 / n_groups

    for i, (group_name, values) in enumerate(group_data.items()):
        offset = (i - n_groups / 2 + 0.5) * width
        bars = ax.bar(x + offset, values, width, label=group_name,
                      color=_COLORS[i % len(_COLORS)], edgecolor="white", linewidth=0.5)

    ax.set_ylabel(ylabel)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.legend()
    if title:
        ax.set_title(title, fontsize=14, fontweight="bold", pad=15)

    fig.tight_layout()
    return _save(fig, filename)


def generate_line_chart(
    x_data: list,
    y_data: dict[str, list[float]],
    title: str = "",
    xlabel: str = "",
    ylabel: str = "",
    filename: str = "line_chart",
    figsize: tuple = (12, 6),
) -> str:
    """Generate line chart. y_data = {'Series A': [...], 'Series B': [...]}."""
    _setup_style()
    fig, ax = plt.subplots(figsize=figsize)

    for i, (name, values) in enumerate(y_data.items()):
        ax.plot(x_data[:len(values)], values, label=name,
                color=_COLORS[i % len(_COLORS)], linewidth=2)

    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.legend()
    if title:
        ax.set_title(title, fontsize=14, fontweight="bold", pad=15)

    fig.tight_layout()
    return _save(fig, filename)


def generate_heatmap(
    data: list[list[float]],
    row_labels: list[str],
    col_labels: list[str],
    title: str = "",
    filename: str = "heatmap",
    figsize: tuple = (10, 8),
    fmt: str = ".2f",
    cmap: str = "RdYlGn_r",
) -> str:
    """Generate heatmap. Returns PNG path."""
    _setup_style()
    fig, ax = plt.subplots(figsize=figsize)

    arr = np.array(data)
    im = ax.imshow(arr, cmap=cmap, aspect="auto")
    fig.colorbar(im, ax=ax, shrink=0.8)

    ax.set_xticks(range(len(col_labels)))
    ax.set_yticks(range(len(row_labels)))
    ax.set_xticklabels(col_labels, rotation=45, ha="right")
    ax.set_yticklabels(row_labels)

    # Annotate cells
    for i in range(len(row_labels)):
        for j in range(len(col_labels)):
            ax.text(j, i, f"{arr[i, j]:{fmt}}", ha="center", va="center",
                    fontsize=9, color="black" if 0.3 < (arr[i, j] - arr.min()) / (arr.max() - arr.min() + 1e-9) < 0.7 else "white")

    if title:
        ax.set_title(title, fontsize=14, fontweight="bold", pad=15)

    fig.tight_layout()
    return _save(fig, filename)


# ─── Supabase upload ─────────────────────────────────────────

def upload_chart(png_path: str, bucket: str = "article-images") -> str:
    """Upload PNG to Supabase Storage, return public URL.

    Requires SUPABASE_URL and SUPABASE_KEY in environment or .env file.
    """
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        # dotenv not available, rely on environment variables
        pass

    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "") or os.environ.get("SUPABASE_KEY", "")

    # Try loading from .env.local or .env if not in environment
    if not url or not key:
        for env_file in [".env.local", ".env"]:
            env_path = Path(__file__).resolve().parents[3] / env_file
            if env_path.exists():
                for line in env_path.read_text().splitlines():
                    if "=" in line and not line.startswith("#"):
                        k, v = line.strip().split("=", 1)
                        if k == "SUPABASE_URL" and not url:
                            url = v
                        if k in ("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_KEY") and not key:
                            key = v

    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set (env or .env)")

    import requests

    filename = Path(png_path).name
    storage_path = f"{bucket}/{filename}"

    with open(png_path, "rb") as f:
        resp = requests.post(
            f"{url}/storage/v1/object/{storage_path}",
            headers={
                "Authorization": f"Bearer {key}",
                "apikey": key,
                "Content-Type": "image/png",
                "x-upsert": "true",
            },
            data=f.read(),
            timeout=30,
        )

    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Upload failed ({resp.status_code}): {resp.text[:200]}")

    public_url = f"{url}/storage/v1/object/public/{storage_path}"
    return public_url


# ─── Content embedding ───────────────────────────────────────

def embed_chart(content: str, chart_url: str, description: str, position: str = "after_summary") -> str:
    """Insert chart markdown image into article content.

    position: 'after_summary' (default), 'before_conclusion', 'append'
    """
    img_md = f"\n\n![{description}]({chart_url})\n\n"

    if position == "append":
        return content + img_md
    elif position == "before_conclusion":
        markers = ["## 結論", "## 結語", "## Conclusion"]
        for m in markers:
            if m in content:
                return content.replace(m, img_md + m)
        return content + img_md
    else:  # after_summary
        markers = ["## 研究背景", "## 背景", "## 核心發現", "---"]
        for m in markers:
            idx = content.find(m)
            if idx > 0:
                return content[:idx] + img_md + content[idx:]
        # Fallback: after first heading
        lines = content.split("\n")
        for i, line in enumerate(lines):
            if line.startswith("## ") and i > 0:
                return "\n".join(lines[:i]) + img_md + "\n".join(lines[i:])
        return img_md + content
