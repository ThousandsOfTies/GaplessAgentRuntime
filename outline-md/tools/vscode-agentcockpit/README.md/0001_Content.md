# Gapless Agent Runtime Terminal Bridge

VSCode integrated terminal に Gapless Agent Runtime の実行要求を流すための拡張です。

Agent は `.gar/terminal-requests/*.json` に要求を書きます。拡張はそのファイルを監視し、VSCode の見える terminal を開いてコマンドを送ります。`sudo` のパスワード入力が必要な場合は、その terminal に人間が入力します。
