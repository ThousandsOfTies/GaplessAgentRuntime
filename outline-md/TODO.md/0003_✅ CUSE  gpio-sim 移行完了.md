## ✅ CUSE / gpio-sim 移行完了

移行ステップ詳細: [docs/12_CUSE_MIGRATION_PLAN.md §6](docs/12_CUSE_MIGRATION_PLAN.md)

- [x] **G1/G2** GPIO は `gpio-sim` + GPIO chardev v2 ルートに切替。`gar sim env start` が fake `/dev/gpiochip0` を用意し、`sensor_demo` は `/dev/gpiochip0` 固定のまま動く — 2026-06-03
- [x] **G3** bridge.py と gpio-sim sysfs を同期（Button17 / LED18 / LED24 を panel と接続） — 2026-06-03。Button17 の `pull-up/down` を bridge から gpio-sim に反映、LED18/24 は gpio-sim `value` を poll して panel state に反映
- [x] **G2.5（実機検証）** EC2 で `gar sim env start` → `gar sim env diag --json` を流し、`/dev/gpiochip0` が gpio-sim 由来で本当に line を返すか確認 — 2026-06-03。`~/sensor_demo` 単体起動、Button17 到達、LED18 反映まで確認
- [x] **G4** GPIO の旧 shim を起動手順から削除 — 2026-06-03。gpio-sim + GPIO chardev v2 経路で `~/sensor_demo` 単体起動確認済み
- [x] **S4** `cuse_spi` 実装（MFRC-522 register sim を移植） — 2026-06-03。Codespace cross-build、EC2 deploy、`/dev/spidev0.0` 作成、`gar sim ui rfid tap ...` で UID ログ、`rfid remove` 復帰まで確認
- [x] **S5** SPI 旧 shim を削除、起動コマンドを `~/sensor_demo` のみに（S4 の実機確認が取れ次第） — 2026-06-03。追加環境変数なしの `~/sensor_demo` で GPIO/I2C/SPI 経路確認済み
- [x] **S6** docs の旧 shim 言及を「移行完了」に更新 — 2026-06-03。主要 docs は CUSE + gpio-sim 完了形へ更新し、`docs/12` は移行記録として保持
- [x] **S7** 旧 `gpio_shim` / `spi_shim` を削除 — `gar-tools/cuse-stubs/{gpio-shim,spi-shim}/` を削除、`cuse-stubs/Makefile` SUBDIRS・`.gitignore`・`.vscode/tasks.json`（GPIO デモ）・AGENT.md 成果物表から参照除去（git 履歴に残るので復元可） — 2026-06-03

---
