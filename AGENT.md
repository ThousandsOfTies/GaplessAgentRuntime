# AgentCockpit — Agent Instructions

## プロジェクト概要

AI が最後まで動かせる組み込み開発コックピット。
Codespaces で ARM バイナリをビルドし、EC2（シミュレーション）または RasPi5（実機）で動かす。
同じバイナリ (`sensor_demo`) が両環境で動作することを実証済み。
人間は意図を指示し、AI はビルド、デプロイ、実行、仮想 H/W 操作、ログ確認を進める。

## AI オペレーションの原則（契約）

**AI（Codex / Copilot 等）は、原則として `agp` のサブコマンド経由で操作する。**
これは人間が押す操作と AI の操作を同じ「正解レール」に乗せ、品質と再現性を保つための契約。

- **生コマンド連打を避ける** — 生 `ssh` / 生 `aws` / 生シェルを直接叩くと、筋の悪い解（例: GPIO を CUSE 単独で解こうとする）に逃げやすい。まず `agp` のサブコマンドで表現できないか探す。
- **`agp` に無い操作は「生で叩く」のではなく「`agp` に足す」** — 不足を見つけたら、その場で生コマンドに逃げず、`agp` のサブコマンド追加を TODO 化する。`agp` = 人の操作面 ＋ AI が参照する実コマンドのドキュメント。
- **機械可読モードを使う** — AI が状態を判断するときは `--json` を付ける（例: `agp sim diag --json`）。人間向けの整形出力をパースしない。
- **exit code を必ず見る** — 0 = 成功、非0 = 失敗。出力の体裁だけ見て「できた」と報告しない。実機能（例: LED トグルがパネルに反映）が確認できるまで done としない。

## 現在の重点作業

`agp setup` と Agent Terminal Bridge を整備中。

- `agp setup` は開発環境 / シミュレート環境 / 実機環境の状態をカテゴリ単位で確認する。
- AI から VSCode integrated terminal へ直接 sudo 入力を橋渡しするため、`tools/vscode-agentcockpit/` に VSCode extension プロトタイプを置いている。
- 次の作業者はまず `docs/09_AGENT_TERMINAL_BRIDGE.md` を読むこと。
- 方針: Extension Development Host を通常 UX に使わない。ローカルインストール導線と MCP server を追加して、AI と人間が同じ VSCode terminal 上で協業できるようにする。

---

## ターゲット構成

### EC2（シミュレーション環境）
- インスタンスID: `i-031e0e5f5f1325ddc`、リージョン: `ap-southeast-2`
- SSH Host名: `vibecode-graviton`（`~/.ssh/config` で管理）
- 起動: WSL2 で `agp ec2 start`

### RasPi5（実機）
- IP: `192.168.0.21`（ローカルネットワーク）
- ADB: port `5555`（`adbd` が systemd で自動起動）

### Codespaces（ビルド環境）
- 名前: `glowing-capybara-5j6g4594j75c44j`
- SSH: `gh codespace ssh --codespace glowing-capybara-5j6g4594j75c44j`

---

## デプロイ手順

### 「EC2 にデプロイして」と言われたら

```bash
gh codespace ssh --codespace glowing-capybara-5j6g4594j75c44j
# Codespace build VM 内で、target software ごとの README / build script に従ってビルド
```

経路: Codespaces でビルド → WSL に成果物コピー → WSL から EC2 へ転送

```bash
agp sim deploy
```

### 「実機にデプロイして」と言われたら

1. Codespaces でビルド:
   ```bash
   gh codespace ssh --codespace glowing-capybara-5j6g4594j75c44j
   # Codespace build VM 内で、target software ごとの README / build script に従ってビルド
   ```
2. WSL hub から実機へ転送:
   ```bash
   agp native deploy
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

# ターミナル③: アプリ本体（シム経由）
LD_PRELOAD="$HOME/gpio_shim.so $HOME/spi_shim.so" ~/sensor_demo
```

Antigravity で Remote SSH → vibecode-graviton → PORTS タブ 8080 を Simple Browser で開く。

### AI/CLI から EC2 シミュレーションを操作

`agp sim` の接続先 EC2 host は `agp setup` で `.agp/config.json` に保存する。

```bash
agp sim start
make panel-button EC2=vibecode-graviton LINE=17
make panel-rfid EC2=vibecode-graviton UID=04:AB:CD:EF:01:23
agp sim status
agp sim log
make sim-test EC2=vibecode-graviton
agp sim diag
agp sim stop
```

詳細: `docs/07_AI_AGENT_OPERATIONS.md`

### RasPi5 で実機実行

実機接続は adb を既定としている（社内環境で複数 NIC が使えない構成に合わせるため）。ネットワーク越しに到達できる環境では、`agp setup` の実機環境カテゴリで `SSH / scp` provider を選べ、`agp native deploy --host <ssh-host>` で転送できる（詳細: [docs/11_COMMAND_REFERENCE.md](docs/11_COMMAND_REFERENCE.md)）。

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
agp ec2 start   # 起動 + SSH config 自動更新（--pull で git pull も実行）
agp ec2 stop    # 停止
agp ec2 status  # 状態確認
```

---

## ビルド成果物

| ファイル | 用途 |
|---|---|
| `app/sensor_demo` | 統合デモアプリ（GPIO + I2C OLED + SPI RFID） |
| `agp-tools/cuse-stubs/gpio-shim/gpio_shim.so` | GPIO LD_PRELOAD シム（EC2 用） |
| `agp-tools/cuse-stubs/spi-shim/spi_shim.so` | SPI LD_PRELOAD シム（MFRC-522 sim、EC2 用） |
| `agp-tools/cuse-stubs/i2c-stub/cuse_i2c` | I2C CUSE スタブ（VL53L0X + SSD1306、EC2 用） |
| `agp-tools/cuse-stubs/test/gpio_led_button` | GPIO 単機能デモ |
| `agp-tools/cuse-stubs/test/vl53l0x_read` | VL53L0X 距離センサーテスト |
| `agp-tools/cuse-stubs/web-bridge/` | Web ブリッジ + HTML パネル |

---

## 既知の制約・トラブルシューティング

### Antigravity-IDE (Windows) からの FUSE マウントへのアクセス制限 (EPERM)
Antigravity-IDE は Windows ネイティブなアプリケーションであり、WSL 内のファイルには Windows のファイル共有（9Pプロトコル経由: `\\wsl.localhost\...`）でアクセスします。
WSL 内で `sshfs` 等の FUSE でマウントしたディレクトリ（例: `agp code start` でマウントした `codespaces/`）に対して、Windows 側からアクセスしようとすると、FUSE のセキュリティ機構（「マウントしたユーザー自身しかアクセスできない」という制限）に弾かれ、**EPERM (Permission denied)** エラーが発生します。

**【回避策】**
1. **VSCode を Remote-WSL で使う（推奨）**
   VSCode の「Remote - WSL」拡張機能を使って開く（`code .`）と、プロセスが Linux 側で動くため、権限エラーは発生せず正常に読み書きできます。（※このエラーが出るのは、VSCode を Windows パス `\\wsl.localhost\...` で直接開いているか、Antigravity-IDE 自身がアクセスしようとした時のみです）
2. **`allow_other` を使う**
   どうしても Windows 側（Antigravity-IDE 等）から監視させたい場合は、Linux 側の `/etc/fuse.conf` で `user_allow_other` を有効化し、`sshfs` に `-o allow_other` オプションを渡す必要があります。
