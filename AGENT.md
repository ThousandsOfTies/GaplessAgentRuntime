# Gapless Agent Runtime — Agent Instructions

この文書は、GAR repositoryで作業するAIエージェント向けの運用正本である。
利用手順は`docs/`、背景と将来方針は`info/`を参照し、このファイルへ重複させない。

## 最初に確認すること

1. `git status --short --branch`で既存差分を確認する。
2. 対象がGAR core、gar-tools、Product parent、Product sourceのどれかを確認する。
3. `.gar/config.json`のworkspace、Target、environmentを確認する。
4. 実機操作ならSSH config aliasと対象Boardを読み取り専用で確認する。
5. repository内外の`AGENTS.md`と環境固有指示を読む。

既存差分はユーザーまたは別作業の所有物である。未確認の`pull`、`reset`、`checkout --`、`clean`、
一括stageを行わない。変更は担当fileへ限定する。

この環境でRTK指示が有効な場合、shell commandは`rtk`をprefixする。

## Repository境界

| 変更内容 | 置き場所 |
|---|---|
| CLI、artifact、system、diagnostic、environment composition | GaplessAgentRuntime |
| Board／OS／toolchain／provisioning／simulation provider | gar-tools |
| Product build環境 | gar-build-envまたはProduct workspace |
| Application、protocol、UI、menu、Peripheral利用 | Product source |
| Product requirements、配線、Target binding、Golden scenario | Product workspace／Product repository |

Target PackへProduct名、TX／RX、menu、ILI9341のProduct用途、KY-040の操作意味、Product固有serviceを
追加しない。Target Packは汎用capabilityまで、Productとの割り当てはBindingで行う。

## GARを使う作業とGARを修正する作業

Productのbuild／deploy／診断は既存`gar` commandを使う。手作業でremote hostへfileを置いたり、
serviceを直接編集したりしない。

GAR自体に不足があるときは、最初の事実確認に必要な読み取り専用操作を行い、その後はCLI、
Target recipe、diagnosticへ再利用可能な形で実装する。同じ生操作を二度必要としない設計を目指す。

GAR coreを変更したらrepository rootで`make check`を実行する。

## 環境の役割

| 環境 | 役割 |
|---|---|
| Windows | `gar`操作面、workspace／artifact store、USB／COM／UUU、deploy起点 |
| Local WSL Containers | Windowsで優先するProduct build hook、test、Linux toolの実行 |
| Local Docker | Product build hook、test、Linux toolの実行 |
| Codespaces | reproducible cloud BuildEnvironment |
| VirtualBox Ubuntu | local Sim Host。`gpio_sim`を含むLinux device simulation runtimeの実行 |
| AWS Ubuntu | remote Sim Host。VirtualBoxと同じLinux runtimeのprovider variant |
| Physical Target | 配布済みapplicationとreal deviceの実行 |
| WSL | WSLC buildの基盤。Docker Desktopが内部で利用する場合もGARからはDockerとして扱う |

Sim HostやPhysical Targetで場当たり的にcompileしない。buildは`gar config`で選択した
WSLC／Docker／Codespaces BuildEnvironmentとProduct hookで行う。Windowsの新規build環境は
WSLCを第一候補にし、Dockerを代替として選べるようにする。保存済みの明示選択は保持する。
VirtualBoxとAWSを別simulatorと
扱わず、`ssh_remote`に対するSim Host providerの差としてcomposition境界で吸収する。

## 標準操作

### Configuration

```bash
gar config
```

workspace編集後は、対象workspaceのTarget、BuildEnvironment、SimulationEnvironment、
Sim Host provider、TargetEnvironment、SSH Host／COM設定が保持されたことを確認する。

### Simulation

```bash
gar sim build --workspace Local/Product
gar sim deploy --workspace Local/Product
gar sim start --workspace Local/Product
gar sim diag --workspace Local/Product --json
```

人間向けPanelの目視だけで完了にしない。可能ならBridge API、metrics、scenario、logで機械的に確認する。

### Physical Target

```bash
gar target prepare --workspace Local/Product
gar target build --workspace Local/Product
gar target preflight --workspace Local/Product --json
gar target deploy --workspace Local/Product
gar target diag --workspace Local/Product --json
```

- `prepare`は初回またはrecipe更新時。
- `preflight`は転送前のread-only compatibility検証。
- `deploy`は最新TARGET_APP snapshotだけを使い、buildを暗黙実行しない。
- `diag`でexpected／running build ID、status、healthを確認する。
- 永続envは`gar target configure --app ... --file ...`で明示し、通常deployへ混ぜない。

実機deploy、flash、再起動、電源操作は、ユーザーが対象と操作を依頼した範囲だけで行う。
対象aliasやBoardが曖昧なら書き込み前に停止する。

### Hardware contract

```bash
gar hw validate --workspace Local/Product --json
```

offline validationと実Target probeを混同しない。前者はrequirements／capabilities／binding、
後者は実device、driver、kernel、配線、電源を確認する。

### Multi-node system

```bash
gar system build --file /path/to/gar-system.json --json
gar system deploy --file /path/to/gar-system.json --json
gar system start --file /path/to/gar-system.json --json
gar system test --file /path/to/gar-system.json --scenario /path/to/scenario.json --json
```

Product protocolをGARへ移さない。GARはnode lifecycle、link由来environment、metrics、assertion、
cleanupを担当し、PnPやmedia protocolはProductが所有する。

## Artifactの扱い

- `SIM_APP`、`SIM_RUNTIME`、`TARGET_APP`を区別する。
- build後のsnapshotを変更しない。
- source commit、gar-tools commit、recipe、architecture、ABI、libc、checksumを保持する。
- dirty source／tools、legacy metadata、checksum不一致、Target identity driftを無視しない。
- Targetのrecipe-backed deployはhealthとrunning build ID一致まで確認する。
- Simulation deployは配置結果。続くstart／diagで最新snapshotと起動時receiptのbuild IDを照合し、Productのmetrics・scenarioで稼働を確認する。IDがunknownのケースや実環境未検証の範囲を保証したと報告しない。

## Terminal操作とhost native tool

通常の非対話commandはbackgroundで実行する。次の場合だけ、Agent Terminal Bridgeで
VS Code integrated terminalへ渡す。

- sudo password
- AWS／GitHub等のlogin
- host keyの初回確認
- 人間が入力すべき秘密情報
- vendor toolのGUI／対話操作

```bash
gar terminal run \
  --title "Gapless Agent Runtime" \
  --command "command requiring user input"
```

認証code、password、private keyをchatやlogへ出さない。人間が完了したら元のGAR commandを再実行し、
成功を機械可読結果で確認する。

Windowsでは`gar target deploy`がTarget recipeに従ってhost nativeの`uuu.exe`と
pyserialの`COMn`を使う。ユーザーやagentが`wsl.exe`、`usbipd`、Linux版UUUを都度
呼び分けない。`gar usb` はLinux-only USB toolが必要な旧WSL passthroughの互換経路であり、
Windows native UUU／COMの標準経路では使わない。

## 安全境界

- image flash、disk書き込み、Terraform destroy、instance削除は対象をprobeし、依頼範囲を確認する。
- repository root、home directory、未解決variableをrecursive削除対象にしない。
- USB BUSID、serial port、block deviceを推測して書き込まない。
- UUUのdownload USBとdebug UARTを同一deviceとみなさない。Board、boot mode、image、COM portは人間が確認する。
- Physical Targetへsimulation dummy deviceやPanelをinstallしない。
- application deployでSSH鍵、host key、`/etc/gar/<app>.env`を上書きしない。
- secret、private IP、identity pathを公開artifactやCI reportへ記録しない。

## 完了条件

作業種別に応じて、次を満たす。

| 作業 | 最低限の確認 |
|---|---|
| GAR core変更 | focused test + `make check` + `git diff --check` |
| gar-tools変更 | Target／runtime test + manifest／recipe validation |
| Product変更 | unit test + artifact build +該当environmentでのbehavior確認 |
| Simulation deploy | `diag --json`、metrics／scenario、running build |
| Physical deploy | `preflight --json`、`diag --json`、実device behavior |
| 文書変更 | 実CLI／sourceとの照合、local link、重複と古い参照の確認 |

未実装adapterのexpected error、CIの`skipped`、file転送成功だけを完了と報告しない。
Windows launcher／Docker build／VirtualBox controller／UUU／COMのunit test成功と、
実Windows／Docker Desktop／VirtualBox VM／NXP BoardでのE2E確認を区別する。

## 正本文書

- 操作: [コマンドリファレンス](docs/01_COMMAND_REFERENCE.md)
- 設計: [アーキテクチャ](docs/02_ARCHITECTURE.md)
- 環境: [開発環境](docs/03_DEVELOPMENT_ENVIRONMENT.md)
- Simulation: [シミュレーション](docs/06_SIMULATION.md)
- 現在地: [検証状態](docs/07_VERIFICATION.md)
- 配置: [リポジトリ配置](docs/08_REPOSITORY_LAYOUT.md)
- Target境界: [Target Pack戦略](info/06_TARGET_PACK_STRATEGY.md)
