# AgentCockpit — Claude 指示プロンプト

## プロジェクト概要

AI が最後まで動かせる組み込み開発コックピット。
Codespaces でクロスコンパイルし、EC2（シミュレーション）または RasPi5（実機）で動かす。
同じバイナリ (`sensor_demo`) が両環境で動作することを実証済み。
人間は意図を指示し、AI はビルド、デプロイ、実行、仮想 H/W 操作、ログ確認を進める。

## 現在の重点作業

`agp init` と Agent Terminal Bridge を整備中。

- `agp init` は開発環境 / シミュレート環境 / 実機環境の状態をカテゴリ単位で確認する。
- AI から VSCode integrated terminal へ直接 sudo 入力を橋渡しするため、`tools/vscode-agentcockpit/` に VSCode extension プロトタイプを置いている。
- 次の作業者はまず `docs/09_AGENT_TERMINAL_BRIDGE.md` を読むこと。
- 方針: Extension Development Host を通常 UX に使わない。ローカルインストール導線と MCP server を追加して、AI と人間が同じ VSCode terminal 上で協業できるようにする。

---

## ターゲット構成

### EC2（シミュレーション環境）
- インスタンスID: `i-031e0e5f5f1325ddc`、リージョン: `ap-southeast-2`
- SSH Host名: `vibecode-graviton`（`~/.ssh/config` で管理）
- 起動: Windows PowerShell で `C:\VibeCode\ec2.ps1 start`

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
gh codespace ssh --codespace glowing-capybara-5j6g4594j75c44j -- \
  "cd /workspaces/AgentCockpit && make cross && make deploy-ec2 EC2=vibecode-graviton"
```

経路: Codespaces → scp → EC2（クラウド同士で直接転送）

### 「実機にデプロイして」と言われたら

1. Codespaces でビルド:
   ```bash
   gh codespace ssh --codespace glowing-capybara-5j6g4594j75c44j -- \
     "cd /workspaces/AgentCockpit && make cross"
   ```
2. Windows で取得・転送:
   ```powershell
   C:\VibeCode\raspi.ps1 deploy
   ```
   経路: Codespaces → gh codespace cp → Windows → adb push → RasPi5

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

```bash
make sim-start EC2=vibecode-graviton
make panel-button EC2=vibecode-graviton LINE=17
make panel-rfid EC2=vibecode-graviton UID=04:AB:CD:EF:01:23
make sim-state EC2=vibecode-graviton
make sim-logs EC2=vibecode-graviton
make sim-test EC2=vibecode-graviton
make diagnose EC2=vibecode-graviton
make sim-stop EC2=vibecode-graviton
```

詳細: `docs/07_AI_AGENT_OPERATIONS.md`

### RasPi5 で実機実行

```powershell
adb shell
```
```bash
# adb shell 内
~/sensor_demo
```

---

## EC2 の起動・停止

```powershell
C:\VibeCode\ec2.ps1 start   # 起動 + SSH config 自動更新 + リポジトリ自動 pull
C:\VibeCode\ec2.ps1 stop    # 停止
C:\VibeCode\ec2.ps1 status  # 状態確認
```

---

## ビルド成果物

| ファイル | 用途 |
|---|---|
| `app/sensor_demo` | 統合デモアプリ（GPIO + I2C OLED + SPI RFID） |
| `cuse-stubs/gpio-shim/gpio_shim.so` | GPIO LD_PRELOAD シム（EC2 用） |
| `cuse-stubs/spi-shim/spi_shim.so` | SPI LD_PRELOAD シム（MFRC-522 sim、EC2 用） |
| `cuse-stubs/i2c-stub/cuse_i2c` | I2C CUSE スタブ（VL53L0X + SSD1306、EC2 用） |
| `cuse-stubs/test/gpio_led_button` | GPIO 単機能デモ |
| `cuse-stubs/test/vl53l0x_read` | VL53L0X 距離センサーテスト |
| `cuse-stubs/web-bridge/` | Web ブリッジ + HTML パネル |
