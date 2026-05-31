# AgentCockpit

**AI が最後まで動かせる開発コックピット。**

AgentCockpit は、開発者が手順を覚えて個別に操作する環境ではなく、**VSCode Free 上で AI への指示、AI の作業、ビルド、デプロイ、仮想 H/W 操作、ログ観察、シミュレータ UI、実機検証までを一貫して扱うための環境定義**です。

現在の実証対象は組み込み Linux 開発です。EC2 Graviton 上に仮想 GPIO/I2C/SPI を用意し、RasPi5 実機と同じ ARM64 バイナリを動かします。これにより、AI は実機がなくてもハードウェア込みの検証を進められ、実機が手に入った際も同じバイナリをそのまま流し込めます。

このプロジェクトの中心的な価値は、製品コードそのものではないため人手では採算が合いにくく、放置すると腐りやすい周辺 runtime を、AI がプロジェクト専用に作り切る点にあります。実機用アプリに `#ifdef SIMULATION` や専用 HAL を持ち込まず、OS/device layer 側で `/dev/*` 互換の仮想デバイスを用意することで、実機とシミュレーションの起動定義をできるだけ共通化します。

現状は I2C を CUSE、GPIO/SPI を LD_PRELOAD shim で実現しています。これは最終形ではなく、AI が `strace` や既存 shim を材料に GPIO/SPI も CUSE/fake device runtime へ寄せていくための段階的な足場です。目標は、EC2 でも RasPi5 でもアプリ起動を `~/sensor_demo` に近づけ、差し替えの責務をアプリではなく AgentCockpit runtime に閉じ込めることです。

> 旧リポジトリ名は `ExperimentalDevEnv` です。

## ドキュメント ナビゲーション

### 📖 [1. アーキテクチャコンセプト (01_ARCHITECTURE.md)](docs/01_ARCHITECTURE.md)
* なぜ「AI が働きやすい環境定義」なのか？
* Human Intent → AI Agent → Cloud/Device という役割分担と、Codespaces + EC2 Graviton + RasPi5 の全体像。

### 🔄 [2. 開発ワークフローとシーケンス (02_WORKFLOW.md)](docs/02_WORKFLOW.md)
* 人間が AI に指示してから、AI がシミュレータや実機で動かすまでの具体的なシーケンス図。
* コマンドリファレンス。

### 🛠️ [3. ハードウェアシミュレーション設定 (03_SIMULATION_SETUP.md)](docs/03_SIMULATION_SETUP.md)
* 現状の CUSE + LD_PRELOAD runtime と、今後 CUSE/fake device へ寄せる設計方針。
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
* `panel-button` / `panel-rfid` / `agp sim log` など、ブラウザ操作や EC2 runtime 観察を AI が実行しやすいコマンドとして定義。

### 🧭 [8. 開発環境方針メモ (08_DEVELOPMENT_ENVIRONMENT_POLICY.md)](docs/08_DEVELOPMENT_ENVIRONMENT_POLICY.md)
* WSL2、Codespaces、devcontainer、Windows ネイティブの役割分担。
* ビルド負荷の分離、環境一致性、Linux 前提スクリプトを優先する判断メモ。

### 🖥️ [9. Agent Terminal Bridge 設計メモ (09_AGENT_TERMINAL_BRIDGE.md)](docs/09_AGENT_TERMINAL_BRIDGE.md)
* AI と VSCode integrated terminal をつなぐための VSCode extension / MCP server 方針。
* sudo password や認証入力を人間の見える terminal に残すための bridge 設計。

### 🤝 [10. AI / Human Collaboration Rules (10_AGENT_COLLABORATION_RULES.md)](docs/10_AGENT_COLLABORATION_RULES.md)
* AI は通常作業を裏で進め、sudo/auth など人間入力が必要な時だけ visible terminal に handoff する。
* password や token を AI に渡さず、状態確認で復帰するための運用ルール。

### 🧰 [11. コマンド / スクリプト早見表 (11_COMMAND_REFERENCE.md)](docs/11_COMMAND_REFERENCE.md)
* WSL ハブ、Codespace build VM、EC2 simulation runtime で使う `agp` コマンド、Make ターゲット、補助スクリプトの一覧。
* どこで実行し、何をセットアップ/起動/操作するのかを表で確認するためのリファレンス。

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

```powershell
# Windows
C:\VibeCode\ec2.ps1 start                       # EC2 起動
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
# VS Code terminal profile "EC2 Simulation" から EC2 へ入り、本番と同じ起動手順を実行
./start.sh
make panel-button EC2=vibecode-graviton LINE=17   # 仮想ボタン操作
make panel-rfid EC2=vibecode-graviton             # 仮想RFIDタップ
make sim-test EC2=vibecode-graviton               # 代表シナリオ実行
agp sim log              # ログ確認
```
```bash
# EC2 (agp sim start が /dev/* runtime を用意した後)
~/venv/bin/python3 ~/web-bridge/bridge.py        # Web ブリッジ
sudo ~/cuse_i2c -f --devname=i2c-1               # CUSE I2C スタブ
./start.sh                                      # 本番と同じアプリ起動手順
```
Antigravity から EC2 に Remote SSH → PORTS タブで 8080 を Simple Browser で開く。

### RasPi5（実機）

```powershell
# Windows
agp native deploy                                # sensor_demo を adb push
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

## 設計の方向性

現状の `LD_PRELOAD` は、PoC を短期間で成立させるための有効な足場です。ただし、長期的な目標は「アプリ起動スクリプトにシミュレーション固有の指定を混ぜない」ことです。

```text
短期: I2C = CUSE, GPIO/SPI = LD_PRELOAD
中期: I2C/SPI/GPIO = CUSE または fake device runtime
長期: agp sim run <target> と agp native run <target> が同じ manifest を読む
```

この方針により、実機検証が始まった後もシミュレーション環境の起動手順が腐りにくくなります。人間が継続保守しにくい `/dev/*` 互換 runtime の実装と追従を AI が担うことが、AgentCockpit の主要な狙いです。
