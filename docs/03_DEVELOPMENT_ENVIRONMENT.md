# 開発環境方針メモ

Gapless Agent Runtime の開発環境は、**制御・操作をできるだけ WSL2 に集約し、Windows ネイティブは原則使わなくても成り立つ状態**を目指します。

目的は、開発スクリプトをシンプルに保ちつつ、ビルド負荷を作業 PC だけに抱え込ませないことです。そのため、開発者向けの操作は Linux（WSL2 / Codespaces）を正規経路とし、Windows 固有の手順は段階的に減らしていきます。

---

## 基本方針

```text
標準開発・制御環境: WSL2 Ubuntu（ここから gar で全てを動かす）
クラウド開発環境: GitHub Codespaces + devcontainer
Windows ネイティブ: 原則不要。USB 経路など残存依存のみ、減らしていく対象
公式判定: GitHub Actions / CI
```

ビルド、テスト、ARM バイナリ生成、デプロイ、EC2 / 実機制御といった開発者向け操作は、すべて WSL2 上の `gar` コマンドから実行できることを目指します。

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

Codespaces 上のファイルを WSL2 側の VS Code Explorer で確認したい場合は `sshfs` でマウントする（`gar code start` が自動設定）。

- **用途**: ファイル配置の目視確認・軽い編集
- **使わない場面**: 重い検索・ビルド・watch・dev server（Codespace 内で直接実行する）
- **人間の視界**: WSL2 + sshfs + VS Code Explorer
- **AI の実作業**: `gh codespace ssh` して Codespace ローカルで検索・ビルド

```bash
gar code start   # マウント・SSH設定・terminal profile を一括設定
gar code stop    # アンマウント・profile 削除
```

Hardware Panel を WSL2/VS Code から見る場合:

```bash
gar sim env start   # EC2:8080/8765 を WSL2:127.0.0.1 に転送
gar sim env status
gar sim env stop
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

**制御・操作は WSL2 上の `gar` に集約済み**です。simulation VM 起動・停止（`gar sim boot` / `gar sim shutdown`）も実機デプロイ（`gar target deploy`）も WSL2 から実行でき、Windows ネイティブは原則不要です。

USB-C 実機への adb も、`usbipd-win` を WSL2 から呼び出す `gar usb attach` で WSL2 に通せます。busid は自動検出・記憶されるので、初回の `usbipd bind`（管理者・一度だけ）以降は `gar usb attach` だけで実機が WSL2 に現れます。ネットワーク経由の SSH / scp provider（`gar target deploy --host <ssh-host>`）も選べます。

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

Gapless Agent Runtime では、Windows を操作の入口として活かしながら、開発・ビルドの複雑さは WSL2 / Codespaces 側に寄せます。これにより、開発スクリプトをシンプルに保ち、ビルド負荷のスケール先を確保し、AI エージェントが再現しやすい環境を提供します。
