# シミュレーション環境

このドキュメントでは、クラウド上（AWS EC2 Graviton）で物理ハードウェアをエミュレートする仕組みについて解説します。

Gapless Agent Runtime のシミュレーションは、EC2 側の device compatibility runtime が実機と同じ `/dev/*` を再現することで、アプリを無改造のまま動かす。差し替えの責務を OS/device layer に閉じ込めることで、アプリは実機・EC2 どちらでも同じバイナリ・同じ起動コマンドで動作します。

現在は I2C/SPI を CUSE、GPIO を `gpio-sim` + GPIO chardev v2 で実現しています。EC2 側の runtime が実機と同じ `/dev/i2c-1`、`/dev/spidev0.0`、`/dev/gpiochip0` を用意するため、アプリは `~/sensor_demo` を直接起動します。runtime の設定・実行ファイルは `/etc/gar/hardware/`、`/usr/local/sbin/`、`/usr/local/lib/gar/`、`/run/gar/` に保存し、アプリ本体だけを本番と同じユーザー領域の成果物として扱います。

I2C/SPI を CUSE、GPIO を `gpio-sim` + GPIO chardev v2 で実現するこの構成への移行は完了済みです。このアプローチがなぜ価値を持つかは [../info/01_INDUSTRY_TRENDS.md](../info/01_INDUSTRY_TRENDS.md) にまとめています。

## Bridge は simulation 共通の操作面

GAR において Bridge は、疑似操作パネル、AI agent、CI scenario が simulator を操作・観察するための共通 control plane である。Linux の `bridge.py` はその最初の実装であって、Linux 固有の補助機能ではない。

新しい provider は、次のいずれかで Bridge を実現する。

1. simulator と同じプロセスまたは近傍プロセスに HTTP/JSON Bridge を起動する。
2. provider 固有 API / CLI を、GAR の JSON command/state 契約へ変換する adapter を実装する。

人間が標準 viewer や provider 独自 UI を使うことはできるが、それは観察・手動デバッグの補助である。AI / CI が再現可能に操作する入口の代わりにはならない。例えば MuJoCo では Bridge が Python SDK を呼び、MuJoCo viewer は Bridge と同じ物理状態を表示する。

現時点で Wokwi scenario は Wokwi CLI 固有の形式を使用する移行中の例外である。これを一般原則と取り違えず、共通 JSON scenario から同じ操作を実行できるように揃える。

## 全体構成

`sensor_demo` と `bridge.py` は独立したプロセス。`sensor_demo` は標準の `/dev/*` インターフェース（ioctl / read / write）しか使わず、`bridge.py` を直接呼び出さない。

```
[EC2 arm64 (Graviton)]

  ┌─ sensor_demo (アプリケーション)
  │     │  GPIO: /dev/gpiochip0 (ioctl)        ──→ gpio-sim (kernel module)
  │     │  I2C:  /dev/i2c-1    (read/write)    ──→ cuse_i2c
  │     │  SPI:  /dev/spidev0.0 (SPI_IOC_MESSAGE) ──→ cuse_spi
  │
  │            仮想デバイス ↔ bridge.py 間は Unix socket で接続
  │
  └─ bridge.py  (/run/gar/hw_sim.sock)
        │  gpio-sim: sim_gpio17/27 pull 書き込み、sim_gpio18/24 value poll
        │  cuse_i2c: SSD1306 0x3C フレームバッファ受信、VL53L0X 0x29 距離値配信
        │  cuse_spi: MFRC-522 register 状態同期
        │
        ├─ WebSocket  ws://0.0.0.0:8765  ──→ Virtual Hardware Panel (browser)
        └─ HTTP       http://0.0.0.0:8080 (panel HTML/CSS/JS 配信)

  [VSCode Simple Browser]
    Virtual Hardware Panel
      - LED GPIO18 / GPIO24 (canvas)
      - Button GPIO17 / GPIO27
      - VL53L0X range slider
      - MFRC-522 Tap Card / Remove
      - SSD1306 OLED 128×64 canvas
```

---

## EC2 AMI 初期セットアップ

simulation host の EC2 インスタンス定義・初期 package install は Terraform で管理する。
Terraform の呼び出しは `gar sim infra` コマンド経由で行う（`terraform` を直接叩かない）。

インフラ定義:

```
infra/terraform/
  main.tf        — EC2 / Security Group / volume / SSH key の定義
  user_data.sh   — 初回起動時の bootstrap（linux-modules-extra / gpiod / strace の install）
```

### インスタンスの作成・再作成

```bash
gar sim infra setup  # 現在設定と変更内容を確認
gar sim infra apply  # インスタンスを作成・SSH config 更新
```

`gar sim infra setup` は `.gar/config.json` と Terraform output から現在値を表示したうえで、Terraform plan を実行する。
`gar sim infra apply` は apply 後に instance_id / public_ip を `.gar/config.json` へ保存し、`~/.ssh/config` の HostName を自動更新する（`gar sim start` 相当の後処理も含む）。

### 起動・停止（既存インスタンス）

インスタンス作成後の日常的な起動停止は `gar sim start` / `gar sim stop` を使う。

```bash
gar sim start     # 起動 + SSH config 更新
gar sim stop      # 停止
```

### アプリ・runtime のデプロイ

インスタンスが起動したら、アプリ成果物と runtime の配置は `gar sim env deploy` / `gar sim env start` が担う。Terraform には持たせない。

```bash
gar sim env deploy   # CUSE stubs / web-bridge を配置
gar sim deploy       # target app を転送
gar sim env start    # systemd services + port forward 起動
```

### SSH/scp 接続エラーからの復旧

AWS EC2 用の SSH Remote provider を使う `gar sim env deploy` / `gar sim deploy`、および将来の EC2 上の build などが SSH/scp 接続エラーで終了した場合、GAR は無限に待機・再試行しません。接続処理を持つ provider 共通の復旧処理が、VS Code Terminal Bridge を通じて、見える terminal に次のログイン要求を送ります。

```bash
aws login --remote --region <設定済みの region>
```

表示された URL はブラウザで開き、認証コードは **その terminal にのみ**入力します。チャットや AI に貼り付けません。認証後、エラー表示に出た `gar sim start --workspace ...` で EC2 を起動して Public IP を更新し、同じ deploy コマンドを再実行します。

### 確認

```bash
gar sim env diag --json   # プロセス・デバイス・API 状態
```

---

## MuJoCo / Sim2Real シミュレーション

二足歩行など、関節・接触・摩擦を含むロボット物理は **MuJoCo** provider で扱う。GAR は MuJoCo を置き換えず、モデル検証・実行・ログ・実機実験の往復を共通の操作面に載せる。

`gar setup` で simulation provider に `MuJoCo（ロボット物理）` を選択すると、必要に応じて現在の Python 環境へ `mujoco` package を導入する。標準では動作確認用の振り子モデルを使う。`gar sim env start` は MuJoCo Python SDK を駆動するローカル JSON bridge を起動し、標準 viewer はその bridge と同じ物理状態を表示する。

```bash
gar sim env build                         # MJCF を読み込めるか検証
gar sim env start --no-port-forward       # MuJoCo viewer をローカルで起動
gar sim env diag --json
gar sim env log
gar sim env stop --no-port-forward
```

実ロボットではプロダクト側の MJCF/URDF を指定する。

```bash
export GAR_MUJOCO_MODEL=/path/to/biped.xml
gar sim env build
gar sim env start --no-port-forward
```

単なる viewer ではなく、制御ポリシー・サーボ同定・実機ログ比較を行う場合は、プロダクトリポジトリに runner を置き、`GAR_MUJOCO_RUNNER` で指定する。GAR は `runner --mjcf /path/to/biped.xml --bridge-url http://127.0.0.1:8081` として起動する。この runner に、サーボ遅れ・トルク制限・摩擦・質量などの同定値、学習済み方策、実機トレースの入出力を持たせる。

```bash
export GAR_MUJOCO_MODEL=/path/to/biped.xml
export GAR_MUJOCO_RUNNER=/path/to/product/sim/run_mujoco.py
gar sim env start --no-port-forward
```

GUI のない CI では viewer を起動せず、headless 対応の runner を使う。MuJoCo provider は Linux の `/dev/*` 互換 runtime を模倣するものではなく、ロボット力学の Sim2Real ループを担当する。

### MuJoCo Bridge の JSON 契約

bridge は疑似操作パネルとシナリオ実行の共通入口であり、MuJoCo SDK の `model` / `data` を直接扱う。標準 bridge は次の API を提供する。プロダクト固有 runner も同じ入口を保ちつつ、`walk-start` や `set-gait` のような意味的な action を追加できる。

```text
GET  /api/state
POST /api/command  {"action": "actuator-set", "params": {"actuator": "hip_motor", "value": 0.2}}
POST /api/command  {"action": "reset", "params": {}}
POST /api/command  {"action": "step", "params": {"count": 10}}
```

標準 bridge の `actuator-set` は actuator の制御値をそのまま設定する低レベル操作である。関節角目標、歩容、ゲームパッドなどの入力をどの actuator 制御へ変換するかはプロダクト側 runner の責務にする。人は MuJoCo viewer で物理状態を観察・外乱操作でき、GAR／AI／CI は同じ bridge へ JSON を送る。

既存の `scripts/run_scenario.py` からは `bridge-command` でこの入口を使う。MuJoCo は既定で `http://127.0.0.1:8081` を使うため、`--base-url` で指定する。

```json
{
  "name": "hip actuator smoke",
  "steps": [
    {"action": "bridge-command", "command": "actuator-set", "params": {"actuator": "hip_motor", "value": 0.2}},
    {"action": "wait", "seconds": 0.1},
    {"action": "expect", "path": "actuators.hip_motor", "equals": 0.2}
  ]
}
```

```bash
python scripts/run_scenario.py scenario.json --base-url http://127.0.0.1:8081
```

---

## Wokwi / M5StackC シミュレーション

ESP32 / M5StackC 系ターゲットでは simulation backend に `wokwi` を選ぶと、`gar sim env start` が `gar-tools` のテンプレートとアプリリポジトリのソースを合成し、ローカルに Wokwi workspace を生成します。シミュレーション実行そのものは、ローカルの `wokwi-cli` または VS Code Wokwi 拡張から Wokwi CI のクラウドシミュレーションを呼び出します。

テンプレートは `gar-tools` 側に置きます。

```text
../gar-tools/targets/esp32/wokwi/m5stackc/
  diagram.json
  wokwi.toml.template
  platformio.ini.template
  lib/M5Unified/src/M5Unified.h
  scripts/env_flags.py
  button.test.yaml
```

Vibe Remote のアプリソースは `gar-tools` には置きません。正本はアプリリポジトリ側です。

```text
../gar-vibe-ui/vibe-remote/m5stickc-client/src/main.cpp
```

既定の生成先は次の通りです。このディレクトリは正本ではなく、消しても再生成できる展開済み workspace です。

```text
.gar/wokwi/m5stackc/
  diagram.json
  wokwi.toml
  platformio.ini
  lib/M5Unified/src/M5Unified.h
  scripts/env_flags.py
  button.test.yaml
  README.md
```

`platformio.ini.template` の `{app_src}` は GAR がアプリ固有のパスへ置換します。標準配置では、生成された `platformio.ini` の `src_dir` は `../../../../gar-vibe-ui/vibe-remote/m5stickc-client/src` になります。Wokwi workspace はアプリソースを持たず、ビルド時にリンクされる `M5Unified` 互換 shim だけを差し替えます。アプリの入口は `m5stickc-client/src/main.cpp` 側が持ち、Wokwi workspace はアプリソースを複製しません。

この分離により、Wokwi の配線・shim・scenario は `gar-tools`、アプリ挙動はアプリリポジトリ、実行時の生成物とログは `.gar/wokwi/...` に閉じます。

生成される `diagram.json` は ESP32 DevKit、SPI TFT、BtnA/BtnB、LED を持つ M5StackC 相当の構成です。`wokwi.toml` は PlatformIO の成果物 `.pio/build/m5stackc/firmware.bin` / `.pio/build/m5stackc/firmware.elf` を参照します。

```bash
gar setup                         # target で ESP32 / M5Stack 系、simulation で Wokwi を選ぶ
cd ../gar-vibe-ui/vibe-remote/m5stickc-client
make wokwi-workspace              # GAR の .gar/wokwi/m5stackc を生成 / 再展開
cd ../../../GaplessAgentRuntime/.gar/wokwi/m5stackc
pio run
export WOKWI_CLI_TOKEN=...
wokwi-cli .
```

`make wokwi-workspace` は `m5stickc-client` 側の生成ルールです。内部では GAR の Wokwi provider を呼び、
`gar-tools` の template とアプリ自身の `src/` から `GaplessAgentRuntime/.gar/wokwi/m5stackc` を再展開します。
`gar sim env start --no-port-forward` も同じ workspace を準備しますが、CLI/token/firmware が揃っている場合は
Wokwi CLI 起動まで進めます。workspace 生成だけを明示したい場合はアプリ側 Makefile target を使います。

`wokwi-cli`、`WOKWI_CLI_TOKEN`、firmware が揃っている場合、`gar sim env start --no-port-forward` は Wokwi CLI をバックグラウンド起動し、Wokwi CI のクラウドシミュレーションへ送信します。PID とログは `.gar/wokwi/m5stackc/state.json` / `wokwi.log` に記録します。まだ CLI や firmware がない場合も、workspace 生成までは成功として扱い、次に必要な手順を表示します。

Wokwi CI はクラウド上で実行されるため、完全なローカル/オフライン実行ではありません。無料プランでも CI simulation の月間枠がありますが、長時間・商用・オフライン用途では有料プランの確認が必要です。

### Wokwi の手動確認と自動確認

Wokwi は「workspace 生成」「firmware build」「シミュレータ起動」を分けて扱います。
VS Code 拡張で手動確認する場合、`gar sim env start` は毎回必要ではありません。
一度 `.gar/wokwi/m5stackc/` が生成され、`firmware.bin` / `firmware.elf` が存在していれば、
`diagram.json` を Wokwi Diagram Editor で開き、Editor ペイン左上の再生ボタンを押して確認します。

```bash
cd ~/Yurufuwa/GaplessAgentRuntime/.gar/wokwi/m5stackc
pio run
code .
```

VS Code で `diagram.json` を開き、左上の再生ボタンを押すと、Wokwi 拡張が
`wokwi.toml` を読み、そこに書かれた `firmware.bin` / `firmware.elf` を
Wokwi 側へ送信してシミュレーションを開始します。

自動確認では、GAR 側で Wokwi workspace と firmware を用意してから、シナリオを実行します。
現時点の Wokwi 向けシナリオは Wokwi CLI の `--scenario` を使います。

```bash
cd ~/Yurufuwa/gar-vibe-ui/vibe-remote/m5stickc-client
make wokwi-workspace                  # Wokwi workspace を準備。
cd ~/Yurufuwa/GaplessAgentRuntime/.gar/wokwi/m5stackc
pio run
wokwi-cli --scenario button.test.yaml .
```

長期的には Linux bridge と Wokwi の両方を GAR 共通 JSON シナリオから起動できる形に揃えます。

必要に応じて次の環境変数で上書きできます。

```bash
GAR_WOKWI_PROJECT_DIR=/path/to/wokwi-project
GAR_WOKWI_TEMPLATE_DIR=/path/to/gar-tools/targets/esp32/wokwi/m5stackc
GAR_VIBE_REMOTE_M5_SRC_DIR=/path/to/gar-vibe-ui/vibe-remote/m5stickc-client/src
GAR_WOKWI_FIRMWARE=.pio/build/custom/firmware.bin
GAR_WOKWI_ELF=.pio/build/custom/firmware.elf
GAR_WOKWI_TIMEOUT_MS=30000
```

アプリ側 Makefile target では同じ意味の値を次の変数で指定できます。

```bash
cd ~/Yurufuwa/gar-vibe-ui/vibe-remote/m5stickc-client
make wokwi-workspace \
  GAR_ROOT=../../../GaplessAgentRuntime \
  GAR_TOOLS_ROOT=../../../gar-tools \
  WOKWI_WORKSPACE=../../../GaplessAgentRuntime/.gar/wokwi/m5stackc
```

---

## Vibe Remote 表示・Decision確認

Vibe Remote は、AI/MCP が送る `agentStatus` と小さな Decision UI を表示し、
必要なときに実機ボタン操作を `uiAction` として返すための操作面。
ボタン操作そのものが `RUNNING` / `WAITING` などの agent 状態を作るわけではない。

現在の確認経路は MCP tool または protocol smoke test を使う。

```bash
cd ~/Yurufuwa/gar-vibe-ui/vibe-remote
npm install
VIBE_REMOTE_TOKEN=... npm run smoke:protocol
```

`scripts/virtual-device.js` は旧来の smoke/debug 補助として残っているが、
`/tmp/gar-vibe-remote-device/button_a` などから `agentStatus` を直接送る実装なので、
現在の Decision relay や実機ボタン仕様の正本としては扱わない。また、GARの
Simulation Environmentとして `gar setup` に登録しない。

---

## ESP32 QEMU Firmware

`gar setup` のシミュレート環境に `ESP32 QEMU Firmware` を追加している。
これは Vibe Remote 疑似デバイスと違い、`firmware.bin` を含むESP32 artifactを
flash imageにまとめ、Espressif QEMUでファームウェアとして起動するための入口。

GARとしての長期理想は Renode 上の M5Stack/ESP32 仮想ボード。QEMU runner は
Renodeが育つまでのboot smoke test兼比較対象として残す。Renode化の段階表は
`~/Yurufuwa/gar-tools/targets/esp32/renode/ROADMAP.md` を参照。

既定 artifact:

```bash
~/Yurufuwa/gar-vibe-ui/vibe-remote/m5stickc-client/artifacts/20260620-070805-m5stickc-plus2-vibe-min
```

手動確認:

```bash
~/Yurufuwa/gar-tools/targets/esp32/qemu/bin/gar-esp32-flash-image \
  --artifact ~/Yurufuwa/gar-vibe-ui/vibe-remote/m5stickc-client/artifacts/20260620-070805-m5stickc-plus2-vibe-min \
  --output /tmp/gar-m5stickc-flash.bin
~/Yurufuwa/gar-tools/targets/esp32/qemu/bin/gar-esp32-qemu-run \
  /tmp/gar-m5stickc-flash.bin
```

---

## Renode MCU

`gar setup` のシミュレート環境に `Renode (MCU/ベアメタル)` を追加している。
WSL/Linux 上で選択すると、Renode portable build を
`~/.local/share/gar/renode` に導入し、`~/.local/bin/renode` と
`~/.local/bin/renode-test` の launcher を作成する。

Renode portable .NET build は最小 WSL 環境で `libicu` 不足に当たることがあるため、
GAR が作成する launcher は既定で
`DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1` を設定する。`libicu` を入れて通常の
globalization mode で動かしたい場合は、実行前に環境変数を明示的に上書きする。

現時点の Renode provider は install / 検証入口であり、`gar sim env start` などの
runtime 統合は未配線。Linux runtime で CUSE/gpio-sim を動かす既存経路には
`SSH Remote` provider を使う。

確認例:

```bash
gar setup
renode --version
. ~/.local/share/gar/renode-test-venv/bin/activate
cd ~/.local/share/gar/renode
renode-test tests/platforms/xtensa.robot
```

`qemu-system-xtensa` が無い場合は、ESP-IDF の `idf_tools.py install qemu-xtensa`
で Espressif QEMU を入れる。

---

## 起動手順

`gar-build-env` Codespace で ARM64 ビルドし、成果物を WSL hub 経由で EC2 に転送済みの前提です。

シミュレーション開始は 2 段階に分けます。

1. **runtime 配置** — `gar sim env start` で bridge と dummy device runtime を起動し、runtime host 上にテスト用 `/dev/*` を用意する。
2. **アプリ起動** — VS Code terminal profile "EC2 Simulation" などから EC2 にログインし、本番と同じ `~/sensor_demo` でアプリを起動する。

この分離により、sim/device でアプリ起動スクリプトを分けず、違いを `/dev/*` を用意する runtime 側に閉じ込めます。

### runtime 配置

```bash
gar sim env deploy
gar sim env start
```

主な配置先:

```text
/etc/gar/hardware/*.csv
/usr/local/sbin/gar-gpio-sim-start
/usr/local/sbin/gar-gpio-sim-stop
/usr/local/sbin/gar-bridge-start
/usr/local/sbin/cuse_i2c
/usr/local/sbin/cuse_spi
/usr/local/lib/gar/web-bridge/
/run/gar/
/run/gar/hw_sim.sock
```

systemd unit:

```text
gar-sim.target
gar-gpio-sim.service
gar-bridge.service
gar-cuse-i2c@i2c-1.service
gar-cuse-spi@spidev0.0.service
```

GPIO dummy runtime だけを確認・更新したい場合は、full runtime の生コマンドを直接打たずに `gar sim env gpio` を使います。

```bash
gar sim env gpio plan --json
gar sim env gpio install
gar sim env gpio start
gar sim env gpio status --json
gar sim env gpio stop
```

`plan` はローカルの `hardware/gpio.csv` から生成される gpio-sim chip / line / label / service 配置の契約を表示します。ローカル `hardware/` が未作成の場合は `gar-tools/targets/linux-device/hardware/` の target 標準テンプレートを参照します。`start` は `modprobe gpio-sim`、configfs chip 作成、必要な bind mount までを `gar-gpio-sim.service` 経由で行います。

### アプリ起動（本番と同じ）

```bash
ssh vibecode-graviton
~/sensor_demo
```


## 設計方針: 起動スクリプトを分岐させない

実機検証が始まると、シミュレーション専用スクリプトは人間の注意から外れ、壊れていても気づきにくくなります。Gapless Agent Runtime では、sim/device で起動スクリプトを完全に分けるのではなく、共通の target 定義から runtime adapter が必要な device layer を用意する設計へ寄せます。

```text
target: sensor_demo
binary: ~/sensor_demo
requires: gpio, spi, i2c

sim runtime:
  gpio -> fake /dev/gpiochip0
  spi  -> fake /dev/spidev0.0
  i2c  -> CUSE /dev/i2c-1

device runtime:
  gpio -> real /dev/gpiochip0
  spi  -> real /dev/spidev0.0
  i2c  -> real /dev/i2c-1
```

この形なら、アプリや起動定義は「何を起動するか」だけを持ち、シミュレーション固有の差し替えは Gapless Agent Runtime runtime が担当します。

---

---

## シミュレーションにおける制約とモダンAPIへの移行方針

旧来の組み込み開発では、高速なGPIO制御のために `/dev/gpiomem` などに対して `mmap` を行い、物理メモリ（レジスタ）を直接書き換える手法が一般的でした（`wiringPi` 等）。しかし、**この `mmap` 方式はシミュレーション環境において致命的な制約**を持ちます。

* **ユーザー空間フックの限界**: `mmap` でマッピングされたメモリ空間に対するアプリからの直接書き込みは、システムコール（関数呼び出し）を伴わないため、ユーザー空間の関数フックでは「いつ値が書き換わったか」を検知できません。これをトラップするには MMU のページフォールトを利用したカーネルレベルの強引なハックが必要になります。
* **ハードウェア依存**: `mmap` は物理メモリアドレス（例: BCM2835 の特定アドレス）に決め打ちとなるため、EC2 Graviton や他の基板への移植性が低くなります。

### 制約の回避（新しいカーネル機能の活用）
Gapless Agent Runtime では、新規開発および移行において **「Linux標準の GPIO Character Device API (`/dev/gpiochipX`) と `libgpiod` を使用する」** 方針を推奨しています。

これにより、すべての操作が `ioctl` などのシステムコールを経由するようになります。
1. **シミュレーションが容易に**: システムコール経由になるため、CUSE や標準のダミーカーネルモジュール（`gpio-mockup`, `gpio-sim`）を使うだけで、特殊なハックなしに完璧なシミュレーションが可能になります。
2. **完全なポータビリティ**: ハードウェア固有のアドレス依存がなくなり、RasPi でもクラウド上の仮想ハードウェアでも、全く同じバイナリ（環境一致）が安全かつ高速に動作します。

---

## ブラウザパネルへのアクセス

Antigravity から EC2 に Remote SSH 接続している場合、ポートは自動的にフォワードされます。

1. **Open Folder → `/home/ubuntu/GaplessAgentRuntime`** を開く（`.vscode/settings.json` の自動転送設定が有効化される）
2. **PORTS タブ**で `8080` の行を右クリック → "Open in Simple Browser"
3. HTML パネルが開き、各デバイスの状態がリアルタイム表示される

> 自動検出されない場合は手動で `8080` と `8765` を Add Port してください。

---

## 操作と確認

| 操作 | パネル表示 / 期待される挙動 |
|---|---|
| `BTN GPIO17` PUSH | LED GPIO18 がトグル / OLED の `System: ON/OFF` 切替 |
| `Range` スライダ | VL53L0X 距離値が変動（vl53l0x_read で確認可） |
| `Tap Card` | OLED に `Last UID: 04:AB:CD:EF` 表示 / LED GPIO24 がフラッシュ / Scans カウンタ増加 |
| `Remove` | カード未検出に戻る |

### bridge HTTP API（内部仕様）

Linux / RasPi-compatible simulation の Web UI とシナリオ実行系は、内部で bridge HTTP API を使う。
人間の手動操作は Web UI から行い、AI / CI の再現操作はGAR共通のJSONシナリオとして定義する。

| Endpoint | Method | 用途 |
|---|---|---|
| `/api/state` | GET | 仮想 H/W 状態を取得 |
| `/api/button` | POST | GPIO ボタン状態を直接セット |
| `/api/button/press` | POST | GPIO ボタンを押して離す |
| `/api/rfid/tap` | POST | RFID カードを置く |
| `/api/rfid/remove` | POST | RFID カードを外す |
| `/api/range` | POST | VL53L0X の距離値をセット |

### JSON シナリオ試験

仮想 H/W 操作は JSON シナリオとして定義し、AI や CI が繰り返し実行できる。
公開CLIの単発UI操作コマンドは持たせず、シナリオを実行単位にする。
Linux bridge 向けの既存補助ランナーは `scripts/run_scenario.py`。

```bash
python scripts/run_scenario.py path/to/scenario.json
```

```json
{
  "name": "sensor_demo system-on rfid flow",
  "steps": [
    { "action": "button_press", "line": 17, "duration_ms": 150 },
    { "action": "wait", "seconds": 0.5 },
    { "action": "rfid_tap", "uid": "04:AB:CD:EF:01:23" },
    { "action": "expect", "path": "spi.mfrc522.present", "equals": true }
  ]
}
```

| action | 用途 |
|---|---|
| `button_press` | GPIO ボタンを押して離す |
| `button_set` | GPIO ボタン状態を直接セット |
| `rfid_tap` / `rfid_remove` | RFID カードを置く / 外す |
| `range_set` | VL53L0X の距離値をセット |
| `wait` | 指定秒数待つ |
| `expect` | `/api/state` の値を検証する |

---

## トラブルシューティング

| 症状 | 原因 | 対処 |
|------|------|------|
| `bridge not available` | bridge.py が未起動 | ターミナル1 を確認 |
| `/dev/fuse: Permission denied` | sudo なしで CUSE 起動 | `sudo` で起動 |
| sensor_demo が `/dev/gpiochip0: No such file` | simulation runtime 未起動 | `gar sim env start` 後に fake `/dev/gpiochip0` 起動状態を確認 |
| `Tap Card しても OLED に UID 出ない` | cuse_spi / bridge / system_on のいずれかが未接続 | `gar sim env diag --json`、`gar sim env log`、`sensor_demo` ログを確認 |
| パネルが Disconnected のまま | ポート 8765 未転送 | PORTS タブで 8765 を Add Port |
| OLED に表示が出ない | I2C アドレス 0x3C 未認識 | `i2cdetect -y 1` で 0x3C があるか確認 |
| `Last UID` が更新されない | system_on が OFF | パネルの GPIO17 PUSH で ON に切替 |
