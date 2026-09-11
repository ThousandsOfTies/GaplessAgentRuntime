# 検証状態

この文書は、現在の実装で機械的に確認できる範囲と、実環境で未確認の範囲を示します。

## 自動検証

`make check`は主に次を確認します。

- Python lint／formatとunit test
- CLI、Windows `.cmd` launcher、PowerShell補完
- action-first構文と旧構文の互換性、subjectに応じたオプション検証
- コマンドリファレンスのトップレベル・共通action・code／sim／target対応表と、docs内の実行例・ローカルリンク
- 未対応backendのbuild／転送／接続開始前の拒否と、capability表示との整合
- Simulationの一括build／deployと全snapshotの転送前検証
- code／sim／targetの共通JSON、環境の層ごとの観測、capability表示
- code prepare／log／diag、sim prepare、Target recipeのstopと稼働ID無効化
- Simulationの途中配置失敗、空app serviceの識別、別portの接続停止
- Simulationの配置IDと起動IDの分離、最新snapshot照合、再起動・停止・PID再利用・health失敗
- Wokwi／MuJoCoの起動入力固定、Linuxの実processとartifactの照合
- systemの一括接続・切断、port衝突、所有権、途中失敗時の後片付け、実ローカルprocessの開始・停止
- artifact schema、checksum、provenance、architecture guard
- Docker BuildEnvironment
- Target prepare／deploy／configure／lifecycle／preflight
- host native UUUとserial verificationのadapter
- VirtualBox host controller
- simulation process、Bridge、diagnostic
- hardware contract、system topology、scenario
- VS Code Terminal Bridge

テスト件数は変化するため固定しません。
文書の照合だけを行う場合は `python tools/check_command_reference.py` を実行します。
対応表の説明文は手で編集し、action・subject・既定subjectとの構造的な整合を検査します。
この検査はunit testに含まれるため、`make check` とLinux／Windows CIの両方で実行されます。

Windowsでも全unit testを実行します。POSIXのmode bitはPOSIXで確認し、Windowsのprocess起動・停止と
COM portはWindowsの契約で確認します。シンボリックリンク作成権限のないWindowsでは該当検査を明示的に
skipし、Linuxで実リンクを使って検証します。WindowsのACL検証や実機E2Eを代替するものではありません。

## 実環境で確認済み

| 経路 | 状態 |
|---|---|
| Windows CLI | 全unit testと実gar.cmdの照会・未対応拒否・補完を確認。リンク作成権限がない場合の検査はLinuxで補完 |
| EC2 Graviton Linux simulation | CUSE／gpio-sim／Bridge／application deployを確認 |
| Raspberry Pi 5 | SSH、systemd recipe、GPIO／SPI／videoを確認 |
| Luckfox Lyra Plus RK3506 | armv7 build、BusyBox recipe、GPIO／SPIを確認 |
| GarStreamTx/Rx | discovery、RTP映像、display、rotary、metricsを確認 |

## 未確認または未実装

| 領域 | 現在地 |
|---|---|
| Windows + Docker Desktop | adapter実装済み。bind mount性能を含む一連のmachine E2Eは限定的 |
| VirtualBox Linux simulation | controller実装済み。実VMのCUSE／gpio-sim／Bridge E2Eは未完了 |
| NXP UUU + COM | backend実装済み。自動HILとしての継続検証は未整備 |
| Renode | setupのみ。GAR runtime lifecycleは未実装 |
| ESP32 QEMU | setupと手動runnerのみ。GAR runtime lifecycleは未実装 |
| AWS SSM simulation | setup optionのみ |
| Wokwi scenario | Product形式を利用。共通Bridge scenarioへ統一途中 |
| Physical Golden HIL | read-only preflight／diagまで。自動deployと物理操作は未実装 |
| CLI収束 | 構文・対応表・実行前の拒否・recipe sandboxを自動検証。prepare／stop／状態集約の実環境E2Eは未実施 |
| Simulation running build ID | protocolとbackend実装、自動テストあり。Sim Host／Wokwi／MuJoCo実サービスでのE2Eは未実施 |
| systemのBridge接続準備 | SSH Remote simの一括接続・切断を実装。所有権・rollbackとローカルprocessで検証。実SSH複数nodeのE2Eは未実施 |

## 完了の基準

1. 対象repositoryのcheckが通る。
2. artifact、diagnostic、scenario結果を機械的に確認できる。
3. Targetはdeploy後、Simulationはdeployとstart後にrunning build IDがartifactと一致する。
4. 実機動作を主張する場合は、そのTargetで確認する。
5. 未実装backendやskipped CIを成功扱いしない。

workflow固有の条件は[workflow README](../.github/workflows/README.md)を参照してください。
