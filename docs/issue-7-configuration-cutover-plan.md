# 2026-08-31 R1 configuration cutover

Jeff authorized a same-day clean configuration cutover after harvesting the final tray. Home
Assistant OS, Supervisor, Core `2026.8.3`, and existing integration pairings remain in place. The
cutover replaces only the v1 HA configuration and dashboards; it does not reimage the host.

## Safety boundary

- The verified full recovery backup remains outside the repository.
- Kasa schedules are disabled and the tent is empty. No agent action turns on a light or fan during
  the cutover without a specific validation step and recorded restoration state.
- The target configuration is staged and validated before it replaces `/config`. The prior config
  remains rollback material until the new config validates.
- The initial target is deliberately **disarmed** (a fresh `input_boolean.r1_safety_armed` defaults
  off). While disarmed, the thermal and watchdog automations report their condition but never
  actuate a load. This prevents a just-restarted Govee entity from treating its brief `unknown`
  state as a command to run the exhaust. The operator arms safety only after a fresh temperature
  reading and the recorded functional test pass; the resulting armed state is restored on later
  Core restarts.
- `.storage` is retained for integration pairings and is never edited directly. Before activation,
  the deploy inventory records every pairing dependency outside `.storage` (custom components,
  YAML platform blocks, snapshot/media paths, and add-ons). Required dependencies are retained or
  explicitly replaced; a config entry alone is never assumed to be sufficient.

## Target configuration

The deployable source lives in `ha/`; it contains only:

- Kasa/Govee and retained local snapshot-camera references. R1 does not load the obsolete Eufy
  YAML platform; its archive/custom component remains recovery material until a later, explicit
  Eufy reauthentication design.
- Explicit restart-deterministic helpers for fallback schedules and thermal safety.
- A thermal priority latch: unsafe, unavailable, or stale temperature keeps lights off and exhaust
  on once R1 safety is armed; normal schedules cannot override it; recovery requires a valid
  reading below 85°F. Every schedule and duty-cycle action checks the latch before commanding a
  device.
- Disabled-by-default light and exhaust fallback schedules, matching the empty-tent state.
- Device/power/sensor/camera watchdogs and command-verification scripts using `config/site.yaml`
  ranges.
- One native-card wall-panel dashboard, no HACS/Browser Mod dependency.
- Snapshot automation only after camera authentication is confirmed.

It intentionally excludes grow slots, crop data, Elasticsearch/GCP workflow logic, v1 scripts,
template crop arithmetic, `input_text` helpers, old dashboards, and custom-card resources.

## Deployment and validation

1. `scripts/deploy.sh --dry-run` compares the manifest with the target and reports drift. The
   command receives `HA_URL` and `HA_ACCESS_TOKEN` only from the operator environment; neither is
   copied into the stage or repository.
2. The script stages `ha/` beside `/config`, applies the recorded compatibility-dependency
   inventory, and validates the staged tree with Home Assistant Core **before** activation.
3. A successful preflight makes a timestamped rollback copy, then applies the stage in place to
   the existing `/config` mount and restarts Core. This is a deliberate reversible in-place
   activation: HA's container bind mount prevents a directory-rename swap from being a real
   atomic cutover. The script records the rollback path, then calls the REST config check and
   `scripts/verify_devices.py`.
4. Post-activation checks are functional checks, not preflight validation. If one fails, stop in
   the disarmed installation state, preserve the captured switch state, and use the documented
   one-command explicit rollback to the captured prior config (or the verified full backup). Do
   not claim that the previous config is still active.
5. Before declaring the cutover successful or retiring v1, record this functional gate: capture
   every switch state; exercise a simulated over-temperature; prove lights off, exhaust on, and
   phone alert; keep the simulated unsafe condition through a normal schedule/duty tick; prove
   latch recovery only below 85°F; exercise a stale/unavailable reading and alert; then restore
   the captured states. The operator explicitly turns `r1_safety_armed` on only after this gate.

The SSH add-on must have Protection mode disabled and restarted for the staging validator to access
the Core container; the agent does not change that add-on setting.

## Credential and notification boundary

- Eufy reauthentication is deferred: R1 retains the verified local snapshot cameras but does not
  load the obsolete Eufy YAML platform. No Eufy value is copied to the repository or archive.
  GCP and Elastic credentials are revoked/rotated through their provider consoles, but no
  replacement GCP or Elastic value is stored in R1: R1 intentionally has no GCP/Elastic workflow
  to consume one.
- Watchdog alert delivery uses the phone-notification target Jeff identifies and must be confirmed
  on-device before #8 is complete.

## Retiring v1

Only after the replacement config loads and the functional safety/alert gate passes, move v1
packages, dashboards, Lovelace views, icons, debug patchers, SFTP deployment file, and MCP stub to
`attic/v1/`. Do not preserve the old plaintext-credential `configuration.yaml`; the scrubbed
forensic archive is the reference. Update `AGENT.md`, `README.md`, and `.gitignore` to describe
the R1 system.
