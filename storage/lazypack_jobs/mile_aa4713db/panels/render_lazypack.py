#!/usr/bin/env python3
"""Render four JSON-bound VolPred infographic panels for drone series EP4.

Every displayed statistic is loaded from the evidence JSON and derived at
runtime.  The article Markdown is used only for explicitly qualitative claims
that are absent from the JSON (operating stage, business attribution, and the
reader-facing conclusion).  Missing fields and missing article evidence fail
fast before any PNG is written.
"""
from __future__ import annotations

import json
import os
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Circle, FancyBboxPatch, Rectangle


EVIDENCE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/drafts/"
    "drone_ep4_six_dim_evidence.json"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_aa4713db/panels/mile_aa4713db_article.md"
)
OUT_DIR = (
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_aa4713db/panels"
)

WIDTH = 1600
HEIGHT = 1000
DPI = 150
FIGSIZE = (WIDTH / DPI, HEIGHT / DPI)

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False

NAVY = "#12233F"
INK = "#172033"
MUTED = "#586579"
FAINT = "#7C8798"
PAPER = "#FFFFFF"
SURFACE = "#F5F7FA"
GRID = "#DDE3EC"
BLUE = "#2463A8"
BLUE_SOFT = "#E9F1FA"
TEAL = "#147D78"
TEAL_SOFT = "#E5F4F2"
AMBER = "#B36B13"
AMBER_SOFT = "#FBF1DF"
RED = "#B83D43"
RED_SOFT = "#FBEAEC"
GREEN = "#277A50"
GREEN_SOFT = "#E9F4EE"
GREY_SOFT = "#EEF1F5"

EXPECTED_COMPANIES = (
    "雷虎",
    "漢翔",
    "亞航",
    "長榮航太",
    "中光電",
    "龍德造船",
)
DIMENSIONS = ("經營", "財務", "市場", "籌碼", "技術", "心理")

# These two thresholds are editorial definitions stated in the supplied article,
# not estimated statistics.  Their exact phrases are validated before use.
REVENUE_GROWTH_THRESHOLD = 0.05
RSI_OVERHEAT_THRESHOLD = 70.0


@dataclass(frozen=True)
class Package:
    evidence: dict[str, Any]
    article: str
    method: dict[str, Any]
    benchmark: dict[str, Any]
    companies: tuple[dict[str, Any], ...]
    by_name: dict[str, dict[str, Any]]
    latest_rows: dict[str, dict[str, Any]]
    previous_rows: dict[str, dict[str, Any]]
    valuation_date: str
    company_last_date: str


@dataclass
class TrackedText:
    artist: Any
    name: str


def require_key(mapping: dict[str, Any], key: str, path: str) -> Any:
    if key not in mapping:
        raise KeyError(f"Missing required field: {path}.{key}")
    return mapping[key]


def require_dict(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"Expected object at {path}, got {type(value).__name__}")
    return value


def require_list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise TypeError(f"Expected list at {path}, got {type(value).__name__}")
    return value


def require_str(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise TypeError(f"Expected non-empty string at {path}")
    return value


def require_num(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Expected number at {path}, got {type(value).__name__}")
    return float(value)


def nested(mapping: dict[str, Any], path: str, *keys: str) -> Any:
    current: Any = mapping
    walked = path
    for key in keys:
        current = require_key(require_dict(current, walked), key, walked)
        walked = f"{walked}.{key}"
    return current


def company_value(pkg: Package, name: str, *keys: str) -> Any:
    if name not in pkg.by_name:
        raise KeyError(f"Missing company: {name}")
    return nested(pkg.by_name[name], f"companies[name={name}]", *keys)


def company_num(pkg: Package, name: str, *keys: str) -> float:
    path = f"companies[name={name}].{'.'.join(keys)}"
    return require_num(company_value(pkg, name, *keys), path)


def latest_num(pkg: Package, name: str, key: str) -> float:
    row = pkg.latest_rows[name]
    latest_fy = require_str(
        nested(pkg.by_name[name], f"companies[name={name}]", "fundamental", "latest_fy"),
        f"companies[name={name}].fundamental.latest_fy",
    )
    return require_num(
        require_key(row, key, f"companies[name={name}].fundamental.fy_rows.{latest_fy}"),
        f"companies[name={name}].fundamental.fy_rows.{latest_fy}.{key}",
    )


def previous_num(pkg: Package, name: str, key: str) -> float:
    row = pkg.previous_rows[name]
    previous_fy = require_str(
        nested(pkg.by_name[name], f"companies[name={name}]", "fundamental", "previous_fy"),
        f"companies[name={name}].fundamental.previous_fy",
    )
    return require_num(
        require_key(row, key, f"companies[name={name}].fundamental.fy_rows.{previous_fy}"),
        f"companies[name={name}].fundamental.fy_rows.{previous_fy}.{key}",
    )


def require_article_phrases(article: str) -> None:
    phrases = (
        "經營、財務、市場、籌碼、技術、心理",
        "四檔的營收年增率不到 5%",
        "一般視為過熱的 70 以上",
        "量產出貨熱顯像無人機到澳洲",
        "已交付兩艘無人水面載具",
        "長榮航太是取得國防部監偵型無人機的供應商資格",
        "公開資料沒有拆出無人艇的營收與獲利",
        "同樣沒有揭露無人機營收占比",
        "最像純無人機股的雷虎，本業還在虧",
        "純度與獲利，目前沒有公開證據能畫上等號",
        "帳面上的稅後淨利",
        "來自業外損益",
    )
    for phrase in phrases:
        if phrase not in article:
            raise ValueError(f"Required article evidence is missing: {phrase}")


def load_package() -> Package:
    with EVIDENCE_PATH.open("r", encoding="utf-8") as handle:
        evidence_raw = json.load(handle)
    evidence = require_dict(evidence_raw, "$")
    article = ARTICLE_PATH.read_text(encoding="utf-8")
    require_article_phrases(article)

    method = require_dict(require_key(evidence, "method", "$"), "$.method")
    benchmark = require_dict(require_key(evidence, "benchmark", "$"), "$.benchmark")
    raw_companies = require_list(require_key(evidence, "companies", "$"), "$.companies")
    companies = tuple(
        require_dict(company, f"$.companies[{index}]")
        for index, company in enumerate(raw_companies)
    )

    by_name: dict[str, dict[str, Any]] = {}
    for index, company in enumerate(companies):
        name = require_str(require_key(company, "name", f"$.companies[{index}]"), f"$.companies[{index}].name")
        if name in by_name:
            raise ValueError(f"Duplicate company name: {name}")
        by_name[name] = company
    if tuple(by_name) != EXPECTED_COMPANIES:
        raise ValueError(
            "Company universe/order mismatch: "
            f"expected {EXPECTED_COMPANIES}, got {tuple(by_name)}"
        )

    # Validate method metadata used by Panel 2 and every footer.
    require_str(require_key(evidence, "generated_at_tw", "$"), "$.generated_at_tw")
    require_str(require_key(evidence, "as_of_date", "$"), "$.as_of_date")
    require_str(require_key(method, "universe", "$.method"), "$.method.universe")
    require_str(require_key(method, "price_source", "$.method"), "$.method.price_source")
    require_str(require_key(method, "financial_source", "$.method"), "$.method.financial_source")
    require_str(require_key(method, "chip_source", "$.method"), "$.method.chip_source")
    require_str(require_key(method, "disclaimer", "$.method"), "$.method.disclaimer")
    price_window = require_list(require_key(method, "price_window", "$.method"), "$.method.price_window")
    chip_range = require_list(require_key(method, "chip_date_range", "$.method"), "$.method.chip_date_range")
    if len(price_window) != 2 or len(chip_range) != 2:
        raise ValueError("price_window and chip_date_range must each contain two endpoints")
    for index, value in enumerate(price_window):
        require_str(value, f"$.method.price_window[{index}]")
    for index, value in enumerate(chip_range):
        require_str(value, f"$.method.chip_date_range[{index}]")
    require_num(
        require_key(method, "chip_lookback_trading_days", "$.method"),
        "$.method.chip_lookback_trading_days",
    )
    require_list(
        require_key(method, "chip_fetch_failed_dates", "$.method"),
        "$.method.chip_fetch_failed_dates",
    )
    require_num(
        require_key(method, "chip_cell_parse_failures", "$.method"),
        "$.method.chip_cell_parse_failures",
    )

    for key in (
        "window_return",
        "annualized_volatility",
        "max_drawdown",
        "beta_vs_twii",
        "corr_vs_twii",
    ):
        require_num(require_key(benchmark, key, "$.benchmark"), f"$.benchmark.{key}")
    require_str(require_key(benchmark, "last_date", "$.benchmark"), "$.benchmark.last_date")

    latest_rows: dict[str, dict[str, Any]] = {}
    previous_rows: dict[str, dict[str, Any]] = {}
    valuation_dates: set[str] = set()
    company_last_dates: set[str] = set()
    for name in EXPECTED_COMPANIES:
        company = by_name[name]
        technical = require_dict(require_key(company, "technical", f"companies[name={name}]"), f"companies[name={name}].technical")
        market = require_dict(require_key(company, "market", f"companies[name={name}]"), f"companies[name={name}].market")
        fundamental = require_dict(require_key(company, "fundamental", f"companies[name={name}]"), f"companies[name={name}].fundamental")
        chip = require_dict(require_key(company, "chip", f"companies[name={name}]"), f"companies[name={name}].chip")

        for key in ("vs_ma20", "vs_ma60", "vs_ma200", "rsi14"):
            require_num(require_key(technical, key, f"companies[name={name}].technical"), f"companies[name={name}].technical.{key}")
        for key in (
            "window_return",
            "annualized_volatility",
            "max_drawdown",
            "beta_vs_twii",
            "corr_vs_twii",
        ):
            require_num(require_key(market, key, f"companies[name={name}].market"), f"companies[name={name}].market.{key}")
        company_last_dates.add(
            require_str(require_key(market, "last_date", f"companies[name={name}].market"), f"companies[name={name}].market.last_date")
        )

        for key in ("revenue_yoy", "return_on_equity", "pe_asof", "pb_asof"):
            require_num(require_key(fundamental, key, f"companies[name={name}].fundamental"), f"companies[name={name}].fundamental.{key}")
        latest_fy = require_str(require_key(fundamental, "latest_fy", f"companies[name={name}].fundamental"), f"companies[name={name}].fundamental.latest_fy")
        previous_fy = require_str(require_key(fundamental, "previous_fy", f"companies[name={name}].fundamental"), f"companies[name={name}].fundamental.previous_fy")
        fy_rows = require_dict(require_key(fundamental, "fy_rows", f"companies[name={name}].fundamental"), f"companies[name={name}].fundamental.fy_rows")
        latest_rows[name] = require_dict(require_key(fy_rows, latest_fy, f"companies[name={name}].fundamental.fy_rows"), f"companies[name={name}].fundamental.fy_rows.{latest_fy}")
        previous_rows[name] = require_dict(require_key(fy_rows, previous_fy, f"companies[name={name}].fundamental.fy_rows"), f"companies[name={name}].fundamental.fy_rows.{previous_fy}")
        for row, year in ((latest_rows[name], latest_fy), (previous_rows[name], previous_fy)):
            for key in ("revenue", "operating_income", "net_income", "operating_margin"):
                require_num(require_key(row, key, f"companies[name={name}].fundamental.fy_rows.{year}"), f"companies[name={name}].fundamental.fy_rows.{year}.{key}")
        valuation_dates.add(
            require_str(require_key(fundamental, "valuation_asof_date", f"companies[name={name}].fundamental"), f"companies[name={name}].fundamental.valuation_asof_date")
        )

        source = require_key(chip, "source", f"companies[name={name}].chip")
        if name == "中光電":
            if source is not None:
                raise ValueError("中光電 chip.source must remain null for the non-comparable 60-day field")
            require_str(require_key(chip, "note", f"companies[name={name}].chip"), f"companies[name={name}].chip.note")
        else:
            require_str(source, f"companies[name={name}].chip.source")
            for key in (
                "trading_days",
                "foreign_net_shares",
                "total_net_shares",
                "total_net_pct_of_shares_out",
            ):
                require_num(require_key(chip, key, f"companies[name={name}].chip"), f"companies[name={name}].chip.{key}")

    if len(valuation_dates) != 1:
        raise ValueError(f"Valuation dates are inconsistent: {sorted(valuation_dates)}")
    if len(company_last_dates) != 1:
        raise ValueError(f"Company price last dates are inconsistent: {sorted(company_last_dates)}")

    return Package(
        evidence=evidence,
        article=article,
        method=method,
        benchmark=benchmark,
        companies=companies,
        by_name=by_name,
        latest_rows=latest_rows,
        previous_rows=previous_rows,
        valuation_date=next(iter(valuation_dates)),
        company_last_date=next(iter(company_last_dates)),
    )


def compact_date(value: str) -> str:
    if len(value) == 8 and value.isdigit():
        return f"{value[:4]}-{value[4:6]}-{value[6:]}"
    return value


def pct(value: float, digits: int = 1, signed: bool = False) -> str:
    sign = "+" if signed else ""
    return f"{value * 100:{sign}.{digits}f}%"


def multiple(value: float, digits: int = 1) -> str:
    return f"{value:.{digits}f} 倍"


def money_twd(value: float) -> str:
    if abs(value) >= 100_000_000:
        return f"{value / 100_000_000:.1f} 億"
    return f"{value / 10_000:,.0f} 萬"


def shares_wan(value: float) -> str:
    return f"{value / 10_000:,.0f} 萬股"


def revenue_yi(value: float) -> str:
    return f"{value / 100_000_000:.0f} 億"


def zh_wrap(text: str, width: int) -> str:
    lines: list[str] = []
    for paragraph in text.splitlines() or [""]:
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
        )
    return "\n".join(lines)


def new_figure() -> tuple[Any, Any, list[TrackedText]]:
    fig = plt.figure(figsize=FIGSIZE, dpi=DPI, facecolor=PAPER)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    return fig, ax, []


def add_text(
    fig: Any,
    tracked: list[TrackedText],
    x: float,
    y: float,
    text: str,
    *,
    size: float,
    color: str = INK,
    weight: str = "normal",
    ha: str = "left",
    va: str = "top",
    wrap: int | None = None,
    linespacing: float = 1.22,
    name: str = "text",
) -> Any:
    rendered = zh_wrap(text, wrap) if wrap else text
    artist = fig.text(
        x,
        y,
        rendered,
        fontsize=size,
        color=color,
        fontweight=weight,
        ha=ha,
        va=va,
        linespacing=linespacing,
        transform=fig.transFigure,
        zorder=10,
    )
    tracked.append(TrackedText(artist=artist, name=f"{name}:{rendered[:30]}"))
    return artist


def box(
    fig: Any,
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    face: str = PAPER,
    edge: str = GRID,
    radius: float = 0.018,
    linewidth: float = 1.2,
) -> None:
    patch = FancyBboxPatch(
        (x, y),
        width,
        height,
        boxstyle=f"round,pad=0.006,rounding_size={radius}",
        facecolor=face,
        edgecolor=edge,
        linewidth=linewidth,
        transform=fig.transFigure,
        zorder=1,
    )
    fig.add_artist(patch)


def rule(fig: Any, x1: float, y1: float, x2: float, y2: float, color: str = GRID, width: float = 1.0) -> None:
    fig.add_artist(
        Line2D(
            [x1, x2],
            [y1, y2],
            color=color,
            linewidth=width,
            transform=fig.transFigure,
            zorder=2,
        )
    )


def dot(fig: Any, x: float, y: float, radius: float, color: str) -> None:
    fig.add_artist(Circle((x, y), radius, facecolor=color, edgecolor="none", transform=fig.transFigure, zorder=3))


def pill(
    fig: Any,
    tracked: list[TrackedText],
    x: float,
    y: float,
    width: float,
    height: float,
    label: str,
    *,
    face: str,
    color: str = INK,
    size: float = 11.0,
    edge: str = "none",
    name: str = "pill",
) -> None:
    box(fig, x, y, width, height, face=face, edge=edge, radius=height / 2, linewidth=0.8)
    add_text(
        fig,
        tracked,
        x + width / 2,
        y + height / 2,
        label,
        size=size,
        color=color,
        weight="bold",
        ha="center",
        va="center",
        name=name,
    )


def header(fig: Any, tracked: list[TrackedText], title: str, subtitle: str, accent: str) -> None:
    fig.add_artist(Rectangle((0, 0.825), 1, 0.175, facecolor=NAVY, edgecolor="none", transform=fig.transFigure, zorder=0))
    fig.add_artist(Rectangle((0.055, 0.966), 0.085, 0.006, facecolor=accent, edgecolor="none", transform=fig.transFigure, zorder=2))
    add_text(fig, tracked, 0.055, 0.958, "VolPred｜無人載具 EP4", size=9.5, color="#C9D6EA", weight="bold", name="header-kicker")
    add_text(fig, tracked, 0.055, 0.928, title, size=29.0, color=PAPER, weight="bold", name="header-title")
    add_text(fig, tracked, 0.055, 0.856, subtitle, size=11.5, color="#DCE5F2", wrap=72, name="header-subtitle")


def footer(fig: Any, tracked: list[TrackedText], pkg: Package) -> None:
    as_of = require_str(require_key(pkg.evidence, "as_of_date", "$"), "$.as_of_date")
    rule(fig, 0.055, 0.071, 0.945, 0.071, color=GRID, width=0.9)
    source = (
        f"資料來源：{EVIDENCE_PATH.name}（查核日 {as_of}；證據包未提供 experiment K 編號）｜"
        f"經營階段文字：{ARTICLE_PATH.name}"
    )
    add_text(fig, tracked, 0.055, 0.055, source, size=8.2, color=FAINT, wrap=104, name="footer-source")


def validate_layout(fig: Any, tracked: list[TrackedText], panel_name: str) -> None:
    """Fail if any text is clipped or overlaps another text bounding box."""
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    canvas = fig.bbox
    measured: list[tuple[TrackedText, Any]] = []
    for item in tracked:
        extent = item.artist.get_window_extent(renderer=renderer)
        if (
            extent.x0 < canvas.x0 + 4
            or extent.y0 < canvas.y0 + 4
            or extent.x1 > canvas.x1 - 4
            or extent.y1 > canvas.y1 - 4
        ):
            raise RuntimeError(f"{panel_name}: text outside canvas: {item.name}")
        measured.append((item, extent))

    for index, (left_item, left_box) in enumerate(measured):
        for right_item, right_box in measured[index + 1 :]:
            overlap_x = min(left_box.x1, right_box.x1) - max(left_box.x0, right_box.x0)
            overlap_y = min(left_box.y1, right_box.y1) - max(left_box.y0, right_box.y0)
            if overlap_x > 1.0 and overlap_y > 1.0:
                raise RuntimeError(
                    f"{panel_name}: text collision between {left_item.name} and {right_item.name}"
                )


def save_panel(fig: Any, tracked: list[TrackedText], filename: str) -> None:
    validate_layout(fig, tracked, filename)
    path = Path(OUT_DIR) / filename
    fig.savefig(
        path,
        format="png",
        dpi=DPI,
        facecolor=PAPER,
        edgecolor="none",
        bbox_inches=None,
        pad_inches=0,
        metadata={"Title": filename, "Author": "VolPred"},
    )
    plt.close(fig)


def derive(pkg: Package) -> dict[str, Any]:
    n = len(pkg.companies)
    all_ma_count = sum(
        all(company_num(pkg, name, "technical", key) > 0 for key in ("vs_ma20", "vs_ma60", "vs_ma200"))
        for name in EXPECTED_COMPANIES
    )
    rsi = {name: company_num(pkg, name, "technical", "rsi14") for name in EXPECTED_COMPANIES}
    overheated = sorted(
        (name for name, value in rsi.items() if value > RSI_OVERHEAT_THRESHOLD),
        key=lambda name: rsi[name],
        reverse=True,
    )
    revenue_yoy = {name: company_num(pkg, name, "fundamental", "revenue_yoy") for name in EXPECTED_COMPANIES}
    weak_growth = [name for name, value in revenue_yoy.items() if value < REVENUE_GROWTH_THRESHOLD]

    chip_names = [name for name in EXPECTED_COMPANIES if name != "中光電"]
    chip_pct = {
        name: company_num(pkg, name, "chip", "total_net_pct_of_shares_out")
        for name in chip_names
    }
    negative_chip = [name for name, value in chip_pct.items() if value < 0]
    chip_days = {int(company_num(pkg, name, "chip", "trading_days")) for name in chip_names}
    method_days = int(require_num(require_key(pkg.method, "chip_lookback_trading_days", "$.method"), "$.method.chip_lookback_trading_days"))
    if chip_days != {method_days}:
        raise ValueError(f"Per-company chip trading_days mismatch: {chip_days} vs method {method_days}")

    pe = [company_num(pkg, name, "fundamental", "pe_asof") for name in EXPECTED_COMPANIES]
    returns = [company_num(pkg, name, "market", "window_return") for name in EXPECTED_COMPANIES]
    benchmark_return = require_num(require_key(pkg.benchmark, "window_return", "$.benchmark"), "$.benchmark.window_return")
    vol = [company_num(pkg, name, "market", "annualized_volatility") for name in EXPECTED_COMPANIES]
    mdd = [abs(company_num(pkg, name, "market", "max_drawdown")) for name in EXPECTED_COMPANIES]
    beta = [company_num(pkg, name, "market", "beta_vs_twii") for name in EXPECTED_COMPANIES]
    corr = [company_num(pkg, name, "market", "corr_vs_twii") for name in EXPECTED_COMPANIES]

    failed_dates = require_list(require_key(pkg.method, "chip_fetch_failed_dates", "$.method"), "$.method.chip_fetch_failed_dates")
    parse_failures = int(require_num(require_key(pkg.method, "chip_cell_parse_failures", "$.method"), "$.method.chip_cell_parse_failures"))

    return {
        "n": n,
        "all_ma_count": all_ma_count,
        "rsi": rsi,
        "overheated": overheated,
        "weak_growth": weak_growth,
        "revenue_yoy": revenue_yoy,
        "chip_pct": chip_pct,
        "negative_chip": negative_chip,
        "chip_days": method_days,
        "fetch_success": method_days - len(failed_dates),
        "failed_count": len(failed_dates),
        "parse_failures": parse_failures,
        "pe_min": min(pe),
        "pe_max": max(pe),
        "underperform_count": sum(value < benchmark_return for value in returns),
        "benchmark_return": benchmark_return,
        "vol_min": min(vol),
        "vol_max": max(vol),
        "benchmark_vol": require_num(require_key(pkg.benchmark, "annualized_volatility", "$.benchmark"), "$.benchmark.annualized_volatility"),
        "mdd_min": min(mdd),
        "mdd_max": max(mdd),
        "benchmark_mdd": abs(require_num(require_key(pkg.benchmark, "max_drawdown", "$.benchmark"), "$.benchmark.max_drawdown")),
        "beta_min": min(beta),
        "beta_max": max(beta),
        "corr_min": min(corr),
        "corr_max": max(corr),
    }


def render_panel_1(pkg: Package, stats: dict[str, Any]) -> None:
    fig, _, tracked = new_figure()
    header(
        fig,
        tracked,
        "六檔龍頭，六個面向：熱度與實績正在分裂",
        "同一套散戶常用框架，跑在五檔空中載具與一檔海域載具龍頭上。",
        TEAL,
    )

    add_text(fig, tracked, 0.055, 0.796, f"{stats['n']} 檔龍頭", size=11.5, color=MUTED, weight="bold", name="p1-company-label")
    company_width = (0.89 - 5 * 0.012) / 6
    for index, name in enumerate(EXPECTED_COMPANIES):
        pill(
            fig,
            tracked,
            0.055 + index * (company_width + 0.012),
            0.720,
            company_width,
            0.052,
            name,
            face=GREY_SOFT,
            color=INK,
            size=10.8,
            name=f"p1-company-{name}",
        )

    add_text(fig, tracked, 0.055, 0.690, f"散戶常用的 {len(DIMENSIONS)} 個面向", size=11.5, color=MUTED, weight="bold", name="p1-dimension-label")
    dim_width = company_width
    for index, name in enumerate(DIMENSIONS):
        if name in ("技術", "籌碼"):
            face, color = BLUE_SOFT, BLUE
        elif name in ("經營", "財務"):
            face, color = AMBER_SOFT, AMBER
        else:
            face, color = GREY_SOFT, MUTED
        pill(
            fig,
            tracked,
            0.055 + index * (dim_width + 0.012),
            0.615,
            dim_width,
            0.052,
            name,
            face=face,
            color=color,
            size=11.4,
            name=f"p1-dimension-{name}",
        )

    box(fig, 0.055, 0.315, 0.43, 0.255, face=BLUE_SOFT, edge="#C8DDF3")
    add_text(fig, tracked, 0.085, 0.545, "衡量熱度", size=13.5, color=BLUE, weight="bold", name="p1-heat-title")
    add_text(fig, tracked, 0.085, 0.495, "技術 ＋ 籌碼", size=22.0, color=INK, weight="bold", name="p1-heat-pair")
    add_text(
        fig,
        tracked,
        0.085,
        0.425,
        f"{stats['all_ma_count']} / {stats['n']}",
        size=31.0,
        color=BLUE,
        weight="bold",
        name="p1-heat-hero",
    )
    add_text(fig, tracked, 0.225, 0.405, "全數站上月線、季線、年線\n法人可比標的也幾乎全為淨買", size=11.2, color=MUTED, wrap=22, name="p1-heat-note")

    box(fig, 0.515, 0.315, 0.43, 0.255, face=AMBER_SOFT, edge="#EAD2A8")
    add_text(fig, tracked, 0.545, 0.545, "衡量實績", size=13.5, color=AMBER, weight="bold", name="p1-substance-title")
    add_text(fig, tracked, 0.545, 0.495, "經營 ＋ 財務", size=22.0, color=INK, weight="bold", name="p1-substance-pair")
    add_text(
        fig,
        tracked,
        0.545,
        0.425,
        f"{len(stats['weak_growth'])} / {stats['n']}",
        size=31.0,
        color=AMBER,
        weight="bold",
        name="p1-substance-hero",
    )
    add_text(fig, tracked, 0.685, 0.405, "營收年增未達 5%\n公開交付與當期獲利沒有同步", size=11.2, color=MUTED, wrap=22, name="p1-substance-note")

    box(fig, 0.055, 0.105, 0.89, 0.155, face=NAVY, edge=NAVY)
    add_text(fig, tracked, 0.085, 0.232, "不要把六個面向當成六個分數加總", size=20.0, color=PAPER, weight="bold", name="p1-core-title")
    add_text(fig, tracked, 0.085, 0.181, "彼此矛盾時，先問：哪一個面向在說真話？", size=14.0, color="#DCE7F5", weight="bold", name="p1-core-question")
    add_text(fig, tracked, 0.085, 0.137, "市場與心理提供風險、估值背景；不能拿來沖銷經營與財務的缺口。", size=10.4, color="#B9C8DB", name="p1-core-note")

    footer(fig, tracked, pkg)
    save_panel(fig, tracked, "1_six_dimensions.png")


def render_panel_2(pkg: Package, stats: dict[str, Any]) -> None:
    fig, _, tracked = new_figure()
    header(
        fig,
        tracked,
        "先固定資料口徑，再比較六檔龍頭",
        "標的、股價、年報與籌碼各自有不同來源；所有估值停在同一個查核點。",
        BLUE,
    )

    box(fig, 0.055, 0.115, 0.575, 0.675, face=PAPER, edge=GRID)
    add_text(fig, tracked, 0.085, 0.762, "四段資料流程", size=15.0, color=INK, weight="bold", name="p2-flow-title")

    price_window = require_list(require_key(pkg.method, "price_window", "$.method"), "$.method.price_window")
    chip_range = require_list(require_key(pkg.method, "chip_date_range", "$.method"), "$.method.chip_date_range")
    universe = require_str(require_key(pkg.method, "universe", "$.method"), "$.method.universe")
    price_source = require_str(require_key(pkg.method, "price_source", "$.method"), "$.method.price_source")
    financial_source = require_str(require_key(pkg.method, "financial_source", "$.method"), "$.method.financial_source")
    chip_source = require_str(require_key(pkg.method, "chip_source", "$.method"), "$.method.chip_source")

    steps = (
        ("01", "標的", universe, 0.695),
        (
            "02",
            "股價",
            f"{price_source}｜下載窗口 {price_window[0]} 至 {price_window[1]}；實際末筆個股 {pkg.company_last_date}、指數 {require_str(require_key(pkg.benchmark, 'last_date', '$.benchmark'), '$.benchmark.last_date')}。",
            0.550,
        ),
        (
            "03",
            "財報",
            f"{financial_source}｜營收、營業利益率、淨利與股東權益報酬率。",
            0.405,
        ),
        (
            "04",
            "籌碼",
            f"{chip_source}｜{compact_date(require_str(chip_range[0], '$.method.chip_date_range[0]'))} 至 {compact_date(require_str(chip_range[1], '$.method.chip_date_range[1]'))}，共 {stats['chip_days']} 個交易日。",
            0.260,
        ),
    )
    for index, (number, label, description, y) in enumerate(steps):
        dot(fig, 0.095, y + 0.002, 0.022, BLUE if index < 3 else TEAL)
        add_text(fig, tracked, 0.095, y + 0.002, number, size=8.3, color=PAPER, weight="bold", ha="center", va="center", name=f"p2-step-number-{number}")
        add_text(fig, tracked, 0.135, y + 0.025, label, size=12.8, color=INK, weight="bold", name=f"p2-step-label-{number}")
        add_text(fig, tracked, 0.135, y - 0.013, description, size=9.6, color=MUTED, wrap=42, linespacing=1.18, name=f"p2-step-desc-{number}")
        if index < len(steps) - 1:
            rule(fig, 0.095, y - 0.065, 0.600, y - 0.065, color=GRID, width=0.8)

    box(fig, 0.660, 0.500, 0.285, 0.290, face=TEAL_SOFT, edge="#C5E2DF")
    add_text(fig, tracked, 0.690, 0.760, "籌碼抓取完整性", size=13.5, color=TEAL, weight="bold", name="p2-fetch-title")
    add_text(
        fig,
        tracked,
        0.690,
        0.705,
        f"{stats['fetch_success']} / {stats['chip_days']}",
        size=31.0,
        color=INK,
        weight="bold",
        name="p2-fetch-hero",
    )
    add_text(fig, tracked, 0.690, 0.640, "交易日全數抓取成功", size=11.0, color=MUTED, weight="bold", name="p2-fetch-note")
    add_text(
        fig,
        tracked,
        0.690,
        0.590,
        f"失敗日 {stats['failed_count']}｜欄位解析失敗 {stats['parse_failures']}",
        size=10.2,
        color=INK,
        name="p2-fetch-errors",
    )
    add_text(
        fig,
        tracked,
        0.690,
        0.545,
        f"區間：{compact_date(require_str(chip_range[0], '$.method.chip_date_range[0]'))}\n至 {compact_date(require_str(chip_range[1], '$.method.chip_date_range[1]'))}",
        size=9.5,
        color=FAINT,
        name="p2-fetch-range",
    )

    box(fig, 0.660, 0.115, 0.285, 0.345, face=BLUE_SOFT, edge="#CADDF1")
    add_text(fig, tracked, 0.690, 0.432, "固定估值口徑", size=13.5, color=BLUE, weight="bold", name="p2-value-title")
    add_text(fig, tracked, 0.690, 0.385, pkg.valuation_date, size=24.0, color=INK, weight="bold", name="p2-value-date")
    add_text(fig, tracked, 0.690, 0.329, "JSON 中的估值最後交易日", size=9.4, color=MUTED, name="p2-value-date-label")
    add_text(
        fig,
        tracked,
        0.690,
        0.292,
        f"下載窗口上界為 {price_window[1]}；本益比、股價淨值比讀 pe_asof／pb_asof 固定值，不採盤中即時值。",
        size=8.8,
        color=INK,
        wrap=23,
        linespacing=1.16,
        name="p2-value-method",
    )
    chip_note = require_str(company_value(pkg, "中光電", "chip", "note"), "companies[name=中光電].chip.note")
    if "最近一日" not in chip_note or "60 日" not in chip_note:
        raise ValueError("中光電 chip.note no longer supports the stated blank-cell treatment")
    add_text(
        fig,
        tracked,
        0.690,
        0.210,
        f"中光電：上櫃；TWSE T86 不含，TPEx 僅最近一日，{stats['chip_days']} 日欄位留白。",
        size=8.8,
        color=MUTED,
        wrap=23,
        linespacing=1.16,
        name="p2-value-otc",
    )
    as_of = require_str(require_key(pkg.evidence, "as_of_date", "$"), "$.as_of_date")
    add_text(fig, tracked, 0.690, 0.142, f"查核日：{as_of}", size=9.2, color=BLUE, weight="bold", name="p2-asof")

    footer(fig, tracked, pkg)
    save_panel(fig, tracked, "2_method.png")


def render_panel_3(pkg: Package, stats: dict[str, Any]) -> None:
    fig, _, tracked = new_figure()
    header(
        fig,
        tracked,
        "熱度幾乎全票通過，實績卻只跟上一小段",
        "技術、法人、營收、獲利與估值放在同一頁，錯位就會變得很清楚。",
        RED,
    )

    box(fig, 0.055, 0.560, 0.430, 0.235, face=BLUE_SOFT, edge="#C9DDF2")
    add_text(fig, tracked, 0.082, 0.765, "技術｜價格動能", size=13.0, color=BLUE, weight="bold", name="p3-tech-title")
    add_text(fig, tracked, 0.082, 0.710, f"{stats['all_ma_count']} / {stats['n']}", size=29.0, color=INK, weight="bold", name="p3-tech-hero")
    add_text(fig, tracked, 0.220, 0.695, "站上月線、季線、年線", size=10.7, color=MUTED, weight="bold", name="p3-tech-ma")
    rsi_min = min(stats["rsi"].values())
    rsi_max = max(stats["rsi"].values())
    add_text(fig, tracked, 0.082, 0.642, f"RSI {rsi_min:.0f}–{rsi_max:.0f}", size=14.5, color=BLUE, weight="bold", name="p3-tech-rsi")
    hot_text = "｜".join(f"{name} {stats['rsi'][name]:.0f}" for name in stats["overheated"])
    add_text(fig, tracked, 0.082, 0.597, f"過熱線 70 以上：{hot_text}", size=9.8, color=MUTED, name="p3-tech-hot")

    box(fig, 0.515, 0.560, 0.430, 0.235, face=TEAL_SOFT, edge="#C4E1DE")
    add_text(fig, tracked, 0.542, 0.765, f"籌碼｜三大法人 {stats['chip_days']} 日", size=13.0, color=TEAL, weight="bold", name="p3-chip-title")
    thunder_chip = stats["chip_pct"]["雷虎"]
    add_text(fig, tracked, 0.542, 0.710, pct(thunder_chip, 2, signed=True), size=28.0, color=INK, weight="bold", name="p3-chip-hero")
    thunder_foreign = company_num(pkg, "雷虎", "chip", "foreign_net_shares")
    add_text(fig, tracked, 0.720, 0.695, f"雷虎／股本\n外資買超 {shares_wan(thunder_foreign)}", size=9.8, color=MUTED, weight="bold", name="p3-chip-thunder")
    compare_names = ("長榮航太", "漢翔", "龍德造船", "亞航")
    compare_text = "｜".join(f"{name} {pct(stats['chip_pct'][name], 2, signed=True)}" for name in compare_names)
    add_text(fig, tracked, 0.542, 0.627, compare_text, size=9.3, color=INK, wrap=35, linespacing=1.17, name="p3-chip-compare")
    if len(stats["negative_chip"]) != 1:
        raise ValueError(f"Expected one net seller among comparable stocks, got {stats['negative_chip']}")
    add_text(fig, tracked, 0.542, 0.582, f"唯一淨賣：{stats['negative_chip'][0]}｜中光電同口徑留白", size=9.2, color=TEAL, weight="bold", name="p3-chip-exception")

    box(fig, 0.055, 0.320, 0.430, 0.195, face=RED_SOFT, edge="#EAC9CC")
    add_text(fig, tracked, 0.082, 0.485, "本業｜兩家公司營業虧損", size=13.0, color=RED, weight="bold", name="p3-op-title")
    thunder_margin = latest_num(pkg, "雷虎", "operating_margin")
    coretronic_margin = latest_num(pkg, "中光電", "operating_margin")
    add_text(fig, tracked, 0.082, 0.430, pct(thunder_margin, 1), size=23.0, color=INK, weight="bold", name="p3-op-thunder-value")
    add_text(fig, tracked, 0.082, 0.378, "雷虎營業利益率", size=9.2, color=MUTED, name="p3-op-thunder-label")
    add_text(fig, tracked, 0.260, 0.430, pct(coretronic_margin, 1), size=23.0, color=INK, weight="bold", name="p3-op-coretronic-value")
    add_text(fig, tracked, 0.260, 0.378, "中光電營業利益率", size=9.2, color=MUTED, name="p3-op-coretronic-label")
    add_text(
        fig,
        tracked,
        0.082,
        0.342,
        f"帳面淨利：雷虎 {money_twd(latest_num(pkg, '雷虎', 'net_income'))}｜中光電 {money_twd(latest_num(pkg, '中光電', 'net_income'))}；正文歸因於業外損益。",
        size=8.7,
        color=RED,
        name="p3-op-net-income",
    )

    box(fig, 0.515, 0.320, 0.430, 0.195, face=AMBER_SOFT, edge="#E9D3AE")
    add_text(fig, tracked, 0.542, 0.485, "成長｜財報還沒追上股價", size=13.0, color=AMBER, weight="bold", name="p3-growth-title")
    aidc_yoy = stats["revenue_yoy"]["漢翔"]
    add_text(fig, tracked, 0.542, 0.430, pct(aidc_yoy, 1), size=23.0, color=INK, weight="bold", name="p3-growth-aidc")
    add_text(
        fig,
        tracked,
        0.542,
        0.378,
        f"漢翔營收：{revenue_yi(previous_num(pkg, '漢翔', 'revenue'))} → {revenue_yi(latest_num(pkg, '漢翔', 'revenue'))}",
        size=9.5,
        color=MUTED,
        name="p3-growth-aidc-label",
    )
    add_text(fig, tracked, 0.755, 0.430, f"{len(stats['weak_growth'])} / {stats['n']}", size=23.0, color=AMBER, weight="bold", name="p3-growth-count")
    add_text(fig, tracked, 0.755, 0.378, "營收年增未達 5%", size=9.5, color=MUTED, name="p3-growth-count-label")
    add_text(fig, tracked, 0.542, 0.342, "熱度一致，營收與本業獲利卻高度分化。", size=8.9, color=AMBER, weight="bold", name="p3-growth-note")

    box(fig, 0.055, 0.105, 0.890, 0.170, face=NAVY, edge=NAVY)
    add_text(fig, tracked, 0.082, 0.247, "估值｜市場買的是未來，不是現在的損益表", size=12.5, color="#B9CAE0", weight="bold", name="p3-value-title")
    add_text(fig, tracked, 0.082, 0.197, f"約 {stats['pe_min']:.0f}–{stats['pe_max']:.0f} 倍", size=24.0, color=PAPER, weight="bold", name="p3-value-pe")
    add_text(fig, tracked, 0.082, 0.145, "六檔查核日本益比", size=9.2, color="#B9CAE0", name="p3-value-pe-label")
    thunder_pb = company_num(pkg, "雷虎", "fundamental", "pb_asof")
    thunder_roe = company_num(pkg, "雷虎", "fundamental", "return_on_equity")
    add_text(fig, tracked, 0.500, 0.197, f"雷虎 P/B {thunder_pb:.2f} 倍", size=20.0, color=PAPER, weight="bold", name="p3-value-pb")
    add_text(fig, tracked, 0.500, 0.150, f"但股東權益報酬率只有 {pct(thunder_roe, 2)}", size=10.5, color="#D6E0ED", name="p3-value-roe")

    footer(fig, tracked, pkg)
    save_panel(fig, tracked, "3_heat_vs_substance.png")


def render_panel_4(pkg: Package, stats: dict[str, Any]) -> None:
    fig, _, tracked = new_figure()
    header(
        fig,
        tracked,
        "唯一交集只有龍德，但交付不等於獲利來源",
        "經營進度、財務品質與題材純度拆開看，才不會把不同生意混成同一張成績單。",
        AMBER,
    )

    box(fig, 0.055, 0.590, 0.420, 0.205, face=TEAL_SOFT, edge="#C7E3DF")
    add_text(fig, tracked, 0.082, 0.765, "經營面較扎實", size=13.0, color=TEAL, weight="bold", name="p4-ops-title")
    add_text(fig, tracked, 0.082, 0.710, "中光電", size=14.5, color=INK, weight="bold", name="p4-ops-coretronic")
    add_text(fig, tracked, 0.205, 0.705, "量產出貨澳洲", size=10.5, color=MUTED, name="p4-ops-coretronic-note")
    add_text(fig, tracked, 0.082, 0.652, "龍德造船", size=14.5, color=INK, weight="bold", name="p4-ops-lungteh")
    add_text(fig, tracked, 0.205, 0.647, "已交付兩艘無人水面載具", size=10.5, color=MUTED, name="p4-ops-lungteh-note")
    add_text(fig, tracked, 0.082, 0.607, "經營階段來自文章所列公開揭露，不是營收占比。", size=8.6, color=TEAL, name="p4-ops-caveat")

    box(fig, 0.525, 0.590, 0.420, 0.205, face=GREEN_SOFT, edge="#CDE3D6")
    add_text(fig, tracked, 0.552, 0.765, "財務面較扎實", size=13.0, color=GREEN, weight="bold", name="p4-fin-title")
    eva_roe = company_num(pkg, "長榮航太", "fundamental", "return_on_equity")
    lungteh_roe = company_num(pkg, "龍德造船", "fundamental", "return_on_equity")
    add_text(fig, tracked, 0.552, 0.710, "長榮航太", size=14.5, color=INK, weight="bold", name="p4-fin-eva")
    add_text(fig, tracked, 0.720, 0.710, pct(eva_roe, 1), size=16.5, color=GREEN, weight="bold", name="p4-fin-eva-roe")
    add_text(fig, tracked, 0.552, 0.652, "龍德造船", size=14.5, color=INK, weight="bold", name="p4-fin-lungteh")
    add_text(fig, tracked, 0.720, 0.652, pct(lungteh_roe, 1), size=16.5, color=GREEN, weight="bold", name="p4-fin-lungteh-roe")
    add_text(fig, tracked, 0.552, 0.607, "股東權益報酬率；不代表獲利來自無人載具。", size=8.6, color=GREEN, name="p4-fin-caveat")

    pill(fig, tracked, 0.385, 0.542, 0.230, 0.042, "兩張名單唯一交集：龍德造船", face=NAVY, color=PAPER, size=9.3, name="p4-overlap")

    box(fig, 0.055, 0.430, 0.890, 0.085, face=AMBER_SOFT, edge="#E8D0A4")
    add_text(fig, tracked, 0.082, 0.494, "純度 ≠ 已證明的獲利來源", size=18.0, color=INK, weight="bold", name="p4-conclusion")
    thunder_margin = latest_num(pkg, "雷虎", "operating_margin")
    add_text(
        fig,
        tracked,
        0.500,
        0.493,
        f"龍德、長榮均未拆無人載具營收與獲利；長榮僅具供應商資格；雷虎本業 {pct(thunder_margin, 1)}。",
        size=9.2,
        color=AMBER,
        wrap=42,
        linespacing=1.14,
        name="p4-conclusion-note",
    )

    box(fig, 0.055, 0.125, 0.540, 0.265, face=SURFACE, edge=GRID)
    add_text(fig, tracked, 0.082, 0.362, "風險量級｜公司區間 vs. 加權指數", size=12.5, color=INK, weight="bold", name="p4-risk-title")
    add_text(fig, tracked, 0.252, 0.326, "六檔", size=8.8, color=FAINT, weight="bold", name="p4-risk-col-company")
    add_text(fig, tracked, 0.440, 0.326, "加權指數", size=8.8, color=FAINT, weight="bold", name="p4-risk-col-index")
    risk_rows = (
        ("近一年報酬", f"{stats['underperform_count']} / {stats['n']} 落後", pct(stats["benchmark_return"], 0, signed=True), 0.286),
        ("年化波動", f"{pct(stats['vol_min'], 1)}–{pct(stats['vol_max'], 1)}", pct(stats["benchmark_vol"], 1), 0.232),
        ("最大回撤", f"{pct(stats['mdd_min'], 0)}–{pct(stats['mdd_max'], 0)}", pct(stats["benchmark_mdd"], 0), 0.178),
    )
    for index, (label, company_value_text, benchmark_value_text, y) in enumerate(risk_rows):
        add_text(fig, tracked, 0.082, y, label, size=9.4, color=MUTED, weight="bold", name=f"p4-risk-label-{index}")
        add_text(fig, tracked, 0.252, y, company_value_text, size=11.5, color=RED if index else INK, weight="bold", name=f"p4-risk-company-{index}")
        add_text(fig, tracked, 0.440, y, benchmark_value_text, size=11.5, color=INK, weight="bold", name=f"p4-risk-index-{index}")

    box(fig, 0.625, 0.125, 0.320, 0.265, face=RED_SOFT, edge="#EAC8CC")
    add_text(fig, tracked, 0.652, 0.362, "大盤不是主要風險來源", size=12.5, color=RED, weight="bold", name="p4-idio-title")
    add_text(fig, tracked, 0.652, 0.310, f"β  {stats['beta_min']:.2f}–{stats['beta_max']:.2f}", size=17.0, color=INK, weight="bold", name="p4-beta")
    add_text(fig, tracked, 0.652, 0.260, f"相關係數  {pct(stats['corr_min'], 0)}–{pct(stats['corr_max'], 0)}", size=14.0, color=INK, weight="bold", name="p4-corr")
    add_text(
        fig,
        tracked,
        0.652,
        0.210,
        "低 beta、低相關但高波動：政策與標案風險不會因分散買進同一題材而消失。",
        size=9.2,
        color=MUTED,
        wrap=25,
        linespacing=1.16,
        name="p4-idio-note",
    )

    add_text(fig, tracked, 0.055, 0.096, "描述性統計｜非投資建議｜歷史不等於未來", size=9.4, color=RED, weight="bold", name="p4-disclaimer")
    footer(fig, tracked, pkg)
    save_panel(fig, tracked, "4_takeaway.png")


def main() -> None:
    # Validate and bind every required input before creating the output directory.
    package = load_package()
    stats = derive(package)
    os.makedirs(OUT_DIR, exist_ok=True)

    render_panel_1(package, stats)
    render_panel_2(package, stats)
    render_panel_3(package, stats)
    render_panel_4(package, stats)


if __name__ == "__main__":
    main()
