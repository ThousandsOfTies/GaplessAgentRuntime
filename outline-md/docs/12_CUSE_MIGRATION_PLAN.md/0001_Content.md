# LD_PRELOAD shim → CUSE / gpio-sim 移行記録

このドキュメントは、EC2 simulation runtime で使用していた **GPIO / SPI の `LD_PRELOAD` shim** を、現在の **CUSE + gpio-sim ベースの fake `/dev/*` runtime** に置き換えた設計判断と移行記録です。

2026-06-03 時点で、アプリ起動コマンドから `LD_PRELOAD` は削除済みです。EC2 でも RasPi5 でも `~/sensor_demo` を直接起動し、EC2 側では I2C/SPI を CUSE、GPIO を `gpio-sim` + GPIO chardev v2 で提供します。

実装は別リポジトリ `gar-tools/cuse-stubs/` で行い、本リポジトリの `gar` CLI / アプリ起動スクリプトは「runtime 側で `/dev/*` が用意される」ことだけを前提に整える、というスコープ分担で進めます。

関連ドキュメント:
- [01_ARCHITECTURE.md §4](01_ARCHITECTURE.md) — 現状の PoC と方向性
- [03_SIMULATION_SETUP.md](03_SIMULATION_SETUP.md) — 全体構成と起動手順
- [05_RESULTS.md](05_RESULTS.md) — 現状の動作確認結果と TODO
- [06_INDUSTRY_TRENDS.md](06_INDUSTRY_TRENDS.md) — 業界比較における位置付け

---
