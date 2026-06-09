## Agent 体験の磨き込み方針

Gapless Agent Runtime の主戦場は **VSCode (Antigravity / Copilot Chat 等) の Agent モード**です。Agent はファイル編集・terminal 実行・タスク実行の機能を既に備えているため、Gapless Agent Runtime が独自プロトコルを増やすのではなく、**`gar` CLI を Agent から叩きやすい形に磨く**ことを差別化の軸とします。

MCP server (`tools/agentcockpit-mcp`) は VSCode 以外の Agent (Claude Desktop, Cursor 等) からも繋げる**補助的な互換口**として最小限維持し、機能の主役にはしません。

具体的な改善方針:

| 項目 | 内容 | 受益者 |
|---|---|---|
| `--json` 出力モード | `gar sim env diag --json` を実装済み（processes / devices / api / ok を構造化出力）。他コマンドへも順次展開 | VSCode Agent / CI |
| 構造化ログ + 末尾 summary | `gar sim env diag` の最後に "OK / FAIL: <理由>" の 1 行 summary を出し、Agent が 1 ターンで判断できるようにする | VSCode Agent |
| `.vscode/tasks.json` テンプレート | `gar setup` で代表タスク (sim start / stop / deploy / button press 等) を仕込み、Agent の `run_task` から呼べるようにする | VSCode Agent |
| copilot-instructions.md / AGENT.md の作法強化 | "まず `gar sim env status` を確認する" 等の手順を Agent に学習させる | VSCode Agent |
| `gar terminal run` の活用 | 長時間実行やインタラクティブ操作は可視 terminal に出して、人間が割り込めるようにする | 人間 + Agent |

このアプローチは、買い手が普段使う VSCode 環境の中で価値が増えるため、MCP エコシステム全体を保守する責任を負わずに済みます。

---
