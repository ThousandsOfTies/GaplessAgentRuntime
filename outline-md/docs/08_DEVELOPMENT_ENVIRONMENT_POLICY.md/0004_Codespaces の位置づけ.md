## Codespaces の位置づけ

GitHub Codespaces は、作業 PC の計算資源を節約し、環境一致性を高めるためのクラウド開発環境です。

特に、ARM ビルド、重いビルド、検証、外部 PC からの作業、AI エージェントによる自律作業に向いています。

主な役割:

- 重いビルドや ARM バイナリ生成の実行
- 開発環境の再現性確保
- 作業 PC の CPU / RAM 負荷の分離
- VS Code / AI エージェントからの一貫した作業環境
- EC2 Graviton や RasPi5 へのデプロイ起点

Codespaces を使う場合、Remote-SSH で Codespace に入る必要はありません。通常は VS Code / GitHub Codespaces の接続機能、または `gh codespace ssh` を使います。

---
