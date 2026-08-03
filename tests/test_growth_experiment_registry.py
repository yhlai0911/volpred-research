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


class StatefulGrowthRpc(FakeRpc):
    def __init__(self, snapshot: dict[str, object]) -> None:
        super().__init__()
        self.snapshot = snapshot

    def call(
        self,
        function: str,
        payload: dict[str, object],
    ) -> object:
        if function == "read_volpred_growth_experiment":
            self.calls.append((function, payload))
            return dict(self.snapshot)
        result = super().call(function, payload)
        if function != "command_volpred_growth_experiment":
            return result
        action = str(payload["p_action"])
        if action == "activate":
            self.snapshot["status"] = "active"
            self.snapshot["activated_at"] = payload["p_now"]
        elif action == "stop":
            request = payload["p_payload"]
            assert isinstance(request, dict)
            self.snapshot["status"] = "observing"
            self.snapshot["stop_reason"] = request["reason"]
            self.snapshot["observation_ends_at"] = (
                "2026-08-07T01:00:00+00:00"
            )
        elif action == "close":
            self.snapshot["status"] = "closed"
            self.snapshot["closed_at"] = payload["p_now"]
        return result


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


def _lifecycle_snapshot(
    *,
    status: str,
) -> dict[str, object]:
    return {
        "contract": "growth-experiment-read.v1",
        "experiment_id": "article-share-cta-copy-v1",
        "status": status,
        "preregistered_at": "2026-07-28T22:39:40+00:00",
        "activated_at": (
            "2026-07-30T00:00:00+00:00"
            if status != "preregistered"
            else None
        ),
        "stop_reason": (
            "window_ended"
            if status in {"observing", "closed"}
            else None
        ),
        "observation_ends_at": (
            "2026-08-07T01:00:00+00:00"
            if status in {"observing", "closed"}
            else None
        ),
        "measurement": {
            "control": {"exposures": 10},
            "treatment": {"exposures": 11},
        },
        "spec": {
            "schema_version": "growth-experiment.v1",
            "experiment_id": "article-share-cta-copy-v1",
            "status": "preregistered",
            "window": {
                "starts_at": "2026-07-30T00:00:00+00:00",
                "ends_at": "2026-08-06T00:00:00+00:00",
            },
            "stop_rule": {
                "maximum_exposure_hours": 168,
                "maximum_exposures_total": 5000,
                "maximum_lifecycle_hours": 193,
            },
        },
    }


@pytest.mark.parametrize(
    ("now", "status", "expected_action", "expected_reason"),
    [
        (
            datetime(2026, 7, 29, 23, 59, tzinfo=UTC),
            "preregistered",
            "noop",
            "awaiting_window",
        ),
        (
            datetime(2026, 7, 30, 0, 0, tzinfo=UTC),
            "preregistered",
            "activate",
            "window_open",
        ),
        (
            datetime(2026, 8, 6, 0, 0, tzinfo=UTC),
            "active",
            "stop",
            "window_ended",
        ),
        (
            datetime(2026, 8, 7, 0, 59, tzinfo=UTC),
            "observing",
            "noop",
            "awaiting_attribution",
        ),
        (
            datetime(2026, 8, 7, 1, 0, tzinfo=UTC),
            "observing",
            "close",
            "window_ended",
        ),
        (
            datetime(2026, 8, 8, 0, 0, tzinfo=UTC),
            "closed",
            "noop",
            "already_closed",
        ),
    ],
)
def test_reconcile_advances_only_mature_lifecycle_edges(
    now: datetime,
    status: str,
    expected_action: str,
    expected_reason: str,
) -> None:
    rpc = StatefulGrowthRpc(_lifecycle_snapshot(status=status))
    registry = GrowthExperimentRegistry(rpc=rpc, clock=lambda: now)

    result = registry.reconcile("article-share-cta-copy-v1")

    assert result["contract"] == "growth-lifecycle-reconcile.v1"
    assert result["action"] == expected_action
    assert result["reason"] == expected_reason
    command_calls = [
        call
        for call in rpc.calls
        if call[0] == "command_volpred_growth_experiment"
    ]
    assert len(command_calls) == (0 if expected_action == "noop" else 1)
    if command_calls:
        assert command_calls[0][1]["p_command_id"] == (
            f"growth-lifecycle:article-share-cta-copy-v1:"
            f"{expected_action}:v1"
        )
        assert result["snapshot"]["status"] == {
            "activate": "active",
            "stop": "observing",
            "close": "closed",
        }[expected_action]


def test_reconcile_stops_on_exposure_cap_and_rejects_missed_window() -> None:
    capped = _lifecycle_snapshot(status="active")
    measurement = capped["measurement"]
    assert isinstance(measurement, dict)
    measurement["control"] = {"exposures": 2500}
    measurement["treatment"] = {"exposures": 2500}
    rpc = StatefulGrowthRpc(capped)
    result = GrowthExperimentRegistry(
        rpc=rpc,
        clock=lambda: datetime(2026, 8, 1, tzinfo=UTC),
    ).reconcile("article-share-cta-copy-v1")
    assert result["action"] == "stop"
    assert result["reason"] == "stop_rule_reached"

    missed = StatefulGrowthRpc(
        _lifecycle_snapshot(status="preregistered")
    )
    with pytest.raises(RuntimeError, match="activation window was missed"):
        GrowthExperimentRegistry(
            rpc=missed,
            clock=lambda: datetime(2026, 8, 6, tzinfo=UTC),
        ).reconcile("article-share-cta-copy-v1")


def test_reconcile_template_drift_fails_before_any_command() -> None:
    snapshot = _lifecycle_snapshot(status="active")
    spec = snapshot["spec"]
    assert isinstance(spec, dict)
    expected = dict(spec)
    rpc = StatefulGrowthRpc(snapshot)
    registry = GrowthExperimentRegistry(
        rpc=rpc,
        clock=lambda: datetime(2026, 8, 1, tzinfo=UTC),
    )

    accepted = registry.reconcile(
        "article-share-cta-copy-v1",
        expected_template=expected,
    )
    assert accepted["action"] == "noop"
    drifted = {
        **expected,
        "hypothesis": "silently changed local hypothesis",
    }
    with pytest.raises(
        RuntimeError,
        match="template mismatched live definition",
    ):
        registry.reconcile(
            "article-share-cta-copy-v1",
            expected_template=drifted,
        )

    assert not [
        call
        for call in rpc.calls
        if call[0] == "command_volpred_growth_experiment"
    ]


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


def test_ops_cli_reconcile_template_and_operations_core_schedule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 7, 29, 23, 59, tzinfo=UTC)
    rpc = StatefulGrowthRpc(
        _lifecycle_snapshot(status="preregistered")
    )
    registry = GrowthExperimentRegistry(rpc=rpc, clock=lambda: now)
    monkeypatch.setattr(cli_module, "_growth_registry", lambda: registry)
    root = Path(__file__).parents[1]
    template_path = (
        root
        / "config"
        / "growth_experiments"
        / "article-share-cta-copy-v1.template.json"
    )
    template = json.loads(template_path.read_text())
    snapshot = _lifecycle_snapshot(status="preregistered")
    snapshot["spec"] = {
        **template,
        "preregistered_at": "2026-07-28T22:39:40+00:00",
    }
    rpc.snapshot = snapshot

    result = CliRunner().invoke(
        cli,
        [
            "ops",
            "growth-experiment",
            "reconcile-template",
            "--template-json",
            str(template_path),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["contract"] == "growth-lifecycle-reconcile.v1"
    assert payload["action"] == "noop"
    schedules = json.loads(
        (root / "config" / "runtime_schedules.json").read_text()
    )
    items = {
        item["id"]: item
        for item in schedules["system_crontab"]["items"]
    }
    job = items["growth_experiment_lifecycle"]
    assert job["cron"] == "*/5 * * * *"
    assert job["host_crontab_managed"] is False
    assert job["piggy_back_enabled"] is False
    assert (
        "growth_experiment_lifecycle"
        in schedules["schedule_materialization"]["active_jobs"]
    )
    wrapper = (
        root / "scripts" / "cron_growth_experiment_lifecycle.sh"
    ).read_text()
    assert "growth-experiment reconcile-template" in wrapper


def test_reconcile_noop_projection_drops_the_invariant_snapshot_bulk() -> None:
    """A no-op fire must log the moving parts, not the whole spec every 5 minutes.

    The lifecycle job fires 288x/day and is a no-op for nearly all of an
    experiment's life. Echoing the full snapshot each time wrote ~338 KB/day of
    identical bytes and, because cron_log_rotate.sh truncates on a byte
    threshold to a fixed line count, capped the log's usable history at ~3.5
    days. The projection keeps the varying signal and drops the invariant bulk.
    """
    snapshot = _lifecycle_snapshot(status="active")
    snapshot["measurement"] = {
        "control": {
            "exposures": 58,
            "qualified_actions": 0,
            "read_depth_75": 42,
            "read_depth_75_rate": 0.724138,
        },
        "treatment": {
            "exposures": 59,
            "qualified_actions": 0,
            "read_depth_75": 43,
            "read_depth_75_rate": 0.728814,
        },
    }
    result = {
        "contract": "growth-lifecycle-reconcile.v1",
        "action": "noop",
        "reason": "exposure_window_open",
        "experiment_id": "article-share-cta-copy-v1",
        "snapshot": snapshot,
    }

    projected = cli_module._growth_reconcile_projection(result)

    # Routing identity survives: the cron log and its readers still see these.
    assert projected["contract"] == "growth-lifecycle-reconcile.v1"
    assert projected["action"] == "noop"
    assert projected["reason"] == "exposure_window_open"
    assert projected["experiment_id"] == "article-share-cta-copy-v1"
    # The bulk is gone...
    assert "snapshot" not in projected
    # ...but every field that actually moves between fires is retained.
    assert projected["snapshot_digest"]["status"] == "active"
    assert projected["snapshot_digest"]["variants"] == {
        "control": {"exposures": 58, "qualified_actions": 0},
        "treatment": {"exposures": 59, "qualified_actions": 0},
    }
    # And it is materially smaller, which is the entire point.
    before = len(json.dumps(result))
    after = len(json.dumps(projected))
    assert after < before / 2, f"projection saved too little: {before} -> {after}"


def test_reconcile_projection_never_abridges_a_real_lifecycle_edge() -> None:
    """activate / stop / close must keep full evidence; only no-ops shrink."""
    snapshot = _lifecycle_snapshot(status="closed")
    snapshot["measurement"] = {
        "control": {"exposures": 58, "qualified_actions": 0},
    }
    for action in ("activate", "stop", "close"):
        result = {
            "contract": "growth-lifecycle-reconcile.v1",
            "action": action,
            "experiment_id": "article-share-cta-copy-v1",
            "snapshot": snapshot,
        }
        assert cli_module._growth_reconcile_projection(result) == result


def test_reconcile_projection_returns_unexpected_shapes_untouched() -> None:
    """Fail-open must be self-evidencing: emit everything rather than guess."""
    for result in (
        {"action": "noop"},                                   # no snapshot
        {"action": "noop", "snapshot": "not-a-mapping"},
        {"action": "noop", "snapshot": {"status": "active"}},  # no measurement
        {"action": "noop", "snapshot": {"measurement": {"control": 7}}},
        "not-a-mapping-at-all",
    ):
        assert cli_module._growth_reconcile_projection(result) == result
