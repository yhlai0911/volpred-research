#!/usr/bin/env python3
"""Render the four data-bound VolPred EP3 lazypack panels.

All displayed statistics are loaded from the absolute-path evidence JSON.  The
two Markdown files are read as supporting evidence only for article-only prose
(the committee label and the four follow-up document names).  Missing or
inconsistent fields raise immediately; the renderer never substitutes values.
"""

from __future__ import annotations

import json
import math
import os
import re
import textwrap
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle


EVIDENCE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/drafts/"
    "drone_ep3_downstream_evidence.json"
)
DRAFT_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/drafts/"
    "drone_ep3_general_draft.md"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_abd517ba/panels/mile_abd517ba_article.md"
)
OUT_DIR = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_abd517ba/panels"
)

WIDTH = 1600
HEIGHT = 1000
DPI = 150

SOURCE_NOTE = (
    "資料來源：drone_ep3_downstream_evidence.json"
    "（證據包未提供 experiment K 編號）"
)

INK = "#172033"
MUTED = "#5D6879"
FAINT = "#8792A3"
PAPER = "#F5F7FA"
WHITE = "#FFFFFF"
NAVY = "#12243A"
BLUE = "#2463A7"
BLUE_SOFT = "#E7F0FA"
TEAL = "#16807C"
TEAL_SOFT = "#E2F2F0"
AMBER = "#B97618"
AMBER_SOFT = "#F8EBD7"
GREEN = "#2C7A57"
GREEN_SOFT = "#E5F1EA"
RED = "#B54242"
RED_SOFT = "#F7E5E5"
BORDER = "#DCE2EA"

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["font.size"] = 12
plt.rcParams["text.color"] = INK
plt.rcParams["axes.labelcolor"] = INK


def require(mapping: Any, *path: str) -> Any:
    """Return a required nested field, raising with the complete JSON path."""
    current = mapping
    walked: list[str] = []
    for key in path:
        walked.append(key)
        if not isinstance(current, dict) or key not in current:
            raise KeyError("Missing required evidence field: " + ".".join(walked))
        current = current[key]
    if current is None:
        raise ValueError("Null required evidence field: " + ".".join(path))
    return current


def require_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"Expected non-empty text at {label}")
    return value.strip()


def require_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Expected numeric value at {label}")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"Expected finite value at {label}")
    return value


def require_integer(value: Any, label: str) -> int:
    number = require_number(value, label)
    if not number.is_integer():
        raise ValueError(f"Expected integer value at {label}")
    return int(number)


def require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list) or not value:
        raise TypeError(f"Expected non-empty list at {label}")
    return value


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise TypeError(f"Evidence root must be an object: {path}")
    return value


def load_markdown(path: Path) -> str:
    value = path.read_text(encoding="utf-8")
    if not value.strip():
        raise ValueError(f"Markdown evidence is empty: {path}")
    return value


def wrap_zh(value: str, width: int) -> str:
    """Pre-wrap Chinese/English prose so matplotlib never relies on auto-wrap."""
    lines: list[str] = []
    for paragraph in str(value).splitlines() or [""]:
        if not paragraph:
            lines.append("")
            continue
        lines.extend(
            textwrap.wrap(
                paragraph,
                width=width,
                break_long_words=True,
                break_on_hyphens=False,
                replace_whitespace=False,
                drop_whitespace=True,
            )
            or [""]
        )
    return "\n".join(lines)


def pct(value: float, *, signed: bool = False) -> str:
    return format(value, "+.1%" if signed else ".1%")


def date_iso(value: Any, label: str) -> str:
    text = require_text(value, label)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        raise ValueError(f"Expected ISO date at {label}: {text}")
    return text


def new_figure(background: str = WHITE) -> plt.Figure:
    return plt.figure(
        figsize=(WIDTH / DPI, HEIGHT / DPI),
        dpi=DPI,
        facecolor=background,
    )


def add_card(
    fig: plt.Figure,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    face: str = WHITE,
    edge: str = BORDER,
    radius: float = 0.012,
    linewidth: float = 1.1,
) -> FancyBboxPatch:
    patch = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle=f"round,pad=0.006,rounding_size={radius}",
        transform=fig.transFigure,
        facecolor=face,
        edgecolor=edge,
        linewidth=linewidth,
        zorder=1,
    )
    fig.add_artist(patch)
    return patch


def add_rect(
    fig: plt.Figure,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    face: str,
    edge: str = "none",
    linewidth: float = 0.0,
    zorder: int = 1,
) -> Rectangle:
    patch = Rectangle(
        (x, y),
        w,
        h,
        transform=fig.transFigure,
        facecolor=face,
        edgecolor=edge,
        linewidth=linewidth,
        zorder=zorder,
    )
    fig.add_artist(patch)
    return patch


def add_footer(fig: plt.Figure) -> None:
    fig.add_artist(
        Line2D(
            [0.055, 0.945],
            [0.060, 0.060],
            transform=fig.transFigure,
            color=BORDER,
            linewidth=1.0,
            zorder=2,
        )
    )
    fig.text(
        0.055,
        0.027,
        SOURCE_NOTE,
        ha="left",
        va="center",
        fontsize=10.2,
        color=MUTED,
        zorder=3,
    )


def save_panel(fig: plt.Figure, filename: str) -> None:
    path = OUT_DIR / filename
    fig.savefig(path, dpi=DPI, facecolor=fig.get_facecolor())
    plt.close(fig)


def extract_follow_up_documents(article: str) -> list[tuple[str, str]]:
    heading = "## 接下來只追四張可核對的單據"
    if heading not in article:
        raise ValueError("Article evidence is missing the follow-up-document section")
    section = article.split(heading, 1)[1]
    section = section.split("\n## ", 1)[0]
    items = re.findall(r"^\d+\.\s+\*\*(.+?)\*\*：(.+)$", section, flags=re.MULTILINE)
    if len(items) != 4:
        raise ValueError(
            "Expected exactly four follow-up documents in article evidence; "
            f"found {len(items)}"
        )
    return [(require_text(name, "article.follow_up.name"),
             require_text(detail, "article.follow_up.detail")) for name, detail in items]


def extract_committee_note(article: str) -> tuple[str, str]:
    committee = re.search(r"排定的是(.+?三委員會)", article)
    agenda = re.search(r"議程為([^，。]+)", article)
    if not committee or not agenda:
        raise ValueError("Article evidence is missing committee or agenda wording")
    return committee.group(1).strip(), agenda.group(1).strip()


def prepare_context() -> dict[str, Any]:
    evidence = load_json(EVIDENCE_PATH)
    draft = load_markdown(DRAFT_PATH)
    article = load_markdown(ARTICLE_PATH)

    if "無人載具" not in draft or "EP3" not in draft:
        raise ValueError("Draft evidence does not match the EP3 article")
    if "無人載具" not in article or "EP3" not in article:
        raise ValueError("Article evidence does not match the EP3 article")

    summary = require(evidence, "summary")
    companies = require_list(require(evidence, "companies"), "companies")
    n_companies = require_integer(require(summary, "n_companies"), "summary.n_companies")
    if len(companies) != n_companies:
        raise ValueError(
            f"companies length {len(companies)} != summary.n_companies {n_companies}"
        )

    group_specs = (
        (
            "量產或已交付",
            "n_mass_production_or_delivered",
        ),
        (
            "產品、原型或合作",
            "n_product_prototype_or_collaboration",
        ),
        (
            "資格或能力",
            "n_qualification_or_capability",
        ),
    )
    stage_counts = require(summary, "stage_counts")
    observed_groups: Counter[str] = Counter()
    revenue_share_disclosed = 0
    binding_order_disclosed = 0
    latest_fys: set[int] = set()

    for index, company in enumerate(companies):
        if not isinstance(company, dict):
            raise TypeError(f"companies[{index}] must be an object")
        require_text(require(company, "name"), f"companies[{index}].name")
        require_text(require(company, "segment"), f"companies[{index}].segment")
        group = require_text(
            require(company, "stage_group"), f"companies[{index}].stage_group"
        )
        require_text(
            require(company, "highest_public_stage"),
            f"companies[{index}].highest_public_stage",
        )
        observed_groups[group] += 1

        revenue_flag = require(company, "separate_uav_usv_revenue_share_disclosed")
        order_flag = require(company, "binding_uav_usv_order_value_disclosed")
        if not isinstance(revenue_flag, bool):
            raise TypeError(
                f"companies[{index}].separate_uav_usv_revenue_share_disclosed "
                "must be boolean"
            )
        if not isinstance(order_flag, bool):
            raise TypeError(
                f"companies[{index}].binding_uav_usv_order_value_disclosed "
                "must be boolean"
            )
        revenue_share_disclosed += int(revenue_flag)
        binding_order_disclosed += int(order_flag)
        latest_fys.add(
            require_integer(require(company, "latest_fy"), f"companies[{index}].latest_fy")
        )

        company_sources = require_list(
            require(company, "source_urls"), f"companies[{index}].source_urls"
        )
        for source_index, url in enumerate(company_sources):
            require_text(url, f"companies[{index}].source_urls[{source_index}]")

    allowed_groups = {label for label, _ in group_specs}
    unexpected_groups = set(observed_groups) - allowed_groups
    if unexpected_groups:
        raise ValueError(f"Unexpected stage_group values: {sorted(unexpected_groups)}")

    for group_label, summary_key in group_specs:
        summary_count = require_integer(
            require(summary, summary_key), f"summary.{summary_key}"
        )
        nested_count = require_integer(
            require(stage_counts, group_label), f"summary.stage_counts.{group_label}"
        )
        observed_count = observed_groups[group_label]
        if summary_count != nested_count or summary_count != observed_count:
            raise ValueError(
                f"Stage count mismatch for {group_label}: "
                f"summary={summary_count}, stage_counts={nested_count}, "
                f"companies={observed_count}"
            )

    summary_revenue_count = require_integer(
        require(summary, "n_with_separately_disclosed_uav_usv_revenue_share"),
        "summary.n_with_separately_disclosed_uav_usv_revenue_share",
    )
    summary_order_count = require_integer(
        require(summary, "n_with_public_binding_uav_usv_order_value_in_checked_sources"),
        "summary.n_with_public_binding_uav_usv_order_value_in_checked_sources",
    )
    if summary_revenue_count != revenue_share_disclosed:
        raise ValueError("Revenue-share disclosure count disagrees with company flags")
    if summary_order_count != binding_order_disclosed:
        raise ValueError("Binding-order disclosure count disagrees with company flags")
    if len(latest_fys) != 1:
        raise ValueError(f"Companies do not share one latest fiscal year: {latest_fys}")

    policy = require(evidence, "policy")
    policy_sources = require_list(require(policy, "source_urls"), "policy.source_urls")
    for index, url in enumerate(policy_sources):
        require_text(url, f"policy.source_urls[{index}]")

    certification = require(evidence, "certification_check")
    for key in ("blue_uas_source_urls", "green_uas_source_urls"):
        sources = require_list(require(certification, key), f"certification_check.{key}")
        for index, url in enumerate(sources):
            require_text(url, f"certification_check.{key}[{index}]")

    method = require(evidence, "method")
    for key in ("return", "volatility", "basket", "financials", "disclosure_stage"):
        require_text(require(method, key), f"method.{key}")

    data_source = require_text(require(evidence, "data_source"), "data_source")
    if "yfinance" not in data_source or "adjusted close" not in data_source:
        raise ValueError("data_source no longer identifies yfinance adjusted close")
    if "no costs" not in require_text(require(method, "basket"), "method.basket"):
        raise ValueError("method.basket no longer states the no-cost assumption")

    documents = extract_follow_up_documents(article)
    committee_label, committee_agenda = extract_committee_note(article)

    for required_phrase in ("描述性分析", "不構成投資建議"):
        if required_phrase not in article:
            raise ValueError(f"Article evidence is missing limitation: {required_phrase}")

    return {
        "evidence": evidence,
        "summary": summary,
        "companies": companies,
        "policy": policy,
        "certification": certification,
        "method": method,
        "n_companies": n_companies,
        "latest_fy": next(iter(latest_fys)),
        "documents": documents,
        "committee_label": committee_label,
        "committee_agenda": committee_agenda,
        "article": article,
    }


def companies_in_group(companies: Iterable[dict[str, Any]], group: str) -> list[str]:
    names = [
        require_text(require(company, "name"), "companies[].name")
        for company in companies
        if require_text(require(company, "stage_group"), "companies[].stage_group") == group
    ]
    if not names:
        raise ValueError(f"No companies found for stage_group={group}")
    return names


def render_disclosure_ladder(context: dict[str, Any]) -> None:
    evidence = context["evidence"]
    summary = context["summary"]
    companies = context["companies"]
    as_of = date_iso(require(evidence, "as_of_date"), "as_of_date")

    stage_specs = (
        (
            "資格或能力",
            require_integer(
                require(summary, "n_qualification_or_capability"),
                "summary.n_qualification_or_capability",
            ),
            AMBER,
            AMBER_SOFT,
            "公開門檻較低",
        ),
        (
            "產品、原型或合作",
            require_integer(
                require(summary, "n_product_prototype_or_collaboration"),
                "summary.n_product_prototype_or_collaboration",
            ),
            BLUE,
            BLUE_SOFT,
            "已有產品或合作證據",
        ),
        (
            "量產或已交付",
            require_integer(
                require(summary, "n_mass_production_or_delivered"),
                "summary.n_mass_production_or_delivered",
            ),
            GREEN,
            GREEN_SOFT,
            "目前最高公開階段",
        ),
    )
    revenue_count = require_integer(
        require(summary, "n_with_separately_disclosed_uav_usv_revenue_share"),
        "summary.n_with_separately_disclosed_uav_usv_revenue_share",
    )
    order_count = require_integer(
        require(summary, "n_with_public_binding_uav_usv_order_value_in_checked_sources"),
        "summary.n_with_public_binding_uav_usv_order_value_in_checked_sources",
    )

    fig = new_figure(PAPER)
    add_rect(fig, 0.0, 0.82, 1.0, 0.18, face=NAVY)
    fig.text(
        0.055,
        0.957,
        f"無人載具 EP3｜查核日 {as_of}",
        color="#C7D5E6",
        fontsize=12.5,
        ha="left",
        va="center",
    )
    fig.text(
        0.055,
        0.905,
        "十家下游廠的公開證據階梯",
        color=WHITE,
        fontsize=29,
        fontweight="bold",
        ha="left",
        va="center",
    )
    fig.text(
        0.055,
        0.852,
        "每家公司只放進截至查核日找到的最高公開階段；三層互斥。",
        color="#DDE6F0",
        fontsize=13.2,
        ha="left",
        va="center",
    )

    fig.text(
        0.055,
        0.785,
        "由資格／能力走向量產／交付，證據門檻逐級提高",
        fontsize=15.5,
        fontweight="bold",
        ha="left",
        va="center",
    )
    arrow = FancyArrowPatch(
        (0.565, 0.785),
        (0.935, 0.785),
        transform=fig.transFigure,
        arrowstyle="-|>",
        mutation_scale=13,
        linewidth=1.7,
        color=FAINT,
        zorder=2,
    )
    fig.add_artist(arrow)

    card_xs = (0.055, 0.365, 0.675)
    for x, (group, count, accent, soft, evidence_label) in zip(card_xs, stage_specs):
        names = companies_in_group(companies, group)
        if len(names) != count:
            raise ValueError(f"Panel 1 count mismatch for {group}")
        add_card(fig, x, 0.505, 0.27, 0.235, face=WHITE)
        add_rect(fig, x, 0.718, 0.27, 0.022, face=accent, zorder=2)
        fig.text(
            x + 0.022,
            0.682,
            evidence_label,
            fontsize=10.7,
            color=accent,
            ha="left",
            va="center",
        )
        fig.text(
            x + 0.022,
            0.625,
            f"{count} 家",
            fontsize=37,
            fontweight="bold",
            color=accent,
            ha="left",
            va="center",
        )
        fig.text(
            x + 0.022,
            0.575,
            group,
            fontsize=14.2,
            fontweight="bold",
            ha="left",
            va="center",
        )
        fig.text(
            x + 0.022,
            0.530,
            wrap_zh("、".join(names), 17),
            fontsize=10.9,
            color=MUTED,
            ha="left",
            va="center",
            linespacing=1.35,
        )

    fig.text(
        0.055,
        0.462,
        "最關鍵的兩個揭露缺口",
        fontsize=15.5,
        fontweight="bold",
        ha="left",
        va="center",
    )
    disclosure_specs = (
        (
            0.055,
            revenue_count,
            "拆出無人載具營收占比",
            "只限本次查核來源",
        ),
        (
            0.515,
            order_count,
            "公開可核對具約束力訂單金額",
            "只限無人機／無人艇訂單",
        ),
    )
    for x, value, label, note in disclosure_specs:
        add_card(fig, x, 0.285, 0.43, 0.14, face=RED_SOFT, edge="#EBCACA")
        fig.text(
            x + 0.025,
            0.355,
            f"{value} 家",
            fontsize=32,
            fontweight="bold",
            color=RED,
            ha="left",
            va="center",
        )
        fig.text(
            x + 0.145,
            0.375,
            wrap_zh(label, 18),
            fontsize=13.2,
            fontweight="bold",
            ha="left",
            va="center",
            linespacing=1.25,
        )
        fig.text(
            x + 0.145,
            0.318,
            note,
            fontsize=10.5,
            color=MUTED,
            ha="left",
            va="center",
        )

    add_card(fig, 0.055, 0.105, 0.89, 0.115, face=WHITE)
    reminder_specs = (
        (0.080, "資格 ≠ 得標"),
        (0.385, "原型 ≠ 量產"),
        (0.675, "公司總營收 ≠ 無人載具營收"),
    )
    for index, (x, text) in enumerate(reminder_specs):
        if index:
            fig.add_artist(
                Line2D(
                    [x - 0.035, x - 0.035],
                    [0.130, 0.195],
                    transform=fig.transFigure,
                    color=BORDER,
                    linewidth=1.2,
                )
            )
        fig.text(
            x,
            0.162,
            wrap_zh(text, 15),
            fontsize=13.8,
            fontweight="bold",
            color=INK,
            ha="left",
            va="center",
            linespacing=1.25,
        )

    add_footer(fig)
    save_panel(fig, "1_disclosure_ladder.png")


def render_method(context: dict[str, Any]) -> None:
    evidence = context["evidence"]
    method = context["method"]
    policy = context["policy"]
    certification = context["certification"]
    companies = context["companies"]
    n_companies = context["n_companies"]
    latest_fy = context["latest_fy"]

    as_of = date_iso(require(evidence, "as_of_date"), "as_of_date")
    window = require(evidence, "price_window_common")
    start = date_iso(require(window, "start"), "price_window_common.start")
    end = date_iso(require(window, "end"), "price_window_common.end")
    observations = require_integer(
        require(window, "observations"), "price_window_common.observations"
    )
    require_text(require(window, "reason"), "price_window_common.reason")
    require_text(require(method, "return"), "method.return")
    require_text(require(method, "volatility"), "method.volatility")
    require_text(require(method, "financials"), "method.financials")
    require_text(require(method, "disclosure_stage"), "method.disclosure_stage")
    basket_method = require_text(require(method, "basket"), "method.basket")

    policy_sources = require_list(require(policy, "source_urls"), "policy.source_urls")
    if not all(isinstance(url, str) and url.strip() for url in policy_sources):
        raise TypeError("policy.source_urls contains an invalid URL")
    if not all(require_list(require(company, "source_urls"), "companies[].source_urls")
               for company in companies):
        raise ValueError("A company is missing source URLs")

    checked_at = date_iso(
        require(certification, "checked_at"), "certification_check.checked_at"
    )
    certification_result = require_text(
        require(certification, "result"), "certification_check.result"
    )
    if "；" not in certification_result:
        raise ValueError("certification_check.result no longer contains route wording")
    route_note = certification_result.split("；", 1)[1].strip()
    if "Blue UAS" not in route_note or "Green UAS" not in route_note:
        raise ValueError("Certification route note is missing Blue/Green UAS")
    require_list(
        require(certification, "blue_uas_source_urls"),
        "certification_check.blue_uas_source_urls",
    )
    require_list(
        require(certification, "green_uas_source_urls"),
        "certification_check.green_uas_source_urls",
    )
    if "no costs" not in basket_method:
        raise ValueError("method.basket must state no costs")

    fig = new_figure(WHITE)
    add_rect(fig, 0.0, 0.0, 0.022, 1.0, face=TEAL)
    fig.text(
        0.060,
        0.942,
        "無人載具 EP3｜查核設計",
        fontsize=12.5,
        color=TEAL,
        fontweight="bold",
        ha="left",
        va="center",
    )
    fig.text(
        0.060,
        0.890,
        "怎麼把題材拆成可核對的證據",
        fontsize=28,
        fontweight="bold",
        ha="left",
        va="center",
    )
    fig.text(
        0.060,
        0.842,
        "同一家公司只取最高公開階段；財報、價格與認證各走自己的查核路徑。",
        fontsize=13.2,
        color=MUTED,
        ha="left",
        va="center",
    )

    add_card(fig, 0.060, 0.655, 0.885, 0.145, face=NAVY, edge=NAVY)
    fig.text(
        0.085,
        0.728,
        f"{n_companies} 家",
        fontsize=39,
        fontweight="bold",
        color=WHITE,
        ha="left",
        va="center",
    )
    fig.text(
        0.225,
        0.750,
        "公司範圍",
        fontsize=11.2,
        color="#AFC2D8",
        ha="left",
        va="center",
    )
    fig.text(
        0.225,
        0.704,
        "下游整機、系統整合、地面控制站與無人艇",
        fontsize=15.2,
        fontweight="bold",
        color=WHITE,
        ha="left",
        va="center",
    )
    fig.add_artist(
        Line2D(
            [0.690, 0.690],
            [0.680, 0.775],
            transform=fig.transFigure,
            color="#445B73",
            linewidth=1.2,
        )
    )
    fig.text(
        0.720,
        0.748,
        f"截至 {as_of}",
        fontsize=11.0,
        color="#AFC2D8",
        ha="left",
        va="center",
    )
    fig.text(
        0.720,
        0.703,
        "最高公開階段｜三層互斥",
        fontsize=14.0,
        fontweight="bold",
        color=WHITE,
        ha="left",
        va="center",
    )

    method_cards = (
        (
            0.060,
            "財報",
            f"FY{latest_fy} 年度損益表",
            "公司整體數字，不歸因到無人載具",
            BLUE,
            BLUE_SOFT,
        ),
        (
            0.360,
            "價格",
            f"{start} 至 {end}\n{observations} 個共同交易日",
            "yfinance 還原收盤價；公司與指數取交集",
            TEAL,
            TEAL_SOFT,
        ),
        (
            0.660,
            "等權籃",
            "每日等權對數報酬",
            "每日再平衡｜不含成本",
            AMBER,
            AMBER_SOFT,
        ),
    )
    for x, label, main, note, accent, soft in method_cards:
        add_card(fig, x, 0.405, 0.265, 0.205, face=soft, edge=soft)
        add_rect(fig, x, 0.588, 0.265, 0.022, face=accent, zorder=2)
        fig.text(
            x + 0.020,
            0.555,
            label,
            fontsize=11.2,
            color=accent,
            fontweight="bold",
            ha="left",
            va="center",
        )
        fig.text(
            x + 0.020,
            0.495,
            main,
            fontsize=15.0,
            fontweight="bold",
            ha="left",
            va="center",
            linespacing=1.35,
        )
        fig.text(
            x + 0.020,
            0.437,
            wrap_zh(note, 20),
            fontsize=10.6,
            color=MUTED,
            ha="left",
            va="center",
            linespacing=1.3,
        )

    add_card(fig, 0.060, 0.235, 0.885, 0.125, face=PAPER, edge=BORDER)
    fig.text(
        0.085,
        0.322,
        f"認證查核｜{checked_at}",
        fontsize=11.1,
        color=TEAL,
        fontweight="bold",
        ha="left",
        va="center",
    )
    fig.text(
        0.085,
        0.276,
        wrap_zh(route_note, 63),
        fontsize=12.3,
        fontweight="bold",
        ha="left",
        va="center",
        linespacing=1.3,
    )

    add_card(fig, 0.060, 0.105, 0.885, 0.085, face=WHITE, edge=BORDER)
    fig.text(
        0.085,
        0.148,
        "政策與公司階段：使用 evidence 附的官方／公司來源；不同查核路徑不互相替代。",
        fontsize=11.5,
        color=MUTED,
        ha="left",
        va="center",
    )

    add_footer(fig)
    save_panel(fig, "2_method.png")


def render_budget_vs_orders(context: dict[str, Any]) -> None:
    evidence = context["evidence"]
    policy = context["policy"]
    summary = context["summary"]
    companies = context["companies"]
    committee_label = context["committee_label"]
    committee_agenda = context["committee_agenda"]

    as_of = date_iso(require(evidence, "as_of_date"), "as_of_date")
    budget = require_integer(
        require(policy, "budget_ceiling_twd"), "policy.budget_ceiling_twd"
    )
    if budget % 100_000_000 != 0:
        raise ValueError("policy.budget_ceiling_twd cannot be shown as whole 億元")
    budget_yi = budget // 100_000_000
    quantity = require_integer(
        require(policy, "small_expendable_usv_planned_quantity"),
        "policy.small_expendable_usv_planned_quantity",
    )
    status = require_text(require(policy, "status"), "policy.status")
    review_date = date_iso(
        require(policy, "next_scheduled_joint_committee_review"),
        "policy.next_scheduled_joint_committee_review",
    )
    interpretation = require_text(
        require(policy, "interpretation_limit"), "policy.interpretation_limit"
    )

    mass_count = require_integer(
        require(summary, "n_mass_production_or_delivered"),
        "summary.n_mass_production_or_delivered",
    )
    mass_names = companies_in_group(companies, "量產或已交付")
    if len(mass_names) != mass_count:
        raise ValueError("Mass-production company names disagree with summary count")
    binding_count = require_integer(
        require(summary, "n_with_public_binding_uav_usv_order_value_in_checked_sources"),
        "summary.n_with_public_binding_uav_usv_order_value_in_checked_sources",
    )

    fig = new_figure(PAPER)
    fig.text(
        0.055,
        0.946,
        f"無人載具 EP3｜截至 {as_of}",
        fontsize=12.5,
        color=RED,
        fontweight="bold",
        ha="left",
        va="center",
    )
    fig.text(
        0.055,
        0.892,
        "政策上限很大，公司單據仍是另一件事",
        fontsize=28,
        fontweight="bold",
        ha="left",
        va="center",
    )
    fig.text(
        0.055,
        0.842,
        "法案上限、規畫數量與審查進度，都不能直接改寫成個別公司的已得標訂單。",
        fontsize=13.0,
        color=MUTED,
        ha="left",
        va="center",
    )

    add_card(fig, 0.055, 0.610, 0.430, 0.180, face=NAVY, edge=NAVY)
    fig.text(
        0.082,
        0.750,
        "法案經費上限",
        fontsize=11.5,
        color="#BFD0E1",
        ha="left",
        va="center",
    )
    fig.text(
        0.082,
        0.690,
        f"{budget_yi:,} 億元",
        fontsize=36,
        fontweight="bold",
        color=WHITE,
        ha="left",
        va="center",
    )
    fig.text(
        0.082,
        0.630,
        "上限，不是已決標金額",
        fontsize=11.4,
        color="#D5DFEA",
        ha="left",
        va="center",
    )

    add_card(fig, 0.515, 0.610, 0.430, 0.180, face=BLUE_SOFT, edge=BLUE_SOFT)
    fig.text(
        0.542,
        0.750,
        "規畫小型自殺無人艇",
        fontsize=11.5,
        color=BLUE,
        ha="left",
        va="center",
    )
    fig.text(
        0.542,
        0.690,
        f"{quantity:,} 艘",
        fontsize=36,
        fontweight="bold",
        color=BLUE,
        ha="left",
        va="center",
    )
    fig.text(
        0.542,
        0.630,
        "規畫數量，不是公司訂單",
        fontsize=11.4,
        color=MUTED,
        ha="left",
        va="center",
    )

    add_card(fig, 0.055, 0.405, 0.560, 0.155, face=WHITE, edge=BORDER)
    fig.text(
        0.082,
        0.522,
        "草案目前狀態",
        fontsize=11.2,
        color=RED,
        fontweight="bold",
        ha="left",
        va="center",
    )
    fig.text(
        0.082,
        0.462,
        wrap_zh(status, 32),
        fontsize=15.0,
        fontweight="bold",
        ha="left",
        va="center",
        linespacing=1.35,
    )

    add_card(fig, 0.645, 0.405, 0.300, 0.155, face=AMBER_SOFT, edge=AMBER_SOFT)
    fig.text(
        0.670,
        0.522,
        "下次排定審查",
        fontsize=11.2,
        color=AMBER,
        fontweight="bold",
        ha="left",
        va="center",
    )
    fig.text(
        0.670,
        0.482,
        review_date,
        fontsize=20.5,
        fontweight="bold",
        color=AMBER,
        ha="left",
        va="center",
    )
    fig.text(
        0.670,
        0.450,
        wrap_zh(f"{committee_label}\n聯席｜{committee_agenda}", 15),
        fontsize=9.8,
        color=MUTED,
        ha="left",
        va="top",
        linespacing=1.2,
    )

    add_card(fig, 0.055, 0.215, 0.500, 0.135, face=GREEN_SOFT, edge=GREEN_SOFT)
    fig.text(
        0.082,
        0.318,
        "量產或已交付",
        fontsize=11.2,
        color=GREEN,
        fontweight="bold",
        ha="left",
        va="center",
    )
    fig.text(
        0.082,
        0.268,
        f"{mass_count} 家｜{'、'.join(mass_names)}",
        fontsize=18.0,
        fontweight="bold",
        color=GREEN,
        ha="left",
        va="center",
    )
    fig.text(
        0.082,
        0.232,
        "有量產出貨或實際交付紀錄",
        fontsize=10.6,
        color=MUTED,
        ha="left",
        va="center",
    )

    add_card(fig, 0.585, 0.215, 0.360, 0.135, face=RED_SOFT, edge=RED_SOFT)
    fig.text(
        0.612,
        0.303,
        f"{binding_count} 家",
        fontsize=31,
        fontweight="bold",
        color=RED,
        ha="left",
        va="center",
    )
    fig.text(
        0.730,
        0.286,
        wrap_zh("拆出具約束力無人載具訂單金額", 14),
        fontsize=11.8,
        fontweight="bold",
        ha="left",
        va="center",
        linespacing=1.3,
    )

    add_card(fig, 0.055, 0.105, 0.890, 0.065, face=WHITE, edge=BORDER)
    fig.text(
        0.080,
        0.138,
        wrap_zh(interpretation, 62),
        fontsize=11.3,
        fontweight="bold",
        color=INK,
        ha="left",
        va="center",
    )

    add_footer(fig)
    save_panel(fig, "3_budget_vs_orders.png")


def add_metric_bars(
    fig: plt.Figure,
    *,
    x: float,
    y: float,
    w: float,
    h: float,
    title: str,
    basket_value: float,
    index_value: float,
    signed: bool,
) -> None:
    add_card(fig, x, y, w, h, face=WHITE, edge=BORDER)
    fig.text(
        x + 0.025,
        y + h - 0.045,
        title,
        fontsize=14.0,
        fontweight="bold",
        ha="left",
        va="center",
    )
    maximum = max(abs(basket_value), abs(index_value))
    if maximum <= 0:
        raise ValueError(f"Cannot draw non-positive scale for {title}")

    rows = (
        ("十公司等權籃", basket_value, AMBER),
        ("加權指數", index_value, BLUE),
    )
    row_ys = (y + 0.115, y + 0.045)
    bar_x = x + 0.155
    bar_w = w - 0.250
    for (label, value, color), row_y in zip(rows, row_ys):
        fig.text(
            x + 0.025,
            row_y + 0.018,
            label,
            fontsize=10.8,
            color=MUTED,
            ha="left",
            va="center",
        )
        add_rect(
            fig,
            bar_x,
            row_y,
            bar_w,
            0.035,
            face="#EDF0F4",
            zorder=2,
        )
        add_rect(
            fig,
            bar_x,
            row_y,
            bar_w * abs(value) / maximum,
            0.035,
            face=color,
            zorder=3,
        )
        fig.text(
            x + w - 0.025,
            row_y + 0.018,
            pct(value, signed=signed),
            fontsize=13.2,
            fontweight="bold",
            color=color,
            ha="right",
            va="center",
            zorder=4,
        )


def render_portfolio_risk(context: dict[str, Any]) -> None:
    evidence = context["evidence"]
    summary = context["summary"]
    method = context["method"]
    documents = context["documents"]
    article = context["article"]

    window = require(evidence, "price_window_common")
    start = date_iso(require(window, "start"), "price_window_common.start")
    end = date_iso(require(window, "end"), "price_window_common.end")
    observations = require_integer(
        require(window, "observations"), "price_window_common.observations"
    )
    require_text(require(window, "reason"), "price_window_common.reason")

    basket_return = require_number(
        require(summary, "basket_return_common_window"),
        "summary.basket_return_common_window",
    )
    basket_volatility = require_number(
        require(summary, "basket_annualized_volatility"),
        "summary.basket_annualized_volatility",
    )
    twii_return = require_number(
        require(summary, "twii_return_common_window"),
        "summary.twii_return_common_window",
    )
    twii_volatility = require_number(
        require(summary, "twii_annualized_volatility"),
        "summary.twii_annualized_volatility",
    )
    return_gap = require_number(
        require(summary, "return_gap_basket_minus_twii"),
        "summary.return_gap_basket_minus_twii",
    )
    if not math.isclose(
        return_gap,
        basket_return - twii_return,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise ValueError("summary return gap does not equal basket minus TWII")

    basket_method = require_text(require(method, "basket"), "method.basket")
    require_text(require(method, "return"), "method.return")
    require_text(require(method, "volatility"), "method.volatility")
    if "no costs" not in basket_method:
        raise ValueError("Panel 4 requires the no-cost basket assumption")
    if "不構成投資建議" not in article:
        raise ValueError("Article evidence is missing the investment disclaimer")
    if len(documents) != 4:
        raise ValueError("Panel 4 requires four follow-up documents")

    fig = new_figure(WHITE)
    fig.text(
        0.055,
        0.946,
        "無人載具 EP3｜共同窗口市場比較",
        fontsize=12.5,
        color=BLUE,
        fontweight="bold",
        ha="left",
        va="center",
    )
    fig.text(
        0.055,
        0.892,
        "題材籃上漲，但報酬落後、波動更高",
        fontsize=28,
        fontweight="bold",
        ha="left",
        va="center",
    )
    fig.text(
        0.055,
        0.842,
        f"共同窗口 {start} 至 {end}｜{observations} 個交易日｜yfinance 還原收盤價",
        fontsize=12.8,
        color=MUTED,
        ha="left",
        va="center",
    )

    add_metric_bars(
        fig,
        x=0.055,
        y=0.565,
        w=0.430,
        h=0.220,
        title="共同窗口累積報酬",
        basket_value=basket_return,
        index_value=twii_return,
        signed=True,
    )
    add_metric_bars(
        fig,
        x=0.515,
        y=0.565,
        w=0.430,
        h=0.220,
        title="年化波動",
        basket_value=basket_volatility,
        index_value=twii_volatility,
        signed=False,
    )

    add_card(fig, 0.055, 0.465, 0.890, 0.065, face=RED_SOFT, edge=RED_SOFT)
    fig.text(
        0.080,
        0.498,
        f"十公司等權籃少 {pct(abs(return_gap))} 個百分點",
        fontsize=19.0,
        fontweight="bold",
        color=RED,
        ha="left",
        va="center",
    )
    fig.text(
        0.925,
        0.498,
        "描述性統計",
        fontsize=11.0,
        color=RED,
        ha="right",
        va="center",
    )

    fig.text(
        0.055,
        0.418,
        f"後續查核只收 {len(documents)} 張單據",
        fontsize=15.2,
        fontweight="bold",
        ha="left",
        va="center",
    )
    doc_xs = (0.055, 0.285, 0.515, 0.745)
    doc_colors = (BLUE_SOFT, TEAL_SOFT, AMBER_SOFT, GREEN_SOFT)
    doc_accents = (BLUE, TEAL, AMBER, GREEN)
    for index, ((name, _detail), x, soft, accent) in enumerate(
        zip(documents, doc_xs, doc_colors, doc_accents), start=1
    ):
        add_card(fig, x, 0.245, 0.200, 0.135, face=soft, edge=soft)
        add_rect(fig, x + 0.020, 0.278, 0.038, 0.062, face=WHITE, edge=accent,
                 linewidth=1.4, zorder=2)
        add_rect(fig, x + 0.028, 0.323, 0.022, 0.004, face=accent, zorder=3)
        add_rect(fig, x + 0.028, 0.311, 0.022, 0.004, face=accent, zorder=3)
        add_rect(fig, x + 0.028, 0.299, 0.017, 0.004, face=accent, zorder=3)
        fig.text(
            x + 0.073,
            0.310,
            name,
            fontsize=13.4,
            fontweight="bold",
            color=accent,
            ha="left",
            va="center",
        )
        fig.text(
            x + 0.020,
            0.263,
            "待公開文件核對",
            fontsize=9.7,
            color=MUTED,
            ha="left",
            va="center",
        )

    add_card(fig, 0.055, 0.105, 0.890, 0.095, face=PAPER, edge=BORDER)
    fig.text(
        0.080,
        0.153,
        "描述性統計｜等權籃每日再平衡、不含成本｜歷史不等於未來｜非投資建議",
        fontsize=11.7,
        fontweight="bold",
        color=MUTED,
        ha="left",
        va="center",
    )

    add_footer(fig)
    save_panel(fig, "4_portfolio_risk.png")


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    context = prepare_context()
    render_disclosure_ladder(context)
    render_method(context)
    render_budget_vs_orders(context)
    render_portfolio_risk(context)


if __name__ == "__main__":
    main()
