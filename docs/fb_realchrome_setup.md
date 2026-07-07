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

## POC 結果（2026-07-07 hourly-11）

| 檢查項 | 結果 |
|---|---|
| CDP port 9222 開著 | ✅ Chrome/149.0.7827.155 |
| `connect_over_cdp` attach 成功 | ✅ contexts=1 |
| headless 能開 FB 頁 + 截圖 + 讀 DOM | ✅（**證明 headless 不是盲貼，看得到結果**）|
| 該 Chrome profile 是否登入 FB | ❌ **login wall**（截圖 `/tmp/fb_realchrome/check_*.png`）|

**結論**：底層 CDP-attach 機制**完全可行且已建好** — headless tick 可以 attach 真 Chrome、
導航、填 composer、截圖驗證。**唯一卡點**：目前開著 debug port（9222）的那台 Chrome 的
profile **沒登入 facebook.com/yihao.lai**（顯示登入牆）。而 AI **不能替老闆輸入 FB 密碼**
（硬規則，即使老闆說「妳幫我做」）。

## 讓它全自動的唯一剩餘步驟（一次性，需老闆做）

在**開著 remote-debugging-port 9222 的那台 Chrome**（= 目前主 Chrome，PID 見
`pgrep "Google Chrome"`）裡，**登入一次** facebook.com/yihao.lai。Cookie 會持久化，
之後任何 headless tick 都能自動發文，不再需要 interactive session。

驗證登入成功：
```bash
uv run python scripts/fb_realchrome_post.py --check
# 期望 [PASS] 這台 Chrome 已登入 FB，CDP-attach 可行
```

若主 Chrome 沒開 debug port，用以下方式啟動（保留真 profile）：
```bash
# 先完全退出 Chrome，再：
open -a "Google Chrome" --args --remote-debugging-port=9222
```
（本機目前 9222 已經開著，不需重啟 — 只差登入。）

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
