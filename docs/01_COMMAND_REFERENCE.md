# コマンドリファレンス

`gar` コマンド一覧。WSL の venv 上で実行する（`make start` で有効化）。
設計背景は [02_ARCHITECTURE.md](02_ARCHITECTURE.md)、シミュレーション詳細は
[06_SIMULATION.md](06_SIMULATION.md) を参照。

---

## 0. 初期セットアップ

| コマンド | 内容 |
|---|---|
| `make init` | `.venv` 作成・`gar` symlink・VSCode extension install |
| `make start` | venv + bash completion を有効化したサブシェルを開く |
| `gar setup` | target 選択・gar-tools 確認/取得・依存 target graph と接続設定の保存・依存コマンド確認・既定 host 保存。local product workspace は複数登録でき、対話画面で追加/削除します |
| `gar hw init` | `gar-tools` の target テンプレートから `hardware/` に CSV を生成 |

### Workspace ごとの設定

`GaplessAgentRuntime/.gar/config.json` は `workspaces` 配列を正本とします。
target、provider、EC2 接続先は各 workspace 要素に保存され、別アプリの設定と混ざりません。

```json
{
  "workspaces": [
    {
      "id": "ws_42f8c1",
      "name": "Local/GarStreamRx",
      "connection": {
        "type": "local",
        "path": "/home/user/Yurufuwa/GarStreamRx"
      },
      "branch": "main",
      "selected_providers": {"codespace": "local", "simulator": "ssh_remote"},
      "selected_target": "linux-device",
      "ec2": {
        "host": "vibecode-graviton",
        "identity_file": "~/.ssh/vibecode-graviton.pem"
      }
    }
  ]
}
```

`id` は GAR が自動生成する内部用の不変 ID で、ユーザーが入力する必要はありません。
`name` は自動生成された workspace名で、既定値は `Local/<product-branch>`、
`Codespaces/<product-branch>`、`Network/<product-branch>` です。`main` branch の場合は
workspace directory 名を使います。setup の修正画面で変更できます。`gar setup` の
一覧に表示され、`--workspace NAME` で指定する識別子でもあります。connection は
`local`、`codespaces`、`network` のいずれかです。複数 workspace がある場合、product
workspace 内で `gar` を実行するとその path の設定が選ばれます。GAR root から Wokwi build を実行する場合は、
`gar sim build --workspace NAME` を指定してください。登録が1件だけなら指定は不要です。

`gar setup` の workspace 追加では接続種別を選びます。Codespaces は Codespace 名と
その中の path、network は IP address または SSH host と remote path を入力します。
Git remote と branch は接続先から自動検出し、検出できない場合だけ branch を確認します。

---

## 1. ビルド環境 管理

| コマンド | 内容 |
|---|---|
| `gar code boot` | Codespace VM を起動し、必要なら接続準備を行う |
| `gar code start` | Codespace を sshfs マウント・terminal profile を追加 |
| `gar code stop` | マウント解除・profile 削除 |
| `gar code shutdown` | Codespace VM を停止 |
| `gar code status` | Codespace VM / 接続状態を確認 |

---

## 2. シミュレーション (`gar sim`)

物理ハードウェアエミュレータ（AWS EC2上の互換ランタイム、またはWokwiなどのローカル/クラウドエミュレータ）を用いた動作検証コマンドです。詳細は [06_SIMULATION.md](06_SIMULATION.md) を参照。

### 2.1. レイヤー（接頭辞）の概念
シミュレーションコマンドは、操作対象となるレイヤーごとに接頭辞が分かれています。

| 接頭辞 | レイヤー | 操作対象 | 日常的な役割 |
|---|---|---|---|
| `gar sim` | **ホスト** | EC2等のシミュレーションホストOS | シミュレーション用のVMやホストの起動・停止・接続状態の管理 |
| `gar sim env` | **環境 (Runtime)** | 仮想デバイス（I2C, SPI, GPIO）のスタブ | 仮想デバイスのエミュレータ（CUSEスタブやブリッジ等）のビルド・起動・ログ監視・個別デバッグ |
| `gar sim` (build/deploy) | **アプリ** | アプリケーション成果物 | 検証したいアプリケーション本体（`sensor_demo`など）のビルドと環境への反映 |
| `gar sim infra` | **インフラ** | AWS等インフラ設備 (Terraform) | テスト用インスタンス自体の作成・破棄（開発初期のみ実行） |

---

### 2.2. ユースケース別基本フロー

#### A. 初めてシミュレーション環境を構築するとき / 完全に初期化するとき
ホストVMを起動し、仮想デバイス環境（Runtime）をビルドして起動するまでの手順です。

```bash
# 1. ホストVMの起動とSSH接続設定の更新
gar sim start --pull

# 2. 仮想デバイスドライバ（スタブ）のビルド・デプロイ・起動
gar sim env build
gar sim env deploy
gar sim env start

# 3. アプリケーションのビルドとデプロイ
gar sim build
gar sim deploy

# 4. シミュレーション環境全体の正常性診断（JSON出力で確認）
gar sim env diag --json
```

#### B. アプリのコードを修正し、再テストするとき (日常開発)
仮想デバイス環境（Runtime）は起動したまま、アプリケーションのみを再デプロイして検証します。

```bash
# アプリケーションをビルドしてホストへ再配置
gar sim build
gar sim deploy
```
> [!NOTE]
> アプリケーションは `gar sim env start` の時点では自動起動しません。シミュレーションホストにログイン、またはテスト用プロセス起動コマンド等を通じて手動で起動します。

#### C. シミュレーションを終了するとき
リソースを無駄にしないよう、仮想環境とホストVMを停止します。

```bash
# 1. 仮想デバイス環境の停止
gar sim env stop

# 2. ホストVMの停止
gar sim stop
```

---

### 2.3. コマンド一覧

#### ホスト管理 (`gar sim`)
| コマンド | 内容 |
|---|---|
| `gar sim start [--pull]` | シミュレーションホストを起動し、SSH接続設定を更新（`--pull` で最新の `gar-tools` 等を git pull） |
| `gar sim stop` | シミュレーションホストを停止（インスタンスは削除されず、課金が抑えられます） |
| `gar sim status` | ホストの現在の実行状態を表示 |
| `gar sim <start/stop/status> --workspace NAME` | 指定 workspace に保存された EC2 設定を使う |

#### 仮想デバイス環境管理 (`gar sim env`)
| コマンド | 内容 |
|---|---|
| `gar sim env build` | 仮想デバイススタブ（CUSE I2C/SPI など）のバイナリをビルド |
| `gar sim env build --workspace NAME` | Wokwi など複数登録した workspace のうち、登録名でビルド対象を指定 |
| `gar sim env deploy` | ビルドしたスタブや接続用Webブリッジをホストへ転送・配置 |
| `gar sim env deploy --workspace NAME` | 指定 workspace の `deploy.sim_env` artifact bundle を転送・配置 |
| `gar sim env start` | 仮想環境（systemd サービス群）とポートフォワードを起動 |
| `gar sim env stop` | 仮想環境（systemd サービス群）を停止 |
| `gar sim env status [--json]` | 各サービスの状態やポートフォワードの接続状態を表示 |
| `gar sim env diag [--json]` | プロセス、仮想デバイス、APIの動作状況をまとめて診断（AIエージェントの診断時は `--json` 推奨） |
| `gar sim env log` | 仮想環境の主要ログ（ブリッジやドライバ等）を表示 |
| `gar sim env gpio-sim-check [--json]` | `gpio-sim` カーネルモジュールの状態確認 |
| `gar sim env gpio <plan/install/start/stop/status>` | GPIO dummy runtime (`gpio-sim`) の個別設定・デバッグ管理 |

#### アプリケーション配置 (`gar sim`)
| コマンド | 内容 |
|---|---|
| `gar sim build` | シミュレーション用のアプリケーション成果物をビルド (※現在は移行中のため、一部ターゲットは Makefile を経由) |
| `gar sim build --workspace NAME` | `gar setup` 一覧の workspace名でビルド対象を指定 |
| `gar sim build clean [--workspace NAME]` | 選択した product workspace の simulation build artifact を削除 |
| `gar sim deploy` | 最新のアプリケーション成果物をシミュレーションホストの実行可能パスへ反映 |
| `gar sim deploy --workspace NAME` | 指定 workspace の `deploy.app` artifact bundle を反映 |

#### インフラ管理 (`gar sim infra`)
| コマンド | 内容 |
|---|---|
| `gar sim infra setup` | 現在のシミュレーションホスト設定値を表示し、Terraform による作成計画を確認 |
| `gar sim infra apply` | インフラを実際に適用してインスタンスを作成し、`.gar/config.json` と SSH config を更新 |
| `gar sim infra destroy` | インスタンスを完全に破棄 |

---

## 3. 実機 build / deploy

| コマンド | 内容 |
|---|---|
| `gar target build` | setup 済み target の実機用 artifact を最新化（現在は ESP32/M5Stack firmware build 経路に委譲） |
| `gar target deploy` | `target.artifact` と `target.access` を解決し、最新 artifact を実機へ反映（target graph 化中） |

低レベルコマンド:

| コマンド | 内容 |
|---|---|
| `gar target fetch` | Codespace から WSL へ成果物取得（artifact node の内部処理） |
| `gar target build-esp32` | ESP32/M5Stack firmware を Codespaces でビルドし、artifact を WSL へ取得 |
| `gar target flash-esp32` | ESP32/M5Stack firmware artifact を esptool で実機へ書き込み |

adb 実機が未検出の場合、`gar target deploy` が自動的に `gar usb attach` を先行実行する。

日常操作:

```bash
gar target deploy
```

ESP32 / USB serial の低レベル確認やトラブルシュートは
[03_DEVELOPMENT_ENVIRONMENT.md](03_DEVELOPMENT_ENVIRONMENT.md) を参照。

---

## 4. USB 接続（WSL2 usbipd-win passthrough）

WSL2 から Windows 側の `usbipd-win` を呼び、USB serial / adb デバイスを
`/dev/ttyACM*` や `/dev/ttyUSB*` として WSL2 に接続するための補助コマンド。
Windows 側に `usbipd-win` が必要。

初回 bind は Host OS 側の管理者権限が必要になることがある。その場合は
Windows 管理者 PowerShell で一度だけ実行する。

```powershell
usbipd bind --busid <busid>
```

| コマンド | 内容 |
|---|---|
| `gar usb bind --match CH9102` | USB デバイスを usbipd-win に share 登録 |
| `gar usb attach` | USB-C デバイスを usbipd-win 経由で WSL2 に attach |
| `gar usb detach` | detach |
| `gar usb status` | 接続状態確認 |
| `gar usb list` | 接続可能デバイス一覧 |

adb 実機は Windows 側 `adb.exe` を直接使う provider もあり、その場合は `usbipd-win`
不要。USB serial flash など WSL2 の device node が必要な経路では `gar usb` を使う。

---

## 補助

| コマンド | 内容 |
|---|---|
| `gar terminal run -- <cmd>` | VSCode integrated terminal でコマンドを実行（sudo 等の人間入力が必要な場合） |
| `gar terminal gc` | terminal-requests の古いエントリを削除 |
| `gar completion bash` | bash completion script を出力 |
