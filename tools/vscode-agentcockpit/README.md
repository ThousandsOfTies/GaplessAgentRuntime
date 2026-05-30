# AgentCockpit Terminal Bridge

VSCode integrated terminal に AgentCockpit の実行要求を流すための拡張です。

Agent は `.agp/terminal-requests/*.json` に要求を書きます。拡張はそのファイルを監視し、VSCode の見える terminal を開いてコマンドを送ります。`sudo` のパスワード入力が必要な場合は、その terminal に人間が入力します。

## Agent からの使い方

```bash
agp terminal run --title "AgentCockpit" --command ".venv/bin/agp setup"
```

## VSCode からの使い方

ローカルインストール:

```bash
make init
```

インストール後、VSCode window を reload してください。

Command Palette で次を実行します。

```text
AgentCockpit: Run AGP Setup
```

## Request / Status

この拡張は以下を監視します。

```text
.agp/terminal-requests/*.json
```

terminal にコマンドを送ったら status を書きます。

```text
.agp/terminal-status/<request-id>.json
```
