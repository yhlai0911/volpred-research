#!/usr/bin/env python3
"""CLI shim —— 已裁決 foreign 路徑的寫入出口。實作在 ``volpred.ops.foreign_disposition``。

用法：

    # 只看能不能做（不寫任何東西）
    uv run python scripts/foreign_disposition.py --disposition /tmp/d.json

    # 落地（需 canonical main checkout + writer lock）
    uv run python scripts/foreign_disposition.py --disposition /tmp/d.json --apply
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from volpred.ops.foreign_disposition import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
