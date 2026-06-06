# AgentCockpit

**AI が切れ目なく最後まで開発し切るコックピット。**

AgentCockpit は、AI がコーディング、VM 試験、実機試験を切れ目なく実行するための環境定義と、AI と開発者が使用するツールコマンド群です。
AgentCockpit 内で AI はコーディング環境、VM、実機のすべてに同時にアクセスできるため、開発フェーズを切り替えても文脈が維持されます。これにより開発者の指示や作業が最小化されます。

現在の実証対象は組み込み Linux (arm64) 開発です。VM 環境には EC2 Graviton を採用し、実機環境には RasPi5 を採用しています。
EC2 Graviton には runtime として仮想 GPIO/I2C/SPI を用意し、製品ソースコード内の `#ifdef SIMULATION` や専用 HAL を不要としています。
EC2 Graviton の ISA は RasPi5 と同じ arm64 のため、VM 試験で動作確認した実行ファイルを実機にそのまま流し込めます。

この VM と実機の間のバイナリ透過性は、複雑、多種、低採算の周辺 runtime の作成と保守を、AI の生産性を用いてやりきることで実現しています。

現在は I2C/SPI を CUSE、GPIO を `gpio-sim` + Linux GPIO chardev v2 で実現しています。EC2 でも RasPi5 でもアプリは `~/sensor_demo` を直接起動し、差し替えの責務はアプリではなく AgentCockpit runtime に閉じ込めます。

<p align="center">
  <img src="docs/images/agentcockpit.svg" alt="AgentCockpit concept diagram" width="900">
</p>

## 読者別の入口

| あなたが… | まず読む | 次に読む |
|---|---|---|
| **このプロジェクトを初めて知る** | [01 アーキテクチャ](docs/01_ARCHITECTURE.md)、[06 技術的価値](docs/06_INDUSTRY_TRENDS.md) | [05 PoC 成果](docs/05_RESULTS.md) |
| **実際に動かしたい開発者** | 下記「クイックスタート」、[15 0 から実機動作まで](docs/15_ZERO_TO_TARGET_TUTORIAL.md) | [02 ワークフロー](docs/02_WORKFLOW.md)、[03 シミュレーション設定](docs/03_SIMULATION_SETUP.md)、[11 コマンド早見表](docs/11_COMMAND_REFERENCE.md) |
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
* [15 0 から実機動作までのチュートリアル](docs/15_ZERO_TO_TARGET_TUTORIAL.md) — WSL Hub 初期化から Codespace build、EC2 simulation、RasPi5 実機実行までの一本道。

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
make start                                     # サブシェルを起動し自動的に venv と bash 補完を有効化する
# --- ここからは venv 環境 (make start 実行後のシェル) で実行 ---
agp setup                                      # EC2 既定 host も .agp/config.json に保存
```

### シミュレーション実行フロー

#### WSL2: simulation host を起動

```bash
agp sim boot                                    # simulation VM 起動
```

#### Codespace build VM: ARM64 成果物をビルド

```bash
cd /workspaces/agp-build-env
bash scripts/post-create.sh
# target software ごとの README / build script に従ってビルド
```

#### WSL hub: deploy と simulation runtime 操作

```bash
cd ~/Yurufuwa/AgentCockpit
agp sim env deploy                                      # app/test binaries + simulation runtime を runtime host へ配置
agp sim env start                                      # /dev/* runtime 起動 + terminal profile + port forward
agp sim ui button press 17                            # 仮想ボタン操作
agp sim ui rfid tap 04:AB:CD:EF:01:23                 # 仮想RFIDタップ
agp sim env status --json                               # 仮想 H/W 状態確認
agp sim env log              # ログ確認
```

#### EC2: アプリ本体を起動

```bash
# agp sim env start が /dev/* runtime を用意した後
~/sensor_demo                                    # 本番と同じアプリ起動手順
```

手動で runtime を起動する場合だけ、EC2 上で次を実行します。

```bash
~/venv/bin/python3 ~/web-bridge/bridge.py        # Web ブリッジ
sudo ~/cuse_i2c -f --devname=i2c-1               # CUSE I2C スタブ
sudo ~/cuse_spi -f --devname=spidev0.0           # CUSE SPI スタブ
```
Antigravity から EC2 に Remote SSH → PORTS タブで 8080 を Simple Browser で開く。

### RasPi5（実機）

```powershell
# Windows (USB / adb 経路)
agp target sync                                  # Codespace から取得して sensor_demo を adb push
adb shell
```

adb 実機が WSL2 に見えていない場合、`agp target sync` / `agp target deploy` は `agp usb attach` 相当を自動で先行実行します。

```bash
# RasPi5 (adb shell 内)
~/sensor_demo                                    # 追加環境変数不要、実 H/W を直接制御
```

ネットワーク越しに RasPi5 へ到達できる環境では、`agp setup` で device プロバイダに `SSH / scp` を選択し、scp 経路で配送できます。

```powershell
# Windows / Linux (SSH / scp 経路)
agp target sync --host raspi5                    # Codespace から取得して scp 配送
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
長期: agp sim run <target> と agp target run <target> が同じ manifest を読む
```

この方針により、実機検証が始まった後もシミュレーション環境の起動手順が腐りにくくなります。人間が継続保守しにくい `/dev/*` 互換 runtime の実装と追従を AI が担うことが、AgentCockpit の主要な狙いです。
