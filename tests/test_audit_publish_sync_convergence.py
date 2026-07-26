from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import pytest

from scripts import audit_publish_sync
from volpred.ops.public_article_projection_contract import (
    PublicArticleProjectionContractError,
    load_public_article_projection_contract,
)


NOW = datetime(2026, 7, 25, 2, 0, tzinfo=timezone.utc).timestamp()


def _write_feed(tmp_path, *slugs: str):
    path = tmp_path / "feed.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": slug,
                    "status": "published",
                    "published_at": "2026-07-25T00:00:00Z",
                }
                for slug in slugs
            ]
        ),
        encoding="utf-8",
    )
    return path


def _contract_ok():
    return {
        "schema_version": "public-article-projection-contract.v1",
        "policy_sha256": (
            "6d125ff39bdb951026cdecf6e314d4cd"
            "56eb6877cc1cf478333375bc78306888"
        ),
        "frontend_source": "fixture:data-server.ts",
        "matches": True,
    }


def test_converged_receipt_is_atomically_persisted_and_read_back(tmp_path):
    feed = _write_feed(tmp_path, "mile_a", "mile_b")
    receipt = tmp_path / "ops" / "convergence.json"

    report, exit_code = audit_publish_sync.run_audit(
        feed_path=feed,
        receipt_path=receipt,
        now=NOW,
        env={},
        supabase_fetch=lambda env, cutoff: {"mile_a", "mile_b"},
        live_status=lambda url: 200,
        projection_contract_audit=_contract_ok,
    )

    assert exit_code == 0
    assert report["schema_version"] == (
        "publisher-projection-convergence.v2"
    )
    assert report["convergence_status"] == "converged"
    assert report["feed_sha256"] == hashlib.sha256(
        feed.read_bytes()
    ).hexdigest()
    assert report["mismatch_total"] == 0
    assert json.loads(receipt.read_text()) == report
    assert list(receipt.parent.glob(".*.tmp")) == []


def test_supabase_outage_is_unavailable_not_false_missing_drift(tmp_path):
    feed = _write_feed(tmp_path, "mile_a")
    receipt = tmp_path / "convergence.json"

    def unavailable(env, cutoff):
        raise audit_publish_sync.RemoteObservationUnavailable(
            "supabase_observation_unavailable"
        )

    report, exit_code = audit_publish_sync.run_audit(
        feed_path=feed,
        receipt_path=receipt,
        now=NOW,
        env={},
        supabase_fetch=unavailable,
        live_status=lambda url: (_ for _ in ()).throw(
            AssertionError("live route must not run without Supabase evidence")
        ),
        projection_contract_audit=_contract_ok,
    )

    assert exit_code == 2
    assert report["convergence_status"] == "unavailable"
    assert report["missing_supabase"] == []
    assert report["mismatch_total"] == 0
    assert report["observation_errors"] == [
        {
            "surface": "supabase",
            "reason": "supabase_observation_unavailable",
        }
    ]
    assert json.loads(receipt.read_text()) == report


def test_frontend_projection_contract_drift_is_unavailable(tmp_path):
    feed = _write_feed(tmp_path, "mile_a")

    def drifted():
        raise PublicArticleProjectionContractError(
            "nested frontend policy drifted from parent pin"
        )

    report, exit_code = audit_publish_sync.run_audit(
        feed_path=feed,
        receipt_path=tmp_path / "convergence.json",
        now=NOW,
        env={},
        supabase_fetch=lambda env, cutoff: {"mile_a"},
        live_status=lambda url: 200,
        projection_contract_audit=drifted,
    )

    assert exit_code == 2
    assert report["convergence_status"] == "unavailable"
    assert report["public_projection_contract"] is None
    assert report["observation_errors"] == [
        {
            "surface": "public_projection_contract",
            "reason": (
                "nested frontend policy drifted from parent pin"
            ),
        }
    ]


@pytest.mark.parametrize(
    "invalid_evidence",
    [
        {},
        {
            "schema_version": "public-article-projection-contract.v1",
            "policy_sha256": "0" * 64,
            "matches": True,
        },
        {
            "schema_version": "public-article-projection-contract.v1",
            "policy_sha256": (
                "6d125ff39bdb951026cdecf6e314d4cd"
                "56eb6877cc1cf478333375bc78306888"
            ),
            "matches": False,
        },
    ],
)
def test_injected_contract_evidence_cannot_make_a_false_green(
    tmp_path,
    invalid_evidence,
):
    feed = _write_feed(tmp_path, "mile_a")
    receipt = tmp_path / "convergence.json"

    report, exit_code = audit_publish_sync.run_audit(
        feed_path=feed,
        receipt_path=receipt,
        now=NOW,
        env={},
        supabase_fetch=lambda env, cutoff: {"mile_a"},
        live_status=lambda url: 200,
        projection_contract_audit=lambda: invalid_evidence,
    )

    assert exit_code == 2
    assert report["convergence_status"] == "unavailable"
    assert report["public_projection_contract"] is None
    assert report["observation_errors"][0] == {
        "surface": "public_projection_contract",
        "reason": "public projection contract evidence is invalid",
    }
    assert json.loads(receipt.read_text()) == report


@pytest.mark.parametrize("content", [None, "{not-json"])
def test_missing_or_invalid_contract_persists_unavailable(
    tmp_path,
    content,
):
    feed = _write_feed(tmp_path, "mile_a")
    contract = tmp_path / "contract.json"
    if content is not None:
        contract.write_text(content, encoding="utf-8")
    receipt = tmp_path / "convergence.json"

    report, exit_code = audit_publish_sync.run_audit(
        feed_path=feed,
        receipt_path=receipt,
        now=NOW,
        env={},
        supabase_fetch=lambda env, cutoff: {"mile_a"},
        live_status=lambda url: 200,
        projection_contract_audit=lambda: (
            load_public_article_projection_contract(contract)
        ),
    )

    assert exit_code == 2
    assert report["convergence_status"] == "unavailable"
    assert report["public_projection_contract"] is None
    assert report["observation_errors"][0]["surface"] == (
        "public_projection_contract"
    )
    assert json.loads(receipt.read_text()) == report


def test_proven_projection_mismatch_is_drifted(tmp_path):
    feed = _write_feed(tmp_path, "mile_missing", "mile_live_404")

    report, exit_code = audit_publish_sync.run_audit(
        feed_path=feed,
        receipt_path=tmp_path / "convergence.json",
        now=NOW,
        env={},
        supabase_fetch=lambda env, cutoff: {"mile_live_404"},
        live_status=lambda url: 404,
        projection_contract_audit=_contract_ok,
    )

    assert exit_code == 1
    assert report["convergence_status"] == "drifted"
    assert report["missing_supabase"] == ["mile_missing"]
    assert report["orphan_supabase"] == []
    assert report["live_404"] == [
        {"mile_id": "mile_live_404", "status_code": 404}
    ]
    assert report["mismatch_total"] == 2
    assert report["observation_errors"] == []


def test_live_transport_outage_cannot_be_claimed_as_convergence(tmp_path):
    feed = _write_feed(tmp_path, "mile_a")

    def unavailable(url):
        raise audit_publish_sync.RemoteObservationUnavailable(
            "live_url_observation_unavailable"
        )

    report, exit_code = audit_publish_sync.run_audit(
        feed_path=feed,
        receipt_path=tmp_path / "convergence.json",
        now=NOW,
        env={},
        supabase_fetch=lambda env, cutoff: {"mile_a"},
        live_status=unavailable,
        projection_contract_audit=_contract_ok,
    )

    assert exit_code == 2
    assert report["convergence_status"] == "unavailable"
    assert report["mismatch_total"] == 0
    assert report["observation_errors"] == [
        {
            "surface": "live_url",
            "subject": "mile_a",
            "reason": "live_url_observation_unavailable",
        }
    ]


def test_supabase_only_article_is_proven_orphan_drift(tmp_path):
    feed = _write_feed(tmp_path, "mile_local")
    observed_cutoffs = []

    def fetch_projection(env, cutoff):
        observed_cutoffs.append(cutoff)
        return {"mile_local", "mile_orphan"}

    report, exit_code = audit_publish_sync.run_audit(
        feed_path=feed,
        receipt_path=tmp_path / "convergence.json",
        now=NOW,
        env={},
        supabase_fetch=fetch_projection,
        live_status=lambda url: 200,
        projection_contract_audit=_contract_ok,
    )

    assert observed_cutoffs == ["2026-07-22T02:00:00Z"]
    assert exit_code == 1
    assert report["convergence_status"] == "drifted"
    assert report["supabase_published_count"] == 2
    assert report["orphan_supabase"] == ["mile_orphan"]
    assert report["mismatch_total"] == 1


def test_empty_local_window_still_queries_remote_for_orphans(tmp_path):
    feed = _write_feed(tmp_path)
    calls = []

    def fetch_projection(env, cutoff):
        calls.append(cutoff)
        return {"mile_orphan"}

    report, exit_code = audit_publish_sync.run_audit(
        feed_path=feed,
        receipt_path=tmp_path / "convergence.json",
        now=NOW,
        env={},
        supabase_fetch=fetch_projection,
        live_status=lambda url: (_ for _ in ()).throw(
            AssertionError("orphan routes are not local projection checks")
        ),
        projection_contract_audit=_contract_ok,
    )

    assert calls == ["2026-07-22T02:00:00Z"]
    assert exit_code == 1
    assert report["orphan_supabase"] == ["mile_orphan"]
