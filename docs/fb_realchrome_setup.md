# FB 個人帳號自動發文 — real-Chrome CDP-attach 底層修復

**Task**: `platform-ops-fb-realchrome-autopost`（boss Telegram msg 237：「我就要你自動發，那能怎麼立刻從底層修復處理？」）

**Worker**: `scripts/fb_realchrome_post.py`

## 為什麼是這條 path

老闆釘死的約束（見 memory `feedback_fb_personal_account_chrome_only`、`docs/fb_pipeline_permanent_fix.md`）：
- ❌ 不用 Graph API（個人帳號無 headless 發文權，卡 App Review）
- ❌ 不用粉專
- ❌ 不用 headless Playwright / 假瀏覽器

現況痛點：FB 個人帳號發文只能靠 interactive Claude-in-Chrome session；hourly headless
巡檢連不到 Chrome → 每次卡 pending/awaiting，老闆反覆催（msg 229/237/246）。

唯一尊重上述約束的底層 path = **attach 到老闆已開著、已登入的真實 Chrome**，經 CDP
`--remote-debugging-port` 由排程 worker 驅動貼文。用 Playwright `connect_over_cdp`
**附掛**既有真 Chrome — 不 launch headless、不開假瀏覽器，就是驅動老闆那台真的、
可見的、已登入的 Chrome。

## 演進史 + 最終方案（2026-07-07）

三個階段：

1. **11:00 POC（原始）**：以為 attach 到「老闆主 Chrome」。實際 9222 port 是一個 headless
   `--user-data-dir=/tmp/cdp_profile` 空白 profile → login wall。
2. **11:23 CORRECTION**：`ps aux` 查證確認 attach 對象是 `/tmp/cdp_profile`（空白且每次
   重開就清空），跟老闆已登入的主 Chrome 是不同 profile → PASS 撤回，開 follow-up task
   `platform-ops-fb-realchrome-wrong-profile-20260707`。
3. **12:00 最終解（現行）**：改用**專用持久 profile 的真 GUI Chrome**（非 headless、非
   /tmp、非老闆主 Chrome），老闆登入一次後 cookie 持久化。已 `--check` PASS。

### 最終方案：dedicated persistent-profile 真 GUI Chrome

啟動一個**獨立第二個** Chrome 實例（跟老闆主 Chrome PID 1536 各自 user-data-dir，
互不干擾、不會關到老闆分頁）：

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9222 \
  --user-data-dir="$HOME/.volpred/fb_chrome_profile" \
  --no-first-run --no-default-browser-check
```

- **非 headless**：是可見的真 GUI Chrome window（尊重老闆「不用假瀏覽器」硬約束）。
- **持久 profile**：`~/.volpred/fb_chrome_profile` 不是 /tmp，登入 cookie reboot 後仍在。
- **一次性登入**：老闆在這個視窗登入 `facebook.com/yihao.lai` 一次即可（已完成，
  `--check` 回 `logged_in` + `[PASS]`）。

### 自癒：worker 會自動確保這台 Chrome 開著

`scripts/fb_realchrome_post.py` 的 `ensure_fb_chrome()`（2026-07-07 加）：`--check` / `--post`
呼叫時先檢查 CDP port，**沒開就自動用上述指令啟動** dedicated profile Chrome，poll 到 CDP
就緒再 attach。→ reboot / crash / 老闆手動關掉該視窗後，下一次 hourly tick 會自動重啟它
（登入 cookie 已持久化），不再永久卡「port 沒開 / login_wall」。

驗證：
```bash
uv run python scripts/fb_realchrome_post.py --check
# 期望 [PASS] 這台 Chrome 已登入 FB，CDP-attach 可行
```

## 發文流程（登入後）

```bash
# 1) 安全驗證登入 + attach
uv run python scripts/fb_realchrome_post.py --check

# 2) dry-run：填 composer 停在送出前，人工看截圖確認
uv run python scripts/fb_realchrome_post.py --post storage/drafts/fb_mile_08fefa59.md --dry-run

# 3) 小樣本真發一篇，確認不觸發 FB 自動化鎖帳
uv run python scripts/fb_realchrome_post.py --post storage/drafts/fb_mile_08fefa59.md

# PASS 後才 wire 進 hourly dispatch（PHASE B 有 draft 時呼叫）
```

- 中文輸入用系統剪貼簿 `pbcopy` + `Cmd+V`（`type` 會中文亂碼，見 memory
  `reference_fb_chrome_browser_autoselect`）。
- 主貼文不放連結；第一則留言補網址（留言補連結目前需貼文出現後定位留言框，見
  worker `[TODO]`，下版補；先確保主文自動發出）。

## 風控 gate（老闆硬性要求）

先手動 `--check` → `--post --dry-run` → 單篇小樣本真發，確認**不觸發 FB 自動化鎖帳**，
PASS 才 wire 進排程。CDP-attach 若觸 FB 風控 → 誠實回報物理上限，不硬繞。

## 待發已備妥 2 篇

- `storage/drafts/fb_mile_08fefa59.md`（AI 基建波動率利差；連結 `/v3/reports/mile_08fefa59` ✅ 200）
- `storage/drafts/fb_mile_d12825bb.md`（MOVE 債市方向感；連結 `/v3/reports/mile_d12825bb` ✅ 200）
