# シミュレーション・セットアップ

このドキュメントでは、クラウド上（AWS EC2 Graviton）で物理ハードウェアをエミュレートする仕組みについて解説します。

Gapless Agent Runtime のシミュレーション方針は、アプリケーションにシミュレーション専用の分岐や HAL を持たせることではありません。実機用アプリは実機と同じ `/dev/*` を開くだけにし、差し替えは EC2 側の device compatibility runtime に閉じ込めます。

現在は I2C/SPI を CUSE、GPIO を `gpio-sim` + GPIO chardev v2 で実現しています。EC2 側の runtime が実機と同じ `/dev/i2c-1`、`/dev/spidev0.0`、`/dev/gpiochip0` を用意するため、アプリは `~/sensor_demo` を直接起動します。runtime の設定・実行ファイルは `/etc/gar/hardware/`、`/usr/local/sbin/`、`/usr/local/lib/gar/`、`/run/gar/` に寄せ、アプリ本体だけを本番と同じユーザー領域の成果物として扱います。

移行の具体的な設計とステップは [12_CUSE_MIGRATION_PLAN.md](12_CUSE_MIGRATION_PLAN.md)、このアプローチがなぜ価値を持つかは [06_INDUSTRY_TRENDS.md](06_INDUSTRY_TRENDS.md) にまとめています。
