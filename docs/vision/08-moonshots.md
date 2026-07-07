# 08 — Moonshots: the go-crazy pass

05 was wild ideas you could build in a weekend. These are the ones that change what the
project *is*. Written with the last of the Fable — aim accordingly.

## 1. The tent becomes an agent, not an automation 🤖

The endgame of the Brain isn't schedules — it's **an agentic ops loop**. Nightly, a scheduled
Claude session (Agent SDK, running against the Brain's MCP) reads the day's telemetry, curves,
and photos, and *does the gardener's thinking*: notices the coverage curve flattening two days
early, cross-references the journal ("this happened in May — dry tray"), decides, acts within
granted scopes (boost photo cadence, flag water, adjust an exhaust band), and — for anything
structural — **opens a PR**: a recipe tweak with evidence in the description, a config change,
a new watchdog. You review agronomy the way you review code, because it *is* code. The
autonomy ladder is explicit: observe → recommend → act-with-ack → act-within-bounds, promoted
per behavior as trust accrues, demoted automatically on a bad call. This is the pattern
worth proving here precisely because the stakes are radishes — then it generalizes to
everything else Nat runs.

## 2. The Almanac 📖

After every harvest, the journal compiles into a living, auto-written book: per-crop chapters
of *your* truths ("Sunflower in this tent: 11.2 days ±0.8, best at 118 g/tray, mold risk
spikes after day 9 below 0.7 kPa — three incidents, all winter"), seasonal patterns (office
temp vs radiator season), lot performance, failure post-mortems written by Fischoeder with
grudging respect. Semantic search over it (the vector field already in the botany-log
mapping) means FLORA answers "have we seen this before?" with citations to your own past
grows. Twenty years from now this document is a family heirloom that happens to be
machine-written. **Data compounds; the Almanac is the interest.**

## 3. Seasons — Beefsquat for the garden 🗓️

Beefsquat programs training blocks; the Almanac + solver program **grow seasons**. Declare
intents, not tasks: "greens for Sunday dinners through fall; basil peaking for the
holiday-gift pesto run; Colin & Sloane race each school break; the yard tomatoes hardened
off after last frost." The season compiler emits the sow calendar, feeds nat's queue on the
right days, adjusts live as actual GDD drifts, and re-plans around travel (it can see the
calendar — sow nothing that peaks while the family is in a national park). The tent stops
being a thing you operate and becomes a standing promise the house keeps.

## 4. Autopilot: seed-to-harvest, zero touches 🚁

The full closed loop, achievement-run style: load cells (water sensing) + a peristaltic pump
and reservoir (~$40) + the phase engine + vision QA = a grow where the only human events are
*sow* and *eat*. The Brain waters by weight, adjusts light by phase, verifies by camera,
and the harvest card arrives with the timelapse attached. Do it once for the badge
("UNTOUCHED-BY-HUMAN-HANDS: 1"); keep it for travel weeks. Outdoor variant: drip valve on a
hose timer, soil moisture, rain-forecast-aware. The tent that grew food *while nobody was
home* is the demo that justifies every hour spent on this repo.

## 5. The Colony 🌐

Recipes are files; status is a contract; the Brain is one small service. So: **federate.**
A second Brain at the in-laws' windowsill, a friend's tent in Colorado, each pushing status
to their own repo, all readable by one Nat. Shared recipes with per-site actuals flowing
back — `sunflower@2.1.0` grown in 4 climates is the beginning of a real dataset, open-source
agronomy at hobby scale ("the Sproutie Protocol"). Family layer: grandparents get the
photo-cards and the kids' race updates with zero setup beyond a repo invite.

## 6. The honest business footnote 💼

There is a real product shape here — "grow ops in a box": open-source Brain + protocol,
hosted bridge + app for people who won't self-host, BOM kits. It's adjacent to the
second-income-strategy project, and it's also a trap: productizing joy is how joy becomes
work-tech. The architecture keeps the door open (nothing here is Jeff-specific except
config); the recommendation is to *build for one household* and let the Colony decide if it
wants to exist. Doors open, no pressure on the hinges.

## 7. Full sensorium 🛰️

The upgrade tree, in order of information-per-dollar: outside temp/RH pair (smart exhaust,
$15) → load cells (water+growth+yield, $10/tray) → SCD41 CO₂ (the invisible growth lever —
an office with humans cycles 400→1200 ppm daily and nobody's microgreens rig measures it,
$40) → dimmable driver + 0-10V ESPHome (light *recipes*: sunrise ramps, DLI targets, per-
phase intensity — the last analog knob goes digital, $25) → PAR sensor for ground truth →
leaf-zone IR thermometer (canopy temp ≠ air temp; VPD computed on leaf temp is the pro
version). Endgame: the tent-sim becomes a **digital twin** — trained on your telemetry, it
answers "what would 18 h light do to the peas?" before a single real seed pays for the
experiment.

## 8. The Vestal Terroir Report 🍷📄

Every January 1st, the system auto-writes the year: total yield by crop, $-offset (Edith
provides the grocery index), best and worst grow with post-mortems, the year's timelapse
supercut, kids' race standings, Fischoeder's year-in-review note ("A season of adequate
rent-paying, Grower"), Kegs of Duff progress ("day 542; photosynthesis continues; coffee
does not"), and one Almanac insight nobody would have guessed. Rendered as a print-ready PDF.
It goes on the fridge. This is the artifact that makes five years of over-engineering
legible to the people you grow the food for.

---

*The through-line of all eight: the tent is the safest possible proving ground for the most
advanced pattern in your toolbox — autonomous agents with real-world actuators, verified
loops, and taste. Everything learned here flows back into Nat proper. The radishes are the
excuse. They were always the excuse.* 🌱
