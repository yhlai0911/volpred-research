from __future__ import annotations

import json

from volpred.cli import _parse_json_input


def test_parse_json_input_handles_long_inline_json_not_as_path() -> None:
    payload = {
        "experiment_refs": ["K1371"],
        "cluster_waiver": (
            "pending daily_article task K1371; angle focuses on why a plausible "
            "financial-sector lead fails to produce usable OOS volatility "
            "forecasts for TSMC, distinct from prior Taiwan volatility or "
            "event-study articles"
        ),
    }
    raw = json.dumps(payload, ensure_ascii=False)

    parsed = _parse_json_input(raw, default={})

    assert parsed == payload
