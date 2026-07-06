# Gapless Agent Runtime タスクリスト

毎日の「今日なにやろうかな」用のメモ。気軽に書き換えてOK。
詳細な設計は [docs/](docs/) 各ファイルに、ここは「次の一手」を思い出すための入口。

最終更新: 2026-07-03

---

## 🔥 いま一番やりたい（Next）

---

## ✅ CUSE / gpio-sim 移行完了

移行は完了済み。詳細は以下の各項目の記録を参照。

- [x] **G1/G2** GPIO は `gpio-sim` + GPIO chardev v2 ルートに切替。`gar sim env start` が fake `/dev/gpiochip0` を用意し、`sensor_demo` は `/dev/gpiochip0` 固定のまま動く — 2026-06-03
- [x] **G3** bridge.py と gpio-sim sysfs を同期（Button17 / LED18 / LED24 を panel と接続） — 2026-06-03。Button17 の `pull-up/down` を bridge から gpio-sim に反映、LED18/24 は gpio-sim `value` を poll して panel state に反映
- [x] **G2.5（実機検証）** EC2 で `gar sim env start` → `gar sim env diag --json` を流し、`/dev/gpiochip0` が gpio-sim 由来で本当に line を返すか確認 — 2026-06-03。`~/sensor_demo` 単体起動、Button17 到達、LED18 反映まで確認
- [x] **G4** GPIO の旧 shim を起動手順から削除 — 2026-06-03。gpio-sim + GPIO chardev v2 経路で `~/sensor_demo` 単体起動確認済み
- [x] **S4** `cuse_spi` 実装（MFRC-522 register sim を移植） — 2026-06-03。Codespace cross-build、EC2 deploy、`/dev/spidev0.0` 作成、`gar sim ui rfid tap ...` で UID ログ、`rfid remove` 復帰まで確認
- [x] **S5** SPI 旧 shim を削除、起動コマンドを `~/sensor_demo` のみに（S4 の実機確認が取れ次第） — 2026-06-03。追加環境変数なしの `~/sensor_demo` で GPIO/I2C/SPI 経路確認済み
- [x] **S6** docs の旧 shim 言及を「移行完了」に更新 — 2026-06-03。主要 docs は CUSE + gpio-sim 完了形へ更新し、`docs/12` は移行記録として保持
- [x] **S7** 旧 `gpio_shim` / `spi_shim` を削除 — `gar-tools/targets/linux-device/runtime/{gpio-shim,spi-shim}/` を削除、`targets/linux-device/runtime/Makefile` SUBDIRS・`.gitignore`・`.vscode/tasks.json`（GPIO デモ）・AGENT.md 成果物表から参照除去（git 履歴に残るので復元可） — 2026-06-03

---

## 💡 アイデア / あとで（Backlog）

- [ ] **OLED framebuffer の期待値チェック追加** — `/api/events` で操作履歴を取得し、OLED canvas の期待値と照合できるようにする
- [ ] **`gar sim run` / `gar target run` の共通 manifest 化** — `~/sensor_demo` 起動後の検証ログ収集まで `gar` に畳む
- [ ] **実機 RasPi5 にも `run / logs / diagnose` 抽象を用意する** — シミュレーションと同じ観察コマンド体系を実機にも適用

- [ ] **検証軸に「ポータビリティ劣化チェック」を追加** — [OK] が押せても成果物の質が落ちていないかを見る目を入れる（押下回数だけ減って質が死ぬのを防ぐ）
- [ ] **AI の自己判断レイヤ** 実行前に AI が `--json` の結果を見て「やめておく / 直す」を選ぶループ（[info/02_DESIGN_PHILOSOPHY.md](info/02_DESIGN_PHILOSOPHY.md) の欠けているピース）
- [x] **hardware assignment CSV の分離** — target 標準の hardware CSV は `gar-tools/targets/*/hardware/` を正本にし、Gapless Agent Runtime 側の `hardware/` は `gar hw init` で生成するローカル上書きとして扱う
- [ ] **「装置」化デモ — 距離キープ P 制御 1 ループ** 既存 sim 資産だけで、目標距離を自律で保つ最小フィードバック制御を組む。get=vl53l0x / 制御=誤差×ゲイン（P のみ、I・D は欲しくなってから）/ put=LED 点滅速度 or PWM / 表示=ssd1306 に「目標・現在・誤差」。狙いは「LED が点くだけ」→「目標値を自律で保つ計器」への一段＝デモを機能証明から価値証明へ。自然言語→仮想でゲイン調整→実機 の既存閉ループに乗せる。遠い構想は [info/03_FUTURE_VISION.md](info/03_FUTURE_VISION.md)、これはその"足元版"

---

## ✅ 最近やったこと（Done）

- [x] **SIM machine 構築を Terraform でレシピ化し `gar sim infra` に接続** — `infra/terraform/main.tf`（EC2/SG/volume/key）と `user_data.sh`（linux-modules-extra / gpiod / strace）を作成。`gar sim infra setup/apply/destroy` が Terraform を実行し、`setup` は現在値と作成計画を表示、`apply` 後は `instance_id` / `public_ip` を `.gar/config.json` と SSH config へ反映 — 2026-06-09 / 2026-07-03 更新
- [x] **既存テストのほころびを解消** — `python -m unittest discover -s tests -v` で 144 tests OK、GitHub Actions の `Tests` も green。古い target deploy 系 3 件失敗メモは解消済み — 2026-07-03
- [x] **rtk（トークン削減）の導入済み確認** — Codex/AGENT 指示で `rtk` を使う運用になっており、未完了バックログから除外。使い方は AGENT.md「オプション: rtk」セクションを参照 — 2026-07-03
- [x] **USB-C の auto-attach は on-demand attach で代替** — Windows タスクスケジューラで挿入瞬間に attach する常駐導線は不要と判断。`gar target deploy/sync` が必要時に `gar usb attach` 相当を自動実行するため、通常運用は gar 操作時の遅延 attach に集約 — 2026-06-06
- [x] **`gar target deploy`（adb 経路）が実機未検出なら `gar usb attach` を自動先行実行する統合** — adb provider の deploy 前に `adb devices` を確認し、対象 device が見えない場合は `gar usb attach` 相当を自動実行してから再確認する形へ変更 — 2026-06-06
- [x] **旧 Windows PowerShell RasPi helper 相当（Codespace から成果物取得 → 実機 push）の `gar` 収容** — `gar target fetch` で Codespace の artifact bundle を WSL hub へ取得し、現在は `gar target deploy` が artifact 未取得時の fetch も担う — 2026-06-06 / 2026-07-03 更新
- [x] **GPIO ダミードライバの生成〜デプロイ手順を `gar` の操作単位に畳む** — `gar sim env gpio plan/install/start/stop/status` を追加し、gpio-sim の生成計画、helper/service 配置、単体起動、状態確認を CLI 化。生の `modprobe` / configfs / bind mount 操作を避けられる導線へ整理 — 2026-06-05 / 2026-07-03 更新
- [x] **runtime socket 対応 artifact の再ビルド・EC2確認** — Codespace で `cuse_i2c` / `cuse_spi` を再生成し、`gar sim env deploy/start/diag --json` で `/run/gar/hw_sim.sock` 経路を確認。古い `/tmp/hw_sim.sock` を削除した状態で `~/sensor_demo`、Button17、RFID tap が通ることを確認 — 2026-06-05
- [x] **bridge / CUSE の runtime socket path 整理** — `bridge.py` / `cuse_i2c` / `cuse_spi` / 旧 `cuse_gpio` を `GAR_HW_SIM_SOCK` 優先、`GAR_RUNTIME_DIR/hw_sim.sock` 次点、`/tmp/hw_sim.sock` fallback に変更。`gar sim env start` の systemd unit から `GAR_HW_SIM_SOCK=/run/gar/hw_sim.sock` を渡す形へ更新 — 2026-06-05
- [x] **runtime 配置の本番寄せ** — `gar sim env deploy/start` を `/etc/gar/hardware/`、`/usr/local/sbin/`、`/usr/local/lib/gar/`、`/run/gar/` へ寄せ、systemd unit の `$HOME` 直参照を削除。旧 artifact manifest の `~/cuse_*` / `~/web-bridge` は deploy 側で互換マップ — 2026-06-05
- [x] **systemd 化 runtime の EC2 動作確認** — `gar sim env start` が `gar-sim.target` と `gar-gpio-sim.service` / `gar-bridge.service` / `gar-cuse-i2c@i2c-1.service` / `gar-cuse-spi@spidev0.0.service` を配置・起動する形へ移行。EC2 で4 service active、`gar sim env diag --json` `ok: true`、`~/sensor_demo` 起動、Button17 → `[btn] System ON`、RFID tap → UIDログ/OLED/state更新まで確認 — 2026-06-05
- [x] **hardware assignment CSV の PoC 導入** — `hardware/{components,gpio,i2c,spi,connections}.csv` を追加し、現在の GPIO17/18/24/27、I2C `/dev/i2c-1` (`0x3c` SSD1306 / `0x29` VL53L0X)、SPI `/dev/spidev0.0` (MFRC-522) を反映。`gar sim env start/diag` がCSVから GPIO line と I2C/SPI dev を読む形に変更 — 2026-06-05
- [x] **panel 操作を `make panel-*` → `gar sim ...` へ移行**（`gar sim ui button press/set`・`rfid tap/remove`・`range set`、`gar sim env status --json`。旧 `make panel-*` は削除し docs 主導線も更新。`make sim-test` は `gar sim` 直呼びに変更） — 2026-06-03
- [x] `gar sim env diag --json` 実装（marker 区切り出力を `parse_sim_diag` で構造化、`ok`/exit code 判定、テスト追加） — 2026-06-03
- [x] `gar sim env gpio-sim-check --json` 実装（modinfo/config.gz/configfs/kernel を構造化プローブ、Codex 移行分） — 2026-06-03
- [x] AGENT.md に「AI オペレーションの原則（契約）」追記（gar 経由・生コマンド連打回避・`--json`/exit code 確認・実機能確認まで done としない） — 2026-06-03
- [x] docs/13 設計思想（なぜ仮想と実機を両方持つのか）を新規作成 — 2026-06-03
- [x] 旧 Windows PowerShell EC2 helper を `gar sim boot/shutdown/status` に移植（SSH config HostName 自動更新付き） — 2026-06-02
- [x] USB-C を `gar usb attach` で WSL2 へ（busid 自動検出・記憶） — 2026-06-02

---

## 📌 リネーム作業時にまとめて行うこと（今はやらない）

最終目標は全名称を `gar` ベースに統一すること（製品名「Gapless Agent Runtime」/ CLI `gar`）。
正本リポは `ThousandsOfTies/GaplessAgentRuntime`、ツールは `ThousandsOfTies/gar-tools`（build-env / embedded-poc-app も同 org）。
トップ 4 フォルダの物理リネームと連動するため、以下は **リネーム作業時に一括**で実施する。

- [ ] **残るフォルダの物理リネーム** — `embedded-poc-app` → `gar-*` 名へ（`GaplessAgentRuntime` / `gar-tools` / `gar-build-env` は変更済み）
- [ ] **リポ跨ぎ参照を URL 化** — サブリポの参照スタブのリポ跨ぎ相対リンクを GitHub の絶対 URL に変更（リポ跨ぎは URL が正、同一リポ内リンクは相対のまま）
- [ ] **フォルダ名を含むパス記述の統一** — 残る旧名や `gar-*` 混在を一括確認

## 🔌 Renode / MCU 拡張（着手済み・ランタイム統合は今後）

- [x] **`gar setup` に Renode(MCU/ベアメタル) simulation プロバイダを追加** — `scripts/gar_lib/environments/registry/simulation/renode_mcu.py`。Linux/WSL2 で最新 portable build を user-local 導入。プラグイン自動発見でコア無改修。ランタイム統合は未配線スタブ（`gar sim env` は当面 `ssh_remote` 利用） — 2026-06-10
- [ ] **Renode ランタイム統合（本配線）** — `.resc` 生成・ペリフェラルモデル起動で `gar sim env` を Renode 上で回す。最小実験として Pico の `.elf` を Renode と実機で同一バイナリ実行（sim↔実機パリティのデモ）＝製品が必要とする「2 件目の汎用性実証」
- [ ] **ターゲット抽象の引き直し（本配線と同時に）** — 現状の simulation/device 抽象（`run_remote`/`push_file`/`start_port_forward`）は「SSH/adb で Linux に繋ぐ」前提に最適化されており、Renode（ローカルプロセス＋ファームロード）や専用 SoC 評価ボード（JTAG/SWD 書き込み・電源/リセット・シリアル/RTT）で破綻する。What（検証対象）と How（接続方法）を分離し、操作を能力（lifecycle / provision / execute / observe）で捉え直す。「SSH」は execute の一実装に格下げ。これは「同一バイナリが sim と実機で動く（バイナリ透過性）」を Linux SBC 以外へ持ち越せるかの試金石。YAGNI に従い、実例 2 つを手にする本配線時に痛みとともに引き直す
- [x] ドキュメント整理（README + docs 01〜12、WSL 中心方針へ）
- [x] GPIO 解決方式の比較表を docs 12 に整理
- [x] EC2 の `gpio-sim` 対応確認、`linux-modules-extra-$(uname -r)` 導入、`sensor_demo` GPIO v2 化、`gar sim env start` の fake `/dev/gpiochip0` setup 実装 — 2026-06-03
