## Gapless Agent Runtime / WSL Hub

`Gapless Agent Runtime` は WSL 側のハブとして、runtime host への接続、デプロイ、シミュレーション操作、Codespaces の見える化を担当します。
`gar setup` は WSL Hub の中心コマンドです。`gar` コマンドは `Gapless Agent Runtime (venv)`、つまり Gapless Agent Runtime repo の `.venv` 上で実行します。`make start` は venv と bash completion を有効化したサブシェルを開きます。

| コマンド | 実行場所 | 目的 | 主な処理 | 備考 |
|---|---|---|---|---|
| `make init` | Gapless Agent Runtime | AGP CLI と周辺連携を整える | `.venv` を作成し、`requirements-gar.txt` から `argcomplete` を導入、`.venv/bin/gar` を `scripts/gar` へ symlink。VSCode terminal bridge extension を install し、`.gar/mcp-config.json` を生成 | 初回セットアップ、または extension / MCP 設定更新時 |
| `make start` | Gapless Agent Runtime | 仮想環境の有効化 | 新しいシェル（サブシェル）を立ち上げ、自動的に venv と bash completion を有効化する（`poetry shell` と同等の挙動） | 日常的な開始入口 |
| `gar completion bash` | Gapless Agent Runtime (venv) | bash completion script を出力 | `argcomplete` の `register-python-argcomplete gar` を優先し、未導入時は argparse parser から候補を拾う fallback を登録 | 通常は `make start` が自動で読み込む |
| `gar setup` | Gapless Agent Runtime (venv) | WSL 側依存の検出と導入 | provider を検出し、`gh` / `sshfs` / `ssh` / `adb` / `aws` などの不足を確認・導入。`gar sim` の既定 host も保存 | 環境構築や設定更新時に手動実行 |
| `gar setup --ec2-host vibecode-graviton` | Gapless Agent Runtime (venv) | 既定 host を明示設定 | 保存済み host 設定を更新 | 対話なしで設定したい場合 |
| `gar hw init` | Gapless Agent Runtime (venv) | 空の hardware 定義 CSV を作成 | `hardware/{components,gpio,i2c,spi,connections}.csv` をヘッダだけで作成 | 既存ファイルは `--force` なしでは上書きしない |
