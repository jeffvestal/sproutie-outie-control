# 01 — Proposal A: HA Done Right

Keep Home Assistant as the platform, but rebuild on eight laws. This proposal alone would end
the breakage cycle. (02 goes further; A is also the foundation B builds on, so nothing here is
throwaway.)

## The Eight Laws

**Law 1 — HA is a device driver, not an application runtime.**
HA's job: talk to switches, sensors, cameras; run dumb schedules; expose an API. Grow logic,
crop math, and state live elsewhere. If a template is doing arithmetic about crops, it's in
the wrong layer.

**Law 2 — State lives in files with a schema, never in helpers.**
Kill all 20 `input_text.slot_*_data` blobs and `input_text.crop_library_json`. Replace with
`state/grows.yaml` + `recipes/*.yaml` in this repo (schema in 03). No 255-char cap, no
`literal_eval` coercion, versioned, diffable, recoverable. HA reads it via one
`command_line`/REST sensor exposing current-state JSON; HA never writes it.

**Law 3 — One writer per file.**
A single phase-engine process (PyScript module now; the Brain in 02) is the only thing that
mutates grow state. UI taps and Nat commands *request* transitions through it. Mobile-vs-
desktop divergence becomes structurally impossible instead of a bug class.

**Law 4 — Logic is Python with tests, YAML stays dumb.**
Install **PyScript** (or AppDaemon). Port: phase engine, exhaust control (one module honoring
mode select — duty/humidity/temp, replacing three interlocking YAML automations), light
scheduling **per rack** (the hardware supports it; the YAML never did), photography
sequencing. Each module gets pytest coverage run in GitHub Actions against recorded sensor
traces (tent-sim, 05§8). YAML retains only: dumb time triggers calling PyScript services, and
on-device-style safety rules.

**Law 5 — Closed loop or it didn't happen.**
The per-outlet power sensors finally earn their keep: after any light/fan command, verify
current draw within 60 s; mismatch → retry once → alert. Watchdog every device: Govee silent
> 15 min, camera snapshot stale > 2× interval, any Kasa outlet unavailable > 5 min → phone
alert. A grow tent's failure mode is *silent* — lights that never came on for 3 days. This law
is the difference between automation and abdication.

**Law 6 — Safety rules are independent of everything.**
Thermal guard (temp > 90°F → lights off, exhaust on, alert) implemented as a standalone
minimal YAML automation *plus*, when hardware migrates (below), on-device ESPHome logic that
works with HA down. The flash safety-valve gets fixed (it currently restores a scene that is
never created — dead code guarding a real failure mode).

**Law 7 — Deploys are validated, versioned, one command.**
`make deploy`: `ha core check` against the new config (via SSH), rsync the delta, targeted
domain reloads, then verify a canary sensor. Secrets sweep first: **Eufy creds and raw ES
URLs move to `secrets.yaml` immediately.** Pin HA version; update monthly *after* snapshot
backup (enable automated HA backups to GCS — the GCP plumbing already exists).

**Law 8 — One dashboard, generated.**
Keep the cyberpunk v3 aesthetic (it has personality; personality stays), but the slot grid,
crop colors, and countdowns are **generated into Lovelace YAML by a script** from the same
recipe/state files the engine uses (that's the strategic-config pattern HA can't do natively).
The 37× copy-paste dies. Mobile Lovelace is deleted, not fixed — the phone story is Nat (02).
FLORA's placeholder chat view goes dormant until the Brain gives it real hands (02).

## Hardware posture (reliability track, incremental)

| Now (cloud, fine for v1) | Target (local, boring) | Why/when |
|---|---|---|
| Kasa strip (cloud) | Zigbee metering plugs or an ESPHome relay+CT board | When a cloud outage bites, or at tent #2. Local control + power metering preserved. |
| Govee via cloud/BLE | ESPHome node: SHT31 ×2 (in + **out** of tent) + SCD41 (CO₂) | The inside/outside pair unlocks smart exhaust (03§3.2); CO₂ is a growth lever nobody home-measures. ~$45. |
| Eufy cams (cloud) | Keep, but add local RTSP or lean on the ESP32-CAM pattern | ESP32-CAMs are $8 and already proven in this tent (sidecar). One per rack = fully local eyes. |
| — | Load cells under trays (03§3.4) | The single highest-value new sensor in the whole plan. |

Rule of thumb: **replace on failure or expansion, not for purity** — but every replacement is
local-first, and new hardware is ESPHome/Zigbee only.

## What Proposal A does *not* fix

- Lovelace remains the only human UI, and Lovelace is why there are three abandoned design
  languages. Law 8 contains the damage; it doesn't make the UI *good*.
- FLORA still has no real control path (stub MCP server).
- The phone experience is still the HA app.

Those are exactly the gaps 02 closes. **Verdict: if you want the minimum-change path, stop at
A and the tent stops breaking. But you have 5% of a Fable and a working Nat app — read on.**
