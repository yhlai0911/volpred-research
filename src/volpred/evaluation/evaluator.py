from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats as sp_stats

from volpred.core.types import ExperimentResult
from volpred.evaluation.metrics import hmse, mae, mse, qlike, r2_log
from volpred.evaluation.statistical_tests import (
    christoffersen_test,
    compute_var_violations,
    kupiec_test,
)


class Evaluator:
    """Computes statistical and economic evaluation metrics for forecast experiments.

    Two evaluation dimensions:
    - Statistical: QLIKE, MSE, MAE, HMSE, R²-log (variance forecast accuracy)
    - Economic: VaR/ES backtesting with Kupiec, Christoffersen tests (risk management)
    """

    def evaluate(
        self,
        result: ExperimentResult,
        actual_data: pd.DataFrame,
        rv_column: str = "rv_proxy",
        var_alphas: list[float] | None = None,
    ) -> dict:
        """Compute all evaluation metrics including VaR/ES backtesting.

        Args:
            result: ExperimentResult with forecasts.
            actual_data: DataFrame with DatetimeIndex containing returns and RV proxy.
            rv_column: Column name for the realized-variance proxy.
            var_alphas: VaR confidence levels to test (default: [0.01, 0.05]).

        Returns:
            dict with statistical metrics and VaR/ES backtest results.
        """
        if var_alphas is None:
            var_alphas = [0.01, 0.05]

        # Auto-detect RV column if default not found
        if rv_column not in actual_data.columns:
            for candidate in ["rv_proxy", "rv_parkinson", "rv_garman_klass"]:
                if candidate in actual_data.columns:
                    rv_column = candidate
                    break

        # --- Align forecasts with actuals ---
        forecast_var = np.array([f.variance_forecast for f in result.forecasts])
        actual_var: list[float] = []
        actual_ret: list[float] = []
        valid_indices: list[int] = []

        for i, f in enumerate(result.forecasts):
            ts = pd.Timestamp(f.date).normalize()
            if ts in actual_data.index:
                if rv_column in actual_data.columns:
                    actual_var.append(float(actual_data.loc[ts, rv_column]))
                if "returns" in actual_data.columns:
                    actual_ret.append(float(actual_data.loc[ts, "returns"]))
                valid_indices.append(i)

        if not actual_var:
            # Fallback: squared returns as RV proxy
            actual_var = [r**2 for r in actual_ret] if actual_ret else []

        actual_var_arr = np.array(actual_var)
        actual_ret_arr = np.array(actual_ret) if actual_ret else np.array([])
        forecast_var_arr = forecast_var[valid_indices]

        # --- Statistical metrics (variance forecast accuracy) ---
        metrics: dict = {}
        if len(actual_var_arr) > 0 and len(forecast_var_arr) > 0:
            metrics.update({
                "mse": mse(actual_var_arr, forecast_var_arr),
                "mae": mae(actual_var_arr**0.5, forecast_var_arr**0.5),
                "qlike": qlike(actual_var_arr, forecast_var_arr),
                "hmse": hmse(actual_var_arr, forecast_var_arr),
                "r2_log": r2_log(actual_var_arr, forecast_var_arr),
                "n_forecasts": len(actual_var_arr),
                "mean_actual_var": float(np.mean(actual_var_arr)),
                "mean_forecast_var": float(np.mean(forecast_var_arr)),
            })
        else:
            metrics.update({
                "mse": float("nan"), "mae": float("nan"), "qlike": float("nan"),
                "hmse": float("nan"), "r2_log": 0.0,
                "n_forecasts": 0,
                "mean_actual_var": float("nan"),
                "mean_forecast_var": float("nan"),
            })

        # --- VaR/ES backtesting (economic significance) ---
        if len(actual_ret_arr) > 0 and len(forecast_var_arr) > 0:
            forecast_sigma = np.sqrt(np.maximum(forecast_var_arr, 1e-12))
            var_es_results = self._backtest_var_es(
                actual_ret_arr, forecast_sigma, var_alphas
            )
            metrics["var_es"] = var_es_results
        else:
            metrics["var_es"] = {}

        return metrics

    def _backtest_var_es(
        self,
        returns: np.ndarray,
        sigma: np.ndarray,
        alphas: list[float],
    ) -> dict:
        """Run VaR and ES backtesting at multiple confidence levels.

        Assumes conditional normality: VaR_alpha = -mu + z_alpha * sigma
        (mean return ≈ 0 for daily data).

        Returns dict keyed by alpha level with violation rates, Kupiec/Christoffersen
        test results, and ES diagnostics.
        """
        results = {}
        for alpha in alphas:
            z = sp_stats.norm.ppf(alpha)
            var_forecast = -z * sigma  # VaR is positive (loss)
            es_forecast = sigma * sp_stats.norm.pdf(z) / alpha  # ES (positive)

            # VaR violations
            violations = compute_var_violations(returns, var_forecast, alpha)
            n_viol = int(np.sum(violations))
            violation_rate = n_viol / len(returns) if len(returns) > 0 else 0.0

            # Kupiec unconditional coverage test
            kupiec = kupiec_test(violations, alpha)

            # Christoffersen independence test
            christo = christoffersen_test(violations)

            # ES backtest: average loss given violation vs expected ES
            viol_mask = violations.astype(bool)
            if np.any(viol_mask):
                avg_loss_given_viol = float(np.mean(np.abs(returns[viol_mask])))
                avg_es_given_viol = float(np.mean(es_forecast[viol_mask]))
                es_ratio = avg_loss_given_viol / avg_es_given_viol if avg_es_given_viol > 0 else float("nan")
            else:
                avg_loss_given_viol = float("nan")
                avg_es_given_viol = float("nan")
                es_ratio = float("nan")

            results[f"alpha_{alpha}"] = {
                "alpha": alpha,
                "n_violations": n_viol,
                "violation_rate": violation_rate,
                "expected_rate": alpha,
                "kupiec": kupiec,
                "christoffersen": christo,
                "avg_loss_given_violation": avg_loss_given_viol,
                "avg_es_forecast": avg_es_given_viol,
                "es_ratio": es_ratio,  # >1 means ES underestimates tail risk
                "var_mean": float(np.mean(var_forecast)),
                "es_mean": float(np.mean(es_forecast)),
            }

        return results

    def compare_models(
        self,
        results: list[tuple[ExperimentResult, dict]],
        actual_data: pd.DataFrame,
    ) -> dict:
        """Compare multiple models using DM test and composite ranking.

        Args:
            results: List of (ExperimentResult, metrics_dict) tuples.
            actual_data: DataFrame with returns and RV proxy.

        Returns:
            dict with pairwise DM tests and overall ranking.
        """
        from volpred.evaluation.statistical_tests import (
            composite_score,
            diebold_mariano_test,
        )

        n = len(results)
        if n < 2:
            return {"error": "Need at least 2 models to compare"}

        # Compute QLIKE losses per forecast for DM test
        rv_col = "rv_proxy"
        for candidate in ["rv_proxy", "rv_parkinson", "rv_garman_klass"]:
            if candidate in actual_data.columns:
                rv_col = candidate
                break

        model_losses: dict[str, np.ndarray] = {}
        for exp_result, _ in results:
            losses = []
            for f in exp_result.forecasts:
                ts = pd.Timestamp(f.date).normalize()
                if ts in actual_data.index and rv_col in actual_data.columns:
                    rv = float(actual_data.loc[ts, rv_col])
                    pred = max(f.variance_forecast, 1e-12)
                    losses.append(rv / pred + np.log(pred))  # QLIKE loss
            model_losses[exp_result.experiment_id] = np.array(losses)

        # Pairwise DM tests
        dm_results = {}
        ids = [r[0].experiment_id for r in results]
        for i in range(n):
            for j in range(i + 1, n):
                id_i, id_j = ids[i], ids[j]
                if id_i in model_losses and id_j in model_losses:
                    min_len = min(len(model_losses[id_i]), len(model_losses[id_j]))
                    if min_len > 0:
                        dm = diebold_mariano_test(
                            model_losses[id_i][:min_len],
                            model_losses[id_j][:min_len],
                        )
                        dm_results[f"{id_i}_vs_{id_j}"] = dm

        # Ranking by composite score
        ranking = []
        for exp_result, metrics in results:
            score = composite_score(metrics)
            ranking.append({
                "experiment_id": exp_result.experiment_id,
                "model_name": exp_result.config.model_name,
                "qlike": metrics.get("qlike", float("nan")),
                "composite_score": score,
                "var_pass": self._check_var_pass(metrics),
            })
        ranking.sort(key=lambda x: x.get("qlike", float("inf")))

        return {
            "ranking": ranking,
            "dm_tests": dm_results,
        }

    @staticmethod
    def _check_var_pass(metrics: dict) -> dict:
        """Check if VaR backtests pass at each alpha level."""
        var_es = metrics.get("var_es", {})
        results = {}
        for key, val in var_es.items():
            if isinstance(val, dict):
                kupiec_pass = val.get("kupiec", {}).get("conclusion") == "fail_to_reject"
                christo_pass = val.get("christoffersen", {}).get("conclusion") == "independent"
                results[key] = {
                    "kupiec_pass": kupiec_pass,
                    "christoffersen_pass": christo_pass,
                    "both_pass": kupiec_pass and christo_pass,
                }
        return results
