import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def iter_python_files() -> list[Path]:
    files: list[Path] = []
    for dirname in ("scripts", "src"):
        files.extend((ROOT / dirname).rglob("*.py"))
    return sorted(files)


def test_scripts_and_src_do_not_use_bare_except() -> None:
    offenders: list[str] = []
    for path in iter_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")

    assert offenders == []
