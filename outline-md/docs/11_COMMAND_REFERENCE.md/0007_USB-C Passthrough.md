## USB-C Passthrough

`gar usb` は USB-C 実機（ADB）を Windows の `usbipd-win` 経由で WSL2 に attach するモードです。WSL2 から Windows interop で `usbipd.exe` を呼び出します。busid は自動検出し、一度確定したものは `.gar/config.json` の `usb.busid` に記憶するので、2 回目以降は `gar usb attach` だけで済みます。

事前に **一度だけ** Windows の管理者 PowerShell で対象デバイスを共有します（再起動後も保持）。busid は `gar usb list` で確認できます。

```powershell
usbipd bind --busid <busid>
```

| コマンド | 実行場所 | 目的 | 主な処理 | 備考 |
|---|---|---|---|---|
| `gar usb list` | Gapless Agent Runtime (venv) | 接続中の USB デバイス一覧 | `usbipd.exe list` の Connected を表示 | busid / VID:PID / state を確認 |
| `gar usb attach` | Gapless Agent Runtime (venv) | 実機を WSL2 に attach | busid を自動検出し `usbipd.exe attach --wsl` を実行。attach 済み busid を記憶 | `--busid` で明示指定、`--no-remember` で記憶しない |
| `gar usb detach` | Gapless Agent Runtime (venv) | attach を解除 | `usbipd.exe detach` を実行 | |
| `gar usb status` | Gapless Agent Runtime (venv) | attach 状態を確認 | 対象デバイスの state を表示 | attach 済みなら exit 0 |

未 share（`Not shared`）のデバイスには `usbipd bind` の案内を表示します。通常は `gar target deploy` / `gar target sync` が必要時に attach を試すため、手動の `gar usb attach` は接続状態を明示的に整えたい場合だけ使います。
