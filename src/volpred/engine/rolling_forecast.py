from __future__ import annotations

import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime

import numpy as np
import pandas as pd

from volpred.core.types import (
    ExperimentConfig,
    ExperimentResult,
    ForecastResult,
    WindowSpec,
)


def _single_window_task(args: tuple) -> tuple:
    """Worker function for parallel execution.

    Args:
        args: (model_class_name, model_config, train_data_dict, target_date_str, window_idx)

    Returns:
        (target_date_str, forecast_dict, fit_info_dict)

    NOTE: We pass serializable data (dict/str) instead of objects to avoid pickling issues.
    """
    model_class_name, model_config, train_data_dict, target_date_str, window_idx = args

    # Import and create model inside worker
    from volpred.models.registry import ModelRegistry

    # Ensure models are registered by importing the models package
    import volpred.models.garch  # noqa: F401 trigger registration
    import volpred.models.realized_vol  # noqa: F401

    model = ModelRegistry.create(model_class_name, **model_config)
    train_df = pd.DataFrame(train_data_dict)

    try:
        fit_info = model.fit(train_df)
        forecast = model.forecast(steps=1)
    except Exception as e:
        # Non-convergent fit: return NaN forecast
        forecast_dict = {
            "date": target_date_str,
            "point_forecast": float("nan"),
            "variance_forecast": float("nan"),
            "distribution_params": {},
            "model_name": model_class_name,
            "fit_info": {"error": str(e)},
        }
        return target_date_str, forecast_dict, {"error": str(e)}

    # Clamp variance to reasonable range (standard practice in quant finance)
    # Daily variance should be between ~1e-10 and ~0.1 (vol between 0.001% and 31%)
    var_forecast = forecast.variance_forecast
    if not np.isfinite(var_forecast) or var_forecast > 0.1 or var_forecast < 1e-10:
        # Use unconditional sample variance as fallback
        returns_col = train_df["returns"].values if "returns" in train_df.columns else train_df.iloc[:, 0].values
        var_forecast = float(np.var(returns_col))

    forecast_dict = {
        "date": target_date_str,
        "point_forecast": var_forecast**0.5,
        "variance_forecast": var_forecast,
        "distribution_params": forecast.distribution_params,
        "model_name": forecast.model_name,
        "fit_info": forecast.fit_info,
    }

    return target_date_str, forecast_dict, fit_info


class RollingForecastEngine:
    """Parallel rolling-window forecast engine.

    Splits an out-of-sample period into individual 1-step-ahead forecast tasks,
    each with its own training window, and optionally distributes them across
    multiple processes.
    """

    def __init__(self, n_workers: int | None = None) -> None:
        self.n_workers = n_workers

    def _build_windows(
        self,
        data: pd.DataFrame,
        window_size: int,
        oos_start: str,
        oos_end: str,
    ) -> list[WindowSpec]:
        """Build list of WindowSpec for rolling forecast."""
        oos_mask = (data.index >= pd.Timestamp(oos_start)) & (
            data.index <= pd.Timestamp(oos_end)
        )
        oos_indices = data.index[oos_mask]

        windows: list[WindowSpec] = []
        for target_date in oos_indices:
            target_loc = data.index.get_loc(target_date)
            start_loc = target_loc - window_size
            if start_loc < 0:
                continue
            windows.append(
                WindowSpec(
                    start=start_loc,
                    end=target_loc,  # exclusive: train on [start, end)
                    target_date=target_date.to_pydatetime(),
                )
            )
        return windows

    def run(
        self, config: ExperimentConfig, data: pd.DataFrame
    ) -> ExperimentResult:
        """Run rolling 1-step ahead forecast experiment.

        Args:
            config: ExperimentConfig with model name, params, window size,
                    OOS period.
            data: Full dataset with DatetimeIndex (must include both IS and OOS).

        Returns:
            ExperimentResult with all forecasts and timing.
        """
        windows = self._build_windows(
            data, config.window_size, config.oos_start, config.oos_end
        )

        if not windows:
            raise ValueError(
                "No valid windows for the given OOS period and window size"
            )

        n_workers = self.n_workers or min(os.cpu_count() or 1, len(windows), 8)

        # Prepare serializable args for each window
        tasks: list[tuple] = []
        for w in windows:
            train_df = data.iloc[w.start : w.end]
            tasks.append(
                (
                    config.model_name,
                    config.model_params,
                    train_df.to_dict(orient="list"),
                    w.target_date.isoformat(),
                    w.start,
                )
            )

        start_time = time.time()
        results: list[tuple] = []

        if n_workers <= 1:
            # Sequential execution (useful for debugging)
            for task in tasks:
                results.append(_single_window_task(task))
        else:
            with ProcessPoolExecutor(max_workers=n_workers) as executor:
                futures = [executor.submit(_single_window_task, t) for t in tasks]
                for future in as_completed(futures):
                    results.append(future.result())

        elapsed = time.time() - start_time

        # Sort by date and convert back to ForecastResult
        results.sort(key=lambda x: x[0])
        forecasts: list[ForecastResult] = []
        for date_str, fdict, _finfo in results:
            forecasts.append(
                ForecastResult(
                    date=datetime.fromisoformat(date_str),
                    point_forecast=fdict["point_forecast"],
                    variance_forecast=fdict["variance_forecast"],
                    distribution_params=fdict["distribution_params"],
                    model_name=fdict["model_name"],
                    fit_info=fdict["fit_info"],
                )
            )

        return ExperimentResult(
            experiment_id=config.experiment_id,
            config=config,
            forecasts=forecasts,
            metrics={},  # metrics computed separately by evaluator
            fit_time=elapsed,
            created_at=datetime.now(),
        )
