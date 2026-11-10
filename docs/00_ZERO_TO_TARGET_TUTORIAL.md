# 最短チュートリアル

GARは、Productのbuild、simulation、実機deployを同じCLIから操作するための基盤です。
WindowsではWSL Containers（WSLC）をbuildの第一候補にし、USB／COM／UUUはWindowsから直接扱います。
Dockerも代替として選べます。[WSLCの導入・対応範囲](WSLC_BUILD.md)を参照してください。

## 1. GARを準備する

Windows:

```powershell
.\scripts\setup.cmd
.\scripts\gar.cmd config
```

Linux／macOS:

```bash
./scripts/setup
./scripts/gar config
```

`setup`はrepository内の`.venv`とPython依存を準備します。`config`はProduct workspace、Target、build環境、simulation環境、接続先を`.gar/config.json`へ保存します。

設定確認だけ行い、外部toolを導入しない場合:

```bash
gar config --no-install
```

複数workspaceがある場合は、以降のコマンドへ`--workspace NAME`を付けます。

## 2. 実機向けにbuildする

```bash
gar target build --workspace Local/Product
```

GARは選択されたWSLC／Docker／CodespacesでProductの`scripts/product-target-build.sh`を実行し、成果物を`.gar/artifacts/`へ保存します。

LinuxのSSH／SCP Targetでは、初回またはrecipe更新時に準備と事前確認を行います。

```bash
gar target prepare --workspace Local/Product
gar target preflight --workspace Local/Product --json
```

## 3. 実機へdeployする

```bash
gar target deploy --workspace Local/Product
```

SSH／SCP Targetでは、続けて状態を確認します。

```bash
gar target status --workspace Local/Product --json
gar target diag --workspace Local/Product --json
```

NXP UUU Targetの標準フローは`target build` → 対象確認 → `target deploy`です。`deploy`はfull imageを書き込むため、Board、boot mode、USB、書込み先、データ消去の影響を実行前に確認してください。

## 4. Simulationを使う

```bash
# VirtualBox／AWSのSim Hostを使う場合
gar sim start host --workspace Local/Product

gar sim build --workspace Local/Product
gar sim deploy --workspace Local/Product
gar sim start --workspace Local/Product
gar sim diag --workspace Local/Product --json
```

終了:

```bash
gar sim stop --workspace Local/Product
# VirtualBox／AWSのVMも停止する場合
gar sim stop host --workspace Local/Product
```

VirtualBoxとAWSでは同じコマンドを使います。接続先のarchitectureが変わった場合は、runtimeとappを両方buildし直してください。
`sim build / deploy` は必要なartifact一式を扱います。Wokwi／MuJoCoではappだけが対象です。
個別操作は `sim build app`、`sim deploy runtime` のように対象を指定できます。

## 5. 複数nodeをまとめて操作する

`gar-system.json`を持つProductだけが対象です。

```bash
gar system build --file gar-system.json --json
gar system deploy --file gar-system.json --json
gar system start --file gar-system.json --json
gar system test --file gar-system.json --scenario scenarios/e2e.json --json
```

## 覚えておくこと

- `deploy`は`build`や`fetch`を自動実行しません。
- `start`は`build`や`deploy`を自動実行しません。VMの停止は`stop host`で明示します。
- buildはDocker／Codespacesで行い、Sim Hostや実機上で場当たり的にcompileしません。
- `.gar/`はmachine-local stateであり、Gitへcommitしません。
- AI／CIから結果を読む場合は、対応コマンドの`--json`を使います。
- 実装済みと実機確認済みは別です。現在の範囲は[検証状態](07_VERIFICATION.md)を参照してください。

全コマンドは[コマンドリファレンス](01_COMMAND_REFERENCE.md)を参照してください。
