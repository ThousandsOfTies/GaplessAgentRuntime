# Product-declared Target probes

`gar target probe --workspace Local/Product --probe status --json` runs a
bounded Python hook declared in the Product's `gar-target-probe.json`:

```json
{"schema_version":1,"entrypoint":"tools/target-probe.py","probes":["status","speaker-test"]}
```

The entrypoint must be inside the local workspace. It receives exactly the
declared probe name as one argument, runs with no local shell, and must return
one JSON object within 90 seconds. Unknown names and escaping paths are rejected.
Do not emit credentials, microphone recordings or private conversation content.

Use this for targeted observations of legacy installations which do not expose
the lifecycle contract, without installing a service or deploying an application.
Probes are not sandboxed: their effects must be documented by the Product.
Use explicit names for tests that play audio or adjust a mixer, and keep the
default `status` probe read-only. Binding, connection identity and service names
belong in the Product; reusable OS/device probes belong in gar-tools.

Results are marked `verification: probe_only`. Success does not imply a deployed
artifact checksum/build-ID match, audible sound or successful speech recognition.
