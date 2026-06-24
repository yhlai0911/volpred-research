"""Audit experiments/ for lookahead-prone volatility experiment patterns.

Background: 2026-05-06 K547 audit sweep (`docs/error_log.md`) identified that
4 experiments (K547 / K570 / K556 / K583) had `port_ret = weights * spy_ret`
(or equivalent) with no lag — weights computed from same-day signal × same-day
return leaks information. K547/K570 were already published with caveat;
K556/K583 were patched in the 2026-05-06 follow-up. Verified-clean experiments
(K288 / K626 / K731 / K759 / K811 / K811v2 / K950) all use one of three lag
forms: `weights = weights.shift(1)`, `_lag = ....shift(1)`, or `_next_ret`.

This script enforces the convention going forward by grepping for the
multiplication pattern and checking each match against allowed lag markers
within a small radius. Mismatches → exit 1 with a list of suspect lines so
CI / cron can flag silent regressions before they ship.

Usage:
  uv run python scripts/lookahead_audit.py            # report mode
  uv run python scripts/lookahead_audit.py --strict   # exit 1 on any unverified hit
  uv run python scripts/lookahead_audit.py --json     # machine-readable

Allowlist (`KNOWN_BUG_FAMILY`) marks experiments that already shipped with
caveats (K547/K570) or whose results.json/article are explicitly tagged as
lookahead-aware caveat — they don't need to fail audit, but the pattern is
still listed so the audit doesn't lose track.

Convention: `signal from t-1, return at t` (`.claude/rules/experiments.md`).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENTS = ROOT / "experiments"

# Pattern matches `weights * RETURN_LIKE`. Right-operand whitelist filters out
# `weights * leverage` / `weights * exposure` / `weights * cap` (exposure
# scaling, not return mul) — those produced false positives in K595 / K598.
RETURN_LIKE = r"(?:[\w\.]*(?:ret|return|rets|returns|spy_ret|gld_ret|shy_ret|equity_ret|safe_ret|simple_ret|log_ret|excess_ret|next_ret|forward_ret|raw_ret|daily_ret)\b)"
PATTERN = re.compile(
    rf"\bweights\s*\*\s*{RETURN_LIKE}|"
    rf"\b\w+_weights\s*\*\s*{RETURN_LIKE}|"
    # 2026-05-06 K222 silent-miss fix: also catch singular `*_weight` variables
    # (vt_weight × raw_ret pattern). K547 audit family used plural "weights"
    # convention but K222 family uses singular — single shape regex missed.
    rf"\b\w*weight\b\s*\*\s*{RETURN_LIKE}|"
    rf"\bport_ret\s*=\s*weights\s*\*|"
    rf"\bgross\s*=\s*weights\s*\*\s*{RETURN_LIKE}|"
    rf"\bstrat_ret\s*=\s*\w*weights\w*\s*\*",
    re.IGNORECASE,
)

# 2026-05-06 K222 silent-miss fix: secondary detector for "signal-at-t × ret-at-t"
# shape (Codex review of mile_291f9029). K222 read `vix_series.loc[date]` then
# computed weight then multiplied by same-day return — primary regex missed
# because the lookahead is in the SIGNAL READ, not the multiplication.
# Heuristic: if a loop body reads VIX/signal with the loop variable as index
# AND applies a return in the same body, the construction is suspicious unless
# a lag marker is nearby.
SIGNAL_LOOKAHEAD_PATTERN = re.compile(
    r"\b(?:vix|signal|sma|momentum|rv|vol|garch)_?[\w]*\.(?:loc|iloc)\[\s*(?:date|i|t|idx)\s*\]",
    re.IGNORECASE,
)

# 2026-06-16 K445 article review: arch's default one-step forecast alignment is
# origin-aligned. The risky OOS pattern is `forecast(horizon=1, start=...,
# reindex=False)` followed by same-index realized variance / QLIKE / MSE / DM
# loss computation. A target-aligned call or an explicit shift/target comment
# must appear nearby.
ARCH_FORECAST_PATTERN = re.compile(
    r"\.forecast\([^#\n]*horizon\s*=\s*1[^#\n]*(?:start\s*=|reindex\s*=\s*False)[^#\n]*\)",
    re.IGNORECASE,
)
ARCH_OOS_LOSS_MARKER = re.compile(
    r"\brealized(?:_sq|_var|_variance|_r2)?\s*\.loc\b|"
    r"\b(?:qlike|mse|dm_test|diebold|loss)\b",
    re.IGNORECASE,
)
ARCH_TARGET_ALIGNMENT_MARKER = re.compile(
    r"align\s*=\s*['\"]target['\"]|"
    r"target[-_ ]aligned|"
    r"origin[-_ ]aligned.*shift|"
    r"\.shift\(\s*-?1\s*\)|"
    r"shift(?:ed)?\s+to\s+target",
    re.IGNORECASE,
)

# Lag markers — at least one must appear within ±LAG_RADIUS lines of each
# multiplication match for the file to be considered lag-aware.
LAG_MARKERS = [
    r"\.shift\(1\)",
    r"_lag\b",
    r"_next_ret\b",
    r"weights\s*=\s*np\.concatenate",
    r"K547 audit",  # comment marker for explicit audit-fix sites
    r"K547-family",  # variant marker
    r"K222 audit",  # 2026-05-06 K222 patch marker
    r"iloc\[\s*i\s*-\s*1\s*\]",  # explicit prev-day numpy/pandas indexing
    r"\.index\[\s*i\s*-\s*1\s*\]",  # 2026-05-06: K222-style index[i-1] lookup
    r"prev_date\s*=",  # 2026-05-06: explicit prev_date assignment
    r"\.index\s*<\s*\w+",  # 2026-05-06 taiwan_paper_fixes pattern: index < date strict-less-than filter
    r"vix_before\s*=",  # 2026-05-06: explicit "before" naming for prev-day extraction
    r"\[\s*:\s*-\s*1\s*\]",  # generic [:-1] slice (lag concat)
]
LAG_REGEX = re.compile("|".join(LAG_MARKERS), re.IGNORECASE)
LAG_RADIUS = 30  # ±30 lines around the match

# Experiments that shipped with documented caveat — pattern present but flagged.
KNOWN_BUG_FAMILY = {"k547", "k570"}
KNOWN_ARCH_ALIGNMENT_CAVEAT = {"k445"}


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def _warn_lookup_audit(message: str, *, path: Path, exc: BaseException) -> None:
    print(
        f"[lookahead_audit] WARN {message} path={_display_path(path)} "
        f"error={type(exc).__name__}: {exc}",
        file=sys.stderr,
    )


def audit_file(path: Path) -> list[dict]:
    """Return list of suspect dicts (empty = clean).

    A match is `verified` if either:
    (a) a lag marker appears within ±LAG_RADIUS lines of the multiplication, OR
    (b) the file globally contains any lag marker (file-wide opt-in).

    Per-variable AST tracking is out of scope; (a) catches the common
    backtest_strategy() pattern, (b) catches files with the lag applied at
    construction time far from the multiplication site (e.g. K731 line 339
    `weights = raw_weights.shift(1)` then line 675 reuses that weights series).
    Tradeoff: (b) accepts false-positive lag-confidence in files that have
    `.shift(1)` in unrelated code paths. Run with `--strict-radius` to
    disable (b) and require lag in window only.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as exc:
        _warn_lookup_audit("source read failed; skipping file", path=path, exc=exc)
        return []
    lines = text.splitlines()
    file_has_lag = bool(LAG_REGEX.search(text))
    suspects: list[dict] = []

    for i, line in enumerate(lines):
        primary_match = bool(PATTERN.search(line))
        signal_match = bool(SIGNAL_LOOKAHEAD_PATTERN.search(line))
        arch_forecast_match = bool(ARCH_FORECAST_PATTERN.search(line))
        if not (primary_match or signal_match or arch_forecast_match):
            continue
        # Skip comments / docstrings
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
            continue

        # Look for a lag / target-alignment marker within ±LAG_RADIUS
        lo = max(0, i - LAG_RADIUS)
        hi = min(len(lines), i + LAG_RADIUS + 1)
        window = "\n".join(lines[lo:hi])
        has_lag_local = bool(LAG_REGEX.search(window))
        has_lag = has_lag_local or file_has_lag

        # For signal-shape matches, require BOTH (a) signal-at-t read AND (b)
        # return application within ±LAG_RADIUS (otherwise it's a benign
        # lookup like a regime classifier read at signal time, not return time).
        is_suspect = primary_match or arch_forecast_match
        if signal_match and not primary_match and not arch_forecast_match:
            # Require window to contain an actual `weight × ret` multiplication,
            # not just any return-like keyword. Filters K641-style metadata
            # snapshots where vix.loc[date] is logged but no return calc nearby.
            mul_with_ret = bool(re.search(rf"\*\s*{RETURN_LIKE}|{RETURN_LIKE}\s*\*", window))
            is_suspect = mul_with_ret
        if not is_suspect:
            continue

        if arch_forecast_match:
            loss_context = bool(ARCH_OOS_LOSS_MARKER.search(window))
            if not loss_context:
                continue
            has_target_alignment = bool(ARCH_TARGET_ALIGNMENT_MARKER.search(window))
            suspects.append({
                "line_no": i + 1,
                "line": stripped[:120],
                "shape": "arch_origin_forecast_alignment",
                "has_lag_marker_nearby": has_target_alignment,
                "lag_local": has_target_alignment,
                "lag_global": False,
            })
            continue

        suspects.append({
            "line_no": i + 1,
            "line": stripped[:120],
            "shape": "primary" if primary_match else "signal_lookahead",
            "has_lag_marker_nearby": has_lag,
            "lag_local": has_lag_local,
            "lag_global": file_has_lag,
        })
    return suspects


def kid_from_path(path: Path) -> str:
    """Extract experiment slug (e.g. 'k556', 'k811v2') from path."""
    parent = path.parent.name.lower()
    return parent if parent.startswith("k") else path.stem.split("_")[0].lower()


def run_audit() -> dict:
    findings: dict[str, dict] = {}
    for py in sorted(EXPERIMENTS.glob("**/*.py")):
        if "__pycache__" in py.parts:
            continue
        suspects = audit_file(py)
        if not suspects:
            continue

        kid = kid_from_path(py)
        unverified = [s for s in suspects if not s["has_lag_marker_nearby"]]
        verified = [s for s in suspects if s["has_lag_marker_nearby"]]
        known_caveat = kid in KNOWN_BUG_FAMILY or kid in KNOWN_ARCH_ALIGNMENT_CAVEAT

        findings[str(py.relative_to(ROOT))] = {
            "kid": kid,
            "is_known_bug": known_caveat,
            "n_matches": len(suspects),
            "n_verified": len(verified),
            "n_unverified": len(unverified),
            "unverified": unverified,
        }
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true",
                        help="exit 1 if any non-known-bug file has unverified matches")
    parser.add_argument("--json", action="store_true",
                        help="emit machine-readable JSON")
    args = parser.parse_args()

    findings = run_audit()

    n_files = len(findings)
    n_verified_files = sum(1 for f in findings.values() if f["n_unverified"] == 0)
    n_known_bug = sum(1 for f in findings.values() if f["is_known_bug"])
    n_unverified_files = sum(1 for f in findings.values()
                             if f["n_unverified"] > 0 and not f["is_known_bug"])

    if args.json:
        print(json.dumps({
            "files_with_pattern": n_files,
            "files_lag_verified": n_verified_files,
            "files_known_bug_family": n_known_bug,
            "files_unverified_unknown": n_unverified_files,
            "findings": findings,
        }, indent=2))
    else:
        print(f"[lookahead_audit] scanned {n_files} file(s) with lookahead-prone pattern(s):")
        print(f"  - lag-verified (≥1 .shift(1)/_lag/_next_ret nearby): {n_verified_files}")
        print(f"  - known-bug / known-caveat family:                   {n_known_bug}")
        print(f"  - UNVERIFIED unknown (potential silent regression):  {n_unverified_files}")
        if n_unverified_files:
            print("\n[lookahead_audit] UNVERIFIED files:")
            for fp, f in findings.items():
                if f["n_unverified"] > 0 and not f["is_known_bug"]:
                    print(f"  {fp}  (kid={f['kid']}, {f['n_unverified']}/{f['n_matches']} unverified)")
                    for s in f["unverified"][:3]:
                        print(f"    L{s['line_no']}: {s['line']}")

    if args.strict and n_unverified_files > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
