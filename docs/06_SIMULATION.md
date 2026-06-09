# シミュレーション環境

このドキュメントでは、クラウド上（AWS EC2 Graviton）で物理ハードウェアをエミュレートする仕組みについて解説します。

Gapless Agent Runtime のシミュレーションは、EC2 側の device compatibility runtime が実機と同じ `/dev/*` を再現することで、アプリを無改造のまま動かす。差し替えの責務を OS/device layer に閉じ込めることで、アプリは実機・EC2 どちらでも同じバイナリ・同じ起動コマンドで動作します。

現在は I2C/SPI を CUSE、GPIO を `gpio-sim` + GPIO chardev v2 で実現しています。EC2 側の runtime が実機と同じ `/dev/i2c-1`、`/dev/spidev0.0`、`/dev/gpiochip0` を用意するため、アプリは `~/sensor_demo` を直接起動します。runtime の設定・実行ファイルは `/etc/gar/hardware/`、`/usr/local/sbin/`、`/usr/local/lib/gar/`、`/run/gar/` に保存し、アプリ本体だけを本番と同じユーザー領域の成果物として扱います。

移行の具体的な設計とステップは [12_CUSE_MIGRATION_PLAN.md](12_CUSE_MIGRATION_PLAN.md)、このアプローチがなぜ価値を持つかは [06_INDUSTRY_TRENDS.md](06_INDUSTRY_TRENDS.md) にまとめています。

﻿## 全体構成

`sensor_demo` と `bridge.py` は独立したプロセス。`sensor_demo` は標準の `/dev/*` インターフェース（ioctl / read / write）しか使わず、`bridge.py` を直接呼び出さない。

```
[EC2 arm64 (Graviton)]

  ┌─ sensor_demo (アプリケーション)
  │     │  GPIO: /dev/gpiochip0 (ioctl)        ──→ gpio-sim (kernel module)
  │     │  I2C:  /dev/i2c-1    (read/write)    ──→ cuse_i2c
  │     │  SPI:  /dev/spidev0.0 (SPI_IOC_MESSAGE) ──→ cuse_spi
  │
  │            仮想デバイス ↔ bridge.py 間は Unix socket で接続
  │
  └─ bridge.py  (/run/gar/hw_sim.sock)
        │  gpio-sim: sim_gpio17/27 pull 書き込み、sim_gpio18/24 value poll
        │  cuse_i2c: SSD1306 0x3C フレームバッファ受信、VL53L0X 0x29 距離値配信
        │  cuse_spi: MFRC-522 register 状態同期
        │
        ├─ WebSocket  ws://0.0.0.0:8765  ──→ Virtual Hardware Panel (browser)
        └─ HTTP       http://0.0.0.0:8080 (panel HTML/CSS/JS 配信)

  [VSCode Simple Browser]
    Virtual Hardware Panel
      - LED GPIO18 / GPIO24 (canvas)
      - Button GPIO17 / GPIO27
      - VL53L0X range slider
      - MFRC-522 Tap Card / Remove
      - SSD1306 OLED 128×64 canvas
```

---

## EC2 AMI 初期セットアップ

simulation host の EC2 インスタンス定義・初期 package install は Terraform で管理する。
Terraform の呼び出しは `gar sim infra` コマンド経由で行う（`terraform` を直接叩かない）。

インフラ定義:

```
infra/terraform/
  main.tf        — EC2 / Security Group / volume / SSH key の定義
  user_data.sh   — 初回起動時の bootstrap（linux-modules-extra / gpiod / strace の install）
```

### インスタンスの作成・再作成

```bash
gar sim infra plan   # 変更内容を確認
gar sim infra apply  # インスタンスを作成・SSH config 更新
```

`gar sim infra apply` は apply 後に instance_id / public_ip を `.gar/config.json` へ保存し、`~/.ssh/config` の HostName を自動更新する（`gar sim boot` 相当の後処理も含む）。

### 起動・停止（既存インスタンス）

インスタンス作成後の日常的な起動停止は `gar sim boot` / `gar sim shutdown` を使う。

```bash
gar sim boot     # 起動 + SSH config 更新
gar sim shutdown # 停止
```

### アプリ・runtime のデプロイ

インスタンスが起動したら、アプリ成果物と runtime の配置は `gar sim env deploy` / `gar sim env start` が担う。Terraform には持たせない。

```bash
gar sim env deploy   # CUSE stubs / web-bridge を配置
gar sim deploy       # target app を転送
gar sim env start    # systemd services + port forward 起動
```

### 確認

```bash
gar sim env diag --json   # プロセス・デバイス・API 状態
```

---

## 起動手順

`gar-build-env` Codespace で ARM64 ビルドし、成果物を WSL hub 経由で EC2 に転送済みの前提です。

シミュレーション開始は 2 段階に分けます。

1. **runtime 配置** — `gar sim env start` で bridge と dummy device runtime を起動し、runtime host 上にテスト用 `/dev/*` を用意する。
2. **アプリ起動** — VS Code terminal profile "EC2 Simulation" などから EC2 にログインし、本番と同じ `~/sensor_demo` でアプリを起動する。

この分離により、sim/device でアプリ起動スクリプトを分けず、違いを `/dev/*` を用意する runtime 側に閉じ込めます。

### runtime 配置

```bash
gar sim env deploy
gar sim env start
```

主な配置先:

```text
/etc/gar/hardware/*.csv
/usr/local/sbin/gar-gpio-sim-start
/usr/local/sbin/gar-gpio-sim-stop
/usr/local/sbin/gar-bridge-start
/usr/local/sbin/cuse_i2c
/usr/local/sbin/cuse_spi
/usr/local/lib/gar/web-bridge/
/run/gar/
/run/gar/hw_sim.sock
```

systemd unit:

```text
gar-sim.target
gar-gpio-sim.service
gar-bridge.service
gar-cuse-i2c@i2c-1.service
gar-cuse-spi@spidev0.0.service
```

GPIO dummy runtime だけを確認・更新したい場合は、full runtime の生コマンドを直接打たずに `gar sim gpio` を使います。

```bash
gar sim gpio plan --json
gar sim gpio install
gar sim gpio start
gar sim gpio status --json
gar sim gpio stop
```

`plan` はローカルの `hardware/gpio.csv` から生成される gpio-sim chip / line / label / service 配置の契約を表示します。`start` は `modprobe gpio-sim`、configfs chip 作成、必要な bind mount までを `gar-gpio-sim.service` 経由で行います。

### アプリ起動（本番と同じ）

```bash
ssh vibecode-graviton
~/sensor_demo
```

---

﻿## Runtime 操作単位

`gar sim env start` が担当するのは、アプリではなく simulation runtime の起動です。bridge / CUSE / gpio-sim を個別の生コマンドで起動するのではなく、`gar` の操作単位を使います。

```bash
gar sim env deploy
gar sim env start
gar sim env diag --json
gar sim env log
```

GPIO dummy runtime だけを扱う場合:

```bash
gar sim gpio plan --json
gar sim gpio install
gar sim gpio start
gar sim gpio status --json
```

アプリはその後 EC2 にログインし、本番と同じ `~/sensor_demo` で起動します。

---

﻿## 設計方針: 起動スクリプトを分岐させない

実機検証が始まると、シミュレーション専用スクリプトは人間の注意から外れ、壊れていても気づきにくくなります。Gapless Agent Runtime では、sim/device で起動スクリプトを完全に分けるのではなく、共通の target 定義から runtime adapter が必要な device layer を用意する設計へ寄せます。

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

この形なら、アプリや起動定義は「何を起動するか」だけを持ち、シミュレーション固有の差し替えは Gapless Agent Runtime runtime が担当します。

---

---

﻿## シミュレーションにおける制約とモダンAPIへの移行方針

旧来の組み込み開発では、高速なGPIO制御のために `/dev/gpiomem` などに対して `mmap` を行い、物理メモリ（レジスタ）を直接書き換える手法が一般的でした（`wiringPi` 等）。しかし、**この `mmap` 方式はシミュレーション環境において致命的な制約**を持ちます。

* **ユーザー空間フックの限界**: `mmap` でマッピングされたメモリ空間に対するアプリからの直接書き込みは、システムコール（関数呼び出し）を伴わないため、ユーザー空間の関数フックでは「いつ値が書き換わったか」を検知できません。これをトラップするには MMU のページフォールトを利用したカーネルレベルの強引なハックが必要になります。
* **ハードウェア依存**: `mmap` は物理メモリアドレス（例: BCM2835 の特定アドレス）に決め打ちとなるため、EC2 Graviton や他の基板への移植性が低くなります。

### 制約の回避（新しいカーネル機能の活用）
Gapless Agent Runtime では、新規開発および移行において **「Linux標準の GPIO Character Device API (`/dev/gpiochipX`) と `libgpiod` を使用する」** 方針を推奨しています。

これにより、すべての操作が `ioctl` などのシステムコールを経由するようになります。
1. **シミュレーションが容易に**: システムコール経由になるため、CUSE や標準のダミーカーネルモジュール（`gpio-mockup`, `gpio-sim`）を使うだけで、特殊なハックなしに完璧なシミュレーションが可能になります。
2. **完全なポータビリティ**: ハードウェア固有のアドレス依存がなくなり、RasPi でもクラウド上の仮想ハードウェアでも、全く同じバイナリ（環境一致）が安全かつ高速に動作します。

---

﻿## ブラウザパネルへのアクセス

Antigravity から EC2 に Remote SSH 接続している場合、ポートは自動的にフォワードされます。

1. **Open Folder → `/home/ubuntu/Gapless Agent Runtime`** を開く（`.vscode/settings.json` の自動転送設定が有効化される）
2. **PORTS タブ**で `8080` の行を右クリック → "Open in Simple Browser"
3. HTML パネルが開き、各デバイスの状態がリアルタイム表示される

> 自動検出されない場合は手動で `8080` と `8765` を Add Port してください。

---

﻿## 操作と確認

| 操作 | パネル表示 / 期待される挙動 |
|---|---|
| `BTN GPIO17` PUSH | LED GPIO18 がトグル / OLED の `System: ON/OFF` 切替 |
| `Range` スライダ | VL53L0X 距離値が変動（vl53l0x_read で確認可） |
| `Tap Card` | OLED に `Last UID: 04:AB:CD:EF` 表示 / LED GPIO24 がフラッシュ / Scans カウンタ増加 |
| `Remove` | カード未検出に戻る |

### bridge HTTP API（内部仕様）

`gar sim ui ...` は内部で bridge HTTP API を SSH 越しに叩く。直接叩く必要は通常ないが参照用に記載する。

| Endpoint | Method | 用途 | 対応 `gar` コマンド |
|---|---|---|---|
| `/api/state` | GET | 仮想 H/W 状態を取得 | `gar sim env status --json` |
| `/api/button` | POST | GPIO ボタン状態を直接セット | `gar sim ui button set` |
| `/api/button/press` | POST | GPIO ボタンを押して離す | `gar sim ui button press` |
| `/api/rfid/tap` | POST | RFID カードを置く | `gar sim ui rfid tap` |
| `/api/rfid/remove` | POST | RFID カードを外す | `gar sim ui rfid remove` |
| `/api/range` | POST | VL53L0X の距離値をセット | `gar sim ui range set` |

### JSON シナリオ試験

仮想 H/W 操作は JSON シナリオとして定義し、AI や CI が繰り返し実行できる。

```json
{
  "name": "sensor_demo system-on rfid flow",
  "steps": [
    { "action": "button_press", "line": 17, "duration_ms": 150 },
    { "action": "wait", "seconds": 0.5 },
    { "action": "rfid_tap", "uid": "04:AB:CD:EF:01:23" },
    { "action": "expect", "path": "spi.mfrc522.present", "equals": true }
  ]
}
```

| action | 用途 |
|---|---|
| `button_press` | GPIO ボタンを押して離す |
| `button_set` | GPIO ボタン状態を直接セット |
| `rfid_tap` / `rfid_remove` | RFID カードを置く / 外す |
| `range_set` | VL53L0X の距離値をセット |
| `wait` | 指定秒数待つ |
| `expect` | `/api/state` の値を検証する |

---

﻿## トラブルシューティング

| 症状 | 原因 | 対処 |
|------|------|------|
| `bridge not available` | bridge.py が未起動 | ターミナル1 を確認 |
| `/dev/fuse: Permission denied` | sudo なしで CUSE 起動 | `sudo` で起動 |
| sensor_demo が `/dev/gpiochip0: No such file` | simulation runtime 未起動 | `gar sim env start` 後に fake `/dev/gpiochip0` 起動状態を確認 |
| `Tap Card しても OLED に UID 出ない` | cuse_spi / bridge / system_on のいずれかが未接続 | `gar sim env diag --json`、`gar sim env log`、`sensor_demo` ログを確認 |
| パネルが Disconnected のまま | ポート 8765 未転送 | PORTS タブで 8765 を Add Port |
| OLED に表示が出ない | I2C アドレス 0x3C 未認識 | `i2cdetect -y 1` で 0x3C があるか確認 |
| `Last UID` が更新されない | system_on が OFF | パネルの GPIO17 PUSH で ON に切替 |

