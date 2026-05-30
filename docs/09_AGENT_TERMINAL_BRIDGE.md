# Agent Terminal Bridge 設計メモ

## 目的

AgentCockpit では、AI Agent がビルド、初期化、デプロイ、実行確認を進める。ただし `sudo` パスワード、`gh auth login`、クラウド認証などは AI に渡さず、人間が VSCode integrated terminal 上で直接入力する。

そのため、通常処理は AI 側の裏実行で進め、sudo/auth など人間入力が必要な場面だけ visible terminal へ handoff する。
AI と VSCode terminal を直接つなぐのではなく、明示的な橋を置く。

```text
AI / Codex
  -> agp setup command を裏で実行
  -> sudo/auth が必要なら agp terminal run
  -> .agp/terminal-requests/*.json
  -> AgentCockpit VSCode Extension
  -> VSCode Integrated Terminal
  -> Human sudo/auth input
```

## 現状

- `agp setup` はカテゴリ単位で状態を表示する。
  - 開発環境
  - シミュレート環境
  - 実機環境
- 設定済みカテゴリは選択済み provider だけを表示する。
- 選択状態は `.agp/config.json` に保存する。
- `.agp/` は git 管理しない。
- `agp terminal run` は `.agp/terminal-requests/*.json` を作る。
- provider が sudo/auth handoff を必要とした場合は、visible terminal request も作る。
- `agp setup` は VSCode Terminal Bridge の導入状況を表示する。
- `tools/vscode-agentcockpit/` に最小 VSCode extension プロトタイプがある。
  - `.agp/terminal-requests/*.json` を監視する。
  - 要求を受けたら VSCode integrated terminal を作成する。
  - コマンドは `sendText()` で terminal に送る。
  - terminal 出力の捕捉や追加入力送信は行わない。AI は裏で状態確認して復帰する。
  - `AgentCockpit: Run AGP Setup` コマンドも提供する。

## 使い方

AI の振る舞いルールは [10_AGENT_COLLABORATION_RULES.md](10_AGENT_COLLABORATION_RULES.md) を優先する。
通常作業は裏で実行し、sudo/auth など人間入力が必要な時だけ visible terminal に handoff する。

### VSCode extension のローカルインストール

```bash
make init
```

その後、VSCode window を reload する。

### Agent / MCP から visible terminal に投げる

MCP 設定例は `make init` で生成される。

```bash
.agp/mcp-config.json
```

MCP tool `run_in_visible_terminal` は以下の request を作る。

```json
{
  "command": ".venv/bin/agp setup",
  "cwd": "/home/user/Yurufuwa/AgentCockpit",
  "title": "AgentCockpit"
}
```

MCP を使わず CLI から同じ request を作る場合:

```bash
agp terminal run --title AgentCockpit --command ".venv/bin/agp setup"
```

## 残りの作業

### 1. request/status の整理

現状は extension が `started` / `invalid` status を書き、request を `processed/` に移動する。

- `.agp/terminal-requests/*.json`: 未処理要求
- `.agp/terminal-status/*.json`: started / invalid など

実行結果は terminal から読まず、AI が裏で状態確認コマンドを実行して判断する。

### 2. agp setup への統合を育てる

`agp setup` は VSCode Terminal Bridge の有無を確認する。

導入済みなら、AI は sudo が必要な処理を `agp terminal run` 経由で visible terminal に流せる。
未導入の場合は、TTY 実行時に `agp setup` から直接導入できる。まとめて整える場合は `make init` を実行する。

MCP 設定は `make init` が `.agp/mcp-config.json` に生成する。

## 作らないもの

- terminal emulator
- sudo password 入力 UI
- shell / PTY の独自実装
- VSCode terminal の再実装
- Marketplace 公開前提の仕組み

## 次のAIへの作業指針

1. まず `python3 -m unittest discover -s tests` を通す。
2. `make init` を実行し、VSCode window を reload する。
3. MCP 設定に `.agp/mcp-config.json` の内容を登録する。
4. `run_in_visible_terminal` で visible terminal にコマンドが流れるところを確認する。
5. handoff 後は `agp setup --no-install` や `which ... --version` を裏で実行して復帰する。
