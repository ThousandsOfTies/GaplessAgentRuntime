#!/bin/bash
# Gapless Agent Runtime — simulation host bootstrap
# EC2 初回起動時に user_data として実行される。
# - gpio-sim kernel module が modprobe できる状態にする
# - 診断・ABI 調査ツールを入れる
# アプリ成果物・systemd unit・runtime state は gar sim env deploy/start が担当する。

set -eux

apt-get update
apt-get install -y \
  linux-modules-extra-"$(uname -r)" \
  gpiod \
  strace

# gpio-sim を事前ロードしてインストール確認（失敗してもブートは止めない）
modprobe gpio-sim || true
