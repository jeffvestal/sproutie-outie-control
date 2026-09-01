# Issue #7 — clean Home Assistant rebuild plan

Status: approved in conversation for a staged in-place Core upgrade. A clean rebuild remains the
fallback only if that upgrade cannot be validated.

## Decision

Upgrade the existing HAOS installation in place before considering a rebuild. Preserve installed
integrations, dashboards, and config while moving Home Assistant Core in two bounded stages:
`2026.1.1` → `2026.7.4` → `2026.8.3`. Do not update HAOS, Supervisor, or add-ons in this change.

Reason: the full off-device recovery backup now exists; the Kasa switch identities are verified;
and the active schedules are working. An in-place Core update preserves integrations and gives a
smaller, reversible failure boundary. A later clean rebuild can use the same archive and backup if
the staged upgrade cannot pass validation.

The archived server reports Core `2026.1.1`. The UI currently offers `2026.8.3`; `2026.7.4` is
the intermediate target so the first update spans no more than six monthly releases. Record the
installed version after each stage.

## Execution record — 2026-08-30

Completed Core-only upgrade: `2026.1.1` → `2026.7.4` → `2026.8.3`. Supervisor, HAOS, firmware,
add-ons, integrations, configuration, and dashboard files were not updated or changed.

- The pre-upgrade full recovery backup was checksum-verified from the server copy to owner-only
  storage outside the repository.
- After each Core stage, HA returned to `RUNNING`; the existing Grow Lights ON/OFF automations
  loaded enabled.
- `scripts/verify_devices.py` passed at `2026.7.4` and `2026.8.3`: all six required Kasa switches
  and mapped power meters are available. At final validation, all six outputs were off and read
  0 W; no verification call actuated a device.
- The tent Govee temperature/humidity sensor and all three camera entities were available after
  the final update.

## Cutover operating protocol

Jeff is manually managing the final sunflower tray with the Kasa app. No waiting-for-morning step
or mechanical-timer prerequisite applies to this cutover. This exception changes no technical
safety checks:

- The agent does not actuate the live loads during the rebuild except for explicit post-pairing
  verification, and records each observed result.
- Before ending any session after devices are paired, verify light, circulation, and exhaust
  actuation and restore the pre-test switch states.
- If a physical install or re-pair stalls, leave the tray under Jeff's Kasa control; do not leave
  partially enabled HA automations acting on it.

## Prerequisites already complete

- #4 forensic archive: `attic/ha-config-2026-08/`, with credentials/auth stores excluded and
  helper values captured separately.
- A fresh full HA recovery backup was created on 2026-08-30, copied outside the repository into
  owner-only local storage, and checksum-verified against the server copy. It is retained only
  for an explicit recovery decision.
- #6 canonical device map: `config/site.yaml` and `scripts/verify_devices.py` with physical
  switch identity and real-meter verification.
- Corrected premise: the schedules are presently active; the stale part was meter labeling, not
  evidence that the configured light schedule had stopped.

## Safety and command-priority contract

Thermal safety is a latch, not a competing schedule. A valid temperature above 90°F, an unavailable
temperature sensor, or a sensor older than 15 minutes activates the thermal latch: both grow
lights remain off, exhaust remains on, and an alert is raised. Normal light and exhaust routines
call a single reconciliation action and are prohibited from issuing an opposing command while the
latch is active.

The latch clears only after a valid temperature below 85°F. On HA startup, before any schedule is
allowed to reconcile, the same test runs. A startup reading at or above 85°F, or an unknown/stale
reading, begins in the safe latched state. This conservative restart behavior prevents a 90°F
event from becoming unsafe during an HA reboot.

## Implementation sequence

1. **Create an explicit recovery point.** Before touching HA Core, create and verify a current full
   HA backup/export, including an explicit decision to retain or omit `/media` snapshots. Store it
   outside the new config and use it only for an explicit recovery decision; do not auto-restore
   it. The scrubbed #4 archive remains forensic evidence, not this recovery point.
2. **Upgrade Core to `2026.7.4`.** Do not update any other component. Wait for a healthy restart,
   then inspect configuration errors, integrations, logs, the existing schedules, and read-only
   #6 device verification before continuing.
3. **Upgrade Core to `2026.8.3`.** Repeat the same health and device checks. Stop at either stage
   if an integration fails, the config has errors, or a required device is unavailable; restore the
   recovery backup only after an explicit recovery decision.
4. **Validate the preserved installation.**
   - `scripts/verify_devices.py` passes with real watts.
   - Existing light schedule and exhaust automation remain enabled and show valid recent triggers.
   - Confirm the six Kasa switches and mapped power meters remain available without actuating them.
   - Record config errors, failed integrations, and any dashboard/custom-card regression.
5. **Decide the next branch.** If both upgrades validate, keep the upgraded install and plan any
   future R1 simplification as a separate, non-destructive issue. If validation fails, stop and
   decide explicitly between restoring the verified backup and the previously planned clean rebuild.
6. **Record and review.** Capture exact version, integration results, verifier result, config/log
   evidence, and observed device behavior. Obtain independent review and Jeff's live validation
   before any commit or issue closure.

## Boundaries requiring Jeff at execution time

- The Core upgrade is issued through the HA update service; no UI version picker is required.
- The final live validation requires Jeff's confirmation before any commit, per `AGENT.md`.

## Independent review

An independent review of this plan on 2026-08-30 identified missing thermal-command priority,
startup reconciliation, staged deployment, dashboard-dependency, and recovery-backup controls.
Those controls are incorporated above. The current #6 verifier was also rechecked: disabled zones
are reported but do not affect required-zone success, and no permissive offline-success option
remains.

## Rollback

If either Core stage cannot validate, retain the archive as a forensic reference and keep hardware
under manual Kasa control. Do not restore automatically. The verified backup supports an explicit
rollback decision; the clean rebuild remains the next option if rollback is not desirable.
