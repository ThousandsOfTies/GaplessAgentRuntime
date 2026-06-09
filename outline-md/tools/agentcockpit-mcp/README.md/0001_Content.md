# Gapless Agent Runtime MCP Server

Gapless Agent Runtime 用の最小 MCP server です。

VSCode integrated terminal を直接制御するのではなく、`.gar/terminal-requests/*.json` に request を作成します。`tools/vscode-agentcockpit` の VSCode extension がそれを拾い、人間が見える integrated terminal にコマンドを送ります。

AI の運用ルールは `docs/10_AGENT_COLLABORATION_RULES.md` を優先します。通常作業は裏で実行し、sudo password / GitHub 認証 / cloud auth など人間入力が必要な時だけ、この MCP server で visible terminal に handoff します。
