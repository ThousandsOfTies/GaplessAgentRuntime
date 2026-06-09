# Gapless Agent Runtime アーキテクチャ

システムは以下の5つのレイヤで構成される。

| レイヤ | 実体 | 役割 |
|---|---|---|
| 1. 統合開発環境 | VSCode + `gar` CLI | AI・人間が共有する操作面。ビルド/デプロイ/観察の起点 |
| 2. クラウドビルド環境 | GitHub Codespaces | ARM64 クロスビルド。ツールチェーン定義を IaC 化 |
| 3. シミュレーション環境 | AWS EC2 Graviton | 実機と同一 ARM64 バイナリを動かす仮想 H/W 実行環境 |
| 4. デバイス互換 Runtime | CUSE / gpio-sim + bridge | `/dev/i2c-*` `/dev/spidev*` `/dev/gpiochip*` を OS レベルで再現しアプリを無改造で動かす |
| 5. 実機接続環境 | RasPi5（adb / SSH） | 同一バイナリを実機で検証。接続経路は config で切り替え |

ビルド成果物は Codespaces → WSL → EC2/実機 の一方向で流れる。EC2 上でのビルドは行わない。

---

﻿## 1. 統合開発環境

Gapless Agent Runtimeでは、VSCodeを、開発者と AI エージェントが共有する統合開発環境として使用します。

ここにすべての情報と操作インタフェースを集約することで**AI が開発作業の最初から最後までを自分で実行できる状態**を実現します。

役割分担は次のように変わります。

| 役割 | Before: 従来の開発環境 | After: Gapless Agent Runtime |
|---|---|---|
| 人間 | SSH接続、データ入力、実機/シミュレータ操作、ログ収集、結果確認、次の手順判断 | AI Agentへの指示、結果の確認、判断 |
| AI Agent | ソフトウェア作成、部分的なコード修正支援 | ソフトウェア作成、SSH接続、デプロイ、データ入力、仮想H/W操作、ログ収集、診断、結果整理 |

この役割変更を実現するために、Gapless Agent Runtime では Make ターゲット、HTTP API、ログ、状態取得を整備し、ビルド、デプロイ、シミュレータ起動、仮想ボタン押下、RFID タップ、ログ確認、診断までを AI が実行できる形にします。

---

﻿## 2. クラウド開発環境 (GitHub Codespaces)

Gapless Agent Runtime では、開発環境として GitHub Codespaces を採用しています。

Codespaces により、ローカルPCのOSやインストール済みツールに依存せず、セットアップ済みの開発環境を瞬時に起動できます。開発環境を IaC 的に定義しておくことで、チームメンバ全員に同じ依存関係、同じツールチェーン、同じコマンド体系を提供できます。

Gapless Agent Runtime では、その標準化された作業場に AI Agent も参加します。AI は人間のローカルPC固有の環境に依存せず、チームで共有された開発環境の中でビルド、デプロイ、実行、観察を行います。

---

﻿## 3. シミュレーション環境 (AWS EC2 Graviton)

### VM の選定理由

シミュレーション環境には AWS EC2 Graviton（ARM64）を採用している。実機である Raspberry Pi 5 と同じ **ARM64 (aarch64)** アーキテクチャのため、Codespaces でクロスビルドした成果物をそのまま EC2 にデプロイして動かせる。x86 VM を挟んだエミュレーション実行では見えない ABI 差異やアライメント問題を早期に検出できる点も選定理由のひとつ。

---

## 4. デバイス互換 Runtime

### 仕組み：アプリを無改造で動かす

アプリ側に `#ifdef SIMULATION` やシミュレーション専用 HAL を持たせない。アプリは実機と同じ `/dev/i2c-1`、`/dev/spidev0.0`、`/dev/gpiochip0` を開くだけにし、差し替えの責務を OS/device layer に閉じ込める。

EC2 上では以下の仮想デバイスで `/dev/*` を再現する。

| I/F | 実装 | アプリから見えるもの |
|---|---|---|
| I2C | CUSE で `/dev/i2c-1` を生成 | 実機と同じ i2c-dev |
| SPI | CUSE で `/dev/spidev0.0` を生成 | 実機と同じ spidev |
| GPIO | `gpio-sim` で `/dev/gpiochip0` を提供 | 実機と同じ GPIO chardev v2 |

### バイナリ透過性

この構成により、Codespaces でビルドした同一バイナリが EC2 でも RasPi5 でも動く。CUSE/gpio-sim の実装と保守は AI が担うことで、実機検証フェーズに入ってもシミュレーション環境が陳腐化しない体制を目指す。

### 仮想 H/W の操作・観察（bridge）

仮想デバイスへの操作・観察は人間・AI・CI のいずれからも共通のインターフェースで行える。

* **Virtual Hardware Panel**: LED・ボタン・RFID・センサーの状態変化を WebSocket 経由でブラウザパネルにリアルタイム表示。人間が目視で動作確認できる。
* **HTTP API（bridge）**: Panel と同じ仮想 H/W 操作ロジックを HTTP API として公開。AI や CI は `/api/button/press`、`/api/rfid/tap`、`/api/state` などで機械的に操作・観察できる。Panel と API が同じコードパスを通るため、UI 変更時のメンテ漏れが起きにくい。
* **JSON シナリオ試験**: ボタン押下・RFID タップ・センサー値変更・状態確認を JSON シナリオとして定義し、AI や CI が同じ手順を再現可能なテストとして実行できる。

---

﻿## 5. 実機接続環境

Gapless Agent Runtime では、AI が実機へ到達するための接続経路として **adb（既定）** と **SSH/scp（オプション）** を想定します。どちらか一方を選択して使う方針で、両方を同時に使うことは想定しません。

既定は USB-C を用いた adb です。社内ネットワークなどで作業 PC が複数の NIC を自由に使えない環境でも、USB ケーブル一本で実機にアクセスできるためです（[scripts/gar_lib/environments/registry/device/adb_usb.py](../scripts/gar_lib/environments/registry/device/adb_usb.py)）。

ネットワーク越しに実機へ到達できる環境では、SSH/scp 経路も選択できます（[scripts/gar_lib/environments/registry/device/ssh_scp.py](../scripts/gar_lib/environments/registry/device/ssh_scp.py)）。`gar setup` の実機環境カテゴリで `SSH / scp` を選ぶと、`gar target deploy --host <ssh-host>` が `scp` と `ssh chmod` で artifact を転送します。adb / SSH の切り替えは `.gar/config.json` の `selected_providers.device` に保存されるため、AI も人間も同じ設定で動作します。

