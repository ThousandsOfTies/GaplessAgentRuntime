## Virtual Hardware Operations

仮想パネル（ボタン / RFID / 距離センサ）の操作は `gar sim ui ...` に統一されています。仮想 H/W 状態の確認は `gar sim env status --json` を使います。AI がブラウザ操作をしなくても検証できる入口です。

| コマンド | 実行場所 | 目的 | 主な処理 | 主な変数 |
|---|---|---|---|---|
| `gar sim ui button press 17` | Gapless Agent Runtime (venv) | Button17 を短押し | bridge API 経由で gpio-sim input を更新 | `--duration-ms` |
| `gar sim ui rfid tap 04:AB:CD:EF:01:23` | Gapless Agent Runtime (venv) | RFID カードを置く | bridge API 経由で cuse_spi へ UID を反映 | UID |
| `gar sim env status --json` | Gapless Agent Runtime (venv) | 仮想 H/W 状態確認 | bridge API state を取得 | `--json` |
