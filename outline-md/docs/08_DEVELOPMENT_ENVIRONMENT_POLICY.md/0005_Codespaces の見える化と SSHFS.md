## Codespaces の見える化と SSHFS

Codespaces 上のファイルを WSL2 側の VS Code Explorer で確認したい場合は、`sshfs` で Codespace の特定ディレクトリを WSL2 にマウントする。

これは、AI が Codespaces 上で裏作業を進める時にも、人間がファイル配置やディレクトリ構造を自分の VS Code Explorer で確認できるようにするための補助線である。

```text
Codespace:
  /workspaces/AgentCockpit

WSL2:
  ~/codespaces/AgentCockpit

VS Code:
  WSL2 側のマウントポイントを開き、Explorer で構造確認・軽い編集を行う
```

`sshfs` は通常のファイルシステムのように見えるため、`grep` / `rg` / `find` などの検索も実行できる。ただし、大量ファイルを読む処理は SSH 越しになるため、ローカル実体ファイルより遅くなる。

特に `node_modules`、`.git`、`dist`、`build` などを含む全文検索や watch 前提の開発サーバーは、`sshfs` 上では重くなったり変更検知が不安定になったりする可能性がある。

そのため、`sshfs` は次の目的に絞って使う。

- VS Code Explorer で Codespaces 側のファイル配置を確認する。
- 既存構成に沿っているか、人間が目視でレビューする。
- 軽いファイル編集やピンポイント検索を行う。

重い検索、ビルド、テスト、watch、dev server は Codespace 内で直接実行する。

```text
人間の視界:
  WSL2 + sshfs + VS Code Explorer

AI の実作業:
  gh codespace ssh
  cd /workspaces/AgentCockpit
  rg / build / test / logs
```

この分担により、`sshfs` の性能や watch 安定性に依存しすぎない。`sshfs` が遅い場合でも、AI は Codespace に SSH 接続して Codespace ローカルのファイルシステム上で検索・ビルド・テストを実行できる。

`sshfs` は「リモート作業をローカル VS Code から見えるようにするための UX 改善」として扱い、ビルド環境そのものの正規経路にはしない。

Codespace を作り直した後は、WSL2 側で次のセットアップを実行する。

```bash
gar code start
```

このコマンドは `~/.config/codespace-dev/env` に現在の接続先を書き込み、`~/.ssh/codespaces`、`sshfs` マウント、VS Code の `Codespaces` ターミナルプロファイルを同じ接続先に揃える。`gh codespace list` が 1 件なら `--codespace` は省略できる。

WSL2 側の Codespace 表示を止める場合は、次を実行する。

```bash
gar code stop
```

`gar code stop` は SSHFS mount を unmount し、VS Code の `Codespaces` ターミナルプロファイルを削除する。`~/.ssh/codespaces` と `~/.config/codespace-dev/env` は再接続用の cache として保持する。

EC2 の Virtual Hardware Panel を WSL2/VS Code から見る場合は、WSL2 側で次を実行する。

```bash
gar sim env start
```

これにより simulation runtime が起動し、EC2 上の `8080` / `8765` が WSL2 の `127.0.0.1:8080` / `127.0.0.1:8765` に転送される。停止と状態確認は次を使う。

```bash
gar sim env status
gar sim env stop
```

---
