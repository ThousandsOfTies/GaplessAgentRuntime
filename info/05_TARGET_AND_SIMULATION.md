# 組み込みターゲットとシミュレーション方式 / GAR の現在地と差別化

本書は、Gapless Agent Runtime (GAR) が対象とする組み込みターゲットと、その
シミュレーション（実機なし実行）方式を整理し、GAR の **コア機能・現在の実装
カバレッジ・差別化ポイント** を一枚にまとめたものである。

関連: [01_INDUSTRY_TRENDS.md](01_INDUSTRY_TRENDS.md)（Graviton 環境パリティ / 互換 runtime の AI 維持）、
[02_DESIGN_PHILOSOPHY.md](02_DESIGN_PHILOSOPHY.md)、[03_FUTURE_VISION.md](03_FUTURE_VISION.md)。

---

## 0. 結論サマリ

- **GAR のコア = シミュレータではなく「接続先(provider)の抽象化 + コマンド実行 + ファイル運搬 + 端末ブリッジ + `--json`」** という *接続と運搬の統一層*。シミュレーション機能はその上に乗る応用。
- **市場観**: 出荷「個数」は MCU が当面圧勝。だが **ソフトの価値・複雑性・AI が触る価値の総量は組み込み Linux が急成長**。ツールビジネスは個数でなく価値に追従するため、**GAR は価値側（Linux エッジ）を主戦場に取る**。
- **GAR が今・強い**: Linux 系エッジの shift-left（**EC2 Graviton = 同 aarch64 実機 → Raspberry Pi 5 = HIL**）。エミュ不要で実速・高忠実。
- **GAR のフロンティア**: MCU/RTOS の CPU エミュ統合（ESP-IDF linux target / STM32・Pico の Renode など）。現状ほぼ未配線。
- **差別化の核**: 組み込みは **Linux + RTOS の 2CPU（AMP）構成が多く、不具合はコア間の境界(IPC)に集中**する。**両コア + コア間 IPC を「1 本の統一 trace」で観測・shift-left する**ことが GAR 独自のポジション。

---

## 1. シミュレーションの 3 バックエンド

ターゲットの性質（arch / OS / RTOS）に応じて、実機なし実行は次の 3 つに落ちる。
GAR の役割は「ターゲットの capability を見て、この 3 つの最適解へ割り振る」こと。

| 方式 | 何を動かすか | 速度 | 可観測性 | 忠実度 | ソース要否 | 代表 |
|---|---|---|---|---|---|---|
| **① host-native 再ビルド / 同アーキ実機** | ソース（再ビルド） or 同 arch バイナリ | ◎ | ◎(gdb/asan) | △〜◎ | 要(再ビルド時) | FreeRTOS-POSIX, Zephyr native_sim, **EC2 Graviton(aarch64)** |
| **② CPU エミュレーション** | 実機バイナリ（命令を物まね） | △ | △ | ○ | 不要 | QEMU, **Renode** |
| **③ HIL（実機ブリッジ）** | 実チップそのもの | ◎ | △(外部観測) | ◎ | 不要 | 実機 + adb/ssh/esptool（GAR の EC2+USB+CUSE） |

補足:
- **Graviton ↔ Raspi5 は「同 aarch64 Linux」なのでエミュ(②)ではなく ① 寄り**。物まねより速く忠実な、シフトレフトの理想形。
- ②の主役は **Cortex-M/RISC-V = Renode**、**AVR = simavr/QEMU**、**Xtensa(ESP32 無印)はどちらも弱く ESP-IDF linux target(①) に逃げる**。

---

## 2. 組み込みターゲット × シミュレーション方式（人気順・概算）

| 順 | ターゲット | 種別 / アーキ | 主な方式 | 具体ツール | 今すぐの実現性 |
|---|---|---|---|---|---|
| 1 | **Raspberry Pi 5** | SBC / ARM Cortex-A76 (Linux) | **①＋③** | **EC2 Graviton(同 aarch64) で実行** → 実機HIL。周辺は gpio-sim/CUSE/web-bridge | ◎(アプリ) / △(実周辺はHIL) |
| 2 | **ESP32 系** | MCU / Xtensa（C3/C6 は RISC-V） | **①本命＋②** | **ESP-IDF linux target**(FreeRTOS POSIX, 現役) / QEMU(Espressif, WIP) / Renode=× | ◎(linux target) / △(QEMU) |
| 3 | **Raspberry Pi Pico** | MCU / RP2040・RP2350 | **②CPUエミュ** | RP2040: `matgla/Renode_RP2040`(MIT・本格的だが "Frozen"・Renode 1.16.1限定) / **RP2350=既製モデル無し** | △(RP2040) / ×(RP2350) |
| 4 | **STM32**（例: Blue Pill F103） | MCU / ARM Cortex-M | **②が強い＋①** | **Renode**(本体に `stm32f103.repl` 同梱=即動く) / QEMU / Zephyr native_sim(①) | ◎ |
| 5 | **Arduino (Uno/Mega)** | MCU / AVR ATmega | **②CPUエミュ** | simavr / QEMU(avr) / Wokwi(画面付き) | ◎ |
| 6 | **Nordic nRF52/53** | MCU / Cortex-M + BLE | **②＋①** | Renode(nrf52840 repl) / Zephyr native_sim / 無線は多ノード Renode | ◎(ロジック) / △(無線) |
| 7 | **Renesas RA / RL78** | MCU / Cortex-M（日本産業） | **②** | Renode(renesas repl) / 一部 QEMU | ○ |
| 8 | **NXP i.MX RT / Kinetis** | MCU / Cortex-M（産業） | **②** | Renode(imxrt/k6xf repl) | ○ |

誤解しやすい点:
- **Raspi5 だけ毛色が違う**: Linux が動く SBC なので「チップを真似る(②)」より「**同 arch のクラウド/別機で Linux アプリをそのまま動かす(①)**」が正攻法。MCU とは土俵が別。
- **RISC-V 版（ESP32-C3/C6, RP2350 の Hazard3）**は将来 Renode/QEMU が伸びる余地がある領域。

### 実測で確定した個別事実（2026-06）

- **ESP-IDF linux ターゲット**は現役・公式・更新中（"experimental" だが放棄されていない）。スケジューラは「cooperative preemption / ブロッキング API でのみ切替」。
- **Renode 本体に ESP32(Xtensa) は事実上無し**（XTENSA は `xtensa-sample-controller` のみ）。
- **Renode 本体に RP2040 / RP2350 の repl は無い**（直接 404 で確認）。RP2040 はコミュニティ製 `matgla/Renode_RP2040` で可、ただし "Frozen"。
- **Renode 本体に STM32 は手厚い**（`stm32f103.repl` ほか多数同梱）→ 追加実装ゼロで即動く。
- ローカル `embedded-poc-app/mcu-renode/sim/pico_blink.resc` は `@platforms/cpus/rp2040.repl`（本体同梱）を前提にしており、**stock Renode では動かない**。

---

## 3. GAR の現在地：できる / できない（コード実測ベース）

### コア機能（provider に依らず常にある = GAR の不変の骨格）

| 操作 | CLI | 実装 |
|---|---|---|
| 環境セットアップ（依存確認/install） | `gar setup` | ✅ |
| リモートコマンド実行 | `DevEnvironment.run_remote()` | ✅（中心） |
| ファイル運搬（push/pull） | `gar sim/target deploy` | ✅ |
| 端末ブリッジ（AI のコマンドを“見える”実行） | `gar terminal run` | ✅ |
| ハードウェア定義 CSV | `gar hw init` | ✅ |
| 機械可読出力（AI/CI 向け） | 各所 `--json` | ✅（順次拡大中） |

### Linux 系シミュレーション（実装済み・GAR の主戦場）

- `LinuxSystemdSimProvider` が実体。**systemd サービス / カーネル `gpio-sim` / CUSE(i2c・spi) / `/dev/*` / web-bridge** で実機互換の周辺を提供。
- **EC2 Graviton 上で同 aarch64 Linux バイナリを実速で動かし、Raspi5 へそのまま deploy** という shift-left が成立している。

### 現状できないこと / 未実装（フロンティア）

| 項目 | 根拠 | 影響 |
|---|---|---|
| **Sim 機能が完全に Linux/systemd 専用** | `_sim.py` が provider 選択を無視し常に `LinuxSystemdSimProvider` をハードコード | ESP32/Pico/STM32 では sim 機能が原理的に動かない |
| **Renode runtime 統合が未配線** | `simulation/renode_mcu.py`（install のみ、runtime 操作は失敗） | Cortex-M/RISC-V MCU の②エミュ |
| **Wokwi SimProvider 全面未実装** | `sim/wokwi.py` 全メソッド `NotImplementedError` | ESP32 Wokwi |
| **ESP32 USB Serial provider 完全スタブ** | `device/esp32_serial.py` | ESP32 実機シリアル |
| **STM32 / Pico 専用 provider が存在しない** | registry に無し | これらの MCU 実機 deploy/flash |

> 整理すると、3 バックエンドのうち **GAR が実装済みなのは ①(Linux sim / Graviton) と ③(adb/ssh/esp32 flash) の一部**。**②(CPU エミュ) はほぼ空白**。これが現在地である。

---

## 4. AMP（Linux + RTOS の 2CPU）こそ GAR の差別化

組み込みは **Linux アプリコア + RTOS リアルタイムコアの 2CPU（AMP）構成が多い**
（カメラ・センサ・車載・産業機器など）。AMP SoC の例: NXP i.MX8 / TI Sitara / ST MP1。

```text
┌─────────────┐   コア間 IPC          ┌─────────────┐
│ Linux 系コア  │◀───────────────────▶│ RTOS 系コア   │
│ アプリ/AI/通信 │  RPMsg / OpenAMP /    │ 実時間/センサ │
│              │  共有メモリ / mailbox  │ /電源/DSP    │
└─────────────┘                       └─────────────┘
   ▲ GAR が今強い(Graviton↔実機)         ▲ GAR のフロンティア(②エミュ)
            └──── ここの“境界”が一番バグる ────┘
```

### 境界(IPC)に集中する定番不具合

- キャッシュコヒーレンシ（A 側キャッシュ vs M 側 DMA → 古いデータ）
- 構造体パディング / アライメント / エンディアンの食い違い → サイレント破損
- 起動・リセット順序（片コア reset で取り残し / 二重初期化）
- バックプレッシャ欠如（RPMsg/共有 FIFO 溢れ → ドロップ）
- mailbox 割り込みの取りこぼしレース → デッドロック
- A-M 間のバージョン非対称（片側だけ OTA 更新）

これらは **片側だけ見ても特定不能**。今のツールは片コアずつ（gdb vs JTAG）で
“2 画面の勘”による突き合わせになっている。

### GAR の独自ポジション

- **両コア + コア間 IPC を「1 本の統一 trace」で観測**し、AMP の境界バグを
  *機械可読な 1 タイムライン* にする。これは Renode 単体 / QEMU 単体が苦手な空白。
- **AI エージェントが最も価値を出せるデバッグ領域**（人間が 2 画面で追うのが地獄）。
- shift-left も AMP 単位で成立: **Linux 側 = Graviton(実装済) / RTOS 側 = ②エミュ(フロンティア) / 境界 = co-sim + 統一 trace**。

---

## 5. ポジショニング（一言）

> **GAR = 「AMP（Linux + RTOS の 2CPU）デバイスの、両コア + コア間 IPC を統一 trace で
> 観測し shift-left する、AI 向けデバッグ基盤」**

- 個数の MCU 戦争（ばらまきセンサー、薄利・コモディティ）は追わない。
- **価値の集まる Linux エッジ / AMP 境界**を取り、その上で MCU（コンパニオンコア）を
  将来カバーする。
- ハード実時間・安全認証・コインセル超低電力は MCU/RTOS の恒久領域であり、GAR の
  主戦場ではないと割り切る。
