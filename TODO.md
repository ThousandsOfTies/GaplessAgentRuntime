# AgentCockpit タスクリスト

毎日の「今日なにやろうかな」用のメモ。気軽に書き換えてOK。
詳細な設計は [docs/](docs/) 各ファイルに、ここは「次の一手」を思い出すための入口。

最終更新: 2026-06-03

---

## 🔥 いま一番やりたい（Next）

- [ ] **G2.5 実機検証** EC2 で `agp sim start` → `agp sim diag --json` → `agp sim button press 17` / `agp sim rfid tap ...` を流し、LED18 がパネルに反映 / Button17 が sensor_demo に届くまで確認する
  - 「device が生えた」「コマンドが通った」だけでは done にしない（AGENT.md の契約）

---

## 🚧 進行中（CUSE / LD_PRELOAD 廃止）

移行ステップ詳細: [docs/12_CUSE_MIGRATION_PLAN.md §6](docs/12_CUSE_MIGRATION_PLAN.md)

- [x] **G1/G2** GPIO は `gpio-sim` + GPIO chardev v2 ルートに切替。`agp sim start` が fake `/dev/gpiochip0` を用意し、`sensor_demo` は `/dev/gpiochip0` 固定のまま動く — 2026-06-03
- [ ] **G3** bridge.py と gpio-sim sysfs を同期（Button17 / LED18 / LED24 を panel と接続）
  - 受け入れ基準: panel の LED18 トグルが gpio-sim 行に反映 / Button17 押下が `sensor_demo` に届く（「device が生えた」だけでは done にしない）
- [ ] **G2.5（実機検証）** EC2 で `agp sim start` → `agp sim diag --json` を流し、`/dev/gpiochip0` が gpio-sim 由来で本当に line を返すか確認
  - 確認点: 既存の実 `gpiochip0`（`ARMH0061:00` 等）がある環境で `mount --bind /dev/gpiochip0` が二重 bind にならないか
  - `agp sim gpio-sim-check --json` の `ok` と exit code で判定（叩く前に使えるか確かめる作法）
- [~] **G4** GPIO の `LD_PRELOAD=gpio_shim.so` を起動手順から削除 — 🟡 **確認待ち**。`gpio_shim` を削除（S7 と同時）、AGENT.md 手動起動を `~/sensor_demo` 単体に更新。残: gpio-sim 経路で実機確認（G2.5）
- [~] **S4** `cuse_spi` 実装（MFRC-522 register sim を移植） — 🟡 **ビルド待ち・修正待ち**。コード一式作成済み（`agp-tools/cuse-stubs/spi-stub/`）、`cuse-stubs/Makefile` の SUBDIRS に追加済み、`agp sim start/stop/diag/log` に `cuse_spi` 組込み済み。**残: Codespaces で cross-build（`make CC=aarch64-linux-gnu-gcc`、ローカル/EC2 ではビルドしない＝鉄則）→ `cuse_spi` バイナリを WSL 経由で EC2 へ deploy → EC2 で起動確認**（ビルドエラーが出たら Codespaces 側で都度修正）
  - 受け入れ基準: ① `agp sim start` で `/dev/spidev0.0` が生える ② `~/sensor_demo`（LD_PRELOAD なし）が VersionReg=0x92 を読む ③ `agp sim rfid tap ...` で UID 表示 ④ `agp sim rfid remove` でカード無しに戻る
- [~] **S5** `LD_PRELOAD=spi_shim.so` を削除、起動コマンドを `~/sensor_demo` のみに（S4 の実機確認が取れ次第） — 🟡 **確認待ち**。AGENT.md の EC2 起動手順から `spi_shim.so` を除去、`cuse_spi` 経路に更新済み。残: S4 実機確認後に LD_PRELOAD なしで通ることを確認
- [ ] **S6** docs の `LD_PRELOAD` 言及を「移行完了」に更新 — ※実機確認後に「完了」へ。それまでは「移行中」表現
- [x] **S7** 旧 `gpio_shim` / `spi_shim` を削除 — `agp-tools/cuse-stubs/{gpio-shim,spi-shim}/` を削除、`cuse-stubs/Makefile` SUBDIRS・`.gitignore`・`.vscode/tasks.json`（GPIO デモ）・AGENT.md 成果物表から参照除去（git 履歴に残るので復元可） — 2026-06-03

---

## 💡 アイデア / あとで（Backlog）

- [ ] **GPIO ダミードライバの生成〜デプロイ手順を `agp` の操作単位に畳む** — 生コマンド連打を AI が外れないレールにする（`agp` = 人の操作面 ＋ AI 参照用の実コマンドドキュメント）
- [ ] **SIM machine 構築を Terraform / Packer / Ansible でレシピ化** — まずは `infra/terraform/` + `user_data` で `linux-modules-extra-$(uname -r)` / `gpiod` / `strace` を入れる。詳細は [docs/03_SIMULATION_SETUP.md](docs/03_SIMULATION_SETUP.md)
- [ ] **検証軸に「ポータビリティ劣化チェック」を追加** — [OK] が押せても成果物の質が落ちていないかを見る目を入れる（押下回数だけ減って質が死ぬのを防ぐ）
- [ ] `agp native deploy`（adb 経路）が実機未検出なら `agp usb attach` を自動先行実行する統合
- [ ] USB-C の auto-attach（Windows タスクスケジューラのデバイス接続トリガで挿した瞬間に attach）
- [ ] `raspi.ps1` 相当（Codespace から成果物取得 → 実機 push）の `agp` 収容
- [ ] **AI の自己判断レイヤ** 実行前に AI が `--json` の結果を見て「やめておく / 直す」を選ぶループ（docs/13 の欠けているピース）

---

## ✅ 最近やったこと（Done）

- [x] **panel 操作を `make panel-*` → `agp sim ...` へ移行**（`agp sim button press/set`・`rfid tap/remove`・`range set`・`state --json`。旧 `make panel-*` は削除し docs 主導線も更新。`make sim-test` は `agp sim` 直呼びに変更） — 2026-06-03
- [x] `agp sim diag --json` 実装（marker 区切り出力を `parse_sim_diag` で構造化、`ok`/exit code 判定、テスト追加） — 2026-06-03
- [x] `agp sim gpio-sim-check --json` 実装（modinfo/config.gz/configfs/kernel を構造化プローブ、Codex 移行分） — 2026-06-03
- [x] AGENT.md に「AI オペレーションの原則（契約）」追記（agp 経由・生コマンド連打回避・`--json`/exit code 確認・実機能確認まで done としない） — 2026-06-03
- [x] docs/13 設計思想（なぜ仮想と実機を両方持つのか）を新規作成 — 2026-06-03
- [x] `ec2.ps1` を `agp ec2 start/stop/status` に移植（SSH config HostName 自動更新付き） — 2026-06-02
- [x] USB-C を `agp usb attach` で WSL2 へ（busid 自動検出・記憶） — 2026-06-02
- [x] ドキュメント整理（README + docs 01〜12、WSL 中心方針へ）
- [x] GPIO 解決方式の比較表を docs 12 に整理
- [x] EC2 の `gpio-sim` 対応確認、`linux-modules-extra-$(uname -r)` 導入、`sensor_demo` GPIO v2 化、`agp sim start` の fake `/dev/gpiochip0` setup 実装 — 2026-06-03
