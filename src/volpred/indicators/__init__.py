"""
Indicator Arena — prediction tracking module.

Submodules:
  registry  — load/manage indicator specs from storage/indicator_arena/registry.json
  signals   — append-only daily signal emission
  reviews   — append-only outcome review computation
  cli       — click CLI: emit / review-due / status
"""

from .registry import IndicatorSpec, load_registry, get_active
from .signals import append_signal, SignalPayload
from .reviews import compute_review, ReviewResult

__all__ = [
    "IndicatorSpec",
    "load_registry",
    "get_active",
    "append_signal",
    "SignalPayload",
    "compute_review",
    "ReviewResult",
]
