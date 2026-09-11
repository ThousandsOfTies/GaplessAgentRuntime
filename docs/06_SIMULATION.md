# Simulation

GARは異なるsimulatorを共通のartifact、lifecycle、diagnosticへ接続します。

## 標準フロー

```bash
# VirtualBox／AWSのSim Hostを使う場合
gar sim start host --workspace Local/Product
# Ubuntu hostの初回・依存更新時（非対話sudoが必要）
gar sim prepare --workspace Local/Product

gar sim build --workspace Local/Product
gar sim deploy --workspace Local/Product
gar sim start --workspace Local/Product
gar sim diag --workspace Local/Product --json
```

終了:

```bash
gar sim stop --workspace Local/Product
# VMも停止する場合
gar sim stop host --workspace Local/Product
```

`runtime`は仮想deviceとBridge、`app`はProduct applicationです。両者は別artifactとして管理されます。
`sim build / deploy` はbackendに必要な一式を扱い、Wokwi／MuJoCoではappだけを処理します。
一括deployは必要なsnapshotの存在・checksum・設定architectureを先に検証し、runtime、appの順で配置します。
checksumのない旧形式や、設定済みarchitectureを確認できないartifactは `sim build` で再生成します。
`sim deploy --json` は配置済みartifactと途中失敗の範囲を報告します。部分反映の巻き戻しには未対応です。
配置成功だけでは稼働を保証しません。`start` と `diag` で後続の確認を行います。

部品単位の操作は `gar sim build runtime`、`gar sim build app`、`gar sim deploy app` のように指定します。
`start` はbuild／deployを暗黙実行しません。`stop` の既定動作はruntimeと接続の停止です。
`start / stop / status host` はhost providerを明示的に操作します。
旧 `sim runtime start` などの構文は互換aliasとして利用できます。

## Backend

| SimulationEnvironment | Host | 状態 |
|---|---|---|
| `ssh_remote` | `virtualbox` | Linux runtimeとhost lifecycleを実装 |
| `ssh_remote` | `aws_ec2` | 同じLinux runtimeのremote providerを実装 |
| `wokwi` | local process | Product所有project／firmwareを実行 |
| `mujoco` | local process | Product modelを配置して実行 |
| `local_docker` | Docker | 旧workspace互換 |
| `renode_mcu` | hostless | 選択／導入のみ。runtime未実装 |
| `esp32_qemu_firmware` | hostless | 選択／導入のみ。runtime未実装 |
| `aws_ssm` | AWS | 選択／導入のみ。runtime未実装 |

未実装backendは別backendへ自動fallbackしません。

## Linux device simulation

```text
SIM_RUNTIME + SIM_APP
        │ SSH / SCP
        ▼
Ubuntu Sim Host
    ├─ VirtualBox: local、通常x86_64
    └─ AWS EC2: remote、通常aarch64
```

VirtualBoxとAWSは別のsimulatorではなく、同じ`ssh_remote` runtimeを載せるhost providerです。architectureが変わる場合はruntimeとappを両方buildし直します。不一致artifactのdeployはGARが拒否します。

Linux runtimeは可能な範囲で実機と同じdevice interfaceを提供します。

| I/F | Simulation |
|---|---|
| GPIO | `gpio-sim` → `/dev/gpiochip*` |
| I2C | CUSE → `/dev/i2c-*` |
| SPI | CUSE → `/dev/spidev*` |
| UI／操作 | BridgeのHTTP／WebSocket／JSON |

Applicationへsimulation専用分岐を増やすのではなく、device layerで差を吸収します。

## Bridgeと仮想I/O

BridgeはHuman UI、AI、CIの共通control planeです。

```bash
gar sim io state --workspace Local/Product --json
gar sim io press --workspace Local/Product --device button --line 17
gar sim io set --workspace Local/Product --device range --value 250
gar sim io clear --workspace Local/Product --device rfid
```

複数nodeでは`gar system test`が各nodeのBridgeとmetricsを利用します。
SSH Remote Simulationでは、接続とruntimeをそれぞれ一括操作できます。

```bash
gar system connect --file gar-system.json --port tx=8081 --port rx=8082 --json
gar system start --file gar-system.json
gar system status connections --file gar-system.json --json
gar system test --file gar-system.json --scenario scenarios/e2e.json --json
gar system stop --file gar-system.json
gar system disconnect --file gar-system.json --json
```

`connect / disconnect` は接続だけを操作し、`start / stop` はruntimeを操作します。
connectは全nodeのportを検証し、途中失敗時は今回開始した接続だけを片付けます。
disconnectは同じsystem fileに属し、PID・起動時刻・commandが一致するprocessだけを停止します。
`system test` は同じfileの接続URLを利用します。外部の接続を使う場合は `--bridge NODE=URL` を指定します。
個別の `sim start --panel-port PORT` で作成した接続は、従来どおり同じportの `sim stop` で停止します。

## VirtualBox初回準備

1. Ubuntu VMを作成し、WindowsからSSH可能にする。
2. SSH configへ固定aliasを登録する。
3. `gar config`で`SSH Remote`と`Local Ubuntu (VirtualBox)`を選ぶ。
4. 非対話sudoを利用できる接続で `gar sim prepare --workspace NAME` を実行する。
5. `gpio-sim`と`/sys/kernel/config`を確認する。

prepareは既存の共通Ubuntu bootstrapを使ってhostのpackage・kernel module・configfsを準備します。
Productのbuildやartifactの配置は行いません。

詳細は[VirtualBox README](../infra/virtualbox/README.md)を参照してください。

## 診断順序

まず `gar sim status --json` または `gar sim diag --json` でhost・接続・runtime・appをまとめて確認します。
hostの確認に失敗しても、取得できたruntime／appの結果は残します。
SSH不通時のappは停止と断定せずunknown、app未配置時の空serviceはnot_deployedとして報告します。
Linuxのdiagは従来のdevice・Bridge診断も含みます。対象省略時のappには次のIDを報告します。

| Field | 意味 |
|---|---|
| `expected_build_id` | ローカルの最新SIM_APP snapshotのID |
| `deployed_build_id` | 最後まで配置とchecksum検証が完了したappのID |
| `running_build_id` | GARが起動時に検証し、現在のprocessに結び付けたID |
| `build_id_match` | expectedとrunningがともに既知で一致するか |
| `build_id_verification` | match、mismatch、unknown、stopped |

新しいbuildやdeployだけではrunning IDを更新しません。途中で失敗したdeployも配置完了として記録しません。
ID不明・不一致のappを全体の成功扱いにせず、runtimeのhealth失敗も独立して失敗として報告します。
`diag runtime` は従来のruntime診断を保持します。appまで検証する場合は対象を省略します。

- Linux/systemd: 配置済みファイルを起動の前後に照合し、実processの実行fileまたはentrypointのscript引数も確認します。
  receiptはPID・process起動時刻・systemd InvocationIDへ結び付けます。GAR外での再起動はunknownとなり、
  次の `sim start` で記録し直します。空service、別application、停止、PID再利用は一致としません。
  wrapper経由でentrypointを特定できないscriptはunknownとして報告します。
- Wokwi／MuJoCo: 起動専用の入力コピーを使い、後のdeployが稼働processのfirmware／modelを変更しないようにします。
  processのcommandと起動時刻を確認します。Wokwiではproject内のfirmware設定、MuJoCoでは配置されたmodelを使う必要があります。
  配置範囲外のmodel／runnerや、検証できない旧形式ではIDはunknownです。確認対象は宣言した起動入力であり、
  simulator内部の動作や外部resourceの完全性はscenarioで別途確認します。

入力コピーはprojectに隣接する `.identity/runs` に保持し、既存snapshot同様、停止時には削除しません。
Linuxの配置receiptは `/var/lib/gar/simulation/app-deployed.json`、起動receiptは `/run/gar/app-running.json` です。
どちらもGARが管理します。legacyのhome相対配置は起動互換を維持しますがID検証の対象外です。

1. `gar sim status host`（hostを持つbackend）
2. SSH接続
3. `gar sim diag --json`
4. artifactのarchitecture、checksum、build ID
5. runtime serviceとdevice node
6. Bridge、metrics、application log

確認済み範囲は[検証状態](07_VERIFICATION.md)を参照してください。
