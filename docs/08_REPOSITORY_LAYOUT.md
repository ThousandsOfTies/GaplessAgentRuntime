# リポジトリ配置と資産の置き場所

この資料は、`GaplessAgentRuntime`、`gar-tools`、`gar-build-env`、target app repo の関係を説明する。

結論として、開発時は兄弟リポジトリとして並べて編集し、利用時は `gar setup`
が `GaplessAgentRuntime/.gar/tools` に `gar-tools` を取得できる構成にする。

---

## 全体像

```mermaid
flowchart TB
  subgraph Dev["開発者 workspace: Yurufuwa/"]
    GAR["GaplessAgentRuntime/"]
    Tools["gar-tools/"]
    BuildEnv["gar-build-env/"]
    LinuxApp["embedded-poc-app/"]
    M5App["gar-vibe-ui/"]
  end

  subgraph User["利用者 checkout: GaplessAgentRuntime/"]
    UserGAR["GaplessAgentRuntime/"]
    DotGar[".gar/"]
    DotGarTools[".gar/tools/"]
  end

  GAR -->|gar CLI / docs / orchestration| RuntimeRole["操作面の正本"]
  Tools -->|target templates / hardware / simulation assets| ToolsRole["target資産の正本"]
  BuildEnv -->|Codespaces / build dependencies / artifact hub| BuildRole["ビルド環境の正本"]
  LinuxApp -->|Linux/RasPi app source / scenarios| LinuxAppRole["Linux target appの正本"]
  M5App -->|M5Stack firmware / VS Code bridge| M5AppRole["ESP32/M5Stack appの正本"]

  UserGAR -->|gar setup| DotGar
  DotGar --> DotGarTools
  DotGarTools -. "auto clone of gar-tools" .-> ToolsRole
```

---

## 開発時の配置

開発者は `GaplessAgentRuntime`、`gar-tools`、`gar-build-env`、target app repo を普通のGitリポジトリとして並べる。
この形だと、それぞれを独立して差分確認、commit、pushしやすい。

```mermaid
flowchart LR
  subgraph Workspace["Yurufuwa/"]
    GAR["GaplessAgentRuntime/"]
    Tools["gar-tools/"]
    BuildEnv["gar-build-env/"]
    LinuxApp["embedded-poc-app/"]
    M5App["gar-vibe-ui/"]
  end

  GAR --> GARFiles["gar CLI\nsetup flow\ndocs\ntests\nruntime orchestration"]
  Tools --> ToolFiles["targets/*\nwokwi templates\nhardware templates\nruntime tools"]
  BuildEnv --> BuildFiles["Codespaces devcontainer\npost-create setup\nartifact bundle Makefile"]
  LinuxApp --> LinuxAppFiles["app/sensor_demo\napp drivers\napp scenarios"]
  M5App --> M5AppFiles["vibe-remote\nm5stack-client\nPlatformIO firmware artifacts"]

  GAR -. "default discovery" .-> Tools
  GAR -. "Codespace build/fetch" .-> BuildEnv
  GAR -. "Linux deploy/run inputs" .-> LinuxApp
  GAR -. "ESP32 build/flash inputs" .-> M5App
```

代表的な配置:

```text
Yurufuwa/
  GaplessAgentRuntime/
  gar-tools/
  gar-build-env/
  embedded-poc-app/
  gar-vibe-ui/
```

---

## 利用時の配置

利用者は `GaplessAgentRuntime` だけをcloneして始められる。
`gar setup` は `gar-tools` が見つからない場合、`.gar/tools` に取得する。

```mermaid
flowchart TB
  Clone["git clone GaplessAgentRuntime"]
  Setup["gar setup"]
  Check{"gar-tools found?"}
  UseExisting["既存のgar-toolsを使う"]
  CloneTools["git clone gar-tools\ninto .gar/tools"]
  Run["target選択 / Wokwi生成 / hw init"]

  Clone --> Setup --> Check
  Check -->|yes| UseExisting --> Run
  Check -->|no| CloneTools --> Run
```

利用者側の生成後イメージ:

```text
GaplessAgentRuntime/
  .gar/
    config.json
    tools/                  # gar setup が取得する gar-tools
    wokwi/
      m5stackc/             # Wokwi project generated from gar-tools
  codespaces/               # gar code start が作る sshfs mount（必要時）
  hardware/                 # gar hw init で作るローカル上書き（必要時）
  scripts/
  docs/
```

`.gar/` はローカル状態と生成物の置き場なので、Git管理しない。
アプリケーションのソースは `GaplessAgentRuntime/app` には置かず、
target app repo（例: `../embedded-poc-app/app`、`../gar-vibe-ui/vibe-remote/m5stack-client`）を正本にする。

---

## 探索順

`GaplessAgentRuntime` は、次の順番で `gar-tools` を探す。

```mermaid
flowchart TB
  Env["1. GAR_TOOLS_ROOT"]
  InRepo["2. GaplessAgentRuntime/gar-tools"]
  DotGar["3. GaplessAgentRuntime/.gar/tools"]
  Sibling["4. ../gar-tools"]
  Missing["not found"]

  Env --> InRepo --> DotGar --> Sibling --> Missing
```

この順番にしている理由:

| 順位 | 場所 | 意図 |
|---:|---|---|
| 1 | `GAR_TOOLS_ROOT` | 開発者・CIが明示した場所を最優先する |
| 2 | `GaplessAgentRuntime/gar-tools` | 手動で内側に置いた構成を許容する |
| 3 | `GaplessAgentRuntime/.gar/tools` | `gar setup` の自動取得先 |
| 4 | `../gar-tools` | 開発時の兄弟リポジトリ配置 |

---

## 資産の責務

```mermaid
flowchart LR
  subgraph GAR["GaplessAgentRuntime"]
    CLI["gar CLI"]
    Setup["setup / provider selection"]
    Runtime["orchestration"]
    CodeMount["codespaces/\nsshfs mount"]
    LocalHW["hardware/\nlocal override"]
    Generated[".gar/\ngenerated state"]
  end

  subgraph Tools["gar-tools"]
    Targets["targets/*/target.json"]
    Wokwi["targets/esp32/wokwi/m5stackc"]
    OptionalTools["targets/esp32/qemu|renode|fake-idf|probes\noptional tools"]
    HW["targets/linux-device/hardware"]
    LinuxRuntime["targets/linux-device/runtime"]
  end

  subgraph BuildEnv["gar-build-env"]
    Codespace["Codespaces devcontainer"]
    BuildArtifacts["artifacts/from-codespace"]
    BuildRepos["repos/gar-tools\nrepos/embedded-poc-app\nrepos/gar-vibe-ui"]
  end

  subgraph LinuxAppRepo["embedded-poc-app"]
    LinuxAppSource["app/sensor_demo"]
    LinuxAppScenarios["scenarios/*.json"]
  end

  subgraph M5AppRepo["gar-vibe-ui"]
    VibeRemote["vibe-remote"]
    M5Client["vibe-remote/m5stack-client"]
    M5Artifacts["m5stack-client/artifacts/*.bin"]
  end

  CLI --> Targets
  Setup --> Targets
  Runtime --> Wokwi
  Runtime -. "必要な時だけ" .-> OptionalTools
  Runtime --> HW
  Runtime --> LinuxRuntime
  Runtime --> BuildArtifacts
  Runtime --> LinuxAppSource
  Runtime --> LinuxAppScenarios
  Runtime --> M5Client
  Runtime --> M5Artifacts
  Runtime --> CodeMount
  Codespace --> BuildRepos
  HW -->|gar hw init| LocalHW
  Wokwi -->|gar sim env start| Generated
```

責務の分け方:

| 種類 | 正本 | ローカル生成先 |
|---|---|---|
| target manifest | `gar-tools/targets/*/target.json` | なし |
| Wokwi project template | `gar-tools/targets/esp32/wokwi/m5stackc/` | `.gar/wokwi/m5stackc/` |
| ESP32 optional tools | `gar-tools/targets/esp32/{qemu,renode,fake-idf,probes}/` | 必要時のみ |
| Linux hardware CSV template | `gar-tools/targets/linux-device/hardware/` | `hardware/` |
| target app source | `embedded-poc-app/app/` | build artifact |
| app scenario | `embedded-poc-app/scenarios/` | remote scenario copy |
| Codespaces build hub | `gar-build-env/` | `codespaces/` sshfs mount |
| ESP32/M5Stack firmware source | `gar-vibe-ui/vibe-remote/m5stack-client/` | `.bin` artifact |
| ESP32/M5Stack firmware artifact | `gar-vibe-ui/vibe-remote/m5stack-client/artifacts/` | flash input |
| Runtime state / logs | なし | `.gar/` |

`hardware/` はプロジェクト固有の上書きとして扱う。標準テンプレートの正本は
`gar-tools` 側に置く。
`app/` は target app repo の責務なので、`GaplessAgentRuntime` には置かない。
`codespaces/` は `gar code start` が作るローカル mount なので、正本ではなく一時的な視界として扱う。

---

## なぜ submodule にしないか

```mermaid
flowchart LR
  User["利用者"] --> Simple["git clone GaplessAgentRuntime\ncd GaplessAgentRuntime\ngar setup"]
  Simple --> Auto[".gar/tools auto clone"]

  Dev["開発者"] --> Parallel["GaplessAgentRuntime + gar-tools\nparallel repos"]
  Parallel --> Commit["それぞれcommit/push"]
```

Git submodule にすると、利用者が `--recurse-submodules` や
`git submodule update --init` を意識する必要が出る。GARの狙いはセットアップを
`gar setup` に集約することなので、submodule より `.gar/tools` 自動取得のほうが
操作モデルが単純になる。
