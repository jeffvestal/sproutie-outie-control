# 07 — The Grow Tab: Sproutie inside Nat iOS

**Decision: a Grow tab in the Nat app, not a separate app.** One person, one assistant, one
codebase; the tent is a life domain like Health and Training, and it rides plumbing that
already exists (cards, queue, today-actions reconciliation, widgets, App Intents). A separate
app is only ever justified if Sproutie ships to strangers (08§6). What keeps it from feeling
bolted-on: the tab imports the tent's *personality* — sproutie-neon accent color, FLORA's
voice in inspection copy — while using Nat's design system. Cross-pollination, not a theme
fork.

## Data path (two stages, ship 1 first)

**Stage 1 — git-mediated, zero new infra.** The Brain pushes `status/tent.yaml` +
`status/latest/*.jpg` thumbnails to the sproutie repo (contract in 06§4). Nat's existing
sync pulls it like `brain.md`. Actions (water logged, mark done, defer) append to
`status/today-actions.yaml` exactly like every other card action; the Brain reconciles on its
next pull (≤5 min). Latency is minutes — fine for plants.

**Stage 2 — live rail for the impatient 10%.** Brain's MCP/REST over Tailscale: live env
numbers, camera peek (go2rtc/HA proxy stream), and immediate control (lights toggle, force
photo, advance phase). The tab must render fully from Stage 1 data alone — the live rail
only upgrades freshness. If Tailscale is down, the tab degrades to Stage 1 silently.

**Staleness is a first-class UI state:** every screen carries `generated_at`; > 45 min stale
→ amber "last seen" banner; > 6 h → red + a watchdog card should already exist. The tab
never displays stale numbers as if live — the failure mode of every home-grown dashboard.

## Information architecture

```
Grow (tab root) — "the tent at a glance"
├── Zone header: temp / RH / VPD tiles, colored vs active phase bands; alerts strip
├── The Grid: visual tent — 2 racks × slots + sidecar cans, mirroring physical layout
│     each cell: crop glyph, day n/N ring, water-needed droplet, phase tint; empty = "+"
├── Harvest rail: horizontally scrolled countdown chips ("Sunflower · Sat ±1d")
└── rows → Grow Detail
      ├── Hero photo (latest snapshot) → tap: timelapse scrubber (all snapshots to date)
      ├── Phase timeline: germ → blackout → light → harvest window, today marked,
      │     transitions annotated (auto vs manual, GDD at transition)
      ├── Forecast card: harvest ETA + confidence, GDD vs coverage forecaster agreement
      │     (disagreement shown honestly: "thermal says Sat, camera says Mon — check water")
      ├── Curves: coverage %, tray weight, GDD accumulation vs target (sparklines, tap to expand)
      ├── Journal: water/notes/issues/phase events + FLORA & Fischoeder inspection notes,
      │     rendered in-voice, photos inline (reads from ES-backed journal via status file digest)
      └── Actions: Log water · Add note · Advance phase (confirm + guard info) · Harvest…
Flows (sheets):
├── Plant: crop (from recipes/) → position (tap empty grid cell) → density (recipe default,
│     stepper) → soak toggle (stored this time) → review → enqueue plant action
├── Harvest: weight g (pre-filled from load cell when present) → quality ★1–5 → note →
│     confirm → enqueue; success screen promises the timelapse ("rendering tonight")
└── Recipe browser (read-only v1): the playbooks, with per-crop Almanac stats when 08§2 lands
```

## Cards (the daily surface — most Grow-tab value lands here, not in the tab)

Emitted by the nat-side routine from `status/tent.yaml` (roadmap Phase 4), all
`dedupe_key: queue-sproutie-*`:

| Card | kind | Trigger | Actions |
|---|---|---|---|
| Harvest window opens | action, prio 2 | ETA −1 day | mark_done → harvest flow deep-link |
| Water needed | action, prio 3 | weight-sawtooth low / no water event in recipe window | "Watered ✓" (→ today-actions → Brain event) |
| Mold risk | watch, prio 2 | risk index > threshold | open tab · "boosted exhaust ✓" ack |
| Phase change (auto) | watch, prio 5 | engine transition | none — FYI with photo |
| Watchdog | action, prio 1–2 | device silent / power-verify mismatch | open tab |
| Fischoeder Sunday inspection | watch, prio 6 | weekly | read note (in voice, with photo) |
| Sow-date solver | action, prio 4 | standing target (08§3) | "sown ✓" |

Deep links: every card opens the relevant Grow Detail or flow (`nat://grow/<grow-id>`).

## Widgets & Intents (the ambient layer)

- **Lock screen circular:** days-to-harvest ring for the nearest harvest; goes 🌱→🥗 on
  window-open day.
- **Lock screen rectangular:** next tent action ("💧 rack-top peas — 2d overdue").
- **Home medium:** grid thumbnail + env tiles + nearest countdown. **StandBy:** same, dark.
- **App Intents:** "How are the sprouts?" (status summary + photo), "I watered the peas"
  (logs event), "When do I harvest the sunflowers?", "Show me the tent" (camera peek, Stage 2).
  Follows the existing siri-app-intents project patterns.

## Kids mode (small, worth it)

`grow.owner: colin|sloane` renders an owner chip on grid cells and a race strip on the tab
root during head-to-head grows (coverage % as score, photo finish at harvest). Their trays,
their bragging rights, zero extra architecture (05§3).

## Build notes for the Opus session

- Nat-ios repo work: new tab following the Health/Training tab v2 conventions (SwiftUI,
  same card/action components); parser for `status/tent.yaml` (schema_version-gated,
  tolerant of unknown fields); timelapse scrubber = AVPlayer over the per-grow MP4 (Phase 3)
  with snapshot-strip fallback.
- Nat repo work: the card-emitting routine + queue tasks (roadmap Phase 4 brief).
- Sproutie repo work: none beyond the 06 contract — **the tab must never read HA directly.**
- Multi-pass suggestion: (1) read-only tab from a hand-written fixture `tent.yaml`; (2) real
  status file + cards + actions loop; (3) widgets + intents; (4) Stage-2 live rail.
- Acceptance: airplane-mode renders last state with staleness banner; plant→water→harvest
  round-trip lands in ES with no direct network path to the tent; a harvest countdown widget
  survives a week without the app being opened.
