"""Research helper: one function to record + publish findings.

Usage:
    from research_helper import record_finding
    record_finding(
        title="發現標題（繁中）",
        thinking="推理過程",
        knowledge="知識內容（可英文）",
        category="model_behavior",
        phase="Phase_X",
        description="Feed 描述（繁中 Markdown，有閱讀價值）",
        confidence=0.85
    )
"""
import sys
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from volpred.memory.system import MemorySystem
from volpred.publisher.publisher import Publisher


def record_finding(
    title: str,
    thinking: str,
    knowledge: str = "",
    category: str = "model_behavior",
    phase: str = "",
    description: str = "",
    confidence: float = 0.85,
    evidence: list = None,
):
    """One-stop recording: thinking + knowledge + feed + frontend sync."""
    m = MemorySystem()
    pub = Publisher()

    # 1. Thinking (always)
    m.think(thinking)

    # 2. Knowledge (if provided)
    if knowledge:
        m.add_knowledge(
            category=category,
            content=knowledge,
            evidence=evidence or [],
            confidence=confidence,
        )

    # 3. Feed (use description if provided, else thinking)
    pub.publish_milestone(
        title=title,
        description=description or thinking[:500],
        phase=phase,
    )

    # 4. Frontend local JSON sync — REMOVED 2026-04-18
    # frontend-v2-fix 走 Supabase API；publish_milestone 已自動 sync 到 articles 表。

    print(f"📢 {title}")
