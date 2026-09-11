# 開発環境

GARは同じコマンドの背後で実行場所を切り替えます。

| 環境 | 役割 |
|---|---|
| Windows | `gar`の操作面、workspace、artifact、USB／COM／UUU |
| Local Docker | Product build hook、test、Linux tool |
| Codespaces | cloud BuildEnvironment |
| VirtualBox Ubuntu | local Linux Sim Host |
| AWS Ubuntu | remote Linux Sim Host |
| Physical Target | 配置済みapplicationと実deviceの実行 |

WSLは必須ではありません。Docker Desktopが内部でWSL2を使う場合も、GARからはDocker Engineとして扱います。

## BuildEnvironmentの選び方

- 通常はLocal Docker
- 大きなSDKや固定devcontainerが必要ならCodespaces
- Product hookがDockerを呼ぶ場合だけDocker socketを渡す

Local DockerはProduct workspaceを`/workspace`へbind mountし、`scripts/product-*-build.sh`を実行します。

## Simulationの選び方

- local Linux simulation: VirtualBox Ubuntu
- remote／aarch64 simulation: AWS Ubuntu
- MCU／robot固有simulation: WokwiまたはMuJoCo

VirtualBoxとAWSは`ssh_remote` runtimeを載せるhost providerです。hostを切り替えてarchitectureが変わった場合はartifactをbuildし直します。

## 実機接続

| Target例 | 接続 |
|---|---|
| Raspberry Pi／Luckfox Linux | SSH／SCP + Target recipe |
| ESP32 | esptool |
| NXP i.MX | Windows native UUU + optional COM verification |

実機はbuild環境ではありません。toolchainはDocker／Codespaces側に置きます。

## Machine-local state

`.gar/config.json`はworkspaceごとに次を保存します。

- Product workspace pathと表示名
- Targetとenvironmentの選択
- build image
- VM名、SSH alias、COM portなどの接続値

`.gar/`はGit管理外です。秘密鍵、token、cloud credentialは保存しません。

## 判断基準

- Product behaviorと配線はProduct側
- Board、OS、toolchain、provisioningはTarget Pack側
- build依存はDocker／Codespaces
- IP、VM名、COMなどはmachine-local設定
- 実機flash前のBoard、boot mode、書込み先の確認は人間が担当

具体的な操作は[最短チュートリアル](00_ZERO_TO_TARGET_TUTORIAL.md)を参照してください。
