from __future__ import annotations

from datetime import datetime, timezone

import pytest

from volpred.ops.work.ownership import WorkOwner
from volpred.ops.work.postgres import PostgresCoordinationStore
from volpred.ops.work.postgres_ownership import PostgresWorkOwnerStore


def test_work_owner_exposes_generation_bound_identity() -> None:
    owner = WorkOwner(
        schema_version="work-owner.v1",
        capability="work.coordinate",
        owner="operations_core",
        generation=2,
        cutover_manifest_sha256="a" * 64,
        changed_at="2026-07-26T03:00:00+00:00",
        changed_by="operator:test",
        change_reason="controlled cutover",
    )

    assert owner.owner_ref == "work-owner:work.coordinate:generation-2"


@pytest.mark.parametrize("invalid_generation", [True, 0, -1, "2"])
def test_postgres_store_rejects_non_positive_integer_owner_generation(
    invalid_generation: object,
) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        PostgresCoordinationStore(
            lambda: None,  # type: ignore[arg-type,return-value]
            owner_generation=invalid_generation,  # type: ignore[arg-type]
        )


class _Cursor:
    def __init__(self, row: dict[str, object]) -> None:
        self._row = row

    def fetchone(self) -> dict[str, object]:
        return self._row


class _Connection:
    def __init__(self, row: dict[str, object]) -> None:
        self._row = row
        self.row_factory = None
        self.executed: list[tuple[str, tuple[object, ...]]] = []

    def __enter__(self) -> _Connection:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(
        self,
        query: str,
        parameters: tuple[object, ...],
    ) -> _Cursor:
        self.executed.append((query, parameters))
        return _Cursor(self._row)


def test_postgres_owner_store_reads_the_durable_owner_generation() -> None:
    connection = _Connection(
        {
            "schema_version": "work-owner.v1",
            "capability": "work.coordinate",
            "owner": "legacy",
            "generation": 1,
            "cutover_manifest_sha256": None,
            "changed_at": datetime(
                2026, 7, 26, 3, 0, tzinfo=timezone.utc
            ),
            "changed_by": "migration:test",
            "change_reason": "legacy remains owner",
        }
    )

    owner = PostgresWorkOwnerStore(lambda: connection).read_owner()

    assert (owner.owner, owner.generation) == ("legacy", 1)
    assert connection.executed == [
        ("SELECT * FROM volpred_ops.read_work_owner()", ())
    ]
