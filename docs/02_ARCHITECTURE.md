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

## コマンドモデル

GAR のコマンドは make の target に近い考え方に寄せる。ユーザーが入力するのは
`gar sim build` / `gar sim deploy` / `gar target build` / `gar target deploy` のような
抽象 target であり、個別の実行方法（PlatformIO、Codespaces、esptool、adb、scp など）は
`gar setup` で選ばれた target 定義と接続設定から解決する。

`deploy` は単なる転送コマンドではない。依存する artifact が無い、または古い場合は、
依存 target を再帰的にたどって必要な build / package を先に実行し、その最新 artifact を
対象 runtime へ反映する。低レベルコマンドは互換・診断用に残すが、日常操作の文法には出さない。

Codespace は build target の実行場所のひとつ。ユーザーは通常 `gar sim build` /
`gar sim deploy` / `gar target build` / `gar target deploy` から間接的に使う。
成果物は target graph の artifact node と `artifact.json` に記載されたパスで管理する。

実機操作も make 的な依存 target として扱う。

```text
target.deploy
  depends on target.artifact
  depends on target.access

target.artifact
  depends on target.build
  depends on target.config

target.build
  depends on target.sources
```

`gar setup` は、この graph の各 node が何を意味するかを保存する。たとえば ESP32/M5StickC
なら `target.access` は USB serial 接続先、`target.build` は PlatformIO/Codespaces build、
`target.deploy` は最新 firmware artifact の flash になる。RasPi/Linux device なら
`target.deploy` は adb または SSH/scp での配置になる。

---

## 1. 統合開発環境

Gapless Agent Runtimeでは、VSCodeを、開発者と AI エージェントが共有する統合開発環境として使用します。

ここにすべての情報と操作インタフェースを集約することで**AI が開発作業の最初から最後までを自分で実行できる状態**を実現します。

役割分担は次のように変わります。

| 役割 | Before: 従来の開発環境 | After: Gapless Agent Runtime |
|---|---|---|
| 人間 | SSH接続、データ入力、実機/シミュレータ操作、ログ収集、結果確認、次の手順判断 | AI Agentへの指示、結果の確認、判断 |
| AI Agent | ソフトウェア作成、部分的なコード修正支援 | ソフトウェア作成、SSH接続、デプロイ、データ入力、仮想H/W操作、ログ収集、診断、結果整理 |

この役割変更を実現するために、Gapless Agent Runtime では Make ターゲット、JSON シナリオ、ログ、状態取得を整備し、ビルド、デプロイ、シミュレータ起動、仮想 H/W 操作、ログ確認、診断までを AI が再現可能な手順として実行できる形にします。

---

## 2. クラウド開発環境 (GitHub Codespaces)

Gapless Agent Runtime では、開発環境として GitHub Codespaces を採用しています。

Codespaces により、ローカルPCのOSやインストール済みツールに依存せず、セットアップ済みの開発環境を瞬時に起動できます。開発環境を IaC 的に定義しておくことで、チームメンバ全員に同じ依存関係、同じツールチェーン、同じコマンド体系を提供できます。

Gapless Agent Runtime では、その標準化された作業場に AI Agent も参加します。AI は人間のローカルPC固有の環境に依存せず、チームで共有された開発環境の中でビルド、デプロイ、実行、観察を行います。

---

## 3. シミュレーション環境 (AWS EC2 Graviton)

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

仮想デバイスへの操作・観察は、人間の手動操作と AI / CI の再現操作で入口を分ける。

* **Virtual Hardware Panel**: LED・ボタン・RFID・センサーの状態変化を WebSocket 経由でブラウザパネルにリアルタイム表示。人間が目視で動作確認できる。
* **JSON シナリオ試験**: ボタン押下・RFID タップ・センサー値変更・状態確認を JSON シナリオとして定義し、AI や CI が同じ手順を再現可能なテストとして実行できる。
* **HTTP API（bridge）**: Linux / RasPi-compatible simulation の内部受け口。Web UI と JSON シナリオ実行系が同じ仮想 H/W 操作ロジックを通るため、UI 変更時のメンテ漏れが起きにくい。

検証入口は simulation provider ごとに分かれる。

| 対象 | 入口 |
|---|---|
| Linux Bridge 手動操作 | Virtual Hardware Panel |
| Linux Bridge シナリオ | `python scripts/run_scenario.py path/to/scenario.json` |
| Wokwi 手動確認 | VS Code Wokwi 拡張 / Diagram Editor |
| Wokwi シナリオ | `wokwi-cli --scenario button.test.yaml .` |
| ESP32 QEMU | `gar-esp32-flash-image` / `gar-esp32-qemu-run` |
| Renode | `renode` / `renode-test` |
| Vibe Remote smoke | `npm run smoke:protocol` |

具体的なセットアップ手順と確認手順は [06_SIMULATION.md](06_SIMULATION.md) を参照。

---

## 5. 実機接続環境

Gapless Agent Runtime では、AI が実機へ到達するための接続経路として **adb（既定）** と **SSH/scp（オプション）** を想定します。どちらか一方を選択して使う方針で、両方を同時に使うことは想定しません。

既定は USB-C を用いた adb です。社内ネットワークなどで作業 PC が複数の NIC を自由に使えない環境でも、USB ケーブル一本で実機にアクセスできるためです（[scripts/gar_lib/environments/registry/target/adb_usb.py](../scripts/gar_lib/environments/registry/target/adb_usb.py)）。

ネットワーク越しに実機へ到達できる環境では、SSH/scp 経路も選択できます（[scripts/gar_lib/environments/registry/target/ssh_scp.py](../scripts/gar_lib/environments/registry/target/ssh_scp.py)）。`gar setup` の実機環境カテゴリで `SSH / scp` を選ぶと、`gar target deploy --host <ssh-host>` が `scp` と `ssh chmod` で artifact を転送します。adb / SSH の切り替えは `.gar/config.json` の `selected_providers.target` に保存されるため、AI も人間も同じ設定で動作します。
