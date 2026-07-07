# 04 — Roadmap: phased briefs for Opus build sessions

Each phase is a self-contained brief. Start an Opus session with:
*"Read `docs/vision/README.md`, `00-current-state.md`, and the Phase N brief in `04-roadmap.md`.
Execute Phase N. Respect the guardrails."* Phases ship value independently — stop anywhere and
be net ahead. Order matters (each builds on the last), but 3/4/5 can interleave.

**Global guardrails (every session):**
- Never edit `ui-lovelace-v3.yaml` except where a brief says so. Plants are in production.
- No new `input_text`/helper state. State goes in files. (Law 2.)
- Deploy only via the Phase 0 deploy script once it exists; verify canary after.
- Small commits, descriptive messages, push when green.

---

## Phase 0 — Stop the bleeding (1 session, no behavior changes)

**Goal:** the system as-is, but observable, deployable, and not leaking credentials.

1. **Secrets sweep:** Eufy creds (`configuration.yaml:17-19`) and the two raw ES URLs
   (`packages/sproutie_outie/sensors.yaml:1195,1213`) → `secrets.yaml`. Audit git history;
   rotate the Eufy password and ES key after (note in PR for Jeff).
2. **Deploy script** (`scripts/deploy.sh`): rsync delta → remote `ha core check` → targeted
   domain reloads → verify a canary template sensor bumped. Replaces `upload.sftp`.
3. **Watchdogs** (new `packages/sproutie_outie/watchdogs.yaml`): Govee stale >15 min; each
   Kasa switch unavailable >5 min; each camera's `_latest.jpg` older than 2× photo interval;
   ES connection status — each → mobile notification. 
4. **Power-verify:** after light/fan state changes, check the outlet's
   `*_current_consumption` within 60 s; mismatch → retry once → alert. (Law 5.)
5. **Dead code:** fix the flash safety-valve's phantom scene; delete the two dead-tap
   template calls (`sproutie_update_selection`, `sproutie_smart_slot_selection`); move the
   root-level debug artifacts (`add_instrumentation.py`, `add_simple_instrumentation.py`,
   `fix_scripts.py`) to `attic/`.
6. Enable scheduled HA backups (to GCS — reuse the existing bucket/creds pattern).

**Accept:** deploy runs end-to-end; unplugging the Govee raises a phone alert; a light
command with the bulb physically unplugged raises a mismatch alert.

## Phase 1 — The state exodus (1–2 sessions) ← the big one

**Goal:** grow state and crop knowledge leave HA helpers forever.

1. Create `recipes/*.yaml` (schema in 03§1) for the 8 current crops, migrating
   `crop_library_json` + phase knowledge; create `state/grows.yaml` reflecting today's live
   slots (read them out of HA first).
2. **Sproutie Brain v0** (`brain/`, FastAPI + APScheduler, runs on the HA box): phase engine
   as single writer of `grows.yaml`; endpoints `GET /status`, `POST /grows` (plant),
   `POST /grows/{id}/phase`, `POST /grows/{id}/harvest`, `POST /grows/{id}/event`; writes
   every event to ES (reuse existing index conventions); pushes `status/tent.yaml` to this
   repo on change (git bridge).
3. HA integration: one REST sensor consuming `GET /status` (replaces the 37 copy-pasted slot
   arrays as the dashboards' source); `rest_command`s for plant/phase/harvest/water pointing
   at the Brain; rewire desktop scripts to call them. Delete `input_text.slot_*` and
   `crop_library_json` **only after** a full grow-cycle's parallel run.
4. **Tests + CI:** pytest on the phase engine (transitions, harvest, the literal_eval bug
   class as regression tests); GitHub Actions; tent-sim harness replaying a recorded day.

**Accept:** plant→phase→harvest round-trips via Brain from the v3 dashboard; slot JSON
corruption is structurally impossible; CI green.

## Phase 2 — One UI to rule them (1 session)

**Goal:** end the dashboard wars. Keep cyberpunk v3 as the *only* Lovelace, generated where
it counts.

1. `scripts/generate_dashboard.py`: emit the slot grid/crop colors/countdown cards for v3
   from `recipes/` + Brain status (kills the stale duplicated crop dict — countdown correctness
   restored). Generated block clearly fenced.
2. Delete `ui-lovelace-mobile.yaml`, `ui-lovelace-test.yaml`, legacy `ui-lovelace.yaml` views,
   and the orphaned `icons/` set (or install them properly in `www/` if v3 wants them — one
   decision, then done). Mobile = Nat (Phase 4); note it in README.
3. Fix remaining desktop taps to Brain endpoints; mobile-script mismatch bug class dies with
   the mobile file.

**Accept:** exactly one dashboard file in repo; countdowns correct for all 8 crops; every tap
does something real.

## Phase 3 — Eyes become instruments (1 session)

**Goal:** the photography pipeline starts measuring.

1. **Coverage:** `brain/vision.py` — HSV green-segmentation over each slot's daily snapshot →
   coverage % → ES + `grows.yaml` observation. Calibrate tray crop regions once per camera.
2. **Timelapse:** at harvest, ffmpeg the grow's GCS snapshots into an MP4, drop into the repo
   (or GCS + link) — auto-attached to the grow record. (05§2.)
3. Fix the snapshot target-dir inconsistency (sidecar vs racks); ensure per-slot snapshot
   naming carries grow-id.
4. **Claude weekly check:** cron in Brain — photo packet + week's telemetry → Claude API →
   qualitative note (legginess/yellowing/mold/uneven) filed as ES event + grow observation.
   (Persona optional here; Fischoeder ships in 05.)

**Accept:** coverage curve visible in Kibana for a live grow; a finished grow yields an MP4;
one AI inspection note filed.

## Phase 4 — The Nat bridge (1 session, touches both repos)

**Goal:** the tent joins the daily briefing.

1. Brain pushes `status/tent.yaml` (already, Phase 1) + `status/latest/*.jpg` thumbnails.
2. In **nat repo**: routine reads sproutie repo status → emits grow card(s) into
   `today-cards.yaml` per queue rules (kind `watch`, dedupe `queue-sproutie-*`): harvest
   countdown, water-needed, mold-risk, watchdog alerts. Mark-done reconciles via existing
   `today-actions.yaml` flow (e.g. "watered" → Brain event on next sync).
3. Sow/harvest tasks into nat's `queue/tasks.yaml` from Brain's forecaster (surface_only).
4. Optional live path: Brain MCP reachable via Tailscale; register with Nat sessions so
   "skip tonight's lights-off" works from the phone. FLORA's workflow tools repointed at the
   real MCP — FLORA comes alive the same day.

**Accept:** tomorrow's daily briefing contains a grow card with a photo and a correct
countdown; tapping done on a water card lands an event in ES.

## Phase 5 — Prediction (1–2 sessions)

**Goal:** the system knows the future (03§3 is the spec).

1. GDD accumulator per grow (tent sensor; Open-Meteo for future outdoor zones); recipes get
   `expected.gdd_f` (backfill from ES history — there are months of 5-min telemetry to mine).
2. VPD derived sensor + exhaust control mode "VPD" in the Brain (per-phase bands from recipe).
3. Harvest ETA = ensemble(GDD, coverage-curve fit) with disagreement alerts; sow-date solver
   (`GET /solve?crop=sunflower&ready_by=2026-07-19`).
4. Mold-risk index (RH-hours + fan duty + phase) → card + auto exhaust boost.
5. Revive the ES anomaly job (apply script exists) + wire its output to a card.

**Accept:** a live grow shows ETA ±1 day by mid-grow; one correct "water/mold/anomaly"
prediction observed in the wild.

## Phase 6 — Scale (when the itch strikes)

Zones abstraction in Brain config; tent #2 BOM (~$120: ESPHome SHT31×2+SCD41 node, 3 Zigbee
metering plugs, ESP32-CAM ×2); outdoor zone (Ecowitt soil/weather → task-emitting mode);
kids' growth-race scoreboard (05§3); hardware migration per 01's posture table; load cells
(03§3.4) under the next tray rotation.

---

### Suggested cadence
Phase 0 this week (it's also the security fix). Phase 1 next. One phase per week of evenings
after that. By fall: a tent that predicts its harvests, briefs you at breakfast, and has
never once been debugged via `input_text` surgery. 🌱
