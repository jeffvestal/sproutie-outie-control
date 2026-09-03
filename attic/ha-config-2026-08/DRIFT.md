# Home Assistant archival snapshot and drift record

Captured on 2026-08-30 from the running Home Assistant configuration. This is a read-only
forensic reference for the clean rebuild; it is not a configuration to restore wholesale.

## Capture boundaries

- The archive contains 2,916 published files (including this record and the helper-state snapshot).
- Direct HA auth stores, secret files, private keys, recorder databases, and Google credential
  stores are excluded. Credential-like values in JSON, text, and URL credentials are redacted.
- `input-helper-states.json` records the state values of 89 `input_*` helpers only; it includes no
  HA API metadata or access token.
- The raw staging copy is protected outside the repository and must be deleted after the rebuild
  rollback point has passed.

## Corrected device-identity record

The six Kasa switch entity IDs and their friendly names were manually confirmed against the physical
devices using the Kasa app. They are the source of truth for actuation.

The old claim that role-named Kasa power-meter entities also proved physical identity was false.
Five meter labels were stale and rotated relative to the Kasa outlet identities. Issue #6 corrected
the canonical role-to-meter map by outlet identity; do not infer physical hardware from a
`sensor.<role>` name alone.

## Runtime findings

The light schedule is currently functioning, not stopped:

- Production mode and the light schedule toggle are both enabled.
- The configured times are 18:00 on and 12:00 off (local time).
- Both live light automations are enabled and were last triggered at those times on the capture day.

No active automation or script uses the obsolete `switch.aux_light` entity. The only surviving
reference is in `packages/sproutie_outie/scripts.yaml.bak`, an inactive backup file. The config also
contains Apple `._*` metadata files and legacy/disabled material that should not be carried into a
minimal rebuild.

Historical logs contain unrelated external-integration failures, but this snapshot has no evidence
of a current light-schedule configuration failure. The prior Issue #4 wording should therefore be
read as a configuration/identity cleanup task, not proof that the schedules are currently broken.

### Supporting evidence

- `input-helper-states.json` records `input_boolean.production_mode: on` and
  `input_boolean.schedule_lights_enabled: on`; it also records `lights_on_time: 18:00:00` and
  `lights_off_time: 12:00:00`.
- `.storage/core.restore_state` is the captured UI/runtime state source. It records
  `automation.grow_lights_on` and `automation.grow_lights_off` as `on`, with last triggers at
  `2026-08-30T23:00:00.484760+00:00` and `2026-08-30T17:00:00.319383+00:00`, respectively
  (18:00 and 12:00 local CDT). The corresponding definitions and helper conditions are in
  `packages/sproutie_outie/automations.yaml`; UI enablement is not represented by that YAML alone.
- The captured rotated logs contain no schedule/automation error. They do contain unrelated,
  historical integration failures: Eufy setup raised `KeyError: 'access_token'`, the August
  authenticator reported `Token has expired.`, and Tuya reported `Authentication failed. Please
  re-authenticate`. Those entries are from 2025-07-22 and 2026-01-03, not the capture day, and
  do not identify the scheduler as failing.

Conclusion: the archive disproves a current light-automation outage and does not establish a
root cause for the earlier report that automation had stopped. In particular, entity-ID drift,
disabled light automations, disabled production/schedule helpers, unset light times, and a
capture-day scheduler error are ruled out by the retained evidence. No more specific historical
cause can be asserted from these logs.

## Rebuild use

Use this archive only to recover intent, names, and manual-state values. For the clean install:

1. Do not restore `.storage`, dashboards, HACS/custom integrations, packages, or legacy backups.
2. Re-pair devices and validate each physical switch before enabling any automation.
3. Use the canonical map in `config/site.yaml` plus `scripts/verify_devices.py` as the new hardware
   gate.
4. Recreate only the approved minimum: emergency thermal protection, simple light/exhaust fallback
   schedules, and a small control/status dashboard.
