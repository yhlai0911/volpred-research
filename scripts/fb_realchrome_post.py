#!/usr/bin/env python3
"""FB 個人帳號自動發文 — real-Chrome CDP-attach worker.

底層修復 (task platform-ops-fb-realchrome-autopost / boss Telegram msg 237)：
現況 FB 個人帳號發文只能靠 interactive Claude-in-Chrome session；hourly headless
巡檢連不到 Chrome → 每次卡 pending/awaiting。老闆釘死：不用 Graph API、不用粉專、
不用 headless Playwright（假瀏覽器）。

本 worker 走唯一尊重上述約束的 path = 用**專用持久 profile 的真 GUI Chrome**
（`~/.volpred/fb_chrome_profile`，非 headless、非老闆主 Chrome、非 /tmp 暫時 profile），
老闆登入一次後 cookie 持久化，經 CDP `connect_over_cdp` 附掛驅動貼文。這是可見的真
Chrome window，不是 headless 假瀏覽器；跟老闆主 Chrome 各自 user-data-dir 不互擾。

自癒：`ensure_fb_chrome()` 在 --check / --post 時若發現 CDP port 沒開，會自動用上述
profile 啟動 dedicated Chrome 再 attach → reboot/crash/老闆關掉視窗後 hourly tick 不再
永久卡死。前置需求（一次性）：老闆在該 dedicated 視窗登入 facebook.com/yihao.lai。
（演進史 + 為何不 attach 老闆主 Chrome：見 `docs/fb_realchrome_setup.md`。）

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
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

CDP_PORT = 9222
CDP_BASE = f"http://127.0.0.1:{CDP_PORT}"
FB_PROFILE_URL = "https://www.facebook.com/yihao.lai"
SHOT_DIR = Path("/tmp/fb_realchrome")
SHOT_DIR.mkdir(parents=True, exist_ok=True)

FEED_PATH = ROOT / "storage" / "reports" / "feed.json"
TRENDING_LOG_PATH = ROOT / "storage" / "reports" / "trending_repost_log.json"
# 同窗競態 claim ledger（兩 session 同時發同一 mile 的 <5min 窗口互斥）。
CLAIM_LEDGER = ROOT / "storage" / "ops" / "fb_post_claims.json"
CLAIM_TTL_S = 300  # 5 min：超過視為前一次 claim 已死，可再 claim


def _mile_id_from_draft(path: Path) -> str | None:
    """從 FB draft 抽 mile_id：優先讀「# mile_id: mile_XXX」註解，退回檔名
    fb_mile_XXX.md → mile_XXX。找不到回 None（guard 會 warn 但不硬擋）。"""
    try:
        m = re.search(r"#\s*mile_id:\s*(mile_[0-9a-fA-F]+)", path.read_text(encoding="utf-8"))
        if m:
            return m.group(1)
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] 讀 draft 抽 mile_id 失敗: {e}", file=sys.stderr)
    m2 = re.match(r"fb_(mile_[0-9a-fA-F]+)\.md$", path.name)
    return m2.group(1) if m2 else None


def _fb_post_status(mile_id: str) -> str | None:
    """讀 canonical fb_post_status（feed.json by id/mile_id + trending_log by mile_id）。
    回最新一筆非空 status，沒有回 None。"""
    for p, keys in ((FEED_PATH, ("id", "mile_id")), (TRENDING_LOG_PATH, ("mile_id",))):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue  # silent-ok: status 檔缺失/壞掉 → 換下一個源，guard 由 caller 決策
        if not isinstance(data, list):
            continue
        for item in data:
            if isinstance(item, dict) and any(item.get(k) == mile_id for k in keys):
                st = str(item.get("fb_post_status") or "").strip()
                if st:
                    return st
    return None


def _claim_fb_post(mile_id: str, *, force: bool) -> tuple[bool, str]:
    """發文前的 atomic 互斥 claim。回 (可發, 原因)。

    步驟（全程 held shared_state_lock，跨 process/session 原子）：
      1. canonical fb_post_status == success → 已發過，abort（除非 --force）
      2. ledger 有 <5min 的 in-flight claim → 另一 session 正在發，abort
      3. 否則寫 in-flight claim（帶 ts）→ 放行
    force=True 只跳過 success/in-flight 檢查，仍寫 claim 供觀測。
    """
    from volpred.ops.shared_lock import shared_state_lock

    with shared_state_lock("fb_post_claim", storage_dir="storage"):
        if not force:
            st = _fb_post_status(mile_id)
            if st == "success":
                return False, f"canonical fb_post_status=success（已發過，用 --force 可強制重發）"
        # ledger in-flight 檢查
        ledger = {}
        try:
            if CLAIM_LEDGER.exists():
                ledger = json.loads(CLAIM_LEDGER.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            print(f"[WARN] claim ledger 讀取失敗，視為空: {e}", file=sys.stderr)
            ledger = {}
        now = time.time()
        prev = ledger.get(mile_id) if isinstance(ledger, dict) else None
        if not force and isinstance(prev, dict) and prev.get("state") == "posting":
            age = now - float(prev.get("ts") or 0)
            if age < CLAIM_TTL_S:
                return False, f"另一 session {int(age)}s 前開始發同一 mile（in-flight，未過 {CLAIM_TTL_S}s TTL）"
        ledger[mile_id] = {"state": "posting", "ts": now,
                           "iso": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        CLAIM_LEDGER.parent.mkdir(parents=True, exist_ok=True)
        CLAIM_LEDGER.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return True, "claimed"


def _finalize_fb_post(mile_id: str, *, ok: bool) -> None:
    """發文結束標記：ok=True → canonical fb_post_status=success + ledger done；
    ok=False → ledger 清 in-flight（讓下次能重試），不動 canonical status。"""
    try:
        from volpred.ops.shared_lock import shared_state_lock
    except Exception:
        shared_state_lock = None  # noqa: N806  # silent-ok: 極端 import 失敗下不阻塞主流程
    if ok:
        try:
            from mark_fb_post_status import update_fb_status  # type: ignore
        except Exception:
            sys.path.insert(0, str(ROOT / "scripts"))
            from mark_fb_post_status import update_fb_status  # type: ignore
        try:
            res = update_fb_status(mile_id, status="success",
                                   note="fb_realchrome_post 發文成功自動標記")
            print(f"[OK] canonical fb_post_status→success（feed={res['updated_feed']} log={res['updated_log']}）")
        except Exception as e:  # noqa: BLE001
            print(f"[WARN] 標記 fb_post_status=success 失敗（貼文已發，需手動 mark）: {e}", file=sys.stderr)
    # 更新 ledger
    if shared_state_lock is None:
        return
    try:
        with shared_state_lock("fb_post_claim", storage_dir="storage"):
            ledger = {}
            if CLAIM_LEDGER.exists():
                ledger = json.loads(CLAIM_LEDGER.read_text(encoding="utf-8"))
            if not isinstance(ledger, dict):
                ledger = {}
            ledger[mile_id] = {"state": "done" if ok else "failed", "ts": time.time(),
                               "iso": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            CLAIM_LEDGER.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] 更新 claim ledger 失敗: {e}", file=sys.stderr)

# 專用持久 profile（登入態持久化，reboot 後仍在）— 不是老闆的主 Chrome，
# 是獨立第二個真 GUI Chrome 實例，各自 user-data-dir 不互擾（見 docs/fb_realchrome_setup.md）。
CHROME_BIN = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
FB_PROFILE_DIR = os.path.expanduser("~/.volpred/fb_chrome_profile")


def cdp_alive() -> dict | None:
    """回傳 /json/version 或 None（port 沒開）。"""
    try:
        r = requests.get(f"{CDP_BASE}/json/version", timeout=3)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None  # silent-ok: CDP probe — None=port 未開，caller 皆檢查處理


def ensure_fb_chrome(wait_s: int = 25) -> dict | None:
    """確保 dedicated persistent-profile Chrome 開著並掛 CDP。

    已開 → 直接回 /json/version。沒開 → 用專用 profile 啟動一個真 GUI Chrome
    （非 headless、非老闆主 Chrome），poll 到 CDP 起來為止。回 version dict 或 None。

    這是 hourly tick 自癒的關鍵：reboot / crash / 老闆關掉 dedicated Chrome 後，
    tick 不再永久卡「port 沒開」，會自動重啟該 profile（登入 cookie 已持久化）。
    """
    ver = cdp_alive()
    if ver:
        return ver
    if not Path(CHROME_BIN).exists():
        print(f"[WARN] ensure_fb_chrome: 找不到 Chrome binary {CHROME_BIN}", file=sys.stderr)
        return None
    print(f"[INFO] CDP port {CDP_PORT} 沒開 → 啟動 dedicated profile Chrome（{FB_PROFILE_DIR}）")
    try:
        subprocess.Popen(
            [
                CHROME_BIN,
                f"--remote-debugging-port={CDP_PORT}",
                f"--user-data-dir={FB_PROFILE_DIR}",
                "--no-first-run",
                "--no-default-browser-check",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] ensure_fb_chrome: 啟動失敗 {e}", file=sys.stderr)
        return None
    deadline = time.time() + wait_s
    while time.time() < deadline:
        time.sleep(1.5)
        ver = cdp_alive()
        if ver:
            print(f"[OK] dedicated Chrome 已就緒（{ver.get('Browser')}）")
            return ver
    print(f"[WARN] ensure_fb_chrome: 等 {wait_s}s CDP 仍未起", file=sys.stderr)
    return None


def parse_draft(path: Path) -> tuple[str, str, list[str]]:
    """從 FB draft .md 抽出 (主貼文純文字, 第一則留言連結, 附圖 URL 清單)。

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
    # 附圖：## 圖片 區塊下的所有圖 URL（結果圖 + 懶人包）。主貼文必附圖（老闆規則）。
    images: list[str] = []
    m_img = re.search(r"##\s*圖片[^\n]*\n(.*)$", text, re.S)
    if m_img:
        images = re.findall(r"https?://\S+?\.(?:png|jpg|jpeg|webp)", m_img.group(1))
    if not body:
        raise ValueError(f"{path.name}: 主貼文抽取為空")
    return body, link, images


def _download_images(urls: list[str]) -> list[str]:
    """下載附圖到 /tmp/fb_realchrome/img，回本地路徑（供 composer set_input_files）。
    任一張失敗只 warn 跳過；全失敗回空 list（caller 決定是否 abort）。"""
    out: list[str] = []
    d = SHOT_DIR / "img"
    d.mkdir(parents=True, exist_ok=True)
    for i, u in enumerate(urls):
        try:
            r = requests.get(u, timeout=30)
            r.raise_for_status()
            ext = os.path.splitext(u.split("?")[0])[1] or ".png"
            fp = d / f"img_{int(time.time())}_{i}{ext}"
            fp.write_bytes(r.content)
            out.append(str(fp))
        except Exception as e:  # noqa: BLE001
            print(f"[WARN] 下載附圖失敗 {u}: {e}", file=sys.stderr)
    return out


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
        pass  # silent-ok: 登入態偵測 best-effort，例外→'unknown' 由 caller WARN 處理
    return "unknown"


def _add_first_comment(page, body: str, link: str) -> None:
    """在剛發的貼文底下補第一則留言（連結）。用主文第一行前段當 anchor，在 timeline
    以 JS innerText 比對定位「該貼文」的留言 textbox（profile 頁 div[role='article']
    不穩，2026-07-07 改此法驗證可行），type URL（ASCII 不亂碼）+ Enter 送出。"""
    anchor = body.strip().splitlines()[0][:12]
    page.goto(FB_PROFILE_URL, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_timeout(3_500)
    page.mouse.wheel(0, 1250)  # 捲過置頂貼文，露出最新貼文
    page.wait_for_timeout(2_500)
    js = """
    (anchor) => {
      const boxes = Array.from(document.querySelectorAll('div'));
      for (const box of boxes) {
        const t = box.innerText || '';
        if (t.includes(anchor) && t.includes('的身分留言') && t.length < 1400) {
          const cb = box.querySelector('div[role="textbox"]');
          if (cb) return cb;
        }
      }
      return null;
    }
    """
    handle = page.evaluate_handle(js, anchor)
    el = handle.as_element()
    if not el:
        raise RuntimeError(f"找不到含「{anchor}」貼文的留言框")
    el.scroll_into_view_if_needed()
    el.click()
    page.wait_for_timeout(800)
    page.keyboard.type(link, delay=12)
    page.wait_for_timeout(3_500)  # 等連結預覽
    page.keyboard.press("Enter")
    page.wait_for_timeout(4_500)
    print(f"[OK] 第一則留言已送出：{link}")


def cmd_check() -> int:
    ver = ensure_fb_chrome()
    if not ver:
        print(f"[FAIL] CDP port {CDP_PORT} 沒開且自動啟動失敗 — 見 docs/fb_realchrome_setup.md")
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


def cmd_post(draft_path: Path, dry_run: bool, force: bool = False) -> int:
    body, link, images = parse_draft(draft_path)
    print(f"[INFO] draft: {draft_path.name}")
    print(f"[INFO] 主貼文 {len(body)} 字；留言連結: {link or '(無)'}；附圖 {len(images)} 張")

    # ── Idempotency guard（2026-07-07 雙發文 incident 根治）─────────────
    # 根因：兩 session（早前 close + hourly dispatch）同時發同一 mile，腳本從不
    # 讀 canonical fb_post_status → 老闆個人頁重複貼文。dry-run 不 claim（不改狀態）。
    mile_id = _mile_id_from_draft(draft_path)
    if not dry_run:
        if not mile_id:
            print("[WARN] 抽不出 mile_id → 無法做 idempotency guard，續發（風險：可能重發）")
        else:
            ok_claim, why = _claim_fb_post(mile_id, force=force)
            print(f"[INFO] idempotency claim（{mile_id}）: {why}")
            if not ok_claim:
                print(f"[SKIP] 不重發：{why}")
                return 0  # 已發過/in-flight 是正常 idempotent 結果，非錯誤

    if not ensure_fb_chrome():
        print(f"[FAIL] CDP port {CDP_PORT} 沒開且自動啟動失敗")
        if not dry_run and mile_id:
            _finalize_fb_post(mile_id, ok=False)
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
                continue  # silent-ok: 逐一試 composer selector，全失敗由 opened=False→ABORT
        if not opened:
            shot = SHOT_DIR / f"post_no_composer_{int(time.time())}.png"
            page.screenshot(path=str(shot))
            print(f"[ABORT] 找不到 composer 觸發鈕，截圖 {shot}")
            browser.close()
            return 4
        page.wait_for_timeout(2_500)

        # 2) 貼主文：聚焦 composer DIALOG 內的 contenteditable → Cmd+V
        # 2026-07-07 fix：`.first` 原本會抓到背景 profile 頁的留言框
        # （aria-label='以 Ivan Lai 的身分留言'），被 composer modal overlay 攔截 →
        # click timeout。scope 到 div[role='dialog'] 只剩 composer 那一個 textbox。
        editor = page.locator(
            "div[role='dialog'] div[role='textbox'][contenteditable='true']"
        ).first
        editor.wait_for(state="visible", timeout=8_000)
        editor.click(timeout=8_000)
        page.wait_for_timeout(500)

        # 清掉任何被 FB 自動還原的舊草稿（上一輪殘留 / link preview），確保從空白開始，
        # 否則 paste 會 append 在舊內容後面（例如上一輪那條 life.tw URL）。
        page.keyboard.press("Meta+A")
        page.keyboard.press("Delete")
        page.wait_for_timeout(400)

        # 移除任何被還原的連結預覽卡（主文不放連結 → 連結進第一則留言）。Meta+A+Delete
        # 只清文字，附著的 link preview 卡要另外按「移除貼文的連結預覽」/「全部移除」。
        for rm_label in ["移除貼文的連結預覽", "全部移除"]:
            try:
                rm = page.locator(f"div[role='dialog'] [aria-label='{rm_label}']").first
                if rm.count() > 0:
                    rm.click(timeout=4_000)
                    page.wait_for_timeout(800)
                    print(f"[INFO] 已移除殘留附件卡（{rm_label}）")
            except Exception as e:  # noqa: BLE001
                print(f"[WARN] 移除附件卡失敗（{rm_label}，可能本來就沒有）: {e}")

        # 2026-07-07 fix：剪貼簿是共享、易被搶的資源。開場的 pbcopy 到這裡已隔 ~10s，
        # 期間老闆/系統/Universal Clipboard 可能覆蓋（dry-run 實測貼到一條 life.tw URL）。
        # 改成「貼上前一刻」再 pbcopy，並用 pbpaste 驗證剪貼簿 == 主文，錯了就 abort。
        subprocess.run(["pbcopy"], input=body.encode("utf-8"), check=True)
        clip = subprocess.run(["pbpaste"], capture_output=True, text=True).stdout
        if clip.strip() != body.strip():
            shot = SHOT_DIR / f"post_clip_mismatch_{int(time.time())}.png"
            page.screenshot(path=str(shot))
            print(f"[ABORT] 剪貼簿驗證失敗（pbcopy 後 pbpaste != 主文）→ 不貼；截圖 {shot}")
            browser.close()
            return 5
        page.keyboard.press("Meta+V")
        page.wait_for_timeout(2_000)

        # 貼上後回讀 composer 內容，確認真的是主文（防剪貼簿在貼上瞬間又被搶）。
        # 不符 → abort，即使 dry-run 也標紅，絕不讓髒資料進到「可發佈」狀態。
        composed = editor.inner_text(timeout=5_000)
        shot = SHOT_DIR / f"post_composed_{int(time.time())}.png"
        page.screenshot(path=str(shot))
        head = body.strip()[:16]
        if head not in composed:
            print(f"[ABORT] composer 內容與主文不符（剪貼簿可能被搶）→ 不貼；截圖 {shot}")
            print(f"        期望開頭: {head!r}")
            print(f"        實際開頭: {composed.strip()[:60]!r}")
            browser.close()
            return 6
        print(f"[INFO] 主文已填入 composer 並驗證一致（{len(composed)} 字），截圖 {shot}")

        # 2.5) 附圖（主貼文必附圖：結果圖 + 懶人包，老闆硬規則 2026-07-07）。
        #      下載圖 → composer 的 input[type=file] set_input_files（隱藏 input 也可）。
        if images:
            local = _download_images(images)
            if not local:
                print("[ABORT] 附圖全下載失敗 → 不發（主貼文必附圖）")
                browser.close()
                return 8
            try:
                finp = page.locator("div[role='dialog'] input[type='file']").first
                if finp.count() == 0:
                    finp = page.locator("input[type='file']").first
                finp.set_input_files(local)
                page.wait_for_timeout(3_000 + 1_500 * len(local))  # 等縮圖上傳
                thumbs = page.locator(
                    "div[role='dialog'] img[src^='blob:'], div[role='dialog'] img[src^='data:']"
                ).count()
                shot = SHOT_DIR / f"post_with_images_{int(time.time())}.png"
                page.screenshot(path=str(shot))
                print(f"[INFO] 已附 {len(local)} 張圖（縮圖偵測 {thumbs}），截圖 {shot}")
                if thumbs == 0:
                    print("[ABORT] 附圖後偵測不到縮圖 → 不發（主貼文必附圖）")
                    browser.close()
                    return 8
            except Exception as e:  # noqa: BLE001
                shot = SHOT_DIR / f"post_image_fail_{int(time.time())}.png"
                page.screenshot(path=str(shot))
                print(f"[ABORT] 附圖失敗 → 不發（主貼文必附圖）: {e}；截圖 {shot}")
                browser.close()
                return 8
        else:
            print("[WARN] draft 無 ## 圖片 → 純文字貼文（老闆規則：主貼文應附圖，建議補圖）")

        if dry_run:
            print("[DRY-RUN] 停在送出前一步，不按「發佈」。人工看截圖確認 composer 正確。")
            browser.close()
            return 0

        # 發佈前最終安全檢查：主文不放連結，若還殘留任何連結預覽卡（移除失敗）→ abort，
        # 絕不帶著錯圖真發（老闆 2026-07-07「圖不對」教訓）。
        if page.locator("div[role='dialog'] [aria-label='移除貼文的連結預覽']").count() > 0:
            shot = SHOT_DIR / f"post_preview_stuck_{int(time.time())}.png"
            page.screenshot(path=str(shot))
            print(f"[ABORT] 發佈前仍偵測到連結預覽卡（移除失敗）→ 不發；截圖 {shot}")
            browser.close()
            return 7

        # 3) 送出：FB 個人頁 composer 是兩段式 — 先「繼續」進「貼文設定」步驟再「發佈」
        #    （2026-07-07 實測 profile composer 走兩段）；相容單段式（直接有「發佈」）。
        def _click_dialog_btn(aria_labels, timeout=8_000):
            for al in aria_labels:
                try:
                    el = page.locator(f"div[role='dialog'] [aria-label='{al}']").first
                    if el.count() > 0 and el.is_visible():
                        el.click(timeout=timeout)
                        return True
                except Exception as e:  # noqa: BLE001
                    print(f"[WARN] 點「{al}」失敗: {e}")
            return False

        posted = _click_dialog_btn(["發佈"])
        if not posted and _click_dialog_btn(["繼續"]):
            page.wait_for_timeout(2_500)  # 進「貼文設定」步驟
            posted = _click_dialog_btn(["發佈"])
        if not posted:
            shot = SHOT_DIR / f"post_no_publish_{int(time.time())}.png"
            page.screenshot(path=str(shot))
            print(f"[ABORT] 找不到「發佈」鈕（繼續後也沒有），截圖 {shot}")
            browser.close()
            return 5
        page.wait_for_timeout(7_000)  # 等貼文送出
        shot = SHOT_DIR / f"post_done_{int(time.time())}.png"
        page.screenshot(path=str(shot))
        print(f"[OK] 主文已送出，截圖 {shot}")

        # 4) 第一則留言補連結（主文不放連結 → 連結進留言引流）。2026-07-07 驗證可行。
        if link:
            try:
                _add_first_comment(page, body, link)
            except Exception as e:  # noqa: BLE001
                shot = SHOT_DIR / f"comment_fail_{int(time.time())}.png"
                page.screenshot(path=str(shot))
                print(f"[WARN] 第一則留言補連結失敗（主文已發，連結需手動補）: {e}；截圖 {shot}")
        browser.close()
        # 發文成功 → 標 canonical fb_post_status=success + ledger done，
        # 之後任何 session/tick 再發同一 mile 會被 idempotency guard 擋下。
        if not dry_run and mile_id:
            _finalize_fb_post(mile_id, ok=True)
        return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="FB real-Chrome CDP-attach 發文 worker")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true", help="安全模式：驗 attach + 登入狀態")
    g.add_argument("--post", metavar="DRAFT", help="發文：FB draft .md 路徑")
    ap.add_argument("--dry-run", action="store_true", help="搭配 --post：停在送出前")
    ap.add_argument("--force", action="store_true",
                    help="繞過 idempotency guard 強制重發（已發過的 mile 也重貼；慎用）")
    args = ap.parse_args()

    if args.check:
        return cmd_check()
    return cmd_post(Path(args.post), args.dry_run, force=args.force)


if __name__ == "__main__":
    sys.exit(main())
