# 05 — Wild Ideas (the over-the-top annex)

Things you didn't ask for. Some are one evening of work, some are a season. All of them are
more fun than work tech. Roughly ordered by joy-per-effort.

## 1. Fischoeder, the landlord-agronomist 🥀🍷

A weekly agent (cloud routine, runs Sunday) that collects the week's photo packet + telemetry
per grow and has Claude write a **landlord's inspection note** — equal parts agronomy and
menace: *"The sunflowers are leggy, Robert. Stretching for light like tenants reaching for a
rent extension. Raise the tray or lower my expectations. The peas, however — magnificent. Rent's
going up."* Real diagnostics (legginess, yellowing, uneven germination, mold fuzz, dry spots)
wrapped in personality, filed to `grows/…/inspections/` and surfaced as a Nat card. He shows up
weekly, judges everything, does no labor. Perfect landlord. Beefsquat coaches you; Fischoeder
coaches the plants.

## 2. Auto-timelapse reels 🎬

Every grow's daily snapshots → ffmpeg → a 12-second seed-to-harvest reel, auto-rendered at
harvest, dropped in the repo and texted to the family thread. Zero-effort after setup; the
kind of thing that makes the whole project make sense to people who ask "why." End-of-year:
stitch every grow into the Sproutie-Outie Year in Review.

## 3. The kids' growth race 🏁

Colin's tray vs Sloane's tray: same crop, same recipe, one variable each (their choice —
density, water, an extra light hour). Live scoreboard card (coverage % as the score), camera
proof, winner picks the next crop. It's a science-fair sneak attack: hypotheses, controls, and
data literacy disguised as sibling rivalry. The entity model already supports it —
`grow.owner: colin`.

## 4. Project Kegs of Duff ☕ (the coffee cans)

The two coffee cans get promoted to first-class citizens: `zone: tent-1/sidecar-{1,2}`,
milestone-based perennial recipes (no day counters — events: germination, true leaves, 6",
first flowers, first cherries). If those cans contain actual coffee plants, the harvest ETA is
~2029, which means the system's longest-running integration test is *a shrub*. The Nat card
writes itself: "Kegs of Duff: day 847. Still not coffee. Morale holding." The ESP32-CAM already
watching the sidecar makes this the most-photographed houseplant in Evanston.

## 5. "Hey Sproutie" — voice in the office 🎙️

Home Assistant Voice PE (~$59) or an ESP32-S3-BOX on the desk: local wake word, no cloud.
"Hey Sproutie, lights out." "Hey Sproutie, when do I harvest?" HA's Assist pipeline can also
route to Claude for the questions that aren't commands. Silly. Deeply satisfying. The office
becomes the ship's bridge.

## 6. Harvest economics (an Edith crossover) 💰

Microgreens retail $20–30/lb. Log yields (the load cells do it for free) → running dashboard:
$/tray produced, grocery offset YTD, amortization curve on the tent hardware. The joke with a
straight face: a payback-period chart for the grow tent, reviewed in the monthly finance wrap.
"The tent breaks even in March 2027, assuming pea consumption holds."

## 7. Seed inventory that reorders itself 🌰

`inventory/seeds.yaml`: lot, grams remaining (each sow decrements), viability date. Below two
sows' worth → a task lands in nat's queue with the reorder link. Never discover you're out of
sunflower seed on sow day. Bonus: seed-lot ID rides on every grow record, so a bad lot shows up
in the yield data — *"lot 2026-B germinates 15% worse"* is knowledge worth actual money.

## 8. Tent-sim: CI for a grow tent 🧪

A simulator that replays recorded sensor days (plus synthetic disasters: stuck exhaust, heat
spike, sensor dropout, flaky wifi) against the Brain's logic in GitHub Actions. Every PR to a
recipe or automation gets a simulated grow before it touches real plants. "The tests must pass
before you may water" is the most Jeff sentence this repo can contain — work-tech discipline,
applied to radishes, on purpose, for fun.

## 9. The sow-date solver, weaponized 🍽️

Wire the harvest forecaster backwards into meal planning: standing Sunday-dinner target →
auto-generated sow tasks on the right days, per crop, drifting with actual GDD. The tent
becomes a just-in-time salad supply chain. Toyota, but for garnish.

## 10. Grow-along protocol 🤝

Recipes are already shareable files; add `sproutie export sunflower-v2` → a gist anyone with
the stack (or just a notebook and a tent) can follow, and their journal rows can merge back.
Two households running the same recipe in different climates = the beginning of an actual
dataset. Open-source agronomy at the two-tray scale.

## 11. SOC 2 certification 📋

When the v2 architecture ships, the repo README badge reads **"SOC 2 Compliant"** — Sproutie
Outie Control, version 2. No auditor need ever know. This is mandatory; I don't make the rules.

---

*Priority hint if forced to choose: 2 (timelapse) and 7 (seed inventory) are weekend-sized and
pay off immediately; 1 (Fischoeder) is the soul of the thing; 8 (tent-sim) is what makes
"keeps breaking" structurally impossible instead of temporarily patched.*
