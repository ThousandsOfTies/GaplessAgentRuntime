# Local Ubuntu Sim Host (VirtualBox)

VirtualBox Ubuntuは、AWS EC2 Ubuntuと同じLinux-device simulation runtimeをローカルで実行する
Sim Hostです。Product buildやUUU／COM操作を担当しません。

人間がmachineごとに一度だけ行う準備:

1. VirtualBoxへUbuntuを作成し、host-only networkまたは明示的なNAT port forwardでWindowsからSSH可能にする。
2. Ubuntu kernelで`gpio_sim`を利用できることを確認する。
3. `infra/simulation-host/ubuntu-bootstrap.sh`をroot権限で実行する。
4. Windowsの`%USERPROFILE%\.ssh\config`へ固定aliasを登録し、host keyを確認する。
5. `gar config`でSimulation Environmentに`SSH Remote`、Sim Hostに
   `Local Ubuntu (VirtualBox)`を選び、VM名とSSH aliasを保存する。

例:

```sshconfig
Host gar-sim-local
    HostName 192.168.56.10
    User gar
    IdentityFile C:/Users/USER/.ssh/gar-sim-local
```

確認:

```powershell
VBoxManage showvminfo "GAR Ubuntu Sim" --machinereadable
ssh gar-sim-local 'sudo modprobe gpio-sim && test -d /sys/kernel/config'
gar sim status host --workspace Local/Product
```

VMのOS、package、kernel設定はsnapshotだけに依存させず、共通bootstrapまたはgar-toolsの
simulation runtime recipeへ戻します。VM名、IP、SSH鍵はmachine-local設定でありrepositoryへcommitしません。
