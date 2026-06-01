# Command Reference

AgentCockpit 周辺で使う `agp` コマンド、Make ターゲット、セットアップスクリプトの早見表です。

## AgentCockpit / WSL Hub

`AgentCockpit` は WSL 側のハブとして、runtime host への接続、デプロイ、シミュレーション操作、Codespaces の見える化を担当します。
`agp setup` は WSL Hub の中心コマンドです。`agp` コマンドは `AgentCockpit (venv)`、つまり AgentCockpit repo の `.venv` 上で実行します。`make start` はそのラッパーとして `.venv/bin/agp setup` を実行します。

| コマンド | 実行場所 | 目的 | 主な処理 | 備考 |
|---|---|---|---|---|
| `make init` | AgentCockpit | AGP CLI と周辺連携を整える | `.venv` を作成し、`.venv/bin/agp` を `scripts/agp` へ symlink。VSCode terminal bridge extension を install し、`.agp/mcp-config.json` を生成 | 初回セットアップ、または extension / MCP 設定更新時 |
| `make start` | AgentCockpit | 仮想環境の有効化 | 新しいシェル（サブシェル）を立ち上げ、自動的に venv を有効化する（`poetry shell` と同等の挙動） | 日常的な開始入口 |
| `agp setup` | AgentCockpit (venv) | WSL 側依存の検出と導入 | provider を検出し、`gh` / `sshfs` / `ssh` / `adb` / `aws` などの不足を確認・導入。`agp sim` の既定 host も保存 | 環境構築や設定更新時に手動実行 |
| `agp setup --ec2-host vibecode-graviton` | AgentCockpit (venv) | 既定 host を明示設定 | 保存済み host 設定を更新 | 対話なしで設定したい場合 |

## Build Artifacts

ビルドそのものは `agp-build-env` の Codespace 内に clone された各 repo で行います。ビルドコマンドや生成物は target software ごとに異なるため、ここでは固定の `make` 手順を定義しません。各 target repo の README / build script に従ってください。
各 target project は、ビルド後に AGP artifact bundle を作成します。`agp sim deploy` / `agp native deploy` は bundle 内の `artifact.json` を読み、`deploy.sim.files` または `deploy.native.files` に従って転送します。

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
    "native": {
      "files": [
        { "src": "files/sensor_demo", "dest": "/home/user/sensor_demo", "mode": "0755" }
      ]
    }
  }
}
```

`src` は bundle root からの相対パスです。`native` の `dest` が相対パスの場合は `agp native deploy --dest <dir>` を基準に配置します。`mode` は省略可能です。

| コマンド | 実行場所 | 目的 | 主な処理 | 備考 |
|---|---|---|---|---|
| `agp code start [--codespace <name>]` | AgentCockpit (venv) | Codespace build workspace を WSL から見えるようにする | `~/.ssh/codespaces` 更新、`~/.config/codespace-dev/env` 更新、SSHFS mount、VS Code `Codespaces` terminal profile 作成 | `gh codespace list` が 1 件なら `--codespace` 省略可。旧 `tools/setup_codespace_wsl.sh` は互換 wrapper |
| `agp code stop` | AgentCockpit (venv) | Codespace build workspace の WSL 側接続を止める | `agp code start` で張った SSHFS mount を unmount し、VS Code `Codespaces` terminal profile を削除 | `~/.ssh/codespaces` と `~/.config/codespace-dev/env` は再接続用 cache として保持 |

## Simulation Runtime

`agp sim` は dummy device runtime を使って動作確認するモードです。ARM64 test/app binaries と simulation runtime を runtime host に配置し、テスト用の仮想 `/dev/*` を起動・停止・観察します。接続先は `agp setup` で保存した既定 host を使います。別 host を一時的に使う場合だけ `--host <name>` を付けます。

| コマンド | 実行場所 | 目的 | 主な処理 | 備考 |
|---|---|---|---|---|
| `agp sim deploy` | AgentCockpit (venv) | simulation runtime へ成果物を配置 | AGP artifact bundle の `deploy.sim.files` に従って runtime host へ転送 | 接続先は保存済み host 設定 |
| `agp sim start` | AgentCockpit (venv) | テスト用仮想 `/dev/*` runtime を起動 | `bridge.py` と dummy device runtime を起動し、テスト用 `/dev/i2c-1` などを用意。VS Code simulation terminal profile と Hardware Panel 用 port forward も作成 | 旧 `make port-forward` の仕事もここへ移動。アプリは起動しない |
| `agp sim stop` | AgentCockpit (venv) | 仮想 `/dev/*` runtime を停止 | dummy device runtime、bridge、Hardware Panel 用 port forward を停止 | 旧 `make port-forward-stop` の仕事もここへ移動。アプリ停止は本番と同じ停止手順に寄せる |
| `agp sim status` | AgentCockpit (venv) | simulation runtime の状態確認 | Hardware Panel 用 port forward の状態と bridge API `/api/state` を表示 | runtime プロセス確認は `agp sim diag` |
| `agp sim diag` | AgentCockpit (venv) | simulation runtime のざっくり診断 | runtime プロセス、仮想 `/dev/*`、bridge API state を表示 | 初動確認向け |
| `agp sim log` | AgentCockpit (venv) | simulation runtime ログ確認 | bridge と dummy device runtime のログ末尾を表示 | アプリログは本番と同じ配置・手順で確認 |

アプリは `agp sim start` では起動しません。simulation terminal profile などからログインし、本番と同じ `start.sh` などを実行します。

## Native Runtime

`agp native` は dummy device runtime を使わず、接続先が提供する native I/O / 実デバイスを使って動かすモードです。現時点では成果物の転送だけを扱います。native runtime 上での起動・停止・診断コマンドが増えた場合は、このセクションに追加します。

実機接続は **adb を既定**としています（社内環境で複数 NIC が使えないケースを優先）。ネットワーク越しに到達できる環境向けには、`agp setup` の実機環境カテゴリで `SSH / scp` provider を選択でき、`agp native deploy --host <ssh-host>` が `scp` + `ssh chmod` で artifact を転送します。

| コマンド | 実行場所 | 目的 | 主な処理 | 備考 |
|---|---|---|---|---|
| `agp native deploy` (adb_usb) | AgentCockpit (venv) | native runtime へ成果物を配置 | AGP artifact bundle の `deploy.native.files` に従って `adb push` で接続先へ転送 | `--serial` で device serial 指定 |
| `agp native deploy --host HOST` (ssh_scp) | AgentCockpit (venv) | SSH 経路で native runtime へ成果物を配置 | `scp -F ~/.ssh/config <host>:<dest>` で転送し、必要なら `ssh chmod` を実行 | `agp setup` で device provider に `SSH / scp` を選択した場合に有効 |

## Terminal Bridge

AI と人間が同じ VSCode integrated terminal を共有するための入口です。`agp terminal run` で `.agp/terminal-requests/` に request JSON を作成し、VSCode extension がそれを検知して visible terminal でコマンドを実行します。

| コマンド | 実行場所 | 目的 | 主な処理 | 備考 |
|---|---|---|---|---|
| `agp terminal run -- <command>` | AgentCockpit (venv) | visible terminal で実行要求 | `.agp/terminal-requests/<id>.json` を作成 | sudo 等の人間入力が必要なコマンドを VSCode に handoff |
| `agp terminal gc [--keep-days N] [--dry-run]` | AgentCockpit (venv) | 古い request / status の削除 | `terminal-requests/processed/` と `terminal-status/` の `.json` を `--keep-days`（既定 7）より古いものから削除 | 長期 session で蓄積した request を整理する |

## Virtual Hardware Operations

Virtual Hardware Panel と同じ操作を Make ターゲットから実行します。AI がブラウザ操作をしなくても検証できるようにするための入口です。

| コマンド | 実行場所 | 目的 | 主な処理 | 主な変数 |
|---|---|---|---|---|
| `make panel-button EC2=vibecode-graviton LINE=17` | AgentCockpit | 仮想ボタン押下 | bridge API `/api/button/press` を叩く | `LINE`, `DURATION_MS` |
| `make panel-rfid EC2=vibecode-graviton` | AgentCockpit | 仮想 RFID タップ | bridge API `/api/rfid/tap` を叩く | `UID` |
| `make panel-rfid-remove EC2=vibecode-graviton` | AgentCockpit | 仮想 RFID カード除去 | bridge API `/api/rfid/remove` を叩く | |
| `make panel-range EC2=vibecode-graviton RANGE_MM=300` | AgentCockpit | 仮想距離センサ値変更 | bridge API `/api/range` を叩く | `RANGE_MM` |
| `make sim-test EC2=vibecode-graviton` | AgentCockpit | 代表シナリオの簡易実行 | button、RFID、state、logs を順に実行 | `UID` |
| `make sim-scenario EC2=vibecode-graviton SCENARIO=scenarios/sensor_demo_rfid.json` | AgentCockpit | JSON シナリオ実行 | scenario runner と JSON を runtime host に転送して実行 | `SCENARIO` |

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

# WSL hub: after copying artifacts to WSL
agp sim deploy
agp sim start
# VS Code simulation terminal profile などからログインし、本番と同じ起動手順を実行
./start.sh
```
