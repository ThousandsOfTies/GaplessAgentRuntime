## Target Runtime

`gar target` は dummy device runtime を使わず、接続先が提供する I/O / 実デバイスを使って動かすモードです。旧 Windows PowerShell RasPi helper 相当の「Codespace から成果物取得 → 実機 push」は `gar target sync` に収容しています。

実機接続は **adb を既定**としています（社内環境で複数 NIC が使えないケースを優先）。adb provider では deploy 前に `adb devices` を確認し、実機が見えない場合は `gar usb attach` 相当を自動で先行実行します。ネットワーク越しに到達できる環境向けには、`gar setup` の実機環境カテゴリで `SSH / scp` provider を選択でき、`gar target deploy --host <ssh-host>` が `scp` + `ssh chmod` で artifact を転送します。

| コマンド | 実行場所 | 目的 | 主な処理 | 備考 |
|---|---|---|---|---|
| `gar target fetch` | Gapless Agent Runtime (venv) | Codespace の artifact bundle を WSL hub へ取得 | `gh codespace cp` で `artifact.json` と manifest 記載の `deploy.*.files[].src` を取得 | 既定 remote root は `/workspaces/gar-build-env/artifacts/from-codespace`。`--codespace` / `--remote-root` / `--artifacts-dir` 指定可 |
| `gar target sync` (adb_usb) | Gapless Agent Runtime (venv) | Codespace 取得から target runtime 配置まで一発実行 | `gar target fetch` 相当の取得後、`deploy.target.files` に従って `adb push` | `--serial` で device serial 指定。実機未検出時は `gar usb attach` 相当を自動実行 |
| `gar target sync --host HOST` (ssh_scp) | Gapless Agent Runtime (venv) | Codespace 取得から SSH 経路の target 配置まで一発実行 | 取得後に `scp -F ~/.ssh/config <host>:<dest>` で転送し、必要なら `ssh chmod` を実行 | `gar setup` で device provider に `SSH / scp` を選択した場合に有効 |
| `gar target deploy` (adb_usb) | Gapless Agent Runtime (venv) | target runtime へ成果物を配置 | AGP artifact bundle の `deploy.target.files` に従って `adb push` で接続先へ転送 | `--serial` で device serial 指定。実機未検出時は `gar usb attach` 相当を自動実行 |
| `gar target deploy --host HOST` (ssh_scp) | Gapless Agent Runtime (venv) | SSH 経路で target runtime へ成果物を配置 | `scp -F ~/.ssh/config <host>:<dest>` で転送し、必要なら `ssh chmod` を実行 | `gar setup` で device provider に `SSH / scp` を選択した場合に有効 |
