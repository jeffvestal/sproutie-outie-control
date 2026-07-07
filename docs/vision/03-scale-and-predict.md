# 03 — Scale & Predict: from a tent to a growing system

The current system automates *a tent*. The vision is a system that models *growing things*,
where the tent is just one place growing happens. Get the data model right and everything
else — second tent, yard beds, pots on the deck, coffee cans — is configuration, not code.

## 1. The entity model

Five nouns. Everything in the platform hangs off these.

```
Site ("home")
└── Zone            — a controlled or observed space: tent-1, tent-2, yard-bed-south, deck-pots, office-window
    ├── capabilities: [light-control, fan-control, exhaust, camera, temp-rh, co2, weather-fed]
    └── Position     — a physical slot: tent-1/rack-top, tent-1/rack-bottom, tent-1/sidecar-1 (coffee can!)
        └── Grow     — ONE lifecycle of ONE crop in ONE position. The atomic unit of everything.
            ├── recipe: → Recipe (crop playbook, versioned data)
            ├── state: sown → germination → blackout → light → harvest-window → harvested | failed
            ├── Observations — timestamped: sensor rollups, photos, coverage %, weights, human notes
            └── Harvest — date, yield grams, quality 1–5, notes
```

**Recipe** is the crop playbook, stored as data (YAML in `recipes/`), never hardcoded in
automations:

```yaml
# recipes/sunflower-v2.yaml
crop: sunflower
seed: "Black oil, True Leaf lot 2026-A"
density_g_per_1020_tray: 125
phases:
  germination: { days: 3,  light: off, target_temp_f: [70, 75], target_rh: [80, 95], weighted: true }
  blackout:    { days: 2,  light: off, target_temp_f: [68, 74], target_rh: [60, 80] }
  light:       { days: 6,  light_hours: 16, target_temp_f: [65, 75], target_vpd_kpa: [0.8, 1.2] }
harvest_window_days: 3
expected: { total_days: 11, gdd_f: 280, yield_g: [350, 500], coverage_at_harvest: 0.92 }
```

Key properties of this model:

- **A Grow is an instance, a Recipe is a class.** Today's pain (hardcoded per-crop schedules,
  slot state corruption) is what happens when instances and classes are smeared together in
  automation YAML and helper entities.
- **State transitions are events, not times.** "Day 5" doesn't move a grow to the light phase —
  a `phase_change` event does, fired by the engine when criteria are met (elapsed days *or* GDD
  *or* manual override from a Nat card tap). Every transition is logged. Nothing else is allowed
  to mutate grow state — that is the whole fix for slot corruption.
- **Positions outlive Grows.** History accrues per position too ("rack-bottom runs 2°F cold"),
  which is how the system learns the *micro*-microclimate.
- **Zones declare capabilities.** The engine adapts: a yard bed has no light switch, so a
  "light" phase becomes an observation-only phase with weather-fed GDD. Same recipe engine,
  zero forked logic.
- **Perennials fit.** The coffee cans are just Grows with `phases: milestone-based` and no
  harvest ETA measured in days. (See 05 — "Project Kegs of Duff.")

### Where it lives

- **Recipes + grow journal**: YAML/JSON files in this repo (`recipes/`, `grows/2026/…`).
  Git is the database of record — versioned, diffable, readable by Nat's cloud routines,
  survives any hub reflash. (Same philosophy as nat's `brain.md`.)
- **Hot state** (current phase, day counters): one small `state/grows.yaml`, written by exactly
  one process (the Brain / phase engine). Single-writer is the corruption cure.
- **Time-series** (temp/RH/VPD/power/coverage): a real TSDB (VictoriaMetrics or InfluxDB) +
  Grafana. HA's recorder keeps ~10 days for UI; long-term data does not live in SQLite.

## 2. Scaling scenarios (proof the model holds)

| Expansion | What it takes |
|---|---|
| **Tent #2** | New `zone: tent-2` config block + hardware BOM (~$120: ESPHome sensor node, 3 power-metering plugs, camera). Zero new logic. |
| **Yard beds** | Zone with `capabilities: [weather-fed, camera?]`. Open-Meteo supplies temp for GDD; a LoRa/Zigbee outdoor soil sensor (Ecowitt is the cheap path) adds moisture. Engine emits *tasks for Jeff* ("water the north bed", frost warning tonight — cover tomatoes) instead of actuating. Surfaces via nat's queue — infrastructure that already exists. |
| **Deck pots / office window** | Observation-only zones: weekly photo + note, GDD from weather or a $10 sensor. The grow journal and Claude vision reviews (05) do the rest. |
| **Someone else's tent** | Recipes are shareable files. Export `sunflower-v2.yaml`, they import it. Grow-along mode. |

The rule that keeps this honest: **the engine never says "tent", "top", or "sunflower" in
code.** If a crop name appears in an automation, the model has been violated.

## 3. The predictive layer

This is where the project stops being "smart plugs on schedules" and starts being agronomy.

### 3.1 GDD — Growing Degree Days (the metric you're not using yet)

Plants develop on **thermal time**, not calendar time. GDD per day ≈
`max(0, (Tmax+Tmin)/2 − Tbase)` (Tbase ≈ 40–50°F depending on crop). Accumulate it from the
tent sensor (or weather feed outdoors).

- Indoors at steady temp, GDD ≈ linear — but *not constant*: a cold-office week genuinely slows
  a grow, and GDD captures that where "day 8 of 11" lies.
- Outdoors, GDD is the difference between useful predictions and guessing.
- Each recipe carries `expected.gdd_f`. **Harvest ETA = date when accumulated GDD hits target**,
  continuously re-forecast from actuals + typical office temps ahead.

### 3.2 VPD — Vapor Pressure Deficit (control on the right variable)

Pros don't control raw humidity; they control VPD (kPa), computed from temp + RH — it's what
the plant actually experiences as drying pressure. Microgreens in the light phase want roughly
0.8–1.2 kPa; too low → mold pressure, too high → stress/wilting.

- Compute VPD as a derived sensor. Drive exhaust/circulation off **VPD bands per recipe phase**,
  not fixed RH thresholds.
- Add a second temp/RH sensor *outside* the tent: exhaust only helps if office air is drier —
  the inside/outside differential is the smartest $15 upgrade available.

### 3.3 Cameras become instruments, not just eyeballs

Daily scheduled snapshots per position (consistent time, lights forced on for the shot), then:

- **Canopy coverage %** — classic CV, no ML needed: HSV green-pixel segmentation over the tray
  region ≈ 30 lines of OpenCV. Microgreens on dark trays segment beautifully.
- **Growth curve fit** — coverage follows a logistic curve. Fit it daily; the inflection and
  plateau predict the harvest window *independently of GDD*. Two forecasters (thermal + visual)
  cross-checking each other, disagreement itself an alert ("GDD says day 10, camera says
  stalled — check water").
- **Height** — one camera top-down (coverage), one side-on with a ruler sticker in frame
  (height). You have exactly two tent cameras. This is why.
- **Timelapse** — every grow automatically becomes a video (05).
- **Claude-vision weekly check** — one photo packet per week to the API: "yellowing? legginess?
  mold fuzz? uneven germination?" Qualitative agronomist eyes, ~pennies per grow (see
  Fischoeder, 05).

### 3.4 Tray weight — the sensor nobody puts in a grow tent (~$10/tray)

Four half-bridge load cells + an HX711 + ESP32 = a scale under each tray. One sensor, three
signals:

1. **Water status** — daily sawtooth (weight drops as tray dries, jumps at watering). Auto-alert
   "rack-top is 200 g light — water it" via a Nat card. The single most useful daily automation
   this system could gain, since watering is the one thing still manual and forgettable.
2. **Biomass curve** — net weight gain tracks growth; third independent harvest forecaster.
3. **Yield at harvest** — auto-logged, closing the data loop with zero typing.

### 3.5 Mold risk index (the microgreens boss-fight)

A composite derived sensor: cumulative hours at RH > 70% + low circulation-fan duty + phase
(germination/blackout = danger zone) + optional camera fuzz check → 0–100 score. Above
threshold: boost exhaust, ping phone, flag the Claude-vision review. Losing a tray to mold
teaches this lesson once; the index makes it never happen twice.

### 3.6 The learning loop

Every completed Grow appends a row: recipe version, seed lot, density, GDD actual, mean VPD,
light-hours delivered (verified by power monitoring, not assumed), coverage curve params,
yield, quality. After ~15–20 grows:

- Regression: environment + recipe → yield. "Sunflower yields 12% better at 16 h light vs 14 h
  in *your* tent" — not internet lore, **your** data.
- Recipe auto-tuning proposals: the system opens a PR against `recipes/sunflower-v2.yaml` with
  evidence in the description. You merge or reject. GitOps agronomy.
- Anomaly detection: "exhaust duty cycle up 40% at same VPD target — clean the filter."

**The grow journal is the moat.** Hardware breaks, hubs get replaced, dashboards get rewritten —
the dataset compounds forever. Design every phase so it feeds the journal.

## 4. Prediction outputs, where you'll actually see them

- **Nat daily card**: "🌱 Sunflower (rack-top): day 8/11, harvest ETA Sat ±1d, coverage 71%,
  on-curve. Peas (rack-bottom): water today (−180 g)."
- **Harvest countdown** on the wall panel + calendar event auto-created at ETA −1 day
  ("Harvest window opens — eat the big salad").
- **Sow-date solver** (the sleeper feature): invert the forecast — "want sunflower ready for
  Sunday dinner on the 19th? Sow Thursday." Microgreens meal-planning, backwards from the plate.
