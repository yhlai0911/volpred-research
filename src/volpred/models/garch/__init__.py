"""GARCH model implementations.

Importing this package auto-registers all GARCH variants
with the ModelRegistry.
"""

from .standard import ArchGARCH, CustomGARCH
from .egarch import ArchEGARCH, CustomEGARCH
from .gjr import ArchGJR, CustomGJR
from .experimental import GJRFloor, GJRAdaptive, GJRHAR, ComponentGARCH, GJRRange, GJROvernight
from .realized_garch import RealizedGARCH
from .garch_midas import GarchMidas, RegisteredGarchMidas

__all__ = [
    "ArchGARCH",
    "CustomGARCH",
    "ArchEGARCH",
    "CustomEGARCH",
    "ArchGJR",
    "CustomGJR",
    "GJRFloor",
    "GJRAdaptive",
    "RealizedGARCH",
    "GarchMidas",
    "RegisteredGarchMidas",
]
