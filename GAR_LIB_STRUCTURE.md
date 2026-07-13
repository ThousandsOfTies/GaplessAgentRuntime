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
├─ simulation/     simulation environment・host・hardware control
├─ target/         実機environmentとADB・serial・SSH/scpの組み立て
├─ recovery/       接続失敗の復旧方針とTerminal Bridge連携
├─ environments/   setup用environment候補と依存関係の自動発見
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
| `environments/` | `gar setup` に表示するenvironment候補、依存コマンド、導入方法を自動発見する仕組み。`EnvironmentSetupOption` はruntime操作を持たない。 |
| `environments/registry/codespace/` | Local と GitHub Codespaces をsetupで選択するためのメタデータと導入処理。 |
| `environments/registry/simulator/` | SSH Remote、Wokwi、Renode、MuJoCo、QEMU 等をsetupで選択するためのメタデータと導入処理。 |
| `environments/registry/target/` | adb、SSH/scp、esptool 等をsetupで選択するためのメタデータと導入処理。 |
| `simulation/` | Linux systemd/CUSE・Wokwi・MuJoCoのruntime操作、Bridge/GPIOのhardware control、診断結果、EC2等のsimulation host lifecycleを表現する。SSHやlocal process等のアクセス手段は `access/` から注入する。 |
| `target/` | ADB・serial・SSH/scpを組み合わせ、`TARGET_APP` artifactを実機へ配置する。実行先はworkspaceの実機環境設定から解決する。 |
| `artifacts/` | artifact manifest の検証、成果物配置先の解決、Codespaces からの取得。 |
| `vscode/` | terminal profile、Terminal Bridge 拡張の導入、terminal 表示用 UI の補助。 |

setup候補の自動発見対象は、実装のある `codespace`、`simulator`、`target` の3分類です。

## 直下モジュールの役割

| モジュール | 役割 |
|---|---|
| `cli.py` | 引数解析と `commands/` へのdispatchだけを行う入口。 |
| `config.py` | `.gar/config.json`、workspace 選択、EC2 接続設定の保存と読み込み。 |
| `gar_tools.py` | `gar-tools` checkout の場所解決と必要時の取得。 |

## `gar sim` の現在の分離

```text
cli.py
  ↓ workspace名 + GarCommand
commands/sim.py
  ├─ BuildEnvironment       build / clean
  ├─ ArtifactStore          成果物の選択
  ├─ SimulationEnvironment deploy / start / stop / status / diag / log
  ├─ SimulationHostController  EC2等のhost lifecycle
  └─ SimulationHardwareControl Bridge / GPIO操作
                                  ↓
                           access channels
```

- `commands/sim.py` はworkspaceから必要なenvironmentを解決し、ユースケースの順序だけを決める。
- `LinuxSystemdSimulationEnvironment` はSSHを知らず、注入されたcommand/file channelを使う。
- `LinuxBridgeHardwareControl` はGPIO・共通Bridge操作をruntime lifecycleから分離する。
- `WokwiSimulationEnvironment` と `MujocoSimulationEnvironment` は同じinterfaceで解決される。個別のruntime artifactを必要としないenvironmentでは `gar sim env build/deploy` は何も要求しない。
- AWS認証やSSH接続に失敗した場合の利用者誘導は、environmentではなく `commands/sim.py` の共通recovery経路がTerminal Bridgeへ渡す。

## `gar target` の現在の分離

```text
cli.py
  ↓ workspace名 + GarCommand
commands/target.py
  ├─ BuildEnvironment      target build
  ├─ ArtifactStore         最新TARGET_APP成果物の選択
  └─ TargetEnvironment     ADB・serial・SSH/scpによるdeploy
                              ↓
                        access channels
```

- `gar target build/deploy` はworkspace設定だけを入力とし、接続先の一時上書きは受け取らない。
- `commands/target.py` はbuild・artifact選択・deployの順序と、共通の接続復旧だけを扱う。
- `TargetEnvironment` はworkspaceの実機環境設定から解決され、ADB・SSH/scp・serialの具体的なアクセス手段は `access/` から組み立てる。
- `gar target fetch`、`build-esp32`、`flash-esp32` は標準のbuild/deployとは用途が異なる明示的な補助commandとして残している。

## 責務の依存方向

Codespaces一覧の解析は `access/codespaces.py` に置き、`commands/code.py` と
`artifacts/manifest.py` の両方から利用する。これにより、現在の標準sim/target経路では
`artifacts`・`simulation`・`target` から `commands` への逆向きimportはない。

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

- `environments` はsetup候補のメタデータと依存導入だけを持ち、runtime操作を持たない。
- `commands` または専用の access orchestration 層が接続失敗を分類し、必要な復旧手順を決定する。
- `vscode` はユーザー入力が必要な復旧操作を visible terminal へ渡す実装として使う。
- `simulation` と `artifacts` は command 層に依存せず、入力された設定・provider・成果物を処理する。
