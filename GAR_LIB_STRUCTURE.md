# `scripts/gar_lib` 構成と責務

この文書は、2026-07-13時点の `scripts/gar_lib` の実ファイルと参照関係を確認してまとめたものです。
理想だけではなく、現在接続されている経路、補助経路、error-only stubとして接続されたsetup選択肢も区別して記載します。

## 用語

- **Workspace**: 1つの製品コードベースと、そのbranch・接続先・選択環境をまとめた実行コンテキスト。
- **BuildEnvironment**: `TARGET_APP`、`SIM_APP`、`SIM_RUNTIME`をどこでbuildするかを表す実行オブジェクト。
- **SimulationEnvironment**: simulation artifactの配置とruntimeのstart / stop / status / diag / logを担当する実行オブジェクト。
- **SimulationHostController**: simulation runtimeを載せるEC2等のhost自体を起動・停止する実行オブジェクト。
- **SimulationHardwareControl**: GPIOやpanelなど、simulation runtimeのhardware control planeを担当する実行オブジェクト。
- **TargetEnvironment**: artifactを物理targetへ配置・書き込みする実行オブジェクト。
- **EnvironmentSetupOption**: `gar setup`に表示する選択肢、依存確認、導入方法だけを持つメタデータ。runtime操作は持たない。
- **TargetManifest**: `gar-tools/targets/*/target.json`から読むboard / target定義。`TargetEnvironment`とは別概念。

設定ファイルには歴史的に `selected_providers` という名前が残っていますが、runtime側では
`Workspace.selected_environments` として扱っています。この文書では、setupのクラスを
「setup選択肢」、実行時に生成されるオブジェクトを「environment」と呼び分けます。

## 現在のファイル構成

各packageの `__init__.py` は省略しています。主にpackage markerまたは一部型のre-exportです。

```text
scripts/gar_lib/
├─ __main__.py                 python -m scripts.gar_lib の入口
├─ cli.py                      全CLI引数定義とtop-level振り分け
├─ cli_tmp.py                  標準sim/target構造だけを示す実行可能な参照CLI
├─ application.py              高水準オブジェクトの協調順序
├─ composition.py              config-backed具体実装の生成と接続
├─ config.py                   .gar/config.jsonの読み書きとworkspace選択
├─ hardware.py                 hardware CSV repositoryとtemplate生成
├─ gar_tools.py                gar-tools探索・取得・TargetManifest読込み
│
├─ core/                       外部I/Oを持たない基本モデル
│  ├─ workspace.py             Workspace
│  ├─ artifact.py              Artifact / ArtifactKind
│  ├─ command.py               GarCommandと標準command定数
│  └─ errors.py                GarDomainError / AccessConnectionError
│
├─ workspaces/                 workspace検索
│  └─ registry.py              WorkspaceRegistry / ConfigWorkspaceRegistry
│
├─ build/                      product buildの実行環境
│  ├─ base.py                  BuildEnvironment protocol
│  ├─ spec.py                  artifact種別からproduct hookを選ぶBuildSpec
│  ├─ local.py                 local product hook実行
│  ├─ codespaces.py            Codespaces上のhook実行とartifact同期
│  └─ resolver.py              workspace設定から具体BuildEnvironmentを選択
│
├─ artifacts/                  artifact bundleの検証・保管・同期
│  ├─ store.py                 ArtifactStore / LocalArtifactStore
│  └─ manifest.py              artifact.json解析とCodespaces artifact取得
│
├─ access/                     接続手段ごとの小さなcapability
│  ├─ base.py                  Command/File/ArtifactInstaller/Console protocol
│  ├─ ssh.py                   SSH command / scp file channel
│  ├─ ssh_config.py            SSH configのHostName更新
│  ├─ adb.py                   ADB shell / file channel
│  ├─ aws.py                   AWS CLI command channelと認証失敗分類
│  ├─ process.py               local background processの起動・停止
│  ├─ serial.py                汎用serial installer / console channel
│  └─ codespaces.py            gh codespace list出力の解析だけを共有
│
├─ simulation/                 simulation domainと具体environment
│  ├─ environment.py           SimulationEnvironment / Resolver protocol
│  ├─ resolver.py              全setup IDから具体SimulationEnvironmentを組立て
│  ├─ linux_systemd.py         Linux/systemd runtimeとartifact配置
│  ├─ linux.py                 Linux runtime command builderとGPIO計画
│  ├─ wokwi.py                 Wokwi runtime・project配置・process管理
│  ├─ mujoco.py                MuJoCo runtimeとHTTP bridge hardware control
│  ├─ pending.py               未実装操作を明示的なdomain errorにする共通stub
│  ├─ renode.py                Renode runtimeのerror-only具体environment
│  ├─ esp32_qemu.py            ESP32 QEMUのerror-only具体environment
│  ├─ aws_ssm.py               AWS SSMのerror-only具体environment
│  ├─ diagnostic.py            構造化diagnostic結果
│  ├─ parse.py                 Linux diagnostic / GPIO出力parser
│  ├─ control.py               hardware control protocolとLinux bridge実装
│  ├─ control_resolver.py      ssh_remote / mujocoのcontrol実装選択
│  ├─ host.py                  SimulationHostController protocolと結果
│  ├─ host_resolver.py         workspaceのEC2設定からhost controllerを生成
│  ├─ aws_ec2.py               AWS EC2 host lifecycle
│  ├─ session.py               SimulationSessionManager protocolとVS Code adapter
│  └─ remote_session.py        SSH port forwardとVS Code terminal profileの実処理
│
├─ target/                     物理target domainと具体environment
│  ├─ environment.py           TargetEnvironment / Resolver protocol
│  ├─ resolver.py              ADB / SSH / ESP32実装の組立て
│  ├─ file_transfer.py         command + file channelによるartifact配置
│  ├─ serial.py                ArtifactInstallerによるserial target
│  ├─ esp32.py                 標準TargetEnvironment用ESP32 installer
│  ├─ esp32_firmware.py        明示的build-esp32とartifact取得の補助経路
│  └─ esptool.py               ESP32 artifact検証とesptool書込み
│
├─ recovery/                   接続失敗から利用者操作への変換
│  ├─ access.py                AccessConnectionErrorからRecoveryActionを生成
│  └─ terminal.py              RecoveryActionをTerminal Bridgeへ渡すadapter
│
├─ environments/               setup用選択肢の発見・依存導入
│  ├─ base.py                  EnvironmentSetupOption / CommandStatus
│  ├─ discovery.py             registry packageの自動走査とcategory付与
│  ├─ install.py               sudo判定とvisible terminalへのhandoff
│  └─ registry/
│     ├─ codespace/
│     │  ├─ local.py           Local Dockerの依存確認・導入
│     │  └─ github_codespaces.py  gh / sshfsの依存確認・導入
│     ├─ simulator/
│     │  ├─ ssh_remote.py      SSH Remoteの依存情報
│     │  ├─ wokwi.py           Wokwi CLIの依存確認・導入
│     │  ├─ mujoco.py          MuJoCo Python packageの依存確認・導入
│     │  ├─ renode_mcu.py      Renode / renode-testの導入
│     │  ├─ esp32_qemu.py      Espressif QEMUの依存情報
│     │  └─ aws_ssm.py         AWS CLI / SSM pluginの導入（runtimeはstub）
│     └─ target/
│        ├─ adb_usb.py         Linux ADBの依存確認・導入
│        ├─ adb_win.py         Windows ADBの検出・設定
│        ├─ ssh_scp.py         SSH / scpの依存情報
│        └─ esp32_esptool.py   esptoolの依存確認・導入
│
├─ commands/                   CLI境界とApplication外の補助command
│  ├─ executor.py              Application実行と共通接続復旧
│  ├─ presentation.py          CommandOutcomeのCLI表示
│  ├─ setup.py                 workspace / target / setup選択肢の対話設定
│  ├─ code.py                  Local / Codespacesのboot・mount・terminal管理
│  ├─ infra.py                 Terraformによるsimulation host作成・破棄
│  ├─ usb.py                   usbipd-winによるWSL USB接続
│  ├─ terminal.py              Terminal Bridge request作成・GC
│  └─ hw.py                    hardware template初期化のCLI adapter
│
└─ vscode/                     VS Code固有I/O
   ├─ terminal_ui.py           ANSI表示とsafe_input
   ├─ profile_manage.py        integrated terminal profileの追加・削除
   └─ terminal_bridge.py       VS Code extensionの検出・導入
```

## 標準Application経路

`gar sim`と`gar target`の標準build / deploy / lifecycleは次の依存方向です。

```text
cli.py
  ↓ GarCommand + workspace selector
commands/executor.py
  ├─ composition.pyで具体オブジェクトを生成
  ├─ application.dispatchを実行
  ├─ presentation.pyでCommandOutcomeを表示
  └─ AccessConnectionErrorをrecoveryへ渡す
          ↓
application.py
  ├─ WorkspaceRegistry
  ├─ BuildEnvironmentResolver
  ├─ ArtifactStore
  ├─ SimulationEnvironmentResolver
  ├─ SimulationHostControllerResolver
  ├─ SimulationHardwareControlResolver
  ├─ SimulationSessionManager
  └─ TargetEnvironmentResolver
          ↓
resolver / concrete environment
          ↓
access channel / external process
```

代表的なシーケンスは `application.py` にそのまま読める形で置いています。

```text
target build:
  Workspace → BuildEnvironment → TARGET_APP Artifact

target deploy:
  Workspace → latest TARGET_APP Artifact → TargetEnvironment.deploy

sim build:
  Workspace → BuildEnvironment → SIM_APP Artifact

sim deploy:
  Workspace → latest SIM_APP Artifact → SimulationEnvironment.deploy

sim env start:
  Workspace → SimulationEnvironment.start → SimulationSessionManager.start

sim host start:
  Workspace → SimulationHostController.start
```

`setup`、`code`、`infra`、`usb`、`terminal`、`hw`、`target fetch`、
`target build-esp32`、`target flash-esp32`は、標準Application経路外の明示的な補助commandです。

## 設定から実行オブジェクトへの対応

| 保存項目 | 読込み先 | 実行時の用途 |
|---|---|---|
| `workspaces[].id/name/branch/connection` | `ConfigWorkspaceRegistry` | Workspaceの識別とlocal / Codespaces / network接続情報 |
| `selected_providers.codespace` | `Workspace.selected_environments["codespace"]` | `ConfigBuildEnvironmentResolver`と`gar code` |
| `selected_providers.simulator` | `Workspace.selected_environments["simulator"]` | simulation runtime / hardware control resolver |
| `selected_providers.target` | `Workspace.selected_environments["target"]` | physical TargetEnvironment resolver |
| `selected_target` | `commands/setup.py` | gar-toolsのTargetManifest選択とsetup表示 |
| `ec2` | Workspace / config helper | simulation host、SSH runtime host、repository更新 |
| `target` / `adb` / `esp32` | Workspace / config helper | physical targetのhost・dest・serial・port |

`selected_target`は現在の `Workspace` modelに含まれず、標準Applicationのresolverは直接参照しません。

## 現在の実装対応表

### BuildEnvironment

| setup ID | 実装 | 備考 |
|---|---:|---|
| `local` | 対応 | workspaceのlocal pathでproduct build hookを実行 |
| `github_codespaces` | 対応 | `gh codespace ssh`でhookを実行しartifactをlocalへ同期 |
| network workspace | 未対応 | workspace登録はできるが、専用のNetworkBuildEnvironmentはない |

### SimulationEnvironment

| setup ID | setup/導入 | runtime | hardware control | 備考 |
|---|---:|---:|---:|---|
| `ssh_remote` | 対応 | 対応 | 対応 | Linux/systemd runtime。EC2の場合もこのIDを使う |
| `wokwi` | 対応 | 対応 | 未対応 | runtimeとartifact配置は実装済み。GPIO/panel resolverはない |
| `mujoco` | 対応 | 対応 | 対応 | local processとHTTP bridgeを使用 |
| `renode_mcu` | 対応 | stub接続 | 未接続 | 具体environmentを生成し、runtime操作時は明示的な未実装エラー |
| `esp32_qemu_firmware` | 依存情報のみ | stub接続 | 未接続 | 具体environmentを生成し、runtime操作時は明示的な未実装エラー |
| `aws_ssm` | 対応 | stub接続 | 未接続 | AWS channelまで組み立てるが、runtime操作は明示的な未実装エラー |

`SimulationHostController`は現在AWS EC2だけです。これは`SimulationEnvironment`とは別軸で、
workspaceの `ec2.host / instance_id / region` から生成されます。

### TargetEnvironment

| setup ID | runtime | 具体実装 |
|---|---:|---|
| `adb_usb` | 対応 | ADB shell + file transfer |
| `adb_win` | 対応 | WSLからWindows `adb.exe`を使用 |
| `ssh_scp` | 対応 | SSH command + scp file transfer |
| `esp32_esptool` | 対応 | SerialTargetEnvironment + Esp32ArtifactInstaller |

## フォルダ境界

| フォルダ | 担当すること | 担当しないこと |
|---|---|---|
| `core/` | 値、意図、domain error | config読込み、subprocess、表示 |
| `workspaces/` | configからWorkspaceを一意に解決 | buildや接続の実行 |
| `build/` | product hookを指定場所で実行 | runtimeへのdeploy |
| `artifacts/` | artifact manifest検証、bundle選択・同期 | simulation/target固有判断 |
| `access/` | SSH、ADB、AWS、process等の単一capability | ユースケース順序、setup UI |
| `simulation/` | simulation runtime / host / controlの契約と実装 | argparse、setup選択画面 |
| `target/` | physical targetへのdeploy/write | setup選択画面 |
| `environments/` | setup候補の発見、依存確認・導入 | runtime commandの実行 |
| `recovery/` | 構造化された接続失敗を利用者操作へ変換 | 実際のSSH/AWS/ADB処理 |
| `commands/` | CLI表示・対話・補助command・Application境界 | 標準sim/targetのdomainシーケンス |
| `vscode/` | VS Code terminal UI/profile/extension I/O | simulationやtargetの判断 |

## 似た名前の区別

| 名前 | 役割 |
|---|---|
| `environments/registry/simulator` | setup画面の選択肢と依存導入。runtime実装ではない |
| `simulation/` | 選択後にApplicationから操作されるruntime / host / control実装 |
| `commands/infra.py` | TerraformでEC2 resourceを作成・破棄するprovisioning |
| `SimulationHostController` | 既に存在するEC2 instanceのstart / stop / status |
| `TargetManifest` / `selected_target` | board・target定義と利用可能backendのsetup情報 |
| `TargetEnvironment` / `selected_providers.target` | artifactを物理targetへ運ぶアクセス方式 |
| `SimulationEnvironment` | simulation runtime本体 |
| `SimulationSessionManager` | runtimeへ入るterminal profileとport forward |
| `target/esp32.py` | 標準TargetEnvironmentへesptoolを適合させるinstaller |
| `target/esp32_firmware.py` | 明示的な旧build-esp32 / artifact取得補助 |
| `target/esptool.py` | artifact検証と実際のflash command |

## 確認できた課題

### 優先度: 高

1. **setup選択肢ごとのruntime成熟度を機械的に判定できない**
   - `renode_mcu`、`esp32_qemu_firmware`、`aws_ssm`も`ConfigSimulationEnvironmentResolver`から固有のerror-only componentとして生成できるようになった。
   - ただしsetup metadataから「実装済み」「stub接続」「非対応」を判定できず、現在は説明文と実装クラスに分散している。
   - setup項目に `runtime_maturity` のような明示的capabilityを持たせ、表示とresolverの対応を検証できるようにする余地がある。

2. **workspaceの接続種別とBuildEnvironment選択が独立しており、矛盾を作れる**
   - `connection.type`は `local / codespaces / network`、build側の設定は `selected_providers.codespace`の `local / github_codespaces`。
   - network workspaceは登録できるがNetworkBuildEnvironmentがなく、localまたはCodespacesを選ぶと必要property取得時に失敗する。
   - simulationの`ssh_remote`も`connection.host`ではなく`workspace.ec2.host`を読むため、「任意のnetwork workspace」と「EC2用SSH設定」の境界が曖昧。
   - Workspace接続とBuildEnvironmentの関係をcomposition時に検証する必要がある。

3. **Terminal Bridge requestの保存実装が二重化している**
   - `commands/terminal.py`はGAR runtime直下の `CONFIG_PATH.parent/terminal-requests`へ保存する。
   - `environments/install.py`は `cwd/.gar/terminal-requests`へ直接保存する。
   - product workspaceからsetupを実行すると別の `.gar` を作る可能性があるため、単一のTerminalRequesterへ統合すべき。

4. **`selected_target`と`selected_providers.target`の関係がruntimeに表現されていない**
   - 前者はboard/TargetManifest、後者はアクセス方式だが、名前が近く利用者・実装者の双方に分かりにくい。
   - `selected_target`はWorkspace modelやApplication resolverへ渡されず、TargetManifestの制約は主にsetup時だけ有効。
   - `TargetDefinition`と`TargetEnvironment`を明示的に別モデルとしてcompositionで結合する余地がある。

5. **product固有のEC2 host既定値がconfig層に残っている**
   - `config.py`の `load_config()` / `default_config()` / `default_ec2_host()`は、未設定時に `DEFAULT_EC2_HOST = "vibecode-graviton"`を返す。
   - 標準Workspace resolverはraw entryを使う一方、setupや補助commandはこのfallbackを使うため、同じ未設定状態の扱いも経路で異なる。
   - 複数workspace構成ではhost未設定を明示的に扱い、setupで入力させる方が一貫する。

### 優先度: 中

6. **Codespacesのアクセス実装が複数層へ分散している**
   - list解析は `access/codespaces.py`、VM/mount操作は `commands/code.py`、buildは `build/codespaces.py`、artifact取得は `artifacts/manifest.py`、ESP32補助取得は `target/esp32_firmware.py`。
   - `gh codespace`実行・認証・timeout・転送をまとめるCodespaces access channel/controllerがない。

7. **ESP32に標準経路と旧補助経路が並存する**
   - 標準経路は `BuildEnvironment.build(TARGET_APP)` → `TargetEnvironment.deploy`。
   - `target/esp32_firmware.py`は `build-esp32`専用で、GarVibeRemoteのpath、PIO env、artifact rootをハードコードしている。
   - 標準product hookで代替できることを確認後、補助commandを縮小または廃止する余地がある。

8. **esptoolの導入先が二重化している**
   - setup選択肢はGARの `.venv`へinstallする。
   - `target/esptool.py`は見つからない場合に `~/.local/share/gar/esptool-venv`を新規作成する。
   - 依存導入をsetupへ集約するか、managed tool environmentを1つに決める必要がある。

9. **session実装が薄い二層になっている**
   - `simulation/session.py`の`VsCodeSimulationSessionManager`は、ほぼそのまま`remote_session.py`のfree functionへ委譲する。
   - protocol境界は有用だが、具体実装を1ファイルにまとめるか、`remote_session.py`をaccess/vscode側へ移すと責務が明確になる。

10. **表示責務がCLI境界へ完全には集約されていない**
    - `commands/presentation.py`が結果表示を担う一方、`HardwareControlResult.render`、Wokwi、MuJoCo、Linux systemd、target/esptool、artifact manifestも直接`print`する。
    - domain結果を構造化してCLI境界で表示する方針をどこまで適用するか決める必要がある。

11. **hardware定義とtemplate生成が同居している**
    - `hardware.py`はApplication用Repository、CSV parser、`gar hw init`用writerを同時に持つ。
    - fallbackも選択TargetManifestではなく固定の `gar-tools/targets/linux-device/hardware`を参照する。
    - repositoryとtemplate initializer、target別hardware sourceの分離余地がある。

### 優先度: 低 / 整理候補

12. **大きなCLI実装が残っている**
    - `cli.py` 約976行、`commands/setup.py` 約1072行、`commands/code.py` 約712行、`simulation/linux.py` 約590行、`commands/usb.py` 約382行。
    - 標準Application経路は分離済みだが、parser定義、setupのworkspace/target/environment設定、Codespaces mount処理、Linux command builderはさらに分割可能。

13. **`cli_tmp.py`の終了条件が曖昧**
    - 正式CLIも既に同じ`application.dispatch`を使っているため、「次期CLI」ではなく構造説明用sampleになっている。
    - documentation sampleとして残すか、テストとともに削除するかを決める必要がある。

14. **package re-exportが未使用かつ一部古い**
    - `core/__init__.py`等のre-exportを内部実装・テストは使っていない。
    - `core/__init__.py`は新しいclean / lifecycle / host command定数をexportしておらず、公開surfaceとして不完全。
    - re-exportを正式APIとして更新するか、単なるpackage markerへ縮小する必要がある。

15. **setup discoveryに不要な明示importが残る**
    - `commands/setup.py`は自動discoveryを使いながら`WokwiEnvironment`を`# noqa: F401`付きで明示importしている。
    - discoveryに必要でないことを確認して削除できる。

## 今後の依存方向

```text
CLI parser / presentation
        ↓
Application use cases
        ↓
domain protocols + composition
        ↓
concrete build / simulation / target implementations
        ↓
access capabilities
        ↓
external systems
```

`environments/registry`はこのruntime依存列とは別に、setup時の選択肢と依存導入だけを
提供します。全setup IDはruntime resolverから具体environmentへ接続されましたが、実装済みか
error-only stubかという成熟度は、今後明示的な登録表またはcapabilityで検証できるようにするのが
次の整理点です。
