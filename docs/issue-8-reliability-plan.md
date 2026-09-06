# Issue #8 — watchdog and command-verification implementation plan

## Scope and safety boundary

This change implements only the Home Assistant watchdog and command-verification configuration
required by #8. It does not deploy or reload Home Assistant, call a live service, toggle a switch,
rename an entity, enable a thermal/fault helper, unplug a device, or run an induced-failure test.
Those proof steps remain explicitly deferred until the tent is confirmed empty and Jeff approves
the exact live test. Any later live test must capture every relevant device/helper state first and
restore and record it afterward.

The two v1 plumbing monitors (Elasticsearch push staleness and GCS upload failures) remain retired
with the #7 clean R1 cutover. This issue adds device-layer monitoring only and does not revive either
external workflow.

## Configuration decisions

1. `config/site.yaml` remains the sole source of device identities, expected power bands, photo
   cadence, latest-snapshot paths, verification timing, watchdog thresholds, cooldown, heartbeat
   time, and Jeff's phone notifier. Generated Home Assistant YAML may contain those values;
   handwritten duplicate maps may not.
2. A generated `ha/packages/r1_reliability.yaml` owns watchdog problem entities, alert cooldown and
   active-state helpers, per-role verified helpers, read-only latest-snapshot mtime sensors,
   alert/recovery routing, and the daily heartbeat. `ha/configuration.yaml` loads the package
   directory. The thermal safety script is generated from the same site contract.
3. Faults have stable keys and one persistent-notification ID/mobile tag per condition. Separate
   active-lifecycle and UI-visibility helpers avoid relying on persistent-notification entities,
   which no longer exist in current Home Assistant. A removal trigger marks a dismissed UI alert
   invisible without clearing the active lifecycle, so the periodic reconciler may re-emit it only
   after cooldown while recovery still replaces the phone notification with a resolved message.
   Visibility helpers initialize off after Core restart because HA notifications are in-memory;
   active lifecycle helpers retain restore behavior.
4. Switch watchdogs treat every state other than `on`/`off` as an integration/entity-ID fault after
   five minutes. Power watchdogs treat unavailable, `N/A`, empty, and other non-numeric states as a
   telemetry fault after ten minutes. Govee temperature and RH use the same invalid-value handling
   after fifteen minutes, and each also gets an exact reported-state frozen-value watchdog after two
   hours. Camera staleness is based on each configured `_latest.jpg` file's actual modification
   timestamp and alerts at twice the configured photo cadence; camera entity `last_updated` is not a
   reliable snapshot-age signal.
5. Every generated role command marks the role unverified, sends the command, waits the measured
   60-second HS300 settle period, and checks both relay state and power. A mismatch gets exactly one
   retry and one more settle period. Success marks the role verified and resolves its stable command
   alert. Final failure remains unverified and classifies the notification as entity/integration,
   relay-state, power-telemetry, or physical-draw failure. Expected on ranges and the off threshold
   come from `site.yaml`.
6. Existing R1 automations and thermal safety continue to call the generated role scripts. A
   transition-gated, non-blocking, `mode: single` thermal owner sends immediate fail-safe commands
   for both lights and exhaust, then passes `initial_command_sent: true` to the role scripts so
   those commands are treated as attempt one, verified after the settle window, and retried at most
   once. Unsafe retriggers cannot restart the owner or add commands. Recovery cancels the owner and
   all three role verifiers before releasing the latch, preventing a delayed retry after hysteresis
   recovery. No auto-remediation beyond the single command retry is introduced.
7. The daily phone heartbeat reports `Tent nominal, 6/6 devices verified` only when every role is
   verified and no watchdog problem entity is active; otherwise it reports both counts explicitly.

## Non-actuating verification

- Unit tests will assert that every enabled device, climate sensor, and camera has the required
  generated watchdog/verification objects and that all thresholds and routes originate in
  `site.yaml`.
- Tests will assert the two-attempt sequence, measured settle delay, state-plus-power predicates,
  persisted verified markers, stable keys, cooldowns, recovery path, failure classification, and
  heartbeat semantics.
- All generated and handwritten R1 YAML will be parsed locally, generator drift will be checked,
  the repository unit suite will run, and the local secret scan will run.
- No acceptance checkbox requiring induced device behavior or phone delivery will be claimed from
  these checks. Live evidence and the restoration inventory will be added to #8 only after a
  separately approved test session.

## Local implementation evidence — 2026-09-02

- Per Jeff's direction, the unavailable Gemini route was not waited on or rerun. A fresh
  `gpt-5.6-sol` reviewer inspected only the bounded issue #8 working-tree diff. It identified alert
  lifecycle and thermal interleaving/recovery issues; those were corrected and its final current-
  tree pass reported no remaining findings.
- Focused reliability/config tests pass: 26/26. Full repository discovery passes: 33/33. The full
  suite was run locally with only its loopback mock HTTP fixture allowed to bind; it did not contact
  Home Assistant or the tent.
- Generated-output drift tests, YAML/Jinja parsing, Python compilation, `git diff --check`, and the
  local credential scan (18 scoped source/config files) pass.
- No Home Assistant deployment, reload, configuration activation, service call, helper toggle,
  switch actuation, induced fault, entity rename, commit, or push was performed.
- Still requires separately approved live validation: HA Core 2026.8 config/schema check; command-
  line `stat` behavior in the HA container; actual `_latest.jpg` update paths; phone delivery/tag
  replacement; watchdog timing; induced command/thermal failure behavior; and complete before/after
  state capture and restoration.
