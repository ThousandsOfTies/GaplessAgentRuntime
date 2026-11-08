# コマンドリファレンス

正確な引数はCLI自身を正本とします。

```bash
gar --help
gar target --help
gar sim start --help
```

WindowsでPATH登録前は`gar`を`.\scripts\gar.cmd`へ読み替えてください。

## 共通

通常操作の構文は `gar <code|sim|target> <action> [subject] [options]` です。
第二引数に動詞を置き、必要な場合だけ第三引数でhostやruntimeを指定します。

- `--workspace NAME`: `gar config`で登録したworkspaceを選択
- `--json`: code・sim・targetの通常actionを単一JSONで出力
- buildとdeployは別操作。deployはbuild／fetchを暗黙実行しない
- startは配置済みの対象を開始する。build／deployを暗黙実行しない
- stopの既定対象はsession／runtime。VMの停止は `stop host` で明示する

現時点の通常操作の対応:

| Action | code | sim | target |
|---|---|---|---|
| `prepare` | tool・workspace・認証の前提確認 | Linux hostの依存を準備 | 対応recipeの初期準備 |
| `build` | 対象外 | 必要なapp・runtimeをbuild | TARGET_APPをbuild |
| `deploy` | 対象外 | 必要なapp・runtimeを配置 | 最新artifactを配置／flash |
| `start` | local接続を準備 | 配置済みruntimeを開始 | 対応recipeでapplicationを再収束 |
| `stop` | local接続を停止 | runtimeと接続を停止 | stop対応recipeでapplication停止 |
| `status` | hostと接続状態 | host・接続・runtime・app | 対応recipeでapplication状態 |
| `log` | Codespace作成log | runtime log | 対応recipeでapplication log |
| `diag` | hostと接続を診断 | host・接続・runtime・appを診断 | 対応recipeでhealth・build ID確認 |

設定したbackend／recipeの対応可否は、接続や設定変更を行わず確認できます。
`--capabilities` とactionは同時指定できません。対応表示は実際の接続・認証・導入済みversionの保証ではありません。
未対応Simulationの通常actionは、build・artifact読出し・host接続へ進む前に失敗します。
Renode／ESP32 QEMU／AWS SSMのruntimeはこの対象です。明示的なhost操作の対応範囲とは別に判定します。

```bash
gar code --capabilities --workspace Local/Product --json
gar sim --capabilities --workspace Local/Product --json
gar target --capabilities --workspace Local/Product --json
```

通常actionのJSONは `schema_version`, `command`, `workspace`, `ok`, `exit_code` を共通に持ちます。
`command` は `sim.status` などの形式で、明示した対象は `subject` に入ります。
`exit_code` はCLIの終了値、外部commandの終了値が異なる場合は `backend_exit_code` へ保持します。
進捗や子processの出力は `output`、補足診断は `diagnostics` に入り、構造化結果へ混ざりません。
引数の構文エラーと `--help` は従来のargparse出力です。

通常の `status / diag` は `components.host / connection / runtime / app` を報告します。
対象外の層は `state: not_applicable, ok: null`、確認できない層は `unknown, false` です。
appの停止・未配置や診断失敗は全体も非成功となります。Simulationの接続観測はhostへの到達性で、
ローカルのPanel tunnelは `sim status runtime --panel-port PORT` で個別に確認します。
移行状況は[CLI収束 TODO](09_CLI_CONVERGENCE_TODO.md)を参照してください。

## トップレベル

| コマンド | 用途 |
|---|---|
| `gar config` | workspace、Target、各environment、接続先を設定 |
| `gar code` | Codespacesの起動と接続を管理 |
| `gar sim` | simulationをbuild、deploy、操作、診断 |
| `gar target` | 実機を準備、build、deploy、診断 |
| `gar system` | 複数workspaceを一つのsystemとして操作 |
| `gar hw` | hardware contractを作成、検証 |
| `gar terminal` | VS Code terminalへの実行要求を管理 |
| `gar usb` | legacy WSL2 USB passthrough |
| `gar completion` | shell補完scriptを出力 |

## `gar config`

```bash
gar config
gar config --no-install
gar config --ec2-host HOST
gar config --esp32-port PORT
```

設定はrepository直下の`.gar/config.json`へ保存されます。

## `gar code`

| Action | 内容 |
|---|---|
| `prepare` | tool・workspace・認証を検証。tool導入・VM起動・接続設定変更は行わない |
| `start [session]` | SSH接続とVS Code terminal profileを準備 |
| `start host` | Codespace VMを起動 |
| `stop [session]` | local接続を停止 |
| `stop host` | Codespace VMを停止 |
| `status` | VMと接続状態を表示 |
| `log` | Codespaceの作成logを取得（Localでは対象外） |
| `diag` | hostと接続を診断。AvailableなCodespaceだけSSH probeを行う |

各actionは`--workspace NAME`、`--target TARGET`、`--json`に対応します。Windowsではsshfs mountを使いません。
`--codespace` は `--target` の別名です。Local環境では利用可能／停止不要という既存の結果を返します。
`start host / stop host` は接続用の `--settings`、`--mount-dir` などを受け付けません。
`prepare` のtool確認はLocalではgit、Codespacesではgit・gh・sshです。Codespacesでは認証と対象名の設定も確認します。
`status` の接続状態は保存済み設定の確認、`diag` は起動済みCodespaceへの到達確認まで行います。
この観測で接続設定の修復や古いstateの移行は行いません。runtime／appはcode環境の観測対象外です。

旧 `code boot / shutdown` はそれぞれ `code start host / stop host` の互換aliasです。
既存の `code stop --shutdown` も互換性を維持します（接続の後片付け後にVM停止）。

## `gar sim`

構文は `gar sim <action> [subject]` です。

| Action | 対象省略時 | 指定できるsubject |
|---|---|---|
| `prepare` | Linux Sim Hostの初期準備 | なし |
| `build` | backendに必要なruntimeとappをbuild | `app`, `runtime` |
| `deploy` | 必要なsnapshotをすべて検証後、runtime・appの順に配置 | `app`, `runtime` |
| `start` | runtimeを起動し、接続を準備 | `runtime`, `host` |
| `stop` | runtimeと接続を停止 | `runtime`, `host` |
| `status` | host・接続・runtime・appの状態を取得 | `runtime`, `host` |
| `log` | runtime logを取得 | `runtime` |
| `diag` | host・接続・runtime・appを診断 | `runtime` |
| `clean` | Product hookでappのbuild成果物を削除 | `app` |

Wokwi／MuJoCoでは個別runtime artifactを必要とせず、対象省略のbuild／deployはappだけを処理します。
`build runtime / deploy runtime` は不要である旨を表示します。
Linux simulationではruntimeとappを別snapshotとして管理します。
一括deployはsnapshotの存在・checksum・設定architectureを転送前に検証しますが、転送途中の障害を巻き戻す機能はありません。
検証できない旧形式のartifactは一括deployの対象にせず、`sim build` での再生成を案内します。

`prepare` はSSH Remoteでは起動済みUbuntu hostと非対話sudoを前提に共通bootstrapを実行します。
Local DockerではTarget Packのhost定義でimage・containerを準備し、hostを開始します。
app／runtime artifactのbuild・deployは行いません。Wokwi／MuJoCoにはこのprepareは不要で、明示指定は未対応として拒否します。

通常actionはすべて `--json` に対応します。`diag runtime` は従来のruntime診断形式を保持します。
Linuxではapp未配置時の空serviceを識別します。Wokwi／MuJoCoでは準備済みprojectとprocessの稼働を区別します。
対象省略の `status / diag` はappの `expected_build_id`（最新snapshot）、`deployed_build_id`、
`running_build_id` と `build_id_match` を報告します。配備だけではrunning IDを更新しません。
起動時の入力検証とprocessの識別ができない場合はunknownとし、全体の成功扱いにはしません。
ID一致とruntimeのhealthは独立して判定します。backendごとの範囲は[Simulation](06_SIMULATION.md)を参照してください。
一括 `deploy --json` は `placed_artifacts`、失敗したartifact、一部反映の可能性を報告します。
成功時も `running: null`, `verification: not_checked`, `requires_start: true` で、続くstartとdiagが必要です。
個別 `deploy app / runtime` は従来のartifact単位の結果です。
`sim start` の `--panel-port` などはruntime専用、`--pull / --no-update-ssh` はhost専用です。
別portで開始した接続は、停止時にも `sim stop --panel-port PORT` を指定します。

専門操作は独自の構文を維持します:

| Subject | Actions |
|---|---|
| `gpio` | `install`, `start`, `stop`, `plan`, `status`, `check` |
| `io` | `state`, `press`, `set`, `clear` |
| `infra` | `setup`, `apply`, `destroy` |

主な例:

```bash
gar sim build --workspace Local/Product
gar sim deploy --workspace Local/Product
gar sim start --workspace Local/Product
gar sim diag --workspace Local/Product --json
gar sim build app --workspace Local/Product
gar sim io press --workspace Local/Product --device button --line 17
gar sim start host --workspace Local/Product --pull
```

旧 `sim app build`、`sim runtime start`、`sim host start` などは互換aliasとして引き続き利用できます。
help・補完・再試行案内は新構文を優先します。
旧構文の削除時期は設けず、既存scriptの実行互換性をテストで維持します。新しい手順・コマンド例には
action-first構文を使います。将来の削除は利用者への移行案内を伴う別の互換性変更として判断します。
この方針は `code boot / shutdown` にも適用します。

`sim infra apply`と`destroy`はAWS resourceを変更します。対象と課金を確認してください。

## `gar target`

| Action | 内容 |
|---|---|
| `prepare` | recipe-backed Targetを初期準備 |
| `probe` | Productが宣言する実機診断を実行（[診断hook](TARGET_PROBE_HOOK.md)） |
| `wifi` | 専用画面からProductの無線LAN設定recipeを実行 |
| `audio` | 専用画面から実機音量の保存・USB再接続時の復元を設定 |
| `trace` | 実機会話の音声入出力の順序を一時観測 |
| `configure` | applicationの永続envを配置 |
| `build` | TARGET_APP artifactをbuild |
| `fetch` | BuildEnvironmentからartifactを取得 |
| `preflight` | artifactと接続Targetの互換性をread-only検証 |
| `deploy` | 最新artifactを配置またはflash |
| `start` | 配置済みapplicationをrecipe経由で起動・再収束し、healthとbuild IDを確認 |
| `stop` | 明示的なstop capabilityを持つrecipeでapplicationを停止 |
| `status` | application状態を取得 |
| `log` | application logを取得 |
| `diag` | healthと稼働build IDを診断 |

```bash
gar target configure --workspace Local/Product --app APP --file app.env --json
gar target log --workspace Local/Product --app APP --lines 200 --json
gar target start --workspace Local/Product --app APP --json
gar target stop --workspace Local/Product --app APP --json
```

全actionは `--workspace / --json` に対応します。
`prepare`、`preflight`、`start`、`stop`、`status`、`log`、`diag`は、対応capabilityを持つTargetだけで利用できます。UUU Targetでは通常`build`と`deploy`だけを使います。
`start` は最新TARGET_APP snapshotとの互換性を確認して既存lifecycleのreloadを呼びます。
既に稼働しているapplicationもrecipeにより再起動されることがあります。build／fetch／artifact転送は行いません。
`stop` は `provisioning.ssh_scp.lifecycle.stop: true` を宣言したrecipeだけが提供します。
Raspberry Pi 5はrecipe 7、RK3506はrecipe 6から対応します。Productが参照するgar-toolsを更新し、
`target prepare` でhelperを導入してください。recipe更新後のbuild・preflightではprovenanceも揃える必要があります。
停止は冪等で、稼働build IDを無効化して停止状態を確認します。Targetの電源やboot時の自動起動設定は変更しません。
`prepare --json` は非対話権限が不足すれば転送前に失敗します。passwordを必要とする初回準備はJSONなしで実行します。

## `gar system`

| Action | 内容 |
|---|---|
| `build` | 宣言順に各nodeをbuild。simは通常の一括buildを利用 |
| `deploy` | 宣言順に配置。simは必要な全snapshotを検証後に配置 |
| `start` | 宣言順にruntime／applicationを開始 |
| `stop` | 逆順にruntime／applicationを停止。接続は保持 |
| `status` | 各nodeの状態を照会 |
| `status connections` | このsystemが開始したBridge接続を照会 |
| `diag` | 各nodeのhealthとbuild IDを診断 |
| `test` | 診断後に任意のscenarioを実行 |
| `connect` | nodeごとのSSH Bridge tunnelを一括開始 |
| `disconnect` | このsystemが開始したBridge tunnelを一括停止 |

```bash
gar system connect --file gar-system.json --port tx=8081 --port rx=8082 --json
gar system status connections --file gar-system.json --json
gar system start --file gar-system.json
gar system stop --file gar-system.json
gar system disconnect --file gar-system.json --json
```

```bash
gar system test \
  --file gar-system.json \
  --scenario scenarios/e2e.json \
  --bridge tx=http://127.0.0.1:8081 \
  --bridge rx=http://127.0.0.1:8080 \
  --json
```

`--file`の既定値は`gar-system.json`です。
`system start` はnodeのruntime／applicationとtopology由来envを扱い、SSH tunnelを自動作成しません。
`system connect` はSSH Remote Simulationに対応します。全nodeの対応可否とportを検証してから接続を開始し、
remoteのBridge port 8080を異なるloopback portへ転送します。`--port NODE=PORT` を省略したnodeは
`simulation_host.bridge_port` を使います。Targetやhostless backendの一括接続は未対応として開始前に拒否します。
接続が途中で失敗した場合は今回作ったtunnelを停止し、以前から存在する接続を保持します。
所有権はsystem fileの絶対pathとprocessの起動識別情報で管理します。同じfileを指定すれば、
内容やworkspace設定が変わった後、fileを削除した後でも `disconnect` できます。
異なるportへ変更するときは一度disconnectしてください。外部tunnelやnodeのapplicationはdisconnectの対象外です。
停止確認に失敗した接続は記録を残してエラーを返します。`status connections` の成功はBridgeのhealthを保証しません。
`--bridge` は既存の接続先を指定するだけで、接続開始の指示ではありません。
`system test` のURLは `--bridge`、同じfileの稼働中接続、workspaceのbridge portの順で解決します。
接続後にworkspaceやSSH hostを変更した場合は、古い接続の再利用を拒否します。
`system test` が後片付けするのはscenarioの操作状態で、別途開始したruntimeやtunnelの停止は利用者側で行います。

## `gar hw`

```bash
gar hw init --dir hardware
gar hw validate --workspace Local/Product --json
```

`validate`はrequirements、capabilities、bindingをoffline検証し、SSHや実機書込みは行いません。

## 補助コマンド

```bash
gar terminal run --title "GAR" --command "gar config"
gar terminal gc --dry-run
gar completion powershell
```

`gar usb`はLinux-only USB toolをWSL2で使う旧環境向けです。Windows native UUU／COMでは使いません。
