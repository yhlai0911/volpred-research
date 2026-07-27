# Frontend Route／Scenario Parity

本文件是 GitHub Issue #6（T19）的操作與現況說明。機械契約唯一來源為
`config/frontend_route_scenario_parity.json`；本文件不另維護 route 清單。

## 重跑

```bash
uv run python scripts/check_frontend_route_parity.py
```

- exit `0`：沒有 unknown route、duplicate owner、missing owner、dead internal link、
  required-mode gap 或 scenario evidence gap。
- exit `1`：至少一項 blocker；JSON stdout 的 `blockers` 是下游 ticket 的精確輸入。
- `--output <path>` 可保存 JSON receipt。相同 source／contract 會產生 byte-identical
  report；report 不含 wall-clock timestamp。

checker 只讀 `config/project_targets.json` 指定的 active frontend，不能由舊文件猜 target；
contract 的 `frontend_target` 若與 active target 不同會 fail closed。Next.js App Router 的
`page.tsx`、API／非 API `route.ts`、`sitemap.ts` 與 `public/robots.txt` 會轉為同一份 route
inventory；`/v3/*` 同時保留 surface path 與去掉 `/v3` 後的 canonical route，供原版／v3
逐 route 比較。每一個 surface row 都帶 mode-keyed source／authoritative data owner、
capabilities 與 mode-specific advantages，不會把兩種模式的 owner union 假裝成同一份
實作。`route.ts` 另按實際 export 的 HTTP method 展開；GET／POST 等權限逐 method
比對，缺 method contract 或無法解析 handler method 都 fail closed。靜態內部 link
會對實體 route、dynamic segment 與 `next.config.js`
redirect source 做解析；expression／router navigation 無法靜態證明目的地時也 fail
closed，不以「大概是合法」略過。

active frontend 是獨立 nested Git repository。每份 report 都記 nested HEAD、dirty
status digest，以及本次真正讀取的 `src/**/*.{ts,tsx,js,jsx}`／`next.config.js`／
`robots.txt` content tree SHA-256；所以父 repo commit 相同但 nested checkout 不同時，
不會產生無法辨認來源的同名 baseline。

## 2026-07-27 baseline

| 項目 | 數量 | 結果 |
|---|---:|---|
| route surfaces | 133 | page、method-level API 與 metadata 全由唯一 rule 認領，unknown 0、duplicate 0 |
| route owner rules | 25 | 每項都有逐 mode owner；handler 另有逐 HTTP method access class |
| core scenarios | 7 | public first paint、auth、member、Admin、SEO、mobile、accessibility |
| explicit known gaps | 4 | `/brand` 原版缺口；`/indicators`、`/pricing`、`/radar` v3 缺口 |
| blockers | 33 | 3 dead link、2 scenario evidence gap、28 unresolved navigation targets |

本次 baseline 的 nested HEAD 為 `03bad28434251df1f7094f87ffcaf85ec70e40d0`；
frontend 正由另一 session 修改，因此 report 同時標 `dirty=true`，並以 `tree_sha256`
錨定實際讀到的 244 個 source files。blocker 是 checker 的真實輸出，不是 #6 的
未完成實作：

1. `EditorialBookmarks.tsx`、`EditorialMemberHome.tsx`、
   `EditorialQuestions.tsx` 連到不存在且無 redirect 的 `/login`。
2. 原版 `MobileNav.tsx` 沒有 `aria-label`／`aria-expanded`。
3. `/v3` 的 server page 沒有 authoritative `getFeed`／`initialData`，首屏仍由
   client `useV3Data` 在 hydration 後取得。
4. 另有 28 個 navigation expression（例如 `href={item.href}`、report helper 與
   provider PDF URL）目前無 typed route registry 可供 checker 證明；依 fail-closed
   契約列為 unresolved，而不是靜默假設合法。

這些項目由 #8（T20 First-paint／Beacon）接續修正；#8 每次改動後重跑本 checker，
並把動態 navigation 收斂到可解析的 typed registry，直到 blockers 歸零。四個
single-mode known gaps 也保留 exact reason 與 owner，不能用省略 route 的方式假裝
parity。
