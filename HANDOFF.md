# GaplessAgentRuntime 全体レビュー — 改善点の指摘

> **対象**: `ThousandsOfTies/GaplessAgentRuntime` の全ソースコード・ドキュメント・テスト・CI
> **時点**: 2026-07-08
> **レビュー範囲**: Python ソース約 8,000 行 / テスト約 3,900 行 / ドキュメント 15 ファイル / CI / MCP / VSCode 拡張

---

## 総評

プロジェクトの **設計思想は明確で一貫している**。「異種環境間の文脈の載せ替えコストをエージェントが吸収する」というコアバリューが、README・info/・AGENT.md まで貫かれている。CLI の構造（`gar setup` → `gar code/sim/target`）は make-target 的な抽象として筋が通っており、provider discovery パターンでの拡張性設計も適切。テストカバレッジは 144 tests、ruff は green、CI は Python 3.11〜3.13 で回っている。

以下、**今の完成度を踏まえたうえで次のステップに進むための改善点**を、優先度順に整理する。

---

## 🔴 高優先（構造的負債・今のうちに直すと後で効く）

### 1. `cli.py` の巨大 re-export（対応済み）

`cli.py` の互換 re-exportを廃止し、CLI dispatchに必要なimportだけを残した。
テストも各実装モジュールを直接importする。

### 2. `cli.py` の dispatch が if-elif の手書き連鎖

`main()` 関数の後半は `if args.command == "sim": if args.sim_command == "env": if args.sim_env_command == "build": ...` という 3〜4 段のネストが続く。現在は動いているが、**コマンド追加のたびにここに手で分岐を足す**必要があり、argparse のサブパーサー定義と dispatch が物理的に分離しているため、対応漏れが起きやすい。

- **提案**: サブコマンドごとに `set_defaults(func=...)` を使って dispatch を argparse に委ねるか、コマンドテーブル（dict[str, Callable]）で解決する。パーサー定義と dispatch を同じ場所に書くだけでもかなり改善する。

### 3. `config.py` のハードコードされたデフォルト値

```python
DEFAULT_EC2_HOST = "vibecode-graviton"  # SSH config alias only
DEFAULT_EC2_INSTANCE_ID = None
DEFAULT_EC2_REGION = None
```

- **対応済み**: instance ID / region は `None` を既定とし、workspace の `.gar/config.json` に保存された値だけを使う。未設定時は `gar setup` を案内して停止する。

### 4. テストファイルの巨大化

[test_gar_cli.py](file:///home/user/Yurufuwa/GaplessAgentRuntime/tests/test_gar_cli.py) が **3,304 行**の単一ファイル。CLI・sim・target・usb・hw・code・MCP のテストがすべて 1 ファイルに混在している。

- **提案**: `tests/test_cli_setup.py`、`tests/test_cli_sim.py`、`tests/test_cli_target.py`、`tests/test_cli_code.py` 等にコマンドグループ単位で分割する。テストの発見性と並列実行が改善する。

---

## 🟡 中優先（品質・安全性・開発体験）

### 5. エラーハンドリングの一貫性

多くのコマンドが成功時に `return 0`、失敗時に `return 1` を返すが、例外が起きた場合のハンドリングが場所によって異なる。

- `subprocess.run` の `check=False` は全体的に適切だが、**stdout/stderr の出し分けが不統一**。成功メッセージが stdout に出る箇所と stderr に出る箇所が混在。
- `NotImplementedError` を catch してユーザーガイダンスを出すパターンは良いが、一部のコマンド（`target build`、`target flash`）ではメッセージが英語混在（`Run \`gar setup\` and choose ESP32 esptool.`）。
- **提案**: エラーメッセージの日英混在を統一する（日本語ベースなら日本語に揃える）。`gar` 全体で共通のエラー出力ヘルパーを用意すると良い。

### 6. setup候補とruntime environmentの分離（完了）

旧`DevEnvironment`のruntime操作を削除し、`EnvironmentSetupOption`へ改名した。
現在はsetup表示用メタデータ・依存確認・導入処理だけを持つ。build、simulation、target、
accessの実行契約はそれぞれの専用層へ分離済み。

### 7. `pyproject.toml` にプロジェクトメタデータがない

現在の `pyproject.toml` は ruff 設定のみ。`[project]` セクション（name, version, description, dependencies, python-requires）が定義されていない。

- **提案**: `[project]` セクションを追加し、`requirements-gar.txt` の内容を `dependencies` に移す。`pip install -e .` でインストール可能にすれば、`scripts/gar` の venv bootstrap ロジックを簡素化できる。`[project.scripts]` に `gar = "scripts.gar_lib.__main__:main"` を定義すれば、エントリポイントも標準化される。

### 8. 型ヒントの強化

関数シグネチャには型ヒントが付いているが、`config` を受け渡す場所では `dict` のままで、キーの存在保証がない。

- **提案**: `config.py` に `TypedDict` または `dataclass` を導入して `GarConfig` を定義する。`load_config() -> GarConfig` にすれば、IDE の補完が効き、キーの typo によるバグを防げる。

### 9. ログ／出力の構造化

`--json` フラグは一部コマンドにあるが、人間向け出力が `print()` の直書き。

- **提案**: `logging` モジュールを導入し、`--verbose` / `--quiet` フラグを `gar` グローバルオプションとして追加する。デバッグ時に `gar --verbose sim env start` で詳細が見えると問題切り分けが速くなる。

### 10. MCP サーバーのプロトコル不完全性

[server.py](file:///home/user/Yurufuwa/GaplessAgentRuntime/tools/gar-mcp/server.py) は最小限の JSON-RPC を手書きしているが、`resources/list` や `prompts/list` への応答がない。MCP クライアントによっては `error` を返されることで機能低下する可能性がある。

- **提案**: 未対応メソッドには空リスト（`{"resources": []}` 等）を返すか、MCP SDK（`mcp` パッケージ）を使って標準準拠にする。`notifications/cancelled` 等の通知も無視でよいが、明示的に `return None` するハンドラを足すと堅牢になる。

---

## 🟢 低優先（磨き・将来への備え）

### 11. CI の Python バージョンに 3.14 がない

ローカル環境は Python 3.14 で動いている（`.venv/pyvenv.cfg` から推定）が、CI は 3.11〜3.13 のみ。`setup-python@v5` が 3.14 をサポートしたタイミングで追加すると安心。

### 12. `.gitignore` の重複パターン

`.gar/` がワイルドカードで無視され、その下の `mcp-config.json` と `terminal-requests/` が個別にも無視されている。ワイルドカードで包含されるため個別行は冗長。

### 13. `Makefile` の役割縮小の明示

`Makefile` は `make init` / `make start` が入口だが、日常操作は完全に `gar` CLI に移行済み。`make sim-test` / `make sim-scenario` もまだ残っているが、これらは `gar sim` 経由に置き換え済みのはず。

- **提案**: `Makefile` の冒頭に「このファイルは初期セットアップ（`make init`）と開発者用 venv 起動（`make start`）のためのもの。日常操作は `gar` コマンドを使ってください」と明記し、`sim-test` / `sim-scenario` は deprecated 表示にするか削除する。

### 14. VSCode 拡張のテストがない

[extension.js](file:///home/user/Yurufuwa/GaplessAgentRuntime/tools/vscode-gar/extension.js) は 130 行ほどだが、ユニットテストがない。`processRequest` のロジック（JSON parse → terminal 起動 → status 書き込み → move）は十分テスト可能。

- **提案**: `jest` または `vitest` で最小限のテストを追加する。少なくとも `shellQuote()` のエスケープテストと、`processRequest` の異常系（invalid JSON、空 command）テストがあるとよい。

### 15. `codespaces/` 配下の `repos/` に実体が含まれている

`find` の結果から `codespaces/repos/gar-vibe-ui/` 配下に大量のファイル（TypeScript ソース、package-lock.json 等）が存在する。`.gitignore` で `codespaces/` は無視されているが、**ディレクトリ構造としてはこのリポジトリに含まれている**。

- **現状**: sshfs マウント先として使っているため実害はないが、新規クローン時に「この空ディレクトリは何？」となる可能性がある。
- **提案**: `codespaces/README.md` に「このディレクトリは `gar code start` で Codespaces を sshfs マウントする先です。中身は git 追跡していません」と書いておく。

### 16. `shim` コマンド（対応済み）

runtime経路で使われない旧`gar shim`と実装を削除した。

### 17. `AGENT.md` と `CLAUDE.md` の分離方針が外部に伝わりにくい

`CLAUDE.md` は「AGENT.md を読め」としか言っていない。GitHub Copilot 用の `.github/copilot-instructions.md` も別にある。

- **提案**: README に「AI エージェント向け指示は AGENT.md に集約しています。各エージェント固有の入口ファイル（CLAUDE.md、.github/copilot-instructions.md）は AGENT.md へのポインタです」と 1 行書く。

---

## 📐 ドキュメント品質

### 良い点

- `docs/` と `info/` の分離（運用手順 vs 思想・ビジョン）は明快。
- `info/00_ESSENCE.md` の「3 層は出発点であって天井ではない」は、プロジェクトの射程を正確に言語化している。
- README の「読者別の入口」テーブルは親切。

### 改善点

- `docs/07_HANDOFF.md` が vibe-remote / Renode の作業メモになっており、**一般的な引き継ぎドキュメントとしての構造がない**。「現在のシステム状態」「既知の問題」「次にやるべきこと」のセクション分けが必要。
- `docs/08_REPOSITORY_LAYOUT.md` は存在するが、内容を確認していない。ソースツリーが増えた場合の更新漏れに注意。
- `TODO.md` の完了項目が大量に残っている。Archival section は別ファイル（`CHANGELOG.md` 等）に分離すると見通しが良くなる。

---

## 🏗️ アーキテクチャの評価

```
                    ┌─────────────────────────────┐
                    │       gar CLI (cli.py)       │  ← 1,067行。dispatch 肥大化
                    └──────────┬──────────────────┘
                               │
            ┌──────────────────┼──────────────────┐
            │                  │                  │
     commands/code       commands/sim       commands/target
     commands/setup      commands/usb       commands/hw
     commands/terminal   commands/infra
            │                  │                  │
            └──────────────────┼──────────────────┘
                               │
                    ┌──────────┴──────────┐
                    │  environments/base  │  ← EnvironmentSetupOption
                    │  environments/      │     provider discovery
                    │    registry/        │     (pkgutil.walk_packages)
                    └──────────┬──────────┘
                               │
              ┌────────────────┼───────────────────┐
              │                │                   │
        codespace/        simulator/          target/
        github_codespaces                     adb_usb
        local              aws_ssm            adb_win
                           esp32_qemu         esp32_esptool
                           renode_mcu         ssh_scp
                           ssh_remote
                           vibe_remote_device
                           wokwi
```

**良い点**:
- Provider discovery が `pkgutil.walk_packages` ＋ クラス検査で自動的に動く。新しい provider を追加するのにレジストリを手で更新する必要がない。
- `simulation/` レイヤーでコマンド生成（`SimCommandBuilder`）と実行（`SimEnvProcessor`）が分離されており、テスタビリティが高い。

**改善すべき点**:
- `gar_tools.py`（target manifest discovery）と `environments/discovery.py`（provider discovery）が似た仕組みだが独立している。将来的に target manifest と provider を紐付ける場合に統合が必要。

---

## ✅ まとめ：優先度マトリクス

| # | 項目 | 優先度 | 工数 | 効果 |
|---|---|---|---|---|
| 1 | cli.py re-export 整理 | ✅ 完了 | - | 保守コスト削減 |
| 2 | cli.py dispatch のテーブル化 | 🔴 高 | 中 | 新コマンド追加の安全性 |
| 3 | config.py のハードコード除去 | 🔴 高 | 小 | 安全性・汎用性 |
| 4 | テストファイル分割 | 🔴 高 | 中 | 開発体験 |
| 5 | エラーメッセージの日英統一 | 🟡 中 | 小 | ユーザー体験 |
| 6 | setup候補とruntime environmentの分離 | ✅ 完了 | - | 責務分離 |
| 7 | pyproject.toml 整備 | 🟡 中 | 小 | 標準化 |
| 8 | config の TypedDict 化 | 🟡 中 | 中 | 型安全性 |
| 9 | logging 導入 | 🟡 中 | 中 | 診断性 |
| 10 | MCP サーバーのプロトコル補完 | 🟡 中 | 小 | 互換性 |
| 11 | CI に Python 3.14 追加 | 🟢 低 | 小 | 互換性 |
| 12 | .gitignore 整理 | 🟢 低 | 小 | 清潔さ |
| 13 | Makefile の役割明示 | 🟢 低 | 小 | 導入体験 |
| 14 | VSCode 拡張テスト | 🟢 低 | 中 | 品質 |
| 15 | codespaces/ の説明追加 | 🟢 低 | 小 | 導入体験 |
| 16 | shim コマンドの削除 | ✅ 完了 | - | 表面積の縮小 |
| 17 | AI 向けファイルの方針説明 | 🟢 低 | 小 | 導入体験 |

---

> **推奨する最初の一手**: #3（ハードコード除去）→ #1（re-export 整理）→ #2（dispatch テーブル化）の順で cli.py / config.py を軽量化する。これだけで日常の開発速度が上がり、新コマンド追加時の事故率が下がる。

---

## 📝 レビュー後の議論（2026-07-08）

### 評価の修正：2 件目のターゲットは存在する

初回レビューで「2 件目がない」と評価したが、**gar-vibe-remote（M5StickC Plus2）が 2 件目として既に存在**していた。コードベースに以下の証拠がある：

- `target/esptool.py` — esptool によるflash実装
- `environments/registry/target/esp32_esptool.py` — setup用の依存確認と導入
- `environments/registry/simulator/wokwi.py`（115行）+ `simulation/wokwi.py`（613行）— Wokwi simulation
- `environments/registry/simulator/vibe_remote_device.py`（137行）— Vibe Remote device provider
- `scripts/gar_lib/targets/esp32.py`（293行）— ESP32 ビルド・artifact 管理
- `gar target build-esp32` / `gar target flash-esp32` コマンド
- `docs/07_HANDOFF.md` の vibe-remote 作業記録

**Linux SBC（RasPi5 + EC2 CUSE sim）** と **ESP32 MCU（M5StickC + Wokwi sim）** という、アーキテクチャが全く異なる 2 つのターゲットが、同じ `gar` CLI + provider 選択で通っている。これは provider 抽象が設計通りに機能している証拠であり、「たまたま 1 パターンに最適化しただけ」という反論が効かない。

#### 修正後の成熟度評価

```
思想・ビジョン       ████████████████████  95%
CLI 設計            ████████████████░░░░  80%
汎用性の実証（2件）  ████████████████░░░░  80%  ← 20% → 80% に修正
初見ユーザー体験     ██████░░░░░░░░░░░░░░  30%
内部コード品質       ████████████░░░░░░░░  60%
```

商品としての残りの距離は、主に「初見ユーザーが自分で始められるか」の一点に絞られる。2 件目の実証がある以上、技術的な基盤は十分。

---

### 3 件目のチャレンジ：カメラ TX/RX（2 台マイコン協調）

次のターゲットとして、**2 台のマイコンを使ったカメラの TX と RX** が計画されている。

#### 1 件目・2 件目との質的な違い

| | 1件目（RasPi5） | 2件目（M5StickC） | 3件目（カメラ TX/RX） |
|---|---|---|---|
| デバイス数 | 1 | 1 | **2** |
| ビルド成果物 | 1 バイナリ | 1 firmware | **2 firmware** |
| deploy | 1 ターゲット | 1 ターゲット | **2 ターゲット** |
| sim | 単体で完結 | 単体で完結 | **2 台の通信を模擬** |

現在の `gar` は **1 target = 1 deploy = 1 sim** のモデル。3 件目で「2 台を同時に扱う」マルチターゲット協調が初めて試される。

#### GAR アーキテクチャへの影響

- **ビルド**: `artifact.json` に `deploy.tx` / `deploy.rx` のようなセクションが生えるか、target.json を 2 つ定義するか
- **deploy**: `gar target deploy` が 2 つのポートに別々の firmware を流す必要
- **sim**: TX が送ったデータを RX が受け取る通信路をどう再現するか（Wokwi なら `diagram.json` に 2 チップ + 配線）

#### これが通ると証明されること

> **「GAR は単体デバイスだけでなく、複数デバイスの協調動作まで 1 セッションで回せる」**

`info/00_ESSENCE.md` の「N 個の異種環境を 1 セッションで横断」がデバイス間協調にまで拡張されたことになる。

#### 推奨する開発アプローチ

別々に開発し、段階的に統合する：

```
Phase 1:  TX 単体で動かす（カメラ → 送信バッファまで）
Phase 2:  RX 単体で動かす（受信 → 表示/保存まで）
Phase 3:  繋ぐ（← ここで初めて 2 台協調の問題が出る）
```

Phase 1・2 は今の GAR がそのまま使える（`gar target build` → `gar target flash-esp32` の 1 対 1 モデル）。GAR の拡張が要るのは Phase 3。そのときに初めて「TX を焼いて、RX も焼いて、通信を確認する」という 1 セッション内マルチターゲットの需要が実際の痛みとして出る。その痛みを感じてから抽象を引き直すのが YAGNI の正しい使い方。

setup候補とruntime environmentの分離は完了済み。Phase 3でマルチターゲットの需要が
具体化した場合は、現在の`TargetEnvironment`を土台にセッション単位の構成を検討する。

Phase 1・2 の間にやっておくと Phase 3 で楽になるもの：
- **#3** config.py のハードコード除去
- **#7** pyproject.toml 整備
