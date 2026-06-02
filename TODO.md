# AgentCockpit タスクリスト

毎日の「今日なにやろうかな」用のメモ。気軽に書き換えてOK。
詳細な設計は [docs/](docs/) 各ファイルに、ここは「次の一手」を思い出すための入口。

最終更新: 2026-06-03

---

## 🔥 いま一番やりたい（Next）

- [ ] **panel 操作を `make panel-*` から `agp sim ...` へ移す**
  - まず実装する操作:
    - `agp sim button press 17 [--duration-ms 150]`
    - `agp sim rfid tap 04:AB:CD:EF:01:23`
    - `agp sim rfid remove`
    - `agp sim range set 300`
    - `agp sim state [--json]`
  - 実体は WSL から SSH で EC2 に入り、EC2 localhost の bridge HTTP API を叩く。
  - `make panel-button` などは互換入口として残してよいが、docs の主導線は `agp sim ...` にする。
  - 将来の対称形として `agp native button press 17` などを置けるよう、操作語彙は `sim` / `native` 配下に置く。
  - 目的: 人間/AI の操作面を `make` ではなく `agp` に統一し、「sim に命令を出す」形にする。

---

## 🚧 進行中（CUSE / LD_PRELOAD 廃止）

移行ステップ詳細: [docs/12_CUSE_MIGRATION_PLAN.md §6](docs/12_CUSE_MIGRATION_PLAN.md)

- [x] **G1/G2** GPIO は `gpio-sim` + GPIO chardev v2 ルートに切替。`agp sim start` が fake `/dev/gpiochip0` を用意し、`sensor_demo` は `/dev/gpiochip0` 固定のまま動く — 2026-06-03
- [ ] **G3** bridge.py と gpio-sim sysfs を同期（Button17 / LED18 / LED24 を panel と接続）
- [ ] **G4** GPIO の `LD_PRELOAD=gpio_shim.so` を起動手順から削除
- [ ] **S4** `cuse_spi` 実装（MFRC-522 register sim を移植）
- [ ] **S5** `LD_PRELOAD=spi_shim.so` を削除、起動コマンドを `~/sensor_demo` のみに
- [ ] **S6** docs の `LD_PRELOAD` 言及を「移行完了」に更新
- [ ] **S7** 旧 `gpio_shim` / `spi_shim` を `legacy/` へ退避 or 削除

---

## 💡 アイデア / あとで（Backlog）

- [ ] **GPIO ダミードライバの生成〜デプロイ手順を `agp` の操作単位に畳む** — 生コマンド連打を AI が外れないレールにする（`agp` = 人の操作面 ＋ AI 参照用の実コマンドドキュメント）
- [ ] **SIM machine 構築を Terraform / Packer / Ansible でレシピ化** — まずは `infra/terraform/` + `user_data` で `linux-modules-extra-$(uname -r)` / `gpiod` / `strace` を入れる。詳細は [docs/03_SIMULATION_SETUP.md](docs/03_SIMULATION_SETUP.md)
- [ ] **検証軸に「ポータビリティ劣化チェック」を追加** — [OK] が押せても成果物の質が落ちていないかを見る目を入れる（押下回数だけ減って質が死ぬのを防ぐ）
- [ ] `agp native deploy`（adb 経路）が実機未検出なら `agp usb attach` を自動先行実行する統合
- [ ] USB-C の auto-attach（Windows タスクスケジューラのデバイス接続トリガで挿した瞬間に attach）
- [ ] `raspi.ps1` 相当（Codespace から成果物取得 → 実機 push）の `agp` 収容
- [ ] `agp sim diag` の `--json` 化（[docs/07](docs/07_AI_AGENT_OPERATIONS.md) の方針と合流）

---

## ✅ 最近やったこと（Done）

- [x] `ec2.ps1` を `agp ec2 start/stop/status` に移植（SSH config HostName 自動更新付き） — 2026-06-02
- [x] USB-C を `agp usb attach` で WSL2 へ（busid 自動検出・記憶） — 2026-06-02
- [x] ドキュメント整理（README + docs 01〜12、WSL 中心方針へ）
- [x] GPIO 解決方式の比較表を docs 12 に整理
- [x] EC2 の `gpio-sim` 対応確認、`linux-modules-extra-$(uname -r)` 導入、`sensor_demo` GPIO v2 化、`agp sim start` の fake `/dev/gpiochip0` setup 実装 — 2026-06-03
