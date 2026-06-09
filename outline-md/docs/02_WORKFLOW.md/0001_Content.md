# 開発ワークフロー

SSH/scp + adb を用いたデプロイベースのワークフローです。実機接続は **adb を既定**とし、ネットワーク越し接続が可能な環境では SSH/scp を選択する方針です（詳細: [01_ARCHITECTURE.md](01_ARCHITECTURE.md)）。

現在の EC2 runtime は I2C/SPI を CUSE、GPIO を `gpio-sim` + GPIO chardev v2 で成立させています。アプリや起動スクリプトにシミュレーション固有の分岐を持たせず、EC2 と RasPi5 の起動定義を共通化します。
