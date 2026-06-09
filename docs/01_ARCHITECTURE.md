# Gapless Agent Runtime アーキテクチャ

Gapless Agent Runtime は、**「人間の意図」と「実装・実行・実機操作」の間で AI エージェントが動く**ための開発環境です。

従来の開発環境は、人間が IDE、ターミナル、SSH、実機、ログ、ブラウザパネルを行き来して操作することを前提にしています。Gapless Agent Runtime では、人間は「何を実現したいか」を伝えるだけで、AIがすべての作業を自動で実施し目的を達成することができる環境を目指します。

現在のPoCでは、組み込みLinux開発を題材に、**AI がビルド、デプロイ、仮想H/W操作、ログ観察、実機デプロイまで進められること**を実証しています。

さらに重要なのは、実機シミュレーションの中でも「製品そのものではないが、壊れると開発全体が止まる周辺 runtime」を AI が作り切る点です。従来は、GPIO/SPI/I2C の ioctl 互換や仮想デバイスの保守は人手では費用対効果が合わず、実機検証が始まるとシミュレーション環境が放置されがちでした。Gapless Agent Runtime では、この人間が維持しにくい層を AI の継続的な作業対象にします。

これを実現するために、以下の5つのコア・アーキテクチャを採用しています。

---

## 1. 統合開発環境

Gapless Agent Runtimeでは、VSCodeを、開発者と AI エージェントが共有する統合開発環境として使用します。

ここにすべての情報と操作インタフェースを集約することで**AI が開発作業の最初から最後までを自分で実行できる状態**を実現します。

役割分担は次のように変わります。

| 役割 | Before: 従来の開発環境 | After: Gapless Agent Runtime |
|---|---|---|
| 人間 | SSH接続、データ入力、実機/シミュレータ操作、ログ収集、結果確認、次の手順判断 | AI Agentへの指示、結果の確認、判断 |
| AI Agent | ソフトウェア作成、部分的なコード修正支援 | ソフトウェア作成、SSH接続、デプロイ、データ入力、仮想H/W操作、ログ収集、診断、結果整理 |

この役割変更を実現するために、Gapless Agent Runtime では Make ターゲット、HTTP API、ログ、状態取得を整備し、ビルド、デプロイ、シミュレータ起動、仮想ボタン押下、RFID タップ、ログ確認、診断までを AI が実行できる形にします。

---

## 2. クラウド開発環境 (GitHub Codespaces)

Gapless Agent Runtime では、開発環境として GitHub Codespaces を採用しています。

Codespaces により、ローカルPCのOSやインストール済みツールに依存せず、セットアップ済みの開発環境を瞬時に起動できます。開発環境を IaC 的に定義しておくことで、チームメンバ全員に同じ依存関係、同じツールチェーン、同じコマンド体系を提供できます。

Gapless Agent Runtime では、その標準化された作業場に AI Agent も参加します。AI は人間のローカルPC固有の環境に依存せず、チームで共有された開発環境の中でビルド、デプロイ、実行、観察を行います。

---

## 3. シミュレーション環境 (AWS EC2 Graviton)

Gapless Agent Runtime では、シミュレーション環境としてAWS EC2 Gravitonインスタンスを利用します。

EC2 Gravitonは実機（Raspberry Pi 5など）と同じ **ARM64 (aarch64)** アーキテクチャであるため、バイナリファイル自体の動作保証を実現します。

GPIOやI2Cなどの物理デバイスが存在しない環境でハードウェアをエミュレートするため、`CUSE`（Character device in Userspace）と Linux 標準の `gpio-sim` を用いて `/dev/*` 互換 runtime を構成します。

この構成では、アプリケーションやアプリ起動スクリプトにシミュレーション固有の差し替え機構を持たせず、EC2 でも RasPi5 でも同じバイナリ、同じ `/dev/*` 前提で動かします。

* **Virtual Hardware Panel**: エミュレートされたハードウェアの挙動（LEDの点灯、ボタンの押下、センサー値の変化）は、WebSocket経由でブラウザ上のパネルに同期され、視覚的にテストが可能です。
* **共通の仮想H/W操作層**: Virtual Hardware Panel は WebSocket、AI/CI は HTTP API から操作できますが、どちらも bridge 内の同じ仮想H/W操作ロジックを通ります。UI変更やAPI追加によるメンテ漏れを防ぎつつ、`/api/button/press`、`/api/rfid/tap`、`/api/state` などで機械的な操作・観察も可能にします。
* **シナリオ自動試験**: 仮想ボタン押下、RFIDタップ、センサー値変更、状態確認を JSON シナリオとして定義し、AI や CI が同じ手順を再現可能なテストとして実行できます。

---

## 4. AI-Native Device Compatibility Runtime

Gapless Agent Runtime の狙いは、アプリ側に `#ifdef SIMULATION` やシミュレーション専用 HAL を持たせることではありません。アプリは実機と同じ `/dev/i2c-1`、`/dev/spidev0.0`、`/dev/gpiochip0` を開くだけにし、差し替えの責務を OS/device layer に閉じ込めます。

現在の PoC では次の構成になっています。

| I/F | 現在の simulation runtime | アプリから見えるもの |
|---|---|---|
| I2C | CUSE で `/dev/i2c-1` を生成 | 実機と同じ i2c-dev |
| SPI | CUSE で `/dev/spidev0.0` を生成 | 実機と同じ spidev |
| GPIO | `gpio-sim` を `/dev/gpiochip0` として提供 | 実機と同じ GPIO chardev v2 |

移行の経緯は [12_CUSE_MIGRATION_PLAN.md](12_CUSE_MIGRATION_PLAN.md)、この層を AI に任せる狙いは [06_INDUSTRY_TRENDS.md](06_INDUSTRY_TRENDS.md) にまとめています。

---

## 5. 実機接続環境

Gapless Agent Runtime では、AI が実機へ到達するための接続経路として **adb（既定）** と **SSH/scp（オプション）** を想定します。どちらか一方を選択して使う方針で、両方を同時に使うことは想定しません。

既定は USB-C を用いた adb です。社内ネットワークなどで作業 PC が複数の NIC を自由に使えない環境でも、USB ケーブル一本で実機にアクセスできるためです（[scripts/gar_lib/environments/registry/device/adb_usb.py](../scripts/gar_lib/environments/registry/device/adb_usb.py)）。

ネットワーク越しに実機へ到達できる環境では、SSH/scp 経路も選択できます（[scripts/gar_lib/environments/registry/device/ssh_scp.py](../scripts/gar_lib/environments/registry/device/ssh_scp.py)）。`gar setup` の実機環境カテゴリで `SSH / scp` を選ぶと、`gar target deploy --host <ssh-host>` が `scp` と `ssh chmod` で artifact を転送します。adb / SSH の切り替えは `.gar/config.json` の `selected_providers.device` に保存されるため、AI も人間も同じ設定で動作します。
