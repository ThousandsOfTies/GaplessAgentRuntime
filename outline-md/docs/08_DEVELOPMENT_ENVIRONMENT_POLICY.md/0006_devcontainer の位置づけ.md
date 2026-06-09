## devcontainer の位置づけ

devcontainer は、Codespaces の環境定義として使います。

このリポジトリには `.devcontainer/devcontainer.json` を置き、必要な OS、ツール、VS Code 拡張、初期セットアップをリポジトリ側で管理します。

主なメリット:

- Node / C / ARM toolchain などのバージョン差分を減らせる
- Codespaces 起動時に必要ツールを自動セットアップできる
- 新しい PC や外部環境でも同じ開発環境を再現しやすい
- WSL2 側の環境設計とも揃えやすい

devcontainer は「全員に必須の魔法の箱」ではなく、Linux 前提の開発環境を再現可能にするための設定ファイルとして扱います。

---
