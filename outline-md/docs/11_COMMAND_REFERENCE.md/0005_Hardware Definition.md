## Hardware Definition

`gar hw` は、Excel のアサイン表に相当する hardware assignment CSV を扱う入口です。CSV は Gapless Agent Runtime 固有の設定でも、製品アプリ固有の設定でもなく、GPIO / I2C / SPI / 部品 / 接続の正本データとして扱います。

現時点の PoC では `Gapless Agent Runtime/hardware/` を置き場にします。これは実装を小さく始めるための暫定配置です。最終的には hardware assignment CSV を別 repo に分離し、Gapless Agent Runtime と製品プロセスがそれぞれ同じ CSV を読み、自分の実行形式へ変換する形にします。

想定する変換先:

| 読み手 | CSV から生成・解釈するもの |
|---|---|
| Gapless Agent Runtime / simulation runtime | `gpio-sim` line 定義、bridge 設定、CUSE I2C/SPI device table、systemd runtime 設定、配線 docs |
| 製品プロセス | `app_config.h`、`device_map.c`、board config JSON、テスト fixture |

アプリ実装上の変数名と CSV の `name` は強く結びつけません。結合点は GPIO line、I2C bus/address、SPI device/chip select などの物理・OS インターフェースに寄せます。

現時点では CSV テンプレート作成に加え、`gar sim env start` / `gar sim env diag` が GPIO line、I2C dev、SPI dev をこのCSVから読みます。後続で validate / docs 生成 / runtime 反映範囲を広げます。

| コマンド | 実行場所 | 目的 | 主な処理 | 備考 |
|---|---|---|---|---|
| `gar hw init` | Gapless Agent Runtime (venv) | 空の hardware 定義 CSV を作成 | `hardware/` に `components.csv`, `gpio.csv`, `i2c.csv`, `spi.csv`, `connections.csv` を作成 | `--dir`, `--force` |
