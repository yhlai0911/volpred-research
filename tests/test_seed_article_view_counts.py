"""Tests for the article view-count display seeding (boss email-12160, 2026-07-18).

The boss's constraint was explicit: seeds are random and capped (1000 in v1, 1417
after email-12163), but "排序不能變" — the displayed ranking must equal the
true-impression ranking.
That is the invariant these tests pin down, because it is the one that silently
breaks if someone later "improves" the seed distribution.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

pytest.importorskip("supabase_sync", reason="requires repo scripts on path")

from seed_article_view_counts import (  # noqa: E402
    MAX_SEED,
    MIN_SEED,
    assign_seeds,
    displayed_views,
    rank_articles,
)


# ── the invariant the boss actually asked for ──────────────────────────────


@pytest.mark.parametrize("n", [0, 1, 2, 5, 100, 1000, 1634, 3000])
def test_seeds_are_non_increasing_so_ranking_is_preserved(n):
    seeds = assign_seeds(n, random.Random(42))
    assert len(seeds) == n
    assert all(a >= b for a, b in zip(seeds, seeds[1:])), "seed ordering inverted"


@pytest.mark.parametrize("n", [1, 50, 1634, 3000])
def test_seeds_respect_the_ceiling_and_stay_positive(n):
    seeds = assign_seeds(n, random.Random(7))
    assert all(MIN_SEED <= s <= MAX_SEED for s in seeds)


def test_ceiling_is_not_a_round_number():
    """Boss email-12163: a visible maximum of exactly 1000 reads as hand-picked."""
    assert MAX_SEED == 1417
    assert MAX_SEED % 100 != 0


@pytest.mark.parametrize("cap", [40, 240, 1417])
def test_assign_seeds_honours_a_lower_ceiling(cap):
    """A caller-supplied ceiling is respected and the ordering guarantee survives it."""
    seeds = assign_seeds(30, random.Random(11), max_seed=cap, tail_target=min(12, cap))
    assert all(MIN_SEED <= s <= cap for s in seeds)
    assert all(a >= b for a, b in zip(seeds, seeds[1:]))


def test_end_to_end_display_ranking_matches_true_ranking():
    """The property that matters: sort by displayed, get the same order as by real."""
    rng = random.Random(2026)
    real = {f"a{i}": rng.randint(0, 60) for i in range(300)}
    articles = [{"id": k, "published_at": f"2026-01-{i % 28 + 1:02d}"} for i, k in enumerate(real)]

    ranked = rank_articles(articles, real)
    seeds = assign_seeds(len(ranked), random.Random(1))

    for (a, seed), (b, next_seed) in zip(zip(ranked, seeds), list(zip(ranked, seeds))[1:]):
        assert real[a["id"]] >= real[b["id"]], "rank_articles did not sort by true views"
        assert seed >= next_seed, "displayed order contradicts true order"


def test_seed_distribution_is_long_tailed_not_piled_at_the_ceiling():
    """Regression guard for the first implementation (uniform draw + sort).

    That version produced 1000, 1000, 999, 999, 998 for the top five of 1,634
    articles — a giveaway. A long tail must actually spread out.
    """
    seeds = assign_seeds(1634, random.Random(20260718))
    assert seeds[0] > seeds[4] + 100, "top of the distribution is piled up at the ceiling"
    assert seeds[-1] < 60, "tail never decays"
    assert len(set(seeds)) > 100, "too few distinct values to look like real traffic"


# ── the display formula ────────────────────────────────────────────────────


def test_displayed_is_seed_plus_real_growth_since_seeding():
    vd = {"seed": 742, "baseline_real": 38}
    assert displayed_views(vd, 38) == 742          # no new views yet
    assert displayed_views(vd, 45) == 749          # +7 real views counted for real
    assert displayed_views(vd, 30) == 742          # impressions deleted -> never goes backwards


def test_article_published_after_the_freeze_shows_its_real_count():
    """Boss email-12167: 「只有第一次需要隨機 之後就是按照正常的瀏覽數據去累積」.

    No second randomisation. An article with no frozen seed was counted honestly
    from its first impression, so it displays that count — 0 included.
    """
    assert displayed_views(None, 12) == 12
    assert displayed_views({}, 12) == 12
    assert displayed_views(None, 0) == 0


def test_rank_tiebreak_is_deterministic():
    real = {"x": 5, "y": 5, "z": 5}
    articles = [
        {"id": "z", "published_at": "2026-03-01"},
        {"id": "x", "published_at": "2026-01-01"},
        {"id": "y", "published_at": "2026-02-01"},
    ]
    assert [a["id"] for a in rank_articles(articles, real)] == ["x", "y", "z"]
    assert [a["id"] for a in rank_articles(list(reversed(articles)), real)] == ["x", "y", "z"]


def test_articles_with_no_impressions_rank_last_but_still_get_seeded():
    real = {"hot": 10}
    articles = [{"id": "cold", "published_at": "2026-01-01"}, {"id": "hot", "published_at": "2026-01-02"}]
    ranked = rank_articles(articles, real)
    assert [a["id"] for a in ranked] == ["hot", "cold"]
    seeds = assign_seeds(len(ranked), random.Random(3))
    assert all(s >= MIN_SEED for s in seeds), "zero-view articles must still show a number"
