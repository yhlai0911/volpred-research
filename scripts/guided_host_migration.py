#!/usr/bin/env python3
"""Assess host parity and perform a fenced, secret-free cold restore."""

from __future__ import annotations

import argparse
from pathlib import Path

from volpred.ops.cold_restore import (
    build_cold_restore_bundle,
    restore_cold_bundle,
)
from volpred.ops.host_attestation import load_trust_policy
from volpred.ops.host_migration import (
    build_guided_plan,
    capture_host,
    compare_hosts,
    load_json_object,
    load_spec,
    write_json,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SPEC = ROOT / "config" / "host_migration_manifest.json"


def _output_path(value: str) -> Path | None:
    return None if value == "-" else Path(value)


def _capture(args: argparse.Namespace) -> int:
    spec = load_spec(Path(args.spec))
    payload = capture_host(
        spec=spec,
        repo_root=Path(args.repo_root),
        migration_id=args.migration_id,
        challenge=args.challenge,
        signing_key_path=Path(args.signing_key),
        signer_identity=args.signer_identity,
        signer_role=args.signer_role,
        attestations_path=Path(args.attestations),
    )
    write_json(_output_path(args.output), payload)
    return 0


def _compare(args: argparse.Namespace) -> int:
    spec = load_spec(Path(args.spec))
    source = load_json_object(Path(args.source))
    target = load_json_object(Path(args.target))
    receipt = (
        load_json_object(Path(args.continuity_receipt))
        if args.continuity_receipt
        else None
    )
    trust_policy = load_trust_policy(Path(args.trust_policy))
    report = compare_hosts(
        spec=spec,
        source=source,
        target=target,
        trust_policy=trust_policy,
        continuity_receipt=receipt,
        report_signing_key_path=Path(args.signing_key),
        report_signer_identity=args.signer_identity,
    )
    write_json(_output_path(args.output), report)
    return 0 if report["promotion_eligible"] else 2


def _plan(args: argparse.Namespace) -> int:
    spec = load_spec(Path(args.spec))
    report = load_json_object(Path(args.report))
    trust_policy = load_trust_policy(Path(args.trust_policy))
    plan = build_guided_plan(
        spec=spec,
        report=report,
        trust_policy=trust_policy,
        plan_signing_key_path=Path(args.signing_key),
        plan_signer_identity=args.signer_identity,
    )
    write_json(_output_path(args.output), plan)
    return 0 if plan["promotion_eligible"] else 2


def _cold_bundle(args: argparse.Namespace) -> int:
    spec = load_spec(Path(args.spec))
    source = load_json_object(Path(args.source))
    trust_policy = load_trust_policy(Path(args.trust_policy))
    manifest = build_cold_restore_bundle(
        spec=spec,
        source_snapshot=source,
        trust_policy=trust_policy,
        repo_root=Path(args.repo_root),
        output_path=Path(args.output),
        signing_key_path=Path(args.signing_key),
        signer_identity=args.signer_identity,
    )
    write_json(
        None,
        {
            "schema_version": manifest["schema_version"],
            "bundle": str(Path(args.output)),
            "manifest_sha256": manifest["manifest_sha256"],
            "payload_sha256": manifest["payload_sha256"],
            "file_count": manifest["file_count"],
            "byte_count": manifest["byte_count"],
            "authorizes_primary_lease": False,
        },
    )
    return 0


def _cold_restore(args: argparse.Namespace) -> int:
    trust_policy = load_trust_policy(Path(args.trust_policy))
    receipt = restore_cold_bundle(
        bundle_path=Path(args.bundle),
        target_root=Path(args.target_root),
        trust_policy=trust_policy,
        target_signing_key_path=Path(args.signing_key),
        target_signer_identity=args.signer_identity,
    )
    write_json(None, receipt)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Manifest-driven host migration. Capture/compare/plan never mutate; "
            "cold restore materializes only a signed Git payload and never "
            "copies secrets, installs schedules, or authorizes a lease."
        )
    )
    subparsers = parser.add_subparsers(required=True)
    capture = subparsers.add_parser("capture")
    capture.add_argument("--spec", default=str(DEFAULT_SPEC))
    capture.add_argument("--repo-root", default=str(ROOT))
    capture.add_argument("--migration-id", required=True)
    capture.add_argument("--challenge", required=True)
    capture.add_argument("--signing-key", required=True)
    capture.add_argument("--signer-identity", required=True)
    capture.add_argument("--signer-role", choices=["source", "target"], required=True)
    capture.add_argument("--attestations", required=True)
    capture.add_argument("--output", required=True, help="path or - for stdout")
    capture.set_defaults(handler=_capture)

    compare = subparsers.add_parser("compare")
    compare.add_argument("--spec", default=str(DEFAULT_SPEC))
    compare.add_argument("--source", required=True)
    compare.add_argument("--target", required=True)
    compare.add_argument("--continuity-receipt")
    compare.add_argument("--trust-policy", required=True)
    compare.add_argument("--signing-key", required=True)
    compare.add_argument("--signer-identity", required=True)
    compare.add_argument("--output", required=True, help="path or - for stdout")
    compare.set_defaults(handler=_compare)

    plan = subparsers.add_parser("plan")
    plan.add_argument("--spec", default=str(DEFAULT_SPEC))
    plan.add_argument("--report", required=True)
    plan.add_argument("--trust-policy", required=True)
    plan.add_argument("--signing-key", required=True)
    plan.add_argument("--signer-identity", required=True)
    plan.add_argument("--output", required=True, help="path or - for stdout")
    plan.set_defaults(handler=_plan)

    cold_bundle = subparsers.add_parser("cold-bundle")
    cold_bundle.add_argument("--spec", default=str(DEFAULT_SPEC))
    cold_bundle.add_argument("--source", required=True)
    cold_bundle.add_argument("--trust-policy", required=True)
    cold_bundle.add_argument("--repo-root", default=str(ROOT))
    cold_bundle.add_argument("--signing-key", required=True)
    cold_bundle.add_argument("--signer-identity", required=True)
    cold_bundle.add_argument("--output", required=True)
    cold_bundle.set_defaults(handler=_cold_bundle)

    cold_restore = subparsers.add_parser("cold-restore")
    cold_restore.add_argument("--bundle", required=True)
    cold_restore.add_argument("--target-root", required=True)
    cold_restore.add_argument("--trust-policy", required=True)
    cold_restore.add_argument("--signing-key", required=True)
    cold_restore.add_argument("--signer-identity", required=True)
    cold_restore.set_defaults(handler=_cold_restore)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
