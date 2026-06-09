## `gar setup` の進め方

1. AI はまず裏で `gar setup --no-install` を実行して不足項目を確認する。
2. 依存コマンドがすべてある項目は、そのまま完了として扱う。
3. 不足があり sudo/auth が不要なら、AI が裏で解決できるか試す。
4. sudo/auth が必要なら、provider の handoff により `.gar/terminal-requests/*.json` を作る。
5. ユーザーに integrated terminal で必要入力をしてもらう。
6. AI は `which ...` や `gar setup --no-install` を裏で再実行し、次の不足項目へ進む。
