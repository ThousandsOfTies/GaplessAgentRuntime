---
name: embedded-development
description: Develop GAR-backed embedded products when building, simulating, deploying, or diagnosing an App and its target.
---

# GAR embedded development

Use GAR's CLI for Product build, simulation, deployment, and diagnosis. Work
inside the selected Product workspace; do not replace GAR lifecycle operations
with ad-hoc remote copies, service edits, or board commands.

## Choose the boundary

- **App/Product:** application behavior, protocol, UI, product requirements,
  wiring assignments, and scenarios.
- **GAR:** artifact lifecycle, environment composition, diagnostics, and
  reusable command behavior.
- **gar-tools/board target:** board capability, OS/toolchain, provisioning, and
  generic device support. Do not add Product names or application semantics to
  a target pack.

Check the selected workspace and its target/environment before changing a
recipe or deploying. Replace `Local/Product` below with a registered workspace.
Use `gar <command> --help` and `--capabilities` to discover a configured route;
if GAR lacks a reusable route, implement it there instead of bypassing it.
Treat a physical board, its serial port, boot mode, and artifact as distinct
facts; do not infer one from another.

## Simulation purpose and execution path

GAR simulation validates software intended for the physical target by running
as much of its real execution path as possible against virtual devices. UI,
feature and navigation checks alone do not satisfy this purpose. WebPanel is
an input and observation window for those devices.

Start from the target's execution path before designing a simulator. Retain
application, protocol, transport-control and peripheral-control code wherever
possible; substitute only the hardware-dependent boundary, as low as practical.
Prefer existing OS/SDK mechanisms: Linux gpio-sim, FUSE/CUSE where suitable,
or SDK/driver APIs such as ESP-IDF and NimBLE on ESP32. Reuse existing host-test
facilities before building a substitute; do not reimplement an entire SDK.
Keep environment selection in target/provider composition rather than Product
behavior branches.

Map the physical and simulated paths and identify the exact substitution
boundary. Feeding messages directly into the application after a real
transport's control logic is a bypass, not validation of that transport.
If unavoidable, document it and test the bypassed control code separately
through mocked SDK/driver APIs where feasible. Simulate prerequisites and
failure events as well as success: for example, BLE payload delivery must not
succeed before the required security and subscription conditions are met.

Before calling a simulator complete, exercise the retained control path and
show evidence of the resulting device/application behavior. For changed
connection code, cover initial connection, disconnect/reconnect and endpoint
restart as applicable. Keep physical interoperability tests for what the
substitute cannot establish. When hardware is unavailable, leave those checks
explicitly unverified rather than implying that simulation covered them.

## Required simulation checks

Before editing simulator behavior, record the physical and simulated paths as
`input -> application -> transport -> external endpoint -> response`. Name the
shared implementation and exact substituted driver/SDK boundary at each step.
Check existing read-only restrictions, demo peers and adapters against the user's
purpose; existing code is subject to correction, not authority to narrow it.
Do not replace production inputs/endpoints or remove the return path merely
because doing so seems safer or easier. Apply the actual authorization boundary
to the common path instead. Keep explicitly requested test modes distinguishable.

Define completion against that path before implementing. For a networked or
interactive Product intended to exercise production integration, require evidence
that the real input reaches the common application and a human's response reaches
the original endpoint once, retaining identities and cancellation semantics.
Isolated fixtures can test the same contract, but synthetic input, a local ACK,
or a successful UI demonstration alone does not prove this integration. Verify
unchanged/substituted/bypassed steps against the initial map before reporting
completion; identify missing external verification as incomplete, not passed.

## Standard workflows

For a simulated Product, use the existing lifecycle and retain evidence beyond
a visual panel check:

```bash
gar sim build --workspace Local/Product
gar sim deploy --workspace Local/Product
gar sim start --workspace Local/Product
gar sim diag --workspace Local/Product --json
```

For a physical target, build explicitly, validate compatibility before writing,
then diagnose the deployed result:

```bash
gar target prepare --workspace Local/Product
gar target build --workspace Local/Product
gar target preflight --workspace Local/Product --json
gar target deploy --workspace Local/Product
gar target diag --workspace Local/Product --json
```

Use `gar hw validate --workspace Local/Product --json` for offline agreement
between Product requirements, target capabilities, and bindings. `prepare` is
for initial setup or recipe changes; `deploy` does not implicitly build.

## Report validation honestly

Report which code ran unchanged, which OS/SDK/device boundary was substituted,
and which paths were bypassed or remain untested. A shared application alone
does not establish shared transport or driver execution.

Record which layer supplied the evidence: build/artifact checks, simulation
diagnostics and scenario or metrics evidence, and physical-board behavior.
Simulation confirms the implemented simulated scope; it does not establish
electrical, timing, wireless, boot-mode, or wiring behavior on hardware.
Before physical deploy/flash/restart, verify the requested board and operation
are within existing authorization; ask only when they are missing or ambiguous.
Preserve the distinction between an artifact being placed and a running
application whose expected build ID and health were diagnosed.
