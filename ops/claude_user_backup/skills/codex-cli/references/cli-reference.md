# Codex CLI — 完整指令與參數對照（機器產生，勿手改）

- **產生時間**：2026-07-20 09:01 台灣時間
- **來源**：本機 `codex help` 逐節點輸出（`codex-cli 0.144.6`）
- **npm `@openai/codex` latest**：0.144.6
- **重新產生**：`uv run python scripts/gen_codex_cli_reference.py`

> 這份檔是**本機實際安裝的 binary 自己吐的**，不是人寫的摘要。任何與這裡衝突的說明，以這裡為準；要改內容請改 CLI 版本或重跑產生器，不要手改本檔。

> ⚠️ **但 help 不是全知的**：Codex 有**隱藏 flag**（`codex exec --full-auto` help 裡沒有、實際吃它且 exit 0），而且 help **完全不列 config.toml 的合法值**（`model_reasoning_effort` 的 enum 就查不到）。所以本檔窮舉的是「檯面上的 flag」。**要斷言某個東西不存在，必須實跑，不能只 grep 本檔。**

## 本機 config 實測值（`~/.codex/config.toml`）

```toml
model = "gpt-5.6-sol"
model_reasoning_effort = "high"
personality = "pragmatic"
sandbox_mode = "danger-full-access"
```

## 指令樹

- [`codex`](#codex)
  - [`codex exec`](#codex-exec)
    - [`codex exec resume`](#codex-exec-resume)
    - [`codex exec review`](#codex-exec-review)
  - [`codex review`](#codex-review)
  - [`codex login`](#codex-login)
    - [`codex login status`](#codex-login-status)
  - [`codex logout`](#codex-logout)
  - [`codex mcp`](#codex-mcp)
    - [`codex mcp list`](#codex-mcp-list)
    - [`codex mcp get`](#codex-mcp-get)
    - [`codex mcp add`](#codex-mcp-add)
    - [`codex mcp remove`](#codex-mcp-remove)
    - [`codex mcp login`](#codex-mcp-login)
    - [`codex mcp logout`](#codex-mcp-logout)
  - [`codex plugin`](#codex-plugin)
    - [`codex plugin add`](#codex-plugin-add)
    - [`codex plugin list`](#codex-plugin-list)
    - [`codex plugin marketplace`](#codex-plugin-marketplace)
    - [`codex plugin remove`](#codex-plugin-remove)
  - [`codex mcp-server`](#codex-mcp-server)
  - [`codex app-server`](#codex-app-server)
    - [`codex app-server daemon`](#codex-app-server-daemon)
    - [`codex app-server proxy`](#codex-app-server-proxy)
    - [`codex app-server generate-ts`](#codex-app-server-generate-ts)
    - [`codex app-server generate-json-schema`](#codex-app-server-generate-json-schema)
  - [`codex remote-control`](#codex-remote-control)
    - [`codex remote-control start`](#codex-remote-control-start)
    - [`codex remote-control stop`](#codex-remote-control-stop)
    - [`codex remote-control pair`](#codex-remote-control-pair)
  - [`codex app`](#codex-app)
  - [`codex completion`](#codex-completion)
  - [`codex update`](#codex-update)
  - [`codex doctor`](#codex-doctor)
  - [`codex sandbox`](#codex-sandbox)
  - [`codex debug`](#codex-debug)
    - [`codex debug models`](#codex-debug-models)
    - [`codex debug app-server`](#codex-debug-app-server)
    - [`codex debug prompt-input`](#codex-debug-prompt-input)
  - [`codex apply`](#codex-apply)
  - [`codex resume`](#codex-resume)
  - [`codex archive`](#codex-archive)
  - [`codex delete`](#codex-delete)
  - [`codex unarchive`](#codex-unarchive)
  - [`codex fork`](#codex-fork)
  - [`codex cloud`](#codex-cloud)
    - [`codex cloud exec`](#codex-cloud-exec)
    - [`codex cloud status`](#codex-cloud-status)
    - [`codex cloud list`](#codex-cloud-list)
    - [`codex cloud apply`](#codex-cloud-apply)
    - [`codex cloud diff`](#codex-cloud-diff)
  - [`codex exec-server`](#codex-exec-server)
  - [`codex features`](#codex-features)
    - [`codex features list`](#codex-features-list)
    - [`codex features enable`](#codex-features-enable)
    - [`codex features disable`](#codex-features-disable)

## codex

```
Codex CLI

If no subcommand is specified, options will be forwarded to the interactive CLI.

Usage: codex [OPTIONS] [PROMPT]
       codex [OPTIONS] <COMMAND> [ARGS]

Commands:
  exec            Run Codex non-interactively [aliases: e]
  review          Run a code review non-interactively
  login           Manage login
  logout          Remove stored authentication credentials
  mcp             Manage external MCP servers for Codex
  plugin          Manage Codex plugins
  mcp-server      Start Codex as an MCP server (stdio)
  app-server      [experimental] Run the app server or related tooling
  remote-control  [experimental] Manage the app-server daemon with remote control enabled
  app             Launch the Codex desktop app (opens the app installer if missing)
  completion      Generate shell completion scripts
  update          Update Codex to the latest version
  doctor          Diagnose local Codex installation, config, auth, and runtime health
  sandbox         Run commands within a Codex-provided sandbox
  debug           Debugging tools
  apply           Apply the latest diff produced by Codex agent as a `git apply` to your local
                  working tree [aliases: a]
  resume          Resume a previous interactive session (picker by default; use --last to continue
                  the most recent)
  archive         Archive a saved session by id or session name
  delete          Permanently delete a saved session by id or session name
  unarchive       Unarchive a saved session by id or session name
  fork            Fork a previous interactive session (picker by default; use --last to fork the
                  most recent)
  cloud           [EXPERIMENTAL] Browse tasks from Codex Cloud and apply changes locally
  exec-server     [EXPERIMENTAL] Run the standalone exec-server service
  features        Inspect feature flags
  help            Print this message or the help of the given subcommand(s)

Arguments:
  [PROMPT]
          Optional user prompt to start the session

Options:
  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

      --remote <ADDR>
          Connect the TUI to a remote app server endpoint.
          
          Accepted forms: `ws://host:port`, `wss://host:port`, `unix://`, or `unix://PATH`.

      --remote-auth-token-env <ENV_VAR>
          Name of the environment variable containing the bearer token to send to a remote app
          server websocket

      --strict-config
          Error out when config.toml contains fields that are not recognized by this version of
          Codex

  -i, --image <FILE>...
          Optional image(s) to attach to the initial prompt

  -m, --model <MODEL>
          Model the agent should use

      --oss
          Use open-source provider

      --local-provider <OSS_PROVIDER>
          Specify which local provider to use (lmstudio or ollama). If not specified with --oss,
          will use config default or show selection

  -p, --profile <CONFIG_PROFILE_V2>
          Layer $CODEX_HOME/<name>.config.toml on top of the base user config

  -s, --sandbox <SANDBOX_MODE>
          Select the sandbox policy to use when executing model-generated shell commands
          
          [possible values: read-only, workspace-write, danger-full-access]

      --dangerously-bypass-approvals-and-sandbox
          Skip all confirmation prompts and execute commands without sandboxing. EXTREMELY
          DANGEROUS. Intended solely for running in environments that are externally sandboxed

      --dangerously-bypass-hook-trust
          Run enabled hooks without requiring persisted hook trust for this invocation. DANGEROUS.
          Intended only for automation that already vets hook sources

  -C, --cd <DIR>
          Tell the agent to use the specified directory as its working root

      --add-dir <DIR>
          Additional directories that should be writable alongside the primary workspace

  -a, --ask-for-approval <APPROVAL_POLICY>
          Configure when the model requires human approval before executing a command

          Possible values:
          - untrusted:  Only run "trusted" commands (e.g. ls, cat, sed) without asking for user
            approval. Will escalate to the user if the model proposes a command that is not in the
            "trusted" set
          - on-request: The model decides when to ask the user for approval
          - never:      Never ask for user approval Execution failures are immediately returned to
            the model

      --search
          Enable live web search. When enabled, the native Responses `web_search` tool is available
          to the model (no per‑call approval)

      --no-alt-screen
          Disable alternate screen mode
          
          Runs the TUI in inline mode, preserving terminal scrollback history.

  -h, --help
          Print help (see a summary with '-h')

  -V, --version
          Print version
```

## codex exec

```
Run Codex non-interactively

Usage: codex exec [OPTIONS] [PROMPT]
       codex exec [OPTIONS] <COMMAND> [ARGS]

Commands:
  resume  Resume a previous session by id or pick the most recent with --last
  review  Run a code review against the current repository
  help    Print this message or the help of the given subcommand(s)

Arguments:
  [PROMPT]
          Initial instructions for the agent. If not provided as an argument (or if `-` is used),
          instructions are read from stdin. If stdin is piped and a prompt is also provided, stdin
          is appended as a `<stdin>` block

Options:
  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

      --strict-config
          Error out when config.toml contains fields that are not recognized by this version of
          Codex

  -i, --image <FILE>...
          Optional image(s) to attach to the initial prompt

  -m, --model <MODEL>
          Model the agent should use

      --oss
          Use open-source provider

      --local-provider <OSS_PROVIDER>
          Specify which local provider to use (lmstudio or ollama). If not specified with --oss,
          will use config default or show selection

  -p, --profile <CONFIG_PROFILE_V2>
          Layer $CODEX_HOME/<name>.config.toml on top of the base user config

  -s, --sandbox <SANDBOX_MODE>
          Select the sandbox policy to use when executing model-generated shell commands
          
          [possible values: read-only, workspace-write, danger-full-access]

      --dangerously-bypass-approvals-and-sandbox
          Skip all confirmation prompts and execute commands without sandboxing. EXTREMELY
          DANGEROUS. Intended solely for running in environments that are externally sandboxed

      --dangerously-bypass-hook-trust
          Run enabled hooks without requiring persisted hook trust for this invocation. DANGEROUS.
          Intended only for automation that already vets hook sources

  -C, --cd <DIR>
          Tell the agent to use the specified directory as its working root

      --add-dir <DIR>
          Additional directories that should be writable alongside the primary workspace

      --skip-git-repo-check
          Allow running Codex outside a Git repository

      --ephemeral
          Run without persisting session files to disk

      --ignore-user-config
          Do not load `$CODEX_HOME/config.toml`; auth still uses `CODEX_HOME`

      --ignore-rules
          Do not load user or project execpolicy `.rules` files

      --output-schema <FILE>
          Path to a JSON Schema file describing the model's final response shape

      --color <COLOR>
          Specifies color settings for use in the output
          
          [default: auto]
          [possible values: always, never, auto]

      --json
          Print events to stdout as JSONL

  -o, --output-last-message <FILE>
          Specifies file where the last message from the agent should be written

  -h, --help
          Print help (see a summary with '-h')

  -V, --version
          Print version
```

## codex exec resume

```
Resume a previous session by id or pick the most recent with --last

Usage: codex exec resume [OPTIONS] [SESSION_ID] [PROMPT]

Arguments:
  [SESSION_ID]
          Conversation/session id (UUID) or thread name. UUIDs take precedence if it parses. If
          omitted, use --last to pick the most recent recorded session

  [PROMPT]
          Prompt to send after resuming the session. If `-` is used, read from stdin

Options:
  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

      --last
          Resume the most recent recorded session (newest) without specifying an id

      --all
          Show all sessions (disables cwd filtering)

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

  -i, --image <FILE>
          Optional image(s) to attach to the prompt sent after resuming

      --strict-config
          Error out when config.toml contains fields that are not recognized by this version of
          Codex

  -m, --model <MODEL>
          Model the agent should use

      --dangerously-bypass-approvals-and-sandbox
          Skip all confirmation prompts and execute commands without sandboxing. EXTREMELY
          DANGEROUS. Intended solely for running in environments that are externally sandboxed

      --dangerously-bypass-hook-trust
          Run enabled hooks without requiring persisted hook trust for this invocation. DANGEROUS.
          Intended only for automation that already vets hook sources

      --skip-git-repo-check
          Allow running Codex outside a Git repository

      --ephemeral
          Run without persisting session files to disk

      --ignore-user-config
          Do not load `$CODEX_HOME/config.toml`; auth still uses `CODEX_HOME`

      --ignore-rules
          Do not load user or project execpolicy `.rules` files

      --output-schema <FILE>
          Path to a JSON Schema file describing the model's final response shape

      --json
          Print events to stdout as JSONL

  -o, --output-last-message <FILE>
          Specifies file where the last message from the agent should be written

  -h, --help
          Print help (see a summary with '-h')
```

## codex exec review

```
Run a code review against the current repository

Usage: codex exec review [OPTIONS] [PROMPT]

Arguments:
  [PROMPT]
          Custom review instructions. If `-` is used, read from stdin

Options:
  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

      --uncommitted
          Review staged, unstaged, and untracked changes

      --base <BRANCH>
          Review changes against the given base branch

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

      --commit <SHA>
          Review the changes introduced by a commit

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

      --strict-config
          Error out when config.toml contains fields that are not recognized by this version of
          Codex

      --title <TITLE>
          Optional commit title to display in the review summary

  -m, --model <MODEL>
          Model the agent should use

      --dangerously-bypass-approvals-and-sandbox
          Skip all confirmation prompts and execute commands without sandboxing. EXTREMELY
          DANGEROUS. Intended solely for running in environments that are externally sandboxed

      --dangerously-bypass-hook-trust
          Run enabled hooks without requiring persisted hook trust for this invocation. DANGEROUS.
          Intended only for automation that already vets hook sources

      --skip-git-repo-check
          Allow running Codex outside a Git repository

      --ephemeral
          Run without persisting session files to disk

      --ignore-user-config
          Do not load `$CODEX_HOME/config.toml`; auth still uses `CODEX_HOME`

      --ignore-rules
          Do not load user or project execpolicy `.rules` files

      --output-schema <FILE>
          Path to a JSON Schema file describing the model's final response shape

      --json
          Print events to stdout as JSONL

  -o, --output-last-message <FILE>
          Specifies file where the last message from the agent should be written

  -h, --help
          Print help (see a summary with '-h')
```

## codex review

```
Run a code review non-interactively

Usage: codex review [OPTIONS] [PROMPT]

Arguments:
  [PROMPT]
          Custom review instructions. If `-` is used, read from stdin

Options:
  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

      --strict-config
          Error out when config.toml contains fields that are not recognized by this version of
          Codex

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

      --uncommitted
          Review staged, unstaged, and untracked changes

      --base <BRANCH>
          Review changes against the given base branch

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

      --commit <SHA>
          Review the changes introduced by a commit

      --title <TITLE>
          Optional commit title to display in the review summary

  -h, --help
          Print help (see a summary with '-h')
```

## codex login

```
Manage login

Usage: codex login [OPTIONS] [COMMAND]

Commands:
  status  Show login status
  help    Print this message or the help of the given subcommand(s)

Options:
  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

      --with-api-key
          Read the API key from stdin (e.g. `printenv OPENAI_API_KEY | codex login --with-api-key`)

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

      --with-access-token
          Read the access token from stdin (e.g. `printenv CODEX_ACCESS_TOKEN | codex login
          --with-access-token`)

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

      --device-auth
          

  -h, --help
          Print help (see a summary with '-h')
```

## codex login status

```
Show login status

Usage: codex login status [OPTIONS]

Options:
  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

  -h, --help
          Print help (see a summary with '-h')
```

## codex logout

```
Remove stored authentication credentials

Usage: codex logout [OPTIONS]

Options:
  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

  -h, --help
          Print help (see a summary with '-h')
```

## codex mcp

```
Manage external MCP servers for Codex

Usage: codex mcp [OPTIONS] <COMMAND>

Commands:
  list    
  get     
  add     
  remove  
  login   
  logout  
  help    Print this message or the help of the given subcommand(s)

Options:
  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

  -h, --help
          Print help (see a summary with '-h')
```

## codex mcp list

```
Usage: codex mcp list [OPTIONS]

Options:
  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

      --json
          Output the configured servers as JSON

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

  -h, --help
          Print help (see a summary with '-h')
```

## codex mcp get

```
Usage: codex mcp get [OPTIONS] <NAME>

Arguments:
  <NAME>
          Name of the MCP server to display

Options:
  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

      --json
          Output the server configuration as JSON

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

  -h, --help
          Print help (see a summary with '-h')
```

## codex mcp add

```
Usage: codex mcp add [OPTIONS] <NAME> (--url <URL> | -- <COMMAND>...)

Arguments:
  <NAME>
          Name for the MCP server configuration

  [COMMAND]...
          Command to launch the MCP server. Use --url for a streamable HTTP server

Options:
  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

      --env <KEY=VALUE>
          Environment variables to set when launching the server. Only valid with stdio servers

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

      --url <URL>
          URL for a streamable HTTP MCP server

      --bearer-token-env-var <ENV_VAR>
          Optional environment variable to read for a bearer token. Only valid with streamable HTTP
          servers

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

      --oauth-client-id <CLIENT_ID>
          Optional OAuth client identifier to use for this MCP server

      --oauth-resource <RESOURCE>
          Optional OAuth resource parameter to include during MCP login

  -h, --help
          Print help (see a summary with '-h')
```

## codex mcp remove

```
Usage: codex mcp remove [OPTIONS] <NAME>

Arguments:
  <NAME>
          Name of the MCP server configuration to remove

Options:
  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

  -h, --help
          Print help (see a summary with '-h')
```

## codex mcp login

```
Usage: codex mcp login [OPTIONS] <NAME>

Arguments:
  <NAME>
          Name of the MCP server to authenticate with oauth

Options:
  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

      --scopes <SCOPE,SCOPE>
          Comma-separated list of OAuth scopes to request

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

  -h, --help
          Print help (see a summary with '-h')
```

## codex mcp logout

```
Usage: codex mcp logout [OPTIONS] <NAME>

Arguments:
  <NAME>
          Name of the MCP server to deauthenticate

Options:
  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

  -h, --help
          Print help (see a summary with '-h')
```

## codex plugin

```
Manage Codex plugins

Usage: codex plugin [OPTIONS] <COMMAND>

Commands:
  add          Install a plugin from a configured marketplace snapshot
  list         List plugins available from configured marketplace snapshots
  marketplace  Add, list, upgrade, or remove configured plugin marketplaces
  remove       Remove an installed plugin from local config and cache
  help         Print this message or the help of the given subcommand(s)

Options:
  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

  -h, --help
          Print help (see a summary with '-h')
```

## codex plugin add

```
Install a plugin from a configured marketplace snapshot.

Pass either `PLUGIN@MARKETPLACE` or pass `PLUGIN` with `--marketplace MARKETPLACE`.

Usage: codex plugin add [OPTIONS] <PLUGIN[@MARKETPLACE]>

Arguments:
  <PLUGIN[@MARKETPLACE]>
          Plugin selector to install: either PLUGIN@MARKETPLACE or PLUGIN with --marketplace

Options:
  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

  -m, --marketplace <MARKETPLACE>
          Configured marketplace name to use when PLUGIN does not include @MARKETPLACE

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

      --json
          Output install result as JSON

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

  -h, --help
          Print help (see a summary with '-h')

Examples:
  codex plugin add sample@debug
  codex plugin add sample --marketplace debug
```

## codex plugin list

```
List plugins available from configured marketplace snapshots

Usage: codex plugin list [OPTIONS]

Options:
  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

  -m, --marketplace <MARKETPLACE>
          Only list plugins from this configured marketplace name

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

      --json
          Output plugin list as JSON

      --available
          Include uninstalled marketplace plugins in the JSON output

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

  -h, --help
          Print help (see a summary with '-h')

Examples:
  codex plugin list
  codex plugin list --marketplace debug
  codex plugin list --json
  codex plugin list --available --json
```

## codex plugin marketplace

```
Add, list, upgrade, or remove configured plugin marketplaces

Usage: codex plugin marketplace [OPTIONS] <COMMAND>

Commands:
  add      Add a local or Git marketplace to the configured marketplace sources
  list     List plugin marketplaces Codex is currently considering and their roots
  upgrade  Refresh configured Git marketplace snapshots
  remove   Remove a configured marketplace source by name
  help     Print this message or the help of the given subcommand(s)

Options:
  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

  -h, --help
          Print help (see a summary with '-h')
```

## codex plugin remove

```
Remove an installed plugin from local config and cache.

Pass either `PLUGIN@MARKETPLACE` or pass `PLUGIN` with `--marketplace MARKETPLACE`.

Usage: codex plugin remove [OPTIONS] <PLUGIN[@MARKETPLACE]>

Arguments:
  <PLUGIN[@MARKETPLACE]>
          Plugin selector to remove: either PLUGIN@MARKETPLACE or PLUGIN with --marketplace

Options:
  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

  -m, --marketplace <MARKETPLACE>
          Marketplace name to use when PLUGIN does not include @MARKETPLACE

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

      --json
          Output remove result as JSON

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

  -h, --help
          Print help (see a summary with '-h')

Examples:
  codex plugin remove sample@debug
  codex plugin remove sample --marketplace debug
```

## codex mcp-server

```
Start Codex as an MCP server (stdio)

Usage: codex mcp-server [OPTIONS]

Options:
  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

      --strict-config
          Error out when config.toml contains fields that are not recognized by this version of
          Codex

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

  -h, --help
          Print help (see a summary with '-h')
```

## codex app-server

```
[experimental] Run the app server or related tooling

Usage: codex app-server [OPTIONS] [COMMAND]

Commands:
  daemon                Manage the local app-server daemon
  proxy                 Proxy stdio bytes to the running app-server control socket
  generate-ts           [experimental] Generate TypeScript bindings for the app server protocol
  generate-json-schema  [experimental] Generate JSON Schema for the app server protocol
  help                  Print this message or the help of the given subcommand(s)

Options:
  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

      --strict-config
          Error out when config.toml contains fields that are not recognized by this version of
          Codex

      --listen <URL>
          Transport endpoint URL. Supported values: `stdio://` (default), `unix://`, `unix://PATH`,
          `ws://IP:PORT`, `off`
          
          [default: stdio://]

      --stdio
          Use stdio as the transport (equivalent to `--listen stdio://`)

      --analytics-default-enabled
          Controls whether analytics are enabled by default.
          
          Analytics are disabled by default for app-server. Users have to explicitly opt in via the
          `analytics` section in the config.toml file.
          
          However, for first-party use cases like the VSCode IDE extension, we default analytics to
          be enabled by default by setting this flag. Users can still opt out by setting this in
          their config.toml:
          
          ```toml [analytics] enabled = false ```
          
          See https://developers.openai.com/codex/config-advanced/#metrics for more details.

      --ws-auth <MODE>
          Websocket auth mode for non-loopback listeners
          
          [possible values: capability-token, signed-bearer-token]

      --ws-token-file <PATH>
          Absolute path to the capability-token file

      --ws-token-sha256 <HEX>
          Hex-encoded SHA-256 digest of the capability token

      --ws-shared-secret-file <PATH>
          Absolute path to the shared secret file for signed JWT bearer tokens

      --ws-issuer <ISSUER>
          Expected issuer for signed JWT bearer tokens

      --ws-audience <AUDIENCE>
          Expected audience for signed JWT bearer tokens

      --ws-max-clock-skew-seconds <SECONDS>
          Maximum clock skew when validating signed JWT bearer tokens

  -h, --help
          Print help (see a summary with '-h')
```

## codex app-server daemon

```
Manage the local app-server daemon

Usage: codex app-server daemon [OPTIONS] <COMMAND>

Commands:
  bootstrap               Install durable local app-server management for SSH-driven use
  start                   Start the local app server daemon if it is not already running
  restart                 Restart the local app server daemon
  enable-remote-control   Enable remote control for future starts and a currently running managed
                          daemon
  disable-remote-control  Disable remote control for future starts and a currently running managed
                          daemon
  stop                    Stop the local app server daemon
  version                 Print local CLI and running app-server versions as JSON
  help                    Print this message or the help of the given subcommand(s)

Options:
  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

  -h, --help
          Print help (see a summary with '-h')
```

## codex app-server proxy

```
Proxy stdio bytes to the running app-server control socket

Usage: codex app-server proxy [OPTIONS]

Options:
  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

      --sock <SOCKET_PATH>
          Path to the app-server Unix domain socket to connect to

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

  -h, --help
          Print help (see a summary with '-h')
```

## codex app-server generate-ts

```
[experimental] Generate TypeScript bindings for the app server protocol

Usage: codex app-server generate-ts [OPTIONS] --out <DIR>

Options:
  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

  -o, --out <DIR>
          Output directory where .ts files will be written

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

  -p, --prettier <PRETTIER_BIN>
          Optional path to the Prettier executable to format generated files

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

      --experimental
          Include experimental methods and fields in the generated output

  -h, --help
          Print help (see a summary with '-h')
```

## codex app-server generate-json-schema

```
[experimental] Generate JSON Schema for the app server protocol

Usage: codex app-server generate-json-schema [OPTIONS] --out <DIR>

Options:
  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

  -o, --out <DIR>
          Output directory where the schema bundle will be written

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

      --experimental
          Include experimental methods and fields in the generated output

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

  -h, --help
          Print help (see a summary with '-h')
```

## codex remote-control

```
[experimental] Manage the app-server daemon with remote control enabled

Usage: codex remote-control [OPTIONS] [COMMAND]

Commands:
  start  Start the app-server daemon with remote control enabled
  stop   Stop the app-server daemon
  pair   Create and print a short-lived manual pairing code
  help   Print this message or the help of the given subcommand(s)

Options:
  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

      --json
          Emit machine-readable JSON

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

  -h, --help
          Print help (see a summary with '-h')
```

## codex remote-control start

```
Start the app-server daemon with remote control enabled

Usage: codex remote-control start [OPTIONS]

Options:
  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

      --json
          Emit machine-readable JSON

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

  -h, --help
          Print help (see a summary with '-h')
```

## codex remote-control stop

```
Stop the app-server daemon

Usage: codex remote-control stop [OPTIONS]

Options:
  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

      --json
          Emit machine-readable JSON

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

  -h, --help
          Print help (see a summary with '-h')
```

## codex remote-control pair

```
Create and print a short-lived manual pairing code

Usage: codex remote-control pair [OPTIONS]

Options:
  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

      --json
          Emit machine-readable JSON

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

  -h, --help
          Print help (see a summary with '-h')
```

## codex app

```
Launch the Codex desktop app (opens the app installer if missing)

Usage: codex app [OPTIONS] [PATH]

Arguments:
  [PATH]
          Workspace path to open in Codex Desktop
          
          [default: .]

Options:
  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

      --download-url <DOWNLOAD_URL_OVERRIDE>
          Override the app installer download URL (advanced)

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

  -h, --help
          Print help (see a summary with '-h')
```

## codex completion

```
Generate shell completion scripts

Usage: codex completion [OPTIONS] [SHELL]

Arguments:
  [SHELL]
          Shell to generate completions for
          
          [default: bash]
          [possible values: bash, elvish, fish, powershell, zsh]

Options:
  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

  -h, --help
          Print help (see a summary with '-h')
```

## codex update

```
Update Codex to the latest version

Usage: codex update [OPTIONS]

Options:
  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

  -h, --help
          Print help (see a summary with '-h')
```

## codex doctor

```
Diagnose local Codex installation, config, auth, and runtime health

Usage: codex doctor [OPTIONS]

Options:
  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

      --json
          Emit a redacted machine-readable report

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

      --summary
          Only show grouped check rows and the final count summary

      --all
          Expand long lists in detailed human output

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

      --no-color
          Disable ANSI color in human output

      --ascii
          Use ASCII status labels and separators in human output

  -h, --help
          Print help (see a summary with '-h')
```

## codex sandbox

```
Run commands within a Codex-provided sandbox

Usage: codex sandbox [OPTIONS] [COMMAND]...

Arguments:
  [COMMAND]...
          Full command args to run under seatbelt

Options:
  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

      --sandbox-state-json <JSON>
          JSON value from `codex/sandbox-state-meta` to apply directly

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

      --sandbox-state-readable-root <SANDBOX_STATE_READABLE_ROOT>
          Add a readable root to the supplied sandbox state. Repeat for multiple roots

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

      --sandbox-state-disable-network
          Disable direct network access in the supplied sandbox state

  -P, --permission-profile <NAME>
          Named permissions profile to apply from the active configuration stack

  -p, --profile <CONFIG_PROFILE>
          Layer $CODEX_HOME/<name>.config.toml on top of the base user config

  -C, --cd <DIR>
          Working directory used for profile resolution and command execution

      --include-managed-config
          Include managed requirements while resolving an explicit permissions profile

      --allow-unix-socket <ALLOW_UNIX_SOCKETS>
          Allow the sandboxed command to bind/connect AF_UNIX sockets rooted at this path. Relative
          paths are resolved against the current directory. Repeat to allow multiple paths

      --log-denials
          While the command runs, capture macOS sandbox denials via `log stream` and print them
          after exit

  -h, --help
          Print help (see a summary with '-h')
```

## codex debug

```
Debugging tools

Usage: codex debug [OPTIONS] <COMMAND>

Commands:
  models        Render the raw model catalog as JSON
  app-server    Tooling: helps debug the app server
  prompt-input  Render the model-visible prompt input list as JSON
  help          Print this message or the help of the given subcommand(s)

Options:
  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

  -h, --help
          Print help (see a summary with '-h')
```

## codex debug models

```
Render the raw model catalog as JSON

Usage: codex debug models [OPTIONS]

Options:
      --bundled
          Skip refresh and dump only the bundled catalog shipped with this binary

  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

  -h, --help
          Print help (see a summary with '-h')
```

## codex debug app-server

```
Tooling: helps debug the app server

Usage: codex debug app-server [OPTIONS] <COMMAND>

Commands:
  send-message-v2  
  help             Print this message or the help of the given subcommand(s)

Options:
  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

  -h, --help
          Print help (see a summary with '-h')
```

## codex debug prompt-input

```
Render the model-visible prompt input list as JSON

Usage: codex debug prompt-input [OPTIONS] [PROMPT]

Arguments:
  [PROMPT]
          Optional user prompt to append after session context

Options:
  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

  -i, --image <FILE>...
          Optional image(s) to attach to the user prompt

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

  -h, --help
          Print help (see a summary with '-h')
```

## codex apply

```
Apply the latest diff produced by Codex agent as a `git apply` to your local working tree

Usage: codex apply [OPTIONS] <TASK_ID>

Arguments:
  <TASK_ID>
          

Options:
  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

  -h, --help
          Print help (see a summary with '-h')
```

## codex resume

```
Resume a previous interactive session (picker by default; use --last to continue the most recent)

Usage: codex resume [OPTIONS] [SESSION_ID] [PROMPT]

Arguments:
  [SESSION_ID]
          Session id (UUID) or session name. UUIDs take precedence if it parses. If omitted, use
          --last to pick the most recent recorded session

  [PROMPT]
          Optional user prompt to start the session

Options:
  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

      --last
          Continue the most recent session without showing the picker

      --all
          Show all sessions (disables cwd filtering and shows CWD column)

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

      --include-non-interactive
          Include non-interactive sessions in the resume picker and --last selection

      --remote <ADDR>
          Connect the TUI to a remote app server endpoint.
          
          Accepted forms: `ws://host:port`, `wss://host:port`, `unix://`, or `unix://PATH`.

      --remote-auth-token-env <ENV_VAR>
          Name of the environment variable containing the bearer token to send to a remote app
          server websocket

      --strict-config
          Error out when config.toml contains fields that are not recognized by this version of
          Codex

  -i, --image <FILE>...
          Optional image(s) to attach to the initial prompt

  -m, --model <MODEL>
          Model the agent should use

      --oss
          Use open-source provider

      --local-provider <OSS_PROVIDER>
          Specify which local provider to use (lmstudio or ollama). If not specified with --oss,
          will use config default or show selection

  -p, --profile <CONFIG_PROFILE_V2>
          Layer $CODEX_HOME/<name>.config.toml on top of the base user config

  -s, --sandbox <SANDBOX_MODE>
          Select the sandbox policy to use when executing model-generated shell commands
          
          [possible values: read-only, workspace-write, danger-full-access]

      --dangerously-bypass-approvals-and-sandbox
          Skip all confirmation prompts and execute commands without sandboxing. EXTREMELY
          DANGEROUS. Intended solely for running in environments that are externally sandboxed

      --dangerously-bypass-hook-trust
          Run enabled hooks without requiring persisted hook trust for this invocation. DANGEROUS.
          Intended only for automation that already vets hook sources

  -C, --cd <DIR>
          Tell the agent to use the specified directory as its working root

      --add-dir <DIR>
          Additional directories that should be writable alongside the primary workspace

  -a, --ask-for-approval <APPROVAL_POLICY>
          Configure when the model requires human approval before executing a command

          Possible values:
          - untrusted:  Only run "trusted" commands (e.g. ls, cat, sed) without asking for user
            approval. Will escalate to the user if the model proposes a command that is not in the
            "trusted" set
          - on-request: The model decides when to ask the user for approval
          - never:      Never ask for user approval Execution failures are immediately returned to
            the model

      --search
          Enable live web search. When enabled, the native Responses `web_search` tool is available
          to the model (no per‑call approval)

      --no-alt-screen
          Disable alternate screen mode
          
          Runs the TUI in inline mode, preserving terminal scrollback history.

  -h, --help
          Print help (see a summary with '-h')

  -V, --version
          Print version
```

## codex archive

```
Archive a saved session by id or session name

Usage: codex archive [OPTIONS] <SESSION>

Arguments:
  <SESSION>
          Session id (UUID) or session name. UUIDs take precedence if it parses

Options:
      --remote <ADDR>
          Connect the TUI to a remote app server endpoint.
          
          Accepted forms: `ws://host:port`, `wss://host:port`, `unix://`, or `unix://PATH`.

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

      --remote-auth-token-env <ENV_VAR>
          Name of the environment variable containing the bearer token to send to a remote app
          server websocket

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

  -i, --image <FILE>...
          Optional image(s) to attach to the initial prompt

  -m, --model <MODEL>
          Model the agent should use

      --oss
          Use open-source provider

      --local-provider <OSS_PROVIDER>
          Specify which local provider to use (lmstudio or ollama). If not specified with --oss,
          will use config default or show selection

  -p, --profile <CONFIG_PROFILE_V2>
          Layer $CODEX_HOME/<name>.config.toml on top of the base user config

  -s, --sandbox <SANDBOX_MODE>
          Select the sandbox policy to use when executing model-generated shell commands
          
          [possible values: read-only, workspace-write, danger-full-access]

      --dangerously-bypass-approvals-and-sandbox
          Skip all confirmation prompts and execute commands without sandboxing. EXTREMELY
          DANGEROUS. Intended solely for running in environments that are externally sandboxed

      --dangerously-bypass-hook-trust
          Run enabled hooks without requiring persisted hook trust for this invocation. DANGEROUS.
          Intended only for automation that already vets hook sources

  -C, --cd <DIR>
          Tell the agent to use the specified directory as its working root

      --add-dir <DIR>
          Additional directories that should be writable alongside the primary workspace

      --strict-config
          Error out when config.toml contains fields that are not recognized by this version of
          Codex

  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

  -h, --help
          Print help (see a summary with '-h')
```

## codex delete

```
Permanently delete a saved session by id or session name

Usage: codex delete [OPTIONS] <SESSION>

Arguments:
  <SESSION>
          Session id (UUID) or session name. UUIDs take precedence if it parses

Options:
      --remote <ADDR>
          Connect the TUI to a remote app server endpoint.
          
          Accepted forms: `ws://host:port`, `wss://host:port`, `unix://`, or `unix://PATH`.

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

      --remote-auth-token-env <ENV_VAR>
          Name of the environment variable containing the bearer token to send to a remote app
          server websocket

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

  -i, --image <FILE>...
          Optional image(s) to attach to the initial prompt

  -m, --model <MODEL>
          Model the agent should use

      --oss
          Use open-source provider

      --local-provider <OSS_PROVIDER>
          Specify which local provider to use (lmstudio or ollama). If not specified with --oss,
          will use config default or show selection

  -p, --profile <CONFIG_PROFILE_V2>
          Layer $CODEX_HOME/<name>.config.toml on top of the base user config

  -s, --sandbox <SANDBOX_MODE>
          Select the sandbox policy to use when executing model-generated shell commands
          
          [possible values: read-only, workspace-write, danger-full-access]

      --dangerously-bypass-approvals-and-sandbox
          Skip all confirmation prompts and execute commands without sandboxing. EXTREMELY
          DANGEROUS. Intended solely for running in environments that are externally sandboxed

      --dangerously-bypass-hook-trust
          Run enabled hooks without requiring persisted hook trust for this invocation. DANGEROUS.
          Intended only for automation that already vets hook sources

  -C, --cd <DIR>
          Tell the agent to use the specified directory as its working root

      --add-dir <DIR>
          Additional directories that should be writable alongside the primary workspace

      --strict-config
          Error out when config.toml contains fields that are not recognized by this version of
          Codex

  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

      --force
          Delete without prompting. SESSION must be a UUID

  -h, --help
          Print help (see a summary with '-h')
```

## codex unarchive

```
Unarchive a saved session by id or session name

Usage: codex unarchive [OPTIONS] <SESSION>

Arguments:
  <SESSION>
          Session id (UUID) or session name. UUIDs take precedence if it parses

Options:
      --remote <ADDR>
          Connect the TUI to a remote app server endpoint.
          
          Accepted forms: `ws://host:port`, `wss://host:port`, `unix://`, or `unix://PATH`.

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

      --remote-auth-token-env <ENV_VAR>
          Name of the environment variable containing the bearer token to send to a remote app
          server websocket

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

  -i, --image <FILE>...
          Optional image(s) to attach to the initial prompt

  -m, --model <MODEL>
          Model the agent should use

      --oss
          Use open-source provider

      --local-provider <OSS_PROVIDER>
          Specify which local provider to use (lmstudio or ollama). If not specified with --oss,
          will use config default or show selection

  -p, --profile <CONFIG_PROFILE_V2>
          Layer $CODEX_HOME/<name>.config.toml on top of the base user config

  -s, --sandbox <SANDBOX_MODE>
          Select the sandbox policy to use when executing model-generated shell commands
          
          [possible values: read-only, workspace-write, danger-full-access]

      --dangerously-bypass-approvals-and-sandbox
          Skip all confirmation prompts and execute commands without sandboxing. EXTREMELY
          DANGEROUS. Intended solely for running in environments that are externally sandboxed

      --dangerously-bypass-hook-trust
          Run enabled hooks without requiring persisted hook trust for this invocation. DANGEROUS.
          Intended only for automation that already vets hook sources

  -C, --cd <DIR>
          Tell the agent to use the specified directory as its working root

      --add-dir <DIR>
          Additional directories that should be writable alongside the primary workspace

      --strict-config
          Error out when config.toml contains fields that are not recognized by this version of
          Codex

  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

  -h, --help
          Print help (see a summary with '-h')
```

## codex fork

```
Fork a previous interactive session (picker by default; use --last to fork the most recent)

Usage: codex fork [OPTIONS] [SESSION_ID] [PROMPT]

Arguments:
  [SESSION_ID]
          Conversation/session id (UUID). When provided, forks this session. If omitted, use --last
          to pick the most recent recorded session

  [PROMPT]
          Optional user prompt to start the session

Options:
  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

      --last
          Fork the most recent session without showing the picker

      --all
          Show all sessions (disables cwd filtering and shows CWD column)

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

      --remote <ADDR>
          Connect the TUI to a remote app server endpoint.
          
          Accepted forms: `ws://host:port`, `wss://host:port`, `unix://`, or `unix://PATH`.

      --remote-auth-token-env <ENV_VAR>
          Name of the environment variable containing the bearer token to send to a remote app
          server websocket

      --strict-config
          Error out when config.toml contains fields that are not recognized by this version of
          Codex

  -i, --image <FILE>...
          Optional image(s) to attach to the initial prompt

  -m, --model <MODEL>
          Model the agent should use

      --oss
          Use open-source provider

      --local-provider <OSS_PROVIDER>
          Specify which local provider to use (lmstudio or ollama). If not specified with --oss,
          will use config default or show selection

  -p, --profile <CONFIG_PROFILE_V2>
          Layer $CODEX_HOME/<name>.config.toml on top of the base user config

  -s, --sandbox <SANDBOX_MODE>
          Select the sandbox policy to use when executing model-generated shell commands
          
          [possible values: read-only, workspace-write, danger-full-access]

      --dangerously-bypass-approvals-and-sandbox
          Skip all confirmation prompts and execute commands without sandboxing. EXTREMELY
          DANGEROUS. Intended solely for running in environments that are externally sandboxed

      --dangerously-bypass-hook-trust
          Run enabled hooks without requiring persisted hook trust for this invocation. DANGEROUS.
          Intended only for automation that already vets hook sources

  -C, --cd <DIR>
          Tell the agent to use the specified directory as its working root

      --add-dir <DIR>
          Additional directories that should be writable alongside the primary workspace

  -a, --ask-for-approval <APPROVAL_POLICY>
          Configure when the model requires human approval before executing a command

          Possible values:
          - untrusted:  Only run "trusted" commands (e.g. ls, cat, sed) without asking for user
            approval. Will escalate to the user if the model proposes a command that is not in the
            "trusted" set
          - on-request: The model decides when to ask the user for approval
          - never:      Never ask for user approval Execution failures are immediately returned to
            the model

      --search
          Enable live web search. When enabled, the native Responses `web_search` tool is available
          to the model (no per‑call approval)

      --no-alt-screen
          Disable alternate screen mode
          
          Runs the TUI in inline mode, preserving terminal scrollback history.

  -h, --help
          Print help (see a summary with '-h')

  -V, --version
          Print version
```

## codex cloud

```
[EXPERIMENTAL] Browse tasks from Codex Cloud and apply changes locally

Usage: codex cloud [OPTIONS] [COMMAND]

Commands:
  exec    Submit a new Codex Cloud task without launching the TUI
  status  Show the status of a Codex Cloud task
  list    List Codex Cloud tasks
  apply   Apply the diff for a Codex Cloud task locally
  diff    Show the unified diff for a Codex Cloud task
  help    Print this message or the help of the given subcommand(s)

Options:
  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

  -h, --help
          Print help (see a summary with '-h')

  -V, --version
          Print version
```

## codex cloud exec

```
Submit a new Codex Cloud task without launching the TUI

Usage: codex cloud exec [OPTIONS] --env <ENV_ID> [QUERY]

Arguments:
  [QUERY]
          Task prompt to run in Codex Cloud

Options:
  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

      --env <ENV_ID>
          Target environment identifier (see `codex cloud` to browse)

      --attempts <ATTEMPTS>
          Number of assistant attempts (best-of-N)
          
          [default: 1]

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

      --branch <BRANCH>
          Git branch to run in Codex Cloud (defaults to current branch)

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

  -h, --help
          Print help (see a summary with '-h')
```

## codex cloud status

```
Show the status of a Codex Cloud task

Usage: codex cloud status [OPTIONS] <TASK_ID>

Arguments:
  <TASK_ID>
          Codex Cloud task identifier to inspect

Options:
  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

  -h, --help
          Print help (see a summary with '-h')
```

## codex cloud list

```
List Codex Cloud tasks

Usage: codex cloud list [OPTIONS]

Options:
  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

      --env <ENV_ID>
          Filter tasks by environment identifier

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

      --limit <N>
          Maximum number of tasks to return (1-20)
          
          [default: 20]

      --cursor <CURSOR>
          Pagination cursor returned by a previous call

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

      --json
          Emit JSON instead of plain text

  -h, --help
          Print help (see a summary with '-h')
```

## codex cloud apply

```
Apply the diff for a Codex Cloud task locally

Usage: codex cloud apply [OPTIONS] <TASK_ID>

Arguments:
  <TASK_ID>
          Codex Cloud task identifier to apply

Options:
      --attempt <N>
          Attempt number to apply (1-based)

  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

  -h, --help
          Print help (see a summary with '-h')
```

## codex cloud diff

```
Show the unified diff for a Codex Cloud task

Usage: codex cloud diff [OPTIONS] <TASK_ID>

Arguments:
  <TASK_ID>
          Codex Cloud task identifier to display

Options:
      --attempt <N>
          Attempt number to display (1-based)

  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

  -h, --help
          Print help (see a summary with '-h')
```

## codex exec-server

```
[EXPERIMENTAL] Run the standalone exec-server service

Usage: codex exec-server [OPTIONS]

Options:
  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

      --strict-config
          Error out when config.toml contains fields that are not recognized by this version of
          Codex

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

      --listen <URL>
          Transport endpoint URL. Supported values: `ws://IP:PORT` (default), `stdio`, `stdio://`

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

      --remote <URL>
          Register this exec-server as a remote environment using the given base URL

      --environment-id <ID>
          Environment id to attach to when registering remotely

      --name <NAME>
          Human-readable environment name

      --use-agent-identity-auth
          Use Agent Identity auth from CODEX_ACCESS_TOKEN for remote registration

  -h, --help
          Print help (see a summary with '-h')
```

## codex features

```
Inspect feature flags

Usage: codex features [OPTIONS] <COMMAND>

Commands:
  list     List known features with their stage and effective state
  enable   Enable a feature in config.toml
  disable  Disable a feature in config.toml
  help     Print this message or the help of the given subcommand(s)

Options:
  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

  -h, --help
          Print help (see a summary with '-h')
```

## codex features list

```
List known features with their stage and effective state

Usage: codex features list [OPTIONS]

Options:
  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

  -h, --help
          Print help (see a summary with '-h')
```

## codex features enable

```
Enable a feature in config.toml

Usage: codex features enable [OPTIONS] <FEATURE>

Arguments:
  <FEATURE>
          Feature key to update (for example: unified_exec)

Options:
  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

  -h, --help
          Print help (see a summary with '-h')
```

## codex features disable

```
Disable a feature in config.toml

Usage: codex features disable [OPTIONS] <FEATURE>

Arguments:
  <FEATURE>
          Feature key to update (for example: unified_exec)

Options:
  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

  -h, --help
          Print help (see a summary with '-h')
```

