# Gapless Agent Runtime — Agent Instructions

## プロジェクト概要

AI が最後まで動かせる組み込み開発コックピット。
Codespaces で ARM バイナリをビルドし、EC2（シミュレーション）または RasPi5（実機）で動かす。
同じバイナリ (`sensor_demo`) が両環境で動作することを実証済み。
人間は意図を指示し、AI はビルド、デプロイ、実行、仮想 H/W 操作、ログ確認を進める。

## AI オペレーションの原則（契約）

**AI（Codex / Copilot 等）は、原則として `gar` のサブコマンド経由で操作する。**
これは人間が押す操作と AI の操作を同じ「正解レール」に乗せ、品質と再現性を保つための契約。

- **生コマンド連打を避ける** — 生 `ssh` / 生 `aws` / 生シェルを直接叩くと、筋の悪い解（例: GPIO を CUSE 単独で解こうとする）に逃げやすい。まず `gar` のサブコマンドで表現できないか探す。
- **`gar` に無い操作は「生で叩く」のではなく「`gar` に足す」** — 不足を見つけたら、その場で生コマンドに逃げず、`gar` のサブコマンド追加を TODO 化する。`gar` = 人の操作面 ＋ AI が参照する実コマンドのドキュメント。
- **機械可読モードを使う** — AI が状態を判断するときは `--json` を付ける（例: `gar sim env diag --json`）。人間向けの整形出力をパースしない。
- **exit code を必ず見る** — 0 = 成功、非0 = 失敗。出力の体裁だけ見て「できた」と報告しない。実機能（例: LED トグルがパネルに反映）が確認できるまで done としない。

## 現在の重点作業

`gar setup` と Agent Terminal Bridge を整備中。

- `gar setup` は開発環境 / シミュレート環境 / 実機環境の状態をカテゴリ単位で確認する。
- AI から VSCode integrated terminal へ直接 sudo 入力を橋渡しするため、`tools/vscode-agentcockpit/` に VSCode extension プロトタイプを置いている。
- 次の作業者はまず `docs/09_AGENT_TERMINAL_BRIDGE.md` を読むこと。
- 方針: Extension Development Host を通常 UX に使わない。ローカルインストール導線と MCP server を追加して、AI と人間が同じ VSCode terminal 上で協業できるようにする。

---

## ターゲット構成

### EC2（シミュレーション環境）
- インスタンスID: `i-031e0e5f5f1325ddc`、リージョン: `ap-southeast-2`
- SSH Host名: `vibecode-graviton`（`~/.ssh/config` で管理）
- 起動: WSL2 で `gar sim boot`

### RasPi5（実機）
- IP: `192.168.0.21`（ローカルネットワーク）
- ADB: port `5555`（`adbd` が systemd で自動起動）

### Codespaces（ビルド環境）
- 名前: `glowing-capybara-5j6g4594j75c44j`
- SSH: `gh codespace ssh --codespace glowing-capybara-5j6g4594j75c44j`

---

## 環境の役割と境界（鉄則）

各環境には固定の役割がある。**SSH で入れること＝そこで何をしてもよい、ではない。**
特に EC2 は「たまたま今は Linux でログインできる」だけで、本来は **実機のスタンドイン
（将来はもっとプア／シェルやログインすら無い実行専用デバイスを想定）**。能力があること
を許可と取り違えないこと。

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

### 「EC2 にデプロイして」と言われたら

```bash
gh codespace ssh --codespace glowing-capybara-5j6g4594j75c44j
# Codespace build VM 内で、target software ごとの README / build script に従ってビルド
```

経路: Codespaces でビルド → WSL に成果物コピー → WSL から EC2 へ転送

```bash
gar sim env deploy
```

### 「実機にデプロイして」と言われたら

1. Codespaces でビルド:
   ```bash
   gh codespace ssh --codespace glowing-capybara-5j6g4594j75c44j
   # Codespace build VM 内で、target software ごとの README / build script に従ってビルド
   ```
2. WSL hub から実機へ転送:
   ```bash
   gar target deploy
   ```
   経路: Codespaces でビルド → WSL に成果物コピー → adb push → RasPi5

---

## 実行手順

### EC2 でシミュレーション起動（3 プロセス並行）

```bash
ssh vibecode-graviton

# ターミナル①: ブリッジ
~/venv/bin/python3 ~/web-bridge/bridge.py

# ターミナル②: I2C CUSE スタブ
sudo ~/cuse_i2c -f --devname=i2c-1
sudo chmod 666 /dev/i2c-1

# ターミナル②': SPI CUSE スタブ（MFRC-522 sim）
sudo ~/cuse_spi -f --devname=spidev0.0
sudo chmod 666 /dev/spidev0.0

# ターミナル③: アプリ本体（GPIO=gpio-sim / I2C=cuse_i2c / SPI=cuse_spi）
# ※ 上記は手動参照用。通常は `gar sim env start` が bridge/cuse_i2c/cuse_spi を一括起動する
~/sensor_demo
```

Antigravity で Remote SSH → vibecode-graviton → PORTS タブ 8080 を Simple Browser で開く。

### AI/CLI から EC2 シミュレーションを操作

`gar sim` の接続先 EC2 host は `gar setup` で `.gar/config.json` に保存する。

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

## EC2 の起動・停止

```bash
gar sim boot       # 起動 + SSH config 自動更新（--pull で git pull も実行）
gar sim shutdown   # 停止
gar sim status  # 状態確認
```

---

## ビルド成果物

| ファイル | 用途 |
|---|---|
| `app/sensor_demo` | 統合デモアプリ（GPIO + I2C OLED + SPI RFID） |
| `gar-tools/cuse-stubs/spi-stub/cuse_spi` | SPI CUSE スタブ（MFRC-522 sim、EC2 用） |
| `gar-tools/cuse-stubs/i2c-stub/cuse_i2c` | I2C CUSE スタブ（VL53L0X + SSD1306、EC2 用） |
| `gar-tools/cuse-stubs/test/gpio_led_button` | GPIO 単機能デモ |
| `gar-tools/cuse-stubs/test/vl53l0x_read` | VL53L0X 距離センサーテスト |
| `gar-tools/cuse-stubs/web-bridge/` | Web ブリッジ + HTML パネル |

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
