"""Canonical drawdown comparison — the one place raw MDD is allowed to be compared.

WHY THIS MODULE EXISTS
----------------------
Raw max drawdown is not comparable across two return series that run at different
exposure.  A strategy holding a quarter of the benchmark's risk shows a shallower
drawdown for purely arithmetic reasons; that is "took less risk", not "timed risk
well".  Anyone can reproduce the entire "benefit" by scaling their position down.

The bug class this guards (see docs/governance/2026-07/raw_mdd_claim_class_sweep.md):

  - K1702 §5.4: on the factor zoo, raw MDD improved for 5/6 factors.  Per unit of
    realized volatility, only 1/6.  The "drawdown benefit" was mostly lower exposure.
  - K1265b: on SPY VIX-managed portfolios, K1265's headline "50-62% MDD reduction"
    shrinks to a 9.8-22.1pp gap once measured against a benchmark carrying the SAME
    realized volatility, and no spec survives Holm correction against a
    circular-shift null.

TWO THINGS THIS MODULE INSISTS ON
---------------------------------
1. If the two series' realized volatilities differ by more than
   ``VOL_MISMATCH_THRESHOLD`` (20%), a raw-MDD comparison is NOT reportable on its
   own.  ``compare_max_drawdown`` computes the scale-invariant companions for you
   and flags the comparison; ``assert_drawdown_comparison_is_fair`` raises.

2. Calmar is NOT sufficient corroboration.  It was tempting to accept it (both its
   numerator and denominator scale with leverage), and an early pass of the class
   sweep did — which is exactly how K1265 got waved through as "OK" despite being
   the entry the sweep was chartered to re-examine.  Calmar answers "return per unit
   of drawdown"; it does not answer "is this drawdown shallow because you timed risk,
   or because you took less of it".

WHAT COUNTS AS HONEST CORROBORATION
-----------------------------------
``mdd_per_annual_vol``
    MDD divided by realized annualized volatility.  Note this is a *normalisation*,
    not an invariant: wealth compounds, so MDD is not homogeneous of degree 1 in
    leverage, and rescaling the same path does move the ratio somewhat.  Useful, but
    not decisive on its own.

``exposure_matched_gap``
    MDD(strategy) - MDD(benchmark rescaled by a CONSTANT lambda so that it carries
    the strategy's realized volatility).  The rescaled benchmark has identical
    realized risk and zero timing ability.  A pure constant de-levering scores exactly
    0 here.

    *** A POSITIVE GAP IS NECESSARY BUT NOT SUFFICIENT.  READ THIS BEFORE USING IT. ***

    It does NOT establish timing skill.  Matching realized volatility matches only the
    second moment; it does not neutralise a DISPERSED weight distribution.  A strategy
    whose weights swing widely earns a positive gap even when its timing is exactly
    BACKWARDS -- dispersed weights concentrate risk into bursts, and a bursty path
    bleeds a shallower peak-to-trough drawdown than a constant-volatility path of the
    same unconditional volatility.  Drawdowns are built by sustained bleeding, not by
    isolated spikes.  Pinned as a test:
    ``scripts/tests/test_mdd_scale_artifact_ratchet.py::
    test_a_positive_exposure_matched_gap_is_not_by_itself_evidence_of_timing``.

    So compare the gap against ITS OWN null, not against zero.  The null is the same
    weight path with its phase randomised (circular shifts): that preserves the weight
    values and their persistence exactly, and destroys only the alignment with returns.
    Reference implementation: ``experiments/k1265b``.

    Also: lambda uses full-sample realized volatility, so the matched benchmark is a
    retrospective attribution device, not a tradeable benchmark.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

TRADING_DAYS = 252

#: Two series whose realized vols differ by more than this cannot be compared on raw MDD.
VOL_MISMATCH_THRESHOLD = 0.20


class RawDrawdownComparisonError(AssertionError):
    """Raised when a raw-MDD comparison is made across materially different exposure."""


def max_drawdown(returns) -> float:
    """Wealth-based max drawdown, measured from an initial wealth of 1.0.

    The leading 1.0 is not decoration: without it a first-period loss is invisible to
    the running maximum and the drawdown is understated.  Returns nan if wealth goes
    non-positive, where the ratio is meaningless.
    """
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    if r.size == 0:
        return float("nan")
    if (r <= -1.0).any():
        return float("nan")
    wealth = np.concatenate(([1.0], np.cumprod(1.0 + r)))
    return float((wealth / np.maximum.accumulate(wealth) - 1.0).min())


def annualized_volatility(returns, periods_per_year: int = TRADING_DAYS) -> float:
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    if r.size < 2:
        return float("nan")
    return float(np.std(r, ddof=1) * np.sqrt(periods_per_year))


@dataclass
class DrawdownComparison:
    """Result of comparing two return series on drawdown, honestly."""

    strategy_mdd: float
    benchmark_mdd: float
    strategy_vol: float
    benchmark_vol: float
    vol_ratio: float
    #: |vol_ratio - 1| > VOL_MISMATCH_THRESHOLD -> raw MDD is not reportable alone
    exposure_mismatch: bool
    strategy_mdd_per_vol: float
    benchmark_mdd_per_vol: float
    #: lambda that makes the benchmark carry the strategy's realized volatility
    matched_lambda: float
    matched_benchmark_mdd: float
    #: MDD(strategy) - MDD(matched benchmark). > 0 means shallower than a same-risk
    #: constant-leverage series, i.e. not explained by de-levering alone.
    exposure_matched_gap: float
    raw_mdd_improvement: float
    warnings: list[str] = field(default_factory=list)

    @property
    def raw_mdd_improvement_is_reportable_alone(self) -> bool:
        return not self.exposure_mismatch

    def summary(self) -> str:
        head = (
            f"raw MDD {self.strategy_mdd:.3f} vs {self.benchmark_mdd:.3f} "
            f"(vol {self.strategy_vol:.3f} vs {self.benchmark_vol:.3f}, ratio {self.vol_ratio:.2f})"
        )
        if not self.exposure_mismatch:
            return head + " — exposures comparable; raw MDD is a fair comparison."
        return (
            head
            + f"\n  EXPOSURE MISMATCH: raw MDD is NOT comparable alone."
            + f"\n  MDD/vol       : {self.strategy_mdd_per_vol:.3f} vs {self.benchmark_mdd_per_vol:.3f}"
            + f"\n  same-risk gap : {self.exposure_matched_gap * 100:+.1f}pp "
            + f"(benchmark rescaled by lambda={self.matched_lambda:.3f})"
        )


def compare_max_drawdown(
    strategy_returns,
    benchmark_returns,
    periods_per_year: int = TRADING_DAYS,
) -> DrawdownComparison:
    """Compare two return series on drawdown, always emitting the scale-invariant companions.

    The two series must be aligned and of equal length — comparing drawdowns computed
    over different samples is a separate way to be wrong.
    """
    s = np.asarray(strategy_returns, dtype=float)
    b = np.asarray(benchmark_returns, dtype=float)
    if s.shape != b.shape:
        raise ValueError(
            f"strategy and benchmark must be aligned and equal length, got {s.shape} vs {b.shape}"
        )
    ok = np.isfinite(s) & np.isfinite(b)
    s, b = s[ok], b[ok]

    s_vol = annualized_volatility(s, periods_per_year)
    b_vol = annualized_volatility(b, periods_per_year)
    s_mdd = max_drawdown(s)
    b_mdd = max_drawdown(b)

    vol_ratio = s_vol / b_vol if b_vol > 0 else float("nan")
    mismatch = bool(np.isfinite(vol_ratio) and abs(vol_ratio - 1.0) > VOL_MISMATCH_THRESHOLD)

    lam = vol_ratio if np.isfinite(vol_ratio) else float("nan")
    matched_mdd = max_drawdown(lam * b) if np.isfinite(lam) else float("nan")

    warnings: list[str] = []
    if mismatch:
        warnings.append(
            f"realized volatilities differ by {abs(vol_ratio - 1.0):.0%} "
            f"(> {VOL_MISMATCH_THRESHOLD:.0%}): raw max drawdown is NOT comparable on its own. "
            f"Report exposure_matched_gap, and do not describe the raw MDD difference as "
            f"evidence of risk-management skill."
        )

    return DrawdownComparison(
        strategy_mdd=s_mdd,
        benchmark_mdd=b_mdd,
        strategy_vol=s_vol,
        benchmark_vol=b_vol,
        vol_ratio=vol_ratio,
        exposure_mismatch=mismatch,
        strategy_mdd_per_vol=s_mdd / s_vol if s_vol > 0 else float("nan"),
        benchmark_mdd_per_vol=b_mdd / b_vol if b_vol > 0 else float("nan"),
        matched_lambda=lam,
        matched_benchmark_mdd=matched_mdd,
        exposure_matched_gap=s_mdd - matched_mdd,
        raw_mdd_improvement=s_mdd - b_mdd,
        warnings=warnings,
    )


def assert_drawdown_comparison_is_fair(
    strategy_returns,
    benchmark_returns,
    periods_per_year: int = TRADING_DAYS,
) -> DrawdownComparison:
    """Like :func:`compare_max_drawdown`, but refuses to return on an unfair comparison.

    Use this at the point where a raw-MDD improvement is about to become a CLAIM.
    """
    cmp = compare_max_drawdown(strategy_returns, benchmark_returns, periods_per_year)
    if cmp.exposure_mismatch:
        raise RawDrawdownComparisonError(
            "raw max-drawdown comparison across materially different exposure.\n"
            + cmp.summary()
            + "\nUse compare_max_drawdown() and report exposure_matched_gap instead."
        )
    return cmp
