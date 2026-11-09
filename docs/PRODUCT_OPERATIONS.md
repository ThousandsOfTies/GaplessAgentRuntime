# Productが定義する操作

GAR本体は固定の `product list` / `product validate` / `product help` / `product run` を提供します。
新しい操作名、実行プログラム、引数、結果の項目はProductリポジトリに置きます。
Productごとのparserやコマンドを生成・インストールする処理はありません。

## 定義と実装

Productルートの `gar-operations.json` の例です。

```json
{
  "schema_version": 1,
  "operations": {
    "camera": {
      "description": "カメラの診断",
      "entrypoint": "tools/camera.py",
      "runtime": "python",
      "args": [],
      "timeout_seconds": 90,
      "result": "json",
      "result_fields": ["ok", "camera", "status", "error"]
    }
  },
  "aliases": {
    "target camera": "camera",
    "camera-check": "camera"
  }
}
```

`tools/camera.py` も同じProductで管理します。カメラへのアクセス・状態判定・
機器固有の引数はその処理が実装します。定義例だけではカメラ機能は実装されません。

```bash
gar product list --workspace Local/Product --json
gar product validate --workspace Local/Product --json
gar product run camera --workspace Local/Product --json -- --device usb0
gar product help camera --workspace Local/Product
```

GARは選択したworkspace内だけから定義を読み、その時点のファイルを使います。
新しい定義を追加した後の再ビルド・グローバル登録・GAR本体の変更は不要です。
同じ操作名でもProductが異なれば別の実装を持てます。

`entrypoint` はProduct内の相対パスです。絶対パス、親参照、解決先がProduct外にある
リンクは拒否します。PythonはGARと同じPython、NodeはPATH上のNodeを使います。
`runtime` は `python`（既定）または `node`。Nodeでは `.js/.cjs/.mjs` を指定します。
作業ディレクトリはProductルートで、シェルを介さず引数配列で呼び出します。
`args` は固定の引数配列で、利用者の引数はその後へ追加します。
タイムアウトは既定90秒、1〜3600秒。認証画面などを持つ操作はProductが長めに指定します。

`--workspace` と `--json` は最初の `--` より前ではGARが処理します。
`--` 以降の文字列・空白を含む引数・オプションはProductへそのまま渡します。
引数の検査、`--help`、認証画面はProduct処理が担当します。認証情報を引数へ渡してはいけません。

## Alias

上の定義なら `gar target camera` / `gar camera-check` からも同じ処理を呼べます。
Aliasは選択Product内でだけ有効です。固定の `product run camera` 呼出しへ引数を変換し、
GARのparserに新コマンドを追加しません。

Aliasは1または2語。既存の `target build` / `sim start` などの標準コマンド、
そのグループ名を上書きできません。Alias同士の曖昧な前方一致も拒否します。
標準コマンドはProduct定義を読まず、従来の経路を維持します。
標準コマンドとの衝突は `validate` が報告します。正式な `product run` は衝突したAliasに影響されません。
Aliasの一覧は `product list` で確認します。標準コマンドのhelpには追加されません。

## 結果と検証範囲

`result: "json"` が既定です。処理はstdoutにJSONオブジェクト1件を返します。
`result_fields` にProductが列挙した項目だけがGARの `result` に入ります。
省略時は `ok/state/error`。カメラなど新しい機能の結果もProduct側で項目を追加できます。
秘密情報を返さず、出力する結果の内容はProductが管理してください。

GARの共通結果は `operation/result/ok/exit_code` とworkspace情報です。
Alias経由では `alias` も入り、`--json` のcommandは一律 `product.run` です。
終了値が非0、または結果の `ok` がfalseなら全体も失敗します。
JSON不正・起動失敗・タイムアウト時に子プロセスの任意出力やstderrは表示しません。
`result: "text"` は明示的にstdoutを受け取る契約です。出力に秘密情報を含めないでください。
ヘルプは `gar product help 操作名` で表示します。この入口だけが `--help` を渡し、text応答を受け取ります。
`run` は `-h` / `--help` が引数に含まれても結果形式を変更しません。

実行環境に `GAR_PRODUCT_ROOT` / `GAR_PRODUCT_OPERATION` / `GAR_PRODUCT_WORKSPACE` を渡します。
定義の一覧・検証は処理を実行しません。`run` はProductのコードを利用者の権限で実行します。
操作ごとの副作用、実機の承認、build ID・health・物理検証の意味はProductが記述します。
操作が成功しただけでGAR標準のartifact検証や実機動作確認に合格したことにはなりません。

## 以前の個別入口からの移行

以前の `gar-target-audio/wifi/trace/update/probe.json` と専用GAR分岐は廃止しました。
各入口を `gar-operations.json` の操作へ移し、必要なら従来の呼び方をAliasにします。
`probe` の引数検査・`verification: probe_only` もProductが返す処理に移します。
新しいProductの定義がない場所では、これらのAliasは存在しません。

`gar-simulator.json` は既存のsimulator lifecycle backendの契約として維持しています。
任意のProduct操作は本ファイルへ追加し、標準build/deploy/startの動作と分けて定義します。

## 実行環境と制限

Python操作は `"python": ".venv/Scripts/python.exe"`（Linuxは `.venv/bin/python`）でProduct専用の環境を指定できます。Product内の相対パスを使い、環境の作成と依存導入はProductが管理します。省略時はGARのPythonを使います。
通信はUTF-8。JSONの `ok` は省略可能で、省略時は終了値に従い、指定する場合はbooleanが必要です。stdoutとstderrはそれぞれ1MiBまで読みながら制限します。
タイムアウト・取消・終了時に、操作が起動したローカルのプロセス群を終了します。WindowsはJob Object、POSIXは専用process groupを使用します。通信先で始まった実機処理の取消はProduct側で別途管理します。
