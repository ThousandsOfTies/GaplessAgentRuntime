# Gapless Agent Runtime 操作ガイド

Gapless Agent Runtime の狙いは、開発者が手順を覚えて操作する環境ではなく、**VSCode 上で AI エージェントがビルド、デプロイ、実行、仮想 H/W 操作、ログ確認まで担える環境**にすることです。

そのために、EC2 simulation runtime は `gar sim`、ブラウザの Virtual Hardware Panel と同じ操作は HTTP API と Make ターゲットから実行できるようにしています。

人間は「何をしたいか」を指示し、AI はコックピット上の `gar` コマンド / Make ターゲット / HTTP API / ログを使って最後まで進めます。

Gapless Agent Runtime で AI に任せたい作業は、アプリ機能の実装だけではありません。実機互換シミュレーションのように、人手では採算が合いにくく、実機検証が始まるとメンテされず腐りやすい runtime を、AI が継続的に直せる状態にすることも重要な狙いです。

---
