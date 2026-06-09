# コマンドリファレンス

`gar` コマンド一覧。グループがそのままフローになっている。WSL の venv 上で実行する（`make start` で有効化）。

---

## 0. 初期セットアップ

| コマンド | 内容 |
|---|---|
| `make init` | `.venv` 作成・`gar` symlink・VSCode extension install |
| `make start` | venv + bash completion を有効化したサブシェルを開く |
| `gar setup` | 依存コマンド確認・接続プロバイダ選択・既定 host 保存 |
| `gar hw init` | `hardware/` に CSV テンプレートを生成 |

---

## 1. Codespace（ビルド環境）接続

| コマンド | 内容 |
|---|---|
| `gar code start` | Codespace を sshfs マウント・terminal profile を追加 |
| `gar code stop` | マウント解除・profile 削除 |

ビルドは各 target repo の README / build script に従う。成果物は `artifact.json` に記載されたパスで管理する。

---

## 2. シミュレーション VM 管理

| コマンド | 内容 |
|---|---|
| `gar sim infra plan` | Terraform で変更内容を確認（要実装） |
| `gar sim infra apply` | EC2 インスタンス作成・SSH config 更新（要実装） |
| `gar sim infra destroy` | インスタンス削除（要実装） |
| `gar sim boot [--pull]` | EC2 起動・SSH config 更新（`--pull` で git pull も実行） |
| `gar sim status` | EC2 の状態確認 |
| `gar sim shutdown` | EC2 停止 |

---

## 3. シミュレーション環境 デプロイ・起動

| コマンド | 内容 |
|---|---|
| `gar sim env deploy` | CUSE stubs / web-bridge を EC2 へ配置（インフラ） |
| `gar sim deploy` | target app（sensor_demo 等）を EC2 へ転送 |
| `gar sim env start` | systemd services（bridge / CUSE / gpio-sim）+ port forward 起動 |
| `gar sim env stop` | services + port forward 停止 |

アプリは `gar sim env start` では起動しない。EC2 にログインして `~/sensor_demo` を実行する。

---

## 4. シミュレーション環境 観察・診断

| コマンド | 内容 |
|---|---|
| `gar sim env status [--json]` | サービス状態・port forward 確認 |
| `gar sim env diag [--json]` | プロセス・デバイス・API 状態まとめ（AI は `--json`） |
| `gar sim env log` | ログ表示 |
| `gar sim env gpio-sim-check [--json]` | gpio-sim の状態確認 |
| `gar sim gpio plan/install/start/stop/status` | GPIO dummy runtime の個別管理 |

---

## 5. 仮想 H/W 操作

| コマンド | 内容 |
|---|---|
| `gar sim ui button press <line> [--duration-ms]` | ボタンを押して離す |
| `gar sim ui button set <line> <0\|1>` | ボタン状態を直接セット |
| `gar sim ui rfid tap <uid>` | RFID カードを置く（例: `04:AB:CD:EF:01:23`） |
| `gar sim ui rfid remove` | RFID カードを外す |
| `gar sim ui range set <mm>` | VL53L0X 距離値をセット |

---

## 6. 実機デプロイ

実機接続は adb を既定とする。`gar setup` で `SSH / scp` provider への切り替えも可能。

| コマンド | 内容 |
|---|---|
| `gar target fetch` | Codespace から WSL へ成果物取得 |
| `gar target deploy` | WSL → RasPi5 へ配置（adb または SSH/scp） |
| `gar target sync` | fetch + deploy を一括実行 |

adb 実機が未検出の場合、`gar target deploy` が自動的に `gar usb attach` を先行実行する。

---

## 7. USB 接続（実機 adb 用）※廃止予定

> **廃止予定**: WSL から `/mnt/c/...` の Windows 側 adb を直接実行する方式に移行する。

事前に Windows 管理者 PowerShell で一度だけ実行が必要:
```powershell
usbipd bind --busid <busid>
```

| コマンド | 内容 |
|---|---|
| `gar usb attach` | USB-C デバイスを usbipd-win 経由で WSL2 に attach |
| `gar usb detach` | detach |
| `gar usb status` | 接続状態確認 |
| `gar usb list` | 接続可能デバイス一覧 |

---

## 補助

| コマンド | 内容 |
|---|---|
| `gar terminal run -- <cmd>` | VSCode integrated terminal でコマンドを実行（sudo 等の人間入力が必要な場合） |
| `gar terminal gc` | terminal-requests の古いエントリを削除 |
| `gar completion bash` | bash completion script を出力 |
