# Interactive Target Wi-Fi configuration

Run `gar product run wifi --workspace Local/Product --json -- --transport ssh`
for a [Product-declared operation](PRODUCT_OPERATIONS.md). In `gar-operations.json`:

```json
{"schema_version":1,"operations":{"wifi":{"entrypoint":"tools/target-wifi.py","timeout_seconds":900,"result_fields":["ok","state","error","address","interface","internet"]}},"aliases":{"target wifi":"wifi"}}
```

The Python entrypoint must stay inside the local workspace. GAR starts it with
the explicit `--transport serial|ssh` choice, allows up to 15 minutes for owner
input, and accepts only allowlisted result fields. The hook owns its masked
input form. Do not put credentials in CLI options, descriptors, stdout or logs.
Generic OS provisioning belongs in gar-tools; hardware/connection bindings
belong in the Product. This does not build or deploy an App.

`gar product run wifi --workspace Local/Product --json -- --transport ssh --check`
observes the existing connection and network tools without changing settings.
The setup hook must not show an elevation prompt or repair IP settings in check
mode. Serial check mode is rejected before launching the hook.

SSH setup may explicitly repair the USB management address after a Windows UAC
confirmation. Network provisioning still requires the Target's own authorized
root/sudo authentication. Windows administrator consent does not provide Linux
root access. A successful result reports route/HTTPS and reconnect observations;
it does not imply a completed reboot or an App-level conversation check.

SSH is the default transport. `--repair-host ADDRESS` uses the Target's pinned
host key to validate a discovered LAN address before asking for owner credentials.
This recovery route retains the Target's existing Wi-Fi settings and restores
the USB management profile. Once USB is reachable, the radio reconnect test runs
over USB. Wi-Fi credentials are not retrieved to the PC in this mode.
