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
`page.tsx`、非 API `route.ts`、`sitemap.ts` 與 `public/robots.txt` 會轉為同一份 route
inventory；`/v3/*` 同時保留 surface path 與去掉 `/v3` 後的 canonical route，供原版／v3
逐 route 比較。靜態內部 link 會對實體 route、dynamic segment 與 `next.config.js`
redirect source 做解析，無目標即為 blocker。

## 2026-07-27 baseline

| 項目 | 數量 | 結果 |
|---|---:|---|
| route surfaces | 64 | 全部由唯一 rule 認領，unknown 0、duplicate 0 |
| route owner rules | 19 | 每項都有存在於 repo 的 authoritative data owner ref |
| core scenarios | 7 | public first paint、auth、member、Admin、SEO、mobile、accessibility |
| explicit known gaps | 4 | `/brand` 原版缺口；`/indicators`、`/pricing`、`/radar` v3 缺口 |
| blockers | 5 | 三個 `/login` dead-link source、原版 mobile ARIA、v3 first paint |

目前 blocker 是 checker 的真實輸出，不是 #6 的未完成實作：

1. `EditorialBookmarks.tsx`、`EditorialMemberHome.tsx`、
   `EditorialQuestions.tsx` 連到不存在且無 redirect 的 `/login`。
2. 原版 `MobileNav.tsx` 沒有 `aria-label`／`aria-expanded`。
3. `/v3` 的 server page 沒有 authoritative `getFeed`／`initialData`，首屏仍由
   client `useV3Data` 在 hydration 後取得。

這些項目由 #8（T20 First-paint／Beacon）接續修正；#8 每次改動後重跑本 checker，
直到 blockers 歸零。四個 single-mode known gaps 也保留 exact reason 與 owner，
不能用省略 route 的方式假裝 parity。
