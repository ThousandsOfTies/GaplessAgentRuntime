# シミュレーション・セットアップ

このドキュメントでは、クラウド上（AWS EC2 Graviton）で物理ハードウェアをエミュレートする仕組みについて解説します。

AgentCockpit のシミュレーション方針は、アプリケーションにシミュレーション専用の分岐や HAL を持たせることではありません。実機用アプリは実機と同じ `/dev/*` を開くだけにし、差し替えは EC2 側の device compatibility runtime に閉じ込めます。

現状は I2C を CUSE、GPIO/SPI を LD_PRELOAD shim で実現しています。これは短期 PoC の到達点であり、最終形ではありません。今後は GPIO/SPI も CUSE/fake device へ寄せ、`LD_PRELOAD` をアプリ起動手順から外していく方針です。人手では採算が合いにくい ioctl ABI 追従や stub 実装を AI が担うことが、このプロジェクトの重要な価値です。

## 全体構成

```
[EC2 arm64 (Graviton)]

  sensor_demo (アプリケーション)
    │
    │  GPIO: /dev/gpiochip0 (ioctl)
    │  ──→ gpio_shim.so (LD_PRELOAD で intercept)
    │       └─ 将来: fake /dev/gpiochip0 runtime へ移行
    │       └─ Unix socket ──→ bridge.py
    │
    │  I2C:  /dev/i2c-1 (read/write/ioctl)
    │  ──→ cuse_i2c (CUSE で /dev/i2c-1 を生成)
    │       └─ SSD1306 0x3C: ssd1306_sim → bridge.py
    │       └─ VL53L0X 0x29: vl53l0x_sim (内部状態)
    │
    │  SPI:  /dev/spidev0.0 (SPI_IOC_MESSAGE)
    │  ──→ spi_shim.so (LD_PRELOAD で intercept)
    │       └─ 将来: fake /dev/spidev0.0 runtime へ移行
    │       └─ MFRC-522 register sim → bridge.py
    │
    └─ bridge.py
         ├─ Unix socket /tmp/hw_sim.sock (シム/スタブ ⇔ bridge)
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

## 起動手順

`agp-build-env` Codespace で ARM64 ビルドし、成果物を WSL hub 経由で EC2 に転送済みの前提です。

シミュレーション開始は 2 段階に分けます。

1. `agp sim start` で bridge と dummy device runtime を起動し、EC2 上にテスト用 `/dev/*` を用意する。
2. VS Code terminal profile "EC2 Simulation" などから EC2 にログインし、本番と同じ `start.sh` などでアプリを起動する。

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

### ターミナル 3: アプリ起動（本番と同じ）

```bash
ssh vibecode-graviton
./start.sh
```

---

## バックグラウンド実行（runtime 起動）

`agp sim start` が担当するのは、アプリではなく simulation device runtime の起動です。手動で確認する場合は次のように bridge と dummy device runtime だけを起動します。

```bash
ssh vibecode-graviton 'setsid bash -c "nohup ~/venv/bin/python3 ~/web-bridge/bridge.py > /tmp/bridge.log 2>&1 &" < /dev/null'
sleep 2
ssh vibecode-graviton 'setsid bash -c "sudo nohup ~/cuse_i2c -f --devname=i2c-1 > /tmp/cuse.log 2>&1 &" < /dev/null'
sleep 3
ssh vibecode-graviton 'sudo chmod 666 /dev/i2c-1'
```

runtime ログ確認:
```bash
ssh vibecode-graviton 'tail -f /tmp/bridge.log /tmp/cuse.log'
```

アプリはその後 EC2 にログインし、本番と同じ `./start.sh` などで起動します。

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
| sensor_demo が `/dev/gpiochip0: No such file` | simulation device runtime 未起動 | `agp sim start` 後に fake `/dev/gpiochip0` 起動状態を確認 |
| `Tap Card しても OLED に UID 出ない` | spi_shim が bridge レスポンスをパース失敗 | バージョン要確認（whitespace 対応済み） |
| パネルが Disconnected のまま | ポート 8765 未転送 | PORTS タブで 8765 を Add Port |
| OLED に表示が出ない | I2C アドレス 0x3C 未認識 | `i2cdetect -y 1` で 0x3C があるか確認 |
| `Last UID` が更新されない | system_on が OFF | パネルの GPIO17 PUSH で ON に切替 |
