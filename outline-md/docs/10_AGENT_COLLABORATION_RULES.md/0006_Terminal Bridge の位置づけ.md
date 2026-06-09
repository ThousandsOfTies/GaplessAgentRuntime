## Terminal Bridge の位置づけ

Terminal Bridge は通常の command runner ではない。
通常作業は AI の裏実行を優先し、Terminal Bridge は人間入力の受け皿として使う。

Terminal Bridge は terminal 出力の捕捉や追加入力送信を担当しない。
AI は terminal buffer を読もうとせず、裏で状態確認コマンドを実行して復帰する。
