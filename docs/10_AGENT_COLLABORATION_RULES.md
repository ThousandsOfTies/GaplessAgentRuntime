# AI / Human Collaboration Rules

## 基本方針

AI は通常作業を裏で実行し、結果を自分で確認する。
VSCode integrated terminal は、sudo password、GitHub 認証、クラウド認証、デバイス pairing など、人間の入力が必要な時だけ使う。

```text
通常作業:
  AI -> 裏で command 実行 -> stdout/stderr や状態確認を読む -> 続行

人間入力が必要な作業:
  AI -> visible terminal request を作る
  User -> integrated terminal に secret/auth input を入力
  AI -> 裏で状態確認 -> 続行
```

## AI が迷わないための判断

### 裏で実行する

- `which gh`
- `aws --version`
- `session-manager-plugin --version`
- `adb version`
- `agp init --no-install`
- build / test / lint
- log file の確認
- `.agp/config.json` や status file の確認

### visible terminal に handoff する

- `sudo` が必要な install / setup
- `gh auth login`
- `aws configure sso` などの cloud login
- device code / browser auth / pairing
- ユーザーが実機・外部環境で直接操作する必要がある手順

handoff 時、AI は password や token を要求しない。
AI は「どの terminal で、何を入力すべきか」だけを伝える。

例:

```text
AgentCockpit User Action terminal で sudo password の入力が必要です。
VSCode integrated terminal に直接入力してください。
入力が終わったら、こちらで状態確認して続けます。
```

## `agp init` の進め方

1. AI はまず裏で `agp init --no-install` を実行して不足項目を確認する。
2. 依存コマンドがすべてある項目は、そのまま完了として扱う。
3. 不足があり sudo/auth が不要なら、AI が裏で解決できるか試す。
4. sudo/auth が必要なら、provider の handoff により `.agp/terminal-requests/*.json` を作る。
5. ユーザーに integrated terminal で必要入力をしてもらう。
6. AI は `which ...` や `agp init --no-install` を裏で再実行し、次の不足項目へ進む。

## 入力してよいもの / いけないもの

AI が送ってよい入力:

- ユーザーが明示した選択値
- 非 secret のコマンドや設定値

AI が送ってはいけない入力:

- sudo password
- GitHub / cloud auth token
- device code
- private key / passphrase
- その他 secret

## Terminal Bridge の位置づけ

Terminal Bridge は通常の command runner ではない。
通常作業は AI の裏実行を優先し、Terminal Bridge は人間入力の受け皿として使う。

Terminal Bridge は terminal 出力の捕捉や追加入力送信を担当しない。
AI は terminal buffer を読もうとせず、裏で状態確認コマンドを実行して復帰する。

## 復帰手順

handoff 後に何が起きたかわからない場合、AI は terminal buffer を読もうとしない。
代わりに次を確認する。

```bash
agp init --no-install
which gh && gh --version
which aws && aws --version
which session-manager-plugin && session-manager-plugin --version
which adb && adb version
find .agp -maxdepth 3 -type f | sort
```

不足が残っていれば、次の handoff を作る。
