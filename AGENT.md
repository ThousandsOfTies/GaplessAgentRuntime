# Gapless Agent Runtime — Agent Instructions

﻿## プロジェクト概要

→ 詳細は [README.md](../README.md) を参照。

﻿## AI オペレーションの原則（契約）

**AI（Codex / Copilot 等）も、原則として `gar` のサブコマンド経由で操作する。**
これは人間が実施する操作と AI の操作を同じ「正解レール」に乗せ、品質と再現性を保つための契約。

> **rtk を使う**: `run_in_terminal` で長い出力が予想されるコマンドには `rtk` を付けてトークンを節約する。
> 例: `rtk git status` / `rtk git log` / `rtk grep` / `rtk python3 -m pytest`

この契約には三つの目的がある。

1. **人間への透明性** — `gar` のサブコマンド体系を見れば、Gapless Agent Runtime が何をできるかが一覧できる。AI が何をしているかを人間が常に把握できる状態を保つ。
2. **AI の操作ブレを減らす** — 都度の判断で異なるコマンドを選ぶ揺らぎをなくし、同じ意図が常に同じ操作に対応するようにする。
3. **シームレスな引き継ぎ** — AI が行き詰まったとき、人間が同じ `gar` コマンドで違和感なく続きを引き取れる。AI と人間の操作面を統一することで、セッションが途切れても文脈が失われない。

### AI と人間の役割分担

| 役割 | 人間 | AI エージェント |
|---|---|---|
| **操作** | AI への指示、結果の確認・判断 | ビルド・デプロイ・H/W 操作・ログ収集・診断・結果整理 |
| **観察** | Web Panel で LED / ボタン / RFID / OLED を見る | `gar sim ui button/rfid/range` と `gar sim env diag --json` で操作・観察 |
| **ログ** | SSH でログを見る | `gar sim env log` / `gar sim env diag --json` で観察 |

### Agent 体験の磨き込み方針

Gapless Agent Runtime の主戦場は **VSCode Agent モード**。独自プロトコルを増やすのではなく、**`gar` CLI を Agent から叩きやすい形に磨く**ことを差別化の軸とする。

MCP server (`tools/agentcockpit-mcp`) は VSCode 以外の Agent（Claude Desktop / Cursor 等）向けの補助的な互換口として最小限維持し、機能の主役にはしない。

| 改善項目 | 内容 |
|---|---|
| `--json` 出力モード | `gar sim env diag --json` 実装済み。他コマンドへも順次展開 |
| 構造化ログ + 末尾 summary | diag 系の最後に "OK / FAIL: 理由" の 1 行 summary を出し、AI が 1 ターンで判断できるようにする |
| `.vscode/tasks.json` テンプレート | `gar setup` で代表タスクを仕込み、AI の `run_task` から呼べるようにする |
| `gar terminal run` の活用 | 長時間実行やインタラクティブ操作は可視 terminal に出して人間が割り込めるようにする |



- **生コマンド連打を避ける** — 生 `ssh` / 生 `aws` / 生シェルを直接叩くと、筋の悪い解（例: GPIO を CUSE 単独で解こうとする）に逃げやすい。まず `gar` のサブコマンドで表現できないか探す。
- **`gar` に無い操作は「生で叩く」のではなく「`gar` に足す」** — 不足を見つけたら、その場で生コマンドに逃げず、`gar` のサブコマンド追加を TODO 化する。`gar` = 人の操作面 ＋ AI が参照する実コマンドのドキュメント。
- **機械可読モードを使う** — AI が状態を判断するときは `--json` を付ける（例: `gar sim env diag --json`）。人間向けの整形出力をパースしない。
- **exit code を必ず見る** — 0 = 成功、非0 = 失敗。出力の体裁だけ見て「できた」と報告しない。実機能（例: LED トグルがパネルに反映）が確認できるまで done としない。

### Terminal 操作の原則

AI は通常作業を裏で実行し、結果を自分で確認する。
VSCode integrated terminal は、sudo password・GitHub 認証・クラウド認証・デバイス pairing など、**人間の入力が必要な時だけ**使う。

**裏で実行する（terminal 不要）:**
- `which gh` / `aws --version` / `adb version` などのバージョン確認
- `gar setup --no-install`
- build / test / lint
- log file・`.gar/config.json`・status file の確認

**visible terminal に handoff する:**
- `sudo` が必要な install / setup
- `gh auth login` / `aws configure sso` などの cloud login
- device code / browser auth / pairing

handoff 時、AI は password や token を要求しない。「どの terminal で何を入力すべきか」だけを伝える。

AI が送ってはいけない入力: sudo password / GitHub・cloud auth token / device code / private key・passphrase

**Terminal Bridge の位置づけ**: 通常の command runner ではなく人間入力の受け皿。AI は terminal buffer を読もうとせず、裏で状態確認コマンドを実行して復帰する。

### `gar setup` の進め方

1. 裏で `gar setup --no-install` を実行して不足項目を確認する。
2. 依存コマンドがすべてある項目はそのまま完了として扱う。
3. 不足があり sudo/auth 不要なら、AI が裏で解決できるか試す。
4. sudo/auth が必要なら `.gar/terminal-requests/*.json` を作り、ユーザーに integrated terminal で入力してもらう。
5. `which ...` や `gar setup --no-install` を裏で再実行し、次の不足項目へ進む。

### handoff 後の復帰手順

何が起きたかわからない場合、terminal buffer を読もうとせず以下を確認する:

```bash
gar setup --no-install
which gh && gh --version
which aws && aws --version
which adb && adb version
find .gar -maxdepth 3 -type f | sort
```

﻿## 接続設定の確認

各環境の接続先は `.gar/config.json` に保存される（`gar setup` で設定）。現在の設定値は `gar setup` または `cat .gar/config.json` で確認すること。

- **SSH 設定**: `ssh_config.template` → `~/.ssh/config`（`gar sim boot` が HostName を自動更新）
- **Codespaces 名**: `gh codespace list` で確認
- **RasPi5**: `gar target status` で確認

---

﻿## 環境の役割と境界（鉄則）

各環境には固定の役割がある。**SSH で入れること＝そこで何をしてもよい、ではない。**
特に EC2 は「たまたま今は Linux でログインできる」だけで、本来は **実機のスタンドイン（将来はもっとプア／シェルやログインすら無い実行専用デバイスを想定）**。
能力があることを許可と取り違えないこと。

| 環境 | 役割 | やってよい | **やってはいけない** |
|---|---|---|---|
| **Codespaces** | ビルド | cross-compile、成果物生成 | — |
| **WSL** | コントロールプレーン | `gar` 発信、成果物中継、deploy | ターゲット用バイナリのビルド |
| **EC2 / RasPi5** | 実行（ターゲット） | 配布されたバイナリの起動・実行 | **ツールチェーン導入・`make`・コンパイル・ビルド環境構築** |

- **ビルドは必ず Codespaces**。EC2/RasPi5 上で `make` / `gcc` / `apt install build-*` 等を
  実行しない。「ビルドできる場所が目の前にある」からといって EC2 で組まない。
- ARM 向け成果物も **Codespaces で cross-build → WSL 経由で EC2/実機へ deploy → ターゲットは起動のみ**。
- EC2 にビルド環境を生やそうとしている自分に気づいたら、それは役割違反。手を止めて Codespaces 経路に戻す。

---

﻿## デプロイ手順

### 「VM（シミュレーション環境）にデプロイして」と言われたら

**target app を VM に転送する（実行テスト用）:**

```bash
gar sim deploy
```

経路: Codespaces でビルド → WSL に成果物コピー → WSL から VM へ転送  
（`artifact.json` の `deploy.sim` セクション）

**VM の仮想 H/W 環境（CUSE stubs, web-bridge）を更新する:**

```bash
gar sim env deploy
```

（`artifact.json` の `deploy.sim_env` セクション）

> `artifact.json` の例:
> ```json
> {
>   "deploy": {
>     "app":     { "files": [{ "src": "sensor_demo", "dest": "~/sensor_demo", "mode": "755" }] },
>     "sim_env": { "files": [{ "src": "cuse_i2c",    "dest": "~/cuse_i2c",    "mode": "755" }] }
>   }
> }
> ```

### 「実機にデプロイして」と言われたら

1. Codespaces でビルド:
   ```bash
   gh codespace ssh  # GAR_CODESPACE_NAME または gh codespace list で確認
   # Codespace build VM 内で、target software ごとの README / build script に従ってビルド
   ```
2. WSL hub から実機へ転送:
   ```bash
   gar target deploy
   ```
   経路: Codespaces でビルド → WSL に成果物コピー → adb push → RasPi5

---

﻿## 実行手順

### VM でシミュレーション起動

bridge / CUSE スタブ（I2C・SPI）/ gpio-sim は systemd unit で管理されており、`gar sim env start` で一括起動する。

```bash
# WSL から: runtime サービス起動 + port forward 開始
gar sim env start

# EC2 に SSH してアプリ本体を起動
ssh vibecode-graviton
~/sensor_demo
```

Hardware Panel の確認: VSCode の PORTS タブで 8080 のリンクをクリックすると Simple Browser 内に表示される。

### AI/CLI から VM シミュレーションを操作

`gar sim` の接続先host は `gar setup` で `.gar/config.json` に保存する。

```bash
gar sim env start
gar sim ui button press 17
gar sim ui rfid tap 04:AB:CD:EF:01:23
gar sim ui range set 300
gar sim env status --json
gar sim env status
gar sim env log
gar sim env diag --json
gar sim env stop
```

詳細: `docs/07_AI_AGENT_OPERATIONS.md`

### RasPi5 で実機実行

実機接続は adb を既定としている（社内環境で複数 NIC が使えない構成に合わせるため）。ネットワーク越しに到達できる環境では、`gar setup` の実機環境カテゴリで `SSH / scp` provider を選べ、`gar target deploy --host <ssh-host>` で転送できる（詳細: [docs/11_COMMAND_REFERENCE.md](docs/11_COMMAND_REFERENCE.md)）。

```powershell
adb shell
```
```bash
# adb shell 内
~/sensor_demo
```

---

﻿## Simulation 環境の起動・停止

```bash
gar sim boot       # 起動 + SSH config 自動更新（--pull で git pull も実行）
gar sim shutdown   # 停止
gar sim status  # 状態確認
```

---

﻿## ビルド成果物

| ファイル | 用途 |
|---|---|
| `app/sensor_demo` | 統合デモアプリ（GPIO + I2C OLED + SPI RFID） |
| `gar-tools/cuse-stubs/spi-stub/cuse_spi` | SPI CUSE スタブ（MFRC-522 sim、EC2 用） |
| `gar-tools/cuse-stubs/i2c-stub/cuse_i2c` | I2C CUSE スタブ（VL53L0X + SSD1306、EC2 用） |
| `gar-tools/cuse-stubs/test/gpio_led_button` | GPIO 単機能デモ |
| `gar-tools/cuse-stubs/test/vl53l0x_read` | VL53L0X 距離センサーテスト |
| `gar-tools/cuse-stubs/web-bridge/` | Web ブリッジ + HTML パネル |

---

﻿## 既知の制約・トラブルシューティング

### Antigravity-IDE (Windows) からの FUSE マウントへのアクセス制限 (EPERM)
Antigravity-IDE は Windows ネイティブなアプリケーションであり、WSL 内のファイルには Windows のファイル共有（9Pプロトコル経由: `\\wsl.localhost\...`）でアクセスします。
WSL 内で `sshfs` 等の FUSE でマウントしたディレクトリ（例: `gar code start` でマウントした `codespaces/`）に対して、Windows 側からアクセスしようとすると、FUSE のセキュリティ機構（「マウントしたユーザー自身しかアクセスできない」という制限）に弾かれ、**EPERM (Permission denied)** エラーが発生します。

**【回避策】**
1. **VSCode を Remote-WSL で使う（推奨）**
   VSCode の「Remote - WSL」拡張機能を使って開く（`code .`）と、プロセスが Linux 側で動くため、権限エラーは発生せず正常に読み書きできます。（※このエラーが出るのは、VSCode を Windows パス `\\wsl.localhost\...` で直接開いているか、Antigravity-IDE 自身がアクセスしようとした時のみです）
2. **`allow_other` を使う**
   どうしても Windows 側（Antigravity-IDE 等）から監視させたい場合は、Linux 側の `/etc/fuse.conf` で `user_allow_other` を有効化し、`sshfs` に `-o allow_other` オプションを渡す必要があります。

---

﻿## オプション: rtk（トークン削減プロキシ）

[rtk](https://github.com/rtk-ai/rtk) は LLM のトークン消費を 60-90% 削減する CLI プロキシ。
`git status` や `cargo test` などのコマンド出力をフィルタ・圧縮してから LLM に渡す。
**使わなくても動く。トークンやコストが気になる場合に入れる。**

### 有効にする手順（WSL2 で一度だけ）

```bash
# インストール
curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/refs/heads/master/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"  # 未追加なら ~/.bashrc にも追記

# GitHub Copilot (VS Code) 向けにフックを設定
rtk init -g --copilot
# → VS Code を再起動するとフックが有効になる

# Codex (OpenAI) 向け（AGENTS.md + RTK.md へのインストラクション注入）
rtk init -g --codex
# → フックではなく指示ベース。Codex が rtk コマンドを使うよう促される
```

### 確認

```bash
rtk --version   # バージョン表示
rtk gain        # トークン削減量の統計
```

### 無効にする

```bash
rtk init -g --uninstall
```

> **Copilot (VS Code) での動作**: `git status` などの Bash ツール呼び出しが自動で `rtk git status` に書き換えられる。
> `Read` / `Grep` など Copilot 組み込みツールはフックを経由しないため、明示的に `rtk read` / `rtk grep` と書いた場合のみ削減される。
>
> **Codex での動作**: フックではなく `AGENTS.md` + `RTK.md` へのインストラクション注入。Codex が判断して rtk を使う形になるため、自動書き換えではない。

