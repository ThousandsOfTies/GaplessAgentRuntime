# アーキテクチャ

GARは「操作」「build」「artifact」「実行先」を分離します。

```text
Human / AI
    │ gar ...
    ▼
GAR CLI + workspace config
    ├─ BuildEnvironment ── WSLC / Docker / Codespaces
    │       └─ immutable artifact
    ├─ Simulation ─────── VirtualBox / AWS / Wokwi / MuJoCo
    └─ Physical Target ── SSH / ADB / esptool / UUU
```

## 基本原則

1. Product固有処理はProduct workspaceのhookに置く。
2. Board、OS、toolchain、provisioningは`gar-tools`のTarget Packに置く。
3. build成果物はartifact storeへ保存してからdeployする。
4. machine-localなIP、COM、credentialは`.gar/`やOS設定に置く。
5. deploy先で場当たり的にbuildしない。

## コマンドから実処理まで

```text
commands
  → Gar API
  → build / simulation / target / system
  → environment composition
  → access adapter
  → docker / ssh / aws / virtualbox / uuu / serial
```

CLIはProductやOSごとのshell commandを直接持ちません。`gar config`で選択したenvironmentとTarget manifestからadapterを組み立てます。

通常操作は `gar <code|sim|target> <action> [subject]` に揃えます。
CLIの共通動詞と、backendが提供する機能を区別し、hostやruntimeを指定する必要がある場合だけsubjectを追加します。
Simulationの対象省略build／deployは必要なartifact一式を扱い、内部のSIM_APP／SIM_RUNTIMEは分離を保ちます。
`start` がbuild／deployを暗黙実行することはありません。残りの共通化は[CLI収束 TODO](09_CLI_CONVERGENCE_TODO.md)で追跡します。

## Artifact

用途ごとにsnapshotを分離します。

```text
.gar/artifacts/<workspace-id>/
├─ sim_app/<build-id>/
├─ sim_runtime/<build-id>/
└─ target_app/<build-id>/
```

artifactには配置manifest、provenance、checksum、architecture、Target identityを記録します。`latest.json`は最新snapshotを指します。

`deploy`は最新artifactを使いますが、`build`や`fetch`は自動実行しません。architecture、checksum、Target recipeが一致しない場合は安全側で拒否します。

## Simulation

Linux device simulationではruntimeとhostを分けます。

```text
SimulationEnvironment: ssh_remote
    ├─ Sim Host: virtualbox  (local Ubuntu)
    └─ Sim Host: aws_ec2     (remote Ubuntu)
```

VirtualBoxとAWSは同じLinux runtimeを動かすhost providerの違いです。仮想I/Oの操作と観測はBridgeのJSON APIへ集約します。

## Physical Target

Target lifecycleはcapabilityに応じて構成されます。

```text
prepare → build → preflight → deploy → status / log / diag
```

- SSH Target: recipe、file transfer、application lifecycleを利用
- ESP32: esptoolでfirmwareをflash
- NXP: Windows native UUUでfull imageを書き込み、必要ならCOMで起動確認

すべてのTargetが全actionを持つわけではありません。たとえばUUU Targetはapplication lifecycleではなくfull-image provisioningです。

## Hardware contract

hardware情報は3つに分離します。

| 所有者 | 内容 |
|---|---|
| Product | 必要なdevice、signal、性能条件 |
| Target Pack | Boardが提供するresourceと制約 |
| Binding | Product要件とBoard resourceの割当 |

`gar hw validate`はこの3入力をofflineで検証します。実deviceの存在や配線はpreflight、diag、HILで別に確認します。

## Multi-node system

`gar-system.json`はworkspaceをnodeとして宣言し、実行順とlinkを定義します。GARはbuild、deploy、start、diag、scenarioを順序どおり実行します。

Product protocolや業務ロジックはGARへ入れず、Product側のscenarioとmetricsで検証します。

Repository境界は[リポジトリ配置](08_REPOSITORY_LAYOUT.md)、実環境の役割は[開発環境](03_DEVELOPMENT_ENVIRONMENT.md)を参照してください。
