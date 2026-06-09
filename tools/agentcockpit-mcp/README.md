# Gapless Agent Runtime MCP Server

Gapless Agent Runtime 用の最小 MCP server です。

VSCode integrated terminal を直接制御するのではなく、`.gar/terminal-requests/*.json` に request を作成します。`tools/vscode-agentcockpit` の VSCode extension がそれを拾い、人間が見える integrated terminal にコマンドを送ります。

AI の運用ルールは [`../../AGENT.md`「Terminal 操作の原則」](../../AGENT.md) を優先します。通常作業は裏で実行し、sudo password / GitHub 認証 / cloud auth など人間入力が必要な時だけ、この MCP server で visible terminal に handoff します。

## MCP 設定例

```json
{
  "mcpServers": {
    "gar": {
      "command": "python3",
      "args": ["/home/user/AI/AgentCockpit/tools/agentcockpit-mcp/server.py"]
    }
  }
}
```

現在の環境向けの設定は `make init` で生成できます。

```bash
.gar/mcp-config.json
```

## Tools

### run_in_visible_terminal

VSCode integrated terminal で実行する request を作成します。

```json
{
  "command": ".venv/bin/gar setup",
  "cwd": "/home/user/AI/AgentCockpit",
  "title": "Gapless Agent Runtime"
}
```

### list_terminal_status

`.gar/terminal-status/*.json` を一覧します。

### get_terminal_status

指定 id の status を取得します。
