"""First-party analytics contracts with privacy-safe lifecycle controls."""

from .privacy import (
    ANALYTICS_EVENT_DICTIONARY,
    AnalyticsEvent,
    AnalyticsEventDefinition,
    AnalyticsEventReceipt,
    AnalyticsIdentityMergeReceipt,
    AnalyticsPrivacyActionReceipt,
    AnalyticsPrivacyReadback,
    AnalyticsPrivacyTracer,
    InMemoryAnalyticsStore,
)
from .postgres import PostgresAnalyticsStore

__all__ = [
    "ANALYTICS_EVENT_DICTIONARY",
    "AnalyticsEvent",
    "AnalyticsEventDefinition",
    "AnalyticsEventReceipt",
    "AnalyticsIdentityMergeReceipt",
    "AnalyticsPrivacyActionReceipt",
    "AnalyticsPrivacyReadback",
    "AnalyticsPrivacyTracer",
    "InMemoryAnalyticsStore",
    "PostgresAnalyticsStore",
]
