# Deploy And Runtime

只有程式、build-time environment 或 service configuration 變更才進部署 branch。內容、
策略、問題與論文 metadata 優先走各自 ops sync。

## Resolve target at run time

```bash
FRONTEND_KEY="$(jq -er '.active_frontend' config/project_targets.json)"
FRONTEND_PATH="$(jq -er --arg key "$FRONTEND_KEY" '.frontends[$key].path' config/project_targets.json)"
ACTIVE_SERVICE="$(jq -er '.deploy.active_service' config/project_targets.json)"
LIVE_URL="$(jq -er '.site.default_remote_url' config/project_targets.json)"
test -n "$ACTIVE_SERVICE"
test -x "$FRONTEND_PATH/scripts/deploy-zeabur-safe.sh"
```

不要把解析值貼回 skill、prompt 或 command。若 frontend key、frontend deploy service 與
`.deploy.active_service` 不相容，先停止並修 `config/project_targets.json` 的 target
transaction。

## Safe handoff

部署只交給 active frontend 自帶的安全 wrapper：

```bash
(cd "$FRONTEND_PATH" && ./scripts/deploy-zeabur-safe.sh)
```

wrapper 應從 config 解析 provider target、等待新 deployment 進 terminal running state，
並驗證 production APIs。任何 bypass 或 provider-level shortcut 都不是本 workflow。

## Verification

至少保存：

1. pre-deploy source identity 與 resolved frontend/service names；
2. wrapper 回傳的 deployment identity 與 terminal status；
3. wrapper 的 production API acknowledgement；
4. `$LIVE_URL` 上本次改動 route 的真實 DOM／文字／console／screenshot readback。

部署 output 只有 upload acknowledgement 時仍是 `contained`。只有 provider terminal
receipt 與本次功能的 live readback 都符合才可宣稱完成。
