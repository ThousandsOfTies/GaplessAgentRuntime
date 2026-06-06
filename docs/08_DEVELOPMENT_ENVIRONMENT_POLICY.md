# 開発環境方針メモ

AgentCockpit の開発環境は、**制御・操作をできるだけ WSL2 に集約し、Windows ネイティブは原則使わなくても成り立つ状態**を目指します。

目的は、開発スクリプトをシンプルに保ちつつ、ビルド負荷を作業 PC だけに抱え込ませないことです。そのため、開発者向けの操作は Linux（WSL2 / Codespaces）を正規経路とし、Windows 固有の手順は段階的に減らしていきます。

---

## 基本方針

```text
標準開発・制御環境: WSL2 Ubuntu（ここから agp で全てを動かす）
クラウド開発環境: GitHub Codespaces + devcontainer
Windows ネイティブ: 原則不要。USB 経路など残存依存のみ、減らしていく対象
公式判定: GitHub Actions / CI
```

ビルド、テスト、ARM バイナリ生成、デプロイ、EC2 / 実機制御といった開発者向け操作は、すべて WSL2 上の `agp` コマンドから実行できることを目指します。

これにより、PowerShell / Bash 差分、パス表現、環境変数、Unix コマンド互換などを吸収するためだけのメンテナンスを増やさない方針とします。

---

## WSL2 の位置づけ

WSL2 Ubuntu は、日常的な編集、ローカル確認、軽量なビルド作業の標準環境です。

Microsoft が Windows 上に標準提供している Linux 実行環境を使うことで、Windows PC を前提にしながらも、開発ツールチェーンは Linux に寄せられます。

主な役割:

- 日常的なソース編集
- Makefile / Bash 前提の開発コマンド実行
- 軽量なビルドとローカル検証
- Codespaces と近い実行環境での作業

---

## Codespaces の位置づけ

GitHub Codespaces は、作業 PC の計算資源を節約し、環境一致性を高めるためのクラウド開発環境です。

特に、ARM ビルド、重いビルド、検証、外部 PC からの作業、AI エージェントによる自律作業に向いています。

主な役割:

- 重いビルドや ARM バイナリ生成の実行
- 開発環境の再現性確保
- 作業 PC の CPU / RAM 負荷の分離
- VS Code / AI エージェントからの一貫した作業環境
- EC2 Graviton や RasPi5 へのデプロイ起点

Codespaces を使う場合、Remote-SSH で Codespace に入る必要はありません。通常は VS Code / GitHub Codespaces の接続機能、または `gh codespace ssh` を使います。

---

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
agp code start
```

このコマンドは `~/.config/codespace-dev/env` に現在の接続先を書き込み、`~/.ssh/codespaces`、`sshfs` マウント、VS Code の `Codespaces` ターミナルプロファイルを同じ接続先に揃える。`gh codespace list` が 1 件なら `--codespace` は省略できる。

WSL2 側の Codespace 表示を止める場合は、次を実行する。

```bash
agp code stop
```

`agp code stop` は SSHFS mount を unmount し、VS Code の `Codespaces` ターミナルプロファイルを削除する。`~/.ssh/codespaces` と `~/.config/codespace-dev/env` は再接続用の cache として保持する。

EC2 の Virtual Hardware Panel を WSL2/VS Code から見る場合は、WSL2 側で次を実行する。

```bash
agp sim env start
```

これにより simulation runtime が起動し、EC2 上の `8080` / `8765` が WSL2 の `127.0.0.1:8080` / `127.0.0.1:8765` に転送される。停止と状態確認は次を使う。

```bash
agp sim env status
agp sim env stop
```

---

## devcontainer の位置づけ

devcontainer は、Codespaces の環境定義として使います。

このリポジトリには `.devcontainer/devcontainer.json` を置き、必要な OS、ツール、VS Code 拡張、初期セットアップをリポジトリ側で管理します。

主なメリット:

- Node / C / ARM toolchain などのバージョン差分を減らせる
- Codespaces 起動時に必要ツールを自動セットアップできる
- 新しい PC や外部環境でも同じ開発環境を再現しやすい
- WSL2 側の環境設計とも揃えやすい

devcontainer は「全員に必須の魔法の箱」ではなく、Linux 前提の開発環境を再現可能にするための設定ファイルとして扱います。

---

## Windows ネイティブの位置づけ

**制御・操作は WSL2 上の `agp` に集約済み**です。simulation VM 起動・停止（`agp sim boot` / `agp sim shutdown`）も実機デプロイ（`agp native deploy`）も WSL2 から実行でき、Windows ネイティブは原則不要です。

USB-C 実機への adb も、`usbipd-win` を WSL2 から呼び出す `agp usb attach` で WSL2 に通せます。busid は自動検出・記憶されるので、初回の `usbipd bind`（管理者・一度だけ）以降は `agp usb attach` だけで実機が WSL2 に現れます。ネットワーク経由の SSH / scp provider（`agp native deploy --host <ssh-host>`）も選べます。

### 当面の Windows 入口（減らす対象）

次は依然として Windows から実行されることがありますが、いずれも「必須」ではなく「まだ残っている入口」です。

- VS Code / Antigravity からの接続（ホスト側 UI として）
- USB パススルー未設定環境での adb
- ブラウザや Simple Browser での確認

開発スクリプト全体を Windows ネイティブで完全対応させることはしません。`rm`, `cp`, `export`, `/tmp`, Bash 構文、パス区切り、改行コードなどの差分を吸収するためにスクリプトとドキュメントが複雑化するためで、そのコストはプロダクト本体や検証環境の整備に回します。


---

## 役割分担

| 環境 | 役割 | 優先度 |
|---|---|---|
| WSL2 Ubuntu | 日常開発、軽量ビルド、Linux 前提スクリプト実行 | 標準 |
| GitHub Codespaces | 重いビルド、環境再現、AI エージェント作業、外部 PC からの作業 | 標準オプション |
| devcontainer | Codespaces の環境定義、再現性の確保 | 維持 |
| Windows ネイティブ | 管理操作、接続、実機連携、軽い確認 | 補助 |
| GitHub Actions / CI | 正式なビルド・テスト・デプロイ判定 | 公式 |

---

## 運用ルール

- 開発・ビルド・検証コマンドは Linux 環境で動くことを優先する。
- Windows ネイティブ対応のためだけに npm scripts / Makefile を過度に分岐させない。
- Codespaces と WSL2 で同じ手順に近づける。
- devcontainer は必要最小限から始め、実際に必要になったツールだけ追加する。
- 秘密情報はリポジトリに置かず、GitHub Codespaces secrets / GitHub Actions secrets / ローカル環境変数で扱う。
- 最終的な正規判定は CI に置く。

---

## 判断メモ

この方針は、Windows を無視するためのものではありません。

エンタープライズ向けであるほど、作業 PC、クラウド開発環境、CI、実機検証環境の役割を分ける価値があります。

AgentCockpit では、Windows を操作の入口として活かしながら、開発・ビルドの複雑さは WSL2 / Codespaces 側に寄せます。これにより、開発スクリプトをシンプルに保ち、ビルド負荷のスケール先を確保し、AI エージェントが再現しやすい環境を提供します。
