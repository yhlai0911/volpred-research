"""Custom exceptions for the volpred system."""


class VolpredError(Exception):
    """Base exception for all volpred errors."""


class ModelFitError(VolpredError):
    """Raised when model fitting fails (non-convergence, numerical issues, etc.)."""


class DataError(VolpredError):
    """Raised for data-related problems (missing columns, insufficient length, etc.)."""


class ExperimentError(VolpredError):
    """Raised when an experiment fails to complete."""
