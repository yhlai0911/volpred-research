"""Shared owner-facing report contract for every dispatch execution path."""

from __future__ import annotations

EXTERNAL_REPORT_CONTRACT = (
    "[Operations Core external report contract]\n"
    "所有對外 Email、Telegram 與最終回報的標題（沒有獨立標題時為第一行）"
    "一律以 `[新架構派發]` 開頭，禁止省略或換成同義標籤。判定 incident 是誤報、"
    "已恢復或已結案前，必須回讀告警當下的 first_seen、evidence timestamp 與 live source；"
    "現在健康只能證明已恢復，不能把先前告警改稱誤報。只有證明 detector 在告警當下"
    "讀錯，才可使用「誤報」。"
)


def inject_external_report_contract(prompt: str) -> str:
    """Prepend the contract once while preserving the caller's prompt bytes."""
    if prompt.startswith(EXTERNAL_REPORT_CONTRACT):
        return prompt
    return f"{EXTERNAL_REPORT_CONTRACT}\n\n{prompt}"
