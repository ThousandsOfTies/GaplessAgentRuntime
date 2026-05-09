# ExperimentalDevEnv — Claude 指示プロンプト

## プロジェクト概要

組み込みHWシミュレーション開発環境。
Codespaces でクロスコンパイルし、EC2（シミュレーション）または RasPi5（実機）で動かす。

---

## ターゲット構成

### EC2（シミュレーション環境）
- インスタンスID: `i-031e0e5f5f1325ddc`、リージョン: `ap-southeast-2`
- SSH Host名: `vibecode-graviton`（`~/.ssh/config` で管理）
- 起動: Windows PowerShell で `.\ec2.ps1 start`（`c:\VibeCode\ec2.ps1`）

### RasPi5（実機）
- IP: `192.168.0.21`（ローカルネットワーク）
- ADB: port `5555`（`adbd` が systemd で自動起動）

### Codespaces（ビルド環境）
- 名前: `glowing-capybara-5j6g4594j75c44j`
- SSH: `gh codespace ssh --codespace glowing-capybara-5j6g4594j75c44j`

---

## デプロイ手順

### 「EC2 にデプロイして」と言われたら

1. Codespaces に SSH でログイン
2. ビルド・デプロイ実行:
   ```bash
   cd /workspaces/ExperimentalDevEnv/cuse-stubs
   make cross
   make deploy EC2=vibecode-graviton
   ```
   経路: Codespaces → scp → EC2（クラウド同士で直接転送）

### 「実機にデプロイして」と言われたら

1. Codespaces に SSH でログイン
2. ビルド実行:
   ```bash
   cd /workspaces/ExperimentalDevEnv/cuse-stubs
   make cross
   ```
3. Windows PowerShell でファイル取得 & 転送:
   ```powershell
   .\raspi.ps1 deploy
   ```
   経路: Codespaces → gh codespace cp → Windows → adb push → RasPi5

---

## 実行手順

### EC2 での実行
```bash
# ターミナル①: ブリッジ起動
ssh vibecode-graviton
~/venv/bin/python3 ~/web-bridge/bridge.py

# ターミナル②: GPIO デモ
ssh vibecode-graviton
LD_PRELOAD=~/gpio_shim.so ~/gpio_led_button
```
Antigravity で Remote SSH → vibecode-graviton → PORTS タブ 8080 を Simple Browser で開く。

### RasPi5 での実行
```powershell
adb shell
# shell 内で
./gpio_led_button
```

---

## EC2 の起動・停止

```powershell
.\ec2.ps1 start   # 起動 + SSH config 自動更新
.\ec2.ps1 stop    # 停止
.\ec2.ps1 status  # 状態確認
```

---

## ビルド成果物

| ファイル | 用途 |
|---|---|
| `gpio_shim.so` | GPIO LD_PRELOAD シム（EC2 用） |
| `gpio_led_button` | GPIO LED+ボタン デモ |
| `cuse_i2c` | I2C CUSE スタブ |
| `vl53l0x_read` | VL53L0X 距離センサー テストクライアント |
| `web-bridge/` | ハードウェアパネル（Python + HTML） |
