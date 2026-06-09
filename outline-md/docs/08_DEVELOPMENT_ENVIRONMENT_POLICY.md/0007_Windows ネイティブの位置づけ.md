## Windows ネイティブの位置づけ

**制御・操作は WSL2 上の `gar` に集約済み**です。simulation VM 起動・停止（`gar sim boot` / `gar sim shutdown`）も実機デプロイ（`gar target deploy`）も WSL2 から実行でき、Windows ネイティブは原則不要です。

USB-C 実機への adb も、`usbipd-win` を WSL2 から呼び出す `gar usb attach` で WSL2 に通せます。busid は自動検出・記憶されるので、初回の `usbipd bind`（管理者・一度だけ）以降は `gar usb attach` だけで実機が WSL2 に現れます。ネットワーク経由の SSH / scp provider（`gar target deploy --host <ssh-host>`）も選べます。

### 当面の Windows 入口（減らす対象）

次は依然として Windows から実行されることがありますが、いずれも「必須」ではなく「まだ残っている入口」です。

- VS Code / Antigravity からの接続（ホスト側 UI として）
- USB パススルー未設定環境での adb
- ブラウザや Simple Browser での確認

開発スクリプト全体を Windows ネイティブで完全対応させることはしません。`rm`, `cp`, `export`, `/tmp`, Bash 構文、パス区切り、改行コードなどの差分を吸収するためにスクリプトとドキュメントが複雑化するためで、そのコストはプロダクト本体や検証環境の整備に回します。


---
