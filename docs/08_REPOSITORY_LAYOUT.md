# リポジトリ配置

GARはcore、Target Pack、build環境、Productを分離します。

```text
Yurufuwa/
├─ GAR/
│  ├─ GaplessAgentRuntime/   # CLIとorchestration
│  ├─ gar-tools/             # Target Pack
│  └─ gar-build-env/         # 共通build環境
└─ ProductWorkspace/
   ├─ scripts/               # Product build hooks
   ├─ hardware/              # requirementsとbinding
   ├─ scenarios/             # Product scenario
   └─ sources/               # 固定したProduct sourceとgar-tools
```

## 責務

| Repository | 所有するもの |
|---|---|
| `GaplessAgentRuntime` | CLI、workspace、artifact、environment composition、diagnostic |
| `gar-tools` | Board／OS／toolchain／provisioning／generic capability |
| `gar-build-env` | devcontainer、共通build依存、workspace生成 |
| Product workspace | build hook、requirements、binding、topology、scenario、source revision |
| Product source | application、firmware、protocol、UI、unit test |

Product名、TX／RX、menu、部品の用途、Product固有配線をTarget Packへ置きません。

## GAR coreの主要directory

```text
GaplessAgentRuntime/
├─ scripts/
│  ├─ gar / gar.cmd          # CLI launcher
│  ├─ setup / setup.cmd      # 初期準備
│  └─ gar_lib/
│     ├─ commands/           # CLI
│     ├─ build/              # Docker／Codespaces
│     ├─ artifacts/          # snapshotとmetadata
│     ├─ simulation/         # runtimeとSim Host
│     ├─ target/             # deployとlifecycle
│     ├─ access/             # external tool adapter
│     └─ system/             # multi-node orchestration
├─ infra/                    # build image、Ubuntu bootstrap、Terraform
├─ tools/                    # VS Code extension、MCP、補助tool
├─ tests/
├─ docs/                     # 現在の操作契約
├─ info/                     # 背景と将来方針
└─ .gar/                     # machine-local state、Git管理外
```

正確なmodule一覧はsource codeを正本とし、文書へ複製しません。

## Product workspace

```text
ProductWorkspace/
├─ scripts/
│  ├─ product-sim-build.sh
│  ├─ product-sim-env-build.sh
│  └─ product-target-build.sh
├─ hardware/
│  ├─ requirements.json
│  └─ bindings/<target-id>.json
├─ scenarios/
├─ gar-system.json           # 複数nodeの場合
└─ sources/
```

すべてが必須ではありません。単一nodeやhardware contractを使わないProductは不要なdirectoryを省略できます。

## `gar-tools`の探索順

1. `GAR_TOOLS_ROOT`
2. Product workspaceの`sources/gar-tools`
3. GAR coreと並ぶ`gar-tools`
4. `.gar/tools`のauto-clone

build時に使用したcommitとdirty状態はartifact metadataへ記録されます。

## 配置ルール

- `.gar/`、credential、IP、COM、VM名はcommitしない。
- Product build commandはGAR coreへ追加せず、Product hookへ置く。
- Target固有処理はTarget Packへ置く。
- Product固有の配線とbehaviorはProduct側へ置く。
- 完了済みTODOや一時handoverは恒久文書へ残さない。

実行時のデータフローは[アーキテクチャ](02_ARCHITECTURE.md)を参照してください。
