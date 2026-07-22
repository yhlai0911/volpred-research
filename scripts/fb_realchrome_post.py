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
    """從 FB draft 抽 mile_id，依可靠度依序嘗試：
      1. 「# mile_id: mile_XXX」註解
      2. 內文的 VolPred report 連結（第一則留言必含，例如 /reports/mile_XXX）
      3. 檔名 fb_mile_XXX.md

    (2) 是 2026-07-13 補的：event_article 的 draft 住在
    storage/event_articles/<slug>/fb_draft.md，既無註解也不合檔名慣例 →
    guard 抽不到 mile_id 就直接放行，等於對外發文完全沒有冪等保護
    （違反 memory feedback_fb_post_idempotency_guard）。連結是每篇 draft
    都有的欄位，拿它當 fallback 才涵蓋得到非 storage/drafts/ 的 draft。

    找不到回 None（guard 會 warn 但不硬擋）。"""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] 讀 draft 抽 mile_id 失敗: {e}", file=sys.stderr)
        text = ""
    for pattern in (
        r"#\s*mile_id:\s*(mile_[0-9a-fA-F]+)",
        r"/reports/(mile_[0-9a-fA-F]+)",
    ):
        m = re.search(pattern, text)
        if m:
            return m.group(1)
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


def _finalize_fb_post(mile_id: str, *, ok: bool,
                      post_url: str | None = None, posted_at: str | None = None) -> None:
    """發文結束標記：ok=True → canonical fb_post_status=success + ledger done；
    ok=False → ledger 清 in-flight（讓下次能重試），不動 canonical status。
    post_url / posted_at 若抓到則一併寫入 canonical（feed + trending log）。"""
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
                                   note="fb_realchrome_post 發文成功自動標記",
                                   post_url=post_url, posted_at=posted_at)
            print(f"[OK] canonical fb_post_status→success（feed={res['updated_feed']} log={res['updated_log']}）"
                  f"{' url✓' if post_url else ' url✗(未抓到)'}"
                  f"{' posted_at✓' if posted_at else ''}")
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
      <可有引言句>
      <url>
    """
    text = path.read_text(encoding="utf-8")
    # 主貼文：介於「## 主貼文」與「## 第一則留言」之間
    m_body = re.search(
        r"##\s*主貼文[^\n]*\n(.*?)\n##\s*第一則留言",
        text,
        re.S,
    )
    # 留言連結：取「## 第一則留言」區塊內的第一個 URL，而不是只認緊接標題的裸 URL。
    # 2026-07-22：mile_903fd2cf 的稿在 URL 前寫了一句引言（人寫稿的自然寫法），舊 regex
    # 因此靜默回空字串 → 主文照發、連結沒進留言。留言送出走 keyboard.type(link) 只打
    # URL，引言本來就不會被貼上，所以正解是放寬抽取而非要求寫稿人把 URL 頂在標題下。
    m_link_block = re.search(r"##\s*第一則留言[^\n]*\n(.*?)(?=\n##\s|\Z)", text, re.S)
    m_link = re.search(r"https?://\S+", m_link_block.group(1)) if m_link_block else None
    if not m_body:
        raise ValueError(f"{path.name}: 找不到「## 主貼文」區塊")
    body = m_body.group(1).strip()
    # 去掉分隔線 --- 與註解行
    body = "\n".join(
        ln for ln in body.splitlines()
        if ln.strip() != "---" and not ln.lstrip().startswith("#")
    ).strip()
    link = m_link.group(0).strip() if m_link else ""
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


# 2026-07-08 3-strike fix — 真實 attached-photo 計數（fb_mile_e1ff7ef9 連 4 次 ABORT root cause）。
# 舊做法 `div[role='dialog'] img[blob/data]` 跨所有 dialog 累加（含通知 dialog 的縮圖）→ 恆 >N。
# 正解：scope 到唯一同時有 file input + contenteditable editor 的 composer dialog，計其中 blob:
# img 且渲染尺寸 ≥60px（排除 0×0 svg/data 圖示）。live DOM 驗證：清空前 4→cleanup 後 0→附 2 後 2。
_COMPOSER_PHOTO_COUNT_JS = """() => {
  const dlgs = [...document.querySelectorAll("div[role='dialog']")];
  const comp = dlgs.find(d =>
    d.querySelector("input[type='file']") &&
    d.querySelector("div[role='textbox'][contenteditable='true']"));
  if (!comp) return -1;
  return [...comp.querySelectorAll("img[src^='blob:']")].filter(img => {
    const r = img.getBoundingClientRect();
    return r.width >= 60 && r.height >= 60;
  }).length;
}"""


def _composer_photo_count(page) -> int:
    """回 composer dialog 內真實 attached photo 數；找不到 composer 回 -1。"""
    return page.evaluate(_COMPOSER_PHOTO_COUNT_JS)


def _composer_dialog(page):
    """回「建立貼文」composer dialog 的 Locator。

    2026-07-20 3-strike fix — 頁面上常同時開著**多個** `div[role='dialog']`：
    上一輪 --check 停在某篇貼文的 permalink，那個「Ivan Lai 的貼文」dialog 也含
    contenteditable 留言框，且在 DOM 排序中先於 composer → 舊的
    `div[role='dialog'] div[role=textbox]`.first 會抓到**舊貼文的留言框**。
    dry-run 實測：整篇 464 字主文被貼進 6/3 那篇 CPI 貼文的留言框，圖卻附在真正的
    composer 上；真發會產出「舊文一則長留言 + 一篇無字純圖新貼文」。

    判準與 _COMPOSER_PHOTO_COUNT_JS 一致：composer 是唯一同時具備 file input
    與 contenteditable textbox 的 dialog。填字與附圖共用這一個定義，不再各自 `.first`。
    """
    return (
        page.locator("div[role='dialog']")
        .filter(has=page.locator("input[type='file']"))
        .filter(has=page.locator("div[role='textbox'][contenteditable='true']"))
        .first
    )


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


def _post_anchor(body: str) -> str:
    """主貼文第一行前 12 字當 timeline 定位 anchor（與 _add_first_comment 一致）。"""
    s = (body or "").strip()
    return s.splitlines()[0][:12] if s else ""


def _capture_permalink(page, anchor: str) -> str | None:
    """在 profile timeline 抓「含 anchor 文字之貼文」的永久連結。策略：掃所有
    permalink-shaped <a>，往上找 ≤8 層祖先其 innerText 含 anchor（= 確定是該貼文）
    才回該連結；**anchor 完全沒匹配任何連結祖先 → 回 None**（誠實：不猜、不用 DOM
    第一個連結頂替，避免把別篇貼文的 permalink 誤寫進 canonical，2026-07-09 review
    finding 1）。回傳去掉 query string 的乾淨 URL。抓不到只回 None（非阻塞，主文已發）。"""
    if not anchor:
        return None
    js = r"""
    (anchor) => {
      const links = Array.from(document.querySelectorAll('a[href]')).filter(a => {
        const h = a.href || '';
        return h.includes('/posts/') || h.includes('story_fbid') ||
               h.includes('/permalink/') || h.includes('/pfbid');
      });
      for (const a of links) {
        let node = a;
        for (let i = 0; i < 8 && node; i++) {
          if ((node.innerText || '').includes(anchor)) return a.href.split('?')[0];
          node = node.parentElement;
        }
      }
      return null;  // anchor 沒匹配任何 permalink 連結的祖先 → 不猜（誠實 fail）
    }
    """
    try:
        url = page.evaluate(js, anchor)
        if url:
            print(f"[OK] 抓到貼文永久連結（anchor 比對命中）：{url}")
        else:
            print(f"[WARN] 抓 permalink：timeline 找不到含「{anchor}」的貼文永久連結"
                  "（可能已捲太下 / 已刪 / anchor 不符）→ 不寫 URL（非阻塞）", file=sys.stderr)
        return url or None
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] 抓 permalink 失敗（非阻塞）: {e}", file=sys.stderr)
        return None


def _locate_comment_box(page, anchor: str = ""):
    """以 JS innerText 比對定位「含 anchor 的那篇貼文」的留言 textbox。

    profile 頁 div[role='article'] 不穩（2026-07-07 改此法驗證可行）：改掃所有 div，
    找同時含 anchor 與「的身分留言」且夠小（<1400 字）的容器，取其 role=textbox。
    anchor="" 用於**單篇 permalink 頁**（頁上只有一篇貼文，不需 anchor 消歧）。
    """
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
    el = page.evaluate_handle(js, anchor).as_element()
    if not el:
        raise RuntimeError(f"找不到含「{anchor}」貼文的留言框")
    return el


def _verify_comment_sent(page, el, needle: str) -> bool:
    """送出後回讀確認：留言框清空 + 頁面出現 needle。

    2026-07-19：原本無條件印 [OK]。實測 mile_29018fa1 這樣誤報成功，貼文實際 0 留言，
    引流連結整篇掉了。送出後一律回讀，不回讀不算成功。
    """
    for _ in range(6):
        cleared = (el.inner_text() or "").strip() == ""
        shown = needle in page.evaluate("() => document.body.innerText")
        if cleared and shown:
            return True
        page.wait_for_timeout(2_500)
    return False


def _add_first_comment(page, body: str, link: str) -> None:
    """在剛發的貼文底下補第一則留言（連結）。用主文第一行前段當 anchor，在 timeline
    定位「該貼文」的留言 textbox，type URL（ASCII 不亂碼）+ Enter 送出。"""
    anchor = body.strip().splitlines()[0][:12]
    # 2026-07-19：原本 domcontentloaded + 3.5s 就掃 DOM，profile feed 常還沒 render
    # （實測 body innerText 僅 2170 字、滿頁佔位）→ 定位不到貼文。改等 load + 15s，
    # 並把「其他貼文」捲進視窗讓最新貼文真正掛上 DOM。
    page.goto(FB_PROFILE_URL, wait_until="load", timeout=90_000)
    page.wait_for_timeout(15_000)
    try:
        page.get_by_text("其他貼文", exact=True).first.scroll_into_view_if_needed(timeout=15_000)
    except Exception:
        page.mouse.wheel(0, 1250)  # fallback: 捲過置頂貼文，露出最新貼文
    page.wait_for_timeout(5_000)
    el = _locate_comment_box(page, anchor)
    el.scroll_into_view_if_needed()
    el.click()
    page.wait_for_timeout(800)
    page.keyboard.type(link, delay=12)
    page.wait_for_timeout(3_500)  # 等連結預覽
    page.keyboard.press("Enter")
    page.wait_for_timeout(4_500)
    if _verify_comment_sent(page, el, link.rsplit("/", 1)[-1]):
        print(f"[OK] 第一則留言已送出並驗證：{link}")
        return
    raise RuntimeError(f"留言送出後驗證失敗（留言框未清空或頁面查無連結）：{link}")


def cmd_delete_matching(anchor: str, confirm: bool) -> int:
    """在 Ivan Lai 個人 timeline 找含 `anchor` 的最新貼文並（可選）刪除。

    兩段式風控（撤掉重發用；SKILL §誠實邊界「刪除既有貼文是對外破壞性動作」）：
      - 無 --confirm-delete：只定位 + 截圖目標貼文，人工/回讀驗證是「該篇」，不刪。
      - 有 --confirm-delete：截圖後開該貼文 ⋯ 選單 → 移至垃圾桶 → 確認，並截圖後狀態。
    """
    from playwright.sync_api import sync_playwright

    ver = ensure_fb_chrome()
    if not ver:
        print(f"[FAIL] CDP port {CDP_PORT} 沒開且自動啟動失敗 — 見 docs/fb_realchrome_setup.md")
        return 2
    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = _connect(pw)
        page = _get_or_open_fb_page(browser)
        if _login_state(page) == "login_wall":
            print("[FAIL] FB 未登入 — 只有老闆能在 dedicated Chrome 手動登入")
            return 2
        page.goto(FB_PROFILE_URL, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(6_000)  # profile 貼文 render 較慢
        # 漸進小捲直到 anchor 進 DOM，並把它捲進視窗中央（FB 虛擬捲動：捲太多會 unmount
        # 目標貼文 → 幾何定位失敗，2026-07-07 T2 教訓）。找到就 scrollIntoView 保持 mounted。
        found = False
        for _ in range(8):
            hit = page.evaluate("""(anchor)=>{
              const w=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
              let n; while(n=w.nextNode()){ if((n.nodeValue||'').includes(anchor)){
                n.parentElement.scrollIntoView({block:'center'}); return true; } }
              return false; }""", anchor)
            if hit:
                found = True
                break
            page.mouse.wheel(0, 700)
            page.wait_for_timeout(1_800)
        if not found:
            print(f"[FAIL] 捲動 8 次仍找不到含「{anchor}」的貼文（可能已刪 / anchor 不符）")
            return 3
        page.wait_for_timeout(1_500)
        # 幾何定位（2026-07-07 T2：舊「最小容器」heuristic 誤配 → 改用「貼文正文位置 +
        # 該貼文動作選單 ⋯ 按鈕正上方」幾何鎖定，可驗證）：
        #   1) 找含 anchor 的正文 text node bounding box
        #   2) FB 每則貼文 ⋯ 的 aria-label = 「對<名字>的這則貼文採取的動作」
        #   3) 取「y 在正文之上、且最接近正文」的那顆 ⋯ = 該貼文 header 的動作鈕
        find_js = """
        (anchor) => {
          const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
          let node, bodyEl = null;
          while (node = walk.nextNode()) {
            if ((node.nodeValue || '').includes(anchor)) { bodyEl = node.parentElement; break; }
          }
          if (!bodyEl) return null;
          const br = bodyEl.getBoundingClientRect();
          const btns = Array.from(document.querySelectorAll('[aria-label*="這則貼文採取的動作"],[aria-label*="更多選項"]'))
            .filter(e => e.getBoundingClientRect().width > 0);
          let best = null, bestGap = 1e9;
          for (const e of btns) {
            const r = e.getBoundingClientRect();
            const gap = br.y - r.y;                 // 正文在下、⋯ 在上 → gap>0
            if (gap >= 0 && gap < 200 && gap < bestGap) { best = e; bestGap = gap; }
          }
          if (!best) return null;
          best.setAttribute('data-vp-target', '1');
          return JSON.stringify({body: (bodyEl.innerText||'').slice(0,40), gap: Math.round(bestGap), al: best.getAttribute('aria-label')});
        }
        """
        matched = page.evaluate(find_js, anchor)
        if not matched:
            print(f"[FAIL] timeline 找不到含「{anchor}」的貼文或其動作鈕（可能已捲不到 / 已刪 / anchor 不符）")
            return 3
        print(f"[OK] 幾何定位到目標貼文的 ⋯：{matched}")
        target_btn = page.locator("div[data-vp-target='1']").first
        target_btn.scroll_into_view_if_needed()
        page.wait_for_timeout(600)
        shot = SHOT_DIR / f"delete_target_{int(page.evaluate('Date.now()'))}.png"
        page.screenshot(path=str(shot))
        print(f"[INFO] 目標貼文截圖：{shot}")
        if not confirm:
            print("[DRY] 未帶 --confirm-delete → 只定位+截圖，未刪除。人工驗證截圖是「該篇」後再帶 --confirm-delete 重跑。")
            return 0
        # 執行刪除：⋯ → 移到垃圾桶 → 確認（FB zh-TW 用字為「移到垃圾桶」，非「移至」）
        target_btn.click()
        page.wait_for_timeout(1_800)
        trash = page.get_by_text("移到垃圾桶", exact=False).first
        if trash.count() == 0:
            print("[FAIL] ⋯ 選單沒出現「移到垃圾桶」項 — FB UI 可能改版，未刪除")
            return 4
        trash.click()
        page.wait_for_timeout(2_000)
        # 確認 dialog：標題「移到垃圾桶？」，確認鈕文字/aria-label = 「移動」（不是「移到垃圾桶」）
        confirm_btn = page.locator("div[role='dialog'] [aria-label='移動'], div[role='dialog'] [role='button']:has-text('移動')").first
        if confirm_btn.count() == 0:
            print("[FAIL] 確認 dialog 找不到「移動」鈕 — 未完成刪除")
            return 4
        confirm_btn.click()
        page.wait_for_timeout(4_000)
        after = SHOT_DIR / f"delete_after_{int(page.evaluate('Date.now()'))}.png"
        page.screenshot(path=str(after))
        print(f"[OK] 已送出刪除，事後截圖：{after}")
        return 0


def cmd_comment_on(post_url: str, comment_file: Path, dry_run: bool) -> int:
    """對**既有**貼文補一則留言（更正說明 / 補連結用）。

    與 `_add_first_comment` 的差別只在定位方式：這裡直接 goto 單篇 permalink（頁上只有
    一篇貼文 → anchor="" 即可），留言框互動邏輯共用 `_locate_comment_box`。
    中文一律走剪貼簿整段貼上（keyboard.type 對中文 IME 會亂碼，SKILL §硬規則 4），
    並沿用發文路徑的「貼上前一刻 pbcopy + pbpaste 驗證 + composer 回讀」三重防剪貼簿被搶。

    --dry-run：貼完 + 截圖後停在送出前，不按 Enter。
    """
    from playwright.sync_api import sync_playwright

    text = comment_file.read_text(encoding="utf-8").strip()
    if not text:
        print(f"[FAIL] 留言檔為空：{comment_file}")
        return 2

    # 送出後回讀用的 needle：優先取留言內 URL 的末段（ASCII，最不易被 FB 改寫），
    # 沒有 URL 才退回中文前段。
    m = re.search(r"https?://\S+", text)
    needle = m.group(0).rstrip("/").rsplit("/", 1)[-1] if m else text[:12]

    ver = ensure_fb_chrome()
    if not ver:
        print(f"[FAIL] CDP port {CDP_PORT} 沒開且自動啟動失敗 — 見 docs/fb_realchrome_setup.md")
        return 2
    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = _connect(pw)
        page = _get_or_open_fb_page(browser)
        if _login_state(page) == "login_wall":
            print("[FAIL] FB 未登入 — 只有老闆能在 dedicated Chrome 手動登入")
            browser.close()
            return 3

        page.goto(post_url, wait_until="load", timeout=90_000)
        page.wait_for_timeout(8_000)
        try:
            el = _locate_comment_box(page, "")
        except RuntimeError as e:
            shot = SHOT_DIR / f"comment_on_nobox_{int(time.time())}.png"
            page.screenshot(path=str(shot))
            print(f"[FAIL] {e}；截圖 {shot}")
            browser.close()
            return 4
        el.scroll_into_view_if_needed()
        el.click()
        page.wait_for_timeout(800)

        subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)
        clip = subprocess.run(["pbpaste"], capture_output=True, text=True).stdout
        if clip.strip() != text:
            shot = SHOT_DIR / f"comment_on_clip_mismatch_{int(time.time())}.png"
            page.screenshot(path=str(shot))
            print(f"[ABORT] 剪貼簿驗證失敗（pbcopy 後 pbpaste != 留言）→ 不貼；截圖 {shot}")
            browser.close()
            return 5
        page.keyboard.press("Meta+V")
        page.wait_for_timeout(2_500)

        composed = el.inner_text() or ""
        shot = SHOT_DIR / f"comment_on_composed_{int(time.time())}.png"
        page.screenshot(path=str(shot))
        head = text[:16]
        if head not in composed:
            print(f"[ABORT] 留言框內容與留言檔不符（剪貼簿可能被搶）→ 不送出；截圖 {shot}")
            print(f"        期望開頭: {head!r}")
            print(f"        實際讀到: {composed[:60]!r}")
            browser.close()
            return 5
        print(f"[OK] 留言已貼入留言框（{len(text)} 字），截圖 {shot}")

        if dry_run:
            print("[DRY-RUN] 停在送出前，未按 Enter。人工看上面截圖確認後再跑不帶 --dry-run 的版本。")
            browser.close()
            return 0

        page.keyboard.press("Enter")
        page.wait_for_timeout(5_000)
        ok = _verify_comment_sent(page, el, needle)
        shot = SHOT_DIR / f"comment_on_{'done' if ok else 'fail'}_{int(time.time())}.png"
        page.screenshot(path=str(shot))
        browser.close()
        if ok:
            print(f"[OK] 留言已送出並驗證（needle={needle!r}）；截圖 {shot}")
            return 0
        print(f"[FAIL] 留言送出後驗證失敗（留言框未清空或頁面查無 {needle!r}）；截圖 {shot}")
        return 6


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


def cmd_recapture_permalink(mile_id: str, posted_at: str | None = None) -> int:
    """回補既有已發貼文的 permalink（+ 選填 posted_at）：讀 canonical FB 稿取 anchor →
    導 timeline 抓永久連結 → 走正式 writer update_fb_status 回寫 canonical。
    給「發文成功但 fb_post_url 仍 null」的歷史 mile 補救用（不修資料、走流程）。"""
    try:
        from mark_fb_post_status import canonical_fb_draft_path, update_fb_status  # type: ignore
    except Exception:
        sys.path.insert(0, str(ROOT / "scripts"))
        from mark_fb_post_status import canonical_fb_draft_path, update_fb_status  # type: ignore

    # 前置檢查：只回補「已成功發文」的 mile — 避免對從未發過的 mile（pending /
    # wont_fix / reject）抓到別篇貼文連結並誤標 success 污染 canonical（2026-07-09 review finding 2）。
    st = _fb_post_status(mile_id)
    if st != "success":
        print(f"[FAIL] {mile_id} canonical fb_post_status={st or '(無)'} ≠ success → "
              "recapture 只回補已成功發文的 mile；請先確認該貼文確實已發出")
        return 2

    draft_path = canonical_fb_draft_path(mile_id)
    if not draft_path.exists():
        print(f"[FAIL] 找不到 canonical FB 稿 {draft_path} → 無 anchor 可定位貼文")
        return 2
    body, _link, _images = parse_draft(draft_path)
    anchor = _post_anchor(body)
    if not anchor:
        print(f"[FAIL] 稿 {draft_path} 主貼文為空 → 無 anchor")
        return 2

    ver = ensure_fb_chrome()
    if not ver:
        print(f"[FAIL] CDP port {CDP_PORT} 沒開且自動啟動失敗 — 見 docs/fb_realchrome_setup.md")
        return 2
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = _connect(pw)
        page = _get_or_open_fb_page(browser)
        page.goto(FB_PROFILE_URL, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(3_500)
        # 漸進捲動找較舊貼文：每捲一段就試抓；anchor 命中即停（_capture_permalink
        # anchor 沒命中回 None，不會誤抓別篇）。最多 6 段涵蓋 timeline 前段。
        post_url = None
        for i in range(6):
            page.mouse.wheel(0, 1250)
            page.wait_for_timeout(2_200)
            post_url = _capture_permalink(page, anchor)
            if post_url:
                break
        browser.close()

    if not post_url:
        print(f"[FAIL] timeline 定位不到含「{anchor}」貼文的永久連結（可能已捲太下 / 已刪）")
        return 1
    res = update_fb_status(mile_id, status="success",
                           note="permalink recapture 回補", post_url=post_url, posted_at=posted_at)
    print(f"[OK] {mile_id} 回補 fb_post_url={post_url}"
          f"{f' fb_posted_at={posted_at}' if posted_at else ''}"
          f"（feed={res['updated_feed']} log={res['updated_log']}）")
    return 0 if (res["updated_feed"] or res["updated_log"]) else 1


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

        # 2026-07-20 fix：--check 等前一輪操作會把分頁留在某篇貼文的 permalink，
        # 那頁的「Ivan Lai 的貼文」dialog 帶著留言框，是上面 _composer_dialog 要閃避的
        # 污染源本身。發文前先回個人頁根，讓 composer 是頁面上唯一的 dialog。
        if "/posts/" in (page.url or "") or "permalink" in (page.url or ""):
            print(f"[INFO] 分頁停在貼文 permalink → 導回個人頁再發（原 URL: {page.url}）")
            page.goto(FB_PROFILE_URL, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(3_000)

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
            # 2026-07-19 fix：click 的 actionability 等待可能在 FB 重繪時 timeout，
            # 但點擊本身已送達、composer 正在開（skeleton）→ 只看例外會誤判 ABORT。
            # 以「dialog 是否真的出現」為準，而非 click 的回傳。
            page.wait_for_timeout(3_000)
            try:
                _composer_dialog(page).locator(
                    "div[role='textbox'][contenteditable='true']"
                ).first.wait_for(state="visible", timeout=8_000)
                opened = True
                print("[INFO] click 回報失敗但 composer 已開 → 續行")
            except Exception:
                pass  # silent-ok: 確認 composer 真的沒開 → 落到下面 ABORT
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
        # 2026-07-20 fix：頁面可同時有多個 dialog（舊貼文 permalink 也含留言框）→
        # 改用 _composer_dialog() 的 file-input+textbox 判準精確鎖定，見該函式 docstring。
        composer = _composer_dialog(page)
        editor = composer.locator(
            "div[role='textbox'][contenteditable='true']"
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
                rm = composer.locator(f"[aria-label='{rm_label}']").first
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
                # 2026-07-08 3-strike fix（fb_mile_e1ff7ef9 連 4 次 ABORT root cause）：
                # 舊偵測 `div[role='dialog'] img[blob/data]` 有兩個致命缺陷，實 DOM dump 證實：
                #   (1) `div[role='dialog']` 不唯一 — 頁面同時有通知/其他 dialog，其 blob 縮圖
                #       被跨 dialog 累加（notif dialog=+1）→ thumbs 恆 > N。
                #   (2) 舊 cleanup 用 `移除相片`/`Remove photo` aria-label，但 current DOM 無此
                #       label（每張照片無獨立 remove 鈕），cleanup 空操作 → 殘留照片累積。
                # 修法（已 live-composer 驗證：清空前 4 → cleanup 後 0 → 附 2 後 2）：
                #   - scope 到唯一同時有 file input + editor 的 composer dialog（排除通知 dialog）
                #   - cleanup 點單一「移除貼文附件」鈕（一次清空全部附件）
                #   - 計 composer 內 blob: img 且渲染尺寸≥60px（排除 0×0 svg/data 圖示）= 真實張數
                for _ in range(6):
                    rm = composer.locator(
                        "[aria-label='移除貼文附件'], [aria-label='Remove attachment']"
                    ).first
                    if rm.count() == 0 or not rm.is_visible():
                        break
                    rm.click(timeout=4_000)
                    page.wait_for_timeout(700)
                pre = _composer_photo_count(page)
                if pre > 0:
                    print(f"[INFO] 清除既存 composer 照片後仍偵測 {pre} 張殘留（將於附圖後校驗總數）")
                elif pre < 0:
                    print("[ABORT] 找不到 composer dialog（無 file input + editor）→ 不發")
                    browser.close()
                    return 8
                # 2026-07-20 fix — composer dialog 內不只一個 file input，且 `.first` 命中的
                # 那個沒有 `multiple` 屬性（accept 清單以 video/* 開頭），多檔 set 會炸
                # "Non-multiple file input can only accept single file" → 附圖 ABORT。
                # 正解：優先挑帶 `multiple` 的 input；真的只有單檔 input 時逐張附上
                # （FB 單檔 input 每次 set 是「再加一張」，不是替換），最後仍由下方
                # _composer_photo_count 校驗總數，附不齊照樣 ABORT。
                finp = composer.locator("input[type='file'][multiple]").first
                if finp.count() == 0:
                    finp = composer.locator("input[type='file']").first
                if finp.evaluate("el => el.multiple"):
                    finp.set_input_files(local)
                else:
                    print(f"[INFO] file input 不支援多檔 → 逐張附上 {len(local)} 張")
                    for one in local:
                        finp.set_input_files(one)
                        page.wait_for_timeout(1_500)
                page.wait_for_timeout(3_000 + 1_500 * len(local))  # 等縮圖上傳
                # 照片 tile 可能稍晚 render；poll 至達 N 或穩定（≤6s 額外等待）
                thumbs = _composer_photo_count(page)
                for _ in range(6):
                    if thumbs >= len(local):
                        break
                    page.wait_for_timeout(1_000)
                    thumbs = _composer_photo_count(page)
                shot = SHOT_DIR / f"post_with_images_{int(time.time())}.png"
                page.screenshot(path=str(shot))
                print(f"[INFO] 已附 {len(local)} 張圖（composer 照片偵測 {thumbs}），截圖 {shot}")
                if thumbs == 0:
                    print("[ABORT] 附圖後 composer 偵測不到照片 → 不發（主貼文必附圖）")
                    browser.close()
                    return 8
                if thumbs != len(local):
                    print(f"[ABORT] composer 照片數 {thumbs} ≠ 預期 {len(local)}（有殘留/重複照片）→ 不發，"
                          f"避免重現「圖片重複」；截圖 {shot}")
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
        posted_at_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")  # 真發文時間戳
        shot = SHOT_DIR / f"post_done_{int(time.time())}.png"
        page.screenshot(path=str(shot))
        print(f"[OK] 主文已送出，截圖 {shot}")

        # 4) 第一則留言補連結（主文不放連結 → 連結進留言引流）。2026-07-07 驗證可行。
        #    _add_first_comment 已導到 timeline 定位貼文 → 順手抓 permalink（同一次載入）。
        anchor = _post_anchor(body)
        post_url: str | None = None
        if link:
            try:
                _add_first_comment(page, body, link)
            except Exception as e:  # noqa: BLE001
                shot = SHOT_DIR / f"comment_fail_{int(time.time())}.png"
                page.screenshot(path=str(shot))
                print(f"[WARN] 第一則留言補連結失敗（主文已發，連結需手動補）: {e}；截圖 {shot}")
            post_url = _capture_permalink(page, anchor)  # 留言後仍在 timeline
        else:
            # 無留言 → 主動導到 timeline 抓 permalink
            try:
                page.goto(FB_PROFILE_URL, wait_until="domcontentloaded", timeout=60_000)
                page.wait_for_timeout(3_500)
                page.mouse.wheel(0, 1250)
                page.wait_for_timeout(2_000)
                post_url = _capture_permalink(page, anchor)
            except Exception as e:  # noqa: BLE001
                print(f"[WARN] 導 timeline 抓 permalink 失敗（非阻塞）: {e}", file=sys.stderr)
        browser.close()
        # 發文成功 → 標 canonical fb_post_status=success + ledger done + permalink/posted_at，
        # 之後任何 session/tick 再發同一 mile 會被 idempotency guard 擋下。
        if not dry_run and mile_id:
            _finalize_fb_post(mile_id, ok=True, post_url=post_url, posted_at=posted_at_iso)
        return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="FB real-Chrome CDP-attach 發文 worker")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true", help="安全模式：驗 attach + 登入狀態")
    g.add_argument("--post", metavar="DRAFT", help="發文：FB draft .md 路徑")
    g.add_argument("--delete-matching", metavar="ANCHOR",
                   help="撤掉重發用：定位 timeline 含此文字的最新貼文並刪除（預設只截圖，需 --confirm-delete 才真刪）")
    g.add_argument("--comment-on", metavar="POST_URL",
                   help="對既有貼文補一則留言（更正說明/補連結）：需搭配 --comment-file")
    g.add_argument("--recapture-permalink", metavar="MILE_ID",
                   help="回補既有已發貼文的 fb_post_url（導 timeline 抓永久連結，走正式 writer 回寫 canonical）")
    ap.add_argument("--posted-at", metavar="ISO",
                    help="搭配 --recapture-permalink：一併回補 fb_posted_at（ISO8601）")
    ap.add_argument("--confirm-delete", action="store_true",
                    help="搭配 --delete-matching：截圖驗證後真的移至垃圾桶（對外破壞性動作）")
    ap.add_argument("--comment-file", metavar="PATH",
                    help="搭配 --comment-on：留言正文 .md 路徑（中文走剪貼簿整段貼上）")
    ap.add_argument("--dry-run", action="store_true", help="搭配 --post / --comment-on：停在送出前")
    ap.add_argument("--force", action="store_true",
                    help="繞過 idempotency guard 強制重發（已發過的 mile 也重貼；慎用）")
    args = ap.parse_args()

    if args.check:
        return cmd_check()
    if args.delete_matching:
        return cmd_delete_matching(args.delete_matching, confirm=args.confirm_delete)
    if args.comment_on:
        if not args.comment_file:
            ap.error("--comment-on 需要搭配 --comment-file")
        cf = Path(args.comment_file)
        if not cf.exists():
            ap.error(f"--comment-file 不存在：{cf}")
        return cmd_comment_on(args.comment_on, cf, args.dry_run)
    if args.recapture_permalink:
        return cmd_recapture_permalink(args.recapture_permalink, posted_at=args.posted_at)
    return cmd_post(Path(args.post), args.dry_run, force=args.force)


if __name__ == "__main__":
    sys.exit(main())
