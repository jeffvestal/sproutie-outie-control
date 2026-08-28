# 09 — Rip & Replace: the clean-room plan

**Supersedes the phase order in `04-roadmap.md` and the migration section in `06-brain-spec.md` §8.**
Those were written for a system with live grows that had to be preserved. That constraint is
gone. Jeff's call, 2026-08-28: *"I want to just rip and replace — I can manage 1 tray manually
while we rebuild."*

The specs in **02, 03, 06, 07** are unchanged and still the target architecture. This doc only
changes *how we get there* — and it gets simpler, because we no longer have to keep a broken
system alive while replacing it.

## What we learned on 2026-08-28 (the diagnostic that reshaped this)

Live dashboard inspection, six months after the last commit:

| Symptom | Diagnosis |
|---|---|
| "System ACTIVE"; tent temp climbs from 06:00; tray lit in camera | `production_mode` is on and **the light schedule still works** |
| Power Usage `N/A` on all 6 outlets; manual button press does nothing | **Kasa integration dead or entity IDs drifted.** The real root cause. Automations fire into a void — service errors nobody sees |
| Manifest: Sunflower "Day 180", Peppermint/Basil "Day 195" | **Ghost grows** — Jan/Feb batches never harvested out of the slot helpers |
| "Harvest in DUEd" | `(days_left if days_left > 0 else "DUE") ~ "d"` in `ui-lovelace-v3.yaml:237` — cosmetic, but it only shows because everything is months overdue |
| Bottom camera frozen at **Feb 18 2026**; top camera live | Photography pipeline dead for ≥1 camera since February |
| 47 pending updates | ~6 months of HA releases, including breaking syntax changes (`service:`→`action:`, trigger `platform:`→`trigger:`) |

**Two structural lessons that become build rules:**

1. **The 64-reference problem.** Those six switch entity IDs appear **64 times** across the
   YAML (`exhaust_fan` alone: 19). One device re-pair silently broke the whole system and would
   take 64 edits to fix. This is exactly why `06-brain-spec.md` §0.4 makes the entity map a
   single config file. **Non-negotiable from day one.**
2. **Silent failure is the actual enemy.** Every single break above was invisible from the
   dashboard — it looked *fine* while doing nothing for six months. Verification and watchdogs
   are not polish, they are the product.

## New context

- **Tent is effectively empty**: one hand-managed sunflower tray (out of blackout 2026-08-28),
  no system-managed grows. Nothing to migrate — the slot helpers contain only garbage.
- **Colin is helping.** This promotes owner/kid features from moonshot to near-term, and adds a
  real design constraint: **a 10-year-old must be able to use it and log with it.**
- **Goal is regular runs again**, not a heroic rebuild that delays growing.

## Sequencing

Each R-phase is one or two Opus sessions. Start each with:
*"Read `docs/vision/README.md`, `09-rip-and-replace.md`, and the referenced spec sections.
Execute Phase RN."*

---

### R0 — Rescue & decide (do first, partly time-sensitive)

1. **Export the Elasticsearch history before anything else.** `sproutie-outie-ccff9a.es.us-central1.gcp.elastic.cloud`
   — if that deployment is still alive, dump `sproutie-events-*`, `sproutie-sensors-*`, and any
   harvest docs to `attic/es-export/`. If it was a trial, it is probably already gone; confirm
   either way. **This is the only irreplaceable thing in the system** — Jan/Feb grow history.
2. **Freeze the old system as reference, not as a base.** `git checkout main` state is already
   the February config; additionally pull the *actual running* `/config` off the box (it drifted
   — manual `scp` deploys, no verification) into `attic/ha-config-2026-08/` so we can diff what
   was really running against what was committed.
3. **Decide the data backend** (fork, needs Jeff):
   - **(a) Elastic Cloud again** — familiar, keeps FLORA/ML/vector search, costs money, is
     work-adjacent. 
   - **(b) Local first** — Brain writes journal files + a local time-series DB
     (VictoriaMetrics/Influx) + Grafana; ES becomes an optional downstream sink later.
   - Recommendation: **(b) with an ES-shaped exit.** The Brain's journal/event schema stays
     ES-compatible so shipping to Elastic later is a config change, not a rewrite. Removes a
     paid cloud dependency from the critical path of a hobby project; keeps FLORA possible.
4. **Physical stopgap for the live tray**: exhaust + circulation on a dumb schedule (or a $12
   mechanical timer) until R2 lands. Log the sunflower grow **by hand** in
   `grows/2026/manual-sunflower-0828.md` — Colin's job, and it becomes record #1 of the new
   journal so the rebuild starts with continuity instead of a blank page.

**Done when:** ES data is exported or confirmed lost; real running config archived; backend
decided; the live tray has airflow and a hand-log.

---

### R1 — Clean foundation (the rip)

**Rebuild Home Assistant deliberately rather than upgrading six months of cruft.**

1. **Fresh HA install** (current stable), or at minimum a clean `/config` built from scratch.
   Restore *nothing* from the old config automatically.
2. **Re-pair devices with pinned identity.** Kasa strip, Govee, cameras. At pairing time, set
   entity IDs explicitly and record them in **`config/site.yaml`** (06§1). Verify each outlet's
   `*_current_consumption` sensor reports real watts before moving on — that is the signal that
   was dead for six months.
3. **Minimal YAML only** — and it is deliberately dumb:
   - safety rules (thermal guard: temp > 90°F → lights off, exhaust on, notify)
   - fallback light schedule + exhaust duty cycle per zone (the deadman target, 06§3)
   - device watchdogs (sensor silent > 15 min, switch unavailable > 5 min, camera snapshot
     stale > 2× interval) → phone notification
   - **no slots, no crop logic, no template arithmetic, no `input_text` state.** If a template
     does math about a crop, it is in the wrong layer.
4. **Secrets done right**: Eufy credentials, GCP bearer token, any ES key → `secrets.yaml`.
   **Rotate all three** — they are in git history.
5. **`scripts/deploy.sh`**: rsync → remote `ha core check` → targeted reload → canary verify.
   No more blind `scp`.
6. **Delete** `ui-lovelace-mobile.yaml`, `ui-lovelace-test.yaml`, legacy `ui-lovelace.yaml`
   views, the orphaned `icons/`, and the root debug artifacts (`add_instrumentation.py`,
   `add_simple_instrumentation.py`, `fix_scripts.py`) → `attic/`.

**Done when:** every device is controllable and *verified by power draw*; unplugging the Govee
raises a phone alert within 15 minutes; a fresh HA restart comes back to a known-good state with
no lost helper values; deploy is one command.

---

### R2 — Brain v0 (the replace)

Build `06-brain-spec.md` §1–2, §5 (read paths), §6 (git bridge). No behavior changes to the
tent yet — the Brain observes and records while HA still runs the dumb schedules.

- `config/site.yaml` (zones, positions, entity map), `recipes/*.yaml` (start with sunflower,
  pea, radish — the crops actually in rotation), `state/grows.yaml`.
- Phase engine as **single writer**, with the event-sourced day counters that make the old
  `literal_eval`/255-char bug class structurally impossible.
- `GET /status` → publishes `status/tent.yaml`, git-pushed on change + hourly.
- Telemetry recording to the R0-chosen backend.
- **pytest + tent-sim from the first commit** (06§7). The golden-grow replay is what keeps this
  from becoming the old system again.
- Migrate the hand-logged sunflower grow into `state/grows.yaml` as the first real record.

**Done when:** `status/tent.yaml` reflects reality and updates itself; a full simulated grow
passes in CI; the ghost-grow class of bug cannot occur (no grow exists without an event trail).

---

### R3 — Brain takes control

06§3–4. The Brain drives lights/exhaust through HA; HA keeps only safety + fallback.

- Per-rack light schedules (hardware always supported this; the old YAML never did), per-phase
  VPD-banded exhaust, photo sequencing owned end-to-end.
- **Deadman switch**: Brain heartbeats HA every 60s; stale > 30 min → HA reverts to fallback
  schedules + alerts. *This is the single feature that would have prevented the last six months.*
- **Command + verify** on every actuation via the power sensors; mismatch → retry → alert +
  `verified: false` in status.
- Delete the old `automations.yaml`/`scripts.yaml` grow logic entirely. One generated wall-panel
  Lovelace view survives (keep the cyberpunk look — it earned it).

**Done when:** killing the Brain for 35 minutes produces fallback behavior + an alert, and
restarting resumes smart control with a logged gap.

---

### R4 — The Grow tab in Nat

Build `07-grow-tab-spec.md` Stage 1 (git-mediated) + cards. **Include the owner/Colin surface in
this phase, not later**: owner chips on grid cells, and a "log water/note" flow simple enough for
a kid to use unsupervised.

**Done when:** the daily briefing carries a grow card with a photo and a correct countdown, and
Colin can log a watering from the phone without help.

---

### R5 — Instruments & prediction

Old roadmap Phases 3 + 5, unchanged: canopy coverage CV, timelapse at harvest, GDD accumulation,
VPD forecasting, harvest ETA ensemble, mold-risk index, sow-date solver. Add **load cells** here
if the hardware appetite exists (03§3.4) — with Colin involved, "the tray tells you it's thirsty"
is the feature that sells the whole project to a kid.

### R6 — Scale & play

Zones for tent #2 / yard / pots (03§2), the kids' growth race with a live scoreboard (05§3),
Fischoeder's weekly inspections (05§1), the Almanac (08§2).

---

## What "rip and replace" explicitly kills

- The parallel-run migration in **06§8** — no longer needed, delete it.
- All 20 `input_text.slot_*_data` helpers and `crop_library_json` — **deleted, not migrated.**
  Their current contents are six-month-old ghosts.
- The 37 copy-pasted slot arrays and the drifted duplicate crop dictionary.
- Three of the four Lovelace dashboards.
- The stub `mcp_server/` — replaced by the Brain's real MCP surface (06§5).

## Operating mode during the rebuild

One tray, hand-managed, hand-logged in `grows/2026/`. Colin owns the daily log. Every hand-logged
grow becomes a record in the new journal, so by the time R2 lands there is already history to
show — and the first thing the new system does is tell you something true about a grow it didn't
manage.
