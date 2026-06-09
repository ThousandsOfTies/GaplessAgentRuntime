## bridge HTTP API（内部仕様）

`gar sim ...` は内部で下記の `bridge.py` HTTP API を SSH 越しに叩いています。直接叩く必要は通常ありませんが、参照用に残します。`bridge.py` は Web Panel 用の WebSocket と HTTP API を持ち、状態変更は同じ仮想 H/W 操作関数を通るため、Panel と自動試験の挙動がずれにくい構成です。

| Endpoint | Method | 用途 | 対応 `gar` コマンド |
|---|---|---|---|
| `/api/state` | GET | 現在の仮想 H/W 状態を取得 | `gar sim env status --json` |
| `/api/button` | POST | GPIO ボタン状態を直接セット | `gar sim ui button set` |
| `/api/button/press` | POST | GPIO ボタンを押して離す | `gar sim ui button press` |
| `/api/rfid/tap` | POST | RFID カードを置く | `gar sim ui rfid tap` |
| `/api/rfid/remove` | POST | RFID カードを外す | `gar sim ui rfid remove` |
| `/api/range` | POST | VL53L0X の距離値をセット | `gar sim ui range set` |

例（参照用の生コマンド）:

```bash
curl -s -X POST "http://127.0.0.1:8080/api/button/press?line=17&duration_ms=150"
curl -s -X POST "http://127.0.0.1:8080/api/rfid/tap?uid=04:AB:CD:EF:01:23"
curl -s http://127.0.0.1:8080/api/state
```

---
