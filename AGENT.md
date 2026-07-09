# Gapless Agent Runtime — Agent Instructions

## プロジェクト概要

→ 詳細は [README.md](README.md) を参照。

## AI オペレーションの原則（契約）

**AI（Codex / Copilot 等）も、原則として `gar` のサブコマンド経由で操作する。**
これは人間が実施する操作と AI の操作を同じ「正解レール」に乗せ、品質と再現性を保つための契約。

> **rtk を使う**: `run_in_terminal` で長い出力が予想されるコマンドには `rtk` を付けてトークンを節約する。
> 例: `rtk git status` / `rtk git log` / `rtk grep` / `rtk python3 -m pytest`

### Workspace / sibling repo 注意

GAR 関連作業では、VS Code のアクティブファイルや CWD が
`gar-tools` / `gar-build-env` / `embedded-poc-app` などの兄弟リポジトリを
指していても、本ファイルと `docs/02_ARCHITECTURE.md` /
`docs/03_DEVELOPMENT_ENVIRONMENT.md` を運用正本として先に読むこと。

`/home/user/Yurufuwa` 配下の代表的な sibling repo:

- `GaplessAgentRuntime/`: 操作規約・アーキテクチャ正本
- `gar-tools/`: CUSE stubs、ESP32/M5Stack firmware runner、Renode/QEMU足場
- `gar-build-env/`: Codespaces/devcontainer build hub
- `embedded-poc-app/`: ARM64 target app

AI は CWD やエディタのアクティブファイルだけから運用境界を推測しない。
GAR 系 sibling repo に入ったら、まず本リポジトリの規約へ戻って環境の役割
（WSL=control plane、Codespaces=build、EC2/RasPi5=execution）を確認する。

### GAR を「使う作業」と GAR 自体の修正を混ぜない

GAR は **開発環境・操作面・検証足場** であり、完成させたいシステムそのものの
実行環境ではない。GAR のコマンドに実行時コンポーネントのプロセス管理を安易に
取り込まないこと。

この区別が必要になった背景:

- M5StickC Plus2 / Vibe Remote の検証中、Local Bridge を安定起動したくなり、
  一度 `gar vibe-remote bridge start/status/stop` のような案を実装しかけた。
- しかし Local Bridge は、Vibe Remote extension と Host OS 上の bridge が構成する
  **Vibe Remote 実行時コンポーネント**であり、GAR の責務ではない。
- GAR から実行時コンポーネントを管理し始めると、GAR が開発支援ツールではなく
  アプリ本体の process manager になってしまい、責務境界が崩れる。

判断基準:

| 作業 | 所在 |
|---|---|
| Codespaces でビルドする、artifact を取得する、flash する、usbipd attach を支援する | GAR に置いてよい |
| シミュレーション対象を操作する、仮想デバイスを押す、診断ログを取る | GAR に置いてよい |
| VS Code extension の UI/command、Local Bridge の開始・停止・状態表示、mDNS/LAN proxy の実行管理 | Vibe Remote 側に置く |
| M5 firmware のアプリ挙動、ボタン割り当て、画面表示、WebSocket protocol | Vibe Remote / m5stickc-client 側に置く |

次のエージェントへの注意:

- 「GAR を使って開発を進める」ことと「GAR 自身を拡張する」ことを分けて考える。
- GAR に機能を足す前に、それが **開発支援/仮想操作/成果物搬送** なのか、
  **対象システムの実行時機能** なのかを確認する。
- 対象システムの実行時機能なら、まず対象リポジトリ側
  （例: `gar-vibe-ui/vibe-remote` の VS Code extension / npm scripts / firmware）へ置く。
- GAR 側には、必要なら「その対象リポジトリの開発手順を呼び出す薄い入口」や
  「artifact/flash/diagnostic」だけを置く。
- 迷った場合は、ユーザーに「これは GAR の開発環境機能として残すべきか、
  対象システム側の実行時機能として移すべきか」を確認する。

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

MCP server (`tools/gar-mcp`) は VSCode 以外の Agent（Claude Desktop / Cursor 等）向けの補助的な互換口として最小限維持し、機能の主役にはしない。

### Vibe Remote MCP を使う応答待ち

Vibe Remote MCP が利用可能なセッションでは、人間の判断待ちをチャット本文だけに閉じ込めず、
M5StickC / Wokwi M5 の小型UIにも出す。

標準の操作モデル:

| ボタン | 意味 |
|---|---|
| A | 選択 / 決定 |
| B | メニュー次項目へ |
| P | 戻る / キャンセル |

AI が人間判断を待つ場合:

1. `vibe_remote_request_decision` か `vibe_remote_show_ui` を呼び、`mode: "menu"` のUIを出す。
2. チャットにも同じ質問を短く書く。
3. `vibe_remote_get_action` を呼び、M5/Wokwiからの選択を回収する。
4. デバイス入力とチャット入力の両方が来た場合は、最新の明示入力を優先し、必要なら一言確認する。
5. 完了時は `vibe_remote_clear_ui` と `vibe_remote_set_status` / `vibe_remote_clear_status` で表示を片付ける。

Vibe Remote MCP がツール一覧に無いセッションでは、通常のチャット確認にフォールバックする。

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

## 接続設定の確認

各環境の接続先は `.gar/config.json` に保存される（`gar setup` で設定）。現在の設定値は `gar setup` または `cat .gar/config.json` で確認すること。

- **SSH 設定**: `gar sim boot` / `gar sim infra apply` が `~/.ssh/config` の HostName を更新する
- **Codespaces 名**: `gh codespace list` で確認
- **RasPi5**: `gar target status` で確認

---

## 環境の役割と境界（鉄則）

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

## デプロイ手順

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

## 実行手順

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

詳細: [docs/06_SIMULATION.md](docs/06_SIMULATION.md)

### RasPi5 で実機実行

実機接続は adb を既定としている（社内環境で複数 NIC が使えない構成に合わせるため）。ネットワーク越しに到達できる環境では、`gar setup` の実機環境カテゴリで `SSH / scp` provider を選べ、`gar target deploy --host <ssh-host>` で転送できる（詳細: [docs/01_COMMAND_REFERENCE.md](docs/01_COMMAND_REFERENCE.md)）。

```powershell
adb shell
```
```bash
# adb shell 内
~/sensor_demo
```

---

## Simulation 環境の起動・停止

```bash
gar sim boot       # 起動 + SSH config 自動更新（--pull で git pull も実行）
gar sim shutdown   # 停止
gar sim status  # 状態確認
```

---

## ビルド成果物

| ファイル | 用途 |
|---|---|
| `../embedded-poc-app/app/sensor_demo` | 統合デモアプリ（GPIO + I2C OLED + SPI RFID） |
| `gar-tools/targets/linux-device/runtime/spi-stub/cuse_spi` | SPI CUSE スタブ（MFRC-522 sim、EC2 用） |
| `gar-tools/targets/linux-device/runtime/i2c-stub/cuse_i2c` | I2C CUSE スタブ（VL53L0X + SSD1306、EC2 用） |
| `gar-tools/targets/linux-device/runtime/test/gpio_led_button` | GPIO 単機能デモ |
| `gar-tools/targets/linux-device/runtime/test/vl53l0x_read` | VL53L0X 距離センサーテスト |
| `gar-tools/targets/linux-device/runtime/web-bridge/` | Web ブリッジ + HTML パネル |

---

## 既知の制約・トラブルシューティング

### Antigravity-IDE (Windows) からの FUSE マウントへのアクセス制限 (EPERM)
Antigravity-IDE は Windows ネイティブなアプリケーションであり、WSL 内のファイルには Windows のファイル共有（9Pプロトコル経由: `\\wsl.localhost\...`）でアクセスします。
WSL 内で `sshfs` 等の FUSE でマウントしたディレクトリ（例: `gar code start` でマウントした `codespaces/`）に対して、Windows 側からアクセスしようとすると、FUSE のセキュリティ機構（「マウントしたユーザー自身しかアクセスできない」という制限）に弾かれ、**EPERM (Permission denied)** エラーが発生します。

**【回避策】**
1. **VSCode を Remote-WSL で使う（推奨）**
   VSCode の「Remote - WSL」拡張機能を使って開く（`code .`）と、プロセスが Linux 側で動くため、権限エラーは発生せず正常に読み書きできます。（※このエラーが出るのは、VSCode を Windows パス `\\wsl.localhost\...` で直接開いているか、Antigravity-IDE 自身がアクセスしようとした時のみです）
2. **`allow_other` を使う**
   どうしても Windows 側（Antigravity-IDE 等）から監視させたい場合は、Linux 側の `/etc/fuse.conf` で `user_allow_other` を有効化し、`sshfs` に `-o allow_other` オプションを渡す必要があります。

---

## オプション: rtk（トークン削減プロキシ）

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
