#!/usr/bin/env python3
"""Anti-AI-style 自動偵測 validator — 把「靠 agent 自律」補上「程式自動檢查」。

背景(2026-05-29 用戶問「寫文都會經過 anti-ai-style?」):
publishing.md 規則強制所有讀者向文章跑 anti-ai-style,但 publisher 程式**無硬 gate**,
全靠寫作 agent 自律 co-run。本 validator 補上自動偵測層(同 validate_feed_audience 模式),
掃 feed 找可量化的 AI-tells,flag 可疑文章供 audit / 重寫。

偵測規則(取自 .claude/skills/anti-ai-style/references/8-landmines.md):
- 破折號密度:`—`/`——` 每 1000 字 >1 偏高、>3 嚴重(地雷 9,最隱性 AI tell)
- 假哲理「不是…而是」/「並非…而是」/「與其說…不如說」(地雷 1,allow=0)
- 翻譯腔/情緒直白:「這讓人」「不禁」「讓人感到」「有人說」(地雷 7)
- AI 套路:「值得注意的是」「綜上所述」「總而言之」「在當今」「不僅…更」

用法:
  uv run python scripts/validate_anti_ai_style.py              # 掃全部 published
  uv run python scripts/validate_anti_ai_style.py --recent 50  # 只掃最近 50 篇
  uv run python scripts/validate_anti_ai_style.py --json       # 輸出 JSON 報告
退出碼:0=掃描完成(報告);非阻塞(歷史文章本就可能有 tell,定位為 audit 工具)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FEED = ROOT / "storage" / "reports" / "feed.json"

EMDASH_RE = re.compile(r"—")  # U+2014;「——」會被計為 2
BANNED = [
    ("假哲理不是而是", re.compile(r"不是.{0,14}而是|並非.{0,14}而是|與其說.{0,14}不如說|不該是.{0,14}而是")),
    ("翻譯腔這讓人", re.compile(r"這讓人|不禁|讓人感到|有人說")),
    ("AI套路詞", re.compile(r"值得注意的是|綜上所述|總而言之|在當今|總的來說|不僅.{0,15}更")),
]


def _strip_md(text: str) -> str:
    # 去 code block / 圖片 markdown,避免把 code 內字元誤計
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    return text


def scan_article(content: str) -> dict:
    body = _strip_md(content or "")
    n = max(len(body), 1)
    emdash = len(EMDASH_RE.findall(body))
    emdash_density = round(emdash / n * 1000, 2)
    hits = {}
    for name, rx in BANNED:
        m = rx.findall(body)
        if m:
            hits[name] = len(m)
    # 判級:嚴重 = 破折號>3/1000 或 假哲理出現;警告 = 破折號 1-3 或其他 tell
    severe = emdash_density > 3 or "假哲理不是而是" in hits
    warn = (not severe) and (emdash_density > 1 or bool(hits))
    return {"emdash": emdash, "emdash_density": emdash_density, "hits": hits,
            "level": "severe" if severe else ("warn" if warn else "ok")}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--recent", type=int, default=0, help="只掃最近 N 篇(0=全部)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    feed = json.loads(FEED.read_text(encoding="utf-8"))
    pub = [a for a in feed if isinstance(a, dict) and a.get("status") == "published"]
    pub.sort(key=lambda a: str(a.get("published_at") or ""), reverse=True)
    if args.recent:
        pub = pub[: args.recent]

    results = []
    for a in pub:
        r = scan_article(a.get("content") or "")
        if r["level"] != "ok":
            results.append({"id": a.get("id"), "title": (a.get("title") or "")[:50],
                            "when": (a.get("published_at") or "")[:10], **r})

    severe = [r for r in results if r["level"] == "severe"]
    warn = [r for r in results if r["level"] == "warn"]

    if args.json:
        print(json.dumps({"scanned": len(pub), "severe": len(severe), "warn": len(warn),
                          "flagged": results[:50]}, ensure_ascii=False, indent=2))
        return 0

    print(f"[anti-ai-style] 掃描 {len(pub)} 篇 published")
    print(f"  嚴重(破折號>3/1000 或 假哲理): {len(severe)}")
    print(f"  警告(破折號 1-3/1000 或其他 tell): {len(warn)}")
    print(f"  乾淨: {len(pub) - len(results)}  ({round((len(pub)-len(results))/max(len(pub),1)*100)}%)")
    print("\n--- 最嚴重 12 篇(優先重寫候選)---")
    for r in sorted(results, key=lambda x: (x["level"] != "severe", -x["emdash_density"]))[:12]:
        flags = f"破折號 {r['emdash_density']}/1k" + ("".join(f" · {k}×{v}" for k, v in r["hits"].items()))
        print(f"  [{r['level']}] {r['id']} ({r['when']}) — {flags}")
        print(f"        {r['title']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
