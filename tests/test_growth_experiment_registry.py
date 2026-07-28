from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from click.testing import CliRunner

from volpred import cli as cli_module
from volpred.cli import cli
from volpred.ops.growth_experiments import GrowthExperimentRegistry


class FakeRpc:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.receipts: dict[str, dict[str, object]] = {}

    def call(
        self,
        function: str,
        payload: dict[str, object],
    ) -> object:
        self.calls.append((function, payload))
        if function == "read_volpred_growth_command_receipt":
            command_id = str(payload["p_command_id"])
            stored = self.receipts.get(command_id)
            if stored is None:
                return None
            return {
                "contract": "growth-command-receipt-read.v1",
                "command_id": command_id,
                "action": stored["action"],
                "request_payload": stored["request_payload"],
                "receipt": stored["receipt"],
            }
        if function == "read_volpred_growth_experiment":
            return {
                "contract": "growth-experiment-read.v1",
                "experiment_id": "article-share-cta-copy-v1",
                "status": "preregistered",
            }
        receipt = {
            "contract": "growth-command-receipt.v1",
            "command_id": payload["p_command_id"],
            "experiment_id": "article-share-cta-copy-v1",
            "action": payload["p_action"],
            "status": {
                "preregister": "preregistered",
                "activate": "active",
                "stop": "observing",
                "close": "closed",
            }[str(payload["p_action"])],
            "duplicate": False,
            "applied_at": payload["p_now"],
        }
        self.receipts[str(payload["p_command_id"])] = {
            "action": payload["p_action"],
            "request_payload": payload["p_payload"],
            "receipt": receipt,
        }
        return receipt


def _registry(
    *,
    now: datetime | None = None,
) -> tuple[GrowthExperimentRegistry, FakeRpc]:
    rpc = FakeRpc()
    return GrowthExperimentRegistry(
        rpc=rpc,
        clock=(
            (lambda: now)
            if now is not None
            else (lambda: datetime.now(UTC))
        ),
    ), rpc


def test_preregister_uses_canonical_digest_and_receipt_contract() -> None:
    registry, rpc = _registry()
    spec = {
        "status": "preregistered",
        "experiment_id": "article-share-cta-copy-v1",
        "preregistered_at": "2026-07-29T00:00:00+00:00",
    }

    receipt = registry.preregister(
        command_id="growth-preregister-v1",
        spec=spec,
    )

    encoded = json.dumps(
        spec,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    assert receipt["status"] == "preregistered"
    assert rpc.calls == [
        (
            "command_volpred_growth_experiment",
            {
                "p_command_id": "growth-preregister-v1",
                "p_action": "preregister",
                "p_payload": spec,
                "p_request_digest": (
                    "\\x" + hashlib.sha256(encoded).hexdigest()
                ),
                "p_now": "2026-07-29T00:00:00+00:00",
            },
        )
    ]


def test_preregister_template_materializes_command_time_without_backdating() -> None:
    now = datetime(2026, 7, 29, 5, 30, tzinfo=UTC)
    registry, rpc = _registry(now=now)
    template = {
        "schema_version": "growth-experiment.v1",
        "status": "preregistered",
        "experiment_id": "article-share-cta-copy-v1",
        "window": {
            "starts_at": "2026-07-30T00:00:00+00:00",
            "ends_at": "2026-08-06T00:00:00+00:00",
        },
    }

    receipt = registry.preregister_template(
        command_id="growth-preregister-template-v1",
        template=template,
    )

    assert rpc.calls[0][0] == "read_volpred_growth_command_receipt"
    materialized = rpc.calls[1][1]["p_payload"]
    assert isinstance(materialized, dict)
    assert materialized["preregistered_at"] == "2026-07-29T05:30:00Z"
    assert rpc.calls[1][1]["p_now"] == "2026-07-29T05:30:00Z"
    assert receipt["applied_at"] == "2026-07-29T05:30:00Z"
    assert "preregistered_at" not in template

    with pytest.raises(ValueError, match="must not contain preregistered_at"):
        registry.preregister_template(
            command_id="growth-preregister-template-stale",
            template={
                **template,
                "preregistered_at": "2026-07-28T00:00:00+00:00",
            },
        )


def test_preregister_template_recovers_ambiguous_success_by_command_id() -> None:
    first_now = datetime(2026, 7, 29, 5, 30, tzinfo=UTC)
    rpc = FakeRpc()
    template = {
        "schema_version": "growth-experiment.v1",
        "status": "preregistered",
        "experiment_id": "article-share-cta-copy-v1",
        "window": {
            "starts_at": "2026-07-30T00:00:00+00:00",
            "ends_at": "2026-08-06T00:00:00+00:00",
        },
    }
    first = GrowthExperimentRegistry(
        rpc=rpc,
        clock=lambda: first_now,
    ).preregister_template(
        command_id="growth-preregister-ambiguous-v1",
        template=template,
    )
    later = GrowthExperimentRegistry(
        rpc=rpc,
        clock=lambda: first_now.replace(hour=7),
    ).preregister_template(
        command_id="growth-preregister-ambiguous-v1",
        template=template,
    )

    command_calls = [
        call
        for call in rpc.calls
        if call[0] == "command_volpred_growth_experiment"
    ]
    assert len(command_calls) == 1
    assert later == {**first, "duplicate": True}


def test_lifecycle_commands_are_narrow_and_read_back() -> None:
    registry, rpc = _registry()

    registry.activate(
        command_id="growth-activate-v1",
        experiment_id="article-share-cta-copy-v1",
        observed_at="2026-07-30T00:00:00+00:00",
    )
    registry.stop(
        command_id="growth-stop-v1",
        experiment_id="article-share-cta-copy-v1",
        reason="window_ended",
        observed_at="2026-08-06T00:00:00+00:00",
    )
    registry.close(
        command_id="growth-close-v1",
        experiment_id="article-share-cta-copy-v1",
        reason="window_ended",
        observed_at="2026-08-06T00:00:00+00:00",
    )
    snapshot = registry.read("article-share-cta-copy-v1")

    assert [call[0] for call in rpc.calls] == [
        "command_volpred_growth_experiment",
        "command_volpred_growth_experiment",
        "command_volpred_growth_experiment",
        "read_volpred_growth_experiment",
    ]
    assert rpc.calls[0][1]["p_payload"] == {
        "experiment_id": "article-share-cta-copy-v1"
    }
    assert rpc.calls[1][1]["p_payload"] == {
        "experiment_id": "article-share-cta-copy-v1",
        "reason": "window_ended",
    }
    assert rpc.calls[2][1]["p_payload"] == {
        "experiment_id": "article-share-cta-copy-v1",
        "reason": "window_ended",
    }
    assert snapshot["contract"] == "growth-experiment-read.v1"


def test_registry_rejects_untrusted_ids_reasons_and_receipts() -> None:
    registry, _ = _registry()
    with pytest.raises(ValueError, match="experiment_id"):
        registry.read("bad id")
    with pytest.raises(ValueError, match="reason"):
        registry.close(
            command_id="growth-close-v1",
            experiment_id="article-share-cta-copy-v1",
            reason="declare_winner",
            observed_at="2026-08-06T00:00:00+00:00",
        )

    invalid = GrowthExperimentRegistry(
        rpc=lambda _function, _payload: {"status": "active"}
    )
    with pytest.raises(RuntimeError, match="receipt"):
        invalid.activate(
            command_id="growth-activate-v1",
            experiment_id="article-share-cta-copy-v1",
            observed_at="2026-07-30T00:00:00+00:00",
        )


def test_ops_cli_exposes_full_lifecycle_and_read(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    registry, rpc = _registry()
    monkeypatch.setattr(
        cli_module,
        "_growth_registry",
        lambda: registry,
    )
    spec = {
        "status": "preregistered",
        "experiment_id": "article-share-cta-copy-v1",
        "preregistered_at": "2026-07-29T00:00:00+00:00",
    }
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    runner = CliRunner()

    commands = [
        [
            "ops",
            "growth-experiment",
            "stop",
            "--experiment-id",
            "article-share-cta-copy-v1",
            "--command-id",
            "growth-stop-v1",
            "--reason",
            "window_ended",
            "--observed-at",
            "2026-08-06T00:00:00+00:00",
        ],
        [
            "ops",
            "growth-experiment",
            "preregister",
            "--spec-json",
            str(spec_path),
            "--command-id",
            "growth-preregister-v1",
        ],
        [
            "ops",
            "growth-experiment",
            "activate",
            "--experiment-id",
            "article-share-cta-copy-v1",
            "--command-id",
            "growth-activate-v1",
            "--observed-at",
            "2026-07-30T00:00:00+00:00",
        ],
        [
            "ops",
            "growth-experiment",
            "close",
            "--experiment-id",
            "article-share-cta-copy-v1",
            "--command-id",
            "growth-close-v1",
            "--reason",
            "window_ended",
            "--observed-at",
            "2026-08-06T00:00:00+00:00",
        ],
        [
            "ops",
            "growth-experiment",
            "read",
            "--experiment-id",
            "article-share-cta-copy-v1",
        ],
    ]
    for command in commands:
        result = runner.invoke(cli, command)
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["contract"] in {
            "growth-command-receipt.v1",
            "growth-experiment-read.v1",
        }
    assert len(rpc.calls) == 5


def test_ops_cli_preregister_template_uses_runtime_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 7, 29, 5, 30, tzinfo=UTC)
    registry, rpc = _registry(now=now)
    monkeypatch.setattr(cli_module, "_growth_registry", lambda: registry)
    template_path = (
        Path(__file__).parents[1]
        / "config"
        / "growth_experiments"
        / "article-share-cta-copy-v1.template.json"
    )

    result = CliRunner().invoke(
        cli,
        [
            "ops",
            "growth-experiment",
            "preregister-template",
            "--template-json",
            str(template_path),
            "--command-id",
            "growth-preregister-template-v1",
        ],
    )

    assert result.exit_code == 0, result.output
    assert rpc.calls[1][1]["p_now"] == "2026-07-29T05:30:00Z"
    materialized = rpc.calls[1][1]["p_payload"]
    assert isinstance(materialized, dict)
    assert materialized["hypothesis"]
    assert materialized["primary_metric"]["action"] == "share"
    assert materialized["policy"]["paid_ads"] is False
