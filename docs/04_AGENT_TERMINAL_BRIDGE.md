# Agent Terminal Bridge

Agent Terminal Bridgeは、AIが直接入力できない認証や`sudo`操作を、VS Code integrated terminalへ引き渡す仕組みです。

```text
AI / CLI / MCP
    │ request JSON
    ▼
.gar/terminal-requests/
    │
    ▼
VS Code extension
    │
    ▼
Visible terminal → Human input
```

通常のコマンドは裏で実行し、人間入力が必要な場面だけBridgeを使います。詳しい判断ルールは[AGENT.md](../AGENT.md)が正本です。

## 準備

```bash
make init
```

VS Code windowをreloadすると、`tools/vscode-gar/`のextensionがrequestを監視します。MCP設定は`.gar/mcp-config.json`へ生成されます。

## CLIから依頼する

```bash
gar terminal run \
  --title "Gapless Agent Runtime" \
  --command "gar config"
```

古いrequestを確認して削除する場合:

```bash
gar terminal gc --dry-run
gar terminal gc --keep-days 7
```

## 保存場所

| Path | 内容 |
|---|---|
| `.gar/terminal-requests/*.json` | 未処理request |
| `.gar/terminal-status/*.json` | `started`、`invalid`等の状態 |

extensionはrequestを検証し、terminalへ送信できた後だけ処理済みにします。terminal出力は捕捉しないため、完了後は対象の`status`や`diag`を別途実行して確認します。

Bridgeはterminal emulator、password入力UI、独自PTYを実装しません。
