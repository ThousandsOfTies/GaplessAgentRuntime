# Agent Terminal Bridge 設計メモ

> このドキュメントは **bridge の仕組み（request ファイル・extension・status）** を扱います。
> AI の**振る舞いルール**（いつ裏で実行し、いつ handoff するか）は [AGENT.md「Terminal 操作の原則」](../AGENT.md) を正本とします。

## 目的

Gapless Agent Runtime では、AI Agent がビルド、初期化、デプロイ、実行確認を進める。ただし `sudo` パスワード、`gh auth login`、クラウド認証などは AI に渡さず、人間が VSCode integrated terminal 上で直接入力する。

そのため、通常処理は AI 側の裏実行で進め、sudo/auth など人間入力が必要な場面だけ visible terminal へ handoff する（判断基準の詳細は [AGENT.md「Terminal 操作の原則」](../AGENT.md)）。
AI と VSCode terminal を直接つなぐのではなく、明示的な橋を置く。

```text
AI / Codex
  -> gar setup command を裏で実行
  -> sudo/auth が必要なら gar terminal run
  -> .gar/terminal-requests/*.json
  -> Gapless Agent Runtime VSCode Extension
  -> VSCode Integrated Terminal
  -> Human sudo/auth input
```

## 現状

- `gar setup` はカテゴリ単位で状態を表示する。
  - 開発環境
  - シミュレート環境
  - 実機環境
- 設定済みカテゴリは選択済み provider だけを表示する。
- 選択状態は `.gar/config.json` に保存する。
- `.gar/` は git 管理しない。
- `gar terminal run` は `.gar/terminal-requests/*.json` を作る。
- provider が sudo/auth handoff を必要とした場合は、visible terminal request も作る。
- `gar setup` は VSCode Terminal Bridge の導入状況を表示する。
- `tools/vscode-agentcockpit/` に最小 VSCode extension プロトタイプがある。
  - `.gar/terminal-requests/*.json` を監視する。
  - 要求を受けたら VSCode integrated terminal を作成する。
  - コマンドは `sendText()` で terminal に送る。
  - terminal 出力の捕捉や追加入力送信は行わない。AI は裏で状態確認して復帰する。
  - `Gapless Agent Runtime: Run gar setup` コマンドも提供する。

## 使い方

AI の振る舞いルールは [AGENT.md「Terminal 操作の原則」](../AGENT.md) を優先する。
通常作業は裏で実行し、sudo/auth など人間入力が必要な時だけ visible terminal に handoff する。

### VSCode extension のローカルインストール

```bash
make init
```

その後、VSCode window を reload する。

### Agent / MCP から visible terminal に投げる

MCP 設定例は `make init` で生成される。

```bash
.gar/mcp-config.json
```

MCP tool `run_in_visible_terminal` は以下の request を作る。

```json
{
  "command": ".venv/bin/gar setup",
  "cwd": "/home/user/AI/GaplessAgentRuntime",
  "title": "Gapless Agent Runtime"
}
```

MCP を使わず CLI から同じ request を作る場合:

```bash
gar terminal run --title Gapless Agent Runtime --command ".venv/bin/gar setup"
```

## 残りの作業

### 1. request/status の整理

現状は extension が `started` / `invalid` status を書き、request を `processed/` に移動する。

- `.gar/terminal-requests/*.json`: 未処理要求
- `.gar/terminal-status/*.json`: started / invalid など

実行結果は terminal から読まず、AI が裏で状態確認コマンドを実行して判断する。

### 2. gar setup への統合を育てる

`gar setup` は VSCode Terminal Bridge の有無を確認する。

導入済みなら、AI は sudo が必要な処理を `gar terminal run` 経由で visible terminal に流せる。
未導入の場合は、TTY 実行時に `gar setup` から直接導入できる。まとめて整える場合は `make init` を実行する。

MCP 設定は `make init` が `.gar/mcp-config.json` に生成する。

## 作らないもの

- terminal emulator
- sudo password 入力 UI
- shell / PTY の独自実装
- VSCode terminal の再実装
- Marketplace 公開前提の仕組み

## 次のAIへの作業指針

> Terminal Bridge の振る舞いルール（いつ裏で実行し、いつ handoff するか）は `AGENT.md` の「Terminal 操作の原則」を参照。

1. まず `python3 -m unittest discover -s tests` を通す。
2. `make init` を実行し、VSCode window を reload する。
3. MCP 設定に `.gar/mcp-config.json` の内容を登録する。
4. `run_in_visible_terminal` で visible terminal にコマンドが流れるところを確認する。
5. handoff 後は `gar setup --no-install` や `which ... --version` を裏で実行して復帰する（詳細は `AGENT.md`）。
