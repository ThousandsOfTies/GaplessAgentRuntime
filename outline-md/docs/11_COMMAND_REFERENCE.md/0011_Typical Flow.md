## Typical Flow

```bash
# WSL hub: first setup
cd ~/Yurufuwa/AgentCockpit
make init
make start
# or directly:
gar setup

# WSL hub: after creating/recreating a Codespace
gar code start
# WSL hub: disconnect the Codespace view when needed
gar code stop

# Codespace build VM: postCreateCommand が scripts/post-create.sh を自動実行済み
# target software ごとの README / build script に従ってビルド

# WSL hub: target runtime は fetch + deploy を一発実行
gar target sync

# WSL hub: simulation runtime は artifact bundle を EC2 へ配置
gar sim boot
gar sim env deploy
gar sim env start
# VS Code simulation terminal profile などからログインし、本番と同じ起動手順を実行
~/sensor_demo
```
