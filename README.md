# Gapless Agent Runtime

**コーディングから実機稼働まで、AI エージェントが切れ目なく進める組み込み開発環境。**

従来の組み込みソフトウェア開発では、コーディング・検証・実機展開のフェーズをまたぐたびに、人間が環境の立ち上げや、ビルド成果物を受け渡す作業が発生していました。VM でビルドして転送し、動作確認し、実機に流し込む――この「フェーズ間の受け渡し」が開発のリズムを分断し、都度AIのセッションが途切れてしまい、高い自律性の妨げになっていました。

Gapless Agent Runtime は、この受け渡しを人間ではなく、AI エージェント自身で行えるようにし、これによりAIエージェントが自律的に最後まで開発を行うことを実現しました。

結果として、開発者が集中すべき「何を作るか」「どう使うか」の意思決定に、より多くのエネルギーを向けられます。

<p align="center">
  <img src="docs/images/beforeafter.svg" alt="Gapless Agent Runtime concept diagram" width="900">
</p>

これを支えるのが、**仮想 I/O デバイス層を AI が徹底的に作り込む**という仕組みです。実機と同じデバイスインターフェースを VM 上に再現することは、仕様が膨大でメンテコストも高く、人手では費用対効果が合いませんでした。Gapless Agent Runtime はその実装と継続保守を AI が担える枠組みを提供することで、アプリ側の改修なしに VM と実機で同じバイナリを動かせるバイナリ透過性を実現します。これにより、実機が手元になくても本番相当の検証が回せる——真のシフトレフトを開発プロセスに組み込めます。

---

## 動作確認済み環境

| 役割 | 環境 |
|---|---|
| **操作ハブ** | VS Code + WSL2（Windows PC 上） |
| **ビルド** | GitHub Codespaces（クラウド） |
| **検証** | AWS EC2 Graviton（arm64 VM） |
| **実機ターゲット** | Raspberry Pi 5 |

手元の Windows PC に VS Code と WSL2 があれば、上記すべてを `gar` コマンドひとつで操作できます。

## セットアップ資産

Runtime 本体とは別に、target ごとのテンプレート・配線定義・シミュレーション資産は
`gar-tools` で管理します。通常は `GaplessAgentRuntime` を clone して `gar setup` を
実行すれば、必要に応じて `.gar/tools` に自動取得されます。

target app のソースは `GaplessAgentRuntime/app` ではなく、兄弟リポジトリ
`embedded-poc-app/app` などの target app repo に置きます。Runtime はそれらの成果物を
ビルド環境・シミュレーション環境・実機へ運ぶ操作面です。

開発者が `gar-tools` も編集する場合は、`GaplessAgentRuntime` と同じ親ディレクトリに
並べるか、`GAR_TOOLS_ROOT` で明示してください。

シミュレーションの操作は、人間の手動確認と AI / CI の再現確認で入口を分けます。
Linux / RasPi-compatible では Web UI、Wokwi では VS Code Wokwi Simulator / Diagram UI を
人間が操作し、AI / CI は GAR 共通の JSON シナリオを実行単位にします。

## 読者別の入口

| あなたが… | まず読む | 次に読む |
|---|---|---|
| **このプロジェクトを初めて知る** | [02 アーキテクチャ](docs/02_ARCHITECTURE.md)、[info/01 業界動向](info/01_INDUSTRY_TRENDS.md) | [99 PoC 成果](docs/99_RESULTS.md) |
| **実際に動かしたい開発者** | [00 チュートリアル](docs/00_ZERO_TO_TARGET_TUTORIAL.md) | [01 コマンドリファレンス](docs/01_COMMAND_REFERENCE.md)、[06 シミュレーション環境](docs/06_SIMULATION.md) |
| **実機で組みたい** | [05 ハードウェア配線](docs/05_HARDWARE_WIRING.md) | [99 PoC 成果](docs/99_RESULTS.md) |

## ドキュメント一覧

### docs/ — 運用・手順・リファレンス
* [00 チュートリアル](docs/00_ZERO_TO_TARGET_TUTORIAL.md) — WSL Hub 初期化から Codespace build、EC2 simulation、RasPi5 実機実行までの一本道。
* [01 コマンドリファレンス](docs/01_COMMAND_REFERENCE.md) — `gar` コマンド全一覧。グループがそのままフローになっている。
* [02 アーキテクチャ](docs/02_ARCHITECTURE.md) — 5 レイヤ構成と各環境の役割分担。
* [03 開発環境方針](docs/03_DEVELOPMENT_ENVIRONMENT.md) — WSL2 / Codespaces / devcontainer / Windows の役割分担。
* [04 Agent Terminal Bridge](docs/04_AGENT_TERMINAL_BRIDGE.md) — AI と VSCode terminal をつなぐ bridge の設計。
* [05 ハードウェア配線](docs/05_HARDWARE_WIRING.md) — RasPi5 の LED / ボタン / I2C / SPI 配線図。
* [06 シミュレーション環境](docs/06_SIMULATION.md) — EC2 上の device compatibility runtime の起動・操作・診断。
* [07 引き継ぎ資料](docs/07_HANDOFF.md) — GAR 周辺作業の現状、環境境界、Renode / BT / Local bridge の申し送り。
* [08 リポジトリ配置](docs/08_REPOSITORY_LAYOUT.md) — GaplessAgentRuntime / gar-tools / `.gar/tools` の配置意図。
* [99 PoC 成果まとめ](docs/99_RESULTS.md) — EC2 フルシミュレーションと RasPi5 実機の動作確認結果。

### info/ — 業界情報・設計思想・将来構想
* [00 本質](info/00_ESSENCE.md) — このプロジェクトが本当は何の実証なのか（3層は一例、本質は環境横断の連続化）。
* [01 業界動向と技術的価値](info/01_INDUSTRY_TRENDS.md) — SOAFEE / SDV 等のトレンドとの比較。
* [02 設計思想](info/02_DESIGN_PHILOSOPHY.md) — なぜこの構成になったのかの設計哲学。
* [03 将来構想](info/03_FUTURE_VISION.md) — 宇宙・ロボットへの展開ビジョン。
* [04 製品の核](info/04_PRODUCT_CORE.md) — 何を売るのか、誰のどの往復（ROM 焼き／ログ解析）を消すのか。競合の空白マップ。
* [05 ターゲットとシミュレーション](info/05_TARGET_AND_SIMULATION.md) — 組み込みターゲット×シミュレーション方式の一覧、GAR の実装カバレッジ（できる/できない）、AMP（Linux+RTOS 2CPU）境界の統一 trace という差別化。
