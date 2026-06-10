# 0 から実機動作までのチュートリアル

このチュートリアルは、しばらく間が空いても Gapless Agent Runtime を最初から立ち上げ直し、シミュレーションで予行してから RasPi5 実機で `sensor_demo` を動かすための一本道です。

操作は人間が行います。AI に頼むときは、各チェックポイントの出力を貼って「次は何をすればいい？」と聞けば続きから進められるようにします。

## ゴール

最終的に次の状態を作ります。

```text
WSL Hub (Gapless Agent Runtime)
  gar setup 済み
  Codespace build VM に接続済み
  EC2 simulation host を起動・deploy・diag 済み
  RasPi5 実機へ target sync 済み

RasPi5
  ~/sensor_demo を実行
  実 GPIO / I2C / SPI / OLED / RFID が反応
```

## 前提

この手順は「完全に空の AWS アカウントや Raspberry Pi OS イメージを作る」手順ではありません。次のものは用意済み、または既存手順で用意されている前提です。

| 対象 | 前提 |
|---|---|
| Windows / WSL2 | WSL2 Ubuntu から `git`, `python3`, `make` が使える |
| GitHub | Codespaces を使える。`gh auth login` 済み、または途中でログインできる |
| EC2 simulation host | `gar sim boot` で起動できる EC2 設定がある |
| RasPi5 | Raspberry Pi OS が起動し、実 H/W 配線済み |
| 実機接続 | 既定は USB-C + adb。ネットワーク接続できる場合は SSH/scp でもよい |
| ビルド成果物 | Codespace 側で artifact bundle を作れる target repo がある |

配線は [05_HARDWARE_WIRING.md](05_HARDWARE_WIRING.md) を参照します。コマンドの細かい意味は [01_COMMAND_REFERENCE.md](01_COMMAND_REFERENCE.md) が正本です。

## 1. WSL Hub を初期化する

Gapless Agent Runtime repo に移動します。

```bash
cd path/to/AgentCockpit
git pull
```

初回、または `.venv` を作り直したいとき:

```bash
make init
```

日常作業の開始:

```bash
make start
```

`make start` の後は、サブシェル内で `gar` と bash 補完が有効になります。抜けるときは `exit` です。

チェック:

```bash
gar ?
gar setup --no-install
```

`python3-venv` がないと言われた場合:

```bash
sudo apt-get update
sudo apt-get install -y python3-venv
rm -rf .venv
make init
make start
```

## 2. provider と既定 host を設定する

まず `gar setup` を実行します。

```bash
gar setup
```

基本の選択は次です。

| カテゴリ | 推奨 |
|---|---|
| 開発環境 | GitHub Codespaces |
| シミュレート環境 | EC2 runtime host へ接続するための SSH Remote |
| 実機環境 | ADB USB-C |

ネットワーク越しに RasPi5 へ SSH できる場合は、実機環境で `SSH / scp` を選んでもよいです。

ここでの `SSH Remote` は「シミュレータ種別」ではなく、EC2 simulation runtime host へ `ssh` / `scp` で入るための接続 provider です。`AWS SSM` は現状の runtime 操作では非推奨なproviderです。

EC2 の既定 host を明示する場合:

```bash
gar setup --ec2-host vibecode-graviton
```

チェック:

```bash
gar sim status
gar code ?
gar target ?
```

## 3. Codespace build VM に接続する

Codespace が 1 つだけなら名前指定なしで進めます。

```bash
gar code start
```

複数ある場合:

```bash
gh codespace list
gar code start --codespace <codespace-name>
```

これで WSL Hub から Codespace の workspace が見えるようになり、VS Code の terminal profile も作られます。

チェック:

```bash
cat ~/.config/codespace-dev/env
ls ~/codespace-dev 2>/dev/null || true
```

## 4. Codespace 側で ARM64 成果物をビルドする

ビルドは Gapless Agent Runtime ではなく、`gar-build-env` Codespace 内の target repo で行います。

Codespace のターミナルで:

```bash
cd /workspaces/gar-build-env
bash scripts/post-create.sh
```

その後は target software ごとの README / build script に従ってビルドします。

ビルド後、artifact bundle ができていることを確認します。既定では次の場所を `gar target fetch` / `gar sim env deploy` が見に行きます。

```bash
ls -la /workspaces/gar-build-env/artifacts/from-codespace
cat /workspaces/gar-build-env/artifacts/from-codespace/artifact.json
```

`artifact.json` には少なくとも `deploy.app.files` が必要です（VM 専用インフラがある場合は `deploy.sim_env.files` も）。

## 5. 先に simulation で予行する

実機へ行く前に、EC2 simulation host で同じ arm64 バイナリを動かします。

WSL Hub 側で:

```bash
gar sim boot
gar sim env deploy
gar sim env start
gar sim env diag --json
```

`diag --json` の `"ok": true` が目安です。失敗したら次を確認します。

```bash
gar sim env status --json
gar sim gpio status --json
gar sim env log
```

EC2 にログインしてアプリを起動します。

```bash
ssh vibecode-graviton
~/sensor_demo
```

別ターミナルの WSL Hub から仮想 H/W を操作します。

```bash
gar sim ui button press 17
gar sim ui rfid tap 04:AB:CD:EF:01:23
gar sim env status --json
```

期待:

```text
button press で system_on 相当の状態が変わる
rfid tap で UID が bridge state / OLED 表示へ反映される
sensor_demo が EC2 上で落ちない
```

simulation を止める場合:

```bash
gar sim env stop
gar sim shutdown
```

## 6. RasPi5 実機を準備する

配線は [05_HARDWARE_WIRING.md](05_HARDWARE_WIRING.md) の通りにします。

RasPi5 側で I2C / SPI を有効化していない場合:

```bash
sudo raspi-config nonint do_i2c 0
sudo raspi-config nonint do_spi 0
sudo reboot
```

再起動後、RasPi5 側で確認します。

```bash
ls -l /dev/i2c-1 /dev/spidev0.0 /dev/gpiochip*
```

I2C デバイスを確認する場合:

```bash
sudo apt-get update
sudo apt-get install -y i2c-tools
i2cdetect -y 1
```

目安:

```text
SSD1306 OLED: 0x3c
VL53L0X:      0x29
```

RFID は配線と SPI 有効化が合っていれば、`sensor_demo` 実行時に UID 読み取りで確認します。

adb 経路を使う場合は、RasPi5 側で `adbd` が起動している必要があります。未設定なら RasPi5 側で:

```bash
sudo apt-get update
sudo apt-get install -y adbd
sudo systemctl enable --now adbd
```

`adbd` package が使えない OS の場合は、無理に adb に寄せず、`gar setup` の実機環境で `SSH / scp` を選びます。

## 7. adb USB-C 経路で実機を WSL2 に見せる

既定の実機 provider は `ADB USB-C` です。

まず WSL Hub 側で確認します。

```bash
gar usb list
gar usb status
adb devices
```

未 share と表示された場合は、Windows の管理者 PowerShell で一度だけ実行します。

```powershell
usbipd bind --busid <busid>
```

その後 WSL Hub 側で:

```bash
gar usb attach --busid <busid>
adb devices
```

`device` と表示されれば OK です。

`gar target sync` / `gar target deploy` は adb device が見えないときに `gar usb attach` 相当を自動で試します。ただし初回の `usbipd bind` だけは管理者 PowerShell が必要です。

## 8. 実機へ deploy する

Codespace から artifact bundle を取得し、そのまま RasPi5 へ push します。

```bash
gar target sync
```

特定 adb device を指定する場合:

```bash
adb devices
gar target sync --serial <serial>
```

ネットワーク越し SSH/scp provider を選んだ場合:

```bash
gar target sync --host raspi5
```

deploy だけやり直す場合:

```bash
gar target fetch
gar target deploy
```

チェック:

```bash
adb shell ls -l /home/user/sensor_demo
```

SSH/scp 経路の場合:

```bash
ssh raspi5 'ls -l ~/sensor_demo'
```

## 9. RasPi5 で実行する

adb 経路:

```bash
adb shell
~/sensor_demo
```

SSH 経路:

```bash
ssh raspi5
~/sensor_demo
```

期待:

```text
物理ボタン GPIO17 を押すと状態が変わる
LED GPIO18 / GPIO24 が反応する
OLED に状態や UID が表示される
RFID カードをかざすと UID が読まれる
```

終了はアプリ側の通常手順に従います。迷ったら `Ctrl-C` で止めます。

## 10. よくある詰まり方

### `gar setup` で不足コマンドが出る

まず案内に従います。sudo や認証が必要なものは人間が visible terminal で実行します。

```bash
gar setup --no-install
```

出力を AI に貼ると、次の手順に分解できます。

### `gar code start` が Codespace を選べない

```bash
gh auth status
gh codespace list
gar code start --codespace <codespace-name>
```

### `gar sim env diag --json` が `"ok": false`

```bash
gar sim env status --json
gar sim gpio status --json
gar sim env log
ssh vibecode-graviton 'systemctl --no-pager --full status gar-sim.target gar-bridge.service gar-gpio-sim.service'
```

出力を貼って「どこが悪い？」と聞けばよいです。

### `gar target sync` が artifact を見つけられない

Codespace 側で artifact bundle の場所を確認します。

```bash
ls -la /workspaces/gar-build-env/artifacts/from-codespace
cat /workspaces/gar-build-env/artifacts/from-codespace/artifact.json
```

WSL Hub 側で取得元を明示します。

```bash
gar target fetch --remote-root /workspaces/gar-build-env/artifacts/from-codespace
gar target deploy
```

### adb device が見えない

```bash
gar usb list
gar usb attach
adb kill-server
adb start-server
adb devices
```

`Not shared` の場合は Windows 管理者 PowerShell で:

```powershell
usbipd bind --busid <busid>
```

### RasPi5 で `/dev/i2c-1` や `/dev/spidev0.0` がない

RasPi5 側で:

```bash
sudo raspi-config nonint do_i2c 0
sudo raspi-config nonint do_spi 0
sudo reboot
```

### `~/sensor_demo` が permission denied

```bash
chmod +x ~/sensor_demo
~/sensor_demo
```

`gar target deploy` の manifest に `mode: "0755"` が入っているかも確認します。



## 11. 最短コマンドまとめ

思い出し用の最短版です。

```bash
cd ~/Yurufuwa/AgentCockpit
git pull
make init
make start
gar setup
gar code start

# Codespace 側で target repo をビルドし artifact bundle を作る

gar sim boot
gar sim env deploy
gar sim env start
gar sim env diag --json
ssh vibecode-graviton '~/sensor_demo'

gar target sync
adb shell
~/sensor_demo
```

SSH/scp 実機経路の場合:

```bash
gar setup                 # 実機環境で SSH / scp を選ぶ
gar target sync --host raspi5
ssh raspi5 '~/sensor_demo'
```
