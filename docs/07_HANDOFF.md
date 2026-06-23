# 引き継ぎ資料

最終更新: 2026-06-18

この資料は、Gapless Agent Runtime 周辺作業を別セッション・別エージェントへ
引き継ぐための作業メモである。運用規約の正本は
`AGENT.md`、`docs/02_ARCHITECTURE.md`、
`docs/03_DEVELOPMENT_ENVIRONMENT.md` を参照すること。

## まず守ること

- GAR 系作業では、CWD や VS Code のアクティブファイルだけで対象を判断しない。
- `/home/user/Yurufuwa` 配下には複数の sibling repo があり、GAR の運用境界は
  `GaplessAgentRuntime/` の文書を正本とする。
- AI も原則 `gar` サブコマンド経由で操作する。足りない操作は、場当たり的な生コマンドではなく
  `gar` へ足す対象として扱う。
- `sudo`、GitHub 認証、クラウド認証、デバイス pairing など人間入力が必要なものは
  visible terminal へ handoff する。password や token をチャットで要求しない。
- EC2 / RasPi5 は実行ターゲットであり、ビルド環境ではない。ビルドは Codespaces、
  制御と転送は WSL、実行は EC2 / RasPi5 に分ける。

## 関連リポジトリ

| パス | 役割 |
|---|---|
| `/home/user/Yurufuwa/GaplessAgentRuntime` | GAR の操作規約、アーキテクチャ、`gar` CLI 正本 |
| `/home/user/Yurufuwa/gar-tools` | CUSE stubs、ESP32/M5Stack firmware runner、Renode/QEMU 足場 |
| `/home/user/Yurufuwa/gar-build-env` | Codespaces/devcontainer build hub |
| `/home/user/Yurufuwa/gar-vibe-ui/vibe-remote` | VS Code extension、M5Stack Vibe Remote、Local bridge |
| `/home/user/Yurufuwa/embedded-poc-app` | ARM64 target app |

## 現在の作業テーマ

M5Stack Vibe Remote と GAR 周辺で、Ethernet/IP、Bluetooth SPP、
Renode、Codespaces build、WSL control plane の役割を整理している。

現時点の基本方針:

- 直近の対象は **M5StickC Plus2 上の Vibe Remote firmware**。
  BugC2 base / アクチュエータドック側の STM32F030F4P6 は後段の I2C peripheral として扱い、
  先にそちらの Cortex-M0 firmware boot へ寄り道しない。
- もっとも環境自由度が高い経路は IP/WebSocket。
- Bluetooth SPP は M5Stack と extension/local bridge の近距離接続には有効だが、
  WSL や Codespaces から直接扱うには環境依存が強い。
- WSL2 からの mDNS advertise は、通常の NAT 構成では物理 LAN 側に安定して出る前提にしない。
- 物理 I/O や mDNS は Windows/local 側の bridge に寄せ、WSL 上の extension/control plane へ
  WebSocket proxy する構成が汎用的。
- Renode の動作確認は WSL 側で行う。Codespaces は build 用に戻し、Renode は削除済み。

## 実施済み

### gar-vibe-ui / vibe-remote

`gar-vibe-ui/vibe-remote` に以下を追加・確認済み。

- M5Stack firmware 側に Bluetooth SPP transport を追加。
- M5StickC Plus2 向け最小 Vibe Remote firmware を追加。
  - `m5stack-client/src/minimal_vibe_remote.cpp`
  - PlatformIO env: `m5stickc-plus2-vibe-min`
  - Wi-Fi + WebSocket + `hello` / `ping` / `agentStatus` のみ。
  - Windows / Local bridge が advertise する `_vibe-remote._tcp.local` を mDNS で探索する。
  - `VIBE_REMOTE_HOST` は mDNS が使えない場合の fallback。
  - Serial Monitor から `r/w/d/f/i/p/x` で状態送信・ping・再接続を操作可能。
- VS Code extension 側に serial/SPP bridge を追加。
- Windows/local 側で動かす `scripts/local-bridge.js` を追加。
- Local bridge は `_vibe-remote._tcp.local` を advertise し、
  local LAN / SPP と WSL 側 WebSocket を中継する想定。

確認済みコマンド:

```bash
cd /home/user/Yurufuwa/gar-vibe-ui/vibe-remote
./scripts/npm.sh run compile
./scripts/npm.sh run typecheck
./scripts/npm.sh run local:bridge -- --help
timeout 2s ./scripts/npm.sh run local:bridge -- --discovery=false --listen-port=39299
```

M5StickC Plus2 最小 firmware の想定ビルド:

```bash
cd /home/user/Yurufuwa/gar-vibe-ui/vibe-remote/m5stack-client
pio run -e m5stickc-plus2-vibe-min
pio run -e m5stickc-plus2-vibe-min -t upload
pio device monitor
```

Codespaces での build/package 確認済み:

```bash
cd /workspaces/gar-build-env/repos/gar-vibe-ui/vibe-remote/m5stack-client
PATH=$HOME/.venvs/platformio/bin:$PATH make vm-package PIO_ENV=m5stickc-plus2-vibe-min
```

WSL へ取得済み artifact:

- `/home/user/Yurufuwa/gar-vibe-ui/vibe-remote/m5stack-client/artifacts/20260619-201256-m5stickc-plus2-vibe-min/`
  - `.env.local` から Wi-Fi / token を注入して Codespaces で build/package 済み。
  - `sha256sum -c SHA256SUMS` は `boot_app0.bin` / `bootloader.bin` / `firmware.bin` / `partitions.bin` すべて OK。
- `/home/user/Yurufuwa/gar-vibe-ui/vibe-remote/m5stack-client/artifacts/20260619-063145-m5stickc-plus2-vibe-min/`
- `sha256sum -c SHA256SUMS` は `boot_app0.bin` / `bootloader.bin` / `firmware.bin` / `partitions.bin` すべて OK。

実機 flash は GAR コマンド化済み:

```bash
cd /home/user/Yurufuwa/GaplessAgentRuntime
gar target flash-esp32 --port COM3
```

`COM3` は WSL 上で `/dev/ttyS3` に変換される。artifact は省略時に
`gar-vibe-ui/vibe-remote/m5stack-client/artifacts/` 配下の最新を選ぶ。
`esptool` が無い場合は `~/.local/share/gar/esptool-venv` に自動導入する。

Local bridge の利用例:

```bash
cd /home/user/Yurufuwa/gar-vibe-ui/vibe-remote
./scripts/npm.sh run local:bridge -- --listen-port=39272 --upstream-port=39271
./scripts/npm.sh run local:bridge -- --spp-port=COM5
```

M5 firmware の PlatformIO build は WSL ではなく Codespaces で確認する。
`m5stickc-plus2-vibe-min` の build/package は Codespaces で成功済み。

### gar-tools

`gar-tools` 側で Bluetooth SPP / Renode 関連の足場を追加・整理済み。

- `targets/esp32/probes/spp-jsonl/bin/gar-spp-jsonl-probe`
  - POSIX serial device 向け JSONL probe。
  - `/dev/rfcomm0` などに接続し、`hello` / `agentStatus` / `ping` を送れる。
- `targets/esp32/README.md`
  - Bluetooth SPP probe の使い方を追記。
- `targets/esp32/renode/INVENTORY.md`
  - ESP32/M5Stack Renode 対応に必要な部品棚卸しを追加。
- `targets/esp32/renode/ROADMAP.md`
  - network-or-SPP 境界と inventory 参照を追記。
- `targets/esp32/renode/m5status-tiny/`
  - Renode の `xtensa-sample-controller` と upstream Zephyr hello-world ELF を使う
    最小 firmware smoke target を追加。
  - `renode-test targets/esp32/renode/m5status-tiny/m5status-tiny.robot`
    で UART 出力を待つ Robot test が通る。

確認済みコマンド:

```bash
cd /home/user/Yurufuwa/gar-tools
python3 -m py_compile targets/esp32/probes/spp-jsonl/bin/gar-spp-jsonl-probe
targets/esp32/probes/spp-jsonl/bin/gar-spp-jsonl-probe --help
renode-test targets/esp32/renode/m5status-tiny/m5status-tiny.robot
```

### Codespaces build

Codespace `friendly-dollop-rq94rwxrxrvfwwv4` で `gar-tools` を同期して build 済み。

確認済み:

```bash
gh codespace ssh -c friendly-dollop-rq94rwxrxrvfwwv4 -- \
  'cd /workspaces/gar-build-env/repos/gar-tools && make clean && make'

gh codespace ssh -c friendly-dollop-rq94rwxrxrvfwwv4 -- \
  'cd /workspaces/gar-build-env && make artifacts'
```

取得済み artifact:

- `/home/user/Yurufuwa/gar-build-env/artifacts/from-codespace`
- `/home/user/Yurufuwa/gar-tools/artifacts/from-codespace-gar-tools/`

取得した主要 binary は ARM aarch64 ELF として確認済み。

Codespaces に一時導入した Renode は、ユーザー指示により削除済み。

### WSL Renode

Renode は WSL にインストール済み。

確認済み:

```bash
renode --version
```

結果:

```text
Renode v1.16.1.17033
build: d66b0c2a-202602160923
runtime: .NET 8.0.12
```

WSL 側の Renode 配置:

- `~/.local/bin/renode`
- `~/.local/bin/renode-test`
- `~/.local/share/gar/renode`
- `~/.local/share/gar/renode-test-venv`

WSL の Python が 3.14 系で、Renode 同梱の test requirements に含まれる
古い `psutil` がそのままでは入らなかった。venv には互換依存を手動で入れている。

確認済み Robot test:

```bash
. ~/.local/share/gar/renode-test-venv/bin/activate
cd ~/.local/share/gar/renode
renode-test tests/platforms/xtensa.robot
```

結果は pass=2 / fail=0。

まだ確認できていないこと:

- ESP32 / LX6 / M5Stack 相当 board の boot。
- M5 firmware binary を Renode 上で起動する経路。
- SPP や IP/WebSocket の simulated device と GAR/Vibe Remote を結合する経路。
- `m5status-tiny` は実行可能な firmware smoke だが、ESP32 LX6 / Arduino /
  M5Unified / 実際の Vibe Remote firmware の boot 証明ではない。

## 未完了・次の一手

1. `m5stickc-plus2-vibe-min` を PlatformIO 環境で build/upload し、
   `hello` ack、`ping` state、Serial `r/w/d/f/i` の agentStatus 反映を確認する。
2. `m5status-tiny` の upstream ELF を GAR-built tiny UART firmware
   （例: `GAR_RENODE_HELLO` を出すもの）へ置き換える。
3. ESP32 LX6 / Arduino hello の direct-load か QEMU flash image 経路との差分を確認する。
4. 起動確認できた範囲を `gar` コマンドに寄せる。
5. Vibe Remote の Local bridge を Windows 側で動かし、
   WSL extension/control plane との WebSocket proxy を実機で確認する。
6. M5Stack 実機で SPP 接続する場合は、Windows の COM port として見える経路を使う。
7. BugC2 base / アクチュエータドック連携は、M5StickC Plus2 側 Vibe Remote の boot / transport が固まった後に、
   I2C address `0x38` の peripheral stub として扱う。

## 作業時の注意

- `GaplessAgentRuntime` には既存の未コミット変更がある可能性がある。
  自分が触っていない変更は戻さない。
- `gar-tools` 側では `firmware-runners/` や `artifacts/` が未追跡として見える場合がある。
  既存状態を確認してから必要最小限だけ触る。
- Renode の install / package 追加で `sudo` が必要な場合は、Terminal Bridge の原則に従い、
  visible terminal へ handoff する。
- ユーザーの意図は「環境を GAR の役割分担に沿って整理し、後続作業を迷わせないこと」。
  個別の便利コマンドよりも、どの環境で何をするかを優先して判断する。
