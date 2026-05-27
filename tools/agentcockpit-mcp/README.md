# AgentCockpit MCP Server

AgentCockpit 用の最小 MCP server です。

VSCode integrated terminal を直接制御するのではなく、`.agp/terminal-requests/*.json` に request を作成します。`tools/vscode-agentcockpit` の VSCode extension がそれを拾い、人間が見える integrated terminal にコマンドを送ります。

AI の運用ルールは `docs/10_AGENT_COLLABORATION_RULES.md` を優先します。通常作業は裏で実行し、sudo password / GitHub 認証 / cloud auth など人間入力が必要な時だけ、この MCP server で visible terminal に handoff します。

## MCP 設定例

```json
{
  "mcpServers": {
    "agentcockpit": {
      "command": "python3",
      "args": ["/home/user/Yurufuwa/AgentCockpit/tools/agentcockpit-mcp/server.py"]
    }
  }
}
```

現在の環境向けの設定は次で出力できます。

```bash
make mcp-config
```

## Tools

### run_in_visible_terminal

VSCode integrated terminal で実行する request を作成します。

```json
{
  "command": "source .venv/bin/activate && agp init",
  "cwd": "/home/user/Yurufuwa/AgentCockpit",
  "title": "AgentCockpit"
}
```

### list_terminal_status

`.agp/terminal-status/*.json` を一覧します。

### get_terminal_status

指定 id の status を取得します。
