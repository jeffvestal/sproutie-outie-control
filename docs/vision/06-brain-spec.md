# 06 — Sproutie Brain: engineering spec

The one new component in architecture B1. A single always-on Python service (FastAPI +
APScheduler, systemd unit on the HA box) that owns grow state, agronomy math, and every
integration contract. This spec is written for multiple Opus passes: build it top-to-bottom
per section, in order; every section ends with acceptance criteria. **No code here — contracts
and behavior.**

## 0. Design invariants (violating any of these is a bug, not a choice)

1. **Single writer.** Only the Brain mutates `state/grows.yaml` and `status/*`. Everything
   else — HA, tab, cards, FLORA, Claude — *requests* mutations through its API.
2. **Files are the database; ES is the history.** Hot state in versioned YAML (small, human-
   readable, git-recoverable). Every event/observation also appended to ES (existing index
   conventions). If the box dies, `git clone` + last telemetry gap = full recovery.
3. **Crash-safe writes.** Atomic write (temp file + rename), then git commit. On startup:
   reconcile `grows.yaml` against last ES events; disagreement → alert, prefer files.
4. **HA is a peripheral.** All HA access through one adapter (WebSocket + REST) using an
   entity map from config — no entity ID appears outside `config/site.yaml`.
5. **Degrade to dumb, never to dead.** Brain silent → HA fallback schedules keep plants
   alive (§3). Internet down → Brain runs local, queues pushes. ES down → journal spools to
   disk, replays later. Every queue has a depth alert.
6. **Idempotent everything.** Commands carry client-generated IDs; replays are no-ops.
   (today-actions reconciliation *will* deliver duplicates.)
7. **Clock discipline.** All timestamps UTC ISO8601; display timezone America/Chicago at the
   edges only. Phase day counters derive from events, never from wall-clock arithmetic in
   templates (the literal_eval class of bug dies here).

## 1. Configuration (`config/site.yaml`) — the shape of the world

Declares: site → zones (capabilities, HA entity map, telemetry sources, fallback schedule
params, photo cadence) → positions (camera, crop-region coords for CV, load-cell entity or
null, physical labels matching the tent). Adding tent #2 or a yard zone = config only (03§2).
Also: recipe directory path, git remotes/branch for the bridge, ES endpoints (via env/secrets,
never in file), Claude API key env ref, alert routing (notify script / HA notify service),
feature flags per zone (`vision`, `forecast`, `voice`).

**Acceptance:** a second zone stanza with fake entities boots cleanly and appears in
`/status` with `online: false` and zero crashes; a position without a camera simply skips
vision without warnings-spam.

## 2. State & schemas

- **`recipes/*.yaml`** — as 03§1, plus: `version` (semver, grows pin the version they started
  with), `sowing` (soak minutes, weight true/false, notes), per-phase `light` (hours *or*
  explicit on/off windows per rack), `env` bands per phase (temp, RH, VPD), `photo_cadence`,
  `expected` block (days, gdd_f, yield_g range, coverage_at_harvest). Recipes are immutable
  once referenced — tuning proposals create a new version (03§3.6).
- **`state/grows.yaml`** — array of active grows: id (`grow-YYYYMMDD-<crop>-<pos>`), position,
  recipe@version, owner, sown_at, phase, phase_entered_at, per-phase actuals, counters
  (gdd_accum, last_water, last_photo), forecast snapshot, flags (mold_risk, needs_water).
  Completed grows move to `grows/2026/<id>.yaml` (full record: events digest, curve params,
  harvest, links to timelapse/GCS) — the journal the Almanac mines.
- **`status/tent.yaml`** — the *published contract*. **This is authoritative** — the Nat app
  decodes exactly this and never invents fields. See §2.1.
- **`status/series/*.json`** — time-series companions for the Trends charts. See §2.2.

### 2.1 `status/tent.yaml` — the published contract

**Version 1.** Consumers MUST reject an unrecognised `schema_version` with a typed error, and
MUST ignore unknown keys so the Brain can add fields without breaking a shipped app. Every
timestamp is UTC ISO8601. `null` means "not measured"; an absent key means "this deployment
has no such capability" — consumers must handle both.

```yaml
schema_version: 1
generated_at: 2026-08-28T17:22:04Z
brain: {version: 0.3.0, uptime_s: 86400, queues: {spool: 0, git_pending: 0}}

zones:
  tent-1:
    label: "Tent 1 · Office"
    online: true
    # Each metric carries its own active band so the consumer never needs the recipe.
    # status is derived by the Brain: below | in | above. band may be null (unbanded metric).
    env:
      temp_f:   {value: 80.1, band: [65, 75],   status: above}
      rh:       {value: 76.7, band: [50, 70],   status: above}
      vpd_kpa:  {value: 0.80, band: [0.8, 1.2], status: below}
      co2_ppm:  {value: null, band: null,       status: null}
      outside:  {temp_f: 76.3, rh: 50.0}          # null when no outdoor sensor

    devices:                                       # keyed by ROLE, never entity id
      top_lights:    {state: on,  verified: true,  watts: 41.2}
      bottom_lights: {state: on,  verified: true,  watts: 39.8}
      top_fan:       {state: on,  verified: true,  watts: 3.1}
      bottom_fan:    {state: on,  verified: true,  watts: 3.0}
      exhaust:       {state: off, verified: true,  watts: 0.0, mode: vpd, duty_1h: 0.22}
      camera_flash:  {state: off, verified: true,  watts: 0.0}

    # Physical shape of the zone. Consumers render the grid from this, not from the grows.
    layout:
      racks:
        - {id: rack-top,    label: "Rack Top",    slots: [a1,a2,a3,a4,a5,a6,a7,a8]}
        - {id: rack-bottom, label: "Rack Bottom", slots: [b1,b2,b3,b4,b5,b6,b7,b8]}
      sidecars:
        - {id: sc-1, label: "Sidecar 1"}
        - {id: sc-2, label: "Sidecar 2"}
        - {id: sc-3, label: "Sidecar 3"}
        - {id: sc-4, label: "Sidecar 4"}

    cameras:
      - id: top-eyes
        label: "Top Eyes"
        covers: [rack-top]                         # layout ids; [] for a general view
        snapshot: status/latest/top-eyes.jpg       # repo-relative, or null if never captured
        captured_at: 2026-08-28T17:22:00Z          # null if never captured
        interval_s: 3600                           # expected cadence; staleness = now - captured_at vs 2x this
        online: true
        stream: null                               # opaque handle for live view; null = snapshots only
      - id: bottom-eyes
        label: "Bottom Eyes"
        covers: [rack-bottom]
        snapshot: status/latest/bottom-eyes.jpg
        captured_at: 2026-08-28T11:15:00Z          # stale — consumer must show it as such
        interval_s: 3600
        online: false
        stream: null

    alerts:
      - id: mold-risk-tent-1                       # stable; survives across publishes
        kind: mold_risk                            # mold_risk|water|watchdog|phase|device|forecast
        severity: warn                             # info|warn|urgent
        title: "Mold risk climbing"
        detail: "9 h above 70% RH, exhaust off, day 1 out of blackout"
        score: {value: 68, max: 100}               # null unless the alert is an index
        grow: null                                 # or a grow id
        since: 2026-08-28T08:00:00Z
        actions: [boost_exhaust]                   # opaque verbs; unknown ones are ignored
      - id: water-grow-20260820-sunf-rack-top
        kind: water
        severity: warn
        title: "Water Rack Top"
        detail: "180 g light — tray weight below the curve since 08:40"
        score: null
        grow: grow-20260820-sunf-rack-top
        since: 2026-08-28T08:40:00Z
        actions: [mark_watered]

    grows:
      - id: grow-20260820-sunf-rack-top
        crop: sunflower
        recipe: sunflower@2.1.0
        owner: null                                # or "colin" / "sloane"
        tracking: cycle                            # cycle = has a harvest ETA; milestone = perennial
        slots: [a1,a2,a3,a4,a5,a6,a7,a8]           # layout slot ids this grow occupies
        sown_at: 2026-08-20T19:30:00Z
        phase: light                               # germination|blackout|light|harvest_window
        phase_index: 2                             # 0-based position in phases[]
        phases:                                    # the recipe's plan, so the consumer can draw a timeline
          - {name: germination, days: 3}
          - {name: blackout,    days: 2}
          - {name: light,       days: 6}
          - {name: harvest_window, days: 3}
        day: 8
        expected_days: 11
        eta:                                       # null when tracking == milestone
          date: 2026-08-31
          plus_minus_d: 1
          gdd_says: 2026-08-31
          camera_says: 2026-09-01
          agreement: disagree                      # agree|disagree|single (only one forecaster available)
        gdd: {accum: 205, target: 280}             # null if not computed
        coverage: 0.71                             # 0..1, null if no vision
        weight: {g: 1840, trend: light, water_needed: true, deficit_g: 180}   # null if no load cell
        photo: status/latest/grow-20260820-sunf-rack-top.jpg                  # null if none
        last_event: {kind: phase_change, at: 2026-08-27T06:00:00Z,
                     detail: "Entered light phase (auto:days)"}

      - id: grow-20260825-radish-rack-bottom
        crop: radish
        recipe: radish@1.3.0
        owner: colin
        tracking: cycle
        slots: [b1,b2,b3,b4]
        sown_at: 2026-08-25T18:00:00Z
        phase: blackout
        phase_index: 1
        phases: [{name: germination, days: 2}, {name: blackout, days: 2},
                 {name: light, days: 3}, {name: harvest_window, days: 2}]
        day: 3
        expected_days: 7
        eta: {date: 2026-09-01, plus_minus_d: 1, gdd_says: 2026-09-01,
              camera_says: null, agreement: single}
        gdd: {accum: 61, target: 165}
        coverage: 0.24
        weight: null
        photo: null
        last_event: null

      - id: grow-20260215-peppermint-sc-1
        crop: peppermint
        recipe: peppermint@1.0.0
        owner: null
        tracking: milestone                        # perennial — no ETA, no expected_days
        slots: [sc-1]
        sown_at: 2026-02-15T12:00:00Z
        phase: established
        phase_index: null
        phases: null
        day: 195
        expected_days: null
        eta: null
        gdd: null
        coverage: null
        weight: null
        photo: status/latest/sidecar-eyes.jpg
        last_event: null
```

**Field notes that matter to implementers**

- **`layout` drives the grid, not `grows`.** Render every slot; a slot with no grow claiming it
  is empty. This is what makes a partially-planted rack (radish on `b1–b4`) render correctly.
- **`tracking: milestone`** is the perennial case — the coffee cans. `eta`, `expected_days`,
  `phases` and `phase_index` are all `null`, and the consumer shows an em dash rather than
  fabricating a date.
- **`eta.agreement`** is computed by the Brain, not the app. `single` means only one forecaster
  had data; the UI must not present that as consensus.
- **`devices` is keyed by role.** Entity ids never appear in this file (§0.4).
- **`verified: false`** means the command was sent but power draw did not confirm it. Surface it;
  do not silently treat it as on.

### 2.2 `status/series/*.json` — history for the Trends charts

`tent.yaml` is a snapshot. The Trends charts need history, and it changes at a different cadence,
so it lives in sibling files that the consumer loads lazily.

```jsonc
// status/series/tent-1-env-24h.json
{
  "schema_version": 1,
  "zone": "tent-1",
  "generated_at": "2026-08-28T17:22:04Z",
  "start": "2026-08-27T17:15:00Z",
  "interval_s": 900,                    // fixed cadence; index i is start + i*interval_s
  "bands": { "temp_f": [65,75], "rh": [50,70], "vpd_kpa": [0.8,1.2] },
  "metrics": {                          // null marks a gap; arrays are equal length
    "temp_f":  [70.9, 71.0, null, 71.4],
    "rh":      [65.1, 65.0, null, 80.2],
    "vpd_kpa": [1.02, 1.01, null, 0.81]
  },
  "events": [                           // annotations the charts draw as reference lines
    { "at": "2026-08-27T06:04:00Z", "kind": "blackout_removed", "label": "blackout off" }
  ]
}
```

```jsonc
// status/series/grow-20260820-sunf-rack-top.json
{
  "schema_version": 1,
  "grow": "grow-20260820-sunf-rack-top",
  "generated_at": "2026-08-28T17:22:04Z",
  "days": [0,1,2,3,4,5,6,7,8],          // day index; all daily arrays align to this
  "coverage":   [0.00,0.01,0.04,0.11,0.26,0.44,0.58,0.66,0.71],
  "gdd_cum":    [0,24,49,76,101,128,154,180,205],
  "gdd_target": 280,
  "projection": {                        // fitted forward curve; null until enough points exist
    "through_day": 11,
    "days":     [9,10,11],
    "coverage": [0.80,0.87,0.92],
    "gdd_cum":  [232,258,280]
  },
  "weight": {                            // higher cadence than daily — carries its own stamps
    "at":         ["2026-08-26T07:00:00Z","2026-08-27T07:00:00Z","2026-08-28T07:00:00Z"],
    "g":          [2010,1920,1840],
    "expected_g": [2020,1960,1900]
  },
  "water_events": [ { "at": "2026-08-26T07:12:00Z", "ml": 400, "by": "colin" } ]
}
```

Rules: arrays within a group are **equal length and index-aligned**; `null` is a gap, never zero;
a consumer that finds a length mismatch treats the series as unavailable rather than guessing.
Series files are optional — a missing file means "no history yet", and the chart shows an empty
state rather than an error.

**Acceptance:** the fixture in nat#235 decodes every construct above, including a milestone grow,
a partially-occupied rack, an offline camera, an alert with a score, and a series file with a gap.

## 3. Control philosophy — two brains, one deadman switch

- **HA keeps** (always loaded, never depends on Brain): safety rules (thermal guard, flash
  valve), a *static fallback* light schedule + exhaust duty cycle per zone, watchdog alerts.
- **Brain drives** the smart layer via HA services: per-rack, per-phase light windows;
  exhaust by VPD band (with humidity/temp/duty modes preserved as selectable strategies);
  photo sequences; germination handling (lights held off).
- **Deadman:** Brain heartbeats an HA entity every 60 s. HA automation: heartbeat stale
  > 30 min → flip zone to fallback schedules + notify. Brain returning flips it back. **This
  is the keystone of "keeps working"** — smart when possible, dumb when not, alive always.
- **Actuation = command + verify:** every switch command re-checks state and power draw
  (per-outlet sensors) within 60 s; mismatch → one retry → alert + mark `verified: false` in
  status (the tab shows it honestly).

**Acceptance:** kill the Brain process for 35 min → lights follow fallback + phone alert;
restart → smart schedule resumes, an `ops` event logs the gap.

## 4. Engine behaviors (each is a scheduler job; all pure functions over state + telemetry, unit-testable)

- **Phase engine:** transition when `elapsed_days >= phase.days` *or* `gdd >= phase.gdd`
  (whichever recipe declares), or manual command. Guards: min-days, blackout-before-light
  ordering, harvest only from harvest-window. Side effects on transition: light profile swap,
  env bands swap, event → ES + journal, card ping. Everything logged with cause
  (`auto:days | auto:gdd | manual:jeff | manual:flora`).
- **GDD accumulator** (hourly): from zone temp; weather-fed for outdoor zones (Open-Meteo).
- **VPD** (minutely): temp+RH → kPa, drives exhaust when mode=vpd; inside/outside differential
  logic when the second sensor exists ("exhaust only if outside air helps").
- **Water inference:** load cell sawtooth when present; else recipe cadence + last water
  event → `water_needed` flag (card, not actuation — until 08§4 autopilot).
- **Mold-risk index** (hourly): RH-hours>70% × phase weight × fan-duty deficit → 0–100;
  >60 → boost exhaust + card; >80 → urgent card + force photo + flag for vision check.
- **Photo sequencer:** per-zone cadence; the existing scene-save/flash/snapshot/GCS chain,
  owned end-to-end, with per-grow naming + `_latest` refresh; nightly retention job.
- **Vision** (daily, post-photo): coverage % per grow (HSV mask over configured crop region);
  logistic fit refresh; write observation. Weekly: Claude API packet (photos + telemetry
  summary) → structured findings (legginess/yellowing/mold/uneven) + prose note → journal.
- **Forecaster** (daily): ETA ensemble = GDD projection ∩ coverage-curve plateau; publish
  both + disagreement; solver endpoint inverts it (target date → sow date).
- **Escalation/dedup:** alerts carry stable keys, cool-downs, and auto-resolve events —
  no re-ping storms (mirror nat queue discipline).

**Acceptance:** tent-sim scenario suite (§7) passes: normal grow, cold week (GDD slip moves
ETA), stuck-exhaust (mold index fires), dead-sensor (watchdog + no false transitions),
duplicate-command replay (idempotent).

## 5. API surface

- **REST (LAN + Tailscale):** `GET /status` (=tent.yaml), `GET /grows/{id}` (full detail +
  journal digest), `POST /grows` (plant: crop, position, density, soak, owner, client_id),
  `POST /grows/{id}/events` (water/note/issue/photo-request), `POST /grows/{id}/phase`
  (target, cause), `POST /grows/{id}/harvest` (weight, quality, note), `GET /forecast`,
  `GET /solve?crop&ready_by`, `GET /recipes`, `POST /zones/{z}/devices/{d}` (state, ttl —
  auto-revert overrides), `GET /healthz`. Auth: bearer per client (tab, flora, ops), read vs
  control scopes.
- **MCP server (same process):** tools mirroring the REST verbs 1:1 —
  `get_tent_status, get_grow, list_recipes, plant_batch, log_event, advance_phase,
  harvest_batch, set_device, get_forecast, solve_sow_date, request_photo`. Replaces the stub
  in `mcp_server/`; FLORA's workflow tools repoint here; Nat/Claude sessions connect via
  Tailscale. Control tools require the control scope; FLORA's config keeps her ask-first rule.
- **today-actions reconciler** (5-min poll of the git bridge): maps card actions →
  the same internal commands (client_id = action id → idempotent).

**Acceptance:** the FLORA workflow that today hits stub data returns live truth; a control
call without scope is refused politely; the same water action delivered twice logs once.

## 6. Bridges

- **Git bridge (out):** on change + hourly heartbeat: write `status/tent.yaml` + thumbnails,
  commit `sproutie: status <ts> (auto)`, push with rebase-retry ×4 (backoff). Never force.
  Separate `status/` path from human-edited files to avoid conflicts. **(In):** pull before
  reconcile pass; consume `status/today-actions.yaml` appends.
- **ES bridge:** existing indices (`sproutie-sensors-*`, events, crops) via bulk with disk
  spool + replay; revive botany-log index (vector field) as the destination for FLORA/
  Fischoeder/Claude notes — semantic search over your own grow history is the Almanac's
  substrate (08§2).
- **HA adapter:** one WebSocket subscription (state_changed filtered by entity map) + service
  calls; reconnect with jittered backoff; connection state is itself a published metric.

## 7. Testing & ops

- **tent-sim:** fake HA WebSocket + accelerated clock + scenario YAMLs (sensor traces incl.
  recorded real days from ES export + synthetic disasters). Runs in GitHub Actions on every
  PR touching brain/, recipes/, or config/. Golden-grow replay asserts phase timeline, alerts,
  and final journal record byte-for-byte (modulo timestamps).
- **Recipe CI:** schema validation + sim-run of a full grow per changed recipe ("the tests
  must pass before you may water").
- **Ops:** systemd with restart=always + watchdog; `/healthz` scraped by HA (that's the
  heartbeat entity); structured logs; version in every status push; `make deploy-brain`
  (rsync + restart + healthz gate) alongside Phase 0's config deploy.

## 8. Migration & cutover (expands roadmap Phase 1)

1. Brain runs **read-only** for a week: mirrors slots from HA helpers → files, publishes
   status, pushes to git. Tab/cards can already build on it. Diff report daily.
2. Cut writes over: desktop scripts → `rest_command` → Brain; helpers become display-only.
3. One full grow cycle in parallel (helpers still updated by Brain for the old dashboard).
4. Delete the 20 helpers + crop JSON + 37 template copies; generated v3 dashboard reads
   Brain. Tag `v2.0.0`. Frame the tag message with the SOC 2 joke; it has earned it.

**Sizing honestly:** ~6 modules, each an evening for an Opus session; the schemas above are
the hard thinking, and they're done. Multi-pass order: §1–2 (state, config, status file) →
§5 REST read-only + §6 git-out → §3–4 core loops → §5 write path + reconciler → §6 ES +
vision/forecast → §7 hardening.
