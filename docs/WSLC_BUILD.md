# WSL Containers build environment

Windowsでは、Docker Desktopの代わりにWSL Containers (`wslc.exe`) をProductの
build環境として選択できます。WSL 2.9.3以上が必要です。

```powershell
wsl --update
& "C:\Program Files\WSL\wslc.exe" --help
```

`gar config` のBuild環境で **Local WSL Containers** を選択します。
Windowsの新規設定ではWSLCを番号1・Enter時の第一候補にし、Docker、Codespacesの順で表示します。
Windows以外ではDockerを先頭にします。保存済みの明示選択は保持します。
保存されるworkspace設定は `selected_environments.codespace: "wslc"` です。
既存workspaceの選択は自動では変更しません。

```text
gar target build --workspace Local/Product
```

GARは既存の `infra/build/Dockerfile` でbuildイメージを作成し、Productの
`scripts/product-target-build.sh` をLinuxコンテナ内で実行します。
`build.image` によるイメージ指定、`build.cache` によるworkspace単位のvolume cache、
成果物の検証・snapshot captureはDockerの場合と同じです。
WSLCのイメージとvolumeはDockerの保存領域とは別なので、初回は依存物の取得が必要です。

WSLCのimage inspectionはJSONを解析します。DockerのGo template形式には依存しません。
更新前から開いているterminalでも、標準インストール先の `wslc.exe` を検出します。
`build.docker_socket: true` は未対応として、build前にエラーにします。
この選択はbuild専用であり、Docker simulation hostをWSLCへ切り替えるものではありません。

## 実ビルド確認（2026-11-10）

WindowsのWSL 3.0.5.0 / WSLCで `Local/GarVibeRemote-M5StickC` を検証しました。
Productソースや既存のDockerfileは、この検証のために変更していません。

| 確認 | 結果 |
| --- | --- |
| 既存DockerfileからのWSLCイメージ作成 | 成功 |
| WSLC image inspectによるbuild-spec fingerprint照合 | 一致 |
| GAR CLIからのPlus2実機向けbuild | 2回ともexit 0 |
| workspace bind mount / named volume cache | 実ビルドで利用成功 |
| キャッシュ利用時の2回目のGAR build | 19.36秒、成功 |
| firmware.bin | 1,908,816 bytes |
| bootloader / partition / boot_app0 / firmwareのsnapshot | 保存成功、checksum検証成功 |
| WindowsのWSLC・Docker build・設定テスト | 54件成功 |
| WSLC内での全Pythonテスト | 666件成功 |
| VS Code拡張のNodeテスト | 5件成功 |

初回のPlatformIO処理は依存物の取得を含め350.12秒でした。イメージ作成時間は別です。
検証時だけ選択を `wslc` に変更し、終了後に元の `local` へ戻しました。
実機への書き込み・接続確認は、このbuild検証には含めていません。

初回の作業ツリーでは `make check` もWSLC内で実行しましたが、別作業の既存ファイル3件のimport整形エラーで停止しました。
今回変更したPythonファイルのlint / formatと `git diff --check` は成功しています。
全PythonテストとNodeテストは、上記のとおり個別に最後まで実行しています。

ローカル検証ログは `.gar/wslc-verification/` に保存します（Git管理外）。
`image-build.log`、`firmware-build.log`、`target-build-first.log`、`target-build.log`、
`artifact-verification.json`、`warm-build-timing.json`、`make-check.log`、
`full-tests.log`、`node-tests.log` を参照してください。

## Windowsでの優先順位の確認（2026-11-10）

Windowsの設定メニューをWSLC、Docker、Codespacesの順にし、未設定時のEnterで
WSLCが選択・保存されることをテストしました。Windows以外ではDockerを先頭にします。
既存のDocker選択が、メニュー順の変更だけでは書き換わらないことも確認しています。

今回、実ビルド済みの `Local/GarVibeRemote-M5StickC` は明示的に `wslc` へ切り替えました。
他のworkspace設定と、このProductのTarget・Simulation・接続・cache設定が保持されたことを照合し、
通常の `gar target build` が成功することを再確認しています。

Windowsで関連テスト35件（WSLC 12件、環境探索23件）、WSLC内で全Pythonテスト670件と
Nodeテスト5件が成功しました。変更ファイルのlint / formatと `git diff --check` も成功しています。
この作業ツリーの `make check` には、前述の別作業のimport整形エラー3件が含まれていました。
今回のログは `.gar/wslc-priority/` に保存しています。

## 公開対象だけの検証（2026-11-10）

最新の公開mainへWSLC対応とその共通cache/API依存だけを適用した独立checkoutで、
`make check` が最後まで成功しました。lint、format、Pythonテスト643件（Windows専用1件はLinuxではskip）、
shell構文、拡張のJavaScript構文とNodeテスト5件を含みます。
WindowsでもWSLC関連テスト12件とコマンド出力・起動テスト4件が成功しています。
公開対象のcheckoutには、上記の別作業の整形エラーは含まれません。
ログは `.gar/wslc-publish/make-check-clean.log` に保存しています。
