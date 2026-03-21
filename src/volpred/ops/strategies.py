from __future__ import annotations

from scripts.supabase_sync import set_strategy_active, sync_strategy_signal


def upsert_strategy_metadata(
    *,
    strategy_key: str,
    strategy_name: str,
    weights: dict,
    display_order: int = 0,
    is_active: bool = True,
    howto: str | None = None,
    description: str | None = None,
    color: str | None = None,
    articles: list | None = None,
    vix_level: float | None = None,
    sigma_ann: float | None = None,
) -> bool:
    return sync_strategy_signal(
        strategy_name,
        weights,
        vix_level=vix_level,
        sigma_ann=sigma_ann,
        display_order=display_order,
        is_active=is_active,
        strategy_key=strategy_key,
        howto=howto,
        description=description,
        color=color,
        articles=articles,
    )


def activate_strategy(identifier: str) -> bool:
    return set_strategy_active(identifier, True)


def deactivate_strategy(identifier: str) -> bool:
    return set_strategy_active(identifier, False)
