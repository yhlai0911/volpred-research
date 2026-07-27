#!/usr/bin/env python3
"""Materialize Operations Core's canonical silent-loss signal."""

from __future__ import annotations

from pathlib import Path

from volpred.ops.silent_loss_retirement import materialize_silent_loss_signal

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    print(materialize_silent_loss_signal(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
