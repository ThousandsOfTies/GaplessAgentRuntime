# Existing Product simulators

`product_hook` integrates a Product's existing simulator lifecycle without adding
Product-specific service names or protocols to GAR. Select this simulator with a
local workspace and declare `gar-simulator.json`:

```json
{"schema_version":1,"entrypoint":"tools/gar-simulator.py"}
```

The entry point must be a Python file within the workspace. GAR invokes it with
one argument (`build`, `deploy`, `start`, `stop`, `diag`, `status` or `log`) using
an argument array, never a shell. The Product owns target-specific wiring and its
simulator adapter. A managed VirtualBox setup can retain its existing parts.

`build` writes the normal `artifacts/from-codespace/artifact.json` and payload.
GAR captures it as a checksum snapshot. `deploy` receives `GAR_SIM_BUNDLE` and
`GAR_SIM_BUILD_ID` only after GAR has verified the snapshot. Deployment must not
build or implicitly start the simulator. `start` starts the deployed artifact.

`diag` returns one JSON object with `ok`, `runningBuildId`, `deployedBuildId` and
the Product's service, protocol or device evidence. GAR independently compares
the running ID to its latest captured snapshot. The hook must verify the actual
running application and installed payload, not just echo a stored build ID.
GAR's host observation is not applicable for this externally managed lifecycle;
host evidence belongs in the diagnostic payload. Simulation diagnostics do not
establish physical-board behavior.
