# USB audio state setup

`gar target audio --workspace Local/Product --json` invokes the local Product's
`gar-target-audio.json` descriptor:

```json
{"schema_version":1,"entrypoint":"tools/target-audio.py"}
```

GAR uses the same bounded private configuration hook as Wi-Fi, with a separate
descriptor and an allowlisted result. The Product owns the expected card ID,
USB identity, verified playback level and Target connection. Reusable Linux
ALSA save/restore and Windows masked authentication belong in gar-tools.

The recipe saves the working card state, verifies restoring that saved state,
and arranges restoration when the selected USB audio device is detected.
It does not redeploy or restart the App. Linux authentication is required for
the protected state file and udev rule. Passwords must never be CLI arguments,
source files, logs or result JSON. Actual power-cycle and voice confirmation
remain physical verification steps.
