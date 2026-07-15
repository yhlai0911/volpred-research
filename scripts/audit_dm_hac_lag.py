#!/usr/bin/env python3
"""Full-population audit of self-written Diebold-Mariano / HLN implementations.

Bug class (K1655, 2026-07-11): a local DM helper that sets its Newey-West
bandwidth to ``lag = h - 1`` silently applies *no* HAC correction when h == 1,
because the correction loop ``range(1, h)`` is then empty. The canonical
implementation (``volpred.stats.model_evaluation.dm_test``) floors the bandwidth
at 1 -- ``max_lag = max(1, min(ceil(h**(1/3) * n**(1/3)), n // 4))`` -- so it
never degenerates.

That matters whenever the loss differential is autocorrelated for reasons other
than overlapping forecast windows (misspecified model vs benchmark, persistent
predictors like NFCI / VIX). In K1655 the differential had acf(1) = 0.68 and the
missing HAC correction inflated |t|: 26 of 60 DM cells read as Harvey-significant
before the fix, 18 after.

The first version only recognised an explicit ``lag = h - 1`` / ``range(1, h)``
shape under ``experiments/``.  That left three important false-negative classes:
plain-variance DM/HLN helpers (zero HAC without any lag variable), DM-like
one-sample t-tests, and replication scripts under ``paper/*/experiments/``.
This script classifies all of those sites so the class can be triaged as a
population rather than one file at a time.  Static analysis only -- it never
imports or executes experiment code.

Usage:
    uv run python scripts/audit_dm_hac_lag.py                    # human summary
    uv run python scripts/audit_dm_hac_lag.py --json report.json # machine report
    uv run python scripts/audit_dm_hac_lag.py --affected-only    # only real bugs
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from volpred.ops.diagnostics import warn  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
SCAN_PATTERNS = (
    "experiments/**/*.py",
    "paper/*/experiments/**/*.py",
)

# Function names that plausibly implement a DM / HLN test locally.
DM_NAME_RE = re.compile(r"(^|_)(dm|hln|diebold|mariano)(_|$)", re.IGNORECASE)

# Names an author would bind a Newey-West bandwidth to.
LAG_NAME_RE = re.compile(
    r"^(?:(?:nw|hac|canon(?:ical)?|newey_west)_)?"
    r"(?:(?:max)_)?(?:lag|lags|bandwidth|band|q|trunc|truncation)"
    r"(?:_(?:max|used|nw|hac))?$|^L$",
    re.IGNORECASE,
)

HORIZON_NAME_RE = re.compile(r"^(?:h|H|(?:\w*_)?horizon(?:_\w*)?)$")

# Verdicts, ordered worst -> best.
DEGENERATE = "degenerate_at_h1"  # lag = h-1 with no floor: zero HAC when h=1
NO_HAC = "no_hac"  # plain variance / iid t-test / explicit zero bandwidth
H_INCLUSIVE = "h_lags_inclusive"  # range(1, h+1): keeps lag 1, but never scales with n
HARDCODED = "hardcoded"  # fixed integer bandwidth, independent of h and n
CANONICAL_LIKE = "canonical_like"  # n**(1/3) style rule, or floored at >= 1
DEPENDENCE_ROBUST = "dependence_robust_resampling"  # block/stationary bootstrap
DELEGATES = "delegates_to_canonical"  # imports volpred canonical dm_test
UNKNOWN = "unknown"  # DM-ish def found, no bandwidth binding recognised
NOT_A_TEST = "not_a_dm_test"  # name matched but the body computes no test statistic

SEVERITY = {
    NO_HAC: 0,
    DEGENERATE: 1,
    UNKNOWN: 2,
    H_INCLUSIVE: 3,
    HARDCODED: 4,
    CANONICAL_LIKE: 5,
    DEPENDENCE_ROBUST: 6,
    DELEGATES: 7,
    NOT_A_TEST: 8,
}

# The CI ratchet freezes both ways a local forecast-comparison test can silently
# omit HAC: an h=1-degenerate loop and an implementation with no HAC machinery.
RATCHET_VERDICTS = frozenset({DEGENERATE, NO_HAC})

# A real DM implementation has to touch the loss differential's second moment.
# Plotting / formatting / classification helpers whose name merely contains "dm"
# do not, and must not inflate the population count.
TEST_MACHINERY_RE = re.compile(
    r"np\.(?:var|std|cov)|\.(?:var|std|cov)\(|gamma|autocov|ttest_1samp"
    r"|(?:\w*stats|_st)\.(?:t|norm)\.|norm\.(?:cdf|sf)"
)

# Reading a ``t_stat`` key in a plot is not evidence that the function computes
# a test.  Assigning the statistic is.  This distinction removes the old
# ``plot_dm_*`` false positives while retaining oddly named local tests.
STAT_TARGET_NAMES = frozenset(
    {"t", "t_stat", "tstat", "dm_stat", "dm_t", "t_hln", "t_hac"}
)

PLAIN_VARIANCE_RE = re.compile(
    r"np\.(?:var|std)\s*\(|\.(?:var|std)\s*\(", re.IGNORECASE
)
# Hand-rolled sample variance used as the long-run variance, e.g.
# ``gamma0 = np.mean(d**2) - d_bar**2`` (the E[X^2] - E[X]^2 computational
# formula). PLAIN_VARIANCE_RE only recognises np.var / np.std, so this idiom --
# treating the plain sample variance as the DM long-run variance, i.e. zero HAC
# correction -- otherwise falls through to ``unknown`` (k1379.py:359 blind spot).
# The left term is a second raw moment ``mean(<x>**2)``; the right term is a
# squared mean (``d_bar**2``, ``np.mean(d)**2``, ``d.mean()**2``, ``** 2`` etc).
# The deviation form ``np.mean((d - d_bar)**2)`` has inner parens after ``mean(``
# and deliberately does NOT match, so a genuine gamma0-plus-autocovariance loop
# is not misread; the HAC_MACHINERY_RE / serial-lag-loop guards in
# _plain_variance_only remain the backstop against false positives.
MANUAL_VARIANCE_RE = re.compile(
    r"(?:np\.)?mean\s*\(\s*[^()]*\*\*\s*2[^()]*\)\s*-\s*[^-+]*?\*\*\s*2",
    re.IGNORECASE,
)
HAC_MACHINERY_RE = re.compile(
    r"np\.cov|\.cov\(|autocov|\bcov_hac\b|gamma(?:_[kl]|\[)|newey_west|bartlett"
    r"|\bnw_var\b|\b_?hac_var\s*\(|\b_?dm_lrv\s*\(|\blong_run_var\b"
    r"|cov_type\s*=\s*['\"]HAC['\"]",
    re.IGNORECASE,
)

# Evidence that the file actually evaluates a one-step-ahead horizon, which is
# the only place lag = h-1 fully degenerates.
H1_RE = re.compile(
    r"\bh\s*=\s*1\b|\bhorizon\s*=\s*1\b|\bHORIZONS?\s*[:=]\s*[\[\(]\s*1\b"
    r"|\bhorizons?\s*[:=]\s*[\[\(]\s*1\b|\bH\s*=\s*1\b",
)


@dataclass
class Finding:
    file: str
    function: str
    lineno: int
    verdict: str
    lag_expr: str | None
    exercises_h1: bool
    notes: list[str] = field(default_factory=list)

    @property
    def exposed(self) -> bool:
        """Structurally exposed to omitted serial-correlation correction.

        This is exposure, not a proven error. At h == 1 the textbook DM statistic
        legitimately uses no HAC term, because a correctly specified one-step
        forecast has a serially uncorrelated loss differential. The correction
        only matters when that assumption fails -- a misspecified challenger, or a
        persistent predictor. Whether it fails at any given site is an empirical
        question about that site's loss differential (K1655: acf(1) = 0.68), and
        static analysis cannot answer it. Confirming materiality means re-running
        the experiment and measuring the autocorrelation.
        """
        return self.verdict == NO_HAC or (
            self.verdict == DEGENERATE and self.exercises_h1
        )


def _target_names(target: ast.expr) -> set[str]:
    """Return all simple names bound by an assignment target."""
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, (ast.Tuple, ast.List)):
        names: set[str] = set()
        for elt in target.elts:
            names.update(_target_names(elt))
        return names
    return set()


def _expression_computes_statistic(value: ast.expr | None) -> bool:
    """Reject result readers such as ``dm_stat = row['dm_stat']``."""
    if value is None:
        return False
    return any(isinstance(node, ast.BinOp) for node in ast.walk(value))


def _function_computes_test_statistic(fn: ast.FunctionDef) -> bool:
    """Distinguish statistic producers from plotting/result-reader helpers."""
    body_src = _function_body_src(fn)
    if TEST_MACHINERY_RE.search(body_src):
        return True
    for node in ast.walk(fn):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        names = set().union(*(_target_names(target) for target in targets))
        statistic_target = bool(names & STAT_TARGET_NAMES) or any(
            "dm" in name.lower()
            and ("stat" in name.lower() or name.lower().endswith("_t"))
            for name in names
        )
        if statistic_target and _expression_computes_statistic(node.value):
            return True
    return False


def _function_body_src(fn: ast.FunctionDef) -> str:
    """Unparse executable body only, excluding a docstring's prose tokens."""
    body = list(fn.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    return "\n".join(ast.unparse(node) for node in body)


def _lag_default(fn: ast.FunctionDef) -> tuple[str, str] | None:
    """Return a lag-like argument and its default expression, if present."""
    positional = [*fn.args.posonlyargs, *fn.args.args]
    defaults = [None] * (len(positional) - len(fn.args.defaults)) + list(fn.args.defaults)
    pairs = list(zip(positional, defaults, strict=True))
    pairs.extend(zip(fn.args.kwonlyargs, fn.args.kw_defaults, strict=True))
    for arg, default in pairs:
        if default is not None and LAG_NAME_RE.match(arg.arg):
            return arg.arg, ast.unparse(default)
    return None


def _is_candidate_function(fn: ast.FunctionDef) -> bool:
    """Select DM-named helpers plus zero-bandwidth forecast-test variants."""
    if DM_NAME_RE.search(fn.name):
        return True
    lag_default = _lag_default(fn)
    if lag_default is None:
        return False
    arg_name, default = lag_default
    parameter_names = {arg.arg for arg in [*fn.args.posonlyargs, *fn.args.args]}
    return (
        arg_name.lower().startswith("nw_")
        and default.replace(" ", "") == "0"
        and "h" in parameter_names
        and _function_computes_test_statistic(fn)
    )


def _function_has_serial_lag_loop(fn: ast.FunctionDef) -> bool:
    """Detect hand-written Bartlett/autocovariance loops independent of names."""
    for node in ast.walk(fn):
        if isinstance(node, ast.For):
            target = node.target
            iterator = node.iter
            loop_src = ast.unparse(node)
        elif isinstance(node, ast.comprehension):
            target = node.target
            iterator = node.iter
            loop_src = ast.unparse(node)
        else:
            continue
        if not isinstance(target, ast.Name) or not isinstance(iterator, ast.Call):
            continue
        if not isinstance(iterator.func, ast.Name) or iterator.func.id != "range":
            continue
        args = iterator.args
        if len(args) < 2 or not isinstance(args[0], ast.Constant) or args[0].value != 1:
            continue
        lag_name = re.escape(target.id)
        forward_slice = re.search(rf"\[\s*{lag_name}\s*:", loop_src)
        backward_slice = re.search(rf":\s*-\s*{lag_name}\s*\]", loop_src)
        covariance_name = re.search(
            r"\b(?:cov|gamma|autocov|long_var|var_d|lrv)\w*\b", loop_src, re.I
        )
        if (forward_slice and backward_slice) or covariance_name:
            return True
    return False


def _plain_variance_only(fn: ast.FunctionDef, body_src: str) -> bool:
    """Recognise iid variance used as the DM long-run variance."""
    return (
        bool(PLAIN_VARIANCE_RE.search(body_src) or MANUAL_VARIANCE_RE.search(body_src))
        and not bool(HAC_MACHINERY_RE.search(body_src))
        and not _function_has_serial_lag_loop(fn)
    )


def _canonical_aliases(tree: ast.AST) -> set[str]:
    """Names bound to canonical DM helpers, including function-local imports."""
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.module != "volpred.stats.model_evaluation":
            continue
        for alias in node.names:
            if "dm_test" in alias.name:
                aliases.add(alias.asname or alias.name)
    return aliases


def _function_calls_alias(fn: ast.FunctionDef, aliases: set[str]) -> bool:
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id in aliases:
            return True
    return False


def _function_has_iid_fallback(fn: ast.FunctionDef) -> bool:
    """A canonical normal path does not make an iid exception fallback safe."""
    for handler in (node for node in ast.walk(fn) if isinstance(node, ast.ExceptHandler)):
        src = ast.unparse(handler)
        if "ttest_1samp" in src:
            return True
        if PLAIN_VARIANCE_RE.search(src) and not HAC_MACHINERY_RE.search(src):
            return True
    return False


def _function_uses_dependence_robust_resampling(fn: ast.FunctionDef) -> bool:
    """Recognise block/stationary bootstrap as a valid non-HAC alternative."""
    name = fn.name.lower()
    if "bootstrap" not in name:
        return False
    src = ast.unparse(fn).lower()
    return any(
        marker in src
        for marker in ("block_size", "block_len", "block_starts", "stationary bootstrap", "p_geom")
    )


def _function_is_explicitly_non_forecast(fn: ast.FunctionDef) -> bool:
    doc = (ast.get_docstring(fn) or "").lower()
    return "not a forecast-loss" in doc or "not a forecast loss" in doc


def _function_has_h1_iid_branch(fn: ast.FunctionDef) -> bool:
    """Catch ``if h <= 1: variance`` variants implemented via comprehensions."""
    for node in ast.walk(fn):
        if not isinstance(node, ast.If) or not isinstance(node.test, ast.Compare):
            continue
        test = node.test
        if len(test.ops) != 1 or len(test.comparators) != 1:
            continue
        if not isinstance(test.left, ast.Name) or not HORIZON_NAME_RE.match(test.left.id):
            continue
        if not isinstance(test.ops[0], (ast.Lt, ast.LtE)):
            continue
        threshold = _numeric_constant(test.comparators[0])
        if threshold is None or threshold > 1:
            continue
        body_src = "\n".join(ast.unparse(stmt) for stmt in node.body)
        if PLAIN_VARIANCE_RE.search(body_src) or ("** 2" in body_src and ".mean()" in body_src):
            return True
    return False


def _numeric_constant(node: ast.AST) -> float | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, ast.USub)
        and isinstance(node.operand, ast.Constant)
        and isinstance(node.operand.value, (int, float))
    ):
        return -float(node.operand.value)
    return None


def _contains_horizon_minus_one(node: ast.AST) -> bool:
    for part in ast.walk(node):
        if not isinstance(part, ast.BinOp) or not isinstance(part.op, ast.Sub):
            continue
        if not isinstance(part.left, ast.Name) or not HORIZON_NAME_RE.match(part.left.id):
            continue
        if _numeric_constant(part.right) == 1.0:
            return True
    return False


def _outer_max_info(node: ast.AST) -> tuple[float | None, bool]:
    """Return the numeric floor and whether max() has an unresolved dynamic arm."""
    if not (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "max"
    ):
        return None, False
    constants = [value for arg in node.args if (value := _numeric_constant(arg)) is not None]
    dynamic = any(
        _numeric_constant(arg) is None and not _contains_horizon_minus_one(arg)
        for arg in node.args
    )
    return (max(constants) if constants else None), dynamic


def _classify_lag_expr(src: str) -> tuple[str, list[str]]:
    """Classify a bandwidth expression by its source text."""
    notes: list[str] = []
    compact = src.replace(" ", "")

    canonical_shape = (
        "**(1/3)" in compact
        or "**(1./3" in compact
        or "**(2/9)" in compact
        or "**(2./9" in compact
        or "ceil" in compact.lower()
        or "n//4" in compact
        or "newey_west" in compact.lower()
    )
    try:
        expr = ast.parse(src, mode="eval").body
    except SyntaxError:
        expr = None
    minus_one = bool(expr is not None and _contains_horizon_minus_one(expr))
    numeric_floor, dynamic_floor = _outer_max_info(expr) if expr is not None else (None, False)

    if canonical_shape and not minus_one:
        return CANONICAL_LIKE, notes
    if minus_one and numeric_floor is not None and numeric_floor >= 1:
        notes.append(f"h-1 present but floored at {numeric_floor:g} -- does not degenerate")
        return CANONICAL_LIKE, notes
    if minus_one and canonical_shape:
        notes.append("h-1 combined with a canonical-shaped bound")
        return CANONICAL_LIKE, notes
    if minus_one and dynamic_floor:
        notes.append("h-1 combined with an unresolved dynamic max() arm -- inspect by hand")
        return UNKNOWN, notes
    if minus_one:
        notes.append("lag = h-1 with no positive floor: HAC loop is empty when h == 1")
        return DEGENERATE, notes
    if compact == "0":
        notes.append("bandwidth fixed at zero: inference uses iid variance only")
        return NO_HAC, notes
    if re.fullmatch(r"\d+", compact):
        notes.append(f"bandwidth fixed at {compact}, ignores h and sample size")
        return HARDCODED, notes
    if numeric_floor is not None and numeric_floor >= 1:
        return CANONICAL_LIKE, notes
    return UNKNOWN, notes


def _horizon_range_kind(node: ast.AST) -> str | None:
    """Classify the upper bound of ``range(1, upper)``."""
    if isinstance(node, ast.Name) and HORIZON_NAME_RE.match(node.id):
        return "exclusive"
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        if node.func.id == "min" and any(
            isinstance(arg, ast.Name) and HORIZON_NAME_RE.match(arg.id)
            for arg in node.args
        ):
            return "exclusive"
        if node.func.id == "max":
            has_horizon = any(
                isinstance(arg, ast.Name) and HORIZON_NAME_RE.match(arg.id)
                for arg in node.args
            )
            numeric_arms = [
                value
                for arg in node.args
                if (value := _numeric_constant(arg)) is not None
            ]
            # `range(1, max(1, h))` is still empty at h=1. A floor of
            # two or more keeps at least lag 1, but remains horizon-based and
            # does not scale with sample size.
            if has_horizon and numeric_arms:
                if max(numeric_arms) <= 1.0:
                    return "exclusive"
                return "positive_floor"
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        pairs = ((node.left, node.right), (node.right, node.left))
        if any(
            isinstance(horizon, ast.Name)
            and HORIZON_NAME_RE.match(horizon.id)
            and _numeric_constant(one) == 1.0
            for horizon, one in pairs
        ):
            return "inclusive"
    return None


def _scan_function(
    fn: ast.FunctionDef,
    path: Path,
    exercises_h1: bool,
    canonical_aliases: set[str],
) -> Finding | None:
    """Find the bandwidth binding inside one DM-ish function."""
    body_src = _function_body_src(fn)
    delegates = _function_calls_alias(fn, canonical_aliases)

    if _function_is_explicitly_non_forecast(fn):
        return Finding(
            file=str(path.relative_to(REPO_ROOT)),
            function=fn.name,
            lineno=fn.lineno,
            verdict=NOT_A_TEST,
            lag_expr=None,
            exercises_h1=exercises_h1,
            notes=["function explicitly documents a non-forecast Monte Carlo comparison"],
        )

    if _function_uses_dependence_robust_resampling(fn):
        return Finding(
            file=str(path.relative_to(REPO_ROOT)),
            function=fn.name,
            lineno=fn.lineno,
            verdict=DEPENDENCE_ROBUST,
            lag_expr="block/stationary bootstrap",
            exercises_h1=exercises_h1,
            notes=["dependence is preserved by block or stationary resampling"],
        )

    if delegates and _function_has_iid_fallback(fn):
        return Finding(
            file=str(path.relative_to(REPO_ROOT)),
            function=fn.name,
            lineno=fn.lineno,
            verdict=NO_HAC,
            lag_expr="iid exception fallback",
            exercises_h1=exercises_h1,
            notes=["canonical normal path has an iid fallback with no HAC correction"],
        )

    if delegates:
        return Finding(
            file=str(path.relative_to(REPO_ROOT)),
            function=fn.name,
            lineno=fn.lineno,
            verdict=DELEGATES,
            lag_expr=None,
            exercises_h1=exercises_h1,
            notes=["calls a canonical volpred model_evaluation DM helper"],
        )

    if not _function_computes_test_statistic(fn):
        return Finding(
            file=str(path.relative_to(REPO_ROOT)),
            function=fn.name,
            lineno=fn.lineno,
            verdict=NOT_A_TEST,
            lag_expr=None,
            exercises_h1=exercises_h1,
            notes=["name matched but body computes no test statistic"],
        )

    lag_expr: str | None = None

    for node in ast.walk(fn):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and LAG_NAME_RE.match(target.id):
                    if node.value is not None:
                        lag_expr = ast.unparse(node.value)

    # A default such as ``nw_lag=0`` is itself the binding when the function
    # never replaces it.  This was the k1116c Clark-West blind spot.
    if lag_expr is None:
        default = _lag_default(fn)
        if default is not None:
            _, lag_expr = default

    # A HAC loop written inline as `for lag in range(1, h)` binds no name but is
    # the same defect -- range(1, 1) is empty.
    if lag_expr is None:
        for node in ast.walk(fn):
            if isinstance(node, ast.For) and isinstance(node.iter, ast.Call):
                callee = node.iter.func
                if isinstance(callee, ast.Name) and callee.id == "range":
                    args = node.iter.args
                    if len(args) < 2:
                        continue
                    upper_node = args[1]
                    upper = ast.unparse(upper_node)
                    range_kind = _horizon_range_kind(upper_node)
                    if range_kind is None:
                        continue
                    if range_kind == "exclusive":
                        verdict = DEGENERATE
                        notes = [
                            f"inline `range(1, {upper})`: HAC loop is empty when h == 1"
                        ]
                    elif range_kind == "inclusive":
                        verdict = H_INCLUSIVE
                        notes = [
                            "inline `range(1, h+1)`: keeps lag 1 at h == 1, so no zero-HAC "
                            "degeneracy, but the bandwidth never grows with the sample"
                        ]
                    else:
                        verdict = H_INCLUSIVE
                        notes = [
                            f"inline `range(1, {upper})` has a positive lag floor, so it "
                            "does not degenerate at h == 1, but it never scales with the sample"
                        ]
                    return Finding(
                        file=str(path.relative_to(REPO_ROOT)),
                        function=fn.name,
                        lineno=fn.lineno,
                        verdict=verdict,
                        lag_expr=f"range(1, {upper})",
                        exercises_h1=exercises_h1,
                        notes=notes,
                    )

    if lag_expr is None and _function_has_h1_iid_branch(fn):
        return Finding(
            file=str(path.relative_to(REPO_ROOT)),
            function=fn.name,
            lineno=fn.lineno,
            verdict=DEGENERATE,
            lag_expr="if h <= 1: iid variance",
            exercises_h1=exercises_h1,
            notes=["explicit h<=1 branch omits every serial-covariance term"],
        )

    iid_ttest = "ttest_1samp" in body_src and not _function_has_serial_lag_loop(fn)
    if lag_expr is None and (iid_ttest or _plain_variance_only(fn, body_src)):
        lag_label = "iid one-sample t-test" if iid_ttest else "iid sample variance"
        return Finding(
            file=str(path.relative_to(REPO_ROOT)),
            function=fn.name,
            lineno=fn.lineno,
            verdict=NO_HAC,
            lag_expr=lag_label,
            exercises_h1=exercises_h1,
            notes=[
                "test statistic uses iid inference only; no long-run variance / "
                "HAC covariance terms are present"
            ],
        )

    if lag_expr is None:
        return Finding(
            file=str(path.relative_to(REPO_ROOT)),
            function=fn.name,
            lineno=fn.lineno,
            verdict=UNKNOWN,
            lag_expr=None,
            exercises_h1=exercises_h1,
            notes=["no bandwidth binding recognised -- inspect by hand"],
        )

    verdict, notes = _classify_lag_expr(lag_expr)
    return Finding(
        file=str(path.relative_to(REPO_ROOT)),
        function=fn.name,
        lineno=fn.lineno,
        verdict=verdict,
        lag_expr=lag_expr,
        exercises_h1=exercises_h1,
        notes=notes,
    )


def scan_file(path: Path) -> list[Finding]:
    # A skipped file is a false negative for a bug-class audit: it silently
    # shrinks the population being certified. Never drop one without a trace.
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        warn("audit_dm_hac_lag", "unreadable file skipped", path=str(path), err=str(exc))
        return []

    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        warn("audit_dm_hac_lag", "unparseable file skipped", path=str(path), err=str(exc))
        return []

    exercises_h1 = H1_RE.search(source) is not None
    canonical_aliases = _canonical_aliases(tree)

    findings: list[Finding] = []
    candidate_function_ids: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if not _is_candidate_function(node):
            continue
        candidate_function_ids.add(id(node))
        finding = _scan_function(node, path, exercises_h1, canonical_aliases)
        if finding is None:
            continue
        findings.append(finding)

    # Some historical scripts label an iid one-sample t-test as DM at module
    # scope or hide it inside an exception fallback in a broad ``main`` helper.
    # Walk assignments at every nesting level; candidate DM functions were
    # already handled above, so this path only fills the non-candidate blind spot.
    parent: dict[ast.AST, ast.AST] = {
        child: owner for owner in ast.walk(tree) for child in ast.iter_child_nodes(owner)
    }
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        value = node.value
        if not isinstance(value, ast.Call):
            continue
        callee = ast.unparse(value.func)
        if not callee.endswith("ttest_1samp"):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        target_names = set().union(*(_target_names(target) for target in targets))
        owner: ast.AST | None = node
        enclosing_function: ast.FunctionDef | None = None
        exception_handler: ast.ExceptHandler | None = None
        while owner in parent:
            owner = parent[owner]
            if exception_handler is None and isinstance(owner, ast.ExceptHandler):
                exception_handler = owner
            if isinstance(owner, ast.FunctionDef):
                enclosing_function = owner
                break
        if enclosing_function is not None and id(enclosing_function) in candidate_function_ids:
            continue
        context = exception_handler or enclosing_function or node
        context_src = ast.unparse(context)
        dm_context = any("dm" in name.lower() for name in target_names) or (
            bool(target_names & {"t", "t_stat", "tstat", "p", "p_val", "p_value"})
            and re.search(r"\bdm_(?:results|stat|test)\b", context_src, re.I) is not None
        )
        if not dm_context:
            continue
        owner_name = enclosing_function.name if enclosing_function is not None else "module"
        findings.append(
            Finding(
                file=str(path.relative_to(REPO_ROOT)),
                function=f"<{owner_name}>:ttest_1samp@{node.lineno}",
                lineno=node.lineno,
                verdict=NO_HAC,
                lag_expr="iid one-sample t-test",
                exercises_h1=True,
                notes=["DM-like iid t-test path has no HAC correction"],
            )
        )

    return findings


def scan_population(root: Path = REPO_ROOT) -> list[Finding]:
    findings: list[Finding] = []
    paths: set[Path] = set()
    for pattern in SCAN_PATTERNS:
        paths.update(root.glob(pattern))
    for path in sorted(paths):
        findings.extend(scan_file(path))
    findings.sort(key=lambda f: (SEVERITY[f.verdict], not f.exercises_h1, f.file))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, help="write the full report here")
    parser.add_argument(
        "--affected-only",
        action="store_true",
        help="print sites with no HAC, or an h=1-degenerate rule exercised at h=1",
    )
    args = parser.parse_args()

    findings = [f for f in scan_population() if f.verdict != NOT_A_TEST]
    exposed = [f for f in findings if f.exposed]

    counts: dict[str, int] = {}
    for f in findings:
        counts[f.verdict] = counts.get(f.verdict, 0) + 1

    if args.json:
        payload = {
            "scan_scope": list(SCAN_PATTERNS),
            "bug_class": (
                "local DM/HLN omits HAC via h-1 at h=1, plain iid variance, "
                "iid t-test fallback, or explicit zero bandwidth"
            ),
            "canonical_owner": "volpred.stats.model_evaluation.dm_test",
            "materiality_caveat": (
                "Exposure is structural, not a proven error. An h=1-degenerate rule is "
                "only material when the loss differential is autocorrelated; a NO_HAC "
                "site omits serial-covariance correction at every horizon. Confirming "
                "materiality requires a re-run and the differential's acf."
            ),
            "total_local_dm_functions": len(findings),
            "verdict_counts": counts,
            "structurally_exposed": len(exposed),
            "findings": [asdict(f) for f in findings],
        }
        args.json.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
        print(f"[audit] report written: {args.json}")

    shown = exposed if args.affected_only else findings
    print(f"[audit] local DM implementations found: {len(findings)}")
    for verdict, count in sorted(counts.items(), key=lambda kv: SEVERITY[kv[0]]):
        print(f"[audit]   {verdict:<24} {count}")
    print(
        f"[audit] STRUCTURALLY EXPOSED (NO_HAC or degenerate on h=1): {len(exposed)}"
        " -- materiality needs a re-run, see --json caveat"
    )

    for f in shown:
        flag = "EXPO" if f.exposed else "    "
        h1 = "h=1" if f.exercises_h1 else "   "
        print(f"{flag} [{f.verdict:<22}] {h1} {f.file}:{f.lineno} {f.function}()")
        if f.lag_expr:
            print(f"        lag = {f.lag_expr}")
        for note in f.notes:
            print(f"        -- {note}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
