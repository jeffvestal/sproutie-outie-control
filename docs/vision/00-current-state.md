# 00 — Current State: an honest review

*Based on a full repo survey, 2026-07-07. Receipts inline.*

## What this system is today

HA (remote box at `192.168.1.232`) drives a Kasa 6-outlet smart strip (2 rack lights, 2
circulation fans, exhaust fan, camera flash), reads one Govee temp/RH sensor in-tent, and runs
2 Eufy cloud cams + 1 LAN ESP32-CAM (sidecar cans). Around it: a photography pipeline
(scene-save → flash → per-slot snapshots → GCS via a GCP Function → ES event), an Elastic
Cloud deployment as the history store (`sproutie-sensors-*`, events, harvests, an ML
anomaly job, the FLORA Agent Builder agent), four Lovelace dashboards in three unrelated
design languages, and a stub MCP server that returns fake data.

## What's genuinely good (keep these instincts)

1. **History was evicted from HA into Elasticsearch.** That was the right call — and it was
   learned the hard way (see below). ES as system of record for events/telemetry is the one
   architectural decision here that already matches the v2 vision. It stays.
2. **Single-writer discipline exists in embryo.** After the corruption saga, slot writes were
   restricted to one script fired only on Phase Change. Correct instinct; v2 makes it a law.
3. **The photography pipeline is 80% of a growth-tracking instrument.** Scene save, flash,
   per-slot snapshots, cloud upload, failure tracking, retention. It just doesn't *measure*
   anything yet.
4. **Per-outlet power sensors already exist** (`*_current_consumption` on every Kasa outlet)
   and are used for nothing. Closed-loop actuation verification is sitting there, free.
5. **Auditing automations** log every switch/mode change to ES. The data habit is real.

## The pathology (why it keeps breaking)

### 1. Grow state lives in 20 tortured `input_text` helpers
Each slot is a 255-char JSON blob (`input_text.slot_a1_data` …). The crop library is *another*
JSON blob with keys shortened (`grow_days`→`d`) **to fit under the 255-char cap**. This is a
database implemented inside a UI text field. The corruption saga was the inevitable result:
history arrays overflowed 255 chars → silent truncation → "Unknown" batch IDs → three commits
of exorcism, plus the discovery that HA's `literal_eval` silently coerces types between script
steps, breaking batch-id comparisons. The fix (build JSON in one template block) treats the
symptom. The disease is *state that belongs in a file/database being smeared across helper
entities with a hard size cap and no schema, no transactions, no history*.

### 2. Template copy-paste at pathological scale
The 20-slot array is duplicated **37×** across 4 files. A stale crop→grow-days dict
(Wheatgrass/Broccoli/Kale…) is duplicated 3× and has drifted from the real crop library — so
the legacy dashboard's harvest countdown silently falls back to "7 days" for most current
crops. There is no build step, so there is no single source of truth *possible* in pure YAML.
Every new slot, crop, or field means editing dozens of sites by hand. This is why every change
breaks something.

### 3. Split brain, and the halves disagree
Desktop phase changes go through `sproutie_advance_phase` → slot update + ES log. **Mobile
phase taps log to ES but never update the slot** (they call a script reading an
`input_select.growth_phase` that doesn't exist). The mobile plant form collects soak fields
the plant script never stores. Two dashboards call selection scripts that exist nowhere —
dead taps. The UI and the state machine are maintained separately by hand, so they diverge.

### 4. Everything critical is cloud, nothing is watched
Kasa (cloud), Eufy (cloud, **plaintext credentials in `configuration.yaml`**, bypassing
`secrets.yaml` — fix this week regardless of anything else in these docs; same for the two
raw ES URLs in `sensors.yaml`), Elastic Cloud, GCP. Internet blip = lights, exhaust logic,
cameras, and history all degrade at once. Meanwhile the only health monitoring is ES-push
staleness and GCS upload failures: a dead Govee sensor silently stops the humidity automation;
a dead camera silently ends growth records; nothing alerts.

### 5. Deploy is `sftp` + hope
Manual file push, manual YAML reload/restart, no validation, no CI. "Kind of working" commits
are the natural output of a system you can't test before deploying to production plants.

### 6. Four dashboards, three design languages, zero conclusions
Aerospace Industrial (v2.6) → Cyberpunk "DO NOT BREAK" (v3, 1,536 lines) → Soft & Round
mobile (1,106 lines) → a test scratchpad. Plus an orphaned custom SVG icon set in a
directory HA can't even serve. Each rebuild was an attempt to make HA's UI pleasant; the
lesson after three attempts is not "try a fourth theme," it's **stop building product UI in
Lovelace** (see 02).

### 7. The AI layer is a beautiful façade
FLORA has a personality spec, ES|QL tools, workflows — and its control path proxies to an MCP
server whose every tool returns hardcoded fake data. The botany-log automations (with a
384-dim vector field ready for semantic search) were dropped in the v3 rewrite. The
scaffolding for the smartest parts of this system exists and is connected to nothing.

## Diagnosis in one sentence

**The device layer is fine, the data instinct (ES) is right, and every chronic failure traces
to one root cause: application state and logic are implemented inside Home Assistant's
config/helper/template system, which is a great device driver and a terrible application
runtime.** 01 and 02 are two escalation levels of the same cure: move state and logic into
real code and real files, and let HA do only what it's good at.
