from __future__ import annotations

import numpy as np
import pytest
from scipy import stats

import volpred.stats.model_evaluation as model_evaluation
from volpred.stats.model_evaluation import unit_variance_student_t_ppf, var_backtest


def test_unit_variance_student_t_ppf_scales_raw_t_quantile() -> None:
    raw = float(stats.t.ppf(0.01, df=5))
    scaled = unit_variance_student_t_ppf(0.01, df=5)

    assert scaled == pytest.approx(raw * np.sqrt((5 - 2) / 5))
    assert abs(scaled) < abs(raw)


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


def test_christoffersen_failure_is_observable_and_not_trinity_pass(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail_transition_count(*_args: object, **_kwargs: object) -> int:
        raise RuntimeError("transition tally failed")

    monkeypatch.setattr(model_evaluation.np, "sum", fail_transition_count)

    result = var_backtest(
        returns=np.array([0.01, -0.02, 0.03, -0.04]),
        sigma_forecasts=np.ones(4) * 0.01,
        alpha=0.5,
    )

    captured = capsys.readouterr()
    christoffersen = result["christoffersen"]
    assert "[model_evaluation] WARN christoffersen independence test failed" in captured.err
    assert christoffersen["computed"] is False
    assert christoffersen["pass"] is False
    assert christoffersen["p_value"] is None
    assert result["trinity_pass"] is False
    assert result["warnings"]
