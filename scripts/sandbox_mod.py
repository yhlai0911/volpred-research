"""Sandbox fixture: fallback with an observable diagnostic."""
import json


def load(raw):
    try:
        return json.loads(raw)
    except Exception as exc:
        print(f"load failed: {exc}")
        return None
