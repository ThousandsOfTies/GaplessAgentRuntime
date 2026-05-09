# ExperimentalDevEnv

組み込みソフトウェア開発の「完全クラウド化」と「シームレスな実機デプロイ」を実現するためのPoC（概念実証）サンドボックスです。

このリポジトリは、**「実機がなくてもクラウド上でハードウェア込みのテストができ、実機が手に入った際も同じバイナリをそのまま流し込める」**という開発体験を目指して設計されています。

## ドキュメント ナビゲーション

### 📖 [1. アーキテクチャコンセプト (01_ARCHITECTURE.md)](docs/01_ARCHITECTURE.md)
* なぜ「クラウド化」なのか？
* Codespaces (ビルド) + EC2 Graviton (シミュレーション) + SSH/scp (デプロイ) の全体像と設計思想。

### 🔄 [2. 開発ワークフローとシーケンス (02_WORKFLOW.md)](docs/02_WORKFLOW.md)
* 開発者がコードを書いてから、シミュレータや実機で動かすまでの具体的なシーケンス図。
* コマンドリファレンス。

### 🛠️ [3. ハードウェアシミュレーション設定 (03_SIMULATION_SETUP.md)](docs/03_SIMULATION_SETUP.md)
* `cuse-stubs` を用いたI2C/GPIOスタブの仕組み。
* EC2上でのWebブリッジ起動方法と、Antigravity（ブラウザ）でのVirtual Hardware Panelの使い方。

### 🔌 [4. 実機の配線 (04_HARDWARE_WIRING.md)](docs/04_HARDWARE_WIRING.md)
* RasPi5 とブレッドボードを使った LED / ボタン / I2C / SPI モジュールの配線図。

---

## クイックスタート概要

1. **Codespaces (x86_64) で開発・クロスコンパイル**
   ```bash
   cd cuse-stubs && make cross
   ```

2. **EC2 / RasPi5 へデプロイ**
   ```bash
   # EC2 へ
   make deploy EC2=vibecode-graviton

   # RasPi5 へ
   make deploy EC2=pi@raspberrypi KEY=~/.ssh/raspi.pem
   ```

3. **SSH でシェルに入って実行**
   ```bash
   ssh vibecode-graviton
   LD_PRELOAD=~/gpio_shim.so ~/gpio_led_button
   ```
