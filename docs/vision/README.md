# Sproutie-Outie: The Vision

*Written by Nat (Fable), 2026-07-07 — the "last 5% of Fable" architecture run.*

This directory is the master plan for turning a grow tent that "works but keeps breaking"
into a grow **platform** that scales from 2 trays of microgreens to multiple tents, yard
beds, potted plants, and two mysterious coffee cans — with predictive harvests and Nat as
the front door.

**Yes, this is absurdly over-engineered for two trays of radish greens. That is the point.
This is the fun tech. Build it like it matters.**

## The docs

| Doc | What it is |
|---|---|
| [00-current-state.md](00-current-state.md) | Honest review of what exists today and why it breaks |
| [01-ha-done-right.md](01-ha-done-right.md) | Proposal A: keep Home Assistant, make it boring and reliable |
| [02-beyond-ha.md](02-beyond-ha.md) | Proposal B: headless HA + Sproutie Brain + Nat as the UI (recommended), and B2: the full no-HA custom stack |
| [03-scale-and-predict.md](03-scale-and-predict.md) | The entity model that scales to N tents/yards/pots, and the predictive layer (GDD, VPD, camera CV, harvest ETA) |
| [04-roadmap.md](04-roadmap.md) | Phased build plan — copy-paste briefs for individual Opus sessions |
| [05-wild-ideas.md](05-wild-ideas.md) | The over-the-top stuff: timelapse reels, Fischoeder the landlord-agronomist, kids' growth races, coffee-can futures |
| [06-brain-spec.md](06-brain-spec.md) | **Sproutie Brain engineering spec** — invariants, schemas, deadman control, API/MCP surface, tent-sim, migration. The multi-pass Opus doc. |
| [07-grow-tab-spec.md](07-grow-tab-spec.md) | **Grow tab in Nat iOS** (decided: tab, not separate app) — IA, cards, widgets, intents, two-stage data path |
| [08-moonshots.md](08-moonshots.md) | The go-crazy pass: agentic ops loop, the Almanac, Seasons, Autopilot, the Colony, digital twin, the Terroir Report |

## TL;DR of the recommendation

1. **Don't rip out HA. Demote it.** HA is a great *device driver* and a miserable *application
   platform*. Keep it as the headless integration layer; stop building UI and grow logic in it.
2. **Grow logic moves to code** — a small Python service ("Sproutie Brain") with recipes as
   data, real state machines, unit tests, and CI. YAML automations stay dumb.
3. **The UI you keep fighting for is one you already have: Nat.** Grow status flows into the
   nat repo's cards/queue system via git. Ask your phone "how are the sprouts?" and get an
   answer with a photo. Lovelace gets one generated wall-panel dashboard and is otherwise fired.
4. **Closed loops, not fire-and-forget.** Power-monitoring plugs verify the lights actually
   turned on. Watchdogs catch silent sensors. Safety rules live on-device, not in the hub.
5. **Data is the moat.** Every grow logged (crop, recipe, environment, photos, yield) becomes
   training data for harvest prediction. GDD + canopy coverage beats calendar guessing.

## How to use this with Opus build sessions

Each phase in [04-roadmap.md](04-roadmap.md) is a self-contained brief. Start an Opus session,
point it at this repo, and say: *"Read docs/vision/README.md and 04-roadmap.md, then execute
Phase N exactly as briefed."* Phases are ordered to deliver value independently — you can stop
after any phase and be better off than before.
