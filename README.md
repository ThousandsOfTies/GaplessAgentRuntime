# AgentCockpit

**AI が最後まで動かせる開発コックピット。**

AgentCockpit は、開発者が手順を覚えて個別に操作する環境ではなく、**VSCode Free 上で AI への指示、AI の作業、ビルド、デプロイ、仮想 H/W 操作、ログ観察、シミュレータ UI、実機検証までを一貫して扱うための環境定義**です。

現在の実証対象は組み込み Linux 開発です。EC2 Graviton 上に仮想 GPIO/I2C/SPI を用意し、RasPi5 実機と同じ ARM64 バイナリを動かします。これにより、AI は実機がなくてもハードウェア込みの検証を進められ、実機が手に入った際も同じバイナリをそのまま流し込めます。

> 旧リポジトリ名は `ExperimentalDevEnv` です。

## ドキュメント ナビゲーション

### 📖 [1. アーキテクチャコンセプト (01_ARCHITECTURE.md)](docs/01_ARCHITECTURE.md)
* なぜ「AI が働きやすい環境定義」なのか？
* Human Intent → AI Agent → Cloud/Device という役割分担と、Codespaces + EC2 Graviton + RasPi5 の全体像。

### 🔄 [2. 開発ワークフローとシーケンス (02_WORKFLOW.md)](docs/02_WORKFLOW.md)
* 人間が AI に指示してから、AI がシミュレータや実機で動かすまでの具体的なシーケンス図。
* コマンドリファレンス。

### 🛠️ [3. ハードウェアシミュレーション設定 (03_SIMULATION_SETUP.md)](docs/03_SIMULATION_SETUP.md)
* `cuse-stubs` を用いた I2C/GPIO/SPI スタブの仕組み。
* EC2上での Web ブリッジ起動方法と、Antigravity（ブラウザ）での Virtual Hardware Panel の使い方。

### 🔌 [4. 実機の配線 (04_HARDWARE_WIRING.md)](docs/04_HARDWARE_WIRING.md)
* RasPi5 とブレッドボードを使った LED / ボタン / I2C / SPI モジュールの配線図。

### 🎯 [5. PoC 成果まとめ (05_RESULTS.md)](docs/05_RESULTS.md)
* EC2 上でのフルシミュレーション動作確認結果と RasPi5 実機での動作確認結果。
* 実装したコンポーネントと得られた知見。

### 🌍 [6. 業界動向と本PoCの技術的価値 (06_INDUSTRY_TRENDS.md)](docs/06_INDUSTRY_TRENDS.md)
* Software Defined Vehicle (SDV) 等の最新トレンドとの比較。
* クラウドネイティブ組み込み開発における本アプローチの優位性と意義。

### 🤖 [7. AI エージェント操作ガイド (07_AI_AGENT_OPERATIONS.md)](docs/07_AI_AGENT_OPERATIONS.md)
* VSCode Free 上で AI がビルド、デプロイ、実行、仮想 H/W 操作、ログ確認を行うための Make ターゲット。
* `panel-button` / `panel-rfid` / `sim-logs` など、ブラウザ操作を AI が実行しやすいコマンドとして定義。

---

## クイックスタート概要

### EC2（シミュレーション）

```powershell
# Windows
C:\VibeCode\ec2.ps1 start                       # EC2 起動
```
```bash
# Codespaces
cd /workspaces/AgentCockpit
make cross                                       # ビルド (aarch64)
make deploy-ec2 EC2=vibecode-graviton            # scp で転送
make sim-start EC2=vibecode-graviton              # bridge / CUSE / app を起動
make panel-button EC2=vibecode-graviton LINE=17   # 仮想ボタン操作
make panel-rfid EC2=vibecode-graviton             # 仮想RFIDタップ
make sim-test EC2=vibecode-graviton               # 代表シナリオ実行
make sim-logs EC2=vibecode-graviton               # ログ確認
```
```bash
# EC2 (3 つのターミナル)
~/venv/bin/python3 ~/web-bridge/bridge.py        # Web ブリッジ
sudo ~/cuse_i2c -f --devname=i2c-1               # CUSE I2C スタブ
LD_PRELOAD="~/gpio_shim.so ~/spi_shim.so" ~/sensor_demo
```
Antigravity から EC2 に Remote SSH → PORTS タブで 8080 を Simple Browser で開く。

### RasPi5（実機）

```powershell
# Windows
C:\VibeCode\raspi.ps1 deploy                     # Codespaces → Windows → adb push
adb shell
```
```bash
# RasPi5 (adb shell 内)
~/sensor_demo                                    # LD_PRELOAD 不要、実 H/W を直接制御
```

---

## 主要バイナリ

| ファイル | 用途 | EC2 | RasPi5 |
|---|---|---|---|
| `sensor_demo` | 統合デモアプリ（GPIO + I2C OLED + SPI RFID） | ✅（シム経由） | ✅（実機） |
| `gpio_led_button` | GPIO 単機能デモ | ✅ | ✅ |
| `vl53l0x_read` | I2C 距離センサーテスト | ✅（CUSE） | △（実機は要 init 列） |
| `cuse_i2c` | I2C CUSE スタブ（VL53L0X + SSD1306） | EC2 専用 | — |
| `gpio_shim.so` | GPIO LD_PRELOAD シム | EC2 専用 | — |
| `spi_shim.so` | SPI LD_PRELOAD シム（MFRC-522 sim） | EC2 専用 | — |
