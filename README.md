# AgentCockpit

**AI が最後まで動かせる開発コックピット。**

AgentCockpit は、開発者が手順を覚えて個別に操作する環境ではなく、**VSCode Free 上で AI への指示、AI の作業、ビルド、デプロイ、仮想 H/W 操作、ログ観察、シミュレータ UI、実機検証までを一貫して扱うための環境定義**です。

現在の実証対象は組み込み Linux 開発です。EC2 Graviton 上に仮想 GPIO/I2C/SPI を用意し、RasPi5 実機と同じ ARM64 バイナリを動かします。これにより、AI は実機がなくてもハードウェア込みの検証を進められ、実機が手に入った際も同じバイナリをそのまま流し込めます。

このプロジェクトの中心的な価値は、製品コードそのものではないため人手では採算が合いにくく、放置すると腐りやすい周辺 runtime を、AI がプロジェクト専用に作り切る点にあります。実機用アプリに `#ifdef SIMULATION` や専用 HAL を持ち込まず、OS/device layer 側で `/dev/*` 互換の仮想デバイスを用意することで、実機とシミュレーションの起動定義をできるだけ共通化します。

現在は I2C/SPI を CUSE、GPIO を `gpio-sim` + Linux GPIO chardev v2 で実現しています。EC2 でも RasPi5 でもアプリは `~/sensor_demo` を直接起動し、差し替えの責務はアプリではなく AgentCockpit runtime に閉じ込めます。

> 旧リポジトリ名は `ExperimentalDevEnv` です。

## 読者別の入口

| あなたが… | まず読む | 次に読む |
|---|---|---|
| **このプロジェクトを初めて知る** | [01 アーキテクチャ](docs/01_ARCHITECTURE.md)、[06 技術的価値](docs/06_INDUSTRY_TRENDS.md) | [05 PoC 成果](docs/05_RESULTS.md) |
| **実際に動かしたい開発者** | 下記「クイックスタート」、[02 ワークフロー](docs/02_WORKFLOW.md) | [03 シミュレーション設定](docs/03_SIMULATION_SETUP.md)、[11 コマンド早見表](docs/11_COMMAND_REFERENCE.md) |
| **作業する AI エージェント** | [AGENT.md](AGENT.md)、[07 操作ガイド](docs/07_AI_AGENT_OPERATIONS.md) | [10 協業ルール](docs/10_AGENT_COLLABORATION_RULES.md)、[11 コマンド早見表](docs/11_COMMAND_REFERENCE.md) |
| **実機で組みたい** | [04 ハードウェア配線](docs/04_HARDWARE_WIRING.md) | [05 PoC 成果](docs/05_RESULTS.md) |

## ドキュメント一覧

### A. 全体像を知る（概念）
* [01 アーキテクチャ](docs/01_ARCHITECTURE.md) — Human Intent → AI Agent → Cloud/Device の役割分担と、5 つのコアアーキテクチャ。
* [06 業界動向と技術的価値](docs/06_INDUSTRY_TRENDS.md) — SOAFEE / SDV 等のトレンドとの比較。なぜこの構成が優れているのか。
* [05 PoC 成果まとめ](docs/05_RESULTS.md) — EC2 フルシミュレーションと RasPi5 実機の動作確認結果、得られた知見、残タスク。

### B. 動かす・運用する（実務）
* [02 開発ワークフロー](docs/02_WORKFLOW.md) — 指示からデプロイ・実行までの全体シーケンス図。
* [03 シミュレーション設定](docs/03_SIMULATION_SETUP.md) — EC2 上の device compatibility runtime と Virtual Hardware Panel の起動・使い方。
* [04 ハードウェア配線](docs/04_HARDWARE_WIRING.md) — RasPi5 + ブレッドボードの LED / ボタン / I2C / SPI 配線図。
* [07 AI エージェント操作ガイド](docs/07_AI_AGENT_OPERATIONS.md) — AI がビルド・デプロイ・仮想 H/W 操作・ログ確認を行うための入口（`agp sim` / Make / HTTP API）。
* [11 コマンド / スクリプト早見表](docs/11_COMMAND_REFERENCE.md) — `agp` コマンド・Make ターゲット・補助スクリプトの**唯一の正本**。どこで実行し何をするかの一覧。

### C. 環境と協業のルール
* [08 開発環境方針メモ](docs/08_DEVELOPMENT_ENVIRONMENT_POLICY.md) — WSL2 / Codespaces / devcontainer / Windows ネイティブの役割分担。
* [09 Agent Terminal Bridge 設計メモ](docs/09_AGENT_TERMINAL_BRIDGE.md) — AI と VSCode terminal をつなぐ bridge の設計（仕組み側）。
* [10 AI / Human 協業ルール](docs/10_AGENT_COLLABORATION_RULES.md) — 裏作業と sudo/auth handoff の運用ルール（振る舞い側）。

### D. 設計・将来計画
* [12 旧 shim → CUSE/gpio-sim 移行記録](docs/12_CUSE_MIGRATION_PLAN.md) — GPIO/SPI を fake `/dev/*` runtime へ寄せた設計と確認結果。

---

## クイックスタート概要

### 初回セットアップ

```bash
make init
make start                                     # サブシェルを起動し自動的に venv を有効化する
# --- ここからは venv 環境 (make start 実行後のシェル) で実行 ---
agp setup                                      # EC2 既定 host も .agp/config.json に保存
```

### EC2（シミュレーション）

```bash
# WSL2
agp ec2 start                                   # EC2 起動
```
```bash
# Codespace build VM
cd /workspaces/agp-build-env
bash scripts/post-create.sh
# target software ごとの README / build script に従ってビルド
```
```bash
# WSL hub
cd ~/Yurufuwa/AgentCockpit
agp sim deploy                                      # app/test binaries + simulation runtime を runtime host へ配置
agp sim start                                      # /dev/* runtime 起動 + terminal profile + port forward
agp sim button press 17                            # 仮想ボタン操作
agp sim rfid tap 04:AB:CD:EF:01:23                 # 仮想RFIDタップ
make sim-test EC2=vibecode-graviton                # 代表シナリオ実行
agp sim log              # ログ確認
```
```bash
# EC2 (agp sim start が /dev/* runtime を用意した後)
~/venv/bin/python3 ~/web-bridge/bridge.py        # Web ブリッジ
sudo ~/cuse_i2c -f --devname=i2c-1               # CUSE I2C スタブ
sudo ~/cuse_spi -f --devname=spidev0.0           # CUSE SPI スタブ
~/sensor_demo                                    # 本番と同じアプリ起動手順
```
Antigravity から EC2 に Remote SSH → PORTS タブで 8080 を Simple Browser で開く。

### RasPi5（実機）

```powershell
# Windows (USB / adb 経路)
agp native deploy                                # sensor_demo を adb push
adb shell
```
```bash
# RasPi5 (adb shell 内)
~/sensor_demo                                    # 追加環境変数不要、実 H/W を直接制御
```

ネットワーク越しに RasPi5 へ到達できる環境では、`agp setup` で device プロバイダに `SSH / scp` を選択し、scp 経路で配送できます。

```powershell
# Windows / Linux (SSH / scp 経路)
agp native deploy --host raspi5                  # ~/.ssh/config の Host エントリ名
ssh raspi5 ~/sensor_demo
```

詳細なコマンド一覧は [docs/11_COMMAND_REFERENCE.md](docs/11_COMMAND_REFERENCE.md) を参照してください。

---

## 主要バイナリ

| ファイル | 用途 | EC2 | RasPi5 |
|---|---|---|---|
| `sensor_demo` | 統合デモアプリ（GPIO + I2C OLED + SPI RFID） | ✅（runtime 経由） | ✅（実機） |
| `gpio_led_button` | GPIO 単機能デモ | ✅ | ✅ |
| `vl53l0x_read` | I2C 距離センサーテスト | ✅（CUSE） | △（実機は要 init 列） |
| `cuse_i2c` | I2C CUSE スタブ（VL53L0X + SSD1306） | EC2 専用 | — |
| `cuse_spi` | SPI CUSE スタブ（MFRC-522 sim） | EC2 専用 | — |
| `gpio-sim` | kernel GPIO simulator（`/dev/gpiochip0` 提供） | EC2 専用 | — |

## 設計の方向性

旧 shim は PoC 初期の足場として役割を終えました。現在の simulation runtime は `/dev/i2c-1`、`/dev/spidev0.0`、`/dev/gpiochip0` を EC2 側で用意し、アプリ起動コマンドは実機と同じ `~/sensor_demo` です。移行の経緯と判断材料は [docs/12_CUSE_MIGRATION_PLAN.md](docs/12_CUSE_MIGRATION_PLAN.md) に残しています。

```text
現在: I2C/SPI = CUSE, GPIO = gpio-sim + GPIO chardev v2
長期: agp sim run <target> と agp native run <target> が同じ manifest を読む
```

この方針により、実機検証が始まった後もシミュレーション環境の起動手順が腐りにくくなります。人間が継続保守しにくい `/dev/*` 互換 runtime の実装と追従を AI が担うことが、AgentCockpit の主要な狙いです。
