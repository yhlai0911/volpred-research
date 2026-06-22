from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def test_oos_gjr_warns_when_refit_fails(monkeypatch, capsys) -> None:
    import validate_garch_midas_cross_asset as mod  # type: ignore

    fake_arch = ModuleType("arch")

    def _raise_fit_failure(*args, **kwargs):
        raise RuntimeError("arch unavailable")

    fake_arch.arch_model = _raise_fit_failure
    monkeypatch.setitem(sys.modules, "arch", fake_arch)

    returns = np.array([0.001, -0.002, 0.003, -0.001, 0.002, 0.001, -0.001])
    out = mod.oos_gjr(returns, oos_start_idx=4, refit_every=1)
    output = capsys.readouterr().out

    assert len(out) == 3
    assert np.isfinite(out).all()
    assert "GJR refit failed" in output
    assert "RuntimeError: arch unavailable" in output
