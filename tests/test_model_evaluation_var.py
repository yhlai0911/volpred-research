from __future__ import annotations

import numpy as np
import pytest

from volpred.stats.model_evaluation import var_backtest


def test_student_t_var_uses_unit_variance_scaling() -> None:
    # df=5 raw t 1% quantile is below -3.3, while unit-variance scaled t is
    # around -2.6. A -3.0 return should breach only under the standardized form.
    result = var_backtest(
        returns=np.array([-3.0]),
        sigma_forecasts=np.array([1.0]),
        alpha=0.01,
        distribution="t",
        df=5,
    )

    assert result["n_violations"] == 1


def test_student_t_var_rejects_non_finite_variance_df() -> None:
    with pytest.raises(ValueError, match="df > 2"):
        var_backtest(
            returns=np.array([-3.0]),
            sigma_forecasts=np.array([1.0]),
            alpha=0.01,
            distribution="t",
            df=2,
        )
