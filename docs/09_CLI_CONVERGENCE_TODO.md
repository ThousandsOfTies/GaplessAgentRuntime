# CLI収束 TODO

承認済み方針: `gar <code|sim|target> <action> [subject] [options]` を通常操作の入口とする。
第二引数を動詞に揃え、必要な場合だけ第三引数で部品を選ぶ。旧構文は互換aliasとして維持する。

操作仕様の正本は01_COMMAND_REFERENCE・06_SIMULATION、検証範囲の正本は07_VERIFICATIONとする。
この文書は未完了作業と段階ごとの検証履歴を管理する。

## 操作契約

- 共通語彙は `prepare / build / deploy / start / stop / status / log / diag`。
- `code` の `build / deploy` は当面追加しない。
- `sim build / deploy` はbackendが必要とするappとruntimeを扱い、artifact自体は分離したまま保持する。
- `start` はbuildやdeployを暗黙実行しない。
- `stop` は通常のsession／runtime／applicationを止める。VMの停止は `stop host` で明示する。
- `target deploy` の既存の再起動・health確認は維持する。flash系Targetの保証とは区別する。
- 未対応操作を成功として扱わない。backendの能力と、未実装のCLI入口を区別する。
- `io / gpio / infra` の専門操作、`config / hw / system / terminal / usb / completion` は必要な独自語彙を維持する。

## 第1段階: 既存機能で通常の入口を揃える

- [x] actionとsubjectの対応を一つの定義にまとめる。
- [x] `sim build/deploy/start/stop/status/log/diag [subject]` を追加する。
- [x] `sim build/deploy` の対象省略時は必要なartifact一式を処理する。
- [x] 一括deployは必要なsnapshotの存在・checksum・設定architectureを転送前にすべて検証する。
- [x] `sim runtime build` などの旧構文を互換入口として維持する。
- [x] `code start host / stop host` を既存のboot／shutdownへ接続する。
- [x] `target start` を既存のapplication lifecycle APIへ接続する。
- [x] help・補完は新構文を優先し、旧構文の実行互換性を検証する。
- [x] コマンドリファレンス、チュートリアル、Simulation手順、再試行案内を新構文へ揃える。
- [x] focused test、`make check`、文書内コマンド・リンク、`git diff --check` を確認する。

第1段階の `sim start/stop/status/log/diag` は既存runtime操作を既定とし、hostは明示操作を保つ。
host・接続・runtime・appをまとめた観測は第2段階で扱う。

### 第1段階の検証結果（2026-09-10）

- Linux／Python 3.14.4で `make check` 成功。Python 528件、JavaScript 5件、lint・format・shell構文を確認。
- Docker Desktopの起動エラーのため、既存WSL Ubuntuの隔離コピーで現在の差分を反映して実行。
  GARの設定・artifact・credentialを検証コピーへ持ち込まず、実機／VMの操作は行っていない。
- Windows／Python 3.11で追加17テスト成功。`gar.cmd` を使う実際のPowerShell補完も確認。
- 関連129テストのWindows実行では既存の5件が失敗。同じ5件を変更前のHEADで再実行し、同一の失敗を確認。
  Windowsの短縮path、POSIX絶対pathの判定、sshfsを前提とするテストであり、別途整理する。
- 文書の57コマンド例・12ローカルリンクと、Simulation対応表をCLI定義へ照合。`git diff --check` 成功。
- 実機、Codespaces、Sim HostでのE2Eは未実施。ログはGit管理外の `.gar/cli-convergence/` に保存。

## 第2段階: 共通動詞の対応範囲と結果を揃える

- [x] `status / diag` で該当するhost・接続・runtime・appをまとめて報告する。
- [x] 共通actionの対応可否をhelpと機械可読結果へ表示する。
- [x] `code prepare / log / diag` の操作契約と実装を揃える。
- [x] `sim prepare` の初期準備範囲をTarget Pack／host providerの責務に沿って実装する。
- [x] `target stop` をrecipeの明示的なcapabilityとして実装する。
- [x] `--workspace / --json` と失敗時の結果形式を共通化する。
- [x] artifact反映、再起動、health確認、部分失敗の報告をsim／targetで整理する。
- [x] 複数nodeのBridge接続準備と `system` の対応範囲を明確にする。

### 第2段階の到達範囲（2026-09-11）

- `code prepare` はtool・workspace・認証の検証、`log` はCodespace作成log、`diag` はhost／接続の観測とする。VM起動や設定修復はstartが担う。
- `sim prepare` は共通Ubuntu bootstrapまたはTarget PackのDocker host定義を利用する。app／runtime artifactは扱わない。
- `status / diag` はhost・接続・runtime・appを集約する。対象外・不明・未配置を区別し、空serviceの起動をapp稼働と扱わない。
- 通常actionは単一JSONへ統一し、進捗・子process出力を結果と分離する。旧Target出力の個別fieldを保ち、CLIとbackendの終了値を分ける。
- `target stop` は明示的なrecipe capability。Raspberry Pi 5のrecipe 7、RK3506のrecipe 6で提供する。Product-pinned toolsの更新・prepareが必要。
- Simulation一括deployは配置済みartifactと途中失敗の可能性を報告する。running build ID一致の保証・自動rollbackは未対応と明示する。
- `system start` はtunnelを自動準備しない契約を明記する。node別のstart／stop／runtime statusは同じ `--panel-port` で操作する。
- gar-toolsのLinux Target既定値を現行のSSH Remoteへ合わせ、契約checkerでは `simulation_host` を省略可能なprovider選択として扱う。

### 第2段階の検証結果

- Linux／Python 3.14.4でGAR本体の `make check` 成功。Python 556件、JavaScript 5件、skipなし。
- gar-toolsの `make check` 成功。Python 66件＋Bridge 24件、CのI2C／PCA9685チェック、全6 Target manifestの契約検証、skipなし。
- Windowsで今回追加28件、前段のaction構文17件、port forward 11件が成功。
- Windows関連114件の実行では既存のpath表記／sshfs前提で5件が失敗。変更前HEADで同じ失敗を再現済み。
  今回はPOSIX lifecycle pathの判定を修正し、port停止テストもWindowsのprocess操作をmockするようにした。
- 文書67コマンド例・12ローカルリンク・Simulation対応表を実CLIへ照合。両repositoryの `git diff --check` 成功。
- Linux確認は既存WSL Ubuntu内の隔離コピーで実施。検証用依存とCコンパイラを導入し、GARのworkspace設定・credential・artifactは持ち込んでいない。
- 実機、Codespaces、Sim HostでのE2Eは未実施。ログはGit管理外の `.gar/cli-convergence/` に保存。

## 第3段階: 再発防止と実環境確認

- [x] コマンドリファレンスの対応表をCLI定義から自動照合する。
- [x] Windowsの全unit testと、実際のgar.cmdによる照会・拒否・PowerShell補完を確認する。
- [ ] Docker Desktop・VirtualBox・Codespaces・対応Targetで一連の実環境操作を確認する。
- [x] backend別の未対応操作を、副作用の前に拒否する検証を追加する。
- [x] Windowsで既存テストが持つPOSIX／path表記／process signalの前提を整理する。
- [x] 旧構文の利用箇所を確認し、互換aliasの将来方針を決める。
- [x] Simulationのexpected／running build IDを比較できるprotocolを実装する。
- [x] systemのBridge接続・切断を一括管理する入口を設計・実装する。
- [x] 完了した移行事項を正本文書へ整理し、このTODOを未完了作業・検証履歴の管理に限定する。

### 第3段階の到達範囲（2026-09-11）

- `tools/check_command_reference.py` でトップレベル、共通action、code／sim／targetの表、
  docs内のshell例とローカルリンクを照合する。CLIへのaction追加、subject／既定対象のずれ、
  無効な専用option、通常例への旧構文の再混入を検出する。`make check` とCIからunit test経由で毎回実行する。
- Simulationのcapability表示と実行前チェックを共通化する。Renode／ESP32 QEMU／AWS SSM等の未対応runtimeは
  build、artifact読出し、接続処理へ進めない。Wokwi／MuJoCoのruntime artifact不要という互換動作と、
  明示的なhost操作は維持する。Target startもlifecycle未対応なら接続前に拒否する。
- Target start／deployの稼働確認失敗で、実行した操作に対応する案内を返すよう修正する。
- Windowsの短縮path、POSIX mode、sshfs、process group、COM変換のテスト前提を修正する。
  tar内のPOSIX絶対pathもhost OSに依存せず拒否する。Windows CIを全unit testへ拡張する。
- lintの探索から外れていた `scripts/gar_lib/build` も明示的に検査する。
- GARのinfra文書とgar-toolsの13ファイルに残っていた手順・コメントを新構文へ更新する。
  旧aliasは削除期限を設けず、互換テストで維持する。新規手順・help・補完はaction-firstを使う。

### 第3段階の検証結果

- Linux／Python 3.14.4でGARの `make check` 成功。Python 571件、JavaScript 5件、skipなし。
- Windows／Python 3.11で全571件を実行し、失敗なし。シンボリックリンク作成権限がないため8件を明示的にskip。
  同じ実リンク検査はLinuxで成功。POSIXのmode bit検査はPOSIXで行い、Windows ACLを検証済みとは扱わない。
- 実際のWindows `gar.cmd` で3環境のcapability JSON、Local code status、Wokwi prepareの未対応拒否、
  hostへのruntime専用optionの拒否、PowerShell補完を確認。前後でworkspace設定の内容が変わらないことも確認。
- gar-toolsの `make check` 成功。Python 66件＋Bridge 24件、Cチェック、全6 Target manifest契約検証、skipなし。
- docsの67コマンド例、12ローカルリンクと対応表の自動照合が成功。
- gar-toolsの変更した文書について44コマンド例・2ローカルリンクを照合。両repositoryの `git diff --check` も確認。
- Linux確認は既存WSL内の隔離コピーで実施。実機・Codespaces・Sim Hostの起動や配置操作は行っていない。
  ログはGit管理外の `.gar/cli-convergence/` に保存。

### 残項目の実装（2026-09-11）

- Simulationの最新snapshot・配置完了・起動時のIDを分離し、停止・PID再利用・外部再起動・health失敗を区別する。
  Linuxは実processとartifactも照合し、Wokwi／MuJoCoは起動用入力を固定する。
  保証範囲とunknownになる条件は06_SIMULATIONへ記載した。
- `system connect / disconnect / status connections` を追加。全nodeの事前検証、node別port、process所有権、
  途中失敗時の今回分だけの後片付け、停止失敗時の記録保持を実装した。
- `system stop` は逆順にruntime／applicationを停止し、接続は保持する。
  systemのsim build／deploy／status／diagも通常APIへ集約し、全artifact事前検証と稼働IDの結果を共有する。
  診断失敗時にもIDの証拠を残し、system JSON境界とコマンドリファレンス自動照合も拡張した。

### 残項目の検証結果

- Linux／Python 3.14.4でGARの `make check` 成功。Python 601件、JavaScript 5件、skipなし。
- Windows／Python 3.11で全601件を実行し、失敗なし。リンク作成権限に依存する8件とLinux `/proc` 専用の1件をskip。
  同じ検査はLinuxで成功した。
- Windows／Linuxで実際のローカル待受processを2個開始し、所有権の確認と停止を検証した。
  Linuxでは実processのscriptとartifactの照合も確認した。実SSH接続やsimulator内部動作のE2Eではない。
- 実際のWindows `gar.cmd` で接続状態JSON、空の接続の切断、未対応backendへのconnect拒否、
  PowerShellの新action／subject補完を確認した。前後でworkspace設定が変わらないことも確認した。
- systemを含む対応表、文書73コマンド例・13ローカルリンクを実CLIへ照合した。
  GARとgar-toolsの `git diff --check` も成功した。
- Linux確認は既存WSLの隔離コピーで実施。ログはGit管理外の `.gar/cli-convergence/` に保存した。

### 残る実環境確認

- [ ] 対象workspace・backendを確定し、prepare → build → deploy → start → diagを実サービス上で確認する。
- [ ] SSH Remote simの複数nodeでconnect → scenario → stop → disconnectを確認する。
- [ ] Docker Desktop／VirtualBox／Codespaces／対応Targetについて、実施した経路ごとの証跡を残す。

今回の事前確認ではDocker Engineへ接続できず、Wokwi CLIもGARの探索先に存在しなかった。
VirtualBoxの検証VMはworkspaceに登録されていない。GitHubの認証は確認できたが、Codespacesや
実機の操作対象は未確定のため起動・配置は行っていない。
これらはunit testの成功で完了扱いにせず、07_VERIFICATIONの未確認範囲として保持する。

## 関連する調査事項

CLIの整理に続けて、artifact検証範囲、gar-tools探索順、hardware CSV／JSON、Windows導入手順、
`--no-install`、dirty provenance、UUU manifestの条件を文書・実装双方で整合させる。
これらはコマンドの並べ替えだけでは解消しないため、変更範囲を分けて扱う。
