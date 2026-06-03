# LD_PRELOAD shim → CUSE / gpio-sim 移行記録

このドキュメントは、EC2 simulation runtime で使用していた **GPIO / SPI の `LD_PRELOAD` shim** を、現在の **CUSE + gpio-sim ベースの fake `/dev/*` runtime** に置き換えた設計判断と移行記録です。

2026-06-03 時点で、アプリ起動コマンドから `LD_PRELOAD` は削除済みです。EC2 でも RasPi5 でも `~/sensor_demo` を直接起動し、EC2 側では I2C/SPI を CUSE、GPIO を `gpio-sim` + GPIO chardev v2 で提供します。

実装は別リポジトリ `agp-tools/cuse-stubs/` で行い、本リポジトリの `agp` CLI / アプリ起動スクリプトは「runtime 側で `/dev/*` が用意される」ことだけを前提に整える、というスコープ分担で進めます。

関連ドキュメント:
- [01_ARCHITECTURE.md §4](01_ARCHITECTURE.md) — 現状の PoC と方向性
- [03_SIMULATION_SETUP.md](03_SIMULATION_SETUP.md) — 全体構成と起動手順
- [05_RESULTS.md](05_RESULTS.md) — 現状の動作確認結果と TODO
- [06_INDUSTRY_TRENDS.md](06_INDUSTRY_TRENDS.md) — 業界比較における位置付け

---

## 1. 目的と非目的

### 目的

1. アプリ起動コマンドから `LD_PRELOAD=...` を **完全に削除する**こと。EC2 でも RasPi5 でも `~/sensor_demo` を直接起動できる状態を到達点とする。**達成済み**。
2. `/dev/gpiochip0` / `/dev/spidev0.0` の **実機と同じパス・同じ ioctl ABI** を fake runtime で提供する。**達成済み**。
3. device compatibility runtime を AI エージェントが追従しやすい形（必要 ioctl だけを実装、ABI 変更は strace 差分で検知）に整理する。

### 非目的

- 全てのカーネル機能の完全互換（`gpio-mockup` 級の網羅）。本 PoC が実際に使う ioctl ABI のみ実装する。
- RasPi5 実機側ランタイムの変更。実機は素の Linux GPIO/SPI/I2C を使う。
- ユーザ空間ライブラリ（`libgpiod` 等）の差し替え。アプリは実機と同じバイナリを使う。

---

## 2. 旧 `LD_PRELOAD` 方式と限界

### 2.1 移行前の構成

| I/F | 方式 | 実装ファイル（agp-tools） | 備考 |
|---|---|---|---|
| I2C | CUSE で `/dev/i2c-1` を生成 | `cuse-stubs/i2c-stub/cuse_i2c` | VL53L0X (0x29) + SSD1306 (0x3C) |
| SPI | `LD_PRELOAD` で `ioctl` を intercept | `cuse-stubs/spi-shim/spi_shim.c` | MFRC-522 register sim |
| GPIO | `LD_PRELOAD` で `/dev/gpiochip0` ioctl を intercept | `cuse-stubs/gpio-shim/gpio_shim.c` | LED18/24, Button17/27 |

移行前のアプリ起動コマンド:

```bash
LD_PRELOAD="$HOME/gpio_shim.so $HOME/spi_shim.so" ~/sensor_demo
```

### 2.2 既知の限界

[03_SIMULATION_SETUP.md](03_SIMULATION_SETUP.md) で指摘済みの内容を整理すると:

1. **`mmap` 経路を捕捉できない**: アプリが `/dev/gpiomem` 等を `mmap` してレジスタを直接読み書きすると、ユーザ空間に閉じた load/store になり `LD_PRELOAD` ではフックできない。`libgpiod` 経路の ioctl は捕捉できるが、レガシー sysfs / mmap の対象アプリには使えない。
2. **`dlsym` 衝突 / 初期化順序の脆さ**: アプリが `libc` の `ioctl` 以外（例: `__libc_ioctl`、`syscall(SYS_ioctl, ...)`、Go の直接 syscall）を使うと素通りする。
3. **アプリ起動コマンドの汚染**: `LD_PRELOAD=...` を `start.sh` に書く、または systemd unit に書く必要があり、sim/device で起動定義が分岐する。これは AgentCockpit の「sim/device で起動を分けない」という設計方針と矛盾する。
4. **ABI 追従の責任がアプリ側に残る**: `LD_PRELOAD` の関数シグネチャは libc の API、ioctl 番号は kernel ABI の両方を追従する必要があり、リファクタリング耐性が低い。

CUSE / gpio-sim 化により、(1)(2) のうち ioctl/read/write 経由の経路は fake `/dev/*` runtime 側に閉じ込め、(3) は起動コマンドから shim 指定が消えることで解消した。`mmap` 経路だけは CUSE でも別途設計が必要（§7 参照）。

### 2.3 GPIO だけ CUSE で解けない理由と解決方式の比較

I2C / SPI は同一 fd 上で `read` / `write` / `ioctl` が完結するため CUSE で素直に置き換えられる。**GPIO だけは別問題**で、`GPIO_V2_GET_LINE_IOCTL` が「呼び出し元プロセスに新しいライン fd を払い出す」ABI のため、他プロセスの fd テーブルに fd を挿し込めない CUSE デーモンでは透過的に再現できない（[gpio-stub/README.md](../../agp-tools/cuse-stubs/gpio-stub/README.md) の limitation）。

解決方式の選択肢:

| # | 方式 | fd 問題 | カーネル改変 | 移植性 | 備考 |
|---|---|---|---|---|---|
| 1 | 旧 `LD_PRELOAD` shim | 回避（偽 fd を `memfd_create`） | 不要 | 低（`dlsym` / `mmap` / 直接 syscall に弱い） | 初期 PoC で動作確認済み |
| 2 | CUSE のみ | **解けない** | 不要 | — | I2C / SPI は OK、GPIO 不可 |
| 3 | 薄い自前カーネルモジュール | 正攻法で解決（fd 払い出しだけ kernel、値処理は user 空間へ委譲） | 要（自前 `.ko`） | 高（実機と同一 ABI） | ビルド / 署名 / 保守コスト |
| 4 | `gpio-mockup`（既存 kernel 機能） | 解決 | 不要（既存モジュール） | 中 | 値注入経路が sysfs/debugfs で限定的 |
| 5 | **`gpio-sim`（configfs、Linux 5.17+）** | 解決 | 不要（標準モジュール） | **高** | **本命候補**。`/dev/gpiochipN` を本物として生やし、ライン値を sysfs から注入。方式 3 を自前で書かずに済む |

方式 5 `gpio-sim` は「方式 3 を自前で書く代わりに、それ相当のものがカーネル標準に入っている」状態。bridge.py は gpio-sim の sysfs を叩くだけで済み、自前 `.ko` の保守を避けられる。**まず EC2 Graviton のカーネルが `gpio-sim` を持つか確認**し、あれば GPIO は CUSE ではなく gpio-sim で解決する方針が有力（確認: `modinfo gpio-sim` または `zcat /proc/config.gz | grep GPIO_SIM`）。

`gpio-sim` が使えない場合のフォールバックとして §4.2 の CUSE 実装（内部仮想 fd 方式）を採る。

確認結果 (2026-06-03, `vibecode-graviton`):

- kernel: `6.17.0-1013-aws`
- `linux-modules-extra-6.17.0-1013-aws` を導入後、`modprobe gpio-sim` は成功。
- configfs で `agp` chip を作成でき、`/dev/gpiochip1` (`label=AgentCockpit`, 54 lines) が出現。
- `GPIO_V2_GET_LINEINFO_IOCTL` は line 17/18/24/27 で成功。
- `GPIO_GET_LINEINFO_IOCTL` (v1) は `EINVAL`。そのため `sensor_demo.c` は GPIO chardev v2 (`GPIO_V2_GET_LINE_IOCTL`) へ移行した。

したがって GPIO は「CUSE GPIO を透明化」ではなく、**アプリ GPIO 呼び出しを GPIO chardev v2 に移す**方針を採用した。これで `gpio-sim` の実 fd 払い出しを使える。

---


## 3. ターゲット構成

[03_SIMULATION_SETUP.md](03_SIMULATION_SETUP.md) §「全体構成」に対応する現在の状態:

```
[EC2 arm64 (Graviton)]

  sensor_demo (アプリケーション、LD_PRELOAD 不要)
    │
    │  GPIO: /dev/gpiochip0 (libgpiod / ioctl)
    │  ──→ gpio-sim (kernel module)
    │       └─ sim_gpio17/27 pull を bridge.py が更新
    │       └─ sim_gpio18/24 value を bridge.py が poll
    │
    │  I2C:  /dev/i2c-1 (read/write/ioctl)
    │  ──→ cuse_i2c (現状維持)
    │
    │  SPI:  /dev/spidev0.0 (SPI_IOC_MESSAGE)
    │  ──→ cuse_spi (CUSE で /dev/spidev0.0 を生成)
    │       └─ MFRC-522 register sim → bridge.py
    │
    └─ bridge.py
```

アプリ起動コマンドはこうなる:

```bash
# EC2 でも RasPi5 でも同一
~/sensor_demo
```

---

## 4. CUSE スタブの設計

### 4.1 共通骨格

CUSE スタブ (`cuse_i2c`, `cuse_spi`) は次の構造を共有する。`cuse_gpio` は調査用プロトタイプとして残し、透明 GPIO runtime には使わない。

```text
main()
  ├─ FUSE/CUSE init: --devname=<dev>, --maj=0 --min=0 (auto)
  ├─ Unix socket connect: /tmp/hw_sim.sock (bridge.py)
  ├─ ops: open / release / read / write / ioctl / poll
  └─ event loop: cuse_lowlevel_main()
```

shared lib として、agp-tools 側に以下を切り出すと保守が楽になる:

- `bridge_client.{c,h}` — Unix socket 経由で bridge.py に JSON メッセージを送る薄い helper（`bridge_send(type, payload)` / `bridge_recv()`）。
- `ioctl_logger.{c,h}` — 不明 ioctl を strace 互換形式でログに残す（AI が ABI 追従に使う）。

### 4.2 GPIO CUSE (`cuse_gpio`) — 採用しなかった案

GPIO CUSE は fd 払い出し問題により透明置換には採用しなかった。現在の GPIO runtime は `gpio-sim` で `/dev/gpiochip0` を提供する。

**提供するノード案**: `/dev/gpiochip0`

**実装すべき ioctl** (Linux GPIO Character Device API v2、`<linux/gpio.h>`):

| ioctl | 用途 | 必須度 |
|---|---|---|
| `GPIO_GET_CHIPINFO_IOCTL` | チップ名、ライン数を返す | **必須** |
| `GPIO_V2_GET_LINEINFO_IOCTL` | 個別ライン情報取得 | **必須** |
| `GPIO_V2_GET_LINE_IOCTL` | ラインリクエスト（fd 払い出し） | **必須** |
| `GPIO_V2_LINE_SET_VALUES_IOCTL` | LED 出力値の設定 | **必須**（LED18/24） |
| `GPIO_V2_LINE_GET_VALUES_IOCTL` | ボタン入力値の取得 | **必須**（Button17/27） |
| `GPIO_V2_LINE_SET_CONFIG_IOCTL` | direction / bias 変更 | 推奨 |
| `GPIOCHIP_INFO_WATCH_IOCTL` | line info 変更通知 | 任意（poll で代替可） |

**ライン定義** (RasPi5 と同じ番号を踏襲):

```c
static const struct line_def lines[] = {
    {17, "BTN_GPIO17", LINE_INPUT},
    {18, "LED_GPIO18", LINE_OUTPUT},
    {24, "LED_GPIO24", LINE_OUTPUT},
    {27, "BTN_GPIO27", LINE_INPUT},
    /* 残りは GPIO_V2_GET_LINEINFO_IOCTL に対して "unused" として返す */
};
```

**bridge.py 連携案**:

- 出力ライン更新: `{ "type": "gpio.set", "line": 18, "value": 1 }` を送る
- 入力ライン更新通知: bridge から `{ "type": "gpio.input", "line": 17, "value": 1 }` を受け、内部状態を更新 → アプリが次に `LINE_GET_VALUES` した時に返す
- 入力エッジ通知: line request fd の poll/read に対して、ボタン押下時に `gpio_v2_line_event` を返す

**不採用理由**: `cuse_gpio` のライン要求 fd は CUSE が払い出せない。`gpio-sim` が EC2 kernel で利用できたため、標準 kernel module に任せる方が透明性と保守性で優れる。

### 4.3 SPI CUSE (`cuse_spi`)

**提供するノード**: `/dev/spidev0.0`

**実装すべき ioctl** (`<linux/spi/spidev.h>`):

| ioctl | 用途 | 必須度 |
|---|---|---|
| `SPI_IOC_MESSAGE(N)` | 任意長 SPI トランザクション | **必須** |
| `SPI_IOC_RD/WR_MODE` | SPI mode 0 を返す | 必須 |
| `SPI_IOC_RD/WR_BITS_PER_WORD` | 8 を返す | 必須 |
| `SPI_IOC_RD/WR_MAX_SPEED_HZ` | 任意値を保持・返す | 必須 |
| `SPI_IOC_RD/WR_LSB_FIRST` | 0 を返す | 推奨 |

`SPI_IOC_MESSAGE` の処理は現行 `spi_shim.c` の MFRC-522 レジスタ sim をそのまま移植する。MFRC-522 のアドレス書式（bit7=R/W, bits6-1=address, bit0=0）と、bridge への `{ "type": "spi.mfrc522.read|write", "register": 0x..., "value": 0x.. }` 連携をそのまま使う。

**実装上の注意**:
- `SPI_IOC_MESSAGE(N)` は ioctl number が `N` を含む可変マクロ。CUSE 側では `_IOC_NR(cmd)` を見て `SPI_IOC_MESSAGE(0)` の NR と一致するか判定する。
- `tx_buf` / `rx_buf` は user space pointer なので、CUSE では ioctl 引数経由ではなく `cuse_lowlevel_ops.ioctl` の `in_buf` / `out_buf` で受け渡す（`fuse_reply_ioctl_retry` でリトライ要求）。

### 4.4 I2C CUSE (`cuse_i2c`)

現状維持。`agp-tools/cuse-stubs/i2c-stub/cuse_i2c` の構造を上記 (4.2)(4.3) のテンプレートに揃えるための小さなリファクタは推奨だが、本計画のスコープ外。

---

## 5. 起動と権限

### 5.1 systemd unit 化

CUSE スタブは sudo が必要。bridge は不要。EC2 上では次のように systemd で常駐させる:

```ini
# /etc/systemd/system/agp-bridge.service
[Service]
ExecStart=/home/ubuntu/venv/bin/python3 /home/ubuntu/web-bridge/bridge.py
Restart=on-failure
User=ubuntu

# /etc/systemd/system/agp-cuse-i2c.service
[Service]
ExecStart=/home/ubuntu/cuse_i2c -f --devname=i2c-1
Restart=on-failure

# /etc/systemd/system/agp-cuse-spi.service
[Service]
ExecStart=/home/ubuntu/cuse_spi -f --devname=spidev0.0
Restart=on-failure
```

`agp sim start / stop` は systemd unit を `systemctl start/stop` する形に切り替える（現状の `setsid nohup` ベースは置き換え）。

### 5.2 デバイスノードのパーミッション

CUSE が払い出すノードは root:root mode 0660 が既定。アプリは ubuntu user で動かすので、各 unit の `ExecStartPost=` で `chmod 666` する、または udev rule を置く:

```bash
# /etc/udev/rules.d/99-agp-cuse.rules
KERNEL=="i2c-1",     MODE="0666"
KERNEL=="spidev0.0", MODE="0666"
```

---

## 6. 移行ステップ

agp-tools リポジトリと AgentCockpit リポジトリで分担。各ステップの完了は `agp sim diag` のグリーンと `make sim-test` の合格で判定する。

| Step | 対象リポ | 内容 | 完了条件 |
|---|---|---|---|
| **S1/S2** | agp-tools | `cuse_gpio` プロトタイプ調査。fd 払い出し問題を確認。 | `gpio-sim` ルートへ方針転換 |
| **S3** | AgentCockpit | `agp sim start` / 起動手順から `LD_PRELOAD=gpio_shim.so` を削除。GPIO は `gpio-sim` へ移行。 | sensor_demo を `LD_PRELOAD` なしで起動 → GPIO 動作 |
| **S4** | agp-tools | `cuse_spi` 実装。MFRC-522 register sim を移植。 | RFID Tap が OLED / ログに UID 反映 |
| **S5** | AgentCockpit | `LD_PRELOAD=spi_shim.so` を削除。`cuse_spi` を起動。 | `LD_PRELOAD` 完全廃止、起動コマンド `~/sensor_demo` のみ |
| **S6** | AgentCockpit | docs (01, 03, 05, 06, AGENT.md, README.md) の記述を移行完了状態に更新。`gpio_shim.so` / `spi_shim.so` を artifact 一覧から削除。 | 完了 |
| **S7** | 両リポ | 旧 `gpio_shim` / `spi_shim` のソースを削除。 | git history で参照可能 |

S1〜S2 で GPIO 経路の正しさを早期検証してから SPI に進む順番が安全。S3 と S4 は並列可。

2026-06-03 の確認により、GPIO は S1/S2 の CUSE ルートではなく `gpio-sim` + GPIO chardev v2 ルートを優先する。暫定の置き換えステップ:

| Step | 対象リポ | 内容 | 完了条件 |
|---|---|---|---|
| **G1** | AgentCockpit | `agp sim gpio-sim-check --json` で EC2 の `gpio-sim` 対応を診断する。 | 完了 |
| **G2** | embedded-poc-app | `sensor_demo.c` の GPIO helper を v1 (`GPIO_GET_LINEHANDLE_IOCTL`) から v2 (`GPIO_V2_GET_LINE_IOCTL`) へ移行する。アプリは引き続き `/dev/gpiochip0` だけを開く。 | 完了 |
| **G3** | agp-tools / AgentCockpit | bridge.py が gpio-sim の sysfs (`/sys/devices/platform/.../sim_gpioN/{pull,value}`) と同期する。 | 完了 |
| **G4** | AgentCockpit | `agp sim start` に gpio-sim setup を組み込み、GPIO の `LD_PRELOAD` を削除する。 | 完了 |

G2 確認結果 (2026-06-03):

- `sensor_demo.c` を GPIO chardev v2 に移行。
- Codespaces (`agp-build-env`) で `aarch64-linux-gnu-gcc` ビルド成功。
- アプリに simulation 固有の chip 選択は入れない。`/dev/gpiochip0` を開くままにし、simulation runtime 側で gpio-sim を `/dev/gpiochip0` として提供する。
- `agp sim start` で gpio-sim chip を作成し、必要なら `/dev/gpiochip1` を `/dev/gpiochip0` に bind mount する。
- EC2 で環境変数なしの `~/sensor_demo` が GPIO setup 成功。
- `agp sim button press 17` で `[btn] System ON/OFF` を確認。
- 実行中の `sim_gpio18/value` と panel state の LED18 が同期することを確認。
- `agp sim rfid tap 04:AB:CD:EF:01:23` で UID ログを確認し、`agp sim rfid remove` で `present=0` に復帰。

---

## 7. リスクと未解決事項

| リスク | 影響 | 軽減策 |
|---|---|---|
| `mmap` 経路を使うアプリやライブラリが現れる | CUSE では捕捉不可 | 本 PoC のスコープでは `libgpiod` / `spidev` 経路に限定する。アプリレビュー時に `mmap("/dev/...")` の使用を禁止する規約を [10_AGENT_COLLABORATION_RULES.md](10_AGENT_COLLABORATION_RULES.md) に追加。 |
| `SPI_IOC_MESSAGE(N)` の可変 ioctl number | CUSE 側で正しく分岐できないと素通り | `_IOC_TYPE(cmd)`/`_IOC_NR(cmd)` で判定し、`size` だけ可変として扱う |
| GPIO line request fd の払い出し方法 | CUSE は新 fd を返せない | 内部仮想 fd 番号を払い出し、後続 ioctl を main fd で受けて分岐する（`gpio_shim.c` の現行設計を踏襲） |
| 既存 demo (`gpio_led_button`, `vl53l0x_read`) の互換性 | regress | S1 完了後に既存 test バイナリで sanity check を行う |
| FUSE/CUSE の libfuse バージョン依存 | EC2 Graviton 上の Ubuntu と RasPi5 用ビルドで差異 | libfuse 3.x で揃え、Codespace ビルドで `pkg-config fuse3 --cflags` を強制 |
| ioctl ABI の kernel バージョン依存 | EC2 と RasPi5 で kernel が変わると壊れる | ABI v2 (`GPIO_V2_*`) で固定、v1 系は実装しない |

未解決事項（実装着手時に AI が決める）:
- `cuse_gpio` で `/sys/class/gpio` 互換は提供するか（しない方針）。
- bridge.py 側の WebSocket イベント名のリネーム要否（`gpio.line17` → `gpio.input.17` 等の正規化）。
- `agp sim diag` の出力フォーマットを CUSE 統一にあわせて再設計するか（[07_AI_AGENT_OPERATIONS.md](07_AI_AGENT_OPERATIONS.md) の `--json` 化方針と合流させると良い）。

---

## 8. AI エージェントへの作業依頼テンプレート

agp-tools 側で実装を進める際の依頼例:

```text
agp-tools リポジトリの cuse-stubs/gpio-stub/ に cuse_gpio を新規実装してください。
仕様は AgentCockpit/docs/12_CUSE_MIGRATION_PLAN.md §4.2 に従います。
既存の cuse-stubs/gpio-shim/gpio_shim.c の MFRC ロジックは流用せず、
GPIO Character Device API v2 の ioctl を CUSE で実装します。
完了基準は同ドキュメント §6 Step S1 の "gpioset gpiochip0 18=1 が panel に反映" です。
作業中、ABI 不明点は strace -e ioctl でログを取り、ioctl_logger.h に記録してください。
```

これに沿って AI が `strace` ログを取りながら実装を進めることで、人間が ioctl ABI を全網羅する必要がなくなる。これが「AI が継続的に維持できる互換 runtime」という AgentCockpit のコンセプトの実証ポイントになる。
