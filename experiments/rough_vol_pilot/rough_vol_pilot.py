from __future__ import annotations

import json
from pathlib import Path


EXPERIMENT_ID = "rough_vol_pilot"


def main() -> None:
    base_dir = Path(__file__).resolve().parent
    output_path = base_dir / f"{EXPERIMENT_ID}_results.json"
    payload = {
        "experiment_id": EXPERIMENT_ID,
        "status": "draft",
        "notes": ["replace with actual experiment output"],
    }
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
