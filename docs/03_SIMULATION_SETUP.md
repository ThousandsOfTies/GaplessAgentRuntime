# シミュレーション・セットアップ

このドキュメントでは、クラウド上（AWS EC2 Graviton）で物理ハードウェアをエミュレートする仕組みについて解説します。

AgentCockpit のシミュレーション方針は、アプリケーションにシミュレーション専用の分岐や HAL を持たせることではありません。実機用アプリは実機と同じ `/dev/*` を開くだけにし、差し替えは EC2 側の device compatibility runtime に閉じ込めます。

現在は I2C/SPI を CUSE、GPIO を `gpio-sim` + GPIO chardev v2 で実現しています。EC2 側の runtime が実機と同じ `/dev/i2c-1`、`/dev/spidev0.0`、`/dev/gpiochip0` を用意するため、アプリは `~/sensor_demo` を直接起動します。

移行の具体的な設計とステップは [12_CUSE_MIGRATION_PLAN.md](12_CUSE_MIGRATION_PLAN.md)、このアプローチがなぜ価値を持つかは [06_INDUSTRY_TRENDS.md](06_INDUSTRY_TRENDS.md) にまとめています。

## 全体構成

```
[EC2 arm64 (Graviton)]

  sensor_demo (アプリケーション)
    │
    │  GPIO: /dev/gpiochip0 (ioctl)
    │  ──→ gpio-sim (kernel module)
    │       └─ sim_gpio17/27 pull を bridge.py が更新
    │       └─ sim_gpio18/24 value を bridge.py が poll
    │
    │  I2C:  /dev/i2c-1 (read/write/ioctl)
    │  ──→ cuse_i2c (CUSE で /dev/i2c-1 を生成)
    │       └─ SSD1306 0x3C: ssd1306_sim → bridge.py
    │       └─ VL53L0X 0x29: vl53l0x_sim (内部状態)
    │
    │  SPI:  /dev/spidev0.0 (SPI_IOC_MESSAGE)
    │  ──→ cuse_spi (CUSE で /dev/spidev0.0 を生成)
    │       └─ MFRC-522 register sim → bridge.py
    │
    └─ bridge.py
         ├─ Unix socket /tmp/hw_sim.sock (CUSE スタブ ⇔ bridge)
         ├─ WebSocket  ws://0.0.0.0:8765 (bridge ⇔ panel)
         └─ HTTP       http://0.0.0.0:8080 (panel HTML/CSS/JS 配信)
                ↓
          [Antigravity Simple Browser]
            Virtual Hardware Panel
              - LED GPIO18 / GPIO24 (canvas)
              - Button GPIO17 / GPIO27
              - VL53L0X range slider
              - MFRC-522 Tap Card / Remove
              - SSD1306 OLED 128×64 canvas
```

---

## EC2 AMI 初期セットアップ

生の Ubuntu EC2 AMI から simulation runtime を動かす場合、通常のデプロイ済み成果物に加えて、GPIO simulation 用の kernel module package を入れておく必要があります。

今回 `vibecode-graviton` で追加したもの:

```bash
sudo apt-get update
sudo apt-get install -y linux-modules-extra-"$(uname -r)"
```

これで `gpio-sim` module が `/lib/modules/$(uname -r)/.../gpio-sim.ko.*` に入り、`agp sim start` が `modprobe gpio-sim` できるようになります。

確認:

```bash
modinfo gpio-sim
zcat /proc/config.gz 2>/dev/null | grep -i GPIO_SIM || \
  grep -i GPIO_SIM /boot/config-"$(uname -r)" 2>/dev/null
```

診断・ABI 調査用に入れたもの:

```bash
sudo apt-get install -y gpiod strace
```

`gpiod` と `strace` は runtime の常時起動には必須ではありません。`gpiodetect` / `gpioinfo` / `strace -e ioctl` で `gpio-sim` や GPIO chardev ABI を確認するための道具です。

`agp sim start` が毎回行うこと:

```text
modprobe gpio-sim
configfs mount
/sys/kernel/config/gpio-sim/agp に 54 line の fake GPIO chip を作成
必要なら gpio-sim の /dev/gpiochipN を /dev/gpiochip0 に bind mount
```

つまり AMI に一度必要なのは kernel module package の導入で、`/dev/gpiochip0` の差し替え自体は simulation runtime 起動時に行います。アプリや `start.sh` 側に EC2 専用の環境変数やパス分岐は置きません。

### SIM マシン構築のコード化方針

上記の AMI 初期セットアップは、手順として残すだけでなく、将来的には infrastructure as code として再現可能にします。

役割分担:

| ツール | 役割 | AgentCockpit での使いどころ |
|---|---|---|
| Terraform | EC2 / Security Group / key / subnet / IAM / disk size などの cloud resource 定義 | simulation host を同じ形で作り直す |
| Terraform `user_data` | 初回起動時の軽い bootstrap | `linux-modules-extra-$(uname -r)`, `gpiod`, `strace` の install |
| Packer | 事前に設定済み AMI を焼く | apt install 済みの AgentCockpit simulation AMI を固定する |
| Ansible | 起動済み machine に対する設定収束 | systemd unit、udev rule、runtime 配置などが増えた段階 |

当面の方針:

1. `infra/terraform/` に simulation host 用 Terraform を置く。
2. EC2 instance / security group / volume / SSH key などを Terraform で定義する。
3. `user_data` で最低限の package install を行う。
4. アプリ成果物や `agp sim start` が作る runtime state は Terraform に持たせない。

最初の `user_data` イメージ:

```bash
#!/bin/bash
set -eux

apt-get update
apt-get install -y \
  linux-modules-extra-"$(uname -r)" \
  gpiod \
  strace

modprobe gpio-sim || true
```

将来の方針:

- runtime が systemd unit 化されたら、Packer で AMI に unit / package / base tools を焼く。
- Terraform は「どの AMI を、どの instance type / network で起動するか」だけを管理する。
- 起動済み machine の設定変更が増える場合は Ansible を足す。
- `agp` CLI は Terraform の代替ではなく、作成済み simulation host の起動停止・deploy・diag を担当する。

この分担にすると、アプリは `/dev/*` 前提のまま、simulation machine の再現性だけを infrastructure layer に閉じ込められます。

---

## 起動手順

`agp-build-env` Codespace で ARM64 ビルドし、成果物を WSL hub 経由で EC2 に転送済みの前提です。

シミュレーション開始は 2 段階に分けます。

1. `agp sim start` で bridge と dummy device runtime を起動し、runtime host 上にテスト用 `/dev/*` を用意する。
2. VS Code terminal profile "EC2 Simulation" などから EC2 にログインし、本番と同じ `~/sensor_demo` でアプリを起動する。

この分離により、sim/device でアプリ起動スクリプトを分けず、違いを `/dev/*` を用意する runtime 側に閉じ込めます。

### ターミナル 1: ウェブブリッジ起動

```bash
ssh vibecode-graviton
~/venv/bin/python3 ~/web-bridge/bridge.py
# → [bridge] Unix socket listening: /tmp/hw_sim.sock
# → [bridge] WebSocket  ws://0.0.0.0:8765
# → [bridge] HTTP panel http://0.0.0.0:8080
```

### ターミナル 2: I2C CUSE スタブ起動

```bash
ssh vibecode-graviton
sudo ~/cuse_i2c -f --devname=i2c-1
# → [vl53l0x_sim] initialized, range=300mm
# → [cuse_i2c] starting /dev/i2c-1 stub

# 別ターミナルから一度だけ
sudo chmod 666 /dev/i2c-1
```

### ターミナル 3: SPI CUSE スタブ起動

```bash
ssh vibecode-graviton
sudo ~/cuse_spi -f --devname=spidev0.0
# → [cuse_spi] starting /dev/spidev0.0 stub

# 別ターミナルから一度だけ
sudo chmod 666 /dev/spidev0.0
```

### ターミナル 4: アプリ起動（本番と同じ）

```bash
ssh vibecode-graviton
~/sensor_demo
```

---

## バックグラウンド実行（runtime 起動）

`agp sim start` が担当するのは、アプリではなく simulation runtime の起動です。手動で確認する場合は次のように bridge と dummy device runtime だけを起動します。

```bash
ssh vibecode-graviton 'setsid bash -c "nohup ~/venv/bin/python3 ~/web-bridge/bridge.py > /tmp/bridge.log 2>&1 &" < /dev/null'
sleep 2
ssh vibecode-graviton 'setsid bash -c "sudo nohup ~/cuse_i2c -f --devname=i2c-1 > /tmp/cuse.log 2>&1 &" < /dev/null'
ssh vibecode-graviton 'setsid bash -c "sudo nohup ~/cuse_spi -f --devname=spidev0.0 > /tmp/cuse_spi.log 2>&1 &" < /dev/null'
sleep 3
ssh vibecode-graviton 'sudo chmod 666 /dev/i2c-1 /dev/spidev0.0'
```

runtime ログ確認:
```bash
ssh vibecode-graviton 'tail -f /tmp/bridge.log /tmp/cuse.log /tmp/cuse_spi.log'
```

アプリはその後 EC2 にログインし、本番と同じ `~/sensor_demo` で起動します。

---

## 設計方針: 起動スクリプトを分岐させない

実機検証が始まると、シミュレーション専用スクリプトは人間の注意から外れ、壊れていても気づきにくくなります。AgentCockpit では、sim/device で起動スクリプトを完全に分けるのではなく、共通の target 定義から runtime adapter が必要な device layer を用意する設計へ寄せます。

```text
target: sensor_demo
binary: ~/sensor_demo
requires: gpio, spi, i2c

sim runtime:
  gpio -> fake /dev/gpiochip0
  spi  -> fake /dev/spidev0.0
  i2c  -> CUSE /dev/i2c-1

device runtime:
  gpio -> real /dev/gpiochip0
  spi  -> real /dev/spidev0.0
  i2c  -> real /dev/i2c-1
```

この形なら、アプリや起動定義は「何を起動するか」だけを持ち、シミュレーション固有の差し替えは AgentCockpit runtime が担当します。

---

---

## シミュレーションにおける制約とモダンAPIへの移行方針

旧来の組み込み開発では、高速なGPIO制御のために `/dev/gpiomem` などに対して `mmap` を行い、物理メモリ（レジスタ）を直接書き換える手法が一般的でした（`wiringPi` 等）。しかし、**この `mmap` 方式はシミュレーション環境において致命的な制約**を持ちます。

* **ユーザー空間フックの限界**: `mmap` でマッピングされたメモリ空間に対するアプリからの直接書き込みは、システムコール（関数呼び出し）を伴わないため、ユーザー空間の関数フックでは「いつ値が書き換わったか」を検知できません。これをトラップするには MMU のページフォールトを利用したカーネルレベルの強引なハックが必要になります。
* **ハードウェア依存**: `mmap` は物理メモリアドレス（例: BCM2835 の特定アドレス）に決め打ちとなるため、EC2 Graviton や他の基板への移植性が低くなります。

### 制約の回避（新しいカーネル機能の活用）
AgentCockpit では、新規開発および移行において **「Linux標準の GPIO Character Device API (`/dev/gpiochipX`) と `libgpiod` を使用する」** 方針を推奨しています。

これにより、すべての操作が `ioctl` などのシステムコールを経由するようになります。
1. **シミュレーションが容易に**: システムコール経由になるため、CUSE や標準のダミーカーネルモジュール（`gpio-mockup`, `gpio-sim`）を使うだけで、特殊なハックなしに完璧なシミュレーションが可能になります。
2. **完全なポータビリティ**: ハードウェア固有のアドレス依存がなくなり、RasPi でもクラウド上の仮想ハードウェアでも、全く同じバイナリ（環境一致）が安全かつ高速に動作します。

---

## ブラウザパネルへのアクセス

Antigravity から EC2 に Remote SSH 接続している場合、ポートは自動的にフォワードされます。

1. **Open Folder → `/home/ubuntu/AgentCockpit`** を開く（`.vscode/settings.json` の自動転送設定が有効化される）
2. **PORTS タブ**で `8080` の行を右クリック → "Open in Simple Browser"
3. HTML パネルが開き、各デバイスの状態がリアルタイム表示される

> 自動検出されない場合は手動で `8080` と `8765` を Add Port してください。

---

## 操作と確認

| 操作 | パネル表示 / 期待される挙動 |
|---|---|
| `BTN GPIO17` PUSH | LED GPIO18 がトグル / OLED の `System: ON/OFF` 切替 |
| `Range` スライダ | VL53L0X 距離値が変動（vl53l0x_read で確認可） |
| `Tap Card` | OLED に `Last UID: 04:AB:CD:EF` 表示 / LED GPIO24 がフラッシュ / Scans カウンタ増加 |
| `Remove` | カード未検出に戻る |

---

## トラブルシューティング

| 症状 | 原因 | 対処 |
|------|------|------|
| `bridge not available` | bridge.py が未起動 | ターミナル1 を確認 |
| `/dev/fuse: Permission denied` | sudo なしで CUSE 起動 | `sudo` で起動 |
| sensor_demo が `/dev/gpiochip0: No such file` | simulation runtime 未起動 | `agp sim start` 後に fake `/dev/gpiochip0` 起動状態を確認 |
| `Tap Card しても OLED に UID 出ない` | cuse_spi / bridge / system_on のいずれかが未接続 | `agp sim diag --json`、`agp sim log`、`sensor_demo` ログを確認 |
| パネルが Disconnected のまま | ポート 8765 未転送 | PORTS タブで 8765 を Add Port |
| OLED に表示が出ない | I2C アドレス 0x3C 未認識 | `i2cdetect -y 1` で 0x3C があるか確認 |
| `Last UID` が更新されない | system_on が OFF | パネルの GPIO17 PUSH で ON に切替 |
