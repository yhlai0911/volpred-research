# Codex 桌面 App、Cloud，以及「這台機器上有三個 codex」

**實測日期**：2026-07-17（`hourly-slot-2`）。指令與參數的**完整清單**在 `cli-reference.md`（機器產生）；本檔只放**那份清單看不出來的東西**。

## 1. 最重要的一件事：`codex` 不是一個 binary，是三個

同一台機器上同時存在三個 codex，版本**各不相同**，實測：

| 安裝面 | 路徑 | 版本（2026-07-17 實測） | 誰在用 |
|---|---|---|---|
| **npm CLI** | `~/.nvm/versions/node/v22.20.0/bin/codex` | **0.144.1** | **我們所有自動化**（`codex_exec_bounded.sh`、compute_queue、review gate）— 這是 `$PATH` 上的那個 |
| 桌面 App 內建 | `/Applications/ChatGPT.app/Contents/Resources/codex` | **0.144.5** | 桌面 App、`codex app`、app-server |
| VS Code 擴充內建 | `~/.vscode/extensions/openai.chatgpt-*/bin/macos-aarch64/codex` | **0.144.2** | VS Code 內的 ChatGPT/Codex 擴充 |

npm 上 `@openai/codex` 的 `latest` 是 **0.144.5**。

**這代表什麼**：

- 桌面 App 會**自己更新**（背景有 Sparkle `Updater.app` 在跑），VS Code 擴充跟著擴充版本走，**只有 npm CLI 不會自己更新** → 它是三者中最容易落後的，偏偏它就是我們自動化在用的那個。
- 所以「我在桌面 App 裡試這個參數可以動」**不能推論** CLI 也能動 —— 版本可能差好幾個 patch。要驗 CLI 行為，就得用 CLI 驗。
- 排查任何 codex 問題，**第一件事是確認你在講哪個 binary**：`which codex && codex --version`。

**版本漂移是機器在管，不是靠記性**：

```bash
uv run python scripts/gen_codex_cli_reference.py --check   # exit 1 = 有漂移
```

會同時比對「本機版本 vs npm latest」與「參考文件是否為當前版本產生」。

## 2. 升級 npm CLI 的注意事項

```bash
codex update                      # CLI 自己的升級路徑
# 或 npm install -g @openai/codex@latest
```

**升級前必看**：`codex exec` 是長時間 agentic loop，我們的 hourly/compute worker 隨時可能有 in-flight job（2026-07-17 21:20 實測當下就有一個 `codex exec resume --last` 在跑）。**升級會把 binary 從跑到一半的 job 腳下抽掉**，所以：

1. 先確認沒有 in-flight：`pgrep -fl "node_modules/@openai/codex.*bin/codex"`
2. 升級後**必跑 smoke**（2026-07-10 事故：config 的 model 指到舊 CLI 不支援的名字 → API 400 靜默失敗、卡死全平台 codex 流程）：
   ```bash
   bash scripts/codex_exec_bounded.sh --timeout 60 --skip-git-repo-check "echo TEST"
   ```
3. 升級後重跑 `gen_codex_cli_reference.py` 讓參考文件跟上。
4. ⚠️ **0.144.5 收緊了 dangerous-command 偵測**（更多 forced `rm` 形式會被拒、拒絕理由更清楚）。原本能跑 `rm -rf` 的自動化腳本升級後可能開始被擋 —— 升級時要一起驗。([rust-v0.144.5](https://github.com/openai/codex/releases/tag/rust-v0.144.5))

**版本現況**（2026-07-17）：GitHub 最新 stable = `rust-v0.144.5`（2026-07-16）。0.145.0-alpha 已出到 alpha.20 但**零 release notes** —— 別把 0.145 的行為寫進任何文件。

## 3. `codex app` — 桌面 App

```
codex app [PATH]        # 預設 PATH = .
```

- 作用：開啟桌面 App 並載入指定 workspace；**App 沒裝的話會去開安裝程式**。
- 參數只有 4 個：`-c/--config`、`--download-url <URL>`（覆寫安裝檔下載網址，進階用）、`--enable/--disable <FEATURE>`。
- 本機已裝：`/Applications/ChatGPT.app` —— **這不是巧合**：官方 2026-07-09 起**已把 Codex app 併進新版 ChatGPT desktop app**（macOS + Windows），Codex 成為 app 內與 Chat / Work 並列的一個 mode，用 composer 上方切換器選。所以「Codex 桌面 App」現在＝ ChatGPT 桌面 App，沒有獨立安裝檔。([app docs](https://learn.chatgpt.com/docs/app) · [changelog](https://learn.chatgpt.com/docs/changelog) · [Help Center](https://help.openai.com/en/articles/20001276-moving-to-the-new-chatgpt-desktop-app))
- ⚠️ **命名漂移**：本機 CLI help 說 "Codex desktop app"，官方文件說 "ChatGPT desktop app" —— 同一個東西。
- **[查不到]** App 沒有專屬的設定/參數文件，設定沿用一般 Codex config。
- **對自動化沒用**：它會開 GUI。hourly fire / headless 流程**不要碰**，跟 bare `codex`（會開 TUI 卡住）同一類。

### app-server（App 與編輯器背後的機制）

桌面 App 與 VS Code 擴充都是靠 `codex app-server --listen stdio://` 起一個背景服務跟 codex core 溝通（實測有多個 app-server 進程在跑）。`codex app-server` / `codex remote-control` / `codex exec-server` 都標 **experimental**，我們沒有在用，不要為了「看起來比較快」把自動化接上去。

## 4. `codex cloud` — 把任務丟雲端（EXPERIMENTAL）

```
codex cloud exec      # 送一個新的 Cloud task（不開 TUI）
codex cloud list      # 列 tasks
codex cloud status    # 查某個 task 狀態
codex cloud diff      # 看 task 的 unified diff
codex cloud apply     # 把 diff 套回本地
codex apply <TASK_ID> # 頂層版本：把 Codex agent 產的 diff git apply 到工作區
```

標記為 EXPERIMENTAL。**目前我們不用**：VolPred 的長任務已經有自己的非同步路徑（`compute_queue.py` + `*/15` worker），那條路有 lock、有 timeout、有 followup receipt。Cloud 是第二套非同步機制，接進來等於同一個 concern 兩個 owner（違反 CLAUDE.md anti-stacking）。要評估再另開任務。

## 5. `codex doctor` — 出事先跑這個

```bash
codex doctor --summary        # 分組結果 + 總計
codex doctor --json           # 機器可讀（已去敏）
codex doctor --all            # 展開長清單
```

2026-07-17 實測本機：`17 ok · 1 idle · 3 notes · 0 warn · 0 fail`，涵蓋 state DB / config / auth / mcp / sandbox / updates / network / websocket / reachability / app-server。

**價值**：以前排查 codex 問題是靠猜（認證？模型？網路？），`doctor` 一次把這些全驗完。**任何「Codex 又壞了」的直覺，先跑 doctor 再查**。注意它只驗基礎設施，**不會**告訴你參數寫錯 —— 參數錯的症狀是 exit 2 + 空 stdout（見 SKILL.md 的陷阱段）。

## 6. 認證與 config 實測值

- 認證：`Logged in using ChatGPT`（`codex login status`）。另有 `codex login --with-api-key`。
- `~/.codex/config.toml` 實測：`model = "gpt-5.6-sol"`、`model_reasoning_effort = "high"`、`sandbox_mode = "danger-full-access"`、`personality = "pragmatic"`。
- ⚠️ **effort 要引用前先 grep，不要照抄任何文件**（含本檔）：曾把 `ultra` 寫進 skill 對外誤述 reviewer 規格。`ultra` 不在本機 config 裡。
  ```bash
  grep model_reasoning_effort ~/.codex/config.toml
  ```
- `codex doctor` 顯示 `approval OnRequest`，與 config 的 `sandbox_mode = danger-full-access` 是**兩個不同維度**（approval policy vs sandbox policy），不要混為一談。

## 7. Feature flags

```bash
codex features list                 # stage（stable/under development/removed）+ 生效狀態
codex features enable <NAME>        # 寫進 config.toml
codex features disable <NAME>
codex --enable <FEATURE> ...        # 單次調用，等同 -c features.<name>=true
```

實測本機 stable+on 的有 `apps`、`browser_use`、`code_mode_host`、`computer_use`、`enable_request_compression` 等。清單會隨版本變動 —— **要引用前先 `codex features list`**，不要照抄。標 `removed` 的即使顯示 true 也已無作用（如 `collaboration_modes`）。
