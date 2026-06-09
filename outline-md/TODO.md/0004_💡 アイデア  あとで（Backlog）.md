## 💡 アイデア / あとで（Backlog）

- [ ] **rtk（トークン削減）の導入** — WSL2 で `curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/refs/heads/master/install.sh | sh` 後に `rtk init -g --copilot` を実行。詳細は AGENT.md「オプション: rtk」セクション参照。コストやトークン量が気になったときに対処。

- [ ] **検証軸に「ポータビリティ劣化チェック」を追加** — [OK] が押せても成果物の質が落ちていないかを見る目を入れる（押下回数だけ減って質が死ぬのを防ぐ）
- [ ] **AI の自己判断レイヤ** 実行前に AI が `--json` の結果を見て「やめておく / 直す」を選ぶループ（docs/13 の欠けているピース）
- [ ] **hardware assignment CSV の分離** — PoC 中は `Gapless Agent Runtime/hardware/` を正本置き場にする。最終的には Excel 代替のアサイン定義 CSV を別 repo に分離し、Gapless Agent Runtime は runtime/systemd/docs 用へ、製品プロセスは app config / device map 用へ、それぞれ変換して利用する
- [ ] **「装置」化デモ — 距離キープ P 制御 1 ループ** 既存 sim 資産だけで、目標距離を自律で保つ最小フィードバック制御を組む。get=vl53l0x / 制御=誤差×ゲイン（P のみ、I・D は欲しくなってから）/ put=LED 点滅速度 or PWM / 表示=ssd1306 に「目標・現在・誤差」。狙いは「LED が点くだけ」→「目標値を自律で保つ計器」への一段＝デモを機能証明から価値証明へ。自然言語→仮想でゲイン調整→実機 の既存閉ループに乗せる。遠い構想は [docs/14](docs/14_FUTURE_VISION_DEVICE_DISCOVERY.md)、これはその"足元版"

---
