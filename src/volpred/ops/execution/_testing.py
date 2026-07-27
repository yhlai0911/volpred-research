"""Test-only adapters for the Provider Execution external seam."""

from . import _InMemoryProviderExecutionStore


InMemoryProviderExecutionStore = _InMemoryProviderExecutionStore

__all__ = ["InMemoryProviderExecutionStore"]
