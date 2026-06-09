## Simulation Environment

`gar sim` は dummy device runtime を使って動作確認するモードです。simulation VM の起動・停止、ARM64 test/app binaries と simulation runtime の配置、テスト用の仮想 `/dev/*` の起動・停止・観察を扱います。接続先は `gar setup` で保存した既定 host を使います。別 host を一時的に使う場合だけ `--host <name>` を付けます。

| コマンド | 実行場所 | 目的 | 主な処理 | 備考 |
|---|---|---|---|---|
| `gar sim boot` | Gapless Agent Runtime (venv) | simulation VM を起動 | EC2 `start-instances` 後 running を待機し、public IP を取得して SSH config の `HostName` を更新 | `--no-update-ssh` で SSH config 更新を抑止、`--pull` で `ec2.repo_dir` を `git pull` |
| `gar sim shutdown` | Gapless Agent Runtime (venv) | simulation VM を停止 | EC2 `stop-instances` を送信 | 停止要求のみ。完了待機はしない |
| `gar sim status` | Gapless Agent Runtime (venv) | simulation VM の状態確認 | instance / region / state / public IP を表示 | `--instance-id` / `--region` / `--host` で一時上書き可 |
| `gar sim deploy` | Gapless Agent Runtime (venv) | target app を VM へ転送 | AGP artifact bundle の `deploy.app.files` に従って runtime host へ転送 | 接続先は保存済み host 設定 |
| `gar sim env deploy` | Gapless Agent Runtime (venv) | VM 環境インフラ（CUSE stubs / web-bridge）を配置 | AGP artifact bundle の `deploy.sim_env.files` に従って runtime host へ転送。`~/cuse_*` dest は `/usr/local/sbin/`、`~/web-bridge` dest は `/usr/local/lib/gar/web-bridge/` に配置 | 接続先は保存済み host 設定 |
| `gar sim env start` | Gapless Agent Runtime (venv) | テスト用仮想 `/dev/*` runtime を起動 | `hardware/*.csv` から GPIO line と I2C/SPI dev を読み、`/etc/gar/hardware/`、`/usr/local/sbin/`、`/usr/local/lib/gar/`、systemd unit を更新して runtime を起動。VS Code simulation terminal profile と Hardware Panel 用 port forward も作成 | `/run/gar/` を runtime directory とし、bridge/CUSE socket は `/run/gar/hw_sim.sock`。アプリは起動しない |
| `gar sim env stop` | Gapless Agent Runtime (venv) | 仮想 `/dev/*` runtime を停止 | dummy device runtime、bridge、Hardware Panel 用 port forward を停止 | 旧 `make port-forward-stop` の仕事もここへ移動。アプリ停止は本番と同じ停止手順に寄せる |
| `gar sim env status [--json]` | Gapless Agent Runtime (venv) | simulation services / 仮想 H/W の状態確認 | 通常表示は Hardware Panel 用 port forward と bridge API `/api/state` を表示。`--json` は bridge API の生 JSON を出力 | runtime プロセス確認は `gar sim env diag` |
| `gar sim env diag` | Gapless Agent Runtime (venv) | simulation runtime のざっくり診断 | runtime プロセス、仮想 `/dev/*`、bridge API state を表示 | 初動確認向け |
| `gar sim env diag --json` | Gapless Agent Runtime (venv) | 診断結果を機械可読 JSON で出力 | `{processes, devices, api, ok}` を 1 つの JSON で出力。AI / CI がパースする用 | AI は人間向け整形でなくこちらを使う |
| `gar sim env log` | Gapless Agent Runtime (venv) | simulation runtime ログ確認 | bridge と dummy device runtime のログ末尾を表示 | アプリログは本番と同じ配置・手順で確認 |
| `gar sim gpio plan [--json]` | Gapless Agent Runtime (venv) | GPIO dummy runtime の生成計画を確認 | `hardware/gpio.csv` から gpio-sim chip、line、label、service/script 配置を表示 | リモートには触らない。AI / CI は `--json` |
| `gar sim gpio install` | Gapless Agent Runtime (venv) | GPIO dummy runtime の helper/service を配置 | `/etc/gar/hardware/`、`/usr/local/sbin/gar-gpio-sim-{start,stop}`、`gar-gpio-sim.service` を更新 | full runtime なしで GPIO 層だけ更新 |
| `gar sim gpio start` | Gapless Agent Runtime (venv) | GPIO dummy runtime だけを起動 | `install` 相当を行ってから `gar-gpio-sim.service` を restart | 生の `modprobe` / configfs 操作の代替 |
| `gar sim gpio stop` | Gapless Agent Runtime (venv) | GPIO dummy runtime だけを停止 | `gar-gpio-sim.service` を stop し、bind mount / configfs chip を teardown | |
| `gar sim gpio status [--json]` | Gapless Agent Runtime (venv) | GPIO dummy runtime の状態確認 | service 状態、target `/dev/gpiochip*`、bind mount、configfs chip、gpiochip 一覧を表示 | AI / CI は `--json` |
| `gar sim ui button press LINE [--duration-ms N]` | Gapless Agent Runtime (venv) | 仮想 GPIO ボタンを短押し | bridge API `/api/button/press` を SSH 越しに叩く | `--duration-ms` 既定 150 |
| `gar sim ui button set LINE VALUE` | Gapless Agent Runtime (venv) | 仮想ボタン状態を直接セット | bridge API `/api/button`（0=離す / 1=押す） | |
| `gar sim ui rfid tap UID` | Gapless Agent Runtime (venv) | 仮想 RFID カードを置く | bridge API `/api/rfid/tap` | UID は `04:AB:CD:EF:01:23` 形式 |
| `gar sim ui rfid remove` | Gapless Agent Runtime (venv) | 仮想 RFID カードを外す | bridge API `/api/rfid/remove` | |
| `gar sim ui range set MM` | Gapless Agent Runtime (venv) | 仮想 VL53L0X 距離値をセット | bridge API `/api/range` | 距離はミリメートル |

アプリは `gar sim env start` では起動しません。simulation terminal profile などからログインし、本番と同じ `~/sensor_demo` を実行します。
