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
- **`status/tent.yaml`** — the *published contract* (tab + cards consume this; schema_version
  gated):

```yaml
schema_version: 1
generated_at: 2026-07-07T21:40:00Z
brain: {version: 0.3.0, uptime_s: 86400, queues: {es_spool: 0, git_pending: 0}}
zones:
  tent-1:
    online: true
    env: {temp_f: 71.2, rh: 58, vpd_kpa: 0.95, co2_ppm: null, outside_rh: 44}
    devices:
      top_lights: {state: on, verified: true, watts: 41.2}
      exhaust: {state: off, mode: vpd, duty_1h: 0.22}
    alerts: [{kind: water, severity: warn, grow: grow-20260701-sunf-a1, msg: "−180 g vs curve", since: …}]
    grows:
      - {id: grow-20260701-sunf-a1, position: rack-top/a1, crop: sunflower, owner: null,
         recipe: sunflower@2.1.0, phase: light, day: 8, expected_days: 11,
         eta: {date: 2026-07-12, plus_minus_d: 1, gdd_says: 2026-07-12, camera_says: 2026-07-13},
         gdd: {accum: 205, target: 280}, coverage: 0.71,
         weight: {g: 1840, trend: light, water_needed: true},
         photo: status/latest/grow-20260701-sunf-a1.jpg}
```

**Acceptance:** schema documented in-repo with examples; unknown-field tolerance stated;
round-trips through the tab fixture tests (07).

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
