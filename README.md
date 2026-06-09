# Gapless Agent Runtime

**コーディングから実機稼働まで、AI エージェントが切れ目なく進める組み込み開発環境。**

従来の組み込みソフトウェア開発では、コーディング・検証・実機展開のフェーズをまたぐたびに、人間が環境の立ち上げや、ビルド成果物を受け渡す作業が発生していました。VM でビルドして転送し、動作確認し、実機に流し込む――この「フェーズ間の受け渡し」が開発のリズムを分断し、都度AIのセッションが途切れてしまい、高い自律性の妨げになっていました。

Gapless Agent Runtime は、この受け渡しを人間ではなく、AI エージェント自身で行えるようにし、これによりAIエージェントが自律的に最後まで開発を行うことを実現しました。

結果として、開発者が集中すべき「何を作るか」「どう使うか」の意思決定に、より多くのエネルギーを向けられます。

<p align="center">
  <img src="docs/images/agentcockpit.svg" alt="Gapless Agent Runtime concept diagram" width="900">
</p>

これを支えるのが、**仮想 I/O デバイス層を AI が徹底的に作り込む**という仕組みです。実機と同じデバイスインターフェースを VM 上に再現することは、仕様が膨大でメンテコストも高く、人手では費用対効果が合いませんでした。Gapless Agent Runtime はその実装と継続保守を AI が担える枠組みを提供することで、アプリ側の改修なしに VM と実機で同じバイナリを動かせるバイナリ透過性を実現します。これにより、実機が手元になくても本番相当の検証が回せる——真のシフトレフトを開発プロセスに組み込めます。

---

﻿## 動作確認済み環境

| 役割 | 環境 |
|---|---|
| **操作ハブ** | VS Code + WSL2（Windows PC 上） |
| **ビルド** | GitHub Codespaces（クラウド） |
| **検証** | AWS EC2 Graviton（arm64 VM） |
| **実機ターゲット** | Raspberry Pi 5 |

手元の Windows PC に VS Code と WSL2 があれば、上記すべてを `gar` コマンドひとつで操作できます。

﻿## 読者別の入口

| あなたが… | まず読む | 次に読む |
|---|---|---|
| **このプロジェクトを初めて知る** | [01 アーキテクチャ](docs/01_ARCHITECTURE.md)、[06 技術的価値](docs/06_INDUSTRY_TRENDS.md) | [05 PoC 成果](docs/05_RESULTS.md) |
| **実際に動かしたい開発者** | [15 0 から実機動作まで](docs/15_ZERO_TO_TARGET_TUTORIAL.md) | [02 ワークフロー](docs/02_WORKFLOW.md)、[03 シミュレーション設定](docs/03_SIMULATION_SETUP.md)、[11 コマンド早見表](docs/11_COMMAND_REFERENCE.md) |
| **作業する AI エージェント** | [AGENT.md](AGENT.md)、[07 操作ガイド](docs/07_AI_AGENT_OPERATIONS.md) | [10 協業ルール](docs/10_AGENT_COLLABORATION_RULES.md)、[11 コマンド早見表](docs/11_COMMAND_REFERENCE.md) |
| **実機で組みたい** | [04 ハードウェア配線](docs/04_HARDWARE_WIRING.md) | [05 PoC 成果](docs/05_RESULTS.md) |

﻿## ドキュメント一覧

### A. 全体像を知る（概念）
* [01 アーキテクチャ](docs/01_ARCHITECTURE.md) — Human Intent → AI Agent → Cloud/Device の役割分担と、5 つのコアアーキテクチャ。
* [06 業界動向と技術的価値](docs/06_INDUSTRY_TRENDS.md) — SOAFEE / SDV 等のトレンドとの比較。なぜこの構成が優れているのか。
* [05 PoC 成果まとめ](docs/05_RESULTS.md) — EC2 フルシミュレーションと RasPi5 実機の動作確認結果、得られた知見、残タスク。

### B. 動かす・運用する（実務）
* [02 開発ワークフロー](docs/02_WORKFLOW.md) — 指示からデプロイ・実行までの全体シーケンス図。
* [03 シミュレーション設定](docs/03_SIMULATION_SETUP.md) — EC2 上の device compatibility runtime と Virtual Hardware Panel の起動・使い方。
* [04 ハードウェア配線](docs/04_HARDWARE_WIRING.md) — RasPi5 + ブレッドボードの LED / ボタン / I2C / SPI 配線図。
* [07 AI エージェント操作ガイド](docs/07_AI_AGENT_OPERATIONS.md) — AI がビルド・デプロイ・仮想 H/W 操作・ログ確認を行うための入口（`gar sim` / Make / HTTP API）。
* [11 コマンド / スクリプト早見表](docs/11_COMMAND_REFERENCE.md) — `gar` コマンド・Make ターゲット・補助スクリプトの**唯一の正本**。どこで実行し何をするかの一覧。
* [15 0 から実機動作までのチュートリアル](docs/15_ZERO_TO_TARGET_TUTORIAL.md) — WSL Hub 初期化から Codespace build、EC2 simulation、RasPi5 実機実行までの一本道。

### C. 環境と協業のルール
* [08 開発環境方針メモ](docs/08_DEVELOPMENT_ENVIRONMENT_POLICY.md) — WSL2 / Codespaces / devcontainer / Windows ネイティブの役割分担。
* [09 Agent Terminal Bridge 設計メモ](docs/09_AGENT_TERMINAL_BRIDGE.md) — AI と VSCode terminal をつなぐ bridge の設計（仕組み側）。
* [10 AI / Human 協業ルール](docs/10_AGENT_COLLABORATION_RULES.md) — 裏作業と sudo/auth handoff の運用ルール（振る舞い側）。

### D. 設計・将来計画
* [12 旧 shim → CUSE/gpio-sim 移行記録](docs/12_CUSE_MIGRATION_PLAN.md) — GPIO/SPI を fake `/dev/*` runtime へ寄せた設計と確認結果。

