# Command Reference

AgentCockpit 周辺で使う `agp` コマンド、Make ターゲット、セットアップスクリプトの早見表です。

## AgentCockpit / WSL Hub

`AgentCockpit` は WSL 側のハブとして、EC2 への接続、デプロイ、シミュレーション操作、Codespaces の見える化を担当します。
`agp setup` は WSL Hub の中心コマンドです。`agp` コマンドは `AgentCockpit (venv)`、つまり AgentCockpit repo の `.venv` 上で実行します。`make start` はそのラッパーとして `.venv/bin/agp setup` を実行します。

| コマンド | 実行場所 | 目的 | 主な処理 | 備考 |
|---|---|---|---|---|
| `make init` | AgentCockpit | AGP CLI と周辺連携を整える | `.venv` を作成し、`.venv/bin/agp` を `scripts/agp` へ symlink。VSCode terminal bridge extension を install し、`.agp/mcp-config.json` を生成 | 初回セットアップ、または extension / MCP 設定更新時 |
| `make start` | AgentCockpit | AGP の環境確認を始める | `.venv/bin/agp setup` を実行し、接続環境 provider と EC2 既定 host を確認・設定 | 日常的な開始入口 |
| `agp setup` | AgentCockpit (venv) | WSL 側依存の検出と導入 | provider を検出し、`gh` / `sshfs` / `ssh` / `adb` / `aws` などの不足を確認・導入。`agp sim` の既定 EC2 host も `.agp/config.json` に保存 | `make start` の実体。venv 未有効時は `.venv/bin/agp setup` |
| `agp setup --ec2-host vibecode-graviton` | AgentCockpit (venv) | 既定 EC2 host を明示設定 | `.agp/config.json` の `ec2.host` を更新 | 対話なしで設定したい場合 |

## Build Artifacts

ビルドそのものは `agp-build-env` の Codespace 内に clone された各 repo で行います。各 repo の入口は原則 `make` と `make clean` だけです。

| コマンド | 実行場所 | 目的 | 主な処理 | 備考 |
|---|---|---|---|---|
| `agp code start [--codespace <name>]` | AgentCockpit (venv) | Codespace build workspace を WSL から見えるようにする | `~/.ssh/codespaces` 更新、`~/.config/codespace-dev/env` 更新、SSHFS mount、VS Code `Codespaces` terminal profile 作成 | `gh codespace list` が 1 件なら `--codespace` 省略可。旧 `tools/setup_codespace_wsl.sh` は互換 wrapper |
| `agp code stop` | AgentCockpit (venv) | Codespace build workspace の WSL 側接続を止める | `agp code start` で張った SSHFS mount を unmount し、VS Code `Codespaces` terminal profile を削除 | `~/.ssh/codespaces` と `~/.config/codespace-dev/env` は再接続用 cache として保持 |
| `make` in `repos/embedded-poc-app` | Codespace / repo 内 | target app の ARM64 成果物を作る | `app/sensor_demo` をビルド | compiler は repo の Makefile 側で既定化 |
| `make clean` in `repos/embedded-poc-app` | Codespace / repo 内 | target app の生成物を消す | `app/sensor_demo` と object files を削除 | |
| `make` in `repos/agp-tools` | Codespace / repo 内 | simulation tools の ARM64 成果物を作る | `cuse_i2c`、`gpio_shim.so`、`spi_shim.so`、test binaries をビルド | `libfuse3-dev:arm64` が必要 |
| `make clean` in `repos/agp-tools` | Codespace / repo 内 | simulation tools の生成物を消す | cuse stubs の build outputs を削除 | |

## EC2 Simulation Runtime

EC2 上に simulation device runtime と ARM64 test/app binaries を配置し、テスト用の仮想 `/dev/*` を起動・停止・観察する `agp` コマンドです。接続先は `agp setup` で保存した `.agp/config.json` の `ec2.host` を使います。別 host を一時的に使う場合だけ `--host <name>` を付けます。

| コマンド | 実行場所 | 目的 | 主な処理 | 備考 |
|---|---|---|---|---|
| `agp sim deploy` | AgentCockpit (venv) | EC2 simulation runtime へ成果物を配置 | test/app binaries（`sensor_demo`、`gpio_led_button`、`vl53l0x_read`）と、simulation device runtime（`web-bridge/`、`cuse_i2c`、現状の `gpio_shim.so` / `spi_shim.so`、将来の fake `/dev/*` runtime）を EC2 へ転送 | 接続先は `.agp/config.json` の `ec2.host` |
| `agp sim start` | AgentCockpit (venv) | EC2 のテスト用仮想 `/dev/*` runtime を起動 | `bridge.py` と dummy device runtime を起動し、テスト用 `/dev/i2c-1` などを用意。VS Code `EC2 Simulation` terminal profile と Hardware Panel 用 port forward も作成 | 旧 `make port-forward` の仕事もここへ移動。アプリは起動しない |
| `agp sim stop` | AgentCockpit (venv) | EC2 の仮想 `/dev/*` runtime を停止 | dummy device runtime、bridge、Hardware Panel 用 port forward を停止 | 旧 `make port-forward-stop` の仕事もここへ移動。アプリ停止は本番と同じ停止手順に寄せる |
| `agp sim status` | AgentCockpit (venv) | EC2 simulation runtime の状態確認 | Hardware Panel 用 port forward の状態と bridge API `/api/state` を表示 | runtime プロセス確認は `agp sim diag` |
| `agp sim diag` | AgentCockpit (venv) | EC2 simulation runtime のざっくり診断 | runtime プロセス、仮想 `/dev/*`、bridge API state を表示 | 初動確認向け |
| `agp sim log` | AgentCockpit (venv) | EC2 runtime ログ確認 | bridge と dummy device runtime のログ末尾を表示 | アプリログは本番と同じ配置・手順で確認 |

アプリは `agp sim start` では起動しません。`EC2 Simulation` terminal profile などからログインし、本番と同じ `start.sh` などを実行します。

## Physical Device Runtime

実機へ配置して動かすための `agp` コマンドです。現時点では成果物の転送だけを扱います。実機上での起動・停止・診断コマンドが増えた場合は、このセクションに追加します。

| コマンド | 実行場所 | 目的 | 主な処理 | 備考 |
|---|---|---|---|---|
| `agp device deploy` | AgentCockpit (venv) | 実機へ成果物を配置 | `sensor_demo` を `adb push` で実機へ転送 | 実機対象の名前は `device` に統一 |

## Virtual Hardware Operations

Virtual Hardware Panel と同じ操作を Make ターゲットから実行します。AI がブラウザ操作をしなくても検証できるようにするための入口です。

| コマンド | 実行場所 | 目的 | 主な処理 | 主な変数 |
|---|---|---|---|---|
| `make panel-button EC2=vibecode-graviton LINE=17` | AgentCockpit | 仮想ボタン押下 | bridge API `/api/button/press` を叩く | `LINE`, `DURATION_MS` |
| `make panel-rfid EC2=vibecode-graviton` | AgentCockpit | 仮想 RFID タップ | bridge API `/api/rfid/tap` を叩く | `UID` |
| `make panel-rfid-remove EC2=vibecode-graviton` | AgentCockpit | 仮想 RFID カード除去 | bridge API `/api/rfid/remove` を叩く | |
| `make panel-range EC2=vibecode-graviton RANGE_MM=300` | AgentCockpit | 仮想距離センサ値変更 | bridge API `/api/range` を叩く | `RANGE_MM` |
| `make sim-test EC2=vibecode-graviton` | AgentCockpit | 代表シナリオの簡易実行 | button、RFID、state、logs を順に実行 | `UID` |
| `make sim-scenario EC2=vibecode-graviton SCENARIO=scenarios/sensor_demo_rfid.json` | AgentCockpit | JSON シナリオ実行 | scenario runner と JSON を EC2 に転送して実行 | `SCENARIO` |

## agp-build-env / Codespace Build VM

`agp-build-env` は Codespaces 用のビルド VM repo です。AgentCockpit 本体ではなく、ビルドに必要な OS パッケージと clone 済み repo を揃える役割です。ここのコマンドは通常ユーザーが実行するものではなく、Codespace 作成後の `postCreateCommand` として自動実行されるレシピです。実際のビルドは上の `Build Artifacts` の通り、各 repo 内で `make` / `make clean` を実行します。

| コマンド | 実行場所 | 目的 | 主な処理 | 備考 |
|---|---|---|---|---|
| `bash scripts/post-create.sh` | Codespace / agp-build-env | Codespace build VM 初期化レシピ | ARM toolchain、`libfuse3-dev:arm64`、git/make 等を install。`repos/agp-tools` と `repos/embedded-poc-app` を clone/update | 通常はユーザーが直接実行しない。`.devcontainer/devcontainer.json` の `postCreateCommand` から自動実行 |

## Typical Flow

```bash
# WSL hub: first setup
cd ~/Yurufuwa/AgentCockpit
make init
make start
# or directly:
agp setup

# WSL hub: after creating/recreating a Codespace
agp code start
# WSL hub: disconnect the Codespace view when needed
agp code stop

# Codespace build VM: postCreateCommand が scripts/post-create.sh を自動実行済み
cd repos/embedded-poc-app && make
cd ../agp-tools && make

# WSL hub: after copying artifacts to WSL
agp sim deploy
agp sim start
# VS Code terminal profile "EC2 Simulation" などからログインし、本番と同じ起動手順を実行
./start.sh
```
