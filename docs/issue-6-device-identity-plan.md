# Issue #6 — device identity migration plan

## Decision

`config/site.yaml` is the sole canonical identity map for the next-generation Sproutie Brain.
It replaces `hardware/entity-map.yaml` in the same change.  Existing v1 Home Assistant YAML is
not migrated because #7/#10 retire it; no new v1 entity-ID references are allowed.

## Shape and compatibility

- The top-level site declares repository, state, status, bridge, and alert-routing context.
- A zone carries capabilities, feature flags, fallback/verification parameters, the HA device
  map keyed by role, telemetry, cameras, physical layout, and CV crop regions.
- A disabled `tent-2-sim` zone deliberately contains non-existent entities.  The verifier must
  parse it, return `online=false`, and continue evaluating other zones.
- Each actuator role has its switch, power, energy, voltage/current sensors, Kasa alias, and
  tentative power band.  The HA strip identity and entity-registry naming anomaly are retained.

## Verification and measurement procedure

1. Export `HA_URL` and `HA_ACCESS_TOKEN`, then run `python3 scripts/verify_devices.py`.
   It is read-only and exits non-zero for any unresolved required role.
2. Record all six switch states before testing.  Toggle only one relay at a time, poll its
   power sensor until the state reflects the physical relay, record watts and elapsed time,
   then restore the original state before continuing.
3. Replace every tentative `expected_watts_on` band and fallback `settle_s` from those observed
   readings.  Re-run the verifier and confirm all six original switch states are restored.
4. Pin IDs in HA’s entity registry as described in `config/README.md`, and paste the verifier
   output, watts, settle time, camera subnet finding, and restoration confirmation into #6.

## ESP32-CAM finding

The local route table sends `192.168.10.180` through gateway `192.168.1.1`, which establishes a
routed separate L3 network (likely a VLAN or routed segment), not an obvious address typo.  A
single ICMP probe on 2026-08-30 received no reply; that does not distinguish a blocked ping from
a disconnected camera.  Live HA entity-state validation is still required before treating the
camera as available.

## Live validation record — 2026-08-30

The API verifier found all six configured HA switch and power entities available. Starting and
ending switch states were the same: top light, top fan, and bottom fan `on`; bottom light,
exhaust, and camera flash `off`.

- `camera_flash` measured **10.2 W** after a stable on reading at **57.6 s**; it settled off in
  **24.2 s** and was restored off.
- The initial readings for top light, bottom light, both fans, and exhaust were invalid because
  their meter entity names were stale. A live registry audit subsequently proved a five-socket
  name rotation: the switch entities were correct, while their meter child devices were not.
  The canonical config was remapped by immutable Kasa outlet ID before the re-test.
- Corrected-map re-test: top light **29.5 W** (off/on settle **6.1/9.1 s**); bottom light
  **30.0 W** (**6.1/45.4 s**); top fan **4.2 W** (**6.1/39.4 s**); bottom fan **4.5 W**
  (**6.1/48.4 s**); exhaust **24.9 W** (**6.1/45.4 s**). Each began off and was restored off.
- The top and bottom light schedules reasserted `on` after their individual restores. A final
  explicit off command returned both to their recorded starting state. All six switches were
  then confirmed off.

The measured bands and a conservative 60-second settle window are now recorded in `site.yaml`.
The 0.5 W off threshold remains valid for the corrected meter map.

## Out of scope

No v1 automation/dashboard rewrite, schedule change, Brain implementation, or switch actuation
is included in this code change.
