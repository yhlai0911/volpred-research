"""Abstract base class for all volatility models."""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

import pandas as pd
from scipy.stats import norm

from volpred.core.types import DataRequirement, ForecastResult, ModelState


class BaseVolatilityModel(ABC):
    """Interface every volatility model in the system must satisfy."""

    # ------------------------------------------------------------------
    # Required overrides
    # ------------------------------------------------------------------

    @abstractmethod
    def get_name(self) -> str:
        """Return a human-readable model name."""
        ...

    @abstractmethod
    def get_data_requirement(self) -> DataRequirement:
        """Declare what data columns / frequency / length the model needs."""
        ...

    @abstractmethod
    def fit(self, data: pd.DataFrame) -> dict:
        """Fit the model to *data*.

        Returns
        -------
        dict
            Fit information: convergence flag, log-likelihood, etc.
        """
        ...

    @abstractmethod
    def forecast(self, steps: int = 1) -> ForecastResult:
        """Produce a volatility forecast *steps* ahead.

        Must be called after :meth:`fit`.
        """
        ...

    # ------------------------------------------------------------------
    # Default implementations (override when needed)
    # ------------------------------------------------------------------

    def compute_var_es(self, alpha: float = 0.05) -> dict:
        """Compute Value-at-Risk and Expected Shortfall.

        The default implementation assumes a zero-mean normal distribution
        with scale equal to the one-step-ahead forecast standard deviation.

        Parameters
        ----------
        alpha : float
            Tail probability (e.g. 0.05 for 95 % VaR).

        Returns
        -------
        dict
            Keys: VaR, ES, alpha, sigma.
        """
        fc = self.forecast(steps=1)
        sigma = fc.variance_forecast ** 0.5
        z = norm.ppf(alpha)
        var = -sigma * z
        es = sigma * norm.pdf(z) / alpha
        return {"VaR": var, "ES": es, "alpha": alpha, "sigma": sigma}

    def get_tunable_params(self) -> dict:
        """Return tuneable hyper-parameters for the orchestrator.

        Returns
        -------
        dict
            ``{param_name: {"type": ..., "range": ..., "current": ...}}``
        """
        return {}

    def get_state(self) -> ModelState:
        """Serialise the current fitted state."""
        return ModelState(
            model_name=self.get_name(),
            params={},
            config={},
            timestamp=datetime.now(),
        )

    def load_state(self, state: ModelState) -> None:
        """Restore a previously serialised state."""
        ...
