#!/usr/bin/env python3
"""Deterministic, data-bound renderer for VolPred lazypack panel sets.

The content agent writes a versioned ``plan.json`` whose numeric values point to
specific JSON evidence fields.  This module validates the complete contract,
verifies evidence hashes, resolves every binding, and renders the panels with
three fixed layout families.  It never invokes an LLM and never writes a
per-article Python program.

Usage::

    uv run python scripts/lazypack_render.py \
      --plan storage/lazypack_jobs/mile_x/plan.json \
      --out-dir storage/lazypack_jobs/mile_x/panels

All panels are first written to a private staging directory and pass the shared
layout guard before any final PNG is replaced.  A bad later panel therefore
cannot leave a mixed partial set in the owned output directory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import string
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import matplotlib

matplotlib.use("Agg")
from matplotlib import font_manager, rcParams  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

rcParams["font.sans-serif"] = ["Heiti TC"]
rcParams["axes.unicode_minus"] = False

ROOT = Path(__file__).resolve().parents[1]
WIDTH = 1600
HEIGHT = 1000
DPI = 150
SCHEMA_VERSION = 1
FONT_FAMILY = "Heiti TC"
PANEL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
INFO_TYPES = {"concept", "method", "results", "takeaway"}
STYLES = {"professional", "editorial", "bento-grid", "scientific"}
FORMAT_KINDS = {"text", "number", "percent", "integer", "date"}

ROOT_KEYS = {"schema_version", "title", "subtitle", "evidence", "panels"}
EVIDENCE_KEYS = {"path", "sha256", "label"}
PANEL_KEYS = {
    "name", "info", "style", "title", "subtitle", "alt", "sources", "blocks",
}
TEXT_BLOCK_KEYS = {"kind", "heading", "body"}
METRIC_BLOCK_KEYS = {"kind", "label", "value", "note"}
BINDING_KEYS = {"source", "path", "format"}
FORMAT_KEYS = {
    "kind", "digits", "scale", "prefix", "suffix", "show_plus", "absolute",
    "thousands",
}


class PlanValidationError(ValueError):
    """The plan is structurally incomplete or internally inconsistent."""


class EvidenceBindingError(KeyError):
    """A declared evidence source or JSON field cannot be resolved."""


class TextFitError(RuntimeError):
    """Complete text cannot fit its assigned rectangle at the minimum size."""


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    @property
    def x1(self) -> int:
        return self.x + self.w

    @property
    def y1(self) -> int:
        return self.y + self.h

    def inset(self, dx: int, dy: int | None = None) -> "Rect":
        dy = dx if dy is None else dy
        return Rect(self.x + dx, self.y + dy, self.w - 2 * dx, self.h - 2 * dy)


@dataclass(frozen=True)
class FittedText:
    text: str
    font: ImageFont.FreeTypeFont
    width: int
    height: int
    spacing: int
    bbox_x0: int
    bbox_y0: int


THEMES = {
    "professional": {
        "ink": "#102A43", "muted": "#5D6B78", "header": "#102A43",
        "accent": "#00A6A6", "soft": "#EEF5F6", "card": "#F8FAFC",
        "border": "#D7E2EA", "value": "#007C83",
    },
    "editorial": {
        "ink": "#252422", "muted": "#66615C", "header": "#252422",
        "accent": "#D97706", "soft": "#FFF7E8", "card": "#FCFBF8",
        "border": "#E7DED0", "value": "#B45309",
    },
    "bento-grid": {
        "ink": "#15233C", "muted": "#5C6880", "header": "#15233C",
        "accent": "#4F46E5", "soft": "#F0F1FF", "card": "#F8F8FF",
        "border": "#DADCF5", "value": "#4338CA",
    },
    "scientific": {
        "ink": "#153028", "muted": "#5E6F69", "header": "#153028",
        "accent": "#168A68", "soft": "#EDF8F4", "card": "#F7FBF9",
        "border": "#CEE3DA", "value": "#0B7254",
    },
}

_FONT_PATH: str | None = None
_FONT_CACHE: dict[int, ImageFont.FreeTypeFont] = {}


def _font_path() -> str:
    global _FONT_PATH
    if _FONT_PATH is None:
        # The project guarantees this exact family on the render host.  Ask the
        # same Matplotlib font registry used by the house style for its file;
        # fallback is deliberately disabled so tofu never passes silently.
        prop = font_manager.FontProperties(family=[FONT_FAMILY])
        _FONT_PATH = font_manager.findfont(prop, fallback_to_default=False)
    return _FONT_PATH


def _font(size: int) -> ImageFont.FreeTypeFont:
    if size not in _FONT_CACHE:
        _FONT_CACHE[size] = ImageFont.truetype(_font_path(), size=size)
    return _FONT_CACHE[size]


def _require(obj: dict[str, Any], key: str, where: str) -> Any:
    if key not in obj:
        raise PlanValidationError(f"missing required field: {where}.{key}")
    return obj[key]


def _reject_unknown(obj: dict[str, Any], allowed: set[str], where: str) -> None:
    unknown = sorted(set(obj) - allowed)
    if unknown:
        raise PlanValidationError(f"unknown field(s) at {where}: {', '.join(unknown)}")


def _require_nonempty_string(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PlanValidationError(f"{where} must be a non-empty string")
    return value


def _validate_format(spec: Any, where: str) -> None:
    if not isinstance(spec, dict):
        raise PlanValidationError(f"{where} must be an object")
    _reject_unknown(spec, FORMAT_KEYS, where)
    kind = _require_nonempty_string(_require(spec, "kind", where), f"{where}.kind")
    if kind not in FORMAT_KINDS:
        raise PlanValidationError(
            f"{where}.kind must be one of {sorted(FORMAT_KINDS)}; got {kind!r}"
        )
    if "digits" in spec:
        digits = spec["digits"]
        if not isinstance(digits, int) or isinstance(digits, bool) or not 0 <= digits <= 3:
            raise PlanValidationError(f"{where}.digits must be an integer from 0 to 3")
    if "scale" in spec and (
        not isinstance(spec["scale"], (int, float)) or isinstance(spec["scale"], bool)
    ):
        raise PlanValidationError(f"{where}.scale must be numeric")
    for key in ("prefix", "suffix"):
        if key in spec and not isinstance(spec[key], str):
            raise PlanValidationError(f"{where}.{key} must be a string")
    for key in ("show_plus", "absolute", "thousands"):
        if key in spec and not isinstance(spec[key], bool):
            raise PlanValidationError(f"{where}.{key} must be boolean")


def _validate_binding(spec: Any, where: str, evidence_aliases: set[str]) -> None:
    if not isinstance(spec, dict):
        raise PlanValidationError(f"{where} must be an object")
    _reject_unknown(spec, BINDING_KEYS, where)
    source = _require_nonempty_string(_require(spec, "source", where), f"{where}.source")
    if source not in evidence_aliases:
        raise PlanValidationError(f"{where}.source references unknown evidence {source!r}")
    _require_nonempty_string(_require(spec, "path", where), f"{where}.path")
    _validate_format(_require(spec, "format", where), f"{where}.format")


def _validate_content(value: Any, where: str, evidence_aliases: set[str]) -> None:
    if isinstance(value, str):
        if not value.strip():
            raise PlanValidationError(f"{where} must not be empty")
        return
    if not isinstance(value, dict):
        raise PlanValidationError(f"{where} must be a string or template object")
    _reject_unknown(value, {"template", "bindings"}, where)
    template = _require_nonempty_string(
        _require(value, "template", where), f"{where}.template"
    )
    bindings = _require(value, "bindings", where)
    if not isinstance(bindings, dict) or not bindings:
        raise PlanValidationError(f"{where}.bindings must be a non-empty object")
    for name, binding in bindings.items():
        _require_nonempty_string(name, f"{where}.bindings key")
        _validate_binding(binding, f"{where}.bindings.{name}", evidence_aliases)
    try:
        fields = {
            field_name
            for _, field_name, _, _ in string.Formatter().parse(template)
            if field_name is not None
        }
    except ValueError as exc:
        raise PlanValidationError(f"invalid template at {where}: {exc}") from exc
    if fields != set(bindings):
        missing = sorted(fields - set(bindings))
        unused = sorted(set(bindings) - fields)
        raise PlanValidationError(
            f"{where} template/binding mismatch; missing={missing}, unused={unused}"
        )


def validate_plan(document: Any, *, plan_path: Path | None = None) -> dict[str, Any]:
    """Validate the strict v1 plan contract and return the same document."""
    label = str(plan_path) if plan_path else "plan"
    if not isinstance(document, dict):
        raise PlanValidationError(f"{label} root must be an object, not a legacy panel list")
    _reject_unknown(document, ROOT_KEYS, "plan")
    version = _require(document, "schema_version", "plan")
    if version != SCHEMA_VERSION:
        raise PlanValidationError(
            f"plan.schema_version must equal {SCHEMA_VERSION}; got {version!r}"
        )
    _require_nonempty_string(_require(document, "title", "plan"), "plan.title")
    if "subtitle" in document:
        _validate_content(document["subtitle"], "plan.subtitle", set(document.get("evidence", {})))

    evidence = _require(document, "evidence", "plan")
    if not isinstance(evidence, dict) or not evidence:
        raise PlanValidationError("plan.evidence must be a non-empty object")
    for alias, spec in evidence.items():
        _require_nonempty_string(alias, "plan.evidence key")
        where = f"plan.evidence.{alias}"
        if not isinstance(spec, dict):
            raise PlanValidationError(f"{where} must be an object")
        _reject_unknown(spec, EVIDENCE_KEYS, where)
        _require_nonempty_string(_require(spec, "path", where), f"{where}.path")
        digest = _require_nonempty_string(_require(spec, "sha256", where), f"{where}.sha256")
        if not SHA256_RE.fullmatch(digest):
            raise PlanValidationError(f"{where}.sha256 must be 64 lowercase hex characters")
        _require_nonempty_string(_require(spec, "label", where), f"{where}.label")

    panels = _require(document, "panels", "plan")
    if not isinstance(panels, list) or not 2 <= len(panels) <= 4:
        raise PlanValidationError("plan.panels must be a list containing 2 to 4 panels")
    names: set[str] = set()
    aliases = set(evidence)
    for index, panel in enumerate(panels):
        where = f"plan.panels[{index}]"
        if not isinstance(panel, dict):
            raise PlanValidationError(f"{where} must be an object")
        _reject_unknown(panel, PANEL_KEYS, where)
        name = _require_nonempty_string(_require(panel, "name", where), f"{where}.name")
        if not PANEL_NAME_RE.fullmatch(name):
            raise PlanValidationError(
                f"{where}.name must match {PANEL_NAME_RE.pattern!r}; got {name!r}"
            )
        if name in names:
            raise PlanValidationError(f"duplicate panel name: {name}")
        names.add(name)
        info = _require_nonempty_string(_require(panel, "info", where), f"{where}.info")
        if info not in INFO_TYPES:
            raise PlanValidationError(f"{where}.info must be one of {sorted(INFO_TYPES)}")
        style = _require_nonempty_string(_require(panel, "style", where), f"{where}.style")
        if style not in STYLES:
            raise PlanValidationError(f"{where}.style must be one of {sorted(STYLES)}")
        _validate_content(_require(panel, "title", where), f"{where}.title", aliases)
        if "subtitle" in panel:
            _validate_content(panel["subtitle"], f"{where}.subtitle", aliases)
        _require_nonempty_string(_require(panel, "alt", where), f"{where}.alt")
        sources = _require(panel, "sources", where)
        if not isinstance(sources, list) or not sources:
            raise PlanValidationError(f"{where}.sources must be a non-empty list")
        if any(not isinstance(x, str) or x not in aliases for x in sources):
            raise PlanValidationError(
                f"{where}.sources must contain only declared evidence aliases"
            )
        if len(sources) != len(set(sources)):
            raise PlanValidationError(f"{where}.sources must not contain duplicates")
        blocks = _require(panel, "blocks", where)
        if not isinstance(blocks, list) or not blocks:
            raise PlanValidationError(f"{where}.blocks must be a non-empty list")
        if len(blocks) > 10:
            raise PlanValidationError(f"{where}.blocks supports at most 10 items")
        for block_index, block in enumerate(blocks):
            bwhere = f"{where}.blocks[{block_index}]"
            if not isinstance(block, dict):
                raise PlanValidationError(f"{bwhere} must be an object")
            kind = _require_nonempty_string(_require(block, "kind", bwhere), f"{bwhere}.kind")
            if kind == "text":
                _reject_unknown(block, TEXT_BLOCK_KEYS, bwhere)
                _validate_content(_require(block, "heading", bwhere), f"{bwhere}.heading", aliases)
                body = _require(block, "body", bwhere)
                if not isinstance(body, list) or not body:
                    raise PlanValidationError(f"{bwhere}.body must be a non-empty list")
                for body_index, item in enumerate(body):
                    _validate_content(item, f"{bwhere}.body[{body_index}]", aliases)
            elif kind == "metric":
                _reject_unknown(block, METRIC_BLOCK_KEYS, bwhere)
                _validate_content(_require(block, "label", bwhere), f"{bwhere}.label", aliases)
                _validate_binding(_require(block, "value", bwhere), f"{bwhere}.value", aliases)
                if "note" in block:
                    _validate_content(block["note"], f"{bwhere}.note", aliases)
            else:
                raise PlanValidationError(f"{bwhere}.kind must be 'text' or 'metric'")
    return document


def _resolve_input_path(path_like: str) -> Path:
    path = Path(path_like).expanduser()
    return path if path.is_absolute() else ROOT / path


def _load_evidence(document: dict[str, Any]) -> dict[str, Any]:
    loaded: dict[str, Any] = {}
    for alias, spec in document["evidence"].items():
        path = _resolve_input_path(spec["path"])
        if path.suffix.lower() != ".json":
            raise PlanValidationError(f"plan.evidence.{alias}.path must point to a JSON file")
        if not path.is_file():
            raise FileNotFoundError(f"evidence file not found for {alias!r}: {path}")
        raw = path.read_bytes()
        actual = hashlib.sha256(raw).hexdigest()
        expected = spec["sha256"]
        if actual != expected:
            raise PlanValidationError(
                f"evidence hash mismatch for {alias!r}: expected {expected}, got {actual} ({path})"
            )
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise PlanValidationError(f"invalid evidence JSON for {alias!r}: {path}: {exc}") from exc
        if not isinstance(value, dict):
            raise PlanValidationError(f"evidence root for {alias!r} must be an object: {path}")
        loaded[alias] = value
    return loaded


def load_plan(plan_path: str | Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read, fully validate, hash-check, and load a plan plus its evidence."""
    path = Path(plan_path).expanduser().resolve()
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PlanValidationError(f"invalid plan JSON: {path}: {exc}") from exc
    validate_plan(document, plan_path=path)
    return document, _load_evidence(document)


def panel_specs(document: dict[str, Any]) -> list[tuple[str, str]]:
    """Return ordered ``(PNG stem, alt text)`` pairs from a validated plan."""
    return [(panel["name"], panel["alt"]) for panel in document["panels"]]


def _json_path(value: Any, dotted_path: str, where: str) -> Any:
    current = value
    for token in dotted_path.split("."):
        if token == "":
            raise EvidenceBindingError(f"empty JSON path component at {where}: {dotted_path!r}")
        if isinstance(current, dict):
            if token not in current:
                raise EvidenceBindingError(
                    f"missing evidence field at {where}: {dotted_path!r} (stopped at {token!r})"
                )
            current = current[token]
        elif isinstance(current, list) and token.isdigit():
            index = int(token)
            if index >= len(current):
                raise EvidenceBindingError(
                    f"evidence list index out of range at {where}: {dotted_path!r}"
                )
            current = current[index]
        else:
            raise EvidenceBindingError(
                f"cannot descend through {type(current).__name__} at {where}: {dotted_path!r}"
            )
    return current


def _format_value(value: Any, spec: dict[str, Any], where: str) -> str:
    kind = spec["kind"]
    prefix = spec.get("prefix", "")
    suffix = spec.get("suffix", "")
    if kind in {"text", "date"}:
        if not isinstance(value, str):
            raise EvidenceBindingError(
                f"{where} format {kind!r} requires a string; got {type(value).__name__}"
            )
        return f"{prefix}{value}{suffix}"
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise EvidenceBindingError(
            f"{where} format {kind!r} requires a finite number; got {value!r}"
        )
    number = float(value)
    if spec.get("absolute", False):
        number = abs(number)
    if kind == "percent":
        default_scale = 100.0
        default_suffix = "%"
    else:
        default_scale = 1.0
        default_suffix = ""
    number *= float(spec.get("scale", default_scale))
    digits = int(spec.get("digits", 0 if kind == "integer" else 1))
    show_plus = bool(spec.get("show_plus", False))
    thousands = bool(spec.get("thousands", kind == "integer"))
    sign = "+" if show_plus else ""
    comma = "," if thousands else ""
    rendered = format(number, f"{sign}{comma}.{digits}f")
    return f"{prefix}{rendered}{suffix or default_suffix}"


def _resolve_binding(
    binding: dict[str, Any], evidence: dict[str, Any], where: str,
) -> str:
    source = binding["source"]
    raw = _json_path(evidence[source], binding["path"], where)
    return _format_value(raw, binding["format"], where)


def _resolve_content(value: Any, evidence: dict[str, Any], where: str) -> str:
    if isinstance(value, str):
        return value
    resolved = {
        name: _resolve_binding(binding, evidence, f"{where}.bindings.{name}")
        for name, binding in value["bindings"].items()
    }
    return value["template"].format_map(resolved)


def _resolve_panels(document: dict[str, Any], evidence: dict[str, Any]) -> list[dict[str, Any]]:
    resolved: list[dict[str, Any]] = []
    for pi, panel in enumerate(document["panels"]):
        where = f"plan.panels[{pi}]"
        item = dict(panel)
        item["title"] = _resolve_content(panel["title"], evidence, f"{where}.title")
        if "subtitle" in panel:
            item["subtitle"] = _resolve_content(panel["subtitle"], evidence, f"{where}.subtitle")
        blocks: list[dict[str, Any]] = []
        for bi, block in enumerate(panel["blocks"]):
            bwhere = f"{where}.blocks[{bi}]"
            if block["kind"] == "text":
                blocks.append({
                    "kind": "text",
                    "heading": _resolve_content(block["heading"], evidence, f"{bwhere}.heading"),
                    "body": [
                        _resolve_content(v, evidence, f"{bwhere}.body[{i}]")
                        for i, v in enumerate(block["body"])
                    ],
                })
            else:
                metric = {
                    "kind": "metric",
                    "label": _resolve_content(block["label"], evidence, f"{bwhere}.label"),
                    "value": _resolve_binding(block["value"], evidence, f"{bwhere}.value"),
                }
                if "note" in block:
                    metric["note"] = _resolve_content(block["note"], evidence, f"{bwhere}.note")
                blocks.append(metric)
        item["blocks"] = blocks
        item["source_labels"] = [document["evidence"][x]["label"] for x in panel["sources"]]
        resolved.append(item)
    return resolved


def _tokens(paragraph: str) -> list[str]:
    """CJK-aware tokens: preserve ASCII words, allow wrapping between CJK glyphs."""
    return re.findall(r"\s+|[A-Za-z0-9][A-Za-z0-9_./:+%,'’()\-]*|.", paragraph)


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> int:
    if not text:
        return 0
    box = draw.textbbox((0, 0), text, font=font, anchor="lt")
    return int(math.ceil(box[2] - box[0]))


def _split_oversize_token(
    draw: ImageDraw.ImageDraw, token: str, font: ImageFont.FreeTypeFont, max_width: int,
) -> list[str]:
    chunks: list[str] = []
    current = ""
    for char in token:
        trial = current + char
        if current and _text_width(draw, trial, font) > max_width:
            chunks.append(current)
            current = char
        else:
            current = trial
    if current:
        chunks.append(current)
    return chunks


def _wrap_text(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int,
) -> str:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        if paragraph == "":
            lines.append("")
            continue
        current = ""
        for token in _tokens(paragraph):
            if token.isspace():
                if current and not current.endswith(" "):
                    current += " "
                continue
            pieces = (
                _split_oversize_token(draw, token, font, max_width)
                if _text_width(draw, token, font) > max_width
                else [token]
            )
            for piece in pieces:
                trial = current + piece
                if current.strip() and _text_width(draw, trial.rstrip(), font) > max_width:
                    lines.append(current.rstrip())
                    current = piece
                else:
                    current = trial
        lines.append(current.rstrip())
    return "\n".join(lines)


def _fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    rect: Rect,
    preferred: int,
    minimum: int,
    *,
    align: str = "left",
) -> FittedText:
    if rect.w <= 0 or rect.h <= 0:
        raise TextFitError(f"invalid text rectangle: {rect}")
    for size in range(preferred, minimum - 1, -1):
        font = _font(size)
        wrapped = _wrap_text(draw, text, font, rect.w)
        spacing = max(4, int(round(size * 0.30)))
        # Pillow deliberately rejects top/bottom anchors for multiline text.
        # Measure with the ascender anchor, retain its bearing, and translate
        # the actual draw call so the *ink box* lands inside ``rect``.
        box = draw.multiline_textbbox(
            (0, 0), wrapped, font=font, spacing=spacing, align=align, anchor="la"
        )
        width = int(math.ceil(box[2] - box[0]))
        height = int(math.ceil(box[3] - box[1]))
        if width <= rect.w and height <= rect.h:
            return FittedText(
                wrapped, font, width, height, spacing,
                int(math.floor(box[0])), int(math.floor(box[1])),
            )
    raise TextFitError(
        f"complete text cannot fit {rect.w}x{rect.h}px at {minimum}pt: {text!r}"
    )


def _draw_fitted(
    draw: ImageDraw.ImageDraw,
    text: str,
    rect: Rect,
    preferred: int,
    minimum: int,
    *,
    fill: str,
    align: str = "left",
    valign: str = "top",
) -> FittedText:
    fitted = _fit_text(draw, text, rect, preferred, minimum, align=align)
    if align == "center":
        left = rect.x + max(0, (rect.w - fitted.width) // 2)
    elif align == "right":
        left = rect.x1 - fitted.width
    else:
        left = rect.x
    if valign == "middle":
        top = rect.y + max(0, (rect.h - fitted.height) // 2)
    elif valign == "bottom":
        top = rect.y1 - fitted.height
    else:
        top = rect.y
    x = left - fitted.bbox_x0
    y = top - fitted.bbox_y0
    draw.text(
        (x, y), fitted.text, font=fitted.font, fill=fill, spacing=fitted.spacing,
        align=align, anchor="la",
    )
    return fitted


def _row_rects(area: Rect, n: int, columns: int, weights: list[float] | None = None) -> list[Rect]:
    columns = max(1, min(columns, n))
    rows = math.ceil(n / columns)
    gap = 20
    row_weights: list[float] = []
    weights = weights or [1.0] * n
    for row in range(rows):
        group = weights[row * columns:(row + 1) * columns]
        row_weights.append(max(group) if group else 1.0)
    height_budget = area.h - gap * (rows - 1)
    total_weight = sum(row_weights)
    heights = [int(round(height_budget * w / total_weight)) for w in row_weights]
    heights[-1] += height_budget - sum(heights)
    rects: list[Rect] = []
    y = area.y
    for row in range(rows):
        count = min(columns, n - row * columns)
        width_budget = area.w - gap * (count - 1)
        cell_w = width_budget // count
        x = area.x
        for _ in range(count):
            rects.append(Rect(x, y, cell_w, heights[row]))
            x += cell_w + gap
        y += heights[row] + gap
    return rects


def _block_weight(block: dict[str, Any]) -> float:
    if block["kind"] == "metric":
        return 1.0
    chars = len(block["heading"]) + sum(len(x) for x in block["body"])
    return max(1.0, min(2.8, 0.8 + chars / 85.0))


def _draw_text_card(
    draw: ImageDraw.ImageDraw, rect: Rect, block: dict[str, Any], theme: dict[str, str],
) -> None:
    draw.rounded_rectangle(
        (rect.x, rect.y, rect.x1, rect.y1), radius=24,
        fill=theme["card"], outline=theme["border"], width=2,
    )
    inner = rect.inset(28, 24)
    heading_area = Rect(inner.x, inner.y, inner.w, min(58, max(42, inner.h // 4)))
    heading = _draw_fitted(
        draw, block["heading"], heading_area, 31, 22, fill=theme["ink"]
    )
    body_y = inner.y + heading.height + 18
    body_area = Rect(inner.x, body_y, inner.w, inner.y1 - body_y)
    bullets = "\n".join(f"• {line}" for line in block["body"])
    _draw_fitted(draw, bullets, body_area, 27, 17, fill=theme["muted"])


def _draw_metric_card(
    draw: ImageDraw.ImageDraw, rect: Rect, block: dict[str, Any], theme: dict[str, str],
) -> None:
    draw.rounded_rectangle(
        (rect.x, rect.y, rect.x1, rect.y1), radius=24,
        fill=theme["soft"], outline=theme["border"], width=2,
    )
    draw.rectangle((rect.x + 24, rect.y + 20, rect.x + 76, rect.y + 27), fill=theme["accent"])
    inner = rect.inset(24, 18)
    label_area = Rect(inner.x, inner.y + 17, inner.w, max(30, int(inner.h * 0.22)))
    _draw_fitted(draw, block["label"], label_area, 24, 17, fill=theme["muted"])
    value_y = label_area.y1 + 4
    note_height = max(0, int(inner.h * 0.22)) if block.get("note") else 0
    value_area = Rect(
        inner.x, value_y, inner.w,
        max(38, inner.y1 - value_y - note_height - (8 if note_height else 0)),
    )
    _draw_fitted(
        draw, block["value"], value_area, 52, 27, fill=theme["value"],
        valign="middle",
    )
    if block.get("note"):
        note_area = Rect(inner.x, inner.y1 - note_height, inner.w, note_height)
        _draw_fitted(draw, block["note"], note_area, 20, 15, fill=theme["muted"])


def _draw_header(
    draw: ImageDraw.ImageDraw,
    document: dict[str, Any],
    panel: dict[str, Any],
    evidence: dict[str, Any],
    theme: dict[str, str],
) -> None:
    draw.rectangle((0, 0, WIDTH, 205), fill=theme["header"])
    draw.rectangle((0, 0, 18, 205), fill=theme["accent"])
    _draw_fitted(
        draw, document["title"], Rect(72, 20, 1450, 28), 21, 17,
        fill="#C9D7E3",
    )
    _draw_fitted(
        draw, panel["title"], Rect(72, 57, 1450, 92), 50, 28,
        fill="#FFFFFF",
    )
    subtitle_spec = panel.get("subtitle", document.get("subtitle"))
    if subtitle_spec:
        subtitle = (
            panel["subtitle"] if "subtitle" in panel
            else _resolve_content(subtitle_spec, evidence, "plan.subtitle")
        )
        _draw_fitted(
            draw, subtitle, Rect(72, 163, 1450, 27), 21, 15,
            fill="#DDE7EE",
        )


def _draw_footer(
    draw: ImageDraw.ImageDraw, panel: dict[str, Any], theme: dict[str, str],
) -> None:
    draw.rectangle((72, 928, 1528, 930), fill=theme["border"])
    source = "資料來源：" + "、".join(panel["source_labels"])
    _draw_fitted(
        draw, source, Rect(72, 946, 1456, 31), 18, 13, fill=theme["muted"]
    )


def _render_concept_or_method(
    draw: ImageDraw.ImageDraw,
    panel: dict[str, Any],
    theme: dict[str, str],
) -> None:
    blocks = panel["blocks"]
    area = Rect(72, 232, 1456, 665)
    if panel["info"] == "method":
        columns = 1 if len(blocks) <= 4 else 2
    else:
        columns = 1 if len(blocks) == 1 else (2 if len(blocks) in {2, 4} else 3)
    weights = [_block_weight(block) for block in blocks]
    for block, rect in zip(blocks, _row_rects(area, len(blocks), columns, weights)):
        if block["kind"] == "metric":
            _draw_metric_card(draw, rect, block, theme)
        else:
            _draw_text_card(draw, rect, block, theme)


def _render_results(
    draw: ImageDraw.ImageDraw,
    panel: dict[str, Any],
    theme: dict[str, str],
) -> None:
    metrics = [b for b in panel["blocks"] if b["kind"] == "metric"]
    texts = [b for b in panel["blocks"] if b["kind"] == "text"]
    full = Rect(72, 232, 1456, 665)
    if not metrics:
        columns = 1 if len(texts) == 1 else min(3, len(texts))
        for block, rect in zip(
            texts, _row_rects(full, len(texts), columns, [_block_weight(x) for x in texts])
        ):
            _draw_text_card(draw, rect, block, theme)
        return
    metric_rows = 1 if len(metrics) <= 4 else 2
    metric_height = 240 if metric_rows == 1 else 342
    if not texts:
        metric_height = full.h
    metric_area = Rect(full.x, full.y, full.w, metric_height)
    metric_columns = min(4, len(metrics)) if metric_rows == 1 else math.ceil(len(metrics) / 2)
    for block, rect in zip(metrics, _row_rects(metric_area, len(metrics), metric_columns)):
        _draw_metric_card(draw, rect, block, theme)
    if texts:
        text_y = metric_area.y1 + 20
        text_area = Rect(full.x, text_y, full.w, full.y1 - text_y)
        columns = min(3, len(texts))
        for block, rect in zip(
            texts, _row_rects(text_area, len(texts), columns, [_block_weight(x) for x in texts])
        ):
            _draw_text_card(draw, rect, block, theme)


def _render_panel(
    document: dict[str, Any], panel: dict[str, Any], evidence: dict[str, Any],
) -> Image.Image:
    theme = THEMES[panel["style"]]
    image = Image.new("RGB", (WIDTH, HEIGHT), "#FFFFFF")
    draw = ImageDraw.Draw(image)
    _draw_header(draw, document, panel, evidence, theme)
    if panel["info"] in {"concept", "method"}:
        _render_concept_or_method(draw, panel, theme)
    else:
        _render_results(draw, panel, theme)
    _draw_footer(draw, panel, theme)
    return image


def render_plan(plan_path: str | Path, out_dir: str | Path) -> list[Path]:
    """Render a complete plan atomically; return final PNG paths in panel order."""
    document, evidence = load_plan(plan_path)
    panels = _resolve_panels(document, evidence)  # resolve every field before writes
    destination = Path(out_dir).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)

    # Install before constructing images so Pillow draw calls are observable.
    from lazypack_layout_guard import install as install_layout_guard

    install_layout_guard(collect=False, write_clean=True)
    stage = Path(tempfile.mkdtemp(prefix=".lazypack-render-", dir=destination))
    staged: list[Path] = []
    finals = [destination / f"{panel['name']}.png" for panel in panels]
    try:
        for panel in panels:
            image = _render_panel(document, panel, evidence)
            target = stage / f"{panel['name']}.png"
            image.save(target, format="PNG", dpi=(DPI, DPI), optimize=False)
            image.close()
            with Image.open(target) as check:
                if check.size != (WIDTH, HEIGHT) or check.format != "PNG":
                    raise RuntimeError(f"invalid rendered panel: {target}")
            staged.append(target)
        for source, target in zip(staged, finals):
            os.replace(source, target)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    return finals


def _manifest(paths: Iterable[Path]) -> dict[str, Any]:
    return {
        "renderer": "scripts/lazypack_render.py",
        "llm_calls": 0,
        "panels": [
            {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in paths
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, help="strict v1 lazypack plan JSON")
    parser.add_argument("--out-dir", required=True, help="directory for one PNG per panel")
    parser.add_argument(
        "--validate-only", action="store_true",
        help="validate schema, evidence hashes, and every binding without writing PNGs",
    )
    args = parser.parse_args(argv)
    if args.validate_only:
        document, evidence = load_plan(args.plan)
        _resolve_panels(document, evidence)
        print(json.dumps({"valid": True, "panels": len(document["panels"])}, ensure_ascii=False))
        return 0
    paths = render_plan(args.plan, args.out_dir)
    print(json.dumps(_manifest(paths), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
