# Command Reference

AgentCockpit 周辺で使う `agp` コマンド、Make ターゲット、セットアップスクリプトの早見表です。

## AgentCockpit / WSL Hub

`AgentCockpit` は WSL 側のハブとして、runtime host への接続、デプロイ、シミュレーション操作、Codespaces の見える化を担当します。
`agp setup` は WSL Hub の中心コマンドです。`agp` コマンドは `AgentCockpit (venv)`、つまり AgentCockpit repo の `.venv` 上で実行します。`make start` は venv と bash completion を有効化したサブシェルを開きます。

| コマンド | 実行場所 | 目的 | 主な処理 | 備考 |
|---|---|---|---|---|
| `make init` | AgentCockpit | AGP CLI と周辺連携を整える | `.venv` を作成し、`requirements-agp.txt` から `argcomplete` を導入、`.venv/bin/agp` を `scripts/agp` へ symlink。VSCode terminal bridge extension を install し、`.agp/mcp-config.json` を生成 | 初回セットアップ、または extension / MCP 設定更新時 |
| `make start` | AgentCockpit | 仮想環境の有効化 | 新しいシェル（サブシェル）を立ち上げ、自動的に venv と bash completion を有効化する（`poetry shell` と同等の挙動） | 日常的な開始入口 |
| `agp completion bash` | AgentCockpit (venv) | bash completion script を出力 | `argcomplete` の `register-python-argcomplete agp` を優先し、未導入時は argparse parser から候補を拾う fallback を登録 | 通常は `make start` が自動で読み込む |
| `agp setup` | AgentCockpit (venv) | WSL 側依存の検出と導入 | provider を検出し、`gh` / `sshfs` / `ssh` / `adb` / `aws` などの不足を確認・導入。`agp sim` の既定 host も保存 | 環境構築や設定更新時に手動実行 |
| `agp setup --ec2-host vibecode-graviton` | AgentCockpit (venv) | 既定 host を明示設定 | 保存済み host 設定を更新 | 対話なしで設定したい場合 |
| `agp hw init` | AgentCockpit (venv) | 空の hardware 定義 CSV を作成 | `hardware/{components,gpio,i2c,spi,connections}.csv` をヘッダだけで作成 | 既存ファイルは `--force` なしでは上書きしない |

## Build Artifacts

ビルドそのものは `agp-build-env` の Codespace 内に clone された各 repo で行います。ビルドコマンドや生成物は target software ごとに異なるため、ここでは固定の `make` 手順を定義しません。各 target repo の README / build script に従ってください。
各 target project は、ビルド後に AGP artifact bundle を作成します。`agp sim env deploy` / `agp target deploy` は bundle 内の `artifact.json` を読み、`deploy.sim.files` または `deploy.target.files` に従って転送します。

最小例:

```json
{
  "name": "sensor-demo",
  "deploy": {
    "sim": {
      "files": [
        { "src": "files/sensor_demo", "dest": "~/sensor_demo", "mode": "0755" },
        { "src": "files/web-bridge", "dest": "~/web-bridge" }
      ]
    },
    "target": {
      "files": [
        { "src": "files/sensor_demo", "dest": "/home/user/sensor_demo", "mode": "0755" }
      ]
    }
  }
}
```

`src` は bundle root からの相対パスです。`target` の `dest` が相対パスの場合は `agp target deploy --dest <dir>` を基準に配置します。`mode` は省略可能です。

| コマンド | 実行場所 | 目的 | 主な処理 | 備考 |
|---|---|---|---|---|
| `agp code start [--codespace <name>]` | AgentCockpit (venv) | Codespace build workspace を WSL から見えるようにする | `~/.ssh/codespaces` 更新、`~/.config/codespace-dev/env` 更新、SSHFS mount、VS Code `Codespaces` terminal profile 作成 | `gh codespace list` が 1 件なら `--codespace` 省略可。旧 `tools/setup_codespace_wsl.sh` は互換 wrapper |
| `agp code stop` | AgentCockpit (venv) | Codespace build workspace の WSL 側接続を止める | `agp code start` で張った SSHFS mount を unmount し、VS Code `Codespaces` terminal profile を削除 | `~/.ssh/codespaces` と `~/.config/codespace-dev/env` は再接続用 cache として保持 |

## Simulation Environment

`agp sim` は dummy device runtime を使って動作確認するモードです。simulation VM の起動・停止、ARM64 test/app binaries と simulation runtime の配置、テスト用の仮想 `/dev/*` の起動・停止・観察を扱います。接続先は `agp setup` で保存した既定 host を使います。別 host を一時的に使う場合だけ `--host <name>` を付けます。

| コマンド | 実行場所 | 目的 | 主な処理 | 備考 |
|---|---|---|---|---|
| `agp sim boot` | AgentCockpit (venv) | simulation VM を起動 | EC2 `start-instances` 後 running を待機し、public IP を取得して SSH config の `HostName` を更新 | `--no-update-ssh` で SSH config 更新を抑止、`--pull` で `ec2.repo_dir` を `git pull` |
| `agp sim shutdown` | AgentCockpit (venv) | simulation VM を停止 | EC2 `stop-instances` を送信 | 停止要求のみ。完了待機はしない |
| `agp sim status` | AgentCockpit (venv) | simulation VM の状態確認 | instance / region / state / public IP を表示 | `--instance-id` / `--region` / `--host` で一時上書き可 |
| `agp sim env deploy` | AgentCockpit (venv) | simulation runtime へ成果物を配置 | AGP artifact bundle の `deploy.sim.files` に従って runtime host へ転送。旧 `~/cuse_*` / `~/web-bridge` dest は `/usr/local/sbin/` / `/usr/local/lib/agentcockpit/web-bridge/` に配置 | 接続先は保存済み host 設定 |
| `agp sim env start` | AgentCockpit (venv) | テスト用仮想 `/dev/*` runtime を起動 | `hardware/*.csv` から GPIO line と I2C/SPI dev を読み、`/etc/agentcockpit/hardware/`、`/usr/local/sbin/`、`/usr/local/lib/agentcockpit/`、systemd unit を更新して runtime を起動。VS Code simulation terminal profile と Hardware Panel 用 port forward も作成 | `/run/agentcockpit/` を runtime directory とし、bridge/CUSE socket は `/run/agentcockpit/hw_sim.sock`。アプリは起動しない |
| `agp sim env stop` | AgentCockpit (venv) | 仮想 `/dev/*` runtime を停止 | dummy device runtime、bridge、Hardware Panel 用 port forward を停止 | 旧 `make port-forward-stop` の仕事もここへ移動。アプリ停止は本番と同じ停止手順に寄せる |
| `agp sim env status [--json]` | AgentCockpit (venv) | simulation services / 仮想 H/W の状態確認 | 通常表示は Hardware Panel 用 port forward と bridge API `/api/state` を表示。`--json` は bridge API の生 JSON を出力 | runtime プロセス確認は `agp sim env diag` |
| `agp sim env diag` | AgentCockpit (venv) | simulation runtime のざっくり診断 | runtime プロセス、仮想 `/dev/*`、bridge API state を表示 | 初動確認向け |
| `agp sim env diag --json` | AgentCockpit (venv) | 診断結果を機械可読 JSON で出力 | `{processes, devices, api, ok}` を 1 つの JSON で出力。AI / CI がパースする用 | AI は人間向け整形でなくこちらを使う |
| `agp sim env log` | AgentCockpit (venv) | simulation runtime ログ確認 | bridge と dummy device runtime のログ末尾を表示 | アプリログは本番と同じ配置・手順で確認 |
| `agp sim gpio plan [--json]` | AgentCockpit (venv) | GPIO dummy runtime の生成計画を確認 | `hardware/gpio.csv` から gpio-sim chip、line、label、service/script 配置を表示 | リモートには触らない。AI / CI は `--json` |
| `agp sim gpio install` | AgentCockpit (venv) | GPIO dummy runtime の helper/service を配置 | `/etc/agentcockpit/hardware/`、`/usr/local/sbin/agp-gpio-sim-{start,stop}`、`agp-gpio-sim.service` を更新 | full runtime なしで GPIO 層だけ更新 |
| `agp sim gpio start` | AgentCockpit (venv) | GPIO dummy runtime だけを起動 | `install` 相当を行ってから `agp-gpio-sim.service` を restart | 生の `modprobe` / configfs 操作の代替 |
| `agp sim gpio stop` | AgentCockpit (venv) | GPIO dummy runtime だけを停止 | `agp-gpio-sim.service` を stop し、bind mount / configfs chip を teardown | |
| `agp sim gpio status [--json]` | AgentCockpit (venv) | GPIO dummy runtime の状態確認 | service 状態、target `/dev/gpiochip*`、bind mount、configfs chip、gpiochip 一覧を表示 | AI / CI は `--json` |
| `agp sim ui button press LINE [--duration-ms N]` | AgentCockpit (venv) | 仮想 GPIO ボタンを短押し | bridge API `/api/button/press` を SSH 越しに叩く | `--duration-ms` 既定 150 |
| `agp sim ui button set LINE VALUE` | AgentCockpit (venv) | 仮想ボタン状態を直接セット | bridge API `/api/button`（0=離す / 1=押す） | |
| `agp sim ui rfid tap UID` | AgentCockpit (venv) | 仮想 RFID カードを置く | bridge API `/api/rfid/tap` | UID は `04:AB:CD:EF:01:23` 形式 |
| `agp sim ui rfid remove` | AgentCockpit (venv) | 仮想 RFID カードを外す | bridge API `/api/rfid/remove` | |
| `agp sim ui range set MM` | AgentCockpit (venv) | 仮想 VL53L0X 距離値をセット | bridge API `/api/range` | 距離はミリメートル |

アプリは `agp sim env start` では起動しません。simulation terminal profile などからログインし、本番と同じ `~/sensor_demo` を実行します。

## Hardware Definition

`agp hw` は、Excel のアサイン表に相当する hardware assignment CSV を扱う入口です。CSV は AgentCockpit 固有の設定でも、製品アプリ固有の設定でもなく、GPIO / I2C / SPI / 部品 / 接続の正本データとして扱います。

現時点の PoC では `AgentCockpit/hardware/` を置き場にします。これは実装を小さく始めるための暫定配置です。最終的には hardware assignment CSV を別 repo に分離し、AgentCockpit と製品プロセスがそれぞれ同じ CSV を読み、自分の実行形式へ変換する形にします。

想定する変換先:

| 読み手 | CSV から生成・解釈するもの |
|---|---|
| AgentCockpit / simulation runtime | `gpio-sim` line 定義、bridge 設定、CUSE I2C/SPI device table、systemd runtime 設定、配線 docs |
| 製品プロセス | `app_config.h`、`device_map.c`、board config JSON、テスト fixture |

アプリ実装上の変数名と CSV の `name` は強く結びつけません。結合点は GPIO line、I2C bus/address、SPI device/chip select などの物理・OS インターフェースに寄せます。

現時点では CSV テンプレート作成に加え、`agp sim env start` / `agp sim env diag` が GPIO line、I2C dev、SPI dev をこのCSVから読みます。後続で validate / docs 生成 / runtime 反映範囲を広げます。

| コマンド | 実行場所 | 目的 | 主な処理 | 備考 |
|---|---|---|---|---|
| `agp hw init` | AgentCockpit (venv) | 空の hardware 定義 CSV を作成 | `hardware/` に `components.csv`, `gpio.csv`, `i2c.csv`, `spi.csv`, `connections.csv` を作成 | `--dir`, `--force` |

## Target Runtime

`agp target` は dummy device runtime を使わず、接続先が提供する I/O / 実デバイスを使って動かすモードです。旧 Windows PowerShell RasPi helper 相当の「Codespace から成果物取得 → 実機 push」は `agp target sync` に収容しています。

実機接続は **adb を既定**としています（社内環境で複数 NIC が使えないケースを優先）。adb provider では deploy 前に `adb devices` を確認し、実機が見えない場合は `agp usb attach` 相当を自動で先行実行します。ネットワーク越しに到達できる環境向けには、`agp setup` の実機環境カテゴリで `SSH / scp` provider を選択でき、`agp target deploy --host <ssh-host>` が `scp` + `ssh chmod` で artifact を転送します。

| コマンド | 実行場所 | 目的 | 主な処理 | 備考 |
|---|---|---|---|---|
| `agp target fetch` | AgentCockpit (venv) | Codespace の artifact bundle を WSL hub へ取得 | `gh codespace cp` で `artifact.json` と manifest 記載の `deploy.*.files[].src` を取得 | 既定 remote root は `/workspaces/agp-build-env/artifacts/from-codespace`。`--codespace` / `--remote-root` / `--artifacts-dir` 指定可 |
| `agp target sync` (adb_usb) | AgentCockpit (venv) | Codespace 取得から target runtime 配置まで一発実行 | `agp target fetch` 相当の取得後、`deploy.target.files` に従って `adb push` | `--serial` で device serial 指定。実機未検出時は `agp usb attach` 相当を自動実行 |
| `agp target sync --host HOST` (ssh_scp) | AgentCockpit (venv) | Codespace 取得から SSH 経路の target 配置まで一発実行 | 取得後に `scp -F ~/.ssh/config <host>:<dest>` で転送し、必要なら `ssh chmod` を実行 | `agp setup` で device provider に `SSH / scp` を選択した場合に有効 |
| `agp target deploy` (adb_usb) | AgentCockpit (venv) | target runtime へ成果物を配置 | AGP artifact bundle の `deploy.target.files` に従って `adb push` で接続先へ転送 | `--serial` で device serial 指定。実機未検出時は `agp usb attach` 相当を自動実行 |
| `agp target deploy --host HOST` (ssh_scp) | AgentCockpit (venv) | SSH 経路で target runtime へ成果物を配置 | `scp -F ~/.ssh/config <host>:<dest>` で転送し、必要なら `ssh chmod` を実行 | `agp setup` で device provider に `SSH / scp` を選択した場合に有効 |

## USB-C Passthrough

`agp usb` は USB-C 実機（ADB）を Windows の `usbipd-win` 経由で WSL2 に attach するモードです。WSL2 から Windows interop で `usbipd.exe` を呼び出します。busid は自動検出し、一度確定したものは `.agp/config.json` の `usb.busid` に記憶するので、2 回目以降は `agp usb attach` だけで済みます。

事前に **一度だけ** Windows の管理者 PowerShell で対象デバイスを共有します（再起動後も保持）。busid は `agp usb list` で確認できます。

```powershell
usbipd bind --busid <busid>
```

| コマンド | 実行場所 | 目的 | 主な処理 | 備考 |
|---|---|---|---|---|
| `agp usb list` | AgentCockpit (venv) | 接続中の USB デバイス一覧 | `usbipd.exe list` の Connected を表示 | busid / VID:PID / state を確認 |
| `agp usb attach` | AgentCockpit (venv) | 実機を WSL2 に attach | busid を自動検出し `usbipd.exe attach --wsl` を実行。attach 済み busid を記憶 | `--busid` で明示指定、`--no-remember` で記憶しない |
| `agp usb detach` | AgentCockpit (venv) | attach を解除 | `usbipd.exe detach` を実行 | |
| `agp usb status` | AgentCockpit (venv) | attach 状態を確認 | 対象デバイスの state を表示 | attach 済みなら exit 0 |

未 share（`Not shared`）のデバイスには `usbipd bind` の案内を表示します。通常は `agp target deploy` / `agp target sync` が必要時に attach を試すため、手動の `agp usb attach` は接続状態を明示的に整えたい場合だけ使います。

## Terminal Bridge

AI と人間が同じ VSCode integrated terminal を共有するための入口です。`agp terminal run` で `.agp/terminal-requests/` に request JSON を作成し、VSCode extension がそれを検知して visible terminal でコマンドを実行します。

| コマンド | 実行場所 | 目的 | 主な処理 | 備考 |
|---|---|---|---|---|
| `agp terminal run -- <command>` | AgentCockpit (venv) | visible terminal で実行要求 | `.agp/terminal-requests/<id>.json` を作成 | sudo 等の人間入力が必要なコマンドを VSCode に handoff |
| `agp terminal gc [--keep-days N] [--dry-run]` | AgentCockpit (venv) | 古い request / status の削除 | `terminal-requests/processed/` と `terminal-status/` の `.json` を `--keep-days`（既定 7）より古いものから削除 | 長期 session で蓄積した request を整理する |

## Virtual Hardware Operations

仮想パネル（ボタン / RFID / 距離センサ）の操作は `agp sim ui ...` に統一されています。仮想 H/W 状態の確認は `agp sim env status --json` を使います。AI がブラウザ操作をしなくても検証できる入口です。

| コマンド | 実行場所 | 目的 | 主な処理 | 主な変数 |
|---|---|---|---|---|
| `agp sim ui button press 17` | AgentCockpit (venv) | Button17 を短押し | bridge API 経由で gpio-sim input を更新 | `--duration-ms` |
| `agp sim ui rfid tap 04:AB:CD:EF:01:23` | AgentCockpit (venv) | RFID カードを置く | bridge API 経由で cuse_spi へ UID を反映 | UID |
| `agp sim env status --json` | AgentCockpit (venv) | 仮想 H/W 状態確認 | bridge API state を取得 | `--json` |

## agp-build-env / Codespace Build VM

`agp-build-env` は Codespaces 用のビルド VM repo です。AgentCockpit 本体ではなく、ビルドに必要な OS パッケージと clone 済み repo を揃える役割です。ここのコマンドは通常ユーザーが実行するものではなく、Codespace 作成後の `postCreateCommand` として自動実行されるレシピです。実際のビルドは target software ごとの手順に従います。

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
# target software ごとの README / build script に従ってビルド

# WSL hub: target runtime は fetch + deploy を一発実行
agp target sync

# WSL hub: simulation runtime は artifact bundle を EC2 へ配置
agp sim boot
agp sim env deploy
agp sim env start
# VS Code simulation terminal profile などからログインし、本番と同じ起動手順を実行
~/sensor_demo
```
