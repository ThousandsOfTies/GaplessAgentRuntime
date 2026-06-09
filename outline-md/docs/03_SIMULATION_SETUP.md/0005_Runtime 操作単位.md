## Runtime 操作単位

`gar sim env start` が担当するのは、アプリではなく simulation runtime の起動です。bridge / CUSE / gpio-sim を個別の生コマンドで起動するのではなく、`gar` の操作単位を使います。

```bash
gar sim env deploy
gar sim env start
gar sim env diag --json
gar sim env log
```

GPIO dummy runtime だけを扱う場合:

```bash
gar sim gpio plan --json
gar sim gpio install
gar sim gpio start
gar sim gpio status --json
```

アプリはその後 EC2 にログインし、本番と同じ `~/sensor_demo` で起動します。

---
