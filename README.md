# Sproutie Outie Control Center (v3)

A Cyberpunk-themed Home Assistant dashboard for a microgreen grow tent, featuring FLORA AI agent integration, Elasticsearch telemetry, automated Botany Logs, and a comprehensive Crop Cockpit.

## Overview

The Sproutie Outie Control Center is a high-tech monitoring and control system for a microgreen grow tent. Version 3 introduces a complete overhaul of the UI and backend logic for better production tracking.

### Key Features

- **Cyberpunk UI (v3)** - Blade Runner-inspired dashboard with neon cyan/pink/amber accents.
- **Crop Cockpit** - Detailed view for each active batch, tracking phases (Germination, Blackout, Growing, Harvest), history, and real-time snapshots.
- **Active Manifest** - High-level production summary of all active trays.
- **Automated Photography** - Periodic high-res snapshots using DSLR-style flash logic, with reactive dashboard updates.
- **Elasticsearch Integration** - Full telemetry, audit logging (every switch/mode change), and long-term history storage.
- **FLORA AI Assistant** - Friendly AI caretaker powered by Elastic Agent Builder (integration ready).
- **Categorized Timeline** - Intelligent history view separating Watering, Phase Changes, Notes, and System Logs.

## Architecture

```
┌─────────────────┐
│  HA Dashboard   │
│  (Cyberpunk v3) │
└────────┬────────┘
         │
    ┌────┴────────┐      ┌───────────────┐
    │ Home Asst   │◄────►│  Elasticsearch│
    │  Core       │      │  (Telemetry)  │
    └────┬────────┘      └───────────────┘
         │
    ┌────┴────┐
    │   MCP   │
    │ Server  │
    └─────────┘
```

## Installation

### Prerequisites

1. **Home Assistant** (Container or OS)
   - HACS installed
   - Required custom cards:
     - `custom:button-card`
     - `card-mod`
     - `custom:layout-card`
     - `custom:mini-graph-card`
     - `custom:mushroom-card`
     - `custom:apexcharts-card`
     - `custom:auto-entities`
     - `custom:stack-in-card`

2. **Elastic Cloud**
   - Elasticsearch cluster
   - API Key with write access to `sproutie-*` indices

### Setup Steps

1. **Copy package files to Home Assistant:**
   ```bash
   cp -r packages/sproutie_outie /config/packages/
   ```

2. **Add to `configuration.yaml`:**
   ```yaml
   homeassistant:
     packages: !include_dir_named packages
   
   shell_command:
     copy_snapshot: 'cp "{{ source }}" "{{ target }}"'
   ```

3. **Configure Secrets:**
   Add these to your `secrets.yaml`:
   ```yaml
   es_url_bulk: "https://.../sproutie-sensors-*/_bulk"
   es_url_botany: "https://.../sproutie-botany-logs/_doc"
   es_api_key: "..."
   elastic_url_doc: "https://.../sproutie-crops/_doc"
   elastic_api_key_header: "ApiKey ..."
   ```

4. **Configure REST commands:**
   - Copy `rest_commands.yaml` content to your HA config.

5. **Deploy Dashboard:**
   - Copy `ui-lovelace-v3.yaml` to `/config/ui-lovelace-v3.yaml`.
   - Add dashboard resource references to your configuration (see `configuration.yaml` example).

## Usage

### Command Center (Main View)
- **Vitals**: Real-time graphs for Temp, Humidity, and VPD (Vapor Pressure Deficit).
- **Active Manifest**: List of all currently growing crops with countdowns to harvest.
- **Station Log**: Recent system activity.
- **Operations**: Quick toggles for lights, fans, and system modes (Production/Inspection).

### Crop Cockpit (Detail View)
- Click any crop in the Active Manifest to enter the Cockpit.
- **Phase Control**: Advance crops through stages (Germination -> Blackout -> Growing -> Harvest).
- **Actions**: Log Water, Add Notes, Harvest.
- **History**: Full categorized timeline of the batch's life.
- **Snapshot**: Latest photo of the specific tray location (Top/Bottom rack).

### Photography System
- **Schedule**: Configurable interval (default 60 mins).
- **Process**: 
  1. Turn on Flash (Smart Plug)
  2. Wait 5s for warmup
  3. Take Snapshots (Top & Bottom cams)
  4. Copy to "latest" reference for Dashboard
  5. Push metadata to Elasticsearch
  6. Turn off Flash

## Configuration

### Key Entities

**Sensors:**
- `sensor.sproutie_outie_internal_temp`
- `sensor.sproutie_outie_internal_humidity`

**Switches:**
- `switch.camera_flash` (Critical for photography)
- `switch.exhaust_fan`
- `switch.top_shelf_lights`
- `switch.bottom_shelf_lights`

**Helpers (Input Text):**
- `input_text.slot_a1_data` through `b8_data`: Stores JSON state for each tray slot.
- `input_text.crop_library_json`: Database of crop types and growth parameters.

## File Structure

```
sproutie-outie-control/
├── packages/
│   └── sproutie_outie/
│       ├── scripts.yaml            # Core logic (Photography, Logging, Planting)
│       ├── automations.yaml        # Schedules, Safety Valves, Auditing
│       ├── helpers.yaml            # Input definitions (Slots, Modes)
│       ├── sensors.yaml            # ES History Sensor
│       ├── auditing.yaml           # System state change logging
│       └── views/                  # (Legacy/Partial views)
├── ui-lovelace-v3.yaml             # MAIN V3 DASHBOARD definition
├── rest_commands.yaml              # ES API definitions
├── elasticsearch/                  # ES configurations
├── gcp_bridge/                     # Google Cloud Platform integration
└── www/                            # Custom icons and assets
```

## Troubleshooting

### Dashboard Photos Not Updating
- Verify `shell_command.copy_snapshot` is defined in `configuration.yaml`.
- Ensure `script.sequence_crop_photography` is running without errors.
- Check permissions on `/config/www/snapshots/`.

### "Unknown" Batch ID
- If a batch shows as "Unknown", run the `sproutie_repair_sunflower_full` script (or similar) to restore slot data integrity.
- Ensure `input_text.selected_batch` is set correctly when navigating.

## License

See LICENSE file.

## Credits

- Built for the Sproutie Outie Microfarm.
- Powered by Home Assistant + Elastic Stack.
