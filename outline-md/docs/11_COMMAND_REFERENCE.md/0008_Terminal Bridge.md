## Terminal Bridge

AI と人間が同じ VSCode integrated terminal を共有するための入口です。`gar terminal run` で `.gar/terminal-requests/` に request JSON を作成し、VSCode extension がそれを検知して visible terminal でコマンドを実行します。

| コマンド | 実行場所 | 目的 | 主な処理 | 備考 |
|---|---|---|---|---|
| `gar terminal run -- <command>` | Gapless Agent Runtime (venv) | visible terminal で実行要求 | `.gar/terminal-requests/<id>.json` を作成 | sudo 等の人間入力が必要なコマンドを VSCode に handoff |
| `gar terminal gc [--keep-days N] [--dry-run]` | Gapless Agent Runtime (venv) | 古い request / status の削除 | `terminal-requests/processed/` と `terminal-status/` の `.json` を `--keep-days`（既定 7）より古いものから削除 | 長期 session で蓄積した request を整理する |
