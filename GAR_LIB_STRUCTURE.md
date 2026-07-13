# `scripts/gar_lib` 構成と責務

`scripts/gar_lib` は GAR CLI の実装本体です。現在の構成と、責務分離のために把握しておく依存関係を記録します。

```text
gar_lib/
├─ commands/       CLI のユースケース実装
├─ core/           workspace・artifact・command・domain error
├─ workspaces/     workspace 設定の検索
├─ build/          build environment と製品build hook
├─ artifacts/      artifact.json と成果物の解決・保管
├─ access/         SSH・scp・ADB・AWS CLI 等のアクセス手段
├─ simulation/     simulation environment と host lifecycle
├─ recovery/       接続失敗の復旧方針とTerminal Bridge連携
├─ environments/   移行前のprovider実装と自動発見
├─ vscode/         VS Code 統合
├─ config.py       GAR の設定保存・workspace 選択
├─ gar_tools.py    gar-tools checkout の検出・導入
└─ cli.py          引数解析と各 commands への振り分け
```

## フォルダごとの役割

| フォルダ | 役割 |
|---|---|
| `commands/` | `gar sim`、`gar target`、`gar setup`、`gar code` など、ユーザーが実行する操作を組み立てるユースケース層。何を実行するか、どの成果物をどこへ配置するかを決定する。 |
| `core/` | workspace、artifact、GAR command、利用者へ説明可能なdomain errorなど、外部接続に依存しないモデル。 |
| `workspaces/` | `.gar/config.json` のworkspaceを識別子・名前・既定選択から解決する。 |
| `build/` | Local・Codespaces等のbuild environmentを選び、製品build hookからartifactを生成する。 |
| `access/` | SSH command、scp、ADB、serial、AWS CLI、local process、SSH config更新などの個別アクセス能力。simulation固有の判断は持たない。 |
| `recovery/` | 構造化された接続失敗を利用者向けの復旧操作へ変換し、必要な場合だけTerminal Bridgeへ渡す。 |
| `environments/` | 実行環境 provider の共通インターフェースと provider 自動発見の仕組み。接続方法・環境固有の実装を置く。 |
| `environments/registry/codespace/` | Local と GitHub Codespaces の、開発・ビルド環境 provider。 |
| `environments/registry/simulator/` | SSH Remote、Wokwi、Renode、MuJoCo、QEMU 等のシミュレータ provider。`aws_ec2` は SSH transport ではなく、EC2 の起動停止・Public IP 解決を担う補助実装。 |
| `environments/registry/target/` | adb、SSH/scp、esptool 等の実機到達 provider。 |
| `simulation/` | Linux systemd/CUSE・Wokwi等のruntime操作、診断結果、EC2等のsimulation host lifecycleを表現する。アクセス手段は `access/` から注入する。Wokwiはhost controllerやruntime artifactを持たないローカル実行環境として実装する。 |
| `artifacts/` | artifact manifest の検証、成果物配置先の解決、Codespaces からの取得。 |
| `vscode/` | terminal profile、Terminal Bridge 拡張の導入、terminal 表示用 UI の補助。 |

`environments/registry/development/`、`environments/registry/simulation/`、`environments/registry/target_access/` は現在は空の旧フォルダです。provider 自動発見の対象は、実装のある `codespace`、`simulator`、`target` の3分類です。

## 直下モジュールの役割

| モジュール | 役割 |
|---|---|
| `cli.py` | 引数解析と dispatch の入口。互換性のため各機能を再 export している。 |
| `config.py` | `.gar/config.json`、workspace 選択、EC2 接続設定の保存と読み込み。 |
| `gar_tools.py` | `gar-tools` checkout の場所解決と必要時の取得。 |

## 現在確認できる責務の混在

アクセス手段とコマンド実行を分離する観点で、次の依存関係は整理対象です。

1. 互換経路の `SshRemoteEnvironment` は、現在も `ssh_recovery` を通じて AWS 認証と Terminal Bridge の復旧 UI に関与している。標準のsim経路は `access/`・`simulation/`・`recovery/` に分離済み。
2. `environments/ssh_recovery` が `commands/terminal` を import しており、下位の環境層から上位のコマンド層へ依存している。
3. `simulation/linux` が `commands/hw` を import しており、実行モデル層がユースケース層へ依存している。
4. `artifacts` が `commands/code` を import しており、成果物層からコマンド層への逆向き依存がある。

## 分離後の目標

依存方向を次のように揃える。

```text
cli
  ↓
commands             # ユースケースと復旧方針
  ↓
core / workspaces / build / artifacts / simulation / recovery
  ↓
access               # SSH, scp, adb, AWS CLI 等の純粋なアクセス能力
  ↓
external systems
```

- `environments` は接続・転送・リモート実行の結果だけを返し、AWS 認証・Terminal Bridge・ユーザー向け文言を持たない。
- `commands` または専用の access orchestration 層が接続失敗を分類し、必要な復旧手順を決定する。
- `vscode` はユーザー入力が必要な復旧操作を visible terminal へ渡す実装として使う。
- `simulation` と `artifacts` は command 層に依存せず、入力された設定・provider・成果物を処理する。
