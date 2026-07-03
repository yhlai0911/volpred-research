"""Plain-language formatting for boss-facing ops messages.

Internal check IDs stay intact in logs/details; this module is only for
alert email, Telegram, and summary surfaces read by the boss.
"""

from __future__ import annotations

import re


_TERM_LABELS: dict[str, str] = {
    "alert": "警報",
    "alert_breach": "需要處理的警報",
    "arc-dup": "舊題材重複",
    "arc_diversity": "主題過度集中",
    "arc_signature": "文章主題指紋",
    "burst": "發文太密集",
    "cluster-pressure": "主題集中壓力",
    "cluster_cap_drift": "主題比例超標",
    "content_completeness": "文章配套完整度",
    "content_completeness:lazypack_gap": "懶人包覆蓋不足",
    "content_quality": "內容品質巡檢",
    "correction_trend": "返工/修正趨勢",
    "cron": "定時任務",
    "daily_digest": "每日精選導讀",
    "daily_article": "日常文章",
    "daily_digest_uniqueness": "每日精選導讀重複檢查",
    "daily_digest_uniqueness=duplicate": "同一天出現超過一篇每日精選導讀",
    "dedup": "去重",
    "dispatch_health": "派工來源健康",
    "distribution_supabase": "網站資料同步",
    "draft_pool_low": "草稿池空了",
    "drought": "發文空窗",
    "eligible_after_dedup": "去重後可釋出的文章數",
    "email_reply": "老闆回信",
    "experiment": "研究實驗",
    "first_pass_success": "首次完成率",
    "frontend_render": "網站首頁顯示異常",
    "gmail_poll_freshness": "老闆回信讀取是否正常",
    "governance": "流程治理",
    "health_alerts_unhandled": "目前未處理警報",
    "health_cron": "定時任務健康",
    "host cron": "主機定時任務",
    "host_cron_fail": "主機定時任務失敗",
    "lazypack_gap": "懶人包覆蓋不足",
    "loop_health": "自主循環健康度",
    "member_qa_stale": "會員提問逾期",
    "paper_stale": "論文線停滯",
    "paper_trading_gaps": "模擬交易資料缺口",
    "paper_website_drift": "網站論文狀態高估",
    "platform_ops": "平台維運",
    "production_pending": "任務池狀態",
    "production_throughput": "發文產量",
    "publish_rhythm": "發文節奏",
    "publish_rhythm:burst": "發文太密集",
    "publish_rhythm:drought": "發文間隔過久",
    "publish_rhythm=burst": "發文太密集",
    "publish_rhythm=drought": "發文間隔過久",
    "publishing_freshness": "發文脫班",
    "release_deadlock": "草稿來源枯竭",
    "release_pool": "文章釋出排程",
    "release_pool_gap": "文章釋出排程停擺",
    "send-alert": "發送警報",
    "send_alert": "發送警報",
    "strategy_metrics_freshness": "策略績效資料是否新鮮",
    "stale_inflight": "卡住的進行中任務",
    "supabase_sync_fail": "網站資料同步失敗",
    "task_outcome": "任務完成率",
    "title_format:digest_prefix": "標題前綴重複",
    "verification_fb_pipeline": "Facebook 同步流程",
    "verification_live_url": "線上網站檢查",
    "work_log_freshness": "工作紀錄是否更新",
}

_TERM_PATTERNS = sorted(_TERM_LABELS.items(), key=lambda kv: len(kv[0]), reverse=True)
_CODE_SPAN_RE = re.compile(r"`([^`]+)`")
_COMMAND_LINE_RE = re.compile(
    r"^\s*(?:"
    r"uv\s+run|VOLPRED_|jq\s+|grep\s+|tail\s+|head\s+|crontab\s+|chmod\s+|"
    r"python\s+|for\s+|from\s+|print\(|System Settings\b"
    r")"
)


def plain_label(raw: object) -> str:
    """Return a boss-readable label for a known internal key."""
    text = str(raw or "").strip()
    if not text:
        return ""
    return _TERM_LABELS.get(text) or _TERM_LABELS.get(text.lower()) or text


def _replace_plain_segment(segment: str) -> str:
    out = segment
    for term, label in _TERM_PATTERNS:
        pattern = re.compile(
            rf"(?<![\w/.-]){re.escape(term)}(?![\w/.-])",
            flags=re.IGNORECASE if term.isascii() else 0,
        )
        out = pattern.sub(label, out)
    return out


def _replace_code_span(match: re.Match[str]) -> str:
    inner = match.group(1).strip()
    label = plain_label(inner)
    if label != inner:
        return label
    return match.group(0)


def plainify_boss_text(text: object) -> str:
    """Translate jargon-heavy ops text without altering shell command lines."""
    raw = str(text or "")
    lines: list[str] = []
    for line in raw.splitlines():
        if _COMMAND_LINE_RE.match(line):
            lines.append(line)
            continue
        protected = _CODE_SPAN_RE.sub(_replace_code_span, line)
        lines.append(_replace_plain_segment(protected))
    return "\n".join(lines)


def _infer_plain_summary(title: str, body: str) -> str:
    combined = f"{title}\n{body}"
    if any(token in combined for token in ("發文脫班", "發文間隔過久", "文章釋出排程")):
        return "系統偵測到讀者端內容更新可能中斷，需要先恢復發文節奏。"
    if "發文太密集" in combined:
        return "系統偵測到短時間內發太多篇，讀者可能覺得洗版。"
    if "每日精選導讀" in combined and "重複" in combined:
        return "同一天出現重複導讀，會讓首頁看起來像重複發文。"
    if "懶人包" in combined:
        return "一般讀者文章缺少快速理解圖組，會降低閱讀與分享效果。"
    if any(token in combined for token in ("主題過度集中", "舊題材重複", "主題集中壓力")):
        return "最近內容題材太集中，讀者可能覺得一直在看同一件事。"
    if "網站" in combined:
        return "網站呈現或同步狀態可能和本地真實資料不一致，需要先保住對外可信度。"
    if "定時任務" in combined:
        return "背景自動化有任務失敗，可能讓資料、發文或同步流程停住。"
    return "系統偵測到需要處理的營運風險。"


def _infer_plain_impact(title: str, body: str) -> str:
    combined = f"{title}\n{body}"
    if any(token in combined for token in ("發文", "內容", "懶人包", "題材")):
        return "影響文章品質、讀者信任與流量表現。"
    if any(token in combined for token in ("網站", "同步", "Supabase")):
        return "影響讀者看到的網站狀態與平台可信度。"
    if any(token in combined for token in ("研究", "論文", "knowledge")):
        return "影響研究結論累積與論文推進。"
    return "影響平台自動運作的穩定性。"


def _infer_plain_action(title: str, body: str) -> str:
    combined = f"{title}\n{body}"
    if "發文間隔過久" in combined or "發文脫班" in combined:
        return "先補一篇可發佈文章或觸發釋出流程，再追查為什麼排程沒接上。"
    if "發文太密集" in combined:
        return "先暫停下一輪讀者端發文，再檢查是否有雙排程同時觸發。"
    if "懶人包" in combined:
        return "先替缺圖的文章補懶人包，再確認新文章的發佈 gate 會擋住同類問題。"
    if "每日精選導讀" in combined and "重複" in combined:
        return "先保留一篇正確導讀、下架重複篇，再查重複入池原因。"
    if any(token in combined for token in ("主題過度集中", "舊題材重複", "主題集中壓力")):
        return "下一篇改派不同題材，並避免再釋出同一主題群的草稿。"
    return "依下方行動清單處理，完成後讓下一輪巡檢自動解除警報。"


def boss_facing_alert(title: object, body: object) -> tuple[str, str]:
    """Return plain title/body for alert email and Telegram."""
    plain_title = plainify_boss_text(title)
    plain_body = plainify_boss_text(body)
    if not plain_body.strip() or "## 白話結論" in plain_body:
        return plain_title, plain_body

    summary = _infer_plain_summary(plain_title, plain_body)
    impact = _infer_plain_impact(plain_title, plain_body)
    action = _infer_plain_action(plain_title, plain_body)
    prefix = "\n".join(
        [
            "## 白話結論",
            summary,
            "",
            "## 影響",
            impact,
            "",
            "## 行動",
            action,
            "",
            "---",
            "",
        ]
    )
    return plain_title, f"{prefix}{plain_body}"
