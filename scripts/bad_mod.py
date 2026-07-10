"""Introduces a new silent fallback: except → return None, no diagnostic."""
import json


def load(raw):
    try:
        return json.loads(raw)
    except Exception:
        return None
