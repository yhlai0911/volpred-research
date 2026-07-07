#!/usr/bin/env python3
"""FB 個人帳號自動發文 — real-Chrome CDP-attach worker.

底層修復 (task platform-ops-fb-realchrome-autopost / boss Telegram msg 237)：
現況 FB 個人帳號發文只能靠 interactive Claude-in-Chrome session；hourly headless
巡檢連不到 Chrome → 每次卡 pending/awaiting。老闆釘死：不用 Graph API、不用粉專、
不用 headless Playwright（假瀏覽器）。

本 worker 走唯一尊重上述約束的 path = **attach 到老闆已開著、已登入的真實 Chrome**
（真 profile、真 session）經 CDP remote-debugging-port 驅動貼文。這不是 headless
Playwright — 是 `connect_over_cdp` 附掛到既有的、可見的、已登入的真 Chrome，不 launch
任何新瀏覽器實例。

前置需求：老闆的 Chrome 以 `--remote-debugging-port=9222` 啟動（見
`docs/fb_realchrome_setup.md`）。本機已驗證 9222 開著。

模式：
  --check          安全模式：attach → 開 FB 個人頁 → 截圖 + 探測登入狀態，不發文
  --post <draft>   發文：讀 draft → 貼主文（不放連結）→ 第一則留言補網址
  --dry-run        搭配 --post：走到送出前一步停下截圖，不真的按「發佈」

風控（老闆硬性 gate）：先手動 --check 確認 attach + 登入 OK，再 --post --dry-run
確認 composer 正確填入，PASS 才拿掉 --dry-run 真發。單篇小樣本先測，確認不觸發 FB
自動化鎖帳，才 wire 進 hourly dispatch。

CDP-attach 若觸 FB 風控 → 誠實回報物理上限，不硬繞。
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

import requests

CDP_PORT = 9222
CDP_BASE = f"http://127.0.0.1:{CDP_PORT}"
FB_PROFILE_URL = "https://www.facebook.com/yihao.lai"
SHOT_DIR = Path("/tmp/fb_realchrome")
SHOT_DIR.mkdir(parents=True, exist_ok=True)


def cdp_alive() -> dict | None:
    """回傳 /json/version 或 None（port 沒開）。"""
    try:
        r = requests.get(f"{CDP_BASE}/json/version", timeout=3)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def parse_draft(path: Path) -> tuple[str, str]:
    """從 FB draft .md 抽出 (主貼文純文字, 第一則留言連結)。

    draft 格式（見 storage/drafts/fb_mile_*.md）：
      ## 主貼文（純文字，不含連結）
      <正文...>
      ## 第一則留言（貼連結）
      <url>
    """
    text = path.read_text(encoding="utf-8")
    # 主貼文：介於「## 主貼文」與「## 第一則留言」之間
    m_body = re.search(
        r"##\s*主貼文[^\n]*\n(.*?)\n##\s*第一則留言",
        text,
        re.S,
    )
    m_link = re.search(r"##\s*第一則留言[^\n]*\n\s*(https?://\S+)", text)
    if not m_body:
        raise ValueError(f"{path.name}: 找不到「## 主貼文」區塊")
    body = m_body.group(1).strip()
    # 去掉分隔線 --- 與註解行
    body = "\n".join(
        ln for ln in body.splitlines()
        if ln.strip() != "---" and not ln.lstrip().startswith("#")
    ).strip()
    link = m_link.group(1).strip() if m_link else ""
    if not body:
        raise ValueError(f"{path.name}: 主貼文抽取為空")
    return body, link


def _connect(pw):
    """connect_over_cdp 到既有真 Chrome。回傳 browser。"""
    return pw.chromium.connect_over_cdp(CDP_BASE)


def _get_or_open_fb_page(browser):
    """在既有 context 找 facebook.com 分頁；沒有就開新分頁導到個人頁。

    只用 default context（真 Chrome 只有一個真 profile context），確保帶著
    老闆已登入的 cookie/session。
    """
    ctx = browser.contexts[0]
    for pg in ctx.pages:
        if "facebook.com" in (pg.url or ""):
            return pg
    pg = ctx.new_page()
    pg.goto(FB_PROFILE_URL, wait_until="domcontentloaded", timeout=60_000)
    return pg


def _login_state(page) -> str:
    """探測 FB 登入狀態：'logged_in' / 'login_wall' / 'unknown'。"""
    try:
        # 登入牆特徵：有 email/pass 輸入框、或 URL 導到 /login
        url = page.url or ""
        if "/login" in url or "login.php" in url:
            return "login_wall"
        has_pass = page.locator("input[name='pass']").count() > 0
        if has_pass:
            return "login_wall"
        # 登入態特徵：有「在想些什麼」composer 觸發鈕或 profile 導覽
        # FB 文案 zh-TW: 「在想些什麼」/「你在想些什麼」
        body_txt = page.locator("body").inner_text(timeout=5_000)
        if any(k in body_txt for k in ["在想些什麼", "限時動態", "建立貼文", "個人檔案"]):
            return "logged_in"
    except Exception:
        pass
    return "unknown"


def cmd_check() -> int:
    ver = cdp_alive()
    if not ver:
        print(f"[FAIL] CDP port {CDP_PORT} 沒開 — Chrome 未以 --remote-debugging-port 啟動")
        print("       修復：見 docs/fb_realchrome_setup.md")
        return 2
    print(f"[OK] CDP alive: {ver.get('Browser')}")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = _connect(pw)
        print(f"[OK] connect_over_cdp 成功，contexts={len(browser.contexts)}")
        page = _get_or_open_fb_page(browser)
        page.wait_for_timeout(4_000)
        shot = SHOT_DIR / f"check_{int(time.time())}.png"
        page.screenshot(path=str(shot))
        state = _login_state(page)
        print(f"[INFO] FB 分頁 URL: {page.url}")
        print(f"[INFO] 登入狀態: {state}")
        print(f"[INFO] 截圖: {shot}")
        # 不關 browser（attach 模式，關掉會影響老闆真 Chrome）
        browser.close()  # connect_over_cdp 的 close 只斷連線不關 Chrome
        if state == "logged_in":
            print("[PASS] 這台 Chrome 已登入 FB，CDP-attach 可行 → 可進 --post --dry-run")
            return 0
        if state == "login_wall":
            print("[BLOCK] 這台 Chrome 未登入 FB（login wall）→ 需老闆先登入該 profile")
            return 3
        print("[WARN] 登入狀態 unknown — 看截圖人工判斷")
        return 1


def cmd_post(draft_path: Path, dry_run: bool) -> int:
    body, link = parse_draft(draft_path)
    print(f"[INFO] draft: {draft_path.name}")
    print(f"[INFO] 主貼文 {len(body)} 字；留言連結: {link or '(無)'}")
    if not cdp_alive():
        print(f"[FAIL] CDP port {CDP_PORT} 沒開")
        return 2

    # 中文輸入用系統剪貼簿 + Cmd+V（type 會中文亂碼，見 memory
    # reference_fb_chrome_browser_autoselect）
    subprocess.run(["pbcopy"], input=body.encode("utf-8"), check=True)

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = _connect(pw)
        page = _get_or_open_fb_page(browser)
        page.wait_for_timeout(3_000)
        state = _login_state(page)
        if state != "logged_in":
            print(f"[ABORT] 登入狀態={state}，不在未登入態發文")
            browser.close()
            return 3

        # 1) 開 composer：點「在想些什麼」觸發鈕
        opened = False
        for sel in [
            "text=在想些什麼",
            "text=你在想些什麼",
            "[aria-label='建立貼文']",
        ]:
            try:
                el = page.locator(sel).first
                if el.count() > 0:
                    el.click(timeout=8_000)
                    opened = True
                    break
            except Exception:
                continue
        if not opened:
            shot = SHOT_DIR / f"post_no_composer_{int(time.time())}.png"
            page.screenshot(path=str(shot))
            print(f"[ABORT] 找不到 composer 觸發鈕，截圖 {shot}")
            browser.close()
            return 4
        page.wait_for_timeout(2_500)

        # 2) 貼主文：聚焦 composer 的 contenteditable → Cmd+V
        editor = page.locator("div[role='textbox'][contenteditable='true']").first
        editor.click(timeout=8_000)
        page.wait_for_timeout(500)
        page.keyboard.press("Meta+V")
        page.wait_for_timeout(2_000)

        shot = SHOT_DIR / f"post_composed_{int(time.time())}.png"
        page.screenshot(path=str(shot))
        print(f"[INFO] 主文已填入 composer，截圖 {shot}")

        if dry_run:
            print("[DRY-RUN] 停在送出前一步，不按「發佈」。人工看截圖確認 composer 正確。")
            browser.close()
            return 0

        # 3) 送出：按「發佈」
        posted = False
        for sel in ["[aria-label='發佈']", "text=發佈"]:
            try:
                el = page.locator(sel).first
                if el.count() > 0:
                    el.click(timeout=8_000)
                    posted = True
                    break
            except Exception:
                continue
        if not posted:
            shot = SHOT_DIR / f"post_no_publish_{int(time.time())}.png"
            page.screenshot(path=str(shot))
            print(f"[ABORT] 找不到「發佈」鈕，截圖 {shot}")
            browser.close()
            return 5
        page.wait_for_timeout(6_000)
        shot = SHOT_DIR / f"post_done_{int(time.time())}.png"
        page.screenshot(path=str(shot))
        print(f"[OK] 主文已送出，截圖 {shot}")
        print(f"[TODO] 第一則留言補連結需在貼文出現後定位留言框 — 見人工步驟 / 下版")
        # 留言補連結留待驗證後版本（需貼文 permalink 定位留言框），先確保主文發出
        browser.close()
        return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="FB real-Chrome CDP-attach 發文 worker")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true", help="安全模式：驗 attach + 登入狀態")
    g.add_argument("--post", metavar="DRAFT", help="發文：FB draft .md 路徑")
    ap.add_argument("--dry-run", action="store_true", help="搭配 --post：停在送出前")
    args = ap.parse_args()

    if args.check:
        return cmd_check()
    return cmd_post(Path(args.post), args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
