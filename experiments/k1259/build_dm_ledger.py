#!/usr/bin/env python3
"""
K1259 Phase 1: DM pair ledger builder.

Scans experiments/k400 ~ experiments/k1258 *_results.json / results.json,
extracts Diebold-Mariano test statistics into a flat row schema, writes:
  - experiments/k1259/dm_ledger.json
  - experiments/k1259/dm_ledger_summary.md

See experiments/k1259/README.md for scope and limitations.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from statistics import mean, median, stdev
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
EXP_DIR = ROOT / "experiments"
OUT_DIR = ROOT / "experiments" / "k1259"

# Canonical output schema
ROW_KEYS = [
    "k_id",
    "model_a",
    "model_b",
    "loss_fn",
    "asset",
    "sample_n",
    "period",
    "dm_stat",
    "p_value",
    "harvey_adjusted",
    "source_file",
    "source_field_path",
]


def parse_k_id(path: Path) -> str:
    """From experiments/k530/... extract K530."""
    for part in path.parts:
        m = re.match(r"^k(\d+)$", part)
        if m:
            return f"K{m.group(1)}"
    return "K?"


def parse_pair(label: str) -> tuple[str, str]:
    """Parse "A vs B" / "A_vs_B" / "A-vs-B" strings into (A, B)."""
    if not isinstance(label, str):
        return (str(label), "")
    # prefer _vs_ first since names can contain spaces like "GJR N vs GJR t"
    for sep in [" vs. ", " vs ", "_vs_", " VS ", "-vs-"]:
        if sep in label:
            a, b = label.split(sep, 1)
            return (a.strip(), b.strip())
    return (label.strip(), "")


# ------ helpers to fish common metadata out of root JSON ------
def norm_asset(asset: Any) -> str:
    if asset is None:
        return ""
    s = str(asset).strip()
    return s


def detect_period(root_data: dict) -> str:
    """Best-effort human-readable period string."""
    for key in ("period", "data_period", "oos_period", "sample_period"):
        v = root_data.get(key)
        if isinstance(v, str) and v:
            return v
        if isinstance(v, dict):
            start = v.get("start") or v.get("from") or v.get("begin")
            end = v.get("end") or v.get("to")
            if start and end:
                return f"{start} to {end}"
    # fallback from oos_start + experiment date
    oos = root_data.get("oos_start") or root_data.get("oos_period_start")
    end = root_data.get("date") or root_data.get("timestamp")
    if oos:
        return f"OOS_{oos}" + (f"_to_{end[:10]}" if isinstance(end, str) and end else "")
    return ""


def detect_sample_n(root_data: dict) -> int | None:
    for key in ("n_oos", "n_total", "sample_size", "n", "n_common", "oos_n"):
        v = root_data.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return int(v)
    return None


def detect_loss(payload: dict | None, ctx: str = "") -> str | None:
    """Try hard to identify the loss function used."""
    if payload and isinstance(payload, dict):
        for key in ("loss", "loss_fn", "loss_function", "criterion", "metric"):
            v = payload.get(key)
            if isinstance(v, str) and v:
                return v
    ctx_l = (ctx or "").lower()
    if "qlike" in ctx_l:
        return "QLIKE"
    if re.search(r"fz1|fz_1%|fz1%|fz_1|fz1percent", ctx_l):
        return "FZ1%"
    if re.search(r"fz2_5|fz_2_5|fz25|fz2\.5", ctx_l):
        return "FZ2.5%"
    if "fz" in ctx_l:
        return "FZ"
    if "mse" in ctx_l:
        return "MSE"
    if "r2" in ctx_l:
        return "MSE"  # r2-style loss defaults to MSE
    if re.search(r"\bpk\b|parkinson", ctx_l):
        return "Parkinson"
    if "es_" in ctx_l or "expected shortfall" in ctx_l:
        return "ES"
    return None


def get_numeric(d: dict | None, *keys: str) -> float | None:
    if not isinstance(d, dict):
        return None
    for k in keys:
        if k in d:
            v = d[k]
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return float(v)
            if isinstance(v, str):
                try:
                    return float(v)
                except Exception:
                    pass
    return None


def get_dm_stat(d: dict) -> float | None:
    return get_numeric(
        d,
        "dm_stat",
        "dm_t",
        "DM",
        "dm",
        "t_stat",
        "t",
        "dm_stat_oos",
        "harvey_t",
        "DM_HLN_t",
        "stat",
    )


def get_p_value(d: dict) -> tuple[float | None, bool]:
    """Return (p, estimated). estimated True if inferred."""
    v = get_numeric(
        d,
        "p_value",
        "p_val",
        "p",
        "pvalue",
        "dm_p",
        "DM_HLN_p",
        "harvey_p",
        "p_val_oos",
    )
    if v is not None:
        return (v, False)
    return (None, False)


def get_harvey_flag(d: dict) -> Any:
    for k in ("harvey_adjusted", "harvey_pass", "harvey_significant", "significant_harvey"):
        if k in d:
            v = d[k]
            if isinstance(v, bool):
                return v
            if isinstance(v, str):
                sl = v.strip().lower()
                if sl in ("true", "yes", "1"):
                    return True
                if sl in ("false", "no", "0"):
                    return False
            return v
    # Harvey-specific key present → True (Harvey small-sample adjustment performed)
    if "DM_HLN_t" in d or "harvey_t" in d or "harvey_p" in d:
        return True
    return None


# ------ asset inference from context path ------
KNOWN_ASSETS = {
    "SPY", "QQQ", "DIA", "IWM", "GLD", "SLV", "TLT", "IEF",
    "0050.TW", "0050", "TAIEX", "TX", "TXF", "MTX",
    "EWT", "EWH", "EWJ", "EWZ",
    "BTC", "ETH", "USO", "XLE", "XLF", "XLK",
    "VIX", "VXN", "^GSPC", "^VIX",
}


def find_asset_in_context(context: Iterable[str]) -> str:
    """Look through ancestor keys for a recognized asset."""
    for part in context:
        if not isinstance(part, str):
            continue
        # Exact-key matches
        if part in KNOWN_ASSETS:
            return part
        # Common "assets.SPY" / "results.GLD.periods"
        m = re.match(r"^[a-zA-Z_]*(SPY|QQQ|DIA|IWM|GLD|SLV|TLT|IEF|IVV|VXX|VOO|EWT|EWH|EWJ|EWZ|XLE|XLF|XLK|USO|BTC|ETH)$", part)
        if m:
            return m.group(1)
        if re.match(r"^0050(\.TW)?$", part):
            return "0050.TW"
        if part.upper() in {"TAIEX", "TW", "TWII"}:
            return "TAIEX"
    return ""


# ------ core extraction ------
# Path segments containing these tokens are NOT Diebold-Mariano tests even
# though they may have {t, p} or {stat, p_value} fields that get_dm_stat
# could match via generic "t" / "stat" / "t_stat" keys. Skipping them prevents
# false-positive ledger rows.
#
# Audit history:
#   2026-04-28 (subagent fallback) — initial 5 tokens caught 11 rows from
#     K649 / K706 / K744 / K789 / K1059. See generic_key_audit.md.
#   2026-04-29 (Codex primary-path review v2) — caught 12 residual rows
#     extracted via t_stat field (priority 5 in get_dm_stat) from K528 /
#     K594 / K658 / K975 / K990 / K1006 under containers
#     `statistical_tests*` / `stat_test_*` / `welch_test*` / `*_vs_zero`.
#     Tokens extended below. See codex_review_v2.md.
NON_DM_PATH_TOKENS = (
    "ttest", "mcnemar", "wilcoxon", "kstest", "kruskal",
    "welch", "stat_test", "statistical_test", "vs_zero",
)


def _path_is_non_dm(ctx_path: list[str]) -> bool:
    return any(
        any(tok in seg.lower() for tok in NON_DM_PATH_TOKENS)
        for seg in ctx_path
    )


def iter_pair_entries(node: Any, context: list[str]):
    """Yield (pair_dict, context_label_for_pair, ctx_path) for everything that looks like a DM pair comparison.

    A "pair entry" is a dict with t_stat/dm_stat-like key + p-value-like key OR
    a dict whose values are such dicts (mapping).
    """
    if isinstance(node, dict):
        # Case A: dict is itself a DM pair entry (has dm_stat + p_value and NOT just container)
        if get_dm_stat(node) is not None and not _path_is_non_dm(context):
            p, _ = get_p_value(node)
            # include pair entry; model names from context
            yield (node, context[-1] if context else "", context)
        else:
            for k, v in node.items():
                new_ctx = context + [str(k)]
                # Case B: a dict mapping "A_vs_B" -> pair dict
                if isinstance(v, dict) and get_dm_stat(v) is not None \
                        and not _path_is_non_dm(new_ctx):
                    yield (v, str(k), new_ctx)
                elif isinstance(v, list):
                    for i, item in enumerate(v):
                        yield from iter_pair_entries(item, new_ctx + [f"[{i}]"])
                elif isinstance(v, dict):
                    yield from iter_pair_entries(v, new_ctx)
    elif isinstance(node, list):
        for i, item in enumerate(node):
            yield from iter_pair_entries(item, context + [f"[{i}]"])


def resolve_models(pair_dict: dict, label: str) -> tuple[str, str]:
    """Prefer explicit model_1/model_2 or model_a/model_b fields, else parse label."""
    for a_key, b_key in [
        ("model_1", "model_2"),
        ("model_a", "model_b"),
        ("modelA", "modelB"),
        ("baseline", "candidate"),
        ("m1", "m2"),
        ("model1", "model2"),
    ]:
        if a_key in pair_dict and b_key in pair_dict:
            return (str(pair_dict[a_key]), str(pair_dict[b_key]))
    if "comparison" in pair_dict and isinstance(pair_dict["comparison"], str):
        return parse_pair(pair_dict["comparison"])
    if "pair" in pair_dict and isinstance(pair_dict["pair"], str):
        return parse_pair(pair_dict["pair"])
    return parse_pair(label)


def resolve_asset(pair_dict: dict, ctx_path: list[str], root_data: dict) -> str:
    # explicit asset field
    for key in ("asset", "symbol", "ticker", "ticker_symbol"):
        if key in pair_dict and isinstance(pair_dict[key], str):
            return pair_dict[key]
    # look in ancestor keys
    a = find_asset_in_context(ctx_path)
    if a:
        return a
    # look in root
    for key in ("asset", "ticker", "symbol"):
        if key in root_data and isinstance(root_data[key], str):
            return root_data[key]
    # check root "assets" is a list of one
    assets = root_data.get("assets")
    if isinstance(assets, list) and len(assets) == 1 and isinstance(assets[0], str):
        return assets[0]
    if isinstance(assets, dict) and len(assets) == 1:
        (k,) = assets.keys()
        return k
    return ""


def resolve_period(pair_dict: dict, ctx_path: list[str], root_data: dict) -> str:
    # explicit period or subperiod label in pair_dict
    for key in ("period", "window", "subperiod", "sub_period", "regime"):
        if key in pair_dict and isinstance(pair_dict[key], str):
            return pair_dict[key]
    # subperiod labels in ancestor context
    subperiod_hits = []
    for part in ctx_path:
        if not isinstance(part, str):
            continue
        if re.search(r"(bear|bull|gfc|covid|euro|dotcom|crisis|early|mid|middle|late|recovery|bucket|extreme|normal|low|high|period|quantile|regime|tranquil)", part, re.IGNORECASE):
            subperiod_hits.append(part)
    if subperiod_hits:
        # exclude generic containers
        filtered = [s for s in subperiod_hits if s.lower() not in {"periods", "crisis_subperiods", "per_window", "vix_buckets", "subperiod_robustness"}]
        if filtered:
            return ":".join(filtered[-2:])
    return detect_period(root_data)


def resolve_loss(pair_dict: dict, ctx_path: list[str]) -> str | None:
    direct = detect_loss(pair_dict)
    if direct:
        return direct
    joined_ctx = ".".join(str(x) for x in ctx_path)
    inferred = detect_loss(None, joined_ctx)
    if inferred:
        return inferred
    # DM tests default to QLIKE in this codebase unless otherwise stated
    return "QLIKE"


def resolve_sample_n(pair_dict: dict, root_data: dict) -> int | None:
    for key in ("n_valid", "n", "n_oos", "sample_n", "n_common", "oos_n"):
        v = pair_dict.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return int(v)
    return detect_sample_n(root_data)


def extract_rows_from_file(jf: Path) -> list[dict]:
    try:
        with jf.open() as fh:
            data = json.load(fh)
    except Exception:
        return []
    if not isinstance(data, dict):
        return []

    k_id = parse_k_id(jf)
    source_rel = str(jf.relative_to(ROOT))

    rows: list[dict] = []
    seen_paths: set[str] = set()

    for pair_dict, label, ctx_path in iter_pair_entries(data, []):
        if not isinstance(pair_dict, dict):
            continue
        dm_stat = get_dm_stat(pair_dict)
        if dm_stat is None:
            continue
        # skip results that are just nested container entries without pair identity
        model_a, model_b = resolve_models(pair_dict, label)
        if not model_a or not model_b:
            # If label doesn't parse as pair and no explicit model_1/2, skip
            # (single-model loss numbers, not DM comparisons)
            # But allow if "winner"/"better_model" exists implying a pair
            if not any(k in pair_dict for k in ("winner", "better_model", "comparison", "pair")):
                continue
        p_value, p_est = get_p_value(pair_dict)
        harvey = get_harvey_flag(pair_dict)
        asset = norm_asset(resolve_asset(pair_dict, ctx_path, data))
        period = resolve_period(pair_dict, ctx_path, data)
        loss_fn = resolve_loss(pair_dict, ctx_path)
        sample_n = resolve_sample_n(pair_dict, data)

        source_field_path = ".".join(str(x) for x in ctx_path) if ctx_path else ""
        dedup_key = f"{k_id}|{source_field_path}|{model_a}|{model_b}|{loss_fn}|{asset}|{period}"
        if dedup_key in seen_paths:
            continue
        seen_paths.add(dedup_key)

        row = {
            "k_id": k_id,
            "model_a": model_a,
            "model_b": model_b,
            "loss_fn": loss_fn,
            "asset": asset,
            "sample_n": sample_n,
            "period": period,
            "dm_stat": round(float(dm_stat), 6),
            "p_value": round(float(p_value), 8) if p_value is not None else None,
            "harvey_adjusted": harvey,
            "source_file": source_rel,
            "source_field_path": source_field_path,
        }
        rows.append(row)
    return rows


def main() -> int:
    folders = []
    for p in sorted(EXP_DIR.iterdir()):
        if not p.is_dir():
            continue
        m = re.match(r"^k(\d+)$", p.name)
        if not m:
            continue
        n = int(m.group(1))
        if 400 <= n <= 1258:
            folders.append(p)

    json_files: list[Path] = []
    for f in folders:
        for jf in sorted(f.rglob("*_results.json")):
            json_files.append(jf)
        for jf in sorted(f.glob("results.json")):
            if jf not in json_files:
                json_files.append(jf)

    print(f"Scanning {len(json_files)} JSON files across {len(folders)} K experiments...")

    all_rows: list[dict] = []
    missing_dm: list[str] = []  # files for which no DM row was extracted
    for jf in json_files:
        rs = extract_rows_from_file(jf)
        if not rs:
            missing_dm.append(str(jf.relative_to(ROOT)))
        else:
            all_rows.extend(rs)

    # Write ledger JSON (array of rows with strict schema)
    # Ensure every row has exactly the canonical keys
    normalized = [{k: r.get(k) for k in ROW_KEYS} for r in all_rows]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_ledger = OUT_DIR / "dm_ledger.json"
    with out_ledger.open("w") as fh:
        json.dump(
            {
                "experiment_id": "K1259",
                "phase": 1,
                "description": "Diebold-Mariano pair ledger extracted from K400-K1258 experiment results.",
                "row_schema": ROW_KEYS,
                "n_rows": len(normalized),
                "n_files_scanned": len(json_files),
                "n_files_without_dm": len(missing_dm),
                "rows": normalized,
            },
            fh,
            indent=2,
            default=str,
        )
    print(f"Wrote {out_ledger} ({len(normalized)} rows)")

    # Write summary
    write_summary(normalized, json_files, missing_dm)
    return 0


def write_summary(rows: list[dict], scanned_files: list[Path], missing: list[str]) -> None:
    out_md = OUT_DIR / "dm_ledger_summary.md"
    n_rows = len(rows)
    unique_k = sorted({r["k_id"] for r in rows})
    unique_models = sorted({m for r in rows for m in (r["model_a"], r["model_b"]) if m})
    unique_assets = sorted({r["asset"] for r in rows if r["asset"]})
    unique_losses = sorted({r["loss_fn"] for r in rows if r["loss_fn"]})

    dm_stats = [r["dm_stat"] for r in rows if isinstance(r["dm_stat"], (int, float))]
    abs_dm = [abs(x) for x in dm_stats]
    harvey_sig = sum(1 for x in abs_dm if x > 3.0)
    p_vals = [r["p_value"] for r in rows if isinstance(r["p_value"], (int, float))]

    def safe_stat(xs, fn):
        try:
            return fn(xs) if xs else float("nan")
        except Exception:
            return float("nan")

    # Model × Asset coverage
    from collections import Counter
    model_counts = Counter(m for r in rows for m in (r["model_a"], r["model_b"]) if m)
    asset_counts = Counter(r["asset"] for r in rows if r["asset"])
    loss_counts = Counter(r["loss_fn"] for r in rows if r["loss_fn"])
    k_counts = Counter(r["k_id"] for r in rows)

    lines: list[str] = []
    lines.append("# K1259 Phase 1 — DM Ledger Summary\n")
    lines.append(f"*Generated by `experiments/k1259/build_dm_ledger.py` for MCS/SPA meta-analysis.*\n")
    lines.append("## Overview\n")
    lines.append(f"- **Total DM rows**: {n_rows}")
    lines.append(f"- **Unique K experiments contributing rows**: {len(unique_k)}")
    lines.append(f"- **Unique model names**: {len(unique_models)}")
    lines.append(f"- **Unique assets**: {len(unique_assets)}")
    lines.append(f"- **Loss functions observed**: {', '.join(unique_losses) if unique_losses else '(none identified)'}")
    lines.append(f"- **Files scanned**: {len(scanned_files)} | **without DM content**: {len(missing)}")
    lines.append("")
    lines.append("## DM statistic distribution\n")
    lines.append(f"- Mean dm_stat: {safe_stat(dm_stats, mean):.4f}")
    lines.append(f"- Median dm_stat: {safe_stat(dm_stats, median):.4f}")
    lines.append(f"- Std dm_stat: {safe_stat(dm_stats, lambda xs: stdev(xs) if len(xs) > 1 else float('nan')):.4f}")
    lines.append(f"- Mean |dm_stat|: {safe_stat(abs_dm, mean):.4f}")
    lines.append(f"- Share |dm_stat| > 3 (Harvey-sig): {harvey_sig}/{len(dm_stats)} = {100*harvey_sig/max(len(dm_stats),1):.1f}%")
    lines.append(f"- p-values available: {len(p_vals)}/{n_rows}")
    lines.append("")

    # Top 20 models
    lines.append("## Top 20 models by row frequency\n")
    lines.append("| Model | Row count |")
    lines.append("|---|---:|")
    for m, c in model_counts.most_common(20):
        lines.append(f"| {m} | {c} |")
    lines.append("")

    # Asset coverage
    lines.append("## Asset coverage\n")
    lines.append("| Asset | Row count |")
    lines.append("|---|---:|")
    for a, c in asset_counts.most_common(30):
        lines.append(f"| {a or '(blank)'} | {c} |")
    lines.append(f"| (no asset tag) | {sum(1 for r in rows if not r['asset'])} |")
    lines.append("")

    # Loss coverage
    lines.append("## Loss function coverage\n")
    lines.append("| Loss | Row count |")
    lines.append("|---|---:|")
    for lf, c in loss_counts.most_common():
        lines.append(f"| {lf} | {c} |")
    lines.append("")

    # K-level concentration (top 20 contributors)
    lines.append("## Top 20 K-experiment contributors\n")
    lines.append("| K | Row count |")
    lines.append("|---|---:|")
    for k, c in k_counts.most_common(20):
        lines.append(f"| {k} | {c} |")
    lines.append("")

    # Model × Asset crosstab (top 20 models × top assets)
    lines.append("## Model × Asset coverage matrix (top 15 models × top 6 assets)\n")
    top_models = [m for m, _ in model_counts.most_common(15)]
    top_assets = [a for a, _ in asset_counts.most_common(6)]
    lines.append("| Model \\ Asset | " + " | ".join(top_assets) + " | total |")
    lines.append("|---" * (len(top_assets) + 2) + "|")
    for m in top_models:
        rowc = []
        total = 0
        for a in top_assets:
            c = sum(1 for r in rows if r["asset"] == a and (r["model_a"] == m or r["model_b"] == m))
            rowc.append(str(c))
            total += c
        lines.append(f"| {m} | " + " | ".join(rowc) + f" | {total} |")
    lines.append("")

    # Representation gaps
    lines.append("## Representation gaps (candidate reviewer flags)\n")
    # Assets with low coverage
    small_assets = [(a, c) for a, c in asset_counts.items() if c < 5]
    if small_assets:
        lines.append("**Assets with fewer than 5 DM rows** (may be insufficient for per-asset MCS):")
        for a, c in sorted(small_assets, key=lambda x: x[1]):
            lines.append(f"- `{a}` : {c} rows")
    else:
        lines.append("- No assets below 5-row threshold.")
    lines.append("")
    # Models with only 1 pair
    lonely = [m for m, c in model_counts.items() if c <= 2]
    lines.append(f"**Models appearing in <=2 DM rows**: {len(lonely)} (listing first 40)")
    for m in lonely[:40]:
        lines.append(f"- {m}")
    if len(lonely) > 40:
        lines.append(f"- ... (+{len(lonely)-40} more)")
    lines.append("")

    # Blank asset tag concern
    n_blank_asset = sum(1 for r in rows if not r["asset"])
    if n_blank_asset > 0:
        lines.append(f"**{n_blank_asset} rows have no asset tag.** These inherit single-asset K defaults (often SPY) but were not machine-tagged. Phase 2 MCS should re-inspect and backfill.")
        lines.append("")

    # 3 representative rows
    lines.append("## 3 representative rows\n")
    # pick one with large |dm|, one marginal, one null
    if rows:
        sorted_abs = sorted([r for r in rows if isinstance(r["dm_stat"], (int, float))], key=lambda r: abs(r["dm_stat"]), reverse=True)
        picks = []
        if sorted_abs:
            picks.append(sorted_abs[0])  # largest
            # marginal around 2
            close_2 = sorted([r for r in sorted_abs if 1.8 <= abs(r["dm_stat"]) <= 2.5], key=lambda r: abs(abs(r["dm_stat"]) - 2.0))
            if close_2:
                picks.append(close_2[0])
            # near-zero null
            close_0 = sorted([r for r in sorted_abs if abs(r["dm_stat"]) < 0.5], key=lambda r: abs(r["dm_stat"]))
            if close_0:
                picks.append(close_0[0])
        for i, r in enumerate(picks, 1):
            lines.append(f"### Example {i}")
            lines.append("```json")
            lines.append(json.dumps(r, indent=2, default=str))
            lines.append("```")
    lines.append("")

    out_md.write_text("\n".join(lines))
    print(f"Wrote {out_md}")


if __name__ == "__main__":
    sys.exit(main())
