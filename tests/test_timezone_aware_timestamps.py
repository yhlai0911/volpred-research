from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_runtime_code_does_not_use_deprecated_utcnow() -> None:
    offenders: list[str] = []
    for base in (ROOT / "scripts", ROOT / "src"):
        for path in base.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if "utcnow(" in text:
                offenders.append(str(path.relative_to(ROOT)))

    assert offenders == []
