#!/usr/bin/env python3
"""Render the EP-Final unmanned-vehicle lazypack from its evidence package."""

from __future__ import annotations

import json
import math
import os
import re
import textwrap
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch


EVIDENCE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/drafts/"
    "drone_ep_final_portfolio_evidence.json"
)
PLAN_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_b6a46796/plan.json"
)
OUT_DIR = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_b6a46796/panels"
)

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False

NAVY = "#132A3A"
BLUE = "#276FBF"
TEAL = "#168C86"
GREEN = "#23845C"
AMBER = "#C47B18"
RED = "#B94444"
INK = "#17242D"
MUTED = "#566873"
LIGHT = "#F4F7F9"
PALE_BLUE = "#EAF2FA"
PALE_TEAL = "#E9F6F3"
PALE_AMBER = "#FFF5E5"
PALE_RED = "#FCEEEE"
WHITE = "#FFFFFF"
BORDER = "#D7E0E5"

EXPECTED_PANELS = (
    "1_risk_layers",
    "2_portfolio_method",
    "3_risk_scoreboard",
    "4_investability_gate",
)
SOURCE_LINE = (
    "資料來源：drone_ep_final_portfolio_evidence.json｜"
    "公開資料描述性統計，未提供 experiment K 編號"
)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def req(root: Any, path: str) -> Any:
    current = root
    walked: list[str] = []
    for key in path.split("."):
        walked.append(key)
        if not isinstance(current, dict):
            raise TypeError(f"Expected object before {'.'.join(walked)}")
        if key not in current:
            raise KeyError(f"Missing required field: {'.'.join(walked)}")
        current = current[key]
    return current


def num(root: Any, path: str) -> float:
    value = req(root, path)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Expected numeric field: {path}")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"Expected finite field: {path}")
    return value


def integer(root: Any, path: str) -> int:
    value = num(root, path)
    if not value.is_integer():
        raise ValueError(f"Expected integer field: {path}")
    return int(value)


def string(root: Any, path: str) -> str:
    value = req(root, path)
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"Expected non-empty string field: {path}")
    return value


def parse_number(pattern: str, value: str, label: str) -> str:
    match = re.search(pattern, value)
    if not match:
        raise ValueError(f"Cannot parse {label} from evidence method: {value}")
    return match.group(1)


def pct(value: float, digits: int = 1, signed: bool = False) -> str:
    sign = "+" if signed and value >= 0 else ""
    return f"{sign}{value * 100:.{digits}f}%"


def money_twd(value: float) -> str:
    yi = value / 100_000_000
    if abs(yi - round(yi)) < 1e-9:
        return f"{yi:,.0f} 億元"
    return f"{yi:,.1f} 億元"


def money_usd(value: float) -> str:
    return f"{value / 100_000_000:.2f} 億美元"


def wrap(text: str, width: int) -> str:
    return "\n".join(
        textwrap.wrap(
            text,
            width=width,
            break_long_words=True,
            break_on_hyphens=False,
            replace_whitespace=False,
        )
    )


def new_canvas(title: str, subtitle: str, accent: str):
    fig, ax = plt.subplots(figsize=(10.6666667, 6.6666667), dpi=150)
    fig.patch.set_facecolor(WHITE)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.add_patch(FancyBboxPatch((0, 0.925), 1, 0.075, boxstyle="square,pad=0", facecolor=NAVY, edgecolor=NAVY))
    ax.add_patch(FancyBboxPatch((0, 0.925), 0.018, 0.075, boxstyle="square,pad=0", facecolor=accent, edgecolor=accent))
    ax.text(0.045, 0.964, title, ha="left", va="center", color=WHITE, fontsize=20, fontweight="bold")
    ax.text(0.045, 0.895, subtitle, ha="left", va="center", color=MUTED, fontsize=10.5)
    return fig, ax


def card(ax, x: float, y: float, w: float, h: float, face: str = WHITE, edge: str = BORDER):
    ax.add_patch(
        FancyBboxPatch(
            (x, y), w, h,
            boxstyle="round,pad=0.008,rounding_size=0.014",
            facecolor=face, edgecolor=edge, linewidth=1.0,
        )
    )


def footer(ax, extra: str = ""):
    text = SOURCE_LINE if not extra else f"{SOURCE_LINE}｜{extra}"
    ax.plot([0.045, 0.955], [0.062, 0.062], color=BORDER, linewidth=0.8)
    ax.text(0.045, 0.035, text, ha="left", va="center", color=MUTED, fontsize=7.7)


def save(fig, name: str):
    os.makedirs(OUT_DIR, exist_ok=True)
    path = OUT_DIR / f"{name}.png"
    fig.savefig(path, dpi=150, facecolor=WHITE, bbox_inches=None)
    plt.close(fig)


def validate_inputs(evidence: dict[str, Any]) -> None:
    plan = load_json(PLAN_PATH)
    if not isinstance(plan, list):
        raise TypeError("Plan must be a list")
    names = tuple(item.get("name") for item in plan if isinstance(item, dict))
    if names != EXPECTED_PANELS:
        raise ValueError(f"Unexpected panel plan: {names}")
    if integer(evidence, "diversification_summary.n_names") != len(req(evidence, "roster")):
        raise ValueError("Roster count does not match diversification_summary.n_names")
    for path in (
        "method.common_price_window.start",
        "method.common_price_window.end",
        "portfolio_comparison.all_29_equal.total_return",
        "portfolio_comparison.core_6_equal.total_return",
        "portfolio_comparison.sea_3_equal.total_return",
        "benchmark.window_return",
        "business_evidence_gap.n_ep2_plus_ep3_checked",
        "official_positioning.realized_2025_output_twd",
        "conclusion_evidence_grade.democratic_supply_chain_node",
    ):
        req(evidence, path)


def panel_1(e: dict[str, Any]) -> None:
    n = integer(e, "diversification_summary.n_names")
    median_vol = num(e, "diversification_summary.median_individual_annualized_volatility")
    basket_vol = num(e, "diversification_summary.all_29_annualized_volatility")
    all_corr = num(e, "portfolio_comparison.all_29_equal.average_pairwise_correlation")
    core_corr = num(e, "portfolio_comparison.core_6_equal.average_pairwise_correlation")
    policy_ceiling = num(e, "policy.budget_ceiling_twd")
    checked = integer(e, "business_evidence_gap.n_ep2_plus_ep3_checked")
    disclosed = integer(e, "business_evidence_gap.n_with_separately_disclosed_uav_usv_revenue_share")

    fig, ax = new_canvas(
        "買更多概念股，只能消掉第一層風險",
        "公司起伏可以分散；題材熱度與政策落地，仍是共同曝險。",
        BLUE,
    )
    ax.text(0.055, 0.827, f"{pct(median_vol)} → {pct(basket_vol)}", color=BLUE, fontsize=27, fontweight="bold", va="center")
    ax.text(0.430, 0.827, f"{n} 檔等權把個股波動中位數壓低", color=INK, fontsize=12, va="center")

    layers = [
        (0.055, "第一層｜公司", PALE_BLUE, BLUE,
         f"單一公司起伏\n等權後波動降 {pct(median_vol - basket_vol)}",
         "分散有效，但不代表報酬提高。"),
        (0.365, "第二層｜題材", PALE_AMBER, AMBER,
         f"平均相關 {all_corr:.2f} → {core_corr:.2f}\n核心名單的共同起伏更高",
         "這是描述性對照，不是因果檢定。"),
        (0.675, "第三層｜政策／訂單", PALE_RED, RED,
         f"草案上限 {money_twd(policy_ceiling)}\n拆出營收占比 {disclosed}/{checked}",
         "法案、決標、交貨才可能進入營收。"),
    ]
    for x, title, face, color, body, note in layers:
        card(ax, x, 0.285, 0.270, 0.425, face=face, edge=color)
        ax.text(x + 0.020, 0.660, title, color=color, fontsize=13.2, fontweight="bold", va="top")
        ax.text(x + 0.020, 0.555, body, color=INK, fontsize=15.2, fontweight="bold", va="top", linespacing=1.45)
        ax.text(x + 0.020, 0.360, wrap(note, 18), color=MUTED, fontsize=9.2, va="top", linespacing=1.35)
    ax.text(0.055, 0.205, "結論｜分散能降低單檔噪音，不能把政策上限、原型或資格變成現金流。", color=NAVY, fontsize=13.5, fontweight="bold", va="center")
    footer(ax)
    save(fig, "1_risk_layers")


def panel_2(e: dict[str, Any]) -> None:
    start = string(e, "method.common_price_window.start")
    end = string(e, "method.common_price_window.end")
    prices = integer(e, "method.common_price_window.price_observations")
    returns = integer(e, "method.common_price_window.return_observations")
    n = integer(e, "diversification_summary.n_names")
    core_n = integer(e, "portfolio_comparison.core_6_equal.n_names")
    sea_n = integer(e, "portfolio_comparison.sea_3_equal.n_names")
    vol_method = string(e, "method.volatility")
    mdd_method = string(e, "method.max_drawdown")
    annualizer = parse_number(r"sqrt\((\d+)\)", vol_method, "annualizer")
    initial_wealth = parse_number(r"wealth ([0-9.]+)", mdd_method, "initial wealth")
    lookback = string(e, "method.lookback_limit")

    fig, ax = new_canvas(
        "先統一窗口與算法，再比較八種曝險",
        "前幾集口徑不同；收尾篇全部回到同一組共同交易日。",
        TEAL,
    )
    cards = [
        (0.055, 0.625, "① Universe", f"EP0 名冊 {n} 檔｜EP4 核心 {core_n} 檔｜EP3 海域 {sea_n} 檔", PALE_BLUE, BLUE),
        (0.055, 0.455, "② 共同窗口", f"{start} 至 {end}\n{prices} 筆價格｜{returns} 筆日報酬", PALE_TEAL, TEAL),
        (0.055, 0.285, "③ 同一算法", f"每日重設目標權重、不計費稅；另以月度重設做敏感度\n波動年化乘 √{annualizer}；回撤含初始財富 {initial_wealth}", PALE_AMBER, AMBER),
        (0.055, 0.115, "④ 誠實邊界", "名單在期末才完成，是 ex-post 回看；起點投資人不知道終點名單。", PALE_RED, RED),
    ]
    for x, y, title, body, face, color in cards:
        card(ax, x, y, 0.890, 0.135, face=face, edge=color)
        ax.text(x + 0.025, y + 0.101, title, color=color, fontsize=12.3, fontweight="bold", va="center")
        ax.text(x + 0.240, y + 0.069, body, color=INK, fontsize=10.8, va="center", linespacing=1.35)
    if "not a tradable backtest" not in lookback:
        raise ValueError("method.lookback_limit must explicitly reject a tradable backtest")
    footer(ax, "行情：yfinance 還原收盤價")
    save(fig, "2_portfolio_method")


def panel_3(e: dict[str, Any]) -> None:
    core = req(e, "portfolio_comparison.core_6_equal")
    all29 = req(e, "portfolio_comparison.all_29_equal")
    sea = req(e, "portfolio_comparison.sea_3_equal")
    benchmark = req(e, "benchmark")
    beat = integer(e, "diversification_summary.n_names_beating_twii")
    vol_above = integer(e, "diversification_summary.n_names_with_vol_above_twii")
    n = integer(e, "diversification_summary.n_names")

    fig, ax = new_canvas(
        "核心六檔追上終點，走過的路卻更顛簸",
        "同一共同窗口、同一每日等權算法；報酬不能脫離波動與回撤看。",
        RED,
    )
    card(ax, 0.055, 0.630, 0.890, 0.185, face=NAVY, edge=NAVY)
    ax.text(0.085, 0.775, "窗口報酬", color="#BFD0DE", fontsize=10, fontweight="bold")
    ax.text(0.085, 0.700, pct(num(core, "total_return"), signed=True), color=WHITE, fontsize=27, fontweight="bold")
    ax.text(0.285, 0.704, "核心六檔", color=WHITE, fontsize=12, fontweight="bold")
    ax.text(0.520, 0.700, pct(num(benchmark, "window_return"), signed=True), color="#FFD59A", fontsize=27, fontweight="bold")
    ax.text(0.745, 0.704, "加權指數", color=WHITE, fontsize=12, fontweight="bold")

    metrics = [
        (0.055, "年化波動", pct(num(core, "annualized_volatility")), pct(num(benchmark, "annualized_volatility")), PALE_RED, RED),
        (0.355, "最大回撤", pct(abs(num(core, "max_drawdown"))), pct(abs(num(benchmark, "max_drawdown"))), PALE_AMBER, AMBER),
        (0.655, "月度重設報酬", pct(num(core, "monthly_rebalance_total_return"), signed=True), "每日領先消失", PALE_BLUE, BLUE),
    ]
    for x, title, first, second, face, color in metrics:
        card(ax, x, 0.425, 0.290, 0.160, face=face, edge=color)
        ax.text(x + 0.020, 0.548, title, color=color, fontsize=11.5, fontweight="bold")
        ax.text(x + 0.020, 0.480, first, color=INK, fontsize=20, fontweight="bold")
        label = f"指數 {second}" if second.endswith("%") else second
        ax.text(x + 0.155, 0.483, label, color=MUTED, fontsize=9.5, fontweight="bold")

    card(ax, 0.055, 0.165, 0.430, 0.210, face=LIGHT)
    ax.text(0.080, 0.335, "全名冊 vs. 海域", color=NAVY, fontsize=12.3, fontweight="bold")
    ax.text(0.080, 0.275, f"{n} 檔等權  {pct(num(all29, 'total_return'), signed=True)}｜波動 {pct(num(all29, 'annualized_volatility'))}", color=INK, fontsize=11.2, fontweight="bold")
    ax.text(0.080, 0.220, f"海域三檔  {pct(num(sea, 'total_return'), signed=True)}｜波動 {pct(num(sea, 'annualized_volatility'))}", color=INK, fontsize=11.2, fontweight="bold")

    card(ax, 0.515, 0.165, 0.430, 0.210, face=PALE_RED, edge=RED)
    ax.text(0.540, 0.335, "個股層面的共同警訊", color=RED, fontsize=12.3, fontweight="bold")
    ax.text(0.540, 0.272, f"{beat}/{n}", color=INK, fontsize=22, fontweight="bold")
    ax.text(0.655, 0.277, "跑贏大盤", color=MUTED, fontsize=10.5)
    ax.text(0.540, 0.215, f"{vol_above}/{n}", color=INK, fontsize=22, fontweight="bold")
    ax.text(0.655, 0.220, "個股波動高於指數", color=MUTED, fontsize=10.5)
    footer(ax)
    save(fig, "3_risk_scoreboard")


def panel_4(e: dict[str, Any]) -> None:
    op = req(e, "official_positioning")
    gap = req(e, "business_evidence_gap")
    grades = req(e, "conclusion_evidence_grade")
    checked = integer(gap, "n_ep2_plus_ep3_checked")
    rev = integer(gap, "n_with_separately_disclosed_uav_usv_revenue_share")
    orders = integer(gap, "n_with_public_binding_uav_usv_order_value_in_checked_sources")

    fig, ax = new_canvas(
        "台灣已是供應鏈節點，可投資性仍卡在兩張空白",
        "把已實現、政策目標與公司財務證據分開，護國神山命題才不會提前兌現。",
        GREEN,
    )
    card(ax, 0.055, 0.600, 0.435, 0.220, face=PALE_TEAL, edge=TEAL)
    ax.text(0.080, 0.785, "官方已實現", color=TEAL, fontsize=12.5, fontweight="bold")
    ax.text(0.080, 0.727, money_twd(num(op, "realized_2025_output_twd")), color=INK, fontsize=19, fontweight="bold")
    ax.text(0.280, 0.730, f"外銷 {money_twd(num(op, 'realized_2025_export_output_twd'))}", color=MUTED, fontsize=9.5)
    ax.text(0.080, 0.675, f"整機出口：2026 Q1 {money_usd(num(op, 'realized_2026_q1_complete_uav_exports_usd'))}｜2025 全年 {money_usd(num(op, 'realized_2025_full_year_complete_uav_exports_usd'))}", color=INK, fontsize=9.5)
    ax.text(0.080, 0.625, f"採購 {integer(op, 'commercial_military_uav_procurement_quantity'):,} 架；已交付超過 {integer(op, 'delivered_commercial_military_uavs_asof_2026_05_21_minimum'):,} 架", color=INK, fontsize=10.2, fontweight="bold")

    card(ax, 0.510, 0.600, 0.435, 0.220, face=PALE_AMBER, edge=AMBER)
    ax.text(0.535, 0.785, "政策目標｜不是現況", color=AMBER, fontsize=12.5, fontweight="bold")
    ax.text(0.535, 0.730, f"2030 產值 {money_twd(num(op, 'target_2030_output_twd'))}", color=INK, fontsize=17, fontweight="bold")
    ax.text(0.535, 0.680, f"月產能 {integer(op, 'monthly_capacity_target'):,} 架｜規畫投入 {money_twd(num(op, 'government_planned_industry_investment_2025_2030_twd'))}", color=INK, fontsize=10.0)
    ax.text(0.535, 0.630, "投入規畫、產能與產值目標都不等於已認列營收。", color=MUTED, fontsize=9.3)

    card(ax, 0.055, 0.330, 0.435, 0.220, face=PALE_RED, edge=RED)
    ax.text(0.080, 0.515, "公司可投資性｜兩個空白", color=RED, fontsize=12.5, fontweight="bold")
    ax.text(0.080, 0.445, f"{rev}/{checked}", color=INK, fontsize=24, fontweight="bold")
    ax.text(0.210, 0.450, "拆出無人載具營收占比", color=MUTED, fontsize=10)
    ax.text(0.080, 0.382, f"{orders}/{checked}", color=INK, fontsize=24, fontweight="bold")
    ax.text(0.210, 0.387, "揭露具約束力訂單金額", color=MUTED, fontsize=10)

    ratio = num(op, "semiconductor_to_uav_output_ratio_2025")
    node_grade = string(grades, "democratic_supply_chain_node")
    resilience_grade = string(grades, "national_security_supply_chain_resilience_cluster")
    pillar_grade = string(grades, "next_semiconductor_scale_economic_pillar")
    card(ax, 0.510, 0.330, 0.435, 0.220, face=PALE_BLUE, edge=BLUE)
    ax.text(0.535, 0.515, "競爭定位｜證據分級", color=BLUE, fontsize=12.5, fontweight="bold")
    ax.text(0.535, 0.455, f"半導體產值約為無人機 {ratio:.0f} 倍", color=INK, fontsize=14.5, fontweight="bold")
    ax.text(0.535, 0.405, f"民主供應鏈節點：{node_grade}｜國安韌性群山：{resilience_grade}", color=INK, fontsize=10)
    ax.text(0.535, 0.365, f"下一座半導體規模護國神山：{pillar_grade}", color=RED, fontsize=10.2, fontweight="bold")

    alliance = integer(op, "industry_alliance_members_minimum")
    us_chain = integer(op, "taiwan_companies_in_us_uav_supply_chain_minimum")
    ax.text(0.055, 0.265, f"供應鏈基礎｜產業聯盟超過 {alliance} 家；超過 {us_chain} 家台廠進入美國供應鏈。", color=NAVY, fontsize=11.3, fontweight="bold")
    ax.text(0.055, 0.205, "下一步只追四張單據", color=MUTED, fontsize=10.5, fontweight="bold")
    documents = ("決標公告", "交貨紀錄", "營收拆分", "獲利與現金")
    for idx, label in enumerate(documents):
        x = 0.220 + idx * 0.180
        card(ax, x, 0.172, 0.150, 0.060, face=WHITE, edge=GREEN)
        ax.text(x + 0.075, 0.202, label, ha="center", va="center", color=GREEN, fontsize=10.2, fontweight="bold")
    footer(ax, "官方來源：行政院、經濟部、國家發展計畫（URL 收錄於 evidence）")
    save(fig, "4_investability_gate")


def main() -> None:
    evidence_raw = load_json(EVIDENCE_PATH)
    if not isinstance(evidence_raw, dict):
        raise TypeError("Evidence root must be an object")
    validate_inputs(evidence_raw)
    panel_1(evidence_raw)
    panel_2(evidence_raw)
    panel_3(evidence_raw)
    panel_4(evidence_raw)


if __name__ == "__main__":
    main()
