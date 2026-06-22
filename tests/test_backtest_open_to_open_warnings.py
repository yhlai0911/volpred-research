from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def test_record_bci_monthly_mom_records_valid_period() -> None:
    from backtest_open_to_open import _record_bci_monthly_mom  # type: ignore

    out: dict[tuple[int, int], float] = {}
    _record_bci_monthly_mom(out, "2023M01", 1.25)

    assert out == {(2023, 1): 1.25}


def test_record_bci_monthly_mom_warns_on_bad_period(capsys) -> None:
    from backtest_open_to_open import _record_bci_monthly_mom  # type: ignore

    out: dict[tuple[int, int], float] = {}
    _record_bci_monthly_mom(out, "2023Mbad", 1.25)
    output = capsys.readouterr().out

    assert out == {}
    assert "BCI period parse failed (2023Mbad)" in output
    assert "ValueError" in output
