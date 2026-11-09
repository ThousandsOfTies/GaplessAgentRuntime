# Product-declared Target probes

`gar product run probe --workspace Local/Product --json -- --probe status` runs
a [Product operation](PRODUCT_OPERATIONS.md) declared in `gar-operations.json`:

```json
{"schema_version":1,"operations":{"probe":{"entrypoint":"tools/target-probe.py","timeout_seconds":90,"result_fields":["ok","probe","verification","observations","error"]}},"aliases":{"target probe":"probe"}}
```

The entrypoint must be inside the local workspace. It receives `--probe status`,
runs with no local shell, and must return one JSON object within 90 seconds.
The Product entrypoint validates its supported probe names; GAR rejects escaping paths.
Do not emit credentials, microphone recordings or private conversation content.

Use this for targeted observations of legacy installations which do not expose
the lifecycle contract, without installing a service or deploying an application.
Probes are not sandboxed: their effects must be documented by the Product.
Use explicit names for tests that play audio or adjust a mixer, and keep the
default `status` probe read-only. Binding, connection identity and service names
belong in the Product; reusable OS/device probes belong in gar-tools.

The Product marks results `verification: probe_only`. Success does not imply a deployed
artifact checksum/build-ID match, audible sound or successful speech recognition.
