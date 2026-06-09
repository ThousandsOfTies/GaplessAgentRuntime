## Build Artifacts

ビルドそのものは `gar-build-env` の Codespace 内に clone された各 repo で行います。ビルドコマンドや生成物は target software ごとに異なるため、ここでは固定の `make` 手順を定義しません。各 target repo の README / build script に従ってください。
各 target project は、ビルド後に AGP artifact bundle を作成します。`gar sim deploy` / `gar sim env deploy` / `gar target deploy` は bundle 内の `artifact.json` を読み、対応するセクションに従って転送します。

| セクション | デプロイ先 | コマンド |
|---|---|---|
| `deploy.app` | VM / 実機（共通の target app バイナリ） | `gar sim deploy` / `gar target deploy` |
| `deploy.sim_env` | VM 専用（CUSE stubs / web-bridge など環境インフラ） | `gar sim env deploy` |

最小例:

```json
{
  "name": "sensor-demo",
  "deploy": {
    "app": {
      "files": [
        { "src": "files/sensor_demo", "dest": "~/sensor_demo", "mode": "0755" }
      ]
    },
    "sim_env": {
      "files": [
        { "src": "files/cuse_i2c",  "dest": "~/cuse_i2c",  "mode": "0755" },
        { "src": "files/web-bridge", "dest": "~/web-bridge" }
      ]
    }
  }
}
```

`src` は bundle root からの相対パスです。`dest` が相対パスの場合は `gar target deploy --dest <dir>` を基準に配置します。`mode` は省略可能です。

**後方互換**: 旧スキーマの `deploy.sim` / `deploy.target` が存在する場合、`deploy.app` が無ければ自動的にフォールバックします。

| コマンド | 実行場所 | 目的 | 主な処理 | 備考 |
| `gar code start [--codespace <name>]` | Gapless Agent Runtime (venv) | Codespace build workspace を WSL から見えるようにする | `~/.ssh/codespaces` 更新、`~/.config/codespace-dev/env` 更新、SSHFS mount、VS Code `Codespaces` terminal profile 作成 | `gh codespace list` が 1 件なら `--codespace` 省略可。旧 `tools/setup_codespace_wsl.sh` は互換 wrapper |
| `gar code stop` | Gapless Agent Runtime (venv) | Codespace build workspace の WSL 側接続を止める | `gar code start` で張った SSHFS mount を unmount し、VS Code `Codespaces` terminal profile を削除 | `~/.ssh/codespaces` と `~/.config/codespace-dev/env` は再接続用 cache として保持 |
