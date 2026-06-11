"""
Indicator Arena — prediction tracking module.

Submodules:
  registry  — load/manage indicator specs from storage/indicator_arena/registry.json
  signals   — append-only daily signal emission
  reviews   — append-only outcome review computation
  supabase_sync — local canonical -> Supabase projection
  cli       — click CLI: emit / review-due / status / sync-supabase
"""

from .registry import IndicatorSpec, load_registry, get_active
from .signals import append_signal, SignalPayload
from .reviews import compute_review, ReviewResult
from .supabase_sync import sync_indicator_arena

__all__ = [
    "IndicatorSpec",
    "load_registry",
    "get_active",
    "append_signal",
    "SignalPayload",
    "compute_review",
    "ReviewResult",
    "sync_indicator_arena",
]
