#!/usr/bin/env python3
"""Render lazypack PNG panels for mile_3303f340 article.

This script reads evidence JSON and plan JSON dynamically and renders 3 panels:
- 1_concept.png
- 2_results.png
- 3_takeaway.png
"""

import json
import os
from pathlib import Path
import textwrap

import matplotlib
matplotlib.use("Agg")
import matplotlib.patches as patches
import matplotlib.pyplot as plt

# Absolute paths to evidence & plan files
EVIDENCE_JSON_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1600/k1600_results.json"
)
PLAN_JSON_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_3303f340/runs/lazypack-mile_3303f340/plan.json"
)
OUT_DIR = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_3303f340/runs/lazypack-mile_3303f340/panels"
)

# Set traditional Chinese font settings for macOS
plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False


def get_json_value(data: dict, path_str: str):
  """Resolve dot-separated path in JSON data dict.

  Raises KeyError/IndexError if key is missing.
  """
  parts = path_str.split(".")
  curr = data
  for p in parts:
    if isinstance(curr, list):
      p = int(p)
      curr = curr[p]
    elif isinstance(curr, dict):
      if p not in curr:
        raise KeyError(f"Key '{p}' not found in JSON path '{path_str}'")
      curr = curr[p]
    else:
      raise KeyError(f"Invalid path step '{p}' in '{path_str}'")
  return curr


def create_base_fig():
  fig, ax = plt.subplots(figsize=(16, 10), dpi=100)
  ax.set_xlim(0, 16)
  ax.set_ylim(0, 10)
  ax.axis("off")
  fig.patch.set_facecolor("#F8FAFC")  # Slate 50 background
  return fig, ax


def draw_header(ax, title: str, subtitle: str, badge_text: str = "VolPred 懶人包"):
  # Header Badge
  badge = patches.FancyBboxPatch(
      (0.8, 9.1),
      2.2,
      0.45,
      boxstyle="round,pad=0.05,rounding_size=0.15",
      facecolor="#4338CA",
      edgecolor="none",
  )
  ax.add_patch(badge)
  ax.text(
      1.9,
      9.325,
      badge_text,
      color="white",
      fontsize=13,
      fontweight="bold",
      ha="center",
      va="center",
  )

  # Title
  ax.text(
      0.8,
      8.55,
      title,
      color="#0F172A",
      fontsize=24,
      fontweight="bold",
      va="top",
  )

  # Subtitle
  ax.text(0.8, 8.0, subtitle, color="#475569", fontsize=14, va="top")

  # Header Divider
  ax.plot([0.8, 15.2], [7.7, 7.7], color="#E2E8F0", linewidth=1.5)


def draw_footer(ax, source_label: str):
  ax.plot([0.8, 15.2], [0.85, 0.85], color="#E2E8F0", linewidth=1.5)
  footer_text = f"資料來源：{source_label}"
  ax.text(
      0.8,
      0.5,
      footer_text,
      color="#64748B",
      fontsize=12,
      fontweight="bold",
      va="center",
  )


def render_panel1(results_data: dict, plan_label: str, out_dir: Path):
  fig, ax = create_base_fig()
  draw_header(
      ax,
      title="這個修正法在修什麼",
      subtitle="說明基準模型的弱點、修正法的想法，以及本次改用日頻資料代理的限制",
  )

  # Main Left Text Box
  box_left = patches.FancyBboxPatch(
      (0.8, 1.2),
      9.4,
      6.2,
      boxstyle="round,pad=0.1,rounding_size=0.2",
      facecolor="#FFFFFF",
      edgecolor="#CBD5E1",
      linewidth=1.5,
  )
  ax.add_patch(box_left)

  # Header bar inside left box
  header_left = patches.FancyBboxPatch(
      (0.8, 6.7),
      9.4,
      0.7,
      boxstyle="round,pad=0.1,rounding_size=0.2",
      facecolor="#EFF6FF",
      edgecolor="#93C5FD",
      linewidth=1.5,
  )
  ax.add_patch(header_left)
  ax.text(
      1.1,
      7.05,
      "一句話直覺",
      color="#1D4ED8",
      fontsize=16,
      fontweight="bold",
      va="center",
  )

  body_lines = [
      (
          "常用模型弱點",
          (
              "常用的波動預測模型把「昨天的波動」當成一個固定可信的數字。"
              "但那個數字本身是估出來的——有時候乾淨，有時候被少數幾筆離譜跳動污染。"
          ),
      ),
      (
          "修正法核心",
          (
              "學界的修正法是：偵測昨天那個讀數的雜訊有多大，雜訊大就自動少信它一點。"
              "原始論文用的是日內逐筆資料。"
          ),
      ),
      (
          "本次代理限制",
          (
              "我們手上只有日收盤價，所以做的是它的低頻代理版。"
              "這一步就決定了結論的邊界：代理版沒效，不代表原版沒效。"
          ),
      ),
  ]

  y_cursor = 6.2
  for label, text in body_lines:
    tag_bg = patches.FancyBboxPatch(
        (1.1, y_cursor - 0.1),
        2.0,
        0.35,
        boxstyle="round,pad=0.05,rounding_size=0.1",
        facecolor="#DBEAFE",
        edgecolor="none",
    )
    ax.add_patch(tag_bg)
    ax.text(
        2.1,
        y_cursor + 0.075,
        label,
        color="#1E40AF",
        fontsize=12,
        fontweight="bold",
        ha="center",
        va="center",
    )

    clean_p = text.replace("**", "")
    wrapped = textwrap.fill(clean_p, width=36)
    ax.text(
        1.1,
        y_cursor - 0.3,
        wrapped,
        color="#334155",
        fontsize=12,
        linespacing=1.4,
        va="top",
    )
    y_cursor -= 1.65

  # Right Side Metrics
  m1_val = (
      str(get_json_value(results_data, "assets_results.0.n_returns")) + " 筆"
  )
  card1 = patches.FancyBboxPatch(
      (10.6, 4.5),
      4.6,
      2.9,
      boxstyle="round,pad=0.1,rounding_size=0.2",
      facecolor="#FFFFFF",
      edgecolor="#CBD5E1",
      linewidth=1.5,
  )
  ax.add_patch(card1)
  ax.text(
      10.9,
      6.9,
      "美股大盤的日報酬筆數",
      color="#475569",
      fontsize=14,
      fontweight="bold",
      va="top",
  )
  ax.text(
      10.9,
      5.7,
      m1_val,
      color="#2563EB",
      fontsize=42,
      fontweight="bold",
      va="center",
  )
  ax.text(
      10.9,
      4.9,
      "標的：SPY / QQQ / 0050.TW 日資料",
      color="#94A3B8",
      fontsize=11,
      va="top",
  )

  m2_val = str(get_json_value(results_data, "verdict_detail.n_cells")) + " 格"
  card2 = patches.FancyBboxPatch(
      (10.6, 1.2),
      4.6,
      2.9,
      boxstyle="round,pad=0.1,rounding_size=0.2",
      facecolor="#FFFFFF",
      edgecolor="#CBD5E1",
      linewidth=1.5,
  )
  ax.add_patch(card2)
  ax.text(
      10.9,
      3.6,
      "測試格數",
      color="#475569",
      fontsize=14,
      fontweight="bold",
      va="top",
  )
  ax.text(
      10.9,
      2.4,
      m2_val,
      color="#059669",
      fontsize=42,
      fontweight="bold",
      va="center",
  )
  ax.text(
      10.9,
      1.6,
      "組合：3 個資產 × 3 個預測期 (1/5/22日)",
      color="#94A3B8",
      fontsize=11,
      va="top",
  )

  draw_footer(ax, plan_label)
  fig.savefig(
      out_dir / "1_concept.png",
      dpi=100,
      bbox_inches=None,
      facecolor=fig.get_facecolor(),
  )
  plt.close(fig)


def render_panel2(results_data: dict, plan_label: str, out_dir: Path):
  fig, ax = create_base_fig()
  draw_header(
      ax,
      title="指紋出現了，準確度沒有",
      subtitle="對照三項計數：預測改善顯著的格數、修正項係數顯著的格數、兩者同時成立的格數",
  )

  # Top Bento Text Box
  top_box = patches.FancyBboxPatch(
      (0.8, 5.0),
      14.4,
      2.4,
      boxstyle="round,pad=0.1,rounding_size=0.2",
      facecolor="#FFFFFF",
      edgecolor="#CBD5E1",
      linewidth=1.5,
  )
  ax.add_patch(top_box)

  t_badge = patches.FancyBboxPatch(
      (1.1, 6.75),
      2.5,
      0.4,
      boxstyle="round,pad=0.05,rounding_size=0.1",
      facecolor="#F1F5F9",
      edgecolor="#CBD5E1",
  )
  ax.add_patch(t_badge)
  ax.text(
      2.35,
      6.95,
      "三個數字要一起看",
      color="#334155",
      fontsize=13,
      fontweight="bold",
      ha="center",
      va="center",
  )

  p1 = (
      "第一個數字問：加了修正之後，預測有沒有真的變準？"
      "第二個問：修正項本身在資料裡看得見嗎？"
      "第三個問：有沒有哪一格是兩件事同時成立？"
  )
  p2 = "判準沿用文獻的嚴格門檻，並非常見的寬鬆標準。"

  ax.text(
      1.1,
      6.4,
      textwrap.fill(p1, width=42),
      color="#475569",
      fontsize=12,
      linespacing=1.4,
      va="top",
  )
  ax.text(
      1.1,
      5.35,
      textwrap.fill(p2, width=42),
      color="#64748B",
      fontsize=11.5,
      fontstyle="italic",
      va="top",
  )

  # Bottom 3 Bento Cards
  m1_val = (
      str(get_json_value(results_data, "verdict_detail.n_dm_harvey_sig"))
      + " 格"
  )
  m2_val = (
      str(get_json_value(results_data, "verdict_detail.n_beta1Q_harvey_sig"))
      + " 格"
  )
  m3_val = (
      str(get_json_value(results_data, "verdict_detail.n_joint_support"))
      + " 格"
  )

  cards_data = [
      (
          "指標 1",
          "預測顯著變準的格數",
          m1_val,
          "Diebold-Mariano 檢定\n門檻 |t| > 3.0",
          "#2563EB",
          "#EFF6FF",
          "#93C5FD",
      ),
      (
          "指標 2",
          "修正項係數顯著的格數",
          m2_val,
          "0050.TW (h=22) 達標\nt-stat = -3.105",
          "#7C3AED",
          "#F5F3FF",
          "#DDD6FE",
      ),
      (
          "核心檢定",
          "兩者同時成立的格數",
          m3_val,
          "兩條件同時成立: 0 格\n檢定結論: 未通過",
          "#D97706",
          "#FFFBEB",
          "#FDE68A",
      ),
  ]

  x_positions = [0.8, 5.7, 10.6]
  for x_pos, (tag, label, val, sub, color, bg, border) in zip(
      x_positions, cards_data, strict=True
  ):
    bento = patches.FancyBboxPatch(
        (x_pos, 1.2),
        4.6,
        3.5,
        boxstyle="round,pad=0.1,rounding_size=0.2",
        facecolor=bg,
        edgecolor=border,
        linewidth=1.5,
    )
    ax.add_patch(bento)

    t_bg = patches.FancyBboxPatch(
        (x_pos + 0.3, 4.1),
        1.5,
        0.35,
        boxstyle="round,pad=0.05,rounding_size=0.1",
        facecolor=color,
        edgecolor="none",
    )
    ax.add_patch(t_bg)
    ax.text(
        x_pos + 1.05,
        4.275,
        tag,
        color="white",
        fontsize=12,
        fontweight="bold",
        ha="center",
        va="center",
    )

    ax.text(
        x_pos + 0.3,
        3.7,
        label,
        color="#334155",
        fontsize=14,
        fontweight="bold",
        va="top",
    )

    ax.text(
        x_pos + 0.3,
        2.75,
        val,
        color=color,
        fontsize=48,
        fontweight="bold",
        va="center",
    )

    ax.text(
        x_pos + 0.3,
        1.9,
        sub,
        color="#64748B",
        fontsize=12,
        linespacing=1.3,
        va="top",
    )

  draw_footer(ax, plan_label)
  fig.savefig(
      out_dir / "2_results.png",
      dpi=100,
      bbox_inches=None,
      facecolor=fig.get_facecolor(),
  )
  plt.close(fig)


def render_panel3(results_data: dict, plan_label: str, out_dir: Path):
  fig, ax = create_base_fig()
  draw_header(
      ax,
      title="帶走的一句話",
      subtitle="說明係數顯著與預測改善是兩件事，以及代理版失敗不足以否定原版",
  )

  # Outer Main Card
  main_box = patches.FancyBboxPatch(
      (0.8, 1.2),
      14.4,
      6.2,
      boxstyle="round,pad=0.1,rounding_size=0.2",
      facecolor="#FFFFFF",
      edgecolor="#CBD5E1",
      linewidth=1.5,
  )
  ax.add_patch(main_box)

  # Header Banner
  header_banner = patches.FancyBboxPatch(
      (0.8, 6.6),
      14.4,
      0.8,
      boxstyle="round,pad=0.1,rounding_size=0.2",
      facecolor="#1E293B",
      edgecolor="none",
  )
  ax.add_patch(header_banner)
  ax.text(
      1.2,
      7.0,
      "係數看得見，不等於預測會變好",
      color="white",
      fontsize=18,
      fontweight="bold",
      va="center",
  )

  takeaway_blocks = [
      (
          "1. 指紋存在但無功",
          (
              "修正項的指紋確實出現在模型裡——它在資料裡不是幻覺。"
              "但同一格的預測誤差沒有跟著降下來。"
          ),
          "#2563EB",
          "#EFF6FF",
      ),
      (
          "2. 樣本內 vs 樣本外",
          (
              "這兩件事本來就可以分開發生：一個變數在樣本內解釋得動，不保證它在樣本外預測得動。"
              "把前者當成後者的證據，是實證研究最常見的過度宣稱。"
          ),
          "#7C3AED",
          "#F5F3FF",
      ),
      (
          "3. 邊界與誠實",
          (
              "還有一句要說清楚：失敗的是日頻代理版。"
              "原始論文用的是日內逐筆資料，本研究沒有資格評論那個版本的效力。"
              "資料撐不起方法時，該退的是宣稱強度，不是把門檻放寬。"
          ),
          "#059669",
          "#ECFDF5",
      ),
  ]

  y_positions = [4.8, 3.1, 1.4]
  for y_pos, (badge, body, border_color, fill_color) in zip(
      y_positions, takeaway_blocks, strict=True
  ):
    row_box = patches.FancyBboxPatch(
        (1.1, y_pos),
        13.8,
        1.5,
        boxstyle="round,pad=0.08,rounding_size=0.15",
        facecolor=fill_color,
        edgecolor=border_color,
        linewidth=1.2,
    )
    ax.add_patch(row_box)

    b_patch = patches.FancyBboxPatch(
        (1.3, y_pos + 0.95),
        2.2,
        0.38,
        boxstyle="round,pad=0.05,rounding_size=0.1",
        facecolor=border_color,
        edgecolor="none",
    )
    ax.add_patch(b_patch)
    ax.text(
        2.4,
        y_pos + 1.14,
        badge,
        color="white",
        fontsize=12,
        fontweight="bold",
        ha="center",
        va="center",
    )

    clean_b = body.replace("**", "")
    wrapped = textwrap.fill(clean_b, width=42)
    ax.text(
        1.3,
        y_pos + 0.82,
        wrapped,
        color="#334155",
        fontsize=11.5,
        linespacing=1.35,
        va="top",
    )

  draw_footer(ax, plan_label)
  fig.savefig(
      out_dir / "3_takeaway.png",
      dpi=100,
      bbox_inches=None,
      facecolor=fig.get_facecolor(),
  )
  plt.close(fig)


def main():
  os.makedirs(OUT_DIR, exist_ok=True)

  with open(EVIDENCE_JSON_PATH, "r", encoding="utf-8") as f:
    results_data = json.load(f)

  with open(PLAN_JSON_PATH, "r", encoding="utf-8") as f:
    plan_data = json.load(f)

  plan_label = plan_data["evidence"]["results"]["label"]

  render_panel1(results_data, plan_label, OUT_DIR)
  render_panel2(results_data, plan_label, OUT_DIR)
  render_panel3(results_data, plan_label, OUT_DIR)
  print(f"Successfully rendered panels to {OUT_DIR}")


if __name__ == "__main__":
  main()
