# USB audio state setup

Audio setup is a [Product operation](PRODUCT_OPERATIONS.md), declared in the
local Product's `gar-operations.json`:

```json
{"schema_version":1,"operations":{"audio":{"entrypoint":"tools/target-audio.py","timeout_seconds":900,"result_fields":["ok","state","error","saved","restoreVerified"]}},"aliases":{"target audio":"audio"}}
```

Use `gar product run audio --workspace Local/Product --json`. The optional alias
retains the previous `target audio` spelling; no audio command is in GAR core.
GAR runs the generic operation contract with declared result fields. The Product owns the expected card ID,
USB identity, verified playback level and Target connection. Reusable Linux
ALSA save/restore and Windows masked authentication belong in gar-tools.

The recipe saves the working card state, verifies restoring that saved state,
and arranges restoration when the selected USB audio device is detected.
It does not redeploy or restart the App. Linux authentication is required for
the protected state file and udev rule. Passwords must never be CLI arguments,
source files, logs or result JSON. Actual power-cycle and voice confirmation
remain physical verification steps.
