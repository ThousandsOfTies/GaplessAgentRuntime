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

### Vibe Remote 疑似デバイス

`gar setup` のシミュレート環境に `Vibe Remote Virtual Device` を追加している。
M5Stack 実機の代わりに `/tmp/gar-vibe-remote-device/` 配下のファイルを操作し、
Vibe Remote の WebSocket へ `agentStatus` を送れる。

```bash
cd ~/Yurufuwa/gar-vibe-ui/vibe-remote
npm install
VIBE_REMOTE_TOKEN=... npm run virtual:device

echo press > /tmp/gar-vibe-remote-device/button_a  # running
echo press > /tmp/gar-vibe-remote-device/button_b  # waiting
echo press > /tmp/gar-vibe-remote-device/button_c  # done
cat /tmp/gar-vibe-remote-device/screen.txt
```

### ESP32 QEMU Firmware

`gar setup` のシミュレート環境に `ESP32 QEMU Firmware` を追加している。
これは Vibe Remote 疑似デバイスと違い、`firmware.bin` を含むESP32 artifactを
flash imageにまとめ、Espressif QEMUでファームウェアとして起動するための入口。

GARとしての長期理想は Renode 上の M5Stack/ESP32 仮想ボード。QEMU runner は
Renodeが育つまでのboot smoke test兼比較対象として残す。Renode化の段階表は
`~/Yurufuwa/gar-tools/targets/esp32/renode/ROADMAP.md` を参照。

既定 artifact:

```bash
~/Yurufuwa/gar-vibe-ui/vibe-remote/m5stack-client/artifacts/20260617-152624-m5stack-core2
```

手動確認:

```bash
~/Yurufuwa/gar-tools/targets/esp32/qemu/bin/gar-esp32-flash-image \
  --artifact ~/Yurufuwa/gar-vibe-ui/vibe-remote/m5stack-client/artifacts/20260617-152624-m5stack-core2 \
  --output /tmp/gar-m5stack-core2-flash.bin
~/Yurufuwa/gar-tools/targets/esp32/qemu/bin/gar-esp32-qemu-run \
  /tmp/gar-m5stack-core2-flash.bin
```

### Renode MCU

`gar setup` のシミュレート環境に `Renode (MCU/ベアメタル)` を追加している。
WSL/Linux 上で選択すると、Renode portable build を
`~/.local/share/gar/renode` に導入し、`~/.local/bin/renode` と
`~/.local/bin/renode-test` の launcher を作成する。

Renode portable .NET build は最小 WSL 環境で `libicu` 不足に当たることがあるため、
GAR が作成する launcher は既定で
`DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1` を設定する。`libicu` を入れて通常の
globalization mode で動かしたい場合は、実行前に環境変数を明示的に上書きする。

現時点の Renode provider は install / 検証入口であり、`gar sim env start` などの
runtime 統合は未配線。Linux runtime で CUSE/gpio-sim を動かす既存経路には
`SSH Remote` provider を使う。

確認例:

```bash
gar setup
renode --version
. ~/.local/share/gar/renode-test-venv/bin/activate
cd ~/.local/share/gar/renode
renode-test tests/platforms/xtensa.robot
```

`qemu-system-xtensa` が無い場合は、ESP-IDF の `idf_tools.py install qemu-xtensa`
で Espressif QEMU を入れる。

---

## 6. 実機デプロイ

実機接続は adb を既定とする。`gar setup` で `SSH / scp` provider への切り替えも可能。

| コマンド | 内容 |
|---|---|
| `gar target fetch` | Codespace から WSL へ成果物取得 |
| `gar target deploy` | WSL → RasPi5 へ配置（adb または SSH/scp） |
| `gar target sync` | fetch + deploy を一括実行 |
| `gar target build-esp32` | Codespaces で ESP32/M5Stack firmware をビルドし、artifact を WSL へ取得 |
| `gar target flash-esp32` | ESP32/M5Stack firmware artifact を esptool で実機へ書き込み |

adb 実機が未検出の場合、`gar target deploy` が自動的に `gar usb attach` を先行実行する。

M5StickC Plus2 Vibe Remote artifact を書き込む例:

```bash
gar target build-esp32 \
  --codespace <codespace-name> \
  --pio-env m5stickc-plus2-vibe-min
gar target flash-esp32 --port /dev/ttyACM0
```

ビルド、artifact 取得、flash を一括で行う例:

```bash
gar target build-esp32 \
  --codespace <codespace-name> \
  --pio-env m5stickc-plus2-vibe-min \
  --flash \
  --port /dev/ttyACM0
```

既存 artifact を書き込む例:

```bash
gar target flash-esp32 \
  --artifact-dir ~/Yurufuwa/gar-vibe-ui/vibe-remote/m5stack-client/artifacts/20260619-063145-m5stickc-plus2-vibe-min \
  --port COM3
```

WSL 上では `COM3` を `/dev/ttyS3` に自動変換する。`--artifact-dir` を省略した場合は
`~/Yurufuwa/gar-vibe-ui/vibe-remote/m5stack-client/artifacts/` 配下の最新 artifact を使う。
`esptool` が見つからない場合は `~/.local/share/gar/esptool-venv` に自動導入する。

`/dev/ttyS3` が `root:dialout` で permission denied になる場合:

```bash
sudo usermod -aG dialout $USER
```

その後、WSL を再起動するかログアウト/ログインして group 変更を反映する。

権限は通ったが `Could not configure port: (5, 'Input/output error')` になる場合は、
WSL の `/dev/ttyS3` COM ブリッジでは USB シリアルの制御が足りていない可能性がある。
Windows 側の serial monitor を閉じても変わらない場合は、WSL から `gar usb` 経由で
CH9102 を WSL へ attach し、`/dev/ttyACM0` または `/dev/ttyUSB0` として書き込む。

```bash
gar usb list
gar usb bind --match CH9102
gar usb attach --match CH9102
```

`bind` は Host OS 側の管理者権限を要求することがある。その場合だけ Host OS 上で
コマンドプロンプトまたは PowerShell を管理者権限で開き、`gar` ではなく `usbipd` を直接実行する。
`--busid` の値は `gar usb bind --match CH9102` のエラー文に表示される。

```powershell
usbipd bind --busid <busid>
```

すでに share 済みなら `attach` は WSL から完結する。

```bash
ls -l /dev/ttyACM* /dev/ttyUSB*
gar target flash-esp32 --port /dev/ttyACM0
```

---

## 7. USB 接続（実機 adb 用）※廃止予定

> **廃止予定**: WSL から `/mnt/c/...` の Windows 側 adb を直接実行する方式に移行する。

事前に Windows 管理者 PowerShell で一度だけ実行が必要:
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

---

## 補助

| コマンド | 内容 |
|---|---|
| `gar terminal run -- <cmd>` | VSCode integrated terminal でコマンドを実行（sudo 等の人間入力が必要な場合） |
| `gar terminal gc` | terminal-requests の古いエントリを削除 |
| `gar completion bash` | bash completion script を出力 |
