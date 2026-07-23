from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "fb_realchrome_post", ROOT / "scripts" / "fb_realchrome_post.py"
)
assert SPEC and SPEC.loader
fb = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fb)


class _TimestampLocator:
    def __init__(self) -> None:
        self.hovered = False

    def hover(self, timeout: int) -> None:
        assert timeout == 5_000
        self.hovered = True

    def evaluate(self, _script: str) -> str:
        assert self.hovered
        return (
            "https://www.facebook.com/yihao.lai/posts/pfbidEXACT"
            "?__cft__[0]=volatile"
        )


class _HoverRenderedPermalinkPage:
    def __init__(self) -> None:
        self.timestamp = _TimestampLocator()
        self.waits: list[int] = []

    def evaluate(self, script: str, anchor: str) -> str | None:
        assert anchor == "目標貼文前十二字"
        if "data-vp-permalink-trigger" in script:
            return "https://www.facebook.com/yihao.lai#before-hover"
        return None

    def locator(self, selector: str) -> _TimestampLocator:
        assert selector == "[data-vp-permalink-trigger='1']"
        return self.timestamp

    def wait_for_timeout(self, milliseconds: int) -> None:
        self.waits.append(milliseconds)


def test_capture_permalink_hovers_anchor_bound_timestamp_before_reading_href() -> None:
    page = _HoverRenderedPermalinkPage()

    url = fb._capture_permalink(page, "目標貼文前十二字")

    assert url == "https://www.facebook.com/yihao.lai/posts/pfbidEXACT"
    assert page.timestamp.hovered
    assert page.waits == [1_200]
