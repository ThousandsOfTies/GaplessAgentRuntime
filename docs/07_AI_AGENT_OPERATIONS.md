# AgentCockpit 操作ガイド

AgentCockpit の狙いは、開発者が手順を覚えて操作する環境ではなく、**VSCode 上で AI エージェントがビルド、デプロイ、実行、仮想 H/W 操作、ログ確認まで担える環境**にすることです。

そのために、EC2 simulation runtime は `agp sim`、ブラウザの Virtual Hardware Panel と同じ操作は HTTP API と Make ターゲットから実行できるようにしています。

人間は「何をしたいか」を指示し、AI はコックピット上の `agp` コマンド / Make ターゲット / HTTP API / ログを使って最後まで進めます。

AgentCockpit で AI に任せたい作業は、アプリ機能の実装だけではありません。実機互換シミュレーションのように、人手では採算が合いにくく、実機検証が始まるとメンテされず腐りやすい runtime を、AI が継続的に直せる状態にすることも重要な狙いです。

---

## 基本方針

| 人間向け | AI エージェント向け |
|---|---|
| Web Panel で LED / ボタン / RFID / OLED を見る | `agp sim ui button/rfid/range` と `agp sim env status --json` で仮想 H/W を操作・観察する |
| SSH でログを見る | `agp sim env log` / `agp sim env diag`（AI は `agp sim env diag --json`）で観察する |
| 手順書を読みながら実行する | `agp` コマンドと Make ターゲットを組み合わせて実行する |

AIに任せたい操作は、なるべく「短く、明示的で、再実行しやすいコマンド」にします。

---

## EC2 シミュレータ操作

`agp sim` の接続先 EC2 host は `agp setup` で `.agp/config.json` に保存します。

```bash
# agp-build-env Codespace でビルドし、成果物を WSL hub 経由で EC2 へ転送

# EC2 上でテスト用 /dev/* runtime を起動
# Hardware Panel 用の 8080/8765 port forward も同時に開始
agp sim env start

# VS Code terminal profile "EC2 Simulation" などから EC2 へ入り、
# 本番と同じアプリ起動手順を実行
~/sensor_demo

# ログ確認
agp sim env log

# プロセス、デバイス、API状態をまとめて確認
agp sim env diag

# 代表操作を実行
agp sim ui button press 17
agp sim ui rfid tap 04:AB:CD:EF:01:23
agp sim env status --json

# 停止
agp sim env stop
```

---

## 仮想 H/W 操作

人間も AI も入口は `agp sim ...` に統一。接続先 EC2 host は `agp setup` で `.agp/config.json` に保存されるため `--host` は省略可。

```bash
# GPIO17 ボタンを短押し
agp sim ui button press 17 --duration-ms 150

# ボタン状態を直接セット（0=離す / 1=押す）
agp sim ui button set 17 1

# RFID カードをタップ / 外す
agp sim ui rfid tap 04:AB:CD:EF:01:23
agp sim ui rfid remove

# VL53L0X 距離センサー値を変更
agp sim ui range set 450

# 仮想 H/W の現在状態（OLED framebuf 含む）を取得
agp sim env status --json

# port forward と bridge の共有状態を確認
agp sim env status
```

---

## bridge HTTP API（内部仕様）

`agp sim ...` は内部で下記の `bridge.py` HTTP API を SSH 越しに叩いています。直接叩く必要は通常ありませんが、参照用に残します。`bridge.py` は Web Panel 用の WebSocket と HTTP API を持ち、状態変更は同じ仮想 H/W 操作関数を通るため、Panel と自動試験の挙動がずれにくい構成です。

| Endpoint | Method | 用途 | 対応 `agp` コマンド |
|---|---|---|---|
| `/api/state` | GET | 現在の仮想 H/W 状態を取得 | `agp sim env status --json` |
| `/api/button` | POST | GPIO ボタン状態を直接セット | `agp sim ui button set` |
| `/api/button/press` | POST | GPIO ボタンを押して離す | `agp sim ui button press` |
| `/api/rfid/tap` | POST | RFID カードを置く | `agp sim ui rfid tap` |
| `/api/rfid/remove` | POST | RFID カードを外す | `agp sim ui rfid remove` |
| `/api/range` | POST | VL53L0X の距離値をセット | `agp sim ui range set` |

例（参照用の生コマンド）:

```bash
curl -s -X POST "http://127.0.0.1:8080/api/button/press?line=17&duration_ms=150"
curl -s -X POST "http://127.0.0.1:8080/api/rfid/tap?uid=04:AB:CD:EF:01:23"
curl -s http://127.0.0.1:8080/api/state
```

---

## シナリオ自動試験

仮想 H/W 操作は JSON シナリオとして定義できます。AI Agent や CI は、同じシナリオを繰り返し実行することで、手順の再現性を確保できます。

```bash
agp sim ui button press 17
agp sim ui rfid tap 04:AB:CD:EF:01:23
agp sim env status --json
```

シナリオ例:

```json
{
  "name": "sensor_demo system-on rfid flow",
  "steps": [
    { "action": "button_press", "line": 17, "duration_ms": 150 },
    { "action": "wait", "seconds": 0.5 },
    { "action": "rfid_tap", "uid": "04:AB:CD:EF:01:23" },
    { "action": "expect", "path": "spi.mfrc522.present", "equals": true }
  ]
}
```

対応アクション:

| action | 用途 |
|---|---|
| `button_press` | GPIOボタンを押して離す |
| `button_set` | GPIOボタン状態を直接セット |
| `rfid_tap` | RFIDカードを置く |
| `rfid_remove` | RFIDカードを外す |
| `range_set` | VL53L0X の距離値をセット |
| `wait` | 指定秒数待つ |
| `expect` | `/api/state` の値を検証する |

---

## AI に依頼するタスク例

```text
sensor_demo を EC2 にデプロイして、シミュレーション用の /dev runtime を起動し、EC2 にログインして `~/sensor_demo` を起動してください。そのあと GPIO17 を押して System ON にしてから RFID をタップし、OLED とログを確認して UID が表示されるか見てください。
```

この依頼は、AIが次のように分解できます。

```bash
# agp-build-env Codespace でビルドし、成果物を WSL hub 経由で EC2 へ転送済み
agp sim env start
# VS Code terminal profile "EC2 Simulation" などから EC2 へログイン
~/sensor_demo
agp sim ui button press 17
agp sim ui rfid tap 04:AB:CD:EF:01:23
agp sim env status --json
agp sim env status
agp sim env log
```

---

## Agent 体験の磨き込み方針

AgentCockpit の主戦場は **VSCode (Antigravity / Copilot Chat 等) の Agent モード**です。Agent はファイル編集・terminal 実行・タスク実行の機能を既に備えているため、AgentCockpit が独自プロトコルを増やすのではなく、**`agp` CLI を Agent から叩きやすい形に磨く**ことを差別化の軸とします。

MCP server (`tools/agentcockpit-mcp`) は VSCode 以外の Agent (Claude Desktop, Cursor 等) からも繋げる**補助的な互換口**として最小限維持し、機能の主役にはしません。

具体的な改善方針:

| 項目 | 内容 | 受益者 |
|---|---|---|
| `--json` 出力モード | `agp sim env diag --json` を実装済み（processes / devices / api / ok を構造化出力）。他コマンドへも順次展開 | VSCode Agent / CI |
| 構造化ログ + 末尾 summary | `agp sim env diag` の最後に "OK / FAIL: <理由>" の 1 行 summary を出し、Agent が 1 ターンで判断できるようにする | VSCode Agent |
| `.vscode/tasks.json` テンプレート | `agp setup` で代表タスク (sim start / stop / deploy / button press 等) を仕込み、Agent の `run_task` から呼べるようにする | VSCode Agent |
| copilot-instructions.md / AGENT.md の作法強化 | "まず `agp sim env status` を確認する" 等の手順を Agent に学習させる | VSCode Agent |
| `agp terminal run` の活用 | 長時間実行やインタラクティブ操作は可視 terminal に出して、人間が割り込めるようにする | 人間 + Agent |

このアプローチは、買い手が普段使う VSCode 環境の中で価値が増えるため、MCP エコシステム全体を保守する責任を負わずに済みます。

---

## 今後の改善候補

- OLED framebuffer の期待値チェックを追加する
- `/api/events` で操作履歴を取得する
- 実機 RasPi5 にも同じ `run / logs / diagnose` 抽象を用意する
- `agp sim run <target>` / `agp target run <target>` を共通 manifest 化する
- `agp sim run <target>` / `agp target run <target>` を共通 manifest 化し、`~/sensor_demo` 起動後の検証ログ収集まで `agp` に畳む
- systemd 化して EC2 上の起動/停止を安定させる
