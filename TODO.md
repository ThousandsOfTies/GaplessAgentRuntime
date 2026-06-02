# AgentCockpit タスクリスト

毎日の「今日なにやろうかな」用のメモ。気軽に書き換えてOK。
詳細な設計は [docs/](docs/) 各ファイルに、ここは「次の一手」を思い出すための入口。

最終更新: 2026-06-02

---

## 🔥 いま一番やりたい（Next）

- [x] **昨日 EC2 で Codex が作った GPIO ダミードライバの「方式」を検証** — 結論: **CUSE 単独方式（doc 12 方式2）だった** — 2026-06-02
  - 実物: [agp-tools/cuse-stubs/gpio-stub/cuse_gpio.c](../agp-tools/cuse-stubs/gpio-stub/cuse_gpio.c)（gpio-sim でも shim でも kernel module でもない）
  - 「できた」の実態 = `GPIO_GET_CHIPINFO_IOCTL` が 1 個通っただけ。**LED/Button は未動作**
  - 致命的限界: line request ioctl で `r.fd = 0`（偽 fd）を返すのみ。CUSE は他プロセスの fd table に fd を入れられない＝**透過置換が原理的に不可能**
  - → doc 12 の「CUSE 単独では GPIO を解けない」が実証で裏付けられた
- [ ] **GPIO の解決方式を決める** — `gpio-sim` が EC2 で使えるか確認する（**EC2 作業 = Codex 担当**）
  - 具体手順は EC2 上の README に記載: [agp-tools/cuse-stubs/gpio-stub/README.md](../agp-tools/cuse-stubs/gpio-stub/README.md) の「Next steps for the agent (run on EC2)」
  - 使えるなら CUSE ではなく gpio-sim で GPIO を解決する方針に切替
  - 背景・比較表: [docs/12_CUSE_MIGRATION_PLAN.md §2.3](docs/12_CUSE_MIGRATION_PLAN.md)

---

## 🚧 進行中（CUSE / LD_PRELOAD 廃止）

移行ステップ詳細: [docs/12_CUSE_MIGRATION_PLAN.md §6](docs/12_CUSE_MIGRATION_PLAN.md)

- [ ] **S1** `cuse_gpio` プロトタイプ（CHIPINFO + LINE_SET_VALUES、LED18 トグル）※ gpio-sim 採否の結論待ち
- [ ] **S2** `cuse_gpio` の入力値 + edge event（Button17 → sensor_demo）
- [ ] **S3** `agp sim start` / `start.sh` から `LD_PRELOAD=gpio_shim.so` を削除
- [ ] **S4** `cuse_spi` 実装（MFRC-522 register sim を移植）
- [ ] **S5** `LD_PRELOAD=spi_shim.so` を削除、起動コマンドを `~/sensor_demo` のみに
- [ ] **S6** docs の `LD_PRELOAD` 言及を「移行完了」に更新
- [ ] **S7** 旧 `gpio_shim` / `spi_shim` を `legacy/` へ退避 or 削除

---

## 💡 アイデア / あとで（Backlog）

- [ ] **GPIO ダミードライバの生成〜デプロイ手順を `agp` の操作単位に畳む** — 生コマンド連打を AI が外れないレールにする（`agp` = 人の操作面 ＋ AI 参照用の実コマンドドキュメント）
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
