# Gapless Agent Runtime PoC 成果まとめ

## コンセプト検証完了

**「AI が、実機がなくてもクラウド上でハードウェア込みのテストを進められ、実機と同じバイナリをそのまま動かせる」**

このコンセプトを実装・検証しました。

Gapless Agent Runtime は、組み込み開発を単にクラウド化するだけでなく、AI エージェントが操作しやすい形にビルド、デプロイ、仮想 H/W 操作、ログ観察を整理するための土台です。

この PoC で見えた最大の価値は、「製品には見えないが、壊れると開発が止まる」互換 runtime を AI が作り切れる見通しが立ったことです（背景は [06_INDUSTRY_TRENDS.md](06_INDUSTRY_TRENDS.md)）。

---

## 動作確認結果

### EC2 (Graviton arm64) — フルシミュレーション

`sensor_demo` バイナリ 1 つを EC2 上で動作させ、ブラウザの Virtual Hardware Panel から完全にインタラクション可能。

| 機能 | 経路 | 状態 |
|---|---|---|
| GPIO LED18 (status) | C app → gpio-sim `/dev/gpiochip0` → bridge poll → panel | ✅ |
| GPIO LED24 (activity) | C app → gpio-sim `/dev/gpiochip0` → bridge poll → panel | ✅ |
| GPIO Button 17 | panel → bridge → gpio-sim pull → C app | ✅ |
| I2C SSD1306 OLED 128×64 | C app → cuse_i2c → bridge → panel canvas | ✅ |
| SPI MFRC-522 RFID | panel → bridge → cuse_spi → C app | ✅ |

OLED にリアルタイムで状態が描画され、`Tap Card` ボタン押下で C アプリ内の RFID 読み取りが動作することを確認。

### Raspberry Pi 5 (実機 arm64) — 個別モジュール検証

| モジュール | I/F | 検証 |
|---|---|---|
| LED + ボタン | GPIO | ✅ `gpio_led_button` C アプリで動作 |
| VL53L0X 距離センサー | I2C | ✅ I2C アドレス 0x29 検出、Python ライブラリで実距離測定 |
| MFRC-522 RFID | SPI | ✅ Version 0x92 検出、UID 読取り（実カード/タグ） |
| SSD1306 OLED | I2C | ✅ I2C アドレス 0x3C 検出、`sensor_demo` で表示 |

**`sensor_demo` を EC2 と同じバイナリ（同じソース・同じビルド）で RasPi5 実機で一発動作。**
シミュレーション環境で詰めた品質がそのまま実機に反映され、PoC の中核コンセプトが実証完了。

---

## 実装したコンポーネント

### アプリケーション (`app/`)
- `sensor_demo.c` — 統合デモアプリ（GPIO + I2C + SPI）
- `ssd1306.c/h` — SSD1306 OLED I2C ドライバ（標準 Linux i2c-dev）
- `mfrc522.c/h` — MFRC-522 RFID SPI ドライバ（標準 Linux spidev）

### CUSE スタブ (`gar-tools/cuse-stubs/`)
- `i2c-stub/cuse_i2c.c` — `/dev/i2c-1` を CUSE で生成
- `i2c-stub/vl53l0x_sim.c` — VL53L0X レジスタシミュレーション
- `i2c-stub/ssd1306_sim.c` — SSD1306 トランザクションパーサー、framebuffer を bridge へ送信
- `spi-stub/cuse_spi.c` — `/dev/spidev0.0` を CUSE で生成し、MFRC-522 レジスタプロトコルをシミュレート
- GPIO は kernel `gpio-sim` を使用し、bridge.py が `sim_gpioN/{pull,value}` と同期

### Web ブリッジ + パネル (`gar-tools/cuse-stubs/web-bridge/`)
- `bridge.py` — Unix socket ↔ WebSocket ↔ HTTP ブリッジ
- `panel/` — HTML/CSS/JS の Virtual Hardware Panel

### 開発インフラ
- 旧 Windows PowerShell EC2 helper → **`gar sim boot/shutdown/status`** に移植。WSL2 の AWS CLI で EC2 起動・停止・SSH config 自動更新
- 旧 Windows PowerShell RasPi helper → **`gar target sync`** に移植。Codespaces から artifact bundle を取得し RasPi5 に ADB push / SSH 配送
- 各種 Makefile — ARM ビルド / デプロイ

---

## アーキテクチャ全体像

```
[Windows + Antigravity]
    │
    ├─ gh codespace ssh ──→ [Codespaces x86_64]
    │                         ARM ビルド
    │                         (aarch64-linux-gnu-gcc)
    │                              │
    │                              ├─ scp ──→ [EC2 arm64 Graviton]
    │                              │            sensor_demo (シミュレーション)
    │                              │            └ /dev/i2c-1 = CUSE (cuse_i2c)
    │                              │            └ /dev/spidev0.0 = CUSE (cuse_spi)
    │                              │            └ /dev/gpiochip0 = gpio-sim
    │                              │            └ bridge.py (port 8080/8765)
    │                              │
    │                              └─ gh codespace cp → Windows → adb push
    │                                                            ↓
    │                                          [Raspberry Pi 5 arm64 実機]
    │                                            sensor_demo (実機接続)
    │                                            └ /dev/i2c-1 = 実 I2C
    │                                            └ /dev/spidev0.0 = 実 SPI
    │                                            └ /dev/gpiochip0 = 実 GPIO
    │
    └─ Remote SSH → [EC2 / RasPi5] → PORTS タブ → Simple Browser
                                       └ Virtual Hardware Panel
                                         (OLED canvas / LED / button / RFID)
```

---

## 今回得られた知見

1. **CUSE + gpio-sim の組み合わせ** で、I2C/SPI/GPIO のすべてを `/dev/*` 互換 runtime としてシミュレート可能。EC2 でも RasPi5 でも `~/sensor_demo` を直接起動できる。

2. **ARM ビルド基盤** は GitHub Codespaces 上で `aarch64-linux-gnu-gcc` を使う方法が安定。Codespaces の VM ファイルは保持されるので毎回環境構築不要。

3. **AWS EC2 Graviton (t4g)** は arm64 サーバーとしては最も入手性が良い。RasPi5 と CPU 命令セット互換のためバイナリがそのまま動く。

4. **RasPi5 の API 互換性** — Python の `RPi.GPIO` は RasPi5 非対応（RP1 チップが BCM2712 になり、旧ライブラリが動かない）。`rpi-lgpio` や `lgpio` への移行が必要。

5. **adbd は Ubuntu 標準パッケージにない**が、Raspberry Pi OS（Debian Bookworm）には `adbd` パッケージが存在し、`systemd` で自動起動。EC2 (Ubuntu 24.04) では adbd は使えず SSH/scp のままが現実的。

6. **シーケンス図 + Mermaid** によりワークフロー全体を可視化。ドキュメントが共有可能で、Claude Code に「EC2 にデプロイして」「実機にデプロイして」と頼むだけで実行できる仕組みも構築。

7. **AI コーディングの適所** — 実機互換 runtime は、`strace` による ABI 抽出、stub 実装、ログ確認、回帰テスト追加といった、AI が得意な地味で構造化された作業の集まりでした（差別化の背景は [06_INDUSTRY_TRENDS.md](06_INDUSTRY_TRENDS.md)）。

---

## 残タスク

- [x] OLED モジュール到着後、`sensor_demo` を RasPi5 実機で完全動作確認
- [ ] LCD HAT (ST7789) の対応（追加するなら）
- [x] systemd サービス化による simulation runtime 起動 — 2026-06-05。EC2 で `gar-sim.target`、`gar-gpio-sim.service`、`gar-bridge.service`、`gar-cuse-i2c@i2c-1.service`、`gar-cuse-spi@spidev0.0.service` の active を確認
- [x] SPI/GPIO の fake device runtime への移行（設計: [12_CUSE_MIGRATION_PLAN.md](12_CUSE_MIGRATION_PLAN.md)）
- [ ] `gar sim run <target>` / `gar target run <target>` の共通 manifest 化
- [ ] 無停止デプロイ機構の実装 (Capistranoスタイル)
  - `releases/<timestamp>/` への新バイナリ配置
  - `current` シンボリックリンクの張り替え (`ln -sfn`)
  - 切り替え後の systemd サービス自動再起動 (`systemctl restart`)
